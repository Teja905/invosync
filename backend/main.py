"""FastAPI backend — production-grade invoice extraction, validation, and Tally XML generation."""

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from bson.objectid import ObjectId

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import database as db
from extractors import ExtractionPipeline
from xml_generator import TallyXmlGenerator
from validation_layer import validate_invoice_for_xml, validate_xml_output
from company_config import CompanyConfig
from ledger_mapping import LedgerMappingEngine
from rules_engine import RulesEngine, LedgerRule, MatchType
from context_classifier import ContextClassifier
from gstr_preview import generate_gstr_preview
from xml_preflight import validate_xml_preflight
from ledger_learner import LedgerLearner
from gst_engine import determine_gst_type, compute_tax_from_items, validate_gstin
from voucher_classifier import classify_voucher_type, classify_service_vs_goods
from ocr_postproc import fix_gstin, fix_date, fix_amount, clean_extracted_invoice_payload
from core.logging import get_logger
from core.debug import time_it
from audit_log import audit as audit_logger
from crypto_utils import encrypt, decrypt
from schemas import (
    StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry,
    DocumentClass, ALLOWED_GST_SLABS, GST_STATE_CODES,
)
import validation as val
from validators.pipeline import ValidationPipeline
_AUTH_ENABLED = False


load_dotenv()

logger = get_logger(__name__)

# Global ledger learner — self-improving, user-scoped correction engine
_learner = LedgerLearner(db=db)

# Global validation pipeline — runs all validators on every generation
_validation_pipeline = ValidationPipeline()


class ClientCreate(BaseModel):
    company_name: str
    client_name: str
    gstin: str = ""


class ClientUpdate(BaseModel):
    company_name: str = ""
    client_name: str = ""
    gstin: str = ""


def _is_valid_image(data: bytes) -> bool:
    if data[:4] == b"%PDF":
        return True
    return any([
        data[:2] == b"\xff\xd8",
        data[:4] == b"\x89PNG",
        data[:4] in (b"GIF8",),
        data[:4] == b"RIFF",
        data[:2] == b"\x42\x4d",
        data[:4] == b"\x00\x00\x00\x0c",
        data[:4] == b"\xff\x4f\xff\x51",
    ])


_extraction_pipeline = ExtractionPipeline()
_company_config = CompanyConfig()
_xml_generator = TallyXmlGenerator(_company_config)
_ledger_engine = LedgerMappingEngine(_company_config)

# Async extraction queue for multi-user concurrency
MAX_CONCURRENT_EXTRACTIONS = 3
extraction_queue = asyncio.Queue()
processing_tasks: dict[str, tuple[str, float]] = {}  # inv_id -> (state, timestamp)

_TASK_TTL_SECONDS = 3600  # 1 hour

app = FastAPI(title="Invoice Extractor & XML Generator")

# -- Rate limiting --
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS if "*" not in _ALLOWED_ORIGINS else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def http_exception_and_timing_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        logger.info("%s %s \u2192 %s (%.0fms)",
                    request.method, request.url.path, response.status_code, process_time * 1000)
        return response
    except RequestValidationError as val_err:
        process_time = time.perf_counter() - start_time
        logger.error("Schema validation error on %s (%dms): %s",
                     request.url.path, process_time * 1000, val_err.errors())
        return JSONResponse(
            status_code=422,
            content={
                "error": "DATA_SCHEMA_MISMATCH",
                "message": "The invoice structure does not conform to compliance models.",
                "details": val_err.errors(),
            },
        )
    except ValueError as val_err:
        logger.error("Compliance validation error on %s: %s", request.url.path, val_err)
        return JSONResponse(
            status_code=400,
            content={
                "error": "ACCOUNTING_VALIDATION_FAILED",
                "message": str(val_err),
            },
        )
    except Exception as exc:
        process_time = time.perf_counter() - start_time
        logger.critical("Unhandled exception on %s %s (%dms): %s\n%s",
                        request.method, request.url.path, process_time * 1000, exc,
                        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SYSTEM_CRASH",
                "message": "An unexpected critical exception occurred.",
            },
        )



@app.post("/api/auth/login")
async def demo_login(body: dict):
    return {"token": "demo-token", "refresh_token": "demo-refresh", "email": body.get("email", "demo@local")}


val.COMPANY_STATE_CODE = _company_config.state_code

_COMPANY_CONFIG_FIELDS = [
    "company_name", "company_gstin", "company_state_code",
    "purchase_ledger", "sales_ledger", "bank_ledger",
    "tds_ledger", "round_off_ledger", "freight_ledger", "suspense_ledger",
    "sundry_creditors_group", "sundry_debtors_group",
    "purchase_accounts_group", "sales_accounts_group",
    "bank_accounts_group", "current_liabilities_group",
    "duties_taxes_group",
    "correction_memory",
    "masters_created",
    "active_company",
    "active_company_id",
    "tally_password",
]


def _user_config_from_current(current_user: dict) -> dict:
    """Extract company config fields from current_user (enriched from DB)."""
    cfg = {}
    encrypted_fields = {"tally_password"}
    for field in _COMPANY_CONFIG_FIELDS:
        val = current_user.get(field)
        if val:
            if field in encrypted_fields:
                val = decrypt(val)
            cfg[field] = val.strip() if isinstance(val, str) else val
    return cfg


def _make_xml_generator(user_cfg: dict) -> tuple[TallyXmlGenerator, CompanyConfig, str]:
    """Create a per-request XML generator with user config overrides.
    Returns (generator, config, active_company).
    Automatically sets reuse_masters=True if masters already created for this company."""
    active_company = ""
    masters_created = False
    if user_cfg:
        masters_created = bool(user_cfg.pop("masters_created", False))
        active_company = user_cfg.pop("active_company", "") or ""
    cfg = _company_config
    if user_cfg:
        cfg = CompanyConfig(user_config=user_cfg)
    gen = TallyXmlGenerator(cfg)
    gen.masters_created = masters_created
    return gen, cfg, active_company


def _run_validation_pipeline(standard: StandardizedInvoice, xml_str: str) -> dict:
    """Run the full validation pipeline and return a validation report dict.

    Called automatically on every XML generation — no user action needed.
    """
    try:
        pipeline = ValidationPipeline()
        report = pipeline.run(standard, xml_str)
        return report.to_dict()
    except Exception as e:
        logger.error("VALIDATION PIPELINE ERROR: %s", e)
        return {
            "scores": {"total": 0},
            "passed": False,
            "ready_for_tally": False,
            "errors": [f"Pipeline error: {str(e)}"],
            "warnings": [],
            "error_count": 1,
            "warning_count": 0,
        }


# ---------------------------------------------------------------------------
# Auth disabled: return default config from env vars (+ per-user in-memory overrides)
# ---------------------------------------------------------------------------
_config_overrides: dict[str, dict] = {}  # keyed by user_id — no cross-user bleed


async def _default_user() -> dict:
    """Return default user config from env vars + any in-memory overrides (no auth required)."""
    base = {
        "email": "default@local",
        "user_id": "default",
        "role": "admin",
        "company_name": os.getenv("COMPANY_NAME", ""),
        "company_gstin": os.getenv("COMPANY_GSTIN", ""),
        "company_state_code": os.getenv("COMPANY_STATE_CODE", ""),
        "purchase_ledger": os.getenv("PURCHASE_LEDGER", "Purchase"),
        "sales_ledger": os.getenv("SALES_LEDGER", "Sales"),
        "bank_ledger": os.getenv("BANK_LEDGER", "Bank"),
        "tds_ledger": os.getenv("TDS_PAYABLE_LEDGER", "TDS Payable"),
        "round_off_ledger": os.getenv("ROUND_OFF_LEDGER", "Round Off"),
        "freight_ledger": os.getenv("FREIGHT_LEDGER", "Freight Expenses"),
        "suspense_ledger": os.getenv("SUSPENSE_LEDGER", "Suspense"),
        "sundry_creditors_group": os.getenv("SUNDRY_CREDITORS_GROUP", "Sundry Creditors"),
        "sundry_debtors_group": os.getenv("SUNDRY_DEBTORS_GROUP", "Sundry Debtors"),
        "purchase_accounts_group": os.getenv("PURCHASE_ACCOUNTS_GROUP", "Purchase Accounts"),
        "sales_accounts_group": os.getenv("SALES_ACCOUNTS_GROUP", "Sales Accounts"),
        "bank_accounts_group": os.getenv("BANK_ACCOUNTS_GROUP", "Bank Accounts"),
        "current_liabilities_group": os.getenv("CURRENT_LIABILITIES_GROUP", "Current Liabilities"),
        "duties_taxes_group": os.getenv("DUTIES_TAXES_GROUP", "Duties & Taxes"),
        "correction_memory": {},
        "tally_password": os.getenv("TALLY_PASSWORD", ""),
    }
    user_id = "default"
    base.update({k: v for k, v in _config_overrides.get(user_id, {}).items() if v})
    # Load active company from MongoDB if available
    if db.organizations is not None:
        try:
            org = await db.organizations.find_one({"org_id": user_id})
            if org:
                if org.get("active_company"):
                    base["active_company"] = org["active_company"]
                if org.get("active_company_id"):
                    base["active_company_id"] = org["active_company_id"]
        except Exception:
            pass
    return base


async def get_authenticated_user() -> dict:
    """Demo mode: return default user without auth."""
    return await _default_user()


class LineItemModel(BaseModel):
    description: str
    quantity: float
    rate: float
    taxable_value: float
    tax_rate: float
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None


class InvoiceDataLegacy(BaseModel):
    gstin: str = ""
    invoice_number: str = ""
    date: str = ""
    total_amount: float = 0
    vendor_name: str = ""
    vendor_address: Optional[str] = None
    buyer_gstin: str = ""
    buyer_name: str = ""
    voucher_type: str = ""
    line_items: list[LineItemModel] = []
    confidence: Optional[float] = None
    client_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

async def _run_queued_extraction(inv_id, tmp_path, file_content_type, user_id, client_id, company_gstin, user_config, semaphore):
    """Process a single queued extraction under semaphore."""
    inv_key = str(inv_id)
    async with semaphore:
        try:
            processing_tasks[inv_key] = ("processing", time.monotonic())
            image_bytes = tmp_path.read_bytes()
            file_hash = db.calculate_file_hash(image_bytes)

            data = await _extraction_pipeline.extract(image_bytes, file_content_type, company_gstin=company_gstin)
            data = clean_extracted_invoice_payload(data)

            usr_cfg = CompanyConfig(user_config=user_config) if user_config else _company_config
            standard = _legacy_to_standard(data, data.get("_provider", ""), data.get("_model", ""), cfg=usr_cfg)

            existing_list = []
            if db.invoices is not None:
                try:
                    existing_list = await db.list_invoices(user_id=user_id, client_id=client_id)
                except Exception:
                    pass

            validation = val.run_full_validation(data, existing_list)
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            active_company_id = (user_config or {}).get("active_company_id") if isinstance(user_config, dict) else None
            inv_display_id, _ = await db.insert_invoice(
                user_id=user_id, client_id=client_id,
                extracted=data, validation=validation,
                file_hash=file_hash, image_data=image_b64,
                company_id=active_company_id,
            )
            if validation.get("decision") == "high" and db.invoices is not None:
                await db.update_invoice_status(inv_display_id, "validated")

            await db.invoices.update_one(
                {"_id": inv_id},
                {"$set": {"status": "draft", "display_id": inv_display_id, "extracted": data, "validation": validation, "image_data": image_b64}}
            )
            processing_tasks[inv_key] = ("completed", time.monotonic())
            user_id_for_audit = user_id or "unknown"
            audit_logger.log_invoice_action("extract", inv_display_id, user_id_for_audit, f"status={validation.get('decision', 'unknown')}")
        except Exception as e:
            logger.error("QUEUE WORKER: invoice %s failed: %s", inv_id, e)
            processing_tasks[inv_key] = (f"failed: {e}", time.monotonic())
            if db.invoices is not None:
                await db.invoices.update_one(
                    {"_id": inv_id},
                    {"$set": {"status": "extraction_failed", "sync_error": str(e)}}
                )
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            extraction_queue.task_done()


