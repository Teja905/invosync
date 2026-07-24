"""XML generation, preview, pre-import check, and validation endpoints."""

import json

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import Response, JSONResponse

import database as db
import validation as val
from api.app_state import company_config as _company_config
from api.deps import get_authenticated_user
from api.helpers import legacy_to_standard, check_duplicate, resolve_config, mark_masters_created
from api.models import InvoiceDataLegacy
from audit_log import audit as audit_logger
from config.settings import run_validation_pipeline
from core.logging import get_logger
from core.metrics import metrics
from validation_layer import validate_invoice_for_xml, validate_xml_output
from api.journal_persist import persist_journal

router = APIRouter()
logger = get_logger(__name__)


@router.post("/preview-masters")
async def preview_masters(data: InvoiceDataLegacy, current_user: dict = Depends(get_authenticated_user)):
    """Preview what masters will be created before generating XML."""
    try:
        user_cfg, xml_gen, usr_cfg, _active_cmp = resolve_config(current_user)
        raw = data.model_dump()
        standard = legacy_to_standard(raw, cfg=usr_cfg, company_config=_company_config)
        report = xml_gen.pre_import_check(standard)

        vendor_name = standard.vendor_name.strip()
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if db.invoices is not None and vendor_name:
            similar = await db.find_similar_vendors(vendor_name, user_id)
            if similar:
                report["warnings"].append({
                    "type": "similar_vendor_exists",
                    "severity": "medium",
                    "message": "Similar vendor names found in previous imports:",
                    "details": [f"{s['vendor_name']} ({s['gstin'] or 'no GSTIN'})" for s in similar],
                })
        return report
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {str(e)}")


@router.post("/pre-import-check")
async def pre_import_check(data: InvoiceDataLegacy, current_user: dict = Depends(get_authenticated_user)):
    """Full pre-import readiness check: masters, warnings, company, voucher info."""
    try:
        user_cfg, xml_gen, usr_cfg, _active_cmp = resolve_config(current_user)
        raw = data.model_dump()
        standard = legacy_to_standard(raw, cfg=usr_cfg, company_config=_company_config)
        report = xml_gen.pre_import_check(standard)

        vendor_name = standard.vendor_name.strip()
        user_id = current_user.get("user_id", current_user.get("email", ""))
        if db.invoices is not None and vendor_name:
            similar = await db.find_similar_vendors(vendor_name, user_id)
            if similar:
                report["warnings"].append({
                    "type": "similar_vendor_exists",
                    "severity": "medium",
                    "message": "Similar vendor names found in previous imports:",
                    "details": [f"{s['vendor_name']} ({s['gstin'] or 'no GSTIN'})" for s in similar],
                })

        inv_no = standard.invoice_number.strip()
        if vendor_name and inv_no:
            dup = await db.find_duplicate(vendor_name, inv_no, user_id, date=standard.invoice_date)
            if dup:
                report["warnings"].append({
                    "type": "duplicate_invoice",
                    "severity": "high",
                    "message": f"Invoice '{inv_no}' from '{vendor_name}' was already imported (ID: {dup.get('display_id')}).",
                })
        return report
    except Exception as e:
        raise HTTPException(500, f"Pre-import check failed: {str(e)}")


@router.post("/generate-xml")
async def generate_xml(data: InvoiceDataLegacy, force: bool = Query(False), current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
        raw = data.model_dump()
        standard = legacy_to_standard(raw, cfg=usr_cfg, company_config=_company_config)
        validation_result = validate_invoice_for_xml(standard)

        user_id = current_user.get("user_id", current_user.get("email", ""))
        dup_msg = await check_duplicate(standard.vendor_name, standard.invoice_number, standard.total_amount, user_id, date=standard.invoice_date)
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
        pipe_report = run_validation_pipeline(standard, xml_str)

        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            mark_masters_created(user_cfg, user_id)

        inv_id = None
        if db.invoices is not None:
            try:
                inv_id, _ = await db.insert_invoice(
                    user_id=user_id,
                    client_id=data.client_id or 0,
                    extracted=raw,
                    validation=old_validation,
                    xml_generated=False, xml_content=None,
                    xml_issues=xml_validation.errors,
                )
            except Exception as e:
                logger.error("DB insert error: %s", e)

        # Persist journal lines (derived ledger legs) as the single source of
        # truth for reporting — Trial Balance / P&L / Balance Sheet read these,
        # never the raw Tally XML. Also seed the chart-of-accounts ledger types.
        if inv_id is not None:
            company_id = active_company or user_cfg.get("company_name", user_id)
            await persist_journal(
                db, inv_id, user_id, company_id, data.client_id or 0,
                standard, xml_gen, usr_cfg,
            )
            await db.update_invoice(inv_id, {
                "xml_generated": True, "xml_content": xml_str,
            })

        score = pipe_report.get("scores", {}).get("total", 0)
        report_json = json.dumps(pipe_report)
        user_id = current_user.get("user_id", "unknown")
        metrics.record_xml_generated()
        await audit_logger.log_invoice_action("generate_xml", inv_id or 0, user_id, f"score={score} passed={pipe_report.get('passed')}")
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


@router.post("/generate-xml/v3")
async def generate_xml_v3(data: dict, current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
        standard = legacy_to_standard(data, cfg=usr_cfg, company_config=_company_config)
        validation_result = validate_invoice_for_xml(standard)
        if not validation_result.passed:
            return {
                "valid": False,
                "validation": validation_result.to_dict(),
                "message": "Validation failed. Correct errors before generating XML.",
            }
        xml_str = xml_gen.generate(standard, company_name=active_company)
        xml_validation = validate_xml_output(xml_str)
        pipe_report = run_validation_pipeline(standard, xml_str)

        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_cfg["masters_created"] = True
            user_id = current_user.get("user_id", "default")
            mark_masters_created(user_cfg, user_id)

        return {
            "valid": True,
            "xml": xml_str,
            "validation": validation_result.to_dict(),
            "xml_validation": xml_validation.to_dict(),
            "validation_report": pipe_report,
        }
    except Exception as e:
        raise HTTPException(500, f"XML generation error: {str(e)}")


@router.get("/api/v3/validate")
async def validate_standardized(data: dict, current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg, xml_gen, usr_cfg, _ = resolve_config(current_user)
        standard = legacy_to_standard(data, cfg=usr_cfg, company_config=_company_config)
        result = validate_invoice_for_xml(standard)
        return {"valid": result.passed, **result.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"Validation error: {str(e)}")


@router.post("/api/v3/generate")
async def generate_v3(data: dict, current_user: dict = Depends(get_authenticated_user)):
    try:
        user_cfg, xml_gen, usr_cfg, active_company = resolve_config(current_user)
        standard = legacy_to_standard(data, cfg=usr_cfg, company_config=_company_config)
        validation_result = validate_invoice_for_xml(standard)
        xml_str = xml_gen.generate(standard, company_name=active_company)
        xml_validation = validate_xml_output(xml_str)

        if not xml_gen.masters_created:
            xml_gen.masters_created = True
            user_cfg["masters_created"] = True
            user_id = current_user.get("user_id", "default")
            mark_masters_created(user_cfg, user_id)

        return {
            "valid": validation_result.passed,
            "xml": xml_str,
            "validation": validation_result.to_dict(),
            "xml_validation": xml_validation.to_dict(),
            "balanced": not xml_validation.errors,
        }
    except Exception as e:
        raise HTTPException(500, f"Generation error: {str(e)}")
