"""Tally sync, connector, masters cache, and pre-flight endpoints."""

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db
from api.app_state import company_config as _company_config, tally_sync_manager
from api.deps import get_authenticated_user
from audit_log import audit as audit_logger
from config.settings import user_config_from_current, make_xml_generator, run_validation_pipeline, config_overrides
from core.logging import get_logger
from core.metrics import metrics
from diagnostics import PreFlightDiagnostics

router = APIRouter()
logger = get_logger(__name__)


# ---- Payload Models ----


class CompanySyncPayload(BaseModel):
    companies: list[str]
    tally_reachable: bool = False
    connector_version: str = ""
    active_company: str = ""


class LedgerInfo(BaseModel):
    name: str
    parent: str = ""
    gst_type: str = ""  # "Input" | "Output" | "None"


class LedgerSyncPayload(BaseModel):
    ledgers: list[LedgerInfo | str]
    """Accepts both old format (list[str]) and new format (list[LedgerInfo])."""


class BulkLedgerMapPayload(BaseModel):
    invoice_ids: list[int]
    target_ledger: str


class ImportedVoucherPayload(BaseModel):
    import_source: str = "tally_pull"
    vouchers: list[dict]


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


class ImportReportPayload(BaseModel):
    invoice_display_id: int
    success: bool
    masters_created: list[str] = []
    voucher_id: str = ""
    tally_response: str = ""
    warnings: list[str] = []
    error: str = ""
    import_duration_ms: int = 0


# ---- Production Mode ----


_PRODUCTION_MODE = os.getenv("PRODUCTION_MODE", "").lower() in ("true", "1", "yes")


def _require_production_checks(invoice_data: dict, user_id: str) -> dict:
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
        return {"passed": False, "checks": checks, "message": f"Production mode: {len(failed)} mandatory check(s) failed"}
    return {"passed": True, "checks": checks, "message": "All mandatory checks passed"}


# ---- Connector Heartbeat / Company Sync ----


@router.post("/api/v3/sync/companies")
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
            db.organizations.update_one, {"org_id": user_id}, {"$set": update}, upsert=True,
        )
    return {"status": "synced", "tally_reachable": payload.tally_reachable, "count": len(payload.companies)}


@router.post("/api/v3/sync/active-company")
async def set_active_company(body: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    active_company = (body or {}).get("active_company", "")
    tally_reachable = (body or {}).get("tally_reachable", False)
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"active_company": active_company, "tally_reachable": tally_reachable}},
            upsert=True,
        )
    return {"status": "ok", "active_company": active_company}


def _normalize_ledger_entry(entry: LedgerInfo | str | dict) -> dict:
    """Normalize a ledger entry to dict{name, parent, gst_type} regardless of input format."""
    if isinstance(entry, str):
        return {"name": entry, "parent": "", "gst_type": ""}
    if isinstance(entry, dict):
        return {"name": entry.get("name", ""), "parent": entry.get("parent", ""), "gst_type": entry.get("gst_type", "")}
    return {"name": entry.name, "parent": entry.parent or "", "gst_type": entry.gst_type or ""}


