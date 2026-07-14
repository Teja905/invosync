"""OCR post-processing — fixes common OCR confusions, validates extracted math, and normalizes text artifacts."""

import re
from typing import Any, Dict, Optional


OCR_CONFUSIONS = {
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "|": "1",
    "S": "5",
    "s": "5",
    "B": "8",
    "b": "6",
    "g": "9",
    "q": "9",
    "Z": "2",
    "z": "2",
}

GSTIN_FIX_CHARS = str.maketrans(OCR_CONFUSIONS)


def fix_gstin(raw: str) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().upper()
    cleaned = re.sub(r"[^0-9A-Z]", "", cleaned)
    # Preserve GSTIN structural chars from OCR translation: literal 'Z' at pos 13
    # and checksum at pos 14 must not be altered.
    if len(cleaned) >= 14:
        core = cleaned[:13].translate(GSTIN_FIX_CHARS)
        return core + cleaned[13:]
    if len(cleaned) > 0:
        return cleaned.translate(GSTIN_FIX_CHARS)
    return cleaned


def fix_invoice_number(raw: str) -> str:
    if not raw:
        return ""
    result = raw.strip()
    result = result.replace(" ", "").replace("\t", "")
    result = result.translate(str.maketrans({
        "O": "0", "o": "0",
        "I": "1", "l": "1",
        " ": "", "\t": "",
    }))
    return result


def fix_amount(raw: Optional[float]) -> Optional[float]:
    if raw is None:
        return None
    return round(abs(raw), 2)


def fix_tax_rate(rate: Optional[float]) -> Optional[float]:
    if rate is None or rate == 0:
        return rate
    rate = abs(rate)
    if rate < 1 and rate != 0:
        return rate
    if rate > 100:
        rate = rate / 10
    if rate > 100:
        rate = rate / 100
    return rate


MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

def _month_to_num(abbr: str) -> str | None:
    return MONTH_MAP.get(abbr.strip().lower()[:3])

def fix_date(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", raw)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2})$", raw)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        prefix = "20" if int(yy) < 50 else "19"
        return f"{prefix}{yy}-{int(mm):02d}-{int(dd):02d}"
    m = re.match(r"^(\d{8})$", raw)
    if m:
        return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
    # DD-Mon-YY or DD-Mon-YYYY
    m = re.match(r"^(\d{1,2})\s*[-/]\s*([A-Za-z]{3,})\s*[-/]\s*(\d{2,4})$", raw)
    if m:
        dd, mon, yy = m.group(1), m.group(2), m.group(3)
        mm = _month_to_num(mon)
        if mm:
            prefix = "20" if len(yy) == 2 and int(yy) < 50 else ("19" if len(yy) == 2 else "")
            return f"{prefix}{yy}-{mm}-{int(dd):02d}"
    # Mon DD, YYYY or Mon DD YYYY
    m = re.match(r"^([A-Za-z]{3,})\s+(\d{1,2})\s*,?\s*(\d{4})$", raw)
    if m:
        mon, dd, yy = m.group(1), m.group(2), m.group(3)
        mm = _month_to_num(mon)
        if mm:
            return f"{yy}-{mm}-{int(dd):02d}"
    return raw