async def _cleanup_processing_tasks():
    """Periodically evict stale entries from processing_tasks to prevent unbounded growth."""
    while True:
        await asyncio.sleep(600)  # run every 10 minutes
        cutoff = time.monotonic() - _TASK_TTL_SECONDS
        stale = [k for k, (_, ts) in list(processing_tasks.items()) if ts < cutoff]
        for k in stale:
            processing_tasks.pop(k, None)
        if stale:
            logger.info("Evicted %d stale processing_tasks entries", len(stale))


async def _extraction_queue_worker():
    """Background worker: processes queued extractions with concurrency throttle."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    while True:
        args = await extraction_queue.get()
        asyncio.create_task(_run_queued_extraction(*args, semaphore))


@app.on_event("startup")
async def startup():
    try:
        await db.connect()
    except Exception as e:
        logger.warning("MongoDB connection failed (%s). Running without database.", e)
        logger.warning("Invoice data will NOT be persisted across restarts.")
    
    has_openrouter = bool(os.getenv("OPENROUTER_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    logger.info("API keys: OpenRouter=%s Gemini=%s (using fallback=%s)",
                "YES" if has_openrouter else "NO",
                "YES" if has_gemini else "NO",
                "NO" if has_gemini else "YES")
    # Load correction memory into LedgerLearner
    try:
        await _learner.load("default@local")
        logger.info("LedgerLearner loaded %d corrections", _learner.stats()["corrections_count"])
    except Exception as e:
        logger.warning("LedgerLearner load failed: %s", e)
    # Auto-migrate env var config to companies collection
    try:
        cid = await db.auto_migrate_env_config("default")
        if cid:
            logger.info("Auto-migrated env config to company_id=%d", cid)
    except Exception as e:
        logger.warning("Company auto-migrate failed: %s", e)
    # Launch background queue worker and task cleanup
    asyncio.create_task(_extraction_queue_worker())
    asyncio.create_task(_cleanup_processing_tasks())
    logger.info("Extraction queue worker started (max %s concurrent)", MAX_CONCURRENT_EXTRACTIONS)


@app.on_event("shutdown")
async def shutdown():
    await db.disconnect()


# ---------------------------------------------------------------------------
# Helper: convert legacy data to StandardizedInvoice
# ---------------------------------------------------------------------------

def _legacy_to_standard(data: dict, provider: str = "", model: str = "", cfg: Optional[CompanyConfig] = None) -> StandardizedInvoice:
    cfg = cfg or _company_config
    gstin = fix_gstin(data.get("gstin", ""))
    company_state = cfg.state_code
    company_gstin = cfg.company_gstin
    buyer_gstin = data.get("buyer_gstin") or company_gstin or ""
    gst_type, is_interstate = determine_gst_type(gstin, buyer_gstin, company_state)

    line_items = []
    for item in data.get("line_items", []):
        desc = item.get("description", "")
        is_svc = classify_service_vs_goods([{"description": desc}])
        line_items.append(LineItem(
            description=desc,
            quantity=float(item.get("quantity", 1) or 1),
            rate=float(item.get("rate", 0) or 0),
            taxable_value=float(item.get("taxable_value", 0) or 0),
            tax_rate=float(item.get("tax_rate", 0) or 0),
            is_service=is_svc,
        ))

    is_rcm = data.get("is_rcm", False) or data.get("reverse_charge", False)
    tax_config = dict(cfg.gst_ledger_mappings)
    tax_config["company_state_code"] = cfg.state_code
    taxes = compute_tax_from_items(
        [item.model_dump() for item in line_items],
        gst_type,
        tax_config,
        is_input=True,
        is_rcm=is_rcm,
    )

    total_taxable = sum(li.taxable_value for li in line_items)
    total_tax = sum(t.amount for t in taxes)

    voucher_type_str = data.get("voucher_type", "")
    if voucher_type_str:
        try:
            voucher_type = VoucherType(voucher_type_str)
        except ValueError:
            voucher_type = classify_voucher_type(data, cfg.state_code, company_gstin=company_gstin)[0]
    else:
        voucher_type = classify_voucher_type(data, cfg.state_code, company_gstin=company_gstin)[0]
    logger.info("VOUCHER CLASSIFICATION (legacy): user_voucher_type=%r > final_voucher_type=%s",
                voucher_type_str, voucher_type.value)

    return StandardizedInvoice(
        invoice_number=data.get("invoice_number", ""),
        invoice_date=fix_date(data.get("date", "")),
        vendor_name=data.get("vendor_name", ""),
        vendor_gstin=gstin,
        vendor_address=data.get("vendor_address", "") or "",
        buyer_name=data.get("buyer_name", "") or "",
        buyer_gstin=data.get("buyer_gstin") or None,
        total_taxable_value=total_taxable or data.get("total_taxable_value", total_taxable),
        total_tax=total_tax or data.get("total_tax", total_tax),
        total_amount=float(data.get("total_amount", 0) or 0),
        line_items=line_items,
        taxes=taxes,
        gst_type=gst_type,
        is_rcm=is_rcm,
        is_interstate=is_interstate,
        is_service=classify_service_vs_goods([li.model_dump() for li in line_items]),
        confidence=float(data.get("confidence", 0) or 0),
        voucher_type=voucher_type,
        auto_create_stock_items=bool(data.get("auto_create_stock_items", False)),
        _provider=provider,
        _model=model,
    )


async def _check_duplicate(vendor: str, inv_no: str, total: float, user_id: str = None) -> Optional[str]:
    if db.invoices is None or not vendor or not inv_no:
        return None
    try:
        dup = await db.find_duplicate(vendor, inv_no, user_id)
        if not dup:
            return None
        existing_amt = dup.get("extracted", {}).get("total_amount")
        if existing_amt is not None and abs(float(existing_amt) - total) < 2:
            return f"Duplicate: same invoice from '{vendor}' #{inv_no} already exists (ID: {dup.get('display_id')})"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------

@app.post("/clients")
async def create_client(data: ClientCreate, current_user: dict = Depends(get_authenticated_user)):
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.create_client(
        user_id=current_user.get("user_id", current_user.get("email", "")),
        company_name=data.company_name,
        client_name=data.client_name,
        gstin=data.gstin,
    )
    return {
        "client_id": client["client_id"],
        "company_name": client["company_name"],
        "client_name": client["client_name"],
        "gstin": client["gstin"],
        "created_at": client["created_at"],
    }


@app.get("/clients")
async def list_clients(current_user: dict = Depends(get_authenticated_user)):
    if db.clients is None:
        return []
    user_id = current_user.get("user_id", current_user.get("email", ""))
    records = await db.list_clients(user_id)
    return [
        {
            "client_id": c["client_id"],
            "company_name": c["company_name"],
            "client_name": c["client_name"],
            "gstin": c.get("gstin", ""),
            "created_at": c["created_at"],
            "invoice_count": c.get("invoice_count", 0),
        }
        for c in records
    ]


@app.get("/clients/{client_id}")
async def get_client(client_id: int, current_user: dict = Depends(get_authenticated_user)):
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if client.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    return {
        "client_id": client["client_id"],
        "company_name": client["company_name"],
        "client_name": client["client_name"],
        "gstin": client.get("gstin", ""),
        "created_at": client["created_at"],
        "invoice_count": client.get("invoice_count", 0),
    }


@app.put("/clients/{client_id}")
async def update_client(client_id: int, data: ClientUpdate, current_user: dict = Depends(get_authenticated_user)):
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if client.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.update_client(client_id, data.model_dump(exclude_unset=True))
    return {"ok": True}


@app.delete("/clients/{client_id}")
async def delete_client(client_id: int, current_user: dict = Depends(get_authenticated_user)):
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if client.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.delete_client(client_id)
    return {"ok": True}


# ---- Correction Memory ----

@app.get("/corrections")
async def list_corrections(current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    memory = _learner.get_corrections()
    if not memory:
        memory = await db.get_correction_memory(email)
    return {"corrections": memory, "count": len(memory)}


class CorrectionSave(BaseModel):
    description: str
    ledger: str


class RuleCreate(BaseModel):
    pattern: str
    target_ledger: str
    match_type: str = "keyword"
    confidence: float = 0.85
    category: str = "expense"


class RuleUpdate(BaseModel):
    pattern: str = ""
    target_ledger: str = ""
    match_type: str = ""
    confidence: float = 0.0
    is_active: bool = True
    category: str = ""


# Module-level rules engine for API access
_api_rules_engine = RulesEngine()
_api_context_classifier = ContextClassifier(rules_engine=_api_rules_engine)


@app.get("/api/v3/ledger-rules")
async def list_rules(category: str = "", current_user: dict = Depends(get_authenticated_user)):
    """List all active ledger mapping rules. Optionally filter by category."""
    rules = _api_rules_engine.get_rules(category if category else None)
    return {
        "count": len(rules),
        "rules": [r.to_dict() for r in rules],
    }


@app.post("/api/v3/ledger-rules")
async def create_rule(rule: RuleCreate, current_user: dict = Depends(get_authenticated_user)):
    """Create a new ledger mapping rule."""
    mt = MatchType(rule.match_type) if rule.match_type else MatchType.KEYWORD
    new_rule = LedgerRule(
        pattern=rule.pattern,
        target_ledger=rule.target_ledger,
        match_type=mt,
        confidence=rule.confidence,
        category=rule.category,
    )
    _api_rules_engine.add_rule(new_rule)
    return {"ok": True, "rule": new_rule.to_dict()}


@app.put("/api/v3/ledger-rules")
async def update_rule(old_pattern: str, old_target: str, rule: RuleUpdate, current_user: dict = Depends(get_authenticated_user)):
    """Update an existing ledger rule."""
    mt = MatchType(rule.match_type) if rule.match_type else MatchType.KEYWORD
    new_rule = LedgerRule(
        pattern=rule.pattern or old_pattern,
        target_ledger=rule.target_ledger or old_target,
        match_type=mt,
        confidence=rule.confidence or 0.85,
        is_active=rule.is_active,
        category=rule.category or "expense",
    )
    ok = _api_rules_engine.update_rule(old_pattern, old_target, new_rule)
    if not ok:
        raise HTTPException(404, f"Rule '{old_pattern}' → '{old_target}' not found")
    return {"ok": True, "rule": new_rule.to_dict()}


@app.delete("/api/v3/ledger-rules")
async def delete_rule(pattern: str, target_ledger: str, current_user: dict = Depends(get_authenticated_user)):
    """Delete a ledger mapping rule."""
    ok = _api_rules_engine.remove_rule(pattern, target_ledger)
    if not ok:
        raise HTTPException(404, f"Rule '{pattern}' → '{target_ledger}' not found")
    return {"ok": True}


@app.post("/api/v3/ledger-rules/suggest")
async def suggest_rules(description: str, current_user: dict = Depends(get_authenticated_user)):
    """Suggest ledgers for an unmapped description. Used when AI can't classify."""
    suggestions = _api_rules_engine.suggest_ledgers(description, top_n=5)
    return {
        "description": description,
        "suggestions": suggestions,
        "count": len(suggestions),
    }


