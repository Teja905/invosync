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

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import database as db
from extractors import ExtractionPipeline
from xml_generator import TallyXmlGenerator
from validation_layer import validate_invoice_for_xml, validate_xml_output
from company_config import CompanyConfig
from ledger_mapping import LedgerMappingEngine
from gst_engine import determine_gst_type, compute_tax_from_items, validate_gstin
from voucher_classifier import classify_voucher_type, classify_service_vs_goods
from ocr_postproc import fix_gstin, fix_date, fix_amount, clean_extracted_invoice_payload
from core.logging import get_logger
from core.debug import time_it
from schemas import (
    StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry,
    DocumentClass, ALLOWED_GST_SLABS, GST_STATE_CODES,
)
import validation as val
# AUTH DISABLED — see _default_user() below
# from auth import router as auth_router, get_current_user


load_dotenv()

logger = get_logger(__name__)


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
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000,https://invosync.vercel.app").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    allow_credentials=True,
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

# AUTH DISABLED
# app.include_router(auth_router)

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
]


def _user_config_from_current(current_user: dict) -> dict:
    """Extract company config fields from current_user (enriched from DB)."""
    cfg = {}
    for field in _COMPANY_CONFIG_FIELDS:
        val = current_user.get(field)
        if val:
            cfg[field] = val.strip() if isinstance(val, str) else val
    return cfg


def _make_xml_generator(user_cfg: dict) -> TallyXmlGenerator:
    """Create a per-request XML generator with user config overrides."""
    cfg = _company_config
    if user_cfg:
        cfg = CompanyConfig(user_config=user_cfg)
    return TallyXmlGenerator(cfg), cfg


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
    }
    user_id = "default"
    base.update({k: v for k, v in _config_overrides.get(user_id, {}).items() if v})
    return base


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
            inv_display_id, _ = await db.insert_invoice(
                user_id=user_id, client_id=client_id,
                extracted=data, validation=validation,
                file_hash=file_hash, image_data=image_b64,
            )
            if validation.get("decision") == "high" and db.invoices is not None:
                await db.update_invoice_status(inv_display_id, "validated")

            await db.invoices.update_one(
                {"_id": inv_id},
                {"$set": {"status": "draft", "display_id": inv_display_id, "extracted": data, "validation": validation, "image_data": image_b64}}
            )
            processing_tasks[inv_key] = ("completed", time.monotonic())
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
async def create_client(data: ClientCreate, current_user: dict = Depends(_default_user)):
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
async def list_clients(current_user: dict = Depends(_default_user)):
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
async def get_client(client_id: int, current_user: dict = Depends(_default_user)):
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
async def update_client(client_id: int, data: ClientUpdate, current_user: dict = Depends(_default_user)):
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
async def delete_client(client_id: int, current_user: dict = Depends(_default_user)):
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
async def list_corrections(current_user: dict = Depends(_default_user)):
    email = current_user.get("email", "")
    memory = await db.get_correction_memory(email)
    return {"corrections": memory, "count": len(memory)}


class CorrectionSave(BaseModel):
    description: str
    ledger: str


@app.post("/corrections")
async def save_correction(body: CorrectionSave, current_user: dict = Depends(_default_user)):
    email = current_user.get("email", "")
    await db.save_correction_memory(email, body.description, body.ledger)
    return {"ok": True, "saved": f"{body.description.lower().strip()} → {body.ledger}"}