def post_process_extracted(data: dict) -> dict:
    data = dict(data)
    if data.get("gstin"):
        data["gstin"] = fix_gstin(data["gstin"])
        data["vendor_gstin"] = data["gstin"]
    if data.get("vendor_gstin"):
        data["vendor_gstin"] = fix_gstin(data["vendor_gstin"])
    if data.get("invoice_number"):
        data["invoice_number"] = fix_invoice_number(data["invoice_number"])
    if data.get("date"):
        data["date"] = fix_date(data["date"])
        data["invoice_date"] = data["date"]
    if "invoice_date" in data and data.get("invoice_date"):
        data["invoice_date"] = fix_date(data["invoice_date"])
    if data.get("total_amount") is not None:
        data["total_amount"] = fix_amount(data["total_amount"])
    if data.get("total_taxable_value") is not None:
        data["total_taxable_value"] = fix_amount(data["total_taxable_value"])
    if data.get("total_tax") is not None:
        data["total_tax"] = fix_amount(data["total_tax"])
    line_items = data.get("line_items", [])
    for item in line_items:
        if item.get("tax_rate") is not None:
            item["tax_rate"] = fix_tax_rate(item["tax_rate"])
        if item.get("rate") is not None:
            item["rate"] = fix_amount(item["rate"])
        if item.get("quantity") is not None and item["quantity"] == 0 and item.get("taxable_value", 0) > 0:
            item["quantity"] = 1.0
        if item.get("taxable_value") is not None:
            item["taxable_value"] = fix_amount(item["taxable_value"])
        if item.get("description"):
            item["description"] = str(item["description"]).strip()
    data["line_items"] = line_items
    return data


def clean_alphanumeric_code(code: str) -> str:
    """Cleans up system identifier strings like GSTIN, PAN, or HSN codes."""
    if not code:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(code).upper().strip())


CORPORATE_ACRONYMS = {"LTD", "PVT", "INC", "CO", "MS"}


def sanitize_ledger_or_party_name(name: str) -> str:
    """Normalizes company names and descriptions into clean, uniform strings."""
    if not name:
        return ""
    clean_name = re.sub(r"\s+", " ", str(name)).strip()
    words = clean_name.split()
    processed = [w.upper() if w.upper() in CORPORATE_ACRONYMS else w for w in words]
    return " ".join(processed)


def clean_extracted_invoice_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-validation text parser filter. Normalizes fields to match structural compliance expectations."""
    cleaned = payload.copy()

    if "vendor_name" in cleaned:
        cleaned["vendor_name"] = sanitize_ledger_or_party_name(cleaned["vendor_name"])
    if "buyer_name" in cleaned:
        cleaned["buyer_name"] = sanitize_ledger_or_party_name(cleaned["buyer_name"])

    if "vendor_gstin" in cleaned:
        cleaned["vendor_gstin"] = clean_alphanumeric_code(cleaned["vendor_gstin"])
    if "buyer_gstin" in cleaned:
        cleaned["buyer_gstin"] = clean_alphanumeric_code(cleaned["buyer_gstin"])

    if "line_items" in cleaned and isinstance(cleaned["line_items"], list):
        cleaned_items = []
        for item in cleaned["line_items"]:
            item_copy = dict(item)
            if "description" in item_copy:
                item_copy["description"] = sanitize_ledger_or_party_name(item_copy["description"])
            if "hsn_sac" in item_copy:
                item_copy["hsn_sac"] = clean_alphanumeric_code(item_copy["hsn_sac"])
            if "unit" in item_copy:
                raw = item_copy["unit"]
                item_copy["unit"] = clean_alphanumeric_code(raw)[:3] if raw else "NOS"
            cleaned_items.append(item_copy)
        cleaned["line_items"] = cleaned_items

    return cleaned


def validate_invoice_math(data: dict) -> list[str]:
    issues = []
    line_items = data.get("line_items", [])
    if not line_items:
        return issues
    calc_taxable = 0.0
    calc_cgst = 0.0
    calc_sgst = 0.0
    calc_igst = 0.0
    for item in line_items:
        tv = float(item.get("taxable_value", 0) or 0)
        calc_taxable += tv
        calc_cgst += float(item.get("cgst", 0) or 0)
        calc_sgst += float(item.get("sgst", 0) or 0)
        calc_igst += float(item.get("igst", 0) or 0)
    calc_total = calc_taxable + calc_cgst + calc_sgst + calc_igst
    reported_total = float(data.get("total_amount", 0) or 0)
    if reported_total > 0 and abs(calc_total - reported_total) > 2.0:
        issues.append(
            f"Math mismatch: line items total ₹{calc_total:.2f} ≠ reported ₹{reported_total:.2f}"
        )
    return issues
