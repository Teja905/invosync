"""Shared route helpers: legacy conversion, duplicate check, config utils."""

from typing import Optional

from company_config import CompanyConfig
from config.settings import config_overrides, user_config_from_current, make_xml_generator
from core.logging import get_logger
from gst_engine import determine_gst_type, compute_tax_from_items
from ocr_postproc import fix_gstin, fix_date
from schemas import StandardizedInvoice, LineItem, VoucherType
from voucher_classifier import classify_voucher_type, classify_service_vs_goods

import database as db

logger = get_logger(__name__)


def legacy_to_standard(data: dict, provider: str = "", model: str = "", cfg: Optional[CompanyConfig] = None, company_config=None) -> StandardizedInvoice:
    cfg = cfg or company_config
    gstin = fix_gstin(data.get("gstin", ""))
    company_state = cfg.state_code
    company_gstin = cfg.company_gstin
    buyer_gstin = data.get("buyer_gstin") or company_gstin or ""
    is_sez = bool(data.get("is_sez", False))
    is_lut = bool(data.get("is_lut", False))
    is_composition = bool(data.get("is_composition", False))
    gst_type, is_interstate = determine_gst_type(
        gstin, buyer_gstin, company_state,
        is_sez=is_sez, is_lut=is_lut, is_composition=is_composition,
    )

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
        is_sez=is_sez,
        is_lut=is_lut,
        is_composition=is_composition,
        confidence=float(data.get("confidence", 0) or 0),
        voucher_type=voucher_type,
        auto_create_stock_items=bool(data.get("auto_create_stock_items", False)),
        _provider=provider,
        _model=model,
    )


async def check_duplicate(vendor: str, inv_no: str, total: float, user_id: str = None, date: str = None) -> Optional[str]:
    if db.invoices is None or not vendor or not inv_no:
        return None
    try:
        dup = await db.find_duplicate(vendor, inv_no, user_id, date=date)
        if not dup:
            return None
        existing_amt = dup.get("extracted", {}).get("total_amount")
        if existing_amt is not None and abs(float(existing_amt) - total) < 2:
            return f"Duplicate: same invoice from '{vendor}' #{inv_no} already exists (ID: {dup.get('display_id')})"
    except Exception:
        pass
    return None


def resolve_config(current_user: dict):
    """Resolve user config + XML generator from current user profile."""
    user_cfg = user_config_from_current(current_user)
    xml_gen, usr_cfg, active_company = make_xml_generator(user_cfg)
    return user_cfg, xml_gen, usr_cfg, active_company


def mark_masters_created(user_cfg: dict, user_id: str):
    """Flag masters as created to avoid re-generation on subsequent calls."""
    if user_id not in config_overrides:
        config_overrides[user_id] = {}
    config_overrides[user_id]["masters_created"] = True