@app.delete("/corrections")
async def clear_corrections(current_user: dict = Depends(_default_user)):
    email = current_user.get("email", "")
    await db.users.update_one({"email": email.lower().strip()}, {"$set": {"correction_memory": {}}})
    return {"ok": True, "cleared": True}


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
    current_user: dict = Depends(_default_user),
):
    if db.clients is not None:
        client = await db.get_client(client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if client.get("user_id") != user_id:
            raise HTTPException(403, "Access denied")

    if not file.content_type or not (file.content_type.startswith("image/") or file.content_type == "application/pdf"):
        raise HTTPException(400, "Only image and PDF files are supported")

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
async def extract_status(invoice_id: str, current_user: dict = Depends(_default_user)):
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
async def preview_masters(data: InvoiceDataLegacy, current_user: dict = Depends(_default_user)):
    """Preview what masters will be created before generating XML."""
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
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
async def pre_import_check(data: InvoiceDataLegacy, current_user: dict = Depends(_default_user)):
    """Full pre-import readiness check: masters, warnings, company, voucher info."""
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
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
async def generate_xml(data: InvoiceDataLegacy, force: bool = Query(False), current_user: dict = Depends(_default_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
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

        xml_str = xml_gen.generate(standard)
        xml_validation = validate_xml_output(xml_str)
        old_validation = val.run_full_validation(raw, [])

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

        return Response(content=xml_str, media_type="text/plain")
    except Exception as e:
        logger.error("XML GENERATION ERROR: %s", e)
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.post("/generate-xml/v3")
async def generate_xml_v3(data: dict, current_user: dict = Depends(_default_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)
        if not validation_result.passed:
            return {
                "valid": False,
                "validation": validation_result.to_dict(),
                "message": "Validation failed. Correct errors before generating XML.",
            }
        xml_str = xml_gen.generate(standard)
        xml_validation = validate_xml_output(xml_str)
        return {
            "valid": True,
            "xml": xml_str,
            "validation": validation_result.to_dict(),
            "xml_validation": xml_validation.to_dict(),
        }
    except Exception as e:
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.get("/api/v3/validate")
async def validate_standardized(data: dict, current_user: dict = Depends(_default_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        _, usr_cfg = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        result = validate_invoice_for_xml(standard)
        return {"valid": result.passed, **result.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"Validation error: {str(e)}")


@app.post("/generate-xml/{invoice_id}")
async def generate_xml_for(
    invoice_id: int, data: InvoiceDataLegacy, force: bool = Query(False),
    current_user: dict = Depends(_default_user),
):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
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

        xml_str = xml_gen.generate(standard)
        xml_issues_obj = validate_xml_output(xml_str)
        validation = val.run_full_validation(raw, [])
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
        return Response(content=xml_str, media_type="text/plain")
    except Exception as e:
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.post("/invoices/{invoice_id}/generate")
async def generate_from_stored(
    invoice_id: int, force: bool = Query(False),
    current_user: dict = Depends(_default_user),
):
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    data = record["extracted"]

    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
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

        xml_str = xml_gen.generate(standard)
        xml_validation = validate_xml_output(xml_str)
        old_validation = val.run_full_validation(data, [])
        await db.update_invoice(invoice_id, {
            "xml_generated": True, "xml_content": xml_str,
            "xml_issues": xml_validation.errors, "v3_validation": validation_result.to_dict(),
        })
        return {"valid": True, "xml": xml_str, "validation": old_validation, "xml_issues": xml_validation.errors}
    except Exception as e:
        logger.error("INVOICE XML GENERATION FAILED [%s]: %s", invoice_id, e)
        raise HTTPException(500, f"XML generation error: {str(e)}")


@app.get("/invoices")
async def list_invoices(
    client_id: Optional[int] = Query(None),
    current_user: dict = Depends(_default_user),
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
        })
    return result


@app.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: int, current_user: dict = Depends(_default_user)):
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
async def get_invoice_xml(invoice_id: int, current_user: dict = Depends(_default_user)):
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
async def get_invoice_image(invoice_id: int, current_user: dict = Depends(_default_user)):
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
async def update_invoice(invoice_id: int, data: InvoiceUpdatePayload, current_user: dict = Depends(_default_user)):
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


@app.post("/api/v3/invoices/{invoice_id}/confirm-review")
async def confirm_review(invoice_id: int, data: InvoiceUpdatePayload, current_user: dict = Depends(_default_user)):
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

    # Save and transition to validated
    set_fields = {"extracted": extracted_update, "status": "validated", "reviewed_at": datetime.now(timezone.utc).isoformat()}
    if ledgers:
        set_fields["item_ledgers"] = ledgers
    await db.update_invoice(invoice_id, set_fields)
    return {"ok": True, "id": invoice_id, "status": "validated", "message": "Invoice reviewed and confirmed"}


@app.get("/invoices/check-duplicate")
async def check_duplicate(vendor: str, invoice_no: str, current_user: dict = Depends(_default_user)):
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
async def get_config(current_user: dict = Depends(_default_user)):
    user_cfg = _user_config_from_current(current_user)
    if user_cfg:
        return user_cfg
    return _company_config.to_env_config()


@app.post("/api/v3/config")
async def save_config(data: dict, current_user: dict = Depends(_default_user)):
    user_id = current_user.get("user_id", "default")
    allowed = set(_COMPANY_CONFIG_FIELDS)
    clean = {k: v for k, v in data.items() if k in allowed and v}
    if clean:
        if user_id not in _config_overrides:
            _config_overrides[user_id] = {}
        _config_overrides[user_id].update(clean)
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
async def generate_v3(data: dict, current_user: dict = Depends(_default_user)):
    try:
        user_cfg = _user_config_from_current(current_user)
        xml_gen, usr_cfg = _make_xml_generator(user_cfg)
        standard = _legacy_to_standard(data, cfg=usr_cfg)
        validation_result = validate_invoice_for_xml(standard)
        xml_str = xml_gen.generate(standard)
        xml_validation = validate_xml_output(xml_str)
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
async def suggest_voucher_type(data: dict, current_user: dict = Depends(_default_user)):
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
    current_user: dict = Depends(_default_user),
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
async def banking_rules_list(current_user: dict = Depends(_default_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    rules = await db.list_banking_rules(user_id)
    return [{"id": str(r["_id"]), "keyword": r["keyword"], "voucher_type": r["voucher_type"], "target_ledger": r["target_ledger"]} for r in rules]


@app.post("/api/v3/banking/rules")
async def banking_rules_create(body: dict, current_user: dict = Depends(_default_user)):
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
async def banking_rules_delete(rule_id: str, current_user: dict = Depends(_default_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    await db.delete_banking_rule(rule_id, user_id)
    return {"status": "ok"}


@app.post("/api/v3/banking/process")
async def banking_process_statement(body: dict, current_user: dict = Depends(_default_user)):
    from ledger_mapping import apply_banking_rules_to_transactions
    from xml_generator import generate_tally_bank_xml
    user_id = current_user.get("user_id", current_user.get("email", ""))
    transactions = (body or {}).get("transactions", [])
    bank_ledger = (body or {}).get("bank_ledger", "Bank")
    if not transactions:
        raise HTTPException(400, "transactions list is required")
    user_cfg = _user_config_from_current(current_user)
    rules = await db.list_banking_rules(user_id)
    processed = apply_banking_rules_to_transactions(transactions, rules)
    xml = generate_tally_bank_xml(processed, bank_ledger_name=bank_ledger)
    return {
        "total": len(processed),
        "processed": processed,
        "xml": xml,
    }


class CompanySyncPayload(BaseModel):
    companies: list[str]
    tally_reachable: bool = False
    connector_version: str = ""


class LedgerSyncPayload(BaseModel):
    ledgers: list[str]


class BulkLedgerMapPayload(BaseModel):
    invoice_ids: list[int]
    target_ledger: str


@app.post("/api/v3/sync/companies")
async def receive_active_tally_companies(payload: CompanySyncPayload, current_user: dict = Depends(_default_user)):
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
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": update},
            upsert=True,
        )
    return {"status": "synced", "tally_reachable": payload.tally_reachable, "count": len(payload.companies)}


@app.post("/api/v3/sync/ledgers")
async def receive_tally_ledgers(payload: LedgerSyncPayload, current_user: dict = Depends(_default_user)):
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
async def get_cached_ledgers(current_user: dict = Depends(_default_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"ledgers": org.get("ledger_cache", [])}
    return {"ledgers": []}


@app.post("/api/v3/invoices/bulk-map")
async def bulk_map_ledgers_before_sync(payload: BulkLedgerMapPayload, current_user: dict = Depends(_default_user)):
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
    current_user: dict = Depends(_default_user),
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
    current_user: dict = Depends(_default_user),
):
    """Called by C# Tally Connector after successful Tally import."""
    inv = await db.get_invoice(display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.update_invoice_status(display_id, "exported")
    return {"status": "ok", "message": f"Invoice #{display_id} marked as exported"}


@app.post("/api/v3/sync/error/{display_id}")
async def sync_error(
    display_id: int,
    body: dict,
    current_user: dict = Depends(_default_user),
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
    return {"status": "ok", "message": f"Sync error recorded for invoice #{display_id}"}


@app.get("/api/v3/tally/status")
async def tally_status(current_user: dict = Depends(_default_user)):
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
            companies = org.get("active_tally_companies", [])
            if status["tally_reachable"] and companies:
                status["company"] = companies[0]
                status["connected"] = True
    return status


@app.post("/api/v3/invoices/{display_id}/sync-now")
async def trigger_invoice_sync(
    display_id: int,
    current_user: dict = Depends(_default_user),
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
