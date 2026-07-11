"""Indian GST Engine — state codes, GSTIN validation, rate validation, tax type detection."""

import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from schemas import GSTType, GST_STATE_CODES, ALLOWED_GST_SLABS, TaxEntry


def precise_round(value: float | Decimal) -> Decimal:
    """Enforce strict commercial two-decimal rounding (paise precision)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

GSTIN_PATTERN = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z]{1})(\d{1})(Z)([A-Z\d]{1})$")


def validate_gstin(gstin: str) -> dict:
    if not gstin:
        return {"valid": False, "message": "GSTIN is empty"}
    gstin = gstin.strip().upper()
    match = GSTIN_PATTERN.match(gstin)
    if not match:
        return {"valid": False, "message": f"Invalid format — OCR may have misread '{gstin}', please verify and correct"}
    state_code = match.group(1)
    pan = match.group(2)
    entity_num = match.group(3)
    check_digit = match.group(5)
    if state_code not in GST_STATE_CODES:
        return {"valid": False, "message": f"State code '{state_code}' not recognised — check if OCR misread the first 2 digits"}
    if not _validate_pan(pan):
        return {"valid": False, "message": f"PAN '{pan}' in GSTIN is invalid — OCR may have misread, please verify"}
    if not _verify_gstin_checksum(gstin):
        return {"valid": False, "message": f"Checksum failed — OCR may have misread '{gstin}', please verify"}
    return {
        "valid": True,
        "message": "GSTIN is valid",
        "state_code": state_code,
        "state_name": GST_STATE_CODES.get(state_code, "Unknown"),
        "pan": pan,
        "entity_number": entity_num,
    }


def _validate_pan(pan: str) -> bool:
    if len(pan) != 10:
        return False
    pattern = r"^[A-Z]{5}\d{4}[A-Z]{1}$"
    return bool(re.match(pattern, pan))


def _compute_gstin_checksum(gstin_without_cd: str) -> str:
    codepoints = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for i, ch in enumerate(gstin_without_cd):
        try:
            val = codepoints.index(ch)
        except ValueError:
            return ""
        factor = 1 if i % 2 == 0 else 2
        product = val * factor
        total += product // 36 + product % 36
    remainder = total % 36
    expected = (36 - remainder) % 36
    return codepoints[expected]


def _verify_gstin_checksum(gstin: str) -> bool:
    expected = _compute_gstin_checksum(gstin[:-1])
    if not expected:
        return False
    return gstin[-1] == expected


def determine_gst_type(
    vendor_gstin: str,
    buyer_gstin: str = "",
    company_state_code: str = "27",
    is_sez: bool = False,
    is_lut: bool = False,
) -> tuple[GSTType, bool]:
    # Rule 1: LUT — zero-rated supply, exempt from GST
    if is_lut:
        return GSTType.EXEMPT, False
    # Rule 2: SEZ — deemed inter-state regardless of state codes
    if is_sez:
        return GSTType.IGST, True
    vendor_code = _extract_state_code(vendor_gstin)
    buyer_code = _extract_state_code(buyer_gstin) if buyer_gstin else company_state_code
    if not vendor_code:
        return GSTType.CGST_SGST, False
    if not buyer_code:
        buyer_code = company_state_code
    if vendor_code == buyer_code:
        return GSTType.CGST_SGST, False
    return GSTType.IGST, True


def _extract_state_code(gstin: str) -> Optional[str]:
    if not gstin:
        return None
    match = re.match(r"^(\d{2})", gstin.strip().upper())
    return match.group(1) if match else None


def validate_tax_rate(rate: float) -> dict:
    if rate in ALLOWED_GST_SLABS:
        return {"valid": True, "message": f"Tax rate {rate}% is valid"}
    near = min(ALLOWED_GST_SLABS, key=lambda x: abs(x - rate))
    if abs(rate - near) <= 0.5:
        return {
            "valid": True,
            "message": f"Tax rate {rate}% rounded to nearest slab {near}%",
            "corrected_rate": near,
        }
    return {
        "valid": False,
        "message": f"Tax rate {rate}% is not a valid Indian GST slab. Nearest: {near}%",
        "suggested_rate": near,
    }


def aggregate_and_round_slab_taxes(
    items: list[dict],
    gst_type: GSTType,
) -> dict[float, dict]:
    """
    Aggregates raw unrounded line-item decimals by tax slab before rounding.
    Prevents row-level fraction accumulation errors from breaking the voucher balance.

    Returns dict keyed by tax rate, each value containing:
      - type: 'CGST_SGST' or 'IGST'
      - cgst_amount / sgst_amount (for CGST_SGST)
      - igst_amount (for IGST)
      - cgst_rate / sgst_rate (for CGST_SGST)
      - igst_rate (for IGST)
    """
    slab_aggregates = defaultdict(Decimal)

    for item in items:
        taxable = Decimal(str(item.get("taxable_value", 0.0)))
        rate = Decimal(str(item.get("tax_rate", 0.0)))
        if taxable <= 0 or rate <= 0:
            continue
        raw_tax = taxable * (rate / Decimal("100"))
        slab_aggregates[rate] += raw_tax

    rounded_slab_results = {}
    for rate, raw_tax_sum in slab_aggregates.items():
        total_slab_tax = raw_tax_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if gst_type == GSTType.CGST_SGST:
            half_rate = rate / Decimal("2")
            cgst_split = (total_slab_tax / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            sgst_split = cgst_split

            # Resolve 1-paisa uneven division anomalies
            if (cgst_split * Decimal("2")) != total_slab_tax:
                cgst_split += total_slab_tax - (cgst_split * Decimal("2"))

            rounded_slab_results[float(rate)] = {
                "type": "CGST_SGST",
                "cgst_amount": float(cgst_split),
                "sgst_amount": float(sgst_split),
                "cgst_rate": float(half_rate),
                "sgst_rate": float(half_rate),
            }
        else:
            rounded_slab_results[float(rate)] = {
                "type": "IGST",
                "igst_amount": float(total_slab_tax),
                "igst_rate": float(rate),
            }

    return rounded_slab_results


def compute_gst_entries(
    taxable_value: float,
    tax_rate: float,
    gst_type: GSTType,
    is_input: bool = True,
    company_config: Optional[dict] = None,
    is_rcm: bool = False,
) -> list[TaxEntry]:
    entries = []
    dec_taxable = Decimal(str(taxable_value))
    dec_rate = Decimal(str(tax_rate))
    total_tax = precise_round(dec_taxable * dec_rate / Decimal("100"))
    if total_tax <= 0:
        return entries
    if gst_type == GSTType.CGST_SGST:
        half_rate = dec_rate / Decimal("2")
        half_rate_f = float(half_rate)
        split_amount = precise_round(total_tax / Decimal("2"))
        if split_amount * Decimal("2") != total_tax:
            cgst_amount = float(split_amount + (total_tax - split_amount * Decimal("2")))
            sgst_amount = float(split_amount)
        else:
            cgst_amount = float(split_amount)
            sgst_amount = float(split_amount)
        cgst_name = _gst_ledger_name("CGST", half_rate_f, is_input, company_config, is_rcm)
        sgst_name = _gst_ledger_name("SGST", half_rate_f, is_input, company_config, is_rcm)
        if cgst_amount > 0:
            entries.append(TaxEntry(name=cgst_name, rate=half_rate_f, amount=cgst_amount, type="cgst", is_input=is_input))
        if sgst_amount > 0:
            entries.append(TaxEntry(name=sgst_name, rate=half_rate_f, amount=sgst_amount, type="sgst", is_input=is_input))
    elif gst_type == GSTType.IGST:
        igst_name = _gst_ledger_name("IGST", tax_rate, is_input, company_config, is_rcm)
        entries.append(TaxEntry(name=igst_name, rate=tax_rate, amount=float(total_tax), type="igst", is_input=is_input))
    return entries


UT_STATE_CODES = {"04", "25", "26", "35", "37"}

def _gst_ledger_name(prefix: str, rate: float, is_input: bool, config: Optional[dict], is_rcm: bool = False) -> str:
    direction = "Input" if is_input else "Output"
    rcm_suffix = " (RCM)" if is_rcm else ""
    if prefix == "SGST" and config and config.get("company_state_code", "") in UT_STATE_CODES:
        if config and f"utgst_{rate}" in config:
            return config[f"utgst_{rate}"]
        return f"{direction} UTGST{rcm_suffix} {rate:g}%"
    if config and f"{prefix.lower()}_{rate}" in config:
        return config[f"{prefix.lower()}_{rate}"]
    return f"{direction} {prefix}{rcm_suffix} {rate:g}%"


def validate_tax_structure(taxes: list[TaxEntry]) -> list[str]:
    issues = []
    has_cgst = any(t.type == "cgst" for t in taxes)
    has_sgst = any(t.type == "sgst" for t in taxes)
    has_igst = any(t.type == "igst" for t in taxes)
    if has_cgst and not has_sgst:
        issues.append("CGST present but SGST missing")
    if has_sgst and not has_cgst:
        issues.append("SGST present but CGST missing")
    if has_igst and (has_cgst or has_sgst):
        issues.append("IGST should not coexist with CGST/SGST")
    return issues


def compute_tax_from_items(
    items: list,
    gst_type: GSTType,
    company_config: Optional[dict] = None,
    is_input: bool = True,
    is_rcm: bool = False,
) -> list[TaxEntry]:
    """Aggregate line items by tax slab, round once per slab, then split into CGST/SGST or IGST.

    Prevents cumulative penny drift from per-line rounding by using
    aggregate_and_round_slab_taxes() to round raw unrounded totals.
    """
    slab_results = aggregate_and_round_slab_taxes(items, gst_type)
    entries: list[TaxEntry] = []

    for rate, result in slab_results.items():
        if result["type"] == "CGST_SGST":
            cgst_name = _gst_ledger_name("CGST", result["cgst_rate"], is_input, company_config, is_rcm)
            sgst_name = _gst_ledger_name("SGST", result["sgst_rate"], is_input, company_config, is_rcm)
            if result["cgst_amount"] > 0:
                entries.append(TaxEntry(
                    name=cgst_name, rate=result["cgst_rate"],
                    amount=result["cgst_amount"], type="cgst", is_input=is_input,
                ))
            if result["sgst_amount"] > 0:
                entries.append(TaxEntry(
                    name=sgst_name, rate=result["sgst_rate"],
                    amount=result["sgst_amount"], type="sgst", is_input=is_input,
                ))
        else:
            igst_name = _gst_ledger_name("IGST", result["igst_rate"], is_input, company_config, is_rcm)
            if result["igst_amount"] > 0:
                entries.append(TaxEntry(
                    name=igst_name, rate=result["igst_rate"],
                    amount=result["igst_amount"], type="igst", is_input=is_input,
                ))

    return entries