@app.post("/api/v3/ledger-rules/teach")
async def teach_rule(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    """Add a user correction as a high-confidence rule."""
    rule = LedgerRule(
        pattern=body.description.lower().strip(),
        target_ledger=body.ledger,
        match_type=MatchType.KEYWORD,
        confidence=1.0,
    )
    _api_rules_engine.add_rule(rule)
    _api_rules_engine.add_correction(body.description, body.ledger)
    return {"ok": True, "rule": rule.to_dict()}


@app.get("/api/v3/ledger-rules/match")
async def match_ledger(description: str, current_user: dict = Depends(get_authenticated_user)):
    """Match a description to a ledger with confidence score.
    Used by frontend to show confidence during review."""
    result = _api_rules_engine.match(description)
    return result.to_dict()


@app.post("/api/v3/ledger/context-suggest")
async def context_suggest(body: dict, current_user: dict = Depends(get_authenticated_user)):
    """Context-aware ledger suggestion (capital vs revenue).

    Body: {"description": "...", "amount": 50000}
    Returns ledger suggestion with context_type, confidence, and explanation.
    """
    description = str(body.get("description", "")).strip()
    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0
    result = _api_context_classifier.classify(description, amount=amount)
    return result.to_dict()


@app.get("/api/v3/invoices/{invoice_id}/gstr-preview")
async def get_gstr_preview(invoice_id: str, current_user: dict = Depends(get_authenticated_user)):
    """Generate GSTR-1 and GSTR-3B preview for an invoice."""
    invoice = await db.invoices.find_one({"_id": ObjectId(invoice_id)})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv = StandardizedInvoice(**invoice.get("data", {}))
    preview = generate_gstr_preview(inv)
    return preview


@app.post("/api/v3/xml/preflight")
async def preflight_xml(body: dict, current_user: dict = Depends(get_authenticated_user)):
    """Validate generated XML for common Tally import issues before export."""
    xml = body.get("xml", "")
    if not xml:
        raise HTTPException(status_code=422, detail="xml field is required")
    report = validate_xml_preflight(xml)
    return report


@app.post("/corrections")
async def save_correction(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    await _learner.learn(body.description, body.ledger, email=email)
    audit_logger.log_correction(email, body.description, body.ledger, "manual")
    return {"ok": True, "saved": f"{body.description.lower().strip()} → {body.ledger}"}


@app.post("/corrections/forget")
async def forget_correction(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    await _learner.forget(body.description, email=email)
    audit_logger.log_correction(email, body.description, "", "forgot")
    return {"ok": True, "forgotten": body.description}


@app.delete("/corrections")
async def clear_corrections(current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    await db.users.update_one({"email": email.lower().strip()}, {"$set": {"correction_memory": {}}})
    _learner._corrections.clear()
    return {"ok": True, "cleared": True}


@app.get("/corrections/stats")
async def correction_stats(current_user: dict = Depends(get_authenticated_user)):
    """Returns learning statistics for the frontend dashboard."""
    return _learner.stats()


# ---------------------------------------------------------------------------
# Companies (multi-company CRUD)
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    company_name: str
    company_gstin: str = ""
    state_code: str = ""
    purchase_ledger: str = "Purchase"
    sales_ledger: str = "Sales"
    bank_ledger: str = "Bank"


class CompanyUpdate(BaseModel):
    company_name: str = ""
    company_gstin: str = ""
    state_code: str = ""
    purchase_ledger: str = ""
    sales_ledger: str = ""
    bank_ledger: str = ""
    active: bool = True


@app.get("/api/v3/companies")
async def list_companies(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    comps = await db.list_companies(user_id)
    result = []
    for c in comps:
        result.append({
            "company_id": c["company_id"],
            "company_name": c.get("company_name", ""),
            "company_gstin": c.get("company_gstin", ""),
            "state_code": c.get("state_code", ""),
            "purchase_ledger": c.get("purchase_ledger", "Purchase"),
            "sales_ledger": c.get("sales_ledger", "Sales"),
            "bank_ledger": c.get("bank_ledger", "Bank"),
            "created_at": c.get("created_at", ""),
        })
    return {"companies": result, "count": len(result)}


@app.post("/api/v3/companies")
async def create_company(body: CompanyCreate, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if not body.company_name:
        raise HTTPException(400, "company_name is required")
    doc = await db.create_company(
        user_id=user_id,
        name=body.company_name,
        gstin=body.company_gstin,
        state_code=body.state_code,
        purchase_ledger=body.purchase_ledger,
        sales_ledger=body.sales_ledger,
        bank_ledger=body.bank_ledger,
    )
    return {"company_id": doc["company_id"], "company_name": doc["company_name"]}


@app.put("/api/v3/companies/{company_id}")
async def update_company(company_id: int, body: CompanyUpdate, current_user: dict = Depends(get_authenticated_user)):
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    updates = {k: v for k, v in body.model_dump().items() if v}
    await db.update_company(company_id, updates)
    return {"ok": True, "company_id": company_id}


@app.delete("/api/v3/companies/{company_id}")
async def delete_company(company_id: int, current_user: dict = Depends(get_authenticated_user)):
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    await db.delete_company(company_id)
    return {"ok": True, "deleted": company_id}


@app.post("/api/v3/companies/{company_id}/switch")
async def switch_company(company_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Switch the active company context for the current user."""
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"active_company_id": company_id, "active_company": existing.get("company_name", "")}},
            upsert=True,
        )
    return {
        "ok": True,
        "company_id": company_id,
        "company_name": existing.get("company_name", ""),
        "company_gstin": existing.get("company_gstin", ""),
        "state_code": existing.get("state_code", ""),
    }


@app.get("/api/v3/companies/{company_id}/analytics")
async def company_analytics(company_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Return invoice analytics for a given company: status breakdown, monthly trend, top clients."""
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    analytics = await db.get_company_analytics(company_id)
    return {"ok": True, "company_id": company_id, "analytics": analytics}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/extract")
@time_it
@limiter.limit("15/minute")
async def extract(
    request: Request,
    file: UploadFile = File(...),
    client_id: int = Query(..., description="Client ID the invoice belongs to"),
    current_user: dict = Depends(get_authenticated_user),
):
    if db.clients is not None:
        client = await db.get_client(client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if client.get("user_id") != user_id:
            raise HTTPException(403, "Access denied")

    _ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if not file.content_type or file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, "Only JPG, PNG, WebP, and PDF files are supported")

    payload = await file.read()
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large. Maximum 10MB allowed.")

    if file.content_type != "application/pdf" and _HAS_PIL:
        try:
            import io
            Image.open(io.BytesIO(payload)).verify()
        except Exception:
            raise HTTPException(400, "File appears corrupted or is not a valid image.")

    file.file.seek(0)  # rewind for downstream processing

    user_config = _user_config_from_current(current_user)
    company_gstin = user_config.get("company_gstin") or os.getenv("COMPANY_GSTIN", "")
    if not company_gstin:
        return JSONResponse(
            status_code=400,
            content={
                "error": "company_profile_required",
                "message": "Set up your company profile first (Company Name, GSTIN, State) in Settings before processing invoices.",
            },
        )

    MAX_FILE_SIZE = 15 * 1024 * 1024
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "upload").suffix) as tmp:
            tmp_path = Path(tmp.name)
            bytes_written = 0
            magic_checked = False
            while chunk := await file.read(64 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_FILE_SIZE:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "PAYLOAD_TOO_LARGE", "message": "Invoice file must be under 15MB."},
                    )
                if not magic_checked:
                    if not _is_valid_image(chunk[:16]):
                        raise HTTPException(400, "File content is not a valid image or PDF (magic bytes mismatch)")
                    magic_checked = True
                tmp.write(chunk)
            tmp.flush()

        image_bytes = tmp_path.read_bytes()
        file_hash = hashlib.sha256(image_bytes).hexdigest()
        user_id = current_user.get("user_id", current_user.get("email", ""))

        # Dedup check before queueing
        if db.invoices is not None:
            existing_hash = await db.find_by_file_hash(file_hash, user_id)
            if existing_hash:
                if tmp_path.exists():
                    tmp_path.unlink()
                return JSONResponse(
                    status_code=409,
                    content={
                        "duplicate": True,
                        "existing_id": existing_hash.get("display_id"),
                        "message": "This exact file has already been processed.",
                    },
                )

        # If no database -> fall back to synchronous extraction
        if db.invoices is None:
            data = await _extraction_pipeline.extract(image_bytes, file.content_type, company_gstin=company_gstin)
            data = clean_extracted_invoice_payload(data)
            return {**data, "client_id": client_id, "_fallback": True}

        # Insert placeholder invoice row immediately
        now_utc = datetime.now(timezone.utc).isoformat()
        placeholder = {
            "user_id": user_id,
            "client_id": client_id,
            "file_hash": file_hash,
            "filename": file.filename or "upload",
            "status": "processing_queued",
            "created_at": now_utc,
        }
        insert_result = await db.invoices.insert_one(placeholder)
        invoice_obj_id = str(insert_result.inserted_id)

        # Queue the extraction for background processing
        await extraction_queue.put((
            ObjectId(invoice_obj_id),  # inv_id
            tmp_path,                   # tmp_path (worker cleans up)
            file.content_type,          # file_content_type
            user_id,
            client_id,
            company_gstin,
            user_config,
        ))

        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "invoice_id": invoice_obj_id,
                "message": "File received. Extraction is processing in the background.",
                "client_id": client_id,
            },
        )
    except HTTPException:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise
    except Exception as e:
        logger.error("EXTRACT QUEUE ERROR: %s", e)
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise HTTPException(502, f"Extraction failed: {str(e)}")


@app.get("/extract/status/{invoice_id}")
async def extract_status(invoice_id: str, current_user: dict = Depends(get_authenticated_user)):
    """Polling endpoint for frontend to check extraction progress."""
    try:
        obj_id = ObjectId(invoice_id)
    except Exception:
        raise HTTPException(400, "Invalid invoice ID format")

    user_id = current_user.get("user_id", current_user.get("email", ""))

    if db.invoices is not None:
        doc = await db.invoices.find_one({"_id": obj_id, "user_id": user_id})
        if not doc:
            raise HTTPException(404, "Invoice not found")

        state_entry = processing_tasks.get(invoice_id)
        state = state_entry[0] if isinstance(state_entry, tuple) else (state_entry or "queued")
        return {
            "invoice_id": invoice_id,
            "processing_state": state,
            "status": doc.get("status", "processing_queued"),
            "display_id": doc.get("display_id"),
        }

    return {"invoice_id": invoice_id, "processing_state": "unknown", "status": "unknown"}


@app.post("/preview-masters")
async def preview_masters(data: InvoiceDataLegacy, current_user: dict = Depends(get_authenticated_user)):
    """Preview what masters will be created before generating XML."""
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, _active_cmp = _make_xml_generator(user_cfg)
        raw = data.model_dump()
        standard = _legacy_to_standard(raw, cfg=usr_cfg)
        report = xml_gen.pre_import_check(standard)

        # Check for similar vendors from import history
        vendor_name = standard.vendor_name.strip()
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if db.invoices is not None and vendor_name:
            similar = await db.find_similar_vendors(vendor_name, user_id)
            if similar:
                report["warnings"].append({
                    "type": "similar_vendor_exists",
                    "severity": "medium",
                    "message": f"Similar vendor names found in previous imports:",
                    "details": [f"{s['vendor_name']} ({s['gstin'] or 'no GSTIN'})" for s in similar],
                })

        return report
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {str(e)}")


@app.post("/pre-import-check")
async def pre_import_check(data: InvoiceDataLegacy, current_user: dict = Depends(get_authenticated_user)):
    """Full pre-import readiness check: masters, warnings, company, voucher info."""
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, _active_cmp = _make_xml_generator(user_cfg)
        raw = data.model_dump()
        standard = _legacy_to_standard(raw, cfg=usr_cfg)
        report = xml_gen.pre_import_check(standard)

        # Similar vendors
        vendor_name = standard.vendor_name.strip()
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if db.invoices is not None and vendor_name:
            similar = await db.find_similar_vendors(vendor_name, user_id)
            if similar:
                report["warnings"].append({
                    "type": "similar_vendor_exists",
                    "severity": "medium",
                    "message": f"Similar vendor names found in previous imports:",
                    "details": [f"{s['vendor_name']} ({s['gstin'] or 'no GSTIN'})" for s in similar],
                })

        # Duplicate check
        inv_no = standard.invoice_number.strip()
        if vendor_name and inv_no:
            dup = await db.find_duplicate(vendor_name, inv_no, user_id)
            if dup:
                report["warnings"].append({
                    "type": "duplicate_invoice",
                    "severity": "high",
                    "message": f"Invoice '{inv_no}' from '{vendor_name}' was already imported (ID: {dup.get('display_id')}).",
                })

        return report
    except Exception as e:
        raise HTTPException(500, f"Pre-import check failed: {str(e)}")


@app.post("/generate-xml")
async def generate_xml(data: InvoiceDataLegacy, force: bool = Query(False), current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
        raw = data.model_dump()
        standard = _legacy_to_standard(raw, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)

        user_id = current_user.get("user_id", current_user.get("email", ""))
        dup_msg = await _check_duplicate(standard.vendor_name, standard.invoice_number, standard.total_amount, user_id)
        if dup_msg:
            validation_result.add_warning(dup_msg)

        if force:
            pass
        elif validation_result.blocking_errors:
            return JSONResponse(
                status_code=422,
                content={
                    "valid": False,
                    "blocking_errors": validation_result.blocking_errors,
                    "soft_errors": validation_result.soft_errors,
                    "checks": validation_result.checks,
                    "message": "Critical errors. Use force=true to generate anyway.",
                },
            )
        elif validation_result.soft_errors:
            return JSONResponse(
                status_code=422,
                content={
                    "valid": False,
                    "blocking_errors": [],
                    "soft_errors": validation_result.soft_errors,
                    "checks": validation_result.checks,
                    "message": "Soft warnings. Retry with ?force=true to generate anyway.",
                },
            )

        xml_str = xml_gen.generate(standard, company_name=active_company)
        xml_validation = validate_xml_output(xml_str)
        old_validation = val.run_full_validation(raw, [])

        # Run full validation pipeline (Accounting, GST, XML, Round-Trip)
        pipe_report = _run_validation_pipeline(standard, xml_str)

        # Mark masters as created (reuse on next generation)
        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_id = current_user.get("user_id", "default")
            if user_id not in _config_overrides:
                _config_overrides[user_id] = {}
            _config_overrides[user_id]["masters_created"] = True

        inv_id = None
        if db.invoices is not None:
            try:
                inv_id, _ = await db.insert_invoice(
                    user_id=user_id,
                    client_id=data.client_id or 0,
                    extracted=raw,
                    validation=old_validation,
                    xml_generated=True, xml_content=xml_str,
                    xml_issues=xml_validation.errors,
                )
            except Exception as e:
                logger.error("DB insert error: %s", e)

        # Attach validation report header for the connector / frontend to read
        score = pipe_report.get("scores", {}).get("total", 0)
        report_json = json.dumps(pipe_report)
        user_id = current_user.get("user_id", "unknown")
        audit_logger.log_invoice_action("generate_xml", inv_id or 0, user_id, f"score={score} passed={pipe_report.get('passed')}")
        return Response(
            content=xml_str,
            media_type="text/plain",
            headers={
                "X-Validation-Score": str(score),
                "X-Validation-Passed": "true" if pipe_report.get("passed") else "false",
                "X-Validation-Report": report_json,
            },
        )
    except Exception as e:
        logger.error("XML GENERATION ERROR: %s", e)
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.post("/generate-xml/v3")
async def generate_xml_v3(data: dict, current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)
        if not validation_result.passed:
            return {
                "valid": False,
                "validation": validation_result.to_dict(),
                "message": "Validation failed. Correct errors before generating XML.",
            }
        xml_str = xml_gen.generate(standard, company_name=active_company)
        xml_validation = validate_xml_output(xml_str)

        # Run full validation pipeline
        pipe_report = _run_validation_pipeline(standard, xml_str)

        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_cfg["masters_created"] = True
            user_id = current_user.get("user_id", "default")
            if user_id not in _config_overrides:
                _config_overrides[user_id] = {}
            _config_overrides[user_id]["masters_created"] = True

        return {
            "valid": True,
            "xml": xml_str,
            "validation": validation_result.to_dict(),
            "xml_validation": xml_validation.to_dict(),
            "validation_report": pipe_report,
        }
    except Exception as e:
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.get("/api/v3/validate")
async def validate_standardized(data: dict, current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        _, usr_cfg, _ = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        result = validate_invoice_for_xml(standard)
        return {"valid": result.passed, **result.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"Validation error: {str(e)}")


@app.post("/generate-xml/{invoice_id}")
async def generate_xml_for(
    invoice_id: int, data: InvoiceDataLegacy, force: bool = Query(False),
    current_user: dict = Depends(get_authenticated_user),
):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
        raw = data.model_dump()
        standard = _legacy_to_standard(raw, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)

        user_id = current_user.get("user_id", current_user.get("email", ""))
        dup_msg = await _check_duplicate(standard.vendor_name, standard.invoice_number, standard.total_amount, user_id)
        if dup_msg:
            validation_result.add_warning(dup_msg)

        if force:
            pass
        elif validation_result.blocking_errors:
            return JSONResponse(status_code=422, content={
                "valid": False, "blocking_errors": validation_result.blocking_errors,
                "soft_errors": validation_result.soft_errors, "checks": validation_result.checks,
                "message": "Critical errors. Use force=true to generate anyway.",
            })
        elif validation_result.soft_errors:
            return JSONResponse(status_code=422, content={
                "valid": False, "blocking_errors": [], "soft_errors": validation_result.soft_errors,
                "checks": validation_result.checks,
                "message": "Soft warnings. Retry with ?force=true to generate anyway.",
            })

        xml_str = xml_gen.generate(standard, company_name=active_company)
        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_id = current_user.get("user_id", "default")
            if user_id not in _config_overrides:
                _config_overrides[user_id] = {}
            _config_overrides[user_id]["masters_created"] = True
        xml_issues_obj = validate_xml_output(xml_str)
        validation = val.run_full_validation(raw, [])

        # Run full validation pipeline
        pipe_report = _run_validation_pipeline(standard, xml_str)

        orig_provider = record.get("extracted", {}).get("_provider", "")
        orig_model = record.get("extracted", {}).get("_model", "")
        raw["_provider"] = orig_provider
        raw["_model"] = orig_model
        raw["validation"] = validation_result.to_dict()
        await db.update_invoice(invoice_id, {
            "extracted": raw, "validation": validation,
            "xml_generated": True, "xml_content": xml_str,
            "xml_issues": xml_issues_obj.errors,
        })
        score = pipe_report.get("scores", {}).get("total", 0)
        report_json = json.dumps(pipe_report)
        return Response(
            content=xml_str,
            media_type="text/plain",
            headers={
                "X-Validation-Score": str(score),
                "X-Validation-Passed": "true" if pipe_report.get("passed") else "false",
                "X-Validation-Report": report_json,
            },
        )
    except Exception as e:
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.post("/invoices/{invoice_id}/generate")
async def generate_from_stored(
    invoice_id: int, force: bool = Query(False),
    current_user: dict = Depends(get_authenticated_user),
):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    data = record["extracted"]

    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)

        if force:
            pass
        elif validation_result.blocking_errors:
            return JSONResponse(status_code=422, content={
                "valid": False, "blocking_errors": validation_result.blocking_errors,
                "soft_errors": validation_result.soft_errors,
                "message": "Critical errors. Use force=true to generate anyway.",
            })
        elif validation_result.soft_errors:
            return {"valid": False, "soft_errors": validation_result.soft_errors, "validation": validation_result.to_dict()}

        xml_str = xml_gen.generate(standard, company_name=active_company)
        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_id = current_user.get("user_id", "default")
            if user_id not in _config_overrides:
                _config_overrides[user_id] = {}
            _config_overrides[user_id]["masters_created"] = True
        xml_validation = validate_xml_output(xml_str)
        old_validation = val.run_full_validation(data, [])

        # Run full validation pipeline
        pipe_report = _run_validation_pipeline(standard, xml_str)

        await db.update_invoice(invoice_id, {
            "xml_generated": True, "xml_content": xml_str,
            "xml_issues": xml_validation.errors, "v3_validation": validation_result.to_dict(),
        })
        return {"valid": True, "xml": xml_str, "validation": old_validation, "xml_issues": xml_validation.errors, "validation_report": pipe_report}
    except Exception as e:
        logger.error("INVOICE XML GENERATION FAILED [%s]: %s", invoice_id, e)
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.get("/invoices")
async def list_invoices(
    client_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_authenticated_user),
):
    if db.invoices is None:
        return []
    user_id = current_user.get("user_id", current_user.get("email", ""))
    records = await db.list_invoices(user_id=user_id, client_id=client_id)
    result = []
    for r in records:
        d = r["extracted"]
        v = r.get("validation") or {}
        dec = v.get("decision") or {}
        result.append({
            "id": r["display_id"],
            "client_id": r.get("client_id"),
            "created_at": r["created_at"],
            "xml_generated": r["xml_generated"],
            "vendor_name": d.get("vendor_name", ""),
            "invoice_number": d.get("invoice_number", ""),
            "date": d.get("date", ""),
            "total_amount": d.get("total_amount", 0),
            "confidence": d.get("confidence"),
            "document_type": v.get("document_type", "unknown"),
            "decision": dec.get("decision", "unknown"),
            "decision_label": dec.get("label", "Unknown"),
            "decision_color": dec.get("color", "gray"),
            "is_service": d.get("is_service", False),
            "gst_type": d.get("gst_type", ""),
            "status": r.get("status", "draft"),
            "synced_at": r.get("synced_at"),
            "sync_error": r.get("sync_error"),
            "source": r.get("source", "extraction"),
            "company_id": r.get("company_id"),
        })
    return result


@app.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    v = record.get("validation")
    return {
        "id": record["display_id"],
        "client_id": record.get("client_id"),
        **record["extracted"],
        "xml_generated": record["xml_generated"],
        "validation": v,
    }


@app.get("/invoices/{invoice_id}/xml")
async def get_invoice_xml(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    if not record.get("xml_content"):
        raise HTTPException(404, "XML not generated yet for this invoice")
    return Response(
        content=record["xml_content"],
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="invoice_{invoice_id}.xml"'},
    )


@app.get("/invoices/{invoice_id}/image")
async def get_invoice_image(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    image_b64 = record.get("image_data", "")
    if not image_b64:
        raise HTTPException(404, "No image stored for this invoice")
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(500, "Corrupt image data")

    async def _stream_chunks():
        chunk_size = 65536
        for offset in range(0, len(image_bytes), chunk_size):
            yield image_bytes[offset:offset + chunk_size]

    return StreamingResponse(
        _stream_chunks(),
        media_type="image/jpeg",
        headers={"Content-Length": str(len(image_bytes))},
    )


class InvoiceUpdatePayload(BaseModel):
    gstin: str = ""
    invoice_number: str = ""
    date: str = ""
    total_amount: float = 0
    vendor_name: str = ""
    vendor_address: str = ""
    buyer_gstin: str = ""
    buyer_name: str = ""
    voucher_type: str = ""
    line_items: list[LineItemModel] = []
    freight: float = 0
    round_off: float = 0
    tds_amount: float = 0
    item_ledgers: list[str] = []


@app.put("/invoices/{invoice_id}")
async def update_invoice(invoice_id: int, data: InvoiceUpdatePayload, current_user: dict = Depends(get_authenticated_user)):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    raw = data.model_dump(exclude_unset=True)
    extracted_update = {
        "gstin": raw.get("gstin", ""),
        "invoice_number": raw.get("invoice_number", ""),
        "date": raw.get("date", ""),
        "total_amount": raw.get("total_amount", 0),
        "vendor_name": raw.get("vendor_name", ""),
        "vendor_address": raw.get("vendor_address", ""),
        "buyer_gstin": raw.get("buyer_gstin", ""),
        "buyer_name": raw.get("buyer_name", ""),
        "voucher_type": raw.get("voucher_type", ""),
        "freight": raw.get("freight", 0),
        "round_off": raw.get("round_off", 0),
        "tds_amount": raw.get("tds_amount", 0),
        "line_items": [{"description": li.description, "quantity": li.quantity, "rate": li.rate, "taxable_value": li.taxable_value, "tax_rate": li.tax_rate, "ledger_name": li.ledger_name} for li in data.line_items],
    }
    set_fields = {"extracted": extracted_update}
    if raw.get("item_ledgers"):
        set_fields["item_ledgers"] = raw["item_ledgers"]
    await db.update_invoice(invoice_id, set_fields)
    return {"ok": True, "id": invoice_id}


@app.get("/api/v3/invoices/{invoice_id}/preview-ledger")
async def preview_ledger(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Exposes live double-entry splits for the review workspace."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    inv = await db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    extracted = inv.get("extracted") or {}
    grand_total = Decimal(str(extracted.get("total_amount", 0)))
    taxable = Decimal(str(extracted.get("total_taxable_value", 0) or 0))
    cgst = Decimal(str(extracted.get("total_cgst", 0) or 0))
    sgst = Decimal(str(extracted.get("total_sgst", 0) or 0))
    igst = Decimal(str(extracted.get("total_igst", 0) or 0))
    vch_type = extracted.get("voucher_type", "Purchase")
    party = extracted.get("vendor_name", extracted.get("buyer_name", "Unknown"))
    expense_ledger = extracted.get("expense_ledger", "Purchase Accounts")
    entries, is_balanced, zero_sum = [], False, Decimal("0.00")

    if vch_type in ("Purchase", "Credit Note"):
        entries.append({"ledger_name": party, "type": "Credit (Cr)", "is_deemed_positive": "No", "amount": f"{grand_total:.2f}"})
        zero_sum += grand_total
        entries.append({"ledger_name": expense_ledger, "type": "Debit (Dr)", "is_deemed_positive": "Yes", "amount": f"-{taxable:.2f}"})
        zero_sum -= taxable
        if igst > 0:
            entries.append({"ledger_name": "Input IGST", "type": "Debit (Dr)", "is_deemed_positive": "Yes", "amount": f"-{igst:.2f}"})
            zero_sum -= igst
        if cgst > 0:
            entries.append({"ledger_name": "Input CGST", "type": "Debit (Dr)", "is_deemed_positive": "Yes", "amount": f"-{cgst:.2f}"})
            zero_sum -= cgst
        if sgst > 0:
            entries.append({"ledger_name": "Input SGST", "type": "Debit (Dr)", "is_deemed_positive": "Yes", "amount": f"-{sgst:.2f}"})
            zero_sum -= sgst
    elif vch_type in ("Sales", "Debit Note"):
        entries.append({"ledger_name": party, "type": "Debit (Dr)", "is_deemed_positive": "Yes", "amount": f"-{grand_total:.2f}"})
        zero_sum -= grand_total
        entries.append({"ledger_name": expense_ledger, "type": "Credit (Cr)", "is_deemed_positive": "No", "amount": f"{taxable:.2f}"})
        zero_sum += taxable
        if igst > 0:
            entries.append({"ledger_name": "Output IGST", "type": "Credit (Cr)", "is_deemed_positive": "No", "amount": f"{igst:.2f}"})
            zero_sum += igst
        if cgst > 0:
            entries.append({"ledger_name": "Output CGST", "type": "Credit (Cr)", "is_deemed_positive": "No", "amount": f"{cgst:.2f}"})
            zero_sum += cgst
        if sgst > 0:
            entries.append({"ledger_name": "Output SGST", "type": "Credit (Cr)", "is_deemed_positive": "No", "amount": f"{sgst:.2f}"})
            zero_sum += sgst
    is_balanced = zero_sum == Decimal("0.00")
    return {"invoice_id": invoice_id, "voucher_type": vch_type, "is_balanced": is_balanced, "ledger_entries": entries}


@app.post("/api/v3/invoices/{invoice_id}/confirm-review")
async def confirm_review(invoice_id: int, data: InvoiceUpdatePayload, current_user: dict = Depends(get_authenticated_user)):
    """Transition invoice from draft to validated after mandatory checks."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    raw = data.model_dump(exclude_unset=True)

    # Save all fields first
    extracted_update = {
        "gstin": raw.get("gstin", ""),
        "invoice_number": raw.get("invoice_number", ""),
        "date": raw.get("date", ""),
        "total_amount": raw.get("total_amount", 0),
        "vendor_name": raw.get("vendor_name", ""),
        "vendor_address": raw.get("vendor_address", ""),
        "buyer_gstin": raw.get("buyer_gstin", ""),
        "buyer_name": raw.get("buyer_name", ""),
        "voucher_type": raw.get("voucher_type", ""),
        "freight": raw.get("freight", 0),
        "round_off": raw.get("round_off", 0),
        "tds_amount": raw.get("tds_amount", 0),
        "line_items": [{"description": li.description, "quantity": li.quantity, "rate": li.rate, "taxable_value": li.taxable_value, "tax_rate": li.tax_rate, "ledger_name": li.ledger_name} for li in data.line_items],
    }

    # Mandatory checks before confirming review
    errors = []
    if not extracted_update.get("vendor_name"):
        errors.append("Vendor name is required")
    if not extracted_update.get("invoice_number"):
        errors.append("Invoice number is required")
    if not extracted_update.get("date"):
        errors.append("Invoice date is required")
    if not extracted_update.get("total_amount") or extracted_update["total_amount"] <= 0:
        errors.append("Valid total amount is required")
    line_items = extracted_update.get("line_items", [])
    if not line_items:
        errors.append("At least one line item is required")
    ledgers = raw.get("item_ledgers", [])
    if line_items and len(ledgers) != len(line_items):
        errors.append(f"Each line item must have a ledger assigned ({len(line_items)} items, {len(ledgers)} ledgers)")
    if line_items:
        for i, li in enumerate(line_items):
            if not li.get("description", "").strip():
                errors.append(f"Line item {i+1}: description is required")
            if i < len(ledgers) and not ledgers[i].strip():
                errors.append(f"Line item {i+1}: ledger is required")

    if errors:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "errors": errors, "message": "Fix errors before confirming review"},
        )

    # Save extracted data + auto-generate XML
    set_fields = {"extracted": extracted_update}
    pipe_report = None
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(extracted_update, cfg=usr_cfg)
        xml_str = xml_gen.generate(standard, company_name=active_company)
        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_id = current_user.get("user_id", "default")
            if user_id not in _config_overrides:
                _config_overrides[user_id] = {}
            _config_overrides[user_id]["masters_created"] = True
        xml_validation = validate_xml_output(xml_str)

        # Run full validation pipeline (Accounting, GST, XML, Round-Trip)
        pipe_report = _run_validation_pipeline(standard, xml_str)

        set_fields["xml_content"] = xml_str
        set_fields["xml_issues"] = xml_validation.errors
        set_fields["xml_generated"] = True
        if pipe_report:
            set_fields["validation_report"] = pipe_report
    except Exception as e:
        logger.error("Auto XML generation failed during review confirm: %s", e)
        set_fields["xml_issues"] = [f"Auto XML generation failed: {str(e)}"]
        set_fields["xml_generated"] = False

    set_fields["status"] = "validated"
    set_fields["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    if ledgers:
        set_fields["item_ledgers"] = ledgers
    await db.update_invoice(invoice_id, set_fields)

    response_data = {
        "ok": True, "id": invoice_id, "status": "validated",
        "xml_generated": True,
        "message": "Invoice reviewed, confirmed, and XML generated. Ready for Tally sync.",
    }
    if pipe_report:
        response_data["validation_report"] = pipe_report
    return response_data


@app.get("/api/v3/validation-report/{invoice_id}")
async def get_validation_report(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Return a stored or freshly-generated validation report for an invoice.

    If the invoice has XML content, re-runs the pipeline and returns the report.
    If not, returns a partial report based on accounting validation only.
    """
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")

    # If stored report exists, return it
    stored = record.get("validation_report")
    if stored:
        return stored

    # Otherwise, build report from stored data
    extracted = record.get("extracted", {})
    if not extracted:
        return {
            "invoice_number": "",
            "scores": {"total": 0},
            "passed": False,
            "ready_for_tally": False,
            "warnings": ["No extracted data found"],
            "errors": ["No extracted data for this invoice"],
        }

    try:
        user_cfg = _user_config_from_current(current_user)
        _, usr_cfg, _ = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(extracted, cfg=usr_cfg)
        xml_str = record.get("xml_content", "")

        report = _run_validation_pipeline(standard, xml_str or None)
        return report
    except Exception as e:
        logger.error("VALIDATION REPORT ERROR [%s]: %s", invoice_id, e)
        return {
            "invoice_number": extracted.get("invoice_number", ""),
            "scores": {"total": 0},
            "passed": False,
            "ready_for_tally": False,
            "errors": [f"Report generation error: {str(e)}"],
        }


@app.get("/invoices/check-duplicate")
async def check_duplicate(vendor: str, invoice_no: str, current_user: dict = Depends(get_authenticated_user)):
    if db.invoices is None:
        return {"duplicate": False}
    user_id = current_user.get("user_id", current_user.get("email", ""))
    dup = await db.find_duplicate(vendor, invoice_no, user_id)
    if dup:
        return {"duplicate": True, "existing_id": dup.get("display_id"), "existing_date": dup.get("created_at")}
    return {"duplicate": False}


@app.get("/health")
async def health():
    status = "healthy"
    checks = {}

    try:
        if db.invoices is not None:
            t0 = time.monotonic()
            await db.invoices.find_one({}, {"_id": 1})
            latency = round((time.monotonic() - t0) * 1000, 1)
            checks["database"] = {"status": "ok", "latency_ms": latency}
        else:
            checks["database"] = {"status": "disconnected", "latency_ms": None}
            status = "degraded"
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        status = "degraded"

    checks["openrouter"] = {"configured": bool(os.getenv("OPENROUTER_API_KEY"))}
    checks["gemini"] = {"configured": bool(os.getenv("GEMINI_API_KEY"))}
    if not checks["openrouter"]["configured"] and not checks["gemini"]["configured"]:
        status = "degraded"

    return {
        "status": status,
        "version": "3.2",
        "checks": checks,
    }


@app.get("/api/v3/gst/state-codes")
async def get_state_codes():
    return GST_STATE_CODES


@app.post("/api/v3/gst/validate")
async def gst_validate(gstin: str):
    return validate_gstin(gstin)


@app.get("/api/v3/config")
async def get_config(current_user: dict = Depends(get_authenticated_user)):
    user_cfg = _user_config_from_current(current_user)
    if user_cfg:
        return user_cfg
    return _company_config.to_env_config()


@app.post("/api/v3/config")
async def save_config(data: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", "default")
    allowed = set(_COMPANY_CONFIG_FIELDS)
    clean = {k: v for k, v in data.items() if k in allowed and v}
    if clean:
        old_config = _config_overrides.get(user_id, {})
        if user_id not in _config_overrides:
            _config_overrides[user_id] = {}
        
        encrypted_fields = {"tally_password"}
        db_clean = {}
        for key, value in clean.items():
            if key in encrypted_fields and value:
                db_clean[key] = encrypt(value)
                clean[key] = value
            else:
                db_clean[key] = value
        
        _config_overrides[user_id].update(clean)
        for key, value in clean.items():
            old_value = old_config.get(key, "")
            if old_value != value:
                audit_logger.log_config_change(user_id, key, str(old_value), str(value))
        # Persist to DB if available
        if db.users is not None:
            try:
                await db.users.update_one(
                    {"email": current_user.get("email", "").lower()},
                    {"$set": clean},
                    upsert=True,
                )
            except Exception as e:
                logger.warning("Config persist failed: %s", e)
    return {**current_user, **_config_overrides.get(user_id, {})}


@app.post("/api/v3/generate")
async def generate_v3(data: dict, current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)
        xml_str = xml_gen.generate(standard, company_name=active_company)
        xml_validation = validate_xml_output(xml_str)

        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_cfg["masters_created"] = True
            user_id = current_user.get("user_id", "default")
            if user_id not in _config_overrides:
                _config_overrides[user_id] = {}
            _config_overrides[user_id]["masters_created"] = True

        return {
            "valid": validation_result.passed,
            "xml": xml_str,
            "validation": validation_result.to_dict(),
            "xml_validation": xml_validation.to_dict(),
            "balanced": not xml_validation.errors,
        }
    except Exception as e:
        raise HTTPException(500, f"Generation error: {str(e)}")


@app.post("/api/v3/voucher-type/suggest")
async def suggest_voucher_type(data: dict, current_user: dict = Depends(get_authenticated_user)):
    user_cfg = _user_config_from_current(current_user)
    state_code = user_cfg.get("company_state_code") or _company_config.state_code
    vtype, rationale = classify_voucher_type(data, state_code)
    return {
        "suggested": vtype.value,
        "rationale": rationale,
        "user_can_override": True,
        "available_types": [t.value for t in VoucherType],
        "is_service": classify_service_vs_goods(data.get("line_items", [])),
    }


@app.post("/api/v3/batch/extract")
async def batch_extract(
    request: Request,
    files: list[UploadFile] = File(...),
    client_id: int = Query(..., description="Client ID"),
    current_user: dict = Depends(get_authenticated_user),
):
    if len(files) > 50:
        raise HTTPException(400, "Maximum 50 files per batch")

    if db.clients is not None:
        client = await db.get_client(client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if client.get("user_id") != user_id:
            raise HTTPException(403, "Access denied")

    user_config = _user_config_from_current(current_user)
    company_gstin = user_config.get("company_gstin") or os.getenv("COMPANY_GSTIN", "")
    if not company_gstin:
        return JSONResponse(
            status_code=400,
            content={
                "error": "company_profile_required",
                "message": "Set up your company profile first.",
            },
        )

    results = []
    errors = []

    for file in files:
        try:
            if not file.filename:
                errors.append({"file": "unknown", "error": "No filename"})
                continue
            file_bytes = await file.read()
            file.file.seek(0)
            if len(file_bytes) > 15 * 1024 * 1024:
                errors.append({"file": file.filename, "error": "File exceeds 15MB"})
                continue
            first_bytes = file_bytes[:16]
            if not _is_valid_image(first_bytes):
                errors.append({"file": file.filename, "error": "Not a valid image or PDF"})
                continue

            # Re-process each file through a fresh temp file
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
            tmp_path = Path(tmp.name)
            tmp.write(file_bytes)
            tmp.close()

            image_bytes = tmp_path.read_bytes()
            try:
                data = await _extraction_pipeline.extract(image_bytes, file.content_type or "image/jpeg", company_gstin=company_gstin)
                data = clean_extracted_invoice_payload(data)
                data.pop("_raw_response", None)
                data["filename"] = file.filename
                data["_provider"] = _extraction_pipeline.last_provider
                data["_model"] = _extraction_pipeline.last_model
                results.append(data)
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            errors.append({"file": file.filename or "unknown", "error": str(e)})

    return {
        "total": len(files),
        "processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }


@app.get("/api/v3/banking/rules")
async def banking_rules_list(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    rules = await db.list_banking_rules(user_id)
    return [{"id": str(r["_id"]), "keyword": r["keyword"], "voucher_type": r["voucher_type"], "target_ledger": r["target_ledger"]} for r in rules]


@app.post("/api/v3/banking/rules")
async def banking_rules_create(body: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    keyword = (body or {}).get("keyword", "").strip()
    if not keyword:
        raise HTTPException(400, "keyword is required")
    doc = await db.create_banking_rule(
        user_id=user_id,
        keyword=keyword,
        voucher_type=body.get("voucher_type", "Receipt"),
        target_ledger=body.get("target_ledger", "Suspense"),
    )
    return {"status": "ok", "rule": {"id": str(doc.get("_id", "")), "keyword": keyword}}


@app.delete("/api/v3/banking/rules/{rule_id}")
async def banking_rules_delete(rule_id: str, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    await db.delete_banking_rule(rule_id, user_id)
    return {"status": "ok"}


@app.post("/api/v3/banking/process")
async def banking_process_statement(body: dict, current_user: dict = Depends(get_authenticated_user)):
    from ledger_mapping import apply_banking_rules_to_transactions
    from xml_generator import generate_tally_bank_xml
    user_id = current_user.get("user_id", current_user.get("email", ""))
    transactions = (body or {}).get("transactions", [])
    bank_ledger = (body or {}).get("bank_ledger", "Bank")
    if not transactions:
        raise HTTPException(400, "transactions list is required")
    user_cfg = _user_config_from_current(current_user)
    active_company = user_cfg.get("active_company", "")
    rules = await db.list_banking_rules(user_id)
    processed = apply_banking_rules_to_transactions(transactions, rules)
    xml = generate_tally_bank_xml(processed, bank_ledger_name=bank_ledger, company_name=active_company)
    return {
        "total": len(processed),
        "processed": processed,
        "xml": xml,
    }


class CompanySyncPayload(BaseModel):
    companies: list[str]
    tally_reachable: bool = False
    connector_version: str = ""
    active_company: str = ""


class LedgerSyncPayload(BaseModel):
    ledgers: list[str]


class BulkLedgerMapPayload(BaseModel):
    invoice_ids: list[int]
    target_ledger: str


@app.post("/api/v3/sync/companies")
async def receive_active_tally_companies(payload: CompanySyncPayload, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "active_tally_companies": payload.companies,
            "last_connector_ping": now,
            "connector_version": payload.connector_version,
            "tally_reachable": payload.tally_reachable,
            "connector_online": True,
        }
        if payload.active_company:
            update["active_company"] = payload.active_company
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": update},
            upsert=True,
        )
    return {"status": "synced", "tally_reachable": payload.tally_reachable, "count": len(payload.companies)}


@app.post("/api/v3/sync/active-company")
async def set_active_company(body: dict, current_user: dict = Depends(get_authenticated_user)):
    """Sets the active Tally company for this user. Called from C# connector when user selects a company."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    active_company = (body or {}).get("active_company", "")
    tally_reachable = (body or {}).get("tally_reachable", False)
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"active_company": active_company, "tally_reachable": tally_reachable}},
            upsert=True,
        )
    return {"status": "ok", "active_company": active_company}


@app.post("/api/v3/sync/ledgers")
async def receive_tally_ledgers(payload: LedgerSyncPayload, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"ledger_cache": payload.ledgers, "last_ledger_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(payload.ledgers)}


@app.get("/api/v3/sync/ledgers")
async def get_cached_ledgers(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"ledgers": org.get("ledger_cache", [])}
    return {"ledgers": []}


@app.post("/api/v3/invoices/bulk-map")
async def bulk_map_ledgers_before_sync(payload: BulkLedgerMapPayload, current_user: dict = Depends(get_authenticated_user)):
    if not payload.invoice_ids:
        raise HTTPException(400, "invoice_ids list is empty")
    if db.invoices is not None:
        result = await db.execute_db_write_with_retry(
            db.invoices.update_many,
            {"display_id": {"$in": payload.invoice_ids}},
            {"$set": {"custom_ledger_override": payload.target_ledger, "status": "validated"}},
        )
        return {"status": "updated", "matched_count": result.matched_count}
    return {"status": "ok", "matched_count": 0}


@app.get("/api/v3/sync/pending")
async def sync_pending(
    current_user: dict = Depends(get_authenticated_user),
    limit: int = Query(50, le=200),
):
    """Polled by C# Tally Connector to fetch invoices ready for local sync."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    pending = await db.list_pending_sync(user_id=user_id, limit=limit)
    return {
        "count": len(pending),
        "invoices": [
            {
                "display_id": inv["display_id"],
                "client_id": inv["client_id"],
                "invoice_number": inv.get("extracted", {}).get("invoice_number", ""),
                "vendor_name": inv.get("extracted", {}).get("vendor_name", ""),
                "voucher_type": inv.get("extracted", {}).get("voucher_type", ""),
                "total_amount": inv.get("extracted", {}).get("total_amount", 0),
                "created_at": inv.get("created_at", ""),
                "xml_content": inv.get("xml_content", ""),
            }
            for inv in pending
        ],
    }


@app.post("/api/v3/sync/confirm/{display_id}")
async def sync_confirm(
    display_id: int,
    current_user: dict = Depends(get_authenticated_user),
):
    """Called by C# Tally Connector after successful Tally import."""
    inv = await db.get_invoice(display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.update_invoice_status(display_id, "exported")
    audit_logger.log_sync(user_id, display_id, True)
    return {"status": "ok", "message": f"Invoice #{display_id} marked as exported"}


@app.post("/api/v3/sync/error/{display_id}")
async def sync_error(
    display_id: int,
    body: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    """Called by C# Tally Connector when Tally rejects an import."""
    inv = await db.get_invoice(display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    error_msg = (body or {}).get("error", "Unknown Tally error")
    await db.update_invoice_status(display_id, "sync_error", sync_error=error_msg)
    audit_logger.log_sync(user_id, display_id, False, error_msg)
    return {"status": "ok", "message": f"Sync error recorded for invoice #{display_id}"}


@app.get("/api/v3/tally/status")
async def tally_status(current_user: dict = Depends(get_authenticated_user)):
    """Returns Tally Prime connection status for the dashboard indicator."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    status = {
        "connected": False,
        "company": "",
        "last_ping": None,
        "connector_online": False,
        "tally_reachable": False,
        "connector_version": "",
    }
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            status["connector_online"] = org.get("connector_online", False)
            status["tally_reachable"] = org.get("tally_reachable", False)
            status["connector_version"] = org.get("connector_version", "")
            status["last_ping"] = org.get("last_connector_ping")
            status["active_company"] = org.get("active_company", "")
            companies = org.get("active_tally_companies", [])
            status["available_companies"] = companies
            if status["tally_reachable"] and companies:
                status["company"] = status["active_company"] or companies[0]
                status["connected"] = True
    return status


@app.get("/api/v3/tally/config")
async def tally_config(current_user: dict = Depends(get_authenticated_user)):
    """Returns Tally connector configuration including password. Called by C# connector on startup."""
    user_cfg = _user_config_from_current(current_user)
    return {
        "tally_password": user_cfg.get("tally_password", ""),
        "active_company": user_cfg.get("active_company", ""),
    }


class ImportedVoucherPayload(BaseModel):
    import_source: str = "tally_pull"
    vouchers: list[dict]


@app.post("/api/v3/sync/import-from-tally")
async def import_from_tally(
    payload: ImportedVoucherPayload,
    current_user: dict = Depends(get_authenticated_user),
):
    """Called by C# connector to store vouchers pulled from Tally as draft invoices."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    imported = []
    for v in payload.vouchers:
        vendor = v.get("party_name", v.get("vendor_name", "Unknown"))
        inv_num = v.get("voucher_number", v.get("invoice_number", ""))
        amount = v.get("amount", v.get("total_amount", 0))
        voucher_type = v.get("voucher_type", "Purchase")
        date = v.get("date", "")
        extracted = {
            "vendor_name": vendor,
            "invoice_number": inv_num,
            "total_amount": amount,
            "date": date,
            "voucher_type": voucher_type,
        }
        if db.invoices is not None:
            company_id = v.get("company_id")
            inv_display_id, _inv_id = await db.insert_invoice(
                user_id=user_id, client_id=v.get("client_id", 0),
                extracted=extracted, company_id=company_id,
                validation={"source": "tally_pull", "imported_at": datetime.now(timezone.utc).isoformat()},
            )
            uploaded_by = current_user.get("email", "default@local")
            await db.execute_db_write_with_retry(
                db.invoices.update_one,
                {"display_id": inv_display_id},
                {"$set": {"source": "tally_pull", "uploaded_by": uploaded_by}},
            )
            imported.append({
                "display_id": inv_display_id,
                "vendor_name": vendor,
                "invoice_number": inv_num,
                "total_amount": amount,
            })
    return {"imported": len(imported), "invoices": imported}


@app.post("/api/v3/invoices/{display_id}/sync-now")
async def trigger_invoice_sync(
    display_id: int,
    current_user: dict = Depends(get_authenticated_user),
):
    """Marks a validated invoice for immediate Tally sync. Called from dashboard 'Send to Tally' button."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    inv = await db.get_invoice(display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    if not inv.get("xml_content"):
        raise HTTPException(400, "No XML content generated yet. Generate XML first.")
    await db.execute_db_write_with_retry(
        db.invoices.update_one,
        {"display_id": display_id},
        {"$set": {"status": "validated", "priority_sync": True, "sync_triggered_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "queued", "message": f"Invoice #{display_id} queued for Tally sync. The connector will pick it up within 30 seconds."}


@app.get("/api/v3/invoices/pending-tally-push")
async def pending_tally_push(
    current_user: dict = Depends(get_authenticated_user),
    limit: int = Query(50, le=200),
):
    """Polled by C# Tally Connector to fetch invoices with XML ready for Tally import."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    pending = await db.list_pending_sync(user_id=user_id, limit=limit)
    return {
        "count": len(pending),
        "invoices": [
            {
                "invoice_id": inv.get("display_id"),
                "voucher_type": inv.get("extracted", {}).get("voucher_type", "Purchase"),
                "invoice_number": inv.get("extracted", {}).get("invoice_number", ""),
                "vendor_name": inv.get("extracted", {}).get("vendor_name", ""),
                "total_amount": inv.get("extracted", {}).get("total_amount", 0),
                "xml_content": inv.get("xml_content", ""),
                "created_at": inv.get("created_at", ""),
            }
            for inv in pending
        ],
    }


@app.post("/api/v3/invoices/{invoice_id}/tally-result")
async def tally_push_result(
    invoice_id: int,
    body: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    """Called by C# Tally Connector after a Tally push attempt to report success or failure."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    inv = await db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    success = body.get("success", False)
    error_msg = body.get("error", "")
    if success:
        await db.update_invoice_status(invoice_id, "exported")
        return {"status": "ok", "message": f"Invoice #{invoice_id} marked as exported"}
    else:
        await db.update_invoice_status(invoice_id, "sync_error", sync_error=error_msg or "Unknown Tally error")
        return {"status": "error", "message": f"Sync error recorded for invoice #{invoice_id}"}


# =====================================================================
# P0 — Tally Masters Read APIs
# =====================================================================

@app.get("/api/v3/tally/masters/companies")
async def tally_masters_companies(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"companies": org.get("active_tally_companies", [])}
    return {"companies": []}


@app.get("/api/v3/tally/masters/ledgers")
async def tally_masters_ledgers(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"ledgers": org.get("ledger_cache", [])}
    return {"ledgers": []}


@app.post("/api/v3/tally/masters/ledgers")
async def tally_masters_ledgers_update(
    payload: LedgerSyncPayload,
    current_user: dict = Depends(get_authenticated_user),
):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"ledger_cache": payload.ledgers, "last_ledger_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(payload.ledgers)}


@app.get("/api/v3/tally/masters/stock-items")
async def tally_masters_stock_items(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"stock_items": org.get("stock_item_cache", [])}
    return {"stock_items": []}


@app.post("/api/v3/tally/masters/stock-items")
async def tally_masters_stock_items_update(
    payload: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    stock_items = payload.get("stock_items", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"stock_item_cache": stock_items, "last_stock_item_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(stock_items)}


@app.get("/api/v3/tally/masters/voucher-types")
async def tally_masters_voucher_types(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"voucher_types": org.get("voucher_type_cache", [])}
    return {"voucher_types": []}


@app.post("/api/v3/tally/masters/voucher-types")
async def tally_masters_voucher_types_update(
    payload: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    voucher_types = payload.get("voucher_types", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"voucher_type_cache": voucher_types, "last_voucher_type_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(voucher_types)}


@app.get("/api/v3/tally/masters/groups")
async def tally_masters_groups(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"groups": org.get("group_cache", [])}
    return {"groups": []}


@app.post("/api/v3/tally/masters/groups")
async def tally_masters_groups_update(
    payload: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    groups = payload.get("groups", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"group_cache": groups, "last_group_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(groups)}


@app.get("/api/v3/tally/masters/units")
async def tally_masters_units(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"units": org.get("unit_cache", [])}
    return {"units": []}


@app.post("/api/v3/tally/masters/units")
async def tally_masters_units_update(
    payload: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    units = payload.get("units", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"unit_cache": units, "last_unit_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(units)}


# =====================================================================
# P0 — Dry Run / Pre-flight Validation
# =====================================================================

class DryRunRequest(BaseModel):
    invoice_data: dict
    check_duplicates: bool = True


class DryRunResponse(BaseModel):
    safe_to_import: bool
    checks: list[dict]
    warnings: list[str]
    masters_to_create: list[str]
    existing_masters: list[str]
    duplicate_found: bool = False
    duplicate_invoice_id: int | None = None


@app.post("/api/v3/sync/dry-run")
async def sync_dry_run(
    request: DryRunRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Pre-flight validation: checks invoice against cached Tally masters before import."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    data = request.invoice_data
    checks = []
    warnings = []
    masters_to_create = []
    existing_masters = []

    vendor_name = (data.get("vendor_name") or "").strip()
    invoice_number = (data.get("invoice_number") or "").strip()
    total_amount = float(data.get("total_amount") or 0)
    voucher_type = (data.get("voucher_type") or "Purchase").strip()

    if not vendor_name:
        checks.append({"check": "vendor_name", "passed": False, "message": "Vendor name is missing"})
    else:
        checks.append({"check": "vendor_name", "passed": True, "message": f"Vendor: {vendor_name}"})

    if not invoice_number:
        checks.append({"check": "invoice_number", "passed": False, "message": "Invoice number is missing"})
    else:
        checks.append({"check": "invoice_number", "passed": True, "message": f"Invoice #: {invoice_number}"})

    if total_amount <= 0:
        checks.append({"check": "total_amount", "passed": False, "message": "Total amount must be > 0"})
    else:
        checks.append({"check": "total_amount", "passed": True, "message": f"Amount: Rs.{total_amount:,.2f}"})

    org = await db.organizations.find_one({"org_id": user_id}) if db.organizations is not None else None

    if org:
        ledger_cache = org.get("ledger_cache", [])
        stock_item_cache = org.get("stock_item_cache", [])
        voucher_type_cache = org.get("voucher_type_cache", [])
        group_cache = org.get("group_cache", [])

        vendor_ledger_exists = any(l.lower() == vendor_name.lower() for l in ledger_cache)
        if vendor_ledger_exists:
            existing_masters.append(f"Ledger: {vendor_name}")
        else:
            masters_to_create.append(f"Ledger: {vendor_name}")
            warnings.append(f"Vendor ledger '{vendor_name}' will be created on import")

        purchase_ledger = user_cfg.get("purchase_ledger", "Purchase") if "user_cfg" in dir() else "Purchase"
        purchase_exists = any(l.lower() == purchase_ledger.lower() for l in ledger_cache)
        if not purchase_exists:
            masters_to_create.append(f"Ledger: {purchase_ledger}")

        line_items = data.get("line_items") or []
        for item in line_items:
            desc = (item.get("description") or "").strip()
            hsn = (item.get("hsn_sac") or "").strip()
            if desc and not any(l.lower() == desc.lower() for l in ledger_cache):
                masters_to_create.append(f"Ledger: {desc}")
            if hsn and not any(s.lower() == hsn.lower() for s in stock_item_cache):
                masters_to_create.append(f"Stock Item: {hsn}")

        if voucher_type and not any(v.lower() == voucher_type.lower() for v in voucher_type_cache):
            masters_to_create.append(f"Voucher Type: {voucher_type}")
    else:
        warnings.append("No Tally masters cached — first sync required")
        masters_to_create.append(f"Ledger: {vendor_name}")
        masters_to_create.append("Voucher Type: Purchase")

    duplicate_found = False
    duplicate_invoice_id = None
    if request.check_duplicates and db.invoices is not None and vendor_name and invoice_number:
        dup = await db.invoices.find_one({
            "user_id": user_id,
            "extracted.vendor_name": vendor_name,
            "extracted.invoice_number": invoice_number,
        })
        if dup:
            duplicate_found = True
            duplicate_invoice_id = dup.get("display_id")
            warnings.append(f"Duplicate detected: invoice #{invoice_number} from {vendor_name} already exists (ID: {duplicate_invoice_id})")
            checks.append({"check": "duplicate", "passed": False, "message": f"Duplicate: invoice #{invoice_number} from {vendor_name}"})
        else:
            checks.append({"check": "duplicate", "passed": True, "message": "No duplicate found"})

    safe = len([c for c in checks if not c.get("passed")]) == 0 and not duplicate_found

    return {
        "safe_to_import": safe,
        "checks": checks,
        "warnings": warnings,
        "masters_to_create": list(set(masters_to_create)),
        "existing_masters": list(set(existing_masters)),
        "duplicate_found": duplicate_found,
        "duplicate_invoice_id": duplicate_invoice_id,
    }


# =====================================================================
# P0 — Import Report
# =====================================================================

class ImportReportPayload(BaseModel):
    invoice_display_id: int
    success: bool
    masters_created: list[str] = []
    voucher_id: str = ""
    tally_response: str = ""
    warnings: list[str] = []
    error: str = ""
    import_duration_ms: int = 0


@app.post("/api/v3/sync/import-report")
async def sync_import_report(
    payload: ImportReportPayload,
    current_user: dict = Depends(get_authenticated_user),
):
    """Stores detailed import report for an invoice."""
    inv = await db.get_invoice(payload.invoice_display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    report = {
        "invoice_display_id": payload.invoice_display_id,
        "success": payload.success,
        "masters_created": payload.masters_created,
        "voucher_id": payload.voucher_id,
        "tally_response": payload.tally_response,
        "warnings": payload.warnings,
        "error": payload.error,
        "import_duration_ms": payload.import_duration_ms,
        "reported_at": datetime.now(timezone.utc).isoformat(),
    }

    await db.execute_db_write_with_retry(
        db.invoices.update_one,
        {"display_id": payload.invoice_display_id},
        {"$set": {"last_import_report": report}},
    )

    return {"status": "ok", "report": report}


@app.get("/api/v3/sync/import-report/{invoice_display_id}")
async def get_import_report(
    invoice_display_id: int,
    current_user: dict = Depends(get_authenticated_user),
):
    """Retrieves the last import report for an invoice."""
    inv = await db.get_invoice(invoice_display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    return inv.get("last_import_report", {})


# =====================================================================
# P0 — Idempotency: Prevent duplicate imports
# =====================================================================

@app.post("/api/v3/sync/check-duplicate")
async def sync_check_duplicate(
    body: dict,
    current_user: dict = Depends(get_authenticated_user),
):
    """Checks if an invoice already exists in Tally to prevent duplicate imports."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    vendor_name = (body.get("vendor_name") or "").strip()
    invoice_number = (body.get("invoice_number") or "").strip()
    total_amount = float(body.get("total_amount") or 0)
    invoice_date = (body.get("invoice_date") or "").strip()

    if not vendor_name or not invoice_number:
        return {"duplicate": False, "message": "vendor_name and invoice_number required"}

    if db.invoices is None:
        return {"duplicate": False, "message": "Database not available"}

    query = {
        "user_id": user_id,
        "extracted.vendor_name": vendor_name,
        "extracted.invoice_number": invoice_number,
    }
    if invoice_date:
        query["extracted.invoice_date"] = invoice_date

    existing = await db.invoices.find_one(query)
    if existing:
        return {
            "duplicate": True,
            "invoice_id": existing.get("display_id"),
            "status": existing.get("status"),
            "message": f"Invoice #{invoice_number} from {vendor_name} already exists (ID: {existing.get('display_id')}, status: {existing.get('status')})",
        }

    return {"duplicate": False, "message": "No duplicate found"}


# =====================================================================
# PRODUCTION MODE — hard enforcement before any import
# =====================================================================

_PRODUCTION_MODE = os.getenv("PRODUCTION_MODE", "").lower() in ("true", "1", "yes")


def _require_production_checks(invoice_data: dict, user_id: str) -> dict:
    """Enforce all production checks when PRODUCTION_MODE=true.
    Returns a dict with 'passed' bool and list of 'checks'.
    Raises HTTPException(422) if any check fails in production mode.
    """
    checks = []
    vendor_name = (invoice_data.get("vendor_name") or "").strip()
    invoice_number = (invoice_data.get("invoice_number") or "").strip()
    total_amount = float(invoice_data.get("total_amount") or 0)
    invoice_date = (invoice_data.get("invoice_date") or "").strip()
    voucher_type = (invoice_data.get("voucher_type") or "Purchase").strip()

    if not vendor_name:
        checks.append({"check": "vendor_name", "passed": False, "message": "Vendor name is required"})
    else:
        checks.append({"check": "vendor_name", "passed": True, "message": f"Vendor: {vendor_name}"})

    if not invoice_number:
        checks.append({"check": "invoice_number", "passed": False, "message": "Invoice number is required"})
    else:
        checks.append({"check": "invoice_number", "passed": True, "message": f"Invoice #: {invoice_number}"})

    if total_amount <= 0:
        checks.append({"check": "total_amount", "passed": False, "message": "Total amount must be > 0"})
    else:
        checks.append({"check": "total_amount", "passed": True, "message": f"Amount: Rs.{total_amount:,.2f}"})

    if not invoice_date:
        checks.append({"check": "invoice_date", "passed": False, "message": "Invoice date is required"})
    else:
        checks.append({"check": "invoice_date", "passed": True, "message": f"Date: {invoice_date}"})

    failed = [c for c in checks if not c.get("passed")]
    if failed:
        return {
            "passed": False,
            "checks": checks,
            "message": f"Production mode: {len(failed)} mandatory check(s) failed",
        }

    return {
        "passed": True,
        "checks": checks,
        "message": "All mandatory checks passed",
    }


# =====================================================================
# P1 — MONITORING / ALERTING
# =====================================================================

class AlertPayload(BaseModel):
    level: str = "info"
    category: str = "general"
    message: str
    details: dict = {}


@app.post("/api/v3/admin/alerts")
async def receive_alert(
    payload: AlertPayload,
    current_user: dict = Depends(get_authenticated_user),
):
    if not _PRODUCTION_MODE:
        return {"status": "accepted", "mode": "development"}

    user_id = current_user.get("user_id", current_user.get("email", ""))
    alert_doc = {
        "user_id": user_id,
        "level": payload.level,
        "category": payload.category,
        "message": payload.message,
        "details": payload.details,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$push": {"alerts": {"$each": [alert_doc], "$slice": -100}}},
            upsert=True,
        )

    logger.warning("ALERT [%s] %s: %s", payload.level, payload.category, payload.message)
    return {"status": "accepted", "mode": "production"}


@app.get("/api/v3/admin/alerts")
async def list_alerts(
    limit: int = Query(50, le=200),
    current_user: dict = Depends(get_authenticated_user),
):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            alerts = org.get("alerts", [])
            return {"alerts": alerts[-limit:], "count": len(alerts)}
    return {"alerts": [], "count": 0}


# =====================================================================
# P1 — REPLAY SYSTEM
# =====================================================================

class ReplayRequest(BaseModel):
    invoice_id: int
    from_step: str = "extract"
    force: bool = False


class ReplayResponse(BaseModel):
    invoice_id: int
    replayed_from: str
    steps: list[dict]
    final_status: str
    result: dict


@app.post("/api/v3/invoices/{invoice_id}/replay")
async def replay_invoice(
    invoice_id: int,
    request: ReplayRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Replay invoice processing from a given step (extract, validate, xml, sync)."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    inv = await db.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    steps = []
    final_status = "replayed"
    result = {}

    if request.from_step in ("extract", "validate", "xml", "sync"):
        extracted = inv.get("extracted", {})
        if not extracted:
            final_status = "failed"
            steps.append({"step": "extract", "passed": False, "message": "No extracted data found"})
            return {"invoice_id": invoice_id, "replayed_from": request.from_step, "steps": steps, "final_status": final_status, "result": result}

        steps.append({"step": "extract", "passed": True, "message": f"Loaded {len(extracted)} fields"})

        if request.from_step in ("validate", "xml", "sync"):
            try:
                user_cfg = _user_config_from_current(current_user)
                _, usr_cfg, _ = _make_xml_generator(user_cfg)
                standard = _legacy_to_standard(extracted, cfg=usr_cfg)
                validation_result = validate_invoice_for_xml(standard)
                steps.append({"step": "validate", "passed": validation_result.passed, "message": f"Validation: {validation_result.passed}"})
                result["validation"] = validation_result.to_dict()
            except Exception as e:
                steps.append({"step": "validate", "passed": False, "message": str(e)})
                final_status = "failed"

        if request.from_step in ("xml", "sync") and final_status != "failed":
            try:
                user_cfg = _user_config_from_current(current_user)
                xml_gen, usr_cfg, active_company = _make_xml_generator(user_cfg)
                standard = _legacy_to_standard(extracted, cfg=usr_cfg)
                xml_str = xml_gen.generate(standard, company_name=active_company)
                xml_validation = validate_xml_output(xml_str)
                steps.append({"step": "xml", "passed": not xml_validation.errors, "message": f"XML generated, {len(xml_validation.errors)} issues"})
                result["xml"] = xml_str
                result["xml_issues"] = xml_validation.errors

                await db.update_invoice(invoice_id, {
                    "xml_content": xml_str,
                    "xml_generated": True,
                    "xml_issues": xml_validation.errors,
                })
            except Exception as e:
                steps.append({"step": "xml", "passed": False, "message": str(e)})
                final_status = "failed"

    replay_doc = {
        "invoice_id": invoice_id,
        "replayed_from": request.from_step,
        "steps": steps,
        "final_status": final_status,
        "replayed_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
    }
    if db.invoices is not None:
        await db.execute_db_write_with_retry(
            db.invoices.update_one,
            {"display_id": invoice_id},
            {"$push": {"replay_history": {"$each": [replay_doc], "$slice": -20}}},
        )

    return {"invoice_id": invoice_id, "replayed_from": request.from_step, "steps": steps, "final_status": final_status, "result": result}


# =====================================================================
# P1 — METRICS DASHBOARD
# =====================================================================

@app.get("/api/v3/metrics")
async def metrics_dashboard(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.invoices is None:
        return _empty_metrics()

    now = datetime.now(timezone.utc)
    last_24h = now - __import__('datetime').timedelta(hours=24)
    last_7d = now - __import__('datetime').timedelta(days=7)

    pipeline_xml = [
        {"$match": {"user_id": user_id, "xml_generated": True}},
        {"$group": {"_id": None, "count": {"$sum": 1}}},
    ]
    xml_success = 0
    xml_cursor = await db.invoices.aggregate(pipeline_xml).to_list(length=1)
    if xml_cursor:
        xml_success = xml_cursor[0].get("count", 0)

    pipeline_exported = [
        {"$match": {"user_id": user_id, "status": "exported"}},
        {"$group": {"_id": None, "count": {"$sum": 1}}},
    ]
    import_success = 0
    exported_cursor = await db.invoices.aggregate(pipeline_exported).to_list(length=1)
    if exported_cursor:
        import_success = exported_cursor[0].get("count", 0)

    pipeline_errors = [
        {"$match": {"user_id": user_id, "status": "sync_error"}},
        {"$group": {"_id": "$sync_error", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    top_errors = await db.invoices.aggregate(pipeline_errors).to_list(length=10)

    total_invoices = await db.invoices.count_documents({"user_id": user_id})
    validation_passed = 0
    validation_failed = 0
    pipeline_validation = [
        {"$match": {"user_id": user_id}},
        {"$project": {"validation": 1}},
    ]
    async for doc in db.invoices.aggregate(pipeline_validation):
        val = doc.get("validation") or {}
        if val.get("passed") or val.get("decision", {}).get("decision") == "high":
            validation_passed += 1
        else:
            validation_failed += 1

    avg_processing_ms = 0
    pipeline_processing = [
        {"$match": {"user_id": user_id, "processing_duration_ms": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": None, "avg_ms": {"$avg": "$processing_duration_ms"}}},
    ]
    proc_cursor = await db.invoices.aggregate(pipeline_processing).to_list(length=1)
    if proc_cursor:
        avg_processing_ms = round(proc_cursor[0].get("avg_ms", 0), 1)

    import_success_rate = round(import_success / max(total_invoices, 1) * 100, 1)
    xml_success_rate = round(xml_success / max(total_invoices, 1) * 100, 1)

    return {
        "total_invoices": total_invoices,
        "xml_success": xml_success,
        "xml_success_rate": xml_success_rate,
        "import_success": import_success,
        "import_success_rate": import_success_rate,
        "validation_passed": validation_passed,
        "validation_failed": validation_failed,
        "avg_processing_ms": avg_processing_ms,
        "top_errors": [{"error": e.get("_id", ""), "count": e.get("count", 0)} for e in top_errors],
    }


def _empty_metrics():
    return {
        "total_invoices": 0,
        "xml_success": 0,
        "xml_success_rate": 0,
        "import_success": 0,
        "import_success_rate": 0,
        "validation_passed": 0,
        "validation_failed": 0,
        "avg_processing_ms": 0,
        "top_errors": [],
    }


# =====================================================================
# P2 — LEARNING ENGINE ENHANCEMENTS
# =====================================================================

@app.get("/api/v3/learning/stats")
async def learning_stats(current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    stats = _learner.stats()
    memory = await db.get_correction_memory(email)
    stats["corrections_count"] = len(memory)
    return stats


@app.post("/api/v3/learning/teach")
async def learn_from_correction(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    await _learner.learn(body.description, body.ledger, email=email)
    rule = LedgerRule(
        pattern=body.description.lower().strip(),
        target_ledger=body.ledger,
        match_type=MatchType.KEYWORD,
        confidence=1.0,
    )
    _api_rules_engine.add_rule(rule)
    return {"ok": True, "rule": rule.to_dict()}


@app.get("/api/v3/learning/corrections")
async def learning_corrections(current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    memory = await db.get_correction_memory(email)
    return {"corrections": memory, "count": len(memory)}


# =====================================================================
# P2 — UX PROGRESS FEEDBACK
# =====================================================================

@app.get("/api/v3/invoices/{invoice_id}/progress")
async def invoice_progress(invoice_id: str, current_user: dict = Depends(get_authenticated_user)):
    try:
        obj_id = ObjectId(invoice_id)
    except Exception:
        raise HTTPException(400, "Invalid invoice ID format")

    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.invoices is not None:
        doc = await db.invoices.find_one({"_id": obj_id, "user_id": user_id})
        if not doc:
            raise HTTPException(404, "Invoice not found")

        state_entry = processing_tasks.get(invoice_id)
        state = state_entry[0] if isinstance(state_entry, tuple) else (state_entry or "queued")

        progress_map = {
            "queued": {"step": "queued", "percent": 5, "message": "File received, waiting for extraction..."},
            "processing": {"step": "extracting", "percent": 20, "message": "Extracting text from invoice..."},
            "validating": {"step": "validating", "percent": 50, "message": "Validating GST and amounts..."},
            "generating_xml": {"step": "generating_xml", "percent": 75, "message": "Generating Tally XML..."},
            "completed": {"step": "completed", "percent": 100, "message": "Processing complete"},
            "failed": {"step": "failed", "percent": 0, "message": doc.get("sync_error") or "Processing failed"},
        }

        progress = progress_map.get(state, {"step": state, "percent": 0, "message": "Unknown state"})
        progress["status"] = doc.get("status", "processing_queued")
        progress["display_id"] = doc.get("display_id")
        progress["xml_generated"] = doc.get("xml_generated", False)
        return progress

    return {"step": "unknown", "percent": 0, "message": "Database not available", "status": "unknown"}


# =====================================================================
# SYSTEM CONFIG
# =====================================================================

@app.get("/api/v3/system/config")
async def system_config(current_user: dict = Depends(get_authenticated_user)):
    return {
        "production_mode": _PRODUCTION_MODE,
        "version": "3.3",
        "features": {
            "dry_run": True,
            "idempotency": True,
            "replay": True,
            "monitoring": True,
            "learning_engine": True,
            "south_indian_invoices": True,
        },
        "max_concurrent_extractions": MAX_CONCURRENT_EXTRACTIONS,
    }
