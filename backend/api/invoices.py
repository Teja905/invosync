"""Invoice CRUD, review, replay, progress, and preview-ledger endpoints."""

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from bson.objectid import ObjectId
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import Response, JSONResponse, StreamingResponse
from pydantic import BaseModel

import database as db
import validation as val
from api.app_state import company_config as _company_config, learner, queue_manager
from api.deps import get_authenticated_user
from api.helpers import legacy_to_standard as _legacy_to_standard, check_duplicate as _check_dup, resolve_config, mark_masters_created
from api.models import InvoiceDataLegacy, InvoiceUpdatePayload, LineItemModel
from audit_log import audit as audit_logger
from config.settings import run_validation_pipeline
from core.logging import get_logger
from validation_layer import validate_invoice_for_xml, validate_xml_output

router = APIRouter()
logger = get_logger(__name__)


# ---- Invoice CRUD ----


@router.get("/invoices")
async def list_invoices(
    client_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_authenticated_user),
):
    """List all invoices for the user, optionally filtered by client ID."""
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


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Retrieve a single invoice's extracted data and validation info."""
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


@router.get("/invoices/{invoice_id}/xml")
async def get_invoice_xml(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Download the generated Tally XML for an invoice."""
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


@router.get("/invoices/{invoice_id}/image")
async def get_invoice_image(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Stream the stored invoice image as a JPEG response."""
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


@router.put("/invoices/{invoice_id}")
async def update_invoice(invoice_id: int, data: InvoiceUpdatePayload, current_user: dict = Depends(get_authenticated_user)):
    """Update extracted invoice fields and line item ledger assignments."""
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


@router.get("/invoices/check-duplicate")
async def check_duplicate_route(vendor: str, invoice_no: str, current_user: dict = Depends(get_authenticated_user)):
    """Check whether an invoice with the given vendor and number already exists."""
    if db.invoices is None:
        return {"duplicate": False}
    user_id = current_user.get("user_id", current_user.get("email", ""))
    dup = await db.find_duplicate(vendor, invoice_no, user_id)
    if dup:
        return {"duplicate": True, "existing_id": dup.get("display_id"), "existing_date": dup.get("created_at")}
    return {"duplicate": False}


# ---- Preview Ledger ----


@router.get("/api/v3/invoices/{invoice_id}/preview-ledger")
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


# ---- Confirm Review ----


@router.post("/api/v3/invoices/{invoice_id}/confirm-review")
async def confirm_review(invoice_id: int, data: InvoiceUpdatePayload, current_user: dict = Depends(get_authenticated_user)):
    """Transition invoice from draft to validated after mandatory checks."""
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

    set_fields = {"extracted": extracted_update}
    pipe_report = None
    try:
        user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
        standard = _legacy_to_standard(extracted_update, cfg=usr_cfg, company_config=_company_config)
        xml_str = xml_gen.generate(standard, company_name=active_company)
        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            mark_masters_created(user_cfg, current_user.get("user_id", "default"))
        xml_validation = validate_xml_output(xml_str)
        pipe_report = run_validation_pipeline(standard, xml_str)
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

    await audit_logger.log_invoice_action(
        "confirm_review", invoice_id, current_user.get("user_id", current_user.get("email", "")),
        details="status->validated xml_generated=True",
        snapshot={"status": "draft", "xml_content": None, "xml_generated": False},
    )

    response_data = {
        "ok": True, "id": invoice_id, "status": "validated",
        "xml_generated": True,
        "message": "Invoice reviewed, confirmed, and XML generated. Ready for Tally sync.",
    }
    if pipe_report:
        response_data["validation_report"] = pipe_report
    return response_data


# ---- Validation Report ----


@router.get("/api/v3/validation-report/{invoice_id}")
async def get_validation_report(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Return the stored or freshly computed validation report for an invoice."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    stored = record.get("validation_report")
    if stored:
        return stored
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
        user_cfg, _, usr_cfg, _ = resolve_config(current_user)
        standard = _legacy_to_standard(extracted, cfg=usr_cfg, company_config=_company_config)
        xml_str = record.get("xml_content", "")
        report = run_validation_pipeline(standard, xml_str or None)
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


# ---- Smart Validation with Fix Suggestions ----

class FixSuggestion(BaseModel):
    field: str
    message: str
    fix_type: str  # "create_ledger", "correct_gstin", "set_field", "auto_detect"
    fix_label: str
    fix_payload: dict

class ValidationWithFixes(BaseModel):
    valid: bool
    blocking_errors: list[str]
    soft_errors: list[str]
    warnings: list[str]
    fix_suggestions: list[FixSuggestion]


@router.post("/api/v3/invoices/{invoice_id}/validate-with-fixes")
async def validate_with_fixes(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Validate an invoice and return actionable fix suggestions for each issue."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    extracted = record.get("extracted", {})
    if not extracted:
        return ValidationWithFixes(valid=False, blocking_errors=["No extracted data"], soft_errors=[], warnings=[], fix_suggestions=[])

    suggestions = []
    blocking = []
    soft = []
    warnings = []

    ledger_name = extracted.get("expense_ledger", "") or "Purchase"
    gstin = extracted.get("gstin", "") or extracted.get("vendor_gstin", "")
    vendor = extracted.get("vendor_name", "")
    total = extracted.get("total_amount", 0)

    if not vendor or not vendor.strip():
        blocking.append("Vendor name is missing")
        suggestions.append(FixSuggestion(
            field="vendor_name", message="Vendor name is required for Tally voucher",
            fix_type="set_field", fix_label="Enter vendor name manually",
            fix_payload={"field": "vendor_name", "value": ""},
        ))

    if not extracted.get("invoice_number"):
        blocking.append("Invoice number is missing")
        suggestions.append(FixSuggestion(
            field="invoice_number", message="Invoice number is required",
            fix_type="set_field", fix_label="Enter invoice number",
            fix_payload={"field": "invoice_number", "value": ""},
        ))

    if not total or float(total) <= 0:
        blocking.append("Valid total amount is required")

    if gstin and len(gstin) != 15:
        suggestions.append(FixSuggestion(
            field="gstin", message=f"GSTIN has {len(gstin)} characters, expected 15",
            fix_type="correct_gstin", fix_label="Auto-Correct GSTIN",
            fix_payload={"field": "gstin", "current": gstin, "suggestion": gstin.ljust(15, 'Z') if len(gstin) < 15 else gstin[:15]},
        ))

    if not record.get("xml_generated") and vendor and extracted.get("invoice_number"):
        warnings.append("XML not yet generated — click generate to create Tally voucher")

    return ValidationWithFixes(
        valid=len(blocking) == 0,
        blocking_errors=blocking,
        soft_errors=soft,
        warnings=warnings,
        fix_suggestions=suggestions,
    )


# ---- Bulk Operations ----

class BulkOperation(BaseModel):
    invoice_ids: list[int]

class BulkLedgerMap(BulkOperation):
    target_ledger: str

@router.post("/api/v3/invoices/bulk/generate-xml")
async def bulk_generate_xml(body: BulkOperation, current_user: dict = Depends(get_authenticated_user)):
    """Generate XML for multiple invoices at once."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    results = []
    for inv_id in body.invoice_ids:
        record = await db.get_invoice(inv_id)
        if not record or record.get("user_id") != user_id:
            results.append({"id": inv_id, "status": "error", "error": "Not found or access denied"})
            continue
        if record.get("xml_generated"):
            results.append({"id": inv_id, "status": "skipped", "reason": "Already generated"})
            continue
        try:
            from api.helpers import resolve_config, legacy_to_standard
            user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
            standard = legacy_to_standard(record["extracted"], cfg=usr_cfg, company_config=None)
            xml_str = xml_gen.generate(standard, company_name=active_company)
            await db.update_invoice(inv_id, {"xml_generated": True, "xml_content": xml_str})
            results.append({"id": inv_id, "status": "generated"})
        except Exception as e:
            results.append({"id": inv_id, "status": "error", "error": str(e)})
    return {"results": results, "total": len(body.invoice_ids), "generated": sum(1 for r in results if r["status"] == "generated")}


@router.post("/api/v3/invoices/bulk/sync")
async def bulk_sync(body: BulkOperation, current_user: dict = Depends(get_authenticated_user)):
    """Mark multiple invoices as synced to Tally."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    results = []
    for inv_id in body.invoice_ids:
        record = await db.get_invoice(inv_id)
        if not record or record.get("user_id") != user_id:
            results.append({"id": inv_id, "status": "error", "error": "Not found"})
            continue
        if record.get("status") != "validated":
            results.append({"id": inv_id, "status": "skipped", "reason": f"Status is '{record.get('status')}', not 'validated'"})
            continue
        await db.update_invoice_status(inv_id, "exported")
        await audit_logger.log_invoice_action("sync", inv_id, user_id, "bulk_sync",
            snapshot={"status": "validated", "synced_at": None})
        results.append({"id": inv_id, "status": "exported"})
    return {"results": results, "total": len(body.invoice_ids), "exported": sum(1 for r in results if r["status"] == "exported")}


@router.post("/api/v3/invoices/bulk/delete")
async def bulk_delete(body: BulkOperation, current_user: dict = Depends(get_authenticated_user)):
    """Delete multiple invoices at once."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    deleted = 0
    for inv_id in body.invoice_ids:
        record = await db.get_invoice(inv_id)
        if record and record.get("user_id") == user_id:
            await db.execute_db_write_with_retry(db.invoices.delete_one, {"display_id": inv_id})
            deleted += 1
    return {"deleted": deleted, "total": len(body.invoice_ids)}


# ---- Audit History ----

@router.get("/invoices/{invoice_id}/audit")
async def get_invoice_audit(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Return audit trail for a specific invoice."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    events = await audit_logger.get_history(
        resource_type="invoice", resource_id=str(invoice_id), user_id=user_id,
    )
    return {"invoice_id": invoice_id, "events": events}


# ---- Undo ----

@router.post("/invoices/{invoice_id}/undo")
async def undo_invoice_action(invoice_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Revert the last action on an invoice (review confirm, XML generate, etc.)."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if record.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")

    last_event = await audit_logger.get_last_event("invoice", str(invoice_id))
    if not last_event:
        raise HTTPException(400, "No undoable action found for this invoice")

    action = last_event.get("action", "")
    snapshot = last_event.get("snapshot")
    updates = {}

    if action == "confirm_review":
        updates["status"] = "draft"
        updates["reviewed_at"] = None
        updates["reviewed_by"] = ""
        if snapshot and snapshot.get("xml_content") is None:
            updates["xml_content"] = None
            updates["xml_generated"] = False
            updates["xml_issues"] = []
        await db.update_invoice(invoice_id, updates)
        await audit_logger.log_invoice_action("undo", invoice_id, user_id,
                                              f"reverted confirm_review (->draft)")
        return {"ok": True, "message": "Review undone, invoice back to draft", "status": "draft"}

    elif action == "generate_xml":
        updates["xml_content"] = None
        updates["xml_generated"] = False
        updates["xml_issues"] = []
        await db.update_invoice(invoice_id, updates)
        await audit_logger.log_invoice_action("undo", invoice_id, user_id,
                                              f"reverted generate_xml (xml cleared)")
        return {"ok": True, "message": "XML generation undone", "xml_generated": False}

    elif action == "sync":
        updates["status"] = "validated"
        updates["synced_at"] = None
        updates["sync_error"] = None
        await db.update_invoice(invoice_id, updates)
        await audit_logger.log_invoice_action("undo", invoice_id, user_id,
                                              f"reverted sync (->validated)")
        return {"ok": True, "message": "Sync undone, invoice back to validated", "status": "validated"}

    else:
        raise HTTPException(400, f"Cannot undo action: {action}")


# ---- Generate XML from stored invoice ----


@router.post("/generate-xml/{invoice_id}")
async def generate_xml_for(
    invoice_id: int, data: InvoiceDataLegacy, force: bool = Query(False),
    current_user: dict = Depends(get_authenticated_user),
):
    """Generate Tally XML from submitted invoice data with validation checks."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    try:
        user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
        raw = data.model_dump()
        standard = _legacy_to_standard(raw, cfg=usr_cfg, company_config=_company_config)
        validation_result = validate_invoice_for_xml(standard)

        user_id = current_user.get("user_id", current_user.get("email", ""))
        dup_msg = await _check_dup(standard.vendor_name, standard.invoice_number, standard.total_amount, user_id)
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
            mark_masters_created(user_cfg, user_id)
        xml_issues_obj = validate_xml_output(xml_str)
        validation = val.run_full_validation(raw, [])
        pipe_report = run_validation_pipeline(standard, xml_str)

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
        await audit_logger.log_invoice_action(
            "generate_xml", invoice_id, current_user.get("user_id", current_user.get("email", "")),
            details=f"score={score} force={force}",
            snapshot={"xml_content": record.get("xml_content"), "xml_generated": record.get("xml_generated")},
        )
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


@router.post("/invoices/{invoice_id}/generate")
async def generate_from_stored(
    invoice_id: int, force: bool = Query(False),
    current_user: dict = Depends(get_authenticated_user),
):
    """Generate Tally XML using previously extracted data stored in the database."""
    if db.invoices is None:
        raise HTTPException(503, "Database not available")
    record = await db.get_invoice(invoice_id)
    if not record:
        raise HTTPException(404, "Invoice not found")
    data = record["extracted"]
    try:
        user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
        standard = _legacy_to_standard(data, cfg=usr_cfg, company_config=_company_config)
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
            mark_masters_created(user_cfg, current_user.get("user_id", "default"))
        xml_validation = validate_xml_output(xml_str)
        old_validation = val.run_full_validation(data, [])
        pipe_report = run_validation_pipeline(standard, xml_str)

        await db.update_invoice(invoice_id, {
            "xml_generated": True, "xml_content": xml_str,
            "xml_issues": xml_validation.errors, "v3_validation": validation_result.to_dict(),
        })
        await audit_logger.log_invoice_action(
            "generate_xml", invoice_id, current_user.get("user_id", current_user.get("email", "")),
            details=f"generate_from_stored force={force}",
            snapshot={"xml_content": record.get("xml_content"), "xml_generated": record.get("xml_generated")},
        )
        return {"valid": True, "xml": xml_str, "validation": old_validation, "xml_issues": xml_validation.errors, "validation_report": pipe_report}
    except Exception as e:
        logger.error("INVOICE XML GENERATION FAILED [%s]: %s", invoice_id, e)
        raise HTTPException(500, f"XML generation error: {str(e)}")


# ---- Replay ----


class _ReplayRequest(BaseModel):
    invoice_id: int
    from_step: str = "extract"
    force: bool = False


@router.post("/api/v3/invoices/{invoice_id}/replay")
async def replay_invoice(
    invoice_id: int,
    request: _ReplayRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Re-run extraction, validation, or XML generation steps from a given starting point."""
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
                user_cfg, _, usr_cfg, _ = resolve_config(current_user)
                standard = _legacy_to_standard(extracted, cfg=usr_cfg, company_config=_company_config)
                validation_result = validate_invoice_for_xml(standard)
                steps.append({"step": "validate", "passed": validation_result.passed, "message": f"Validation: {validation_result.passed}"})
                result["validation"] = validation_result.to_dict()
            except Exception as e:
                steps.append({"step": "validate", "passed": False, "message": str(e)})
                final_status = "failed"

        if request.from_step in ("xml", "sync") and final_status != "failed":
            try:
                user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
                standard = _legacy_to_standard(extracted, cfg=usr_cfg, company_config=_company_config)
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


# ---- Progress ----


@router.get("/api/v3/invoices/{invoice_id}/progress")
async def invoice_progress(invoice_id: str, current_user: dict = Depends(get_authenticated_user)):
    """Return processing progress and status for a queued invoice."""
    try:
        obj_id = ObjectId(invoice_id)
    except Exception:
        raise HTTPException(400, "Invalid invoice ID format")

    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.invoices is not None:
        doc = await db.invoices.find_one({"_id": obj_id, "user_id": user_id})
        if not doc:
            raise HTTPException(404, "Invoice not found")

        state = queue_manager.get_status(invoice_id) or "queued"

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