@router.post("/api/v3/sync/ledgers")
async def receive_tally_ledgers(payload: LedgerSyncPayload, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    normalized = [_normalize_ledger_entry(e) for e in payload.ledgers]
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"ledger_cache": normalized, "last_ledger_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(normalized)}


@router.get("/api/v3/sync/ledgers")
async def get_cached_ledgers(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"ledgers": org.get("ledger_cache", [])}
    return {"ledgers": []}


# ---- Ledger Discovery (Parent-Group Auto-Detection) ----


@router.post("/api/v3/sync/discover-ledgers")
async def discover_ledgers(current_user: dict = Depends(get_authenticated_user)):
    """Score all cached Tally ledgers for every role (PURCHASE, SALES, BANK, etc.)
    using parent-group-based matching. Returns the top suggestion per role + all scored ledgers."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    ledgers = []
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            ledgers = org.get("ledger_cache", [])

    from ledger_mapping import LedgerDiscoveryEngine
    engine = LedgerDiscoveryEngine()
    all_suggestions = engine.discover_all(ledgers)
    return {
        "suggestions": {
            role: [s.model_dump() for s in suggestions]
            for role, suggestions in all_suggestions.items()
        },
        "ledger_count": len(ledgers),
    }


# ---- Ledger Selection Validation ----

class LedgerSelectionValidationItem(BaseModel):
    role: str
    ledger_name: str
    parent: str = ""

class LedgerSelectionValidationRequest(BaseModel):
    selections: list[LedgerSelectionValidationItem]


@router.post("/api/v3/sync/validate-ledger-selection")
async def validate_ledger_selection(
    request: LedgerSelectionValidationRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Validate each user-selected ledger for its role.
    Checks parent group, common name, and universal group mappings.
    Returns scored suggestions + warnings when parent group doesn't match expected role."""
    from ledger_mapping import LedgerDiscoveryEngine
    engine = LedgerDiscoveryEngine()

    results = []
    for sel in request.selections:
        suggestion = engine.validate_selection(sel.ledger_name, sel.parent, sel.role)
        expected = engine.expected_parent_groups_text(sel.role)
        is_mismatch = suggestion.confidence < 60 and suggestion.confidence > 0
        results.append({
            "role": sel.role,
            "ledger_name": sel.ledger_name,
            "parent": sel.parent,
            "confidence": suggestion.confidence,
            "match_reason": suggestion.match_reason,
            "expected_parent_groups": expected,
            "is_mismatch": is_mismatch,
        })

    mismatches = [r for r in results if r["is_mismatch"]]
    return {
        "results": results,
        "mismatch_count": len(mismatches),
        "all_ok": len(mismatches) == 0,
    }


# ---- Bulk Ledger Map ----


@router.post("/api/v3/invoices/bulk-map")
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


# ---- Connector Polling Endpoints ----


@router.get("/api/v3/sync/pending")
async def sync_pending(
    current_user: dict = Depends(get_authenticated_user),
    limit: int = Query(50, le=200),
):
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


@router.post("/api/v3/sync/confirm/{display_id}")
async def sync_confirm(display_id: int, current_user: dict = Depends(get_authenticated_user)):
    inv = await db.get_invoice(display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.update_invoice_status(display_id, "exported")
    metrics.record_tally_synced()
    await audit_logger.log_sync(user_id, display_id, True)
    await audit_logger.log_invoice_action(
        "sync", display_id, user_id, details="status->exported",
        snapshot={"status": inv.get("status"), "synced_at": inv.get("synced_at")},
    )
    return {"status": "ok", "message": f"Invoice #{display_id} marked as exported"}


@router.post("/api/v3/sync/error/{display_id}")
async def sync_error(display_id: int, body: dict, current_user: dict = Depends(get_authenticated_user)):
    inv = await db.get_invoice(display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    error_msg = (body or {}).get("error", "Unknown Tally error")
    await db.update_invoice_status(display_id, "sync_error", sync_error=error_msg)
    await audit_logger.log_sync(user_id, display_id, False, error_msg)
    return {"status": "ok", "message": f"Sync error recorded for invoice #{display_id}"}


# ---- Tally Status & Config ----


@router.get("/api/v3/tally/status")
async def tally_status(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    status = {
        "connected": False, "company": "", "last_ping": None,
        "connector_online": False, "tally_reachable": False, "connector_version": "",
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


@router.get("/api/v3/tally/config")
async def tally_config(current_user: dict = Depends(get_authenticated_user)):
    user_cfg = user_config_from_current(current_user)
    return {"tally_password": user_cfg.get("tally_password", ""), "active_company": user_cfg.get("active_company", "")}


# ---- Sync Job Status ----


@router.get("/api/v3/sync/job/{job_id}")
async def get_sync_job_status(job_id: str, current_user: dict = Depends(get_authenticated_user)):
    job = tally_sync_manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Sync job not found")
    return {
        "job_id": job.job_id,
        "invoice_id": job.invoice_display_id,
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


# ---- Import from Tally Pull ----


@router.post("/api/v3/sync/import-from-tally")
async def import_from_tally(payload: ImportedVoucherPayload, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    imported = []
    for v in payload.vouchers:
        vendor = v.get("party_name", v.get("vendor_name", "Unknown"))
        inv_num = v.get("voucher_number", v.get("invoice_number", ""))
        amount = v.get("amount", v.get("total_amount", 0))
        voucher_type = v.get("voucher_type", "Purchase")
        date = v.get("date", "")
        extracted = {"vendor_name": vendor, "invoice_number": inv_num, "total_amount": amount, "date": date, "voucher_type": voucher_type}
        if db.invoices is not None:
            company_id = v.get("company_id")
            inv_display_id, _inv_id = await db.insert_invoice(
                user_id=user_id, client_id=v.get("client_id", 0),
                extracted=extracted, company_id=company_id,
                validation={"source": "tally_pull", "imported_at": datetime.now(timezone.utc).isoformat()},
            )
            uploaded_by = current_user.get("email", "default@local")
            await db.execute_db_write_with_retry(
                db.invoices.update_one, {"display_id": inv_display_id},
                {"$set": {"source": "tally_pull", "uploaded_by": uploaded_by}},
            )
            imported.append({"display_id": inv_display_id, "vendor_name": vendor, "invoice_number": inv_num, "total_amount": amount})
    return {"imported": len(imported), "invoices": imported}


# ---- Dashboard Sync Trigger ----


@router.post("/api/v3/invoices/{display_id}/sync-now")
async def trigger_invoice_sync(display_id: int, current_user: dict = Depends(get_authenticated_user)):
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
    job_id = tally_sync_manager.create_job(display_id)
    await db.execute_db_write_with_retry(
        db.invoices.update_one, {"display_id": display_id},
        {"$set": {"status": "validated", "priority_sync": True, "sync_triggered_at": datetime.now(timezone.utc).isoformat(), "sync_job_id": job_id}},
    )
    return {"status": "queued", "job_id": job_id, "message": f"Invoice #{display_id} queued for Tally sync. The connector will pick it up within 30 seconds."}


@router.get("/api/v3/invoices/pending-tally-push")
async def pending_tally_push(current_user: dict = Depends(get_authenticated_user), limit: int = Query(50, le=200)):
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


@router.post("/api/v3/invoices/{invoice_id}/tally-result")
async def tally_push_result(invoice_id: int, body: dict, current_user: dict = Depends(get_authenticated_user)):
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
    job_id = body.get("job_id") or inv.get("sync_job_id")
    if job_id:
        tally_sync_manager.update_status(
            job_id,
            "success" if success else "failed",
            error=None if success else (error_msg or "Unknown Tally error"),
        )
    if success:
        await db.update_invoice_status(invoice_id, "exported")
        return {"status": "ok", "message": f"Invoice #{invoice_id} marked as exported"}
    else:
        await db.update_invoice_status(invoice_id, "sync_error", sync_error=error_msg or "Unknown Tally error")
        return {"status": "error", "message": f"Sync error recorded for invoice #{invoice_id}"}


# ---- Tally Masters CRUD ----


@router.get("/api/v3/tally/masters/companies")
async def tally_masters_companies(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"companies": org.get("active_tally_companies", [])}
    return {"companies": []}


@router.get("/api/v3/tally/masters/ledgers")
async def tally_masters_ledgers(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"ledgers": org.get("ledger_cache", [])}
    return {"ledgers": []}


@router.post("/api/v3/tally/masters/ledgers")
async def tally_masters_ledgers_update(payload: LedgerSyncPayload, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"ledger_cache": payload.ledgers, "last_ledger_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(payload.ledgers)}


@router.get("/api/v3/tally/masters/stock-items")
async def tally_masters_stock_items(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"stock_items": org.get("stock_item_cache", [])}
    return {"stock_items": []}


@router.post("/api/v3/tally/masters/stock-items")
async def tally_masters_stock_items_update(payload: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    stock_items = payload.get("stock_items", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"stock_item_cache": stock_items, "last_stock_item_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(stock_items)}


@router.get("/api/v3/tally/masters/voucher-types")
async def tally_masters_voucher_types(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"voucher_types": org.get("voucher_type_cache", [])}
    return {"voucher_types": []}


@router.post("/api/v3/tally/masters/voucher-types")
async def tally_masters_voucher_types_update(payload: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    voucher_types = payload.get("voucher_types", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"voucher_type_cache": voucher_types, "last_voucher_type_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(voucher_types)}


@router.get("/api/v3/tally/masters/groups")
async def tally_masters_groups(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"groups": org.get("group_cache", [])}
    return {"groups": []}


@router.post("/api/v3/tally/masters/groups")
async def tally_masters_groups_update(payload: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    groups = payload.get("groups", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"group_cache": groups, "last_group_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(groups)}


@router.get("/api/v3/tally/masters/units")
async def tally_masters_units(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            return {"units": org.get("unit_cache", [])}
    return {"units": []}


@router.post("/api/v3/tally/masters/units")
async def tally_masters_units_update(payload: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    units = payload.get("units", [])
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one, {"org_id": user_id},
            {"$set": {"unit_cache": units, "last_unit_sync": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return {"status": "synced", "count": len(units)}


# ---- Pre-flight / Diagnostics ----


@router.post("/api/v3/sync/dry-run")
async def sync_dry_run(request: DryRunRequest, current_user: dict = Depends(get_authenticated_user)):
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

    def _ledger_name_set(cache):
        """Extract ledger name strings from cache (supports both old str[] and new dict[] format)."""
        names = set()
        for entry in cache:
            if isinstance(entry, dict):
                names.add(entry.get("name", "").lower())
            else:
                names.add(entry.lower() if isinstance(entry, str) else str(entry).lower())
        return names

    if org:
        ledger_cache = org.get("ledger_cache", [])
        stock_item_cache = org.get("stock_item_cache", [])
        voucher_type_cache = org.get("voucher_type_cache", [])

        ledger_names = _ledger_name_set(ledger_cache)

        vendor_ledger_exists = vendor_name.lower() in ledger_names
        if vendor_ledger_exists:
            existing_masters.append(f"Ledger: {vendor_name}")
        else:
            masters_to_create.append(f"Ledger: {vendor_name}")
            warnings.append(f"Vendor ledger '{vendor_name}' will be created on import")

        purchase_ledger = user_config_from_current(current_user).get("purchase_ledger", "Purchase")
        purchase_exists = purchase_ledger.lower() in ledger_names
        if not purchase_exists:
            masters_to_create.append(f"Ledger: {purchase_ledger}")

        line_items = data.get("line_items") or []
        for item in line_items:
            desc = (item.get("description") or "").strip()
            hsn = (item.get("hsn_sac") or "").strip()
            if desc and desc.lower() not in ledger_names:
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
            "user_id": user_id, "extracted.vendor_name": vendor_name, "extracted.invoice_number": invoice_number,
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


# ---- Smart Pre-Flight Diagnostics ----

class PreFlightRequest(BaseModel):
    invoice_data: dict
    check_duplicates: bool = True

@router.post("/api/v3/sync/preflight-diagnostics")
async def preflight_diagnostics(request: PreFlightRequest, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    data = request.invoice_data
    org = await db.organizations.find_one({"org_id": user_id}) if db.organizations is not None else None
    ledger_cache = org.get("ledger_cache", []) if org else []
    group_cache = org.get("group_cache", []) if org else []
    voucher_type_cache = org.get("voucher_type_cache", []) if org else []
    stock_item_cache = org.get("stock_item_cache", []) if org else []
    user_cfg = user_config_from_current(current_user)
    engine = PreFlightDiagnostics(
        invoice_data=data, ledger_cache=ledger_cache, group_cache=group_cache,
        voucher_type_cache=voucher_type_cache, stock_item_cache=stock_item_cache,
        user_config=user_cfg,
    )
    report = engine.run_all()
    return report.model_dump()


# ---- Auto-Create Masters ----

class MissingMasterPayload(BaseModel):
    type: str  # "group" | "ledger"
    name: str
    parent: str = ""


class AutoCreateMastersRequest(BaseModel):
    company_name: str = ""
    masters: list[MissingMasterPayload]
    invoice_id: int | None = None


class MasterEditPayload(BaseModel):
    original_description: str = ""
    type: str  # "group" | "ledger"
    name: str
    parent: str


class ApplyMasterEditsRequest(BaseModel):
    invoice_id: int | None = None
    company_name: str = ""
    edits: list[MasterEditPayload]


@router.post("/api/v3/sync/apply-master-edits")
async def apply_master_edits(
    request: ApplyMasterEditsRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Apply user edits to missing masters and save corrections for learning."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    user_cfg = user_config_from_current(current_user)
    corrections = user_cfg.get("correction_memory", {}) or {}

    # Save corrections: original_description → new parent (for learning)
    save_count = 0
    for edit in request.edits:
        orig = edit.original_description.strip()
        new_parent = edit.parent.strip()
        if orig and new_parent and edit.type == "ledger":
            # Only save if parent changed from original suggestion
            corrections[orig] = new_parent
            save_count += 1

    # Persist corrections back to user config
    if save_count and user_id:
        if user_id not in config_overrides:
            config_overrides[user_id] = {}
        config_overrides[user_id]["correction_memory"] = corrections
        # Also save to LedgerLearner for cross-user learning
        try:
            from api.app_state import learner as _learner
            for desc, parent in corrections.items():
                await _learner.record_correction(user_id, desc, parent)
            await _learner.save()
        except Exception:
            logger.warning("Failed to persist corrections to LedgerLearner", exc_info=True)

    # Now create the masters with edited values (reuse logic)
    masters = [MissingMasterPayload(type=e.type, name=e.name, parent=e.parent) for e in request.edits]
    create_req = AutoCreateMastersRequest(
        invoice_id=request.invoice_id,
        company_name=request.company_name,
        masters=masters,
    )
    # Build XML
    from constants.tally_groups import EscapeXmlForTally

    group_xml = ""
    ledger_xml = ""
    for m in masters:
        if m.type == "group":
            group_xml += f"""<OBJECT>\n<GROUP ACTION="Create">\n<NAME>{EscapeXmlForTally(m.name)}</NAME>\n<PARENT>{EscapeXmlForTally(m.parent)}</PARENT>\n</GROUP>\n</OBJECT>\n"""
        elif m.type == "ledger":
            ledger_xml += f"""<OBJECT>\n<LEDGER ACTION="Create">\n<NAME>{EscapeXmlForTally(m.name)}</NAME>\n<PARENT>{EscapeXmlForTally(m.parent)}</PARENT>\n</LEDGER>\n</OBJECT>\n"""

    company_name = request.company_name or user_cfg.get("company_name", "")
    master_xml = f"""<ENVELOPE>\n<HEADER>\n<VERSION>1</VERSION>\n<TALLYREQUEST>Import</TALLYREQUEST>\n<TYPE>Object</TYPE>\n</HEADER>\n<BODY>\n<DESC>\n<STATICVARIABLES>\n<SVCURRENTCOMPANY>{EscapeXmlForTally(company_name)}</SVCURRENTCOMPANY>\n</STATICVARIABLES>\n</DESC>\n{group_xml}{ledger_xml}</BODY>\n</ENVELOPE>"""

    prepended = False
    if request.invoice_id and db.invoices is not None:
        inv = await db.get_invoice(request.invoice_id)
        if inv:
            existing_xml = inv.get("xml_content", "")
            if existing_xml:
                updated_xml = master_xml.strip() + "\n" + existing_xml.strip()
                await db.execute_db_write_with_retry(
                    db.invoices.update_one,
                    {"display_id": request.invoice_id},
                    {"$set": {"xml_content": updated_xml}},
                )
                prepended = True

    return {
        "success": True,
        "corrections_saved": save_count,
        "master_xml": master_xml,
        "prepended_to_invoice": prepended,
        "masters_count": len(masters),
        "message": f"Applied {len(masters)} master(s) with {save_count} correction(s) saved for learning.",
    }


@router.post("/api/v3/sync/auto-create-masters")
async def auto_create_masters(
    request: AutoCreateMastersRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Generate master creation XML for missing groups + ledgers.
    Then prepend it to the invoice's xml_content so the connector creates
    masters before the voucher on its next poll cycle.

    Returns the generated XML + whether each master was accepted."""
    from ledger_mapping import LedgerDiscoveryEngine
    from constants.tally_groups import EscapeXmlForTally

    engine = LedgerDiscoveryEngine()
    user_id = current_user.get("user_id", current_user.get("email", ""))

    # Build the multi-master XML
    # Groups first, then ledgers (Tally requires parent objects to exist first)
    group_xml = ""
    ledger_xml = ""

    for m in request.masters:
        if m.type == "group":
            group_xml += f"""<OBJECT>
<GROUP ACTION="Create">
<NAME>{EscapeXmlForTally(m.name)}</NAME>
<PARENT>{EscapeXmlForTally(m.parent)}</PARENT>
</GROUP>
</OBJECT>
"""
        elif m.type == "ledger":
            ledger_xml += f"""<OBJECT>
<LEDGER ACTION="Create">
<NAME>{EscapeXmlForTally(m.name)}</NAME>
<PARENT>{EscapeXmlForTally(m.parent)}</PARENT>
</LEDGER>
</OBJECT>
"""

    company_name = request.company_name or user_config_from_current(current_user).get("company_name", "")
    master_xml = f"""<ENVELOPE>
<HEADER>
<VERSION>1</VERSION>
<TALLYREQUEST>Import</TALLYREQUEST>
<TYPE>Object</TYPE>
</HEADER>
<BODY>
<DESC>
<STATICVARIABLES>
<SVCURRENTCOMPANY>{EscapeXmlForTally(company_name)}</SVCURRENTCOMPANY>
</STATICVARIABLES>
</DESC>
{group_xml}{ledger_xml}</BODY>
</ENVELOPE>"""

    # If invoice_id is provided, prepend this XML to the invoice's xml_content
    prepended = False
    if request.invoice_id and db.invoices is not None:
        inv = await db.get_invoice(request.invoice_id)
        if inv:
            existing_xml = inv.get("xml_content", "")
            if existing_xml:
                updated_xml = master_xml.strip() + "\n" + existing_xml.strip()
                await db.execute_db_write_with_retry(
                    db.invoices.update_one,
                    {"display_id": request.invoice_id},
                    {"$set": {"xml_content": updated_xml}},
                )
                prepended = True

    return {
        "success": True,
        "master_xml": master_xml,
        "prepended_to_invoice": prepended,
        "masters_count": len(request.masters),
        "groups": [m.name for m in request.masters if m.type == "group"],
        "ledgers": [m.name for m in request.masters if m.type == "ledger"],
        "message": f"Generated XML for {len(request.masters)} master(s). {'Prepended to invoice for connector pickup.' if prepended else ''}",
    }


# ---- Import Report ----


@router.post("/api/v3/sync/import-report")
async def sync_import_report(payload: ImportReportPayload, current_user: dict = Depends(get_authenticated_user)):
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
        db.invoices.update_one, {"display_id": payload.invoice_display_id},
        {"$set": {"last_import_report": report}},
    )
    return {"status": "ok", "report": report}


@router.get("/api/v3/sync/import-report/{invoice_display_id}")
async def get_import_report(invoice_display_id: int, current_user: dict = Depends(get_authenticated_user)):
    inv = await db.get_invoice(invoice_display_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if inv.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    return inv.get("last_import_report", {})


# ---- Idempotency (duplicate check for sync) ----


@router.post("/api/v3/sync/check-duplicate")
async def sync_check_duplicate(body: dict, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    vendor_name = (body.get("vendor_name") or "").strip()
    invoice_number = (body.get("invoice_number") or "").strip()
    total_amount = float(body.get("total_amount") or 0)
    invoice_date = (body.get("invoice_date") or "").strip()

    if not vendor_name or not invoice_number:
        return {"duplicate": False, "message": "vendor_name and invoice_number required"}

    if db.invoices is None:
        return {"duplicate": False, "message": "Database not available"}

    query = {"user_id": user_id, "extracted.vendor_name": vendor_name, "extracted.invoice_number": invoice_number}
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
