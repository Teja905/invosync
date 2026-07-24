"""Hallucination guard — independently measures extraction quality without trusting AI self-assessment.

The AI returns a self-attested `confidence` score. This engine computes an
*independent* confidence by checking:
  1. Mathematical integrity: do line items sum to header totals?
  2. Cross-field consistency: does GSTIN PAN match vendor name initials?
  3. Date sanity: is the date valid, not future, not pre-GST era?
  4. GSTIN validity: checksum, state code, format?
  5. Field presence: are critical fields non-empty and non-generic?
  6. Line item health: does every item have description + value?

Overall confidence = minimum of all scores (weakest-link principle).
A single bad score means the extraction cannot be trusted.

Thresholds:
  ≥ 0.70:  Normal — warnings on individual low fields
  0.40–0.69: Mandatory review — human must confirm every field
  < 0.40:   BLOCKED — XML generation impossible, even with force=true
"""

import re
from datetime import date, datetime

from gst_engine import validate_gstin, ALLOWED_GST_SLABS

# Generic vendor names the AI fabricates when it can't read the actual name
GENERIC_VENDOR_NAMES = {
    "vendor", "supplier", "seller", "customer", "client", "party",
    "unknown", "not found", "n/a", "na", "none", "test", "demo",
    "bharti", "xyz", "abc", "purchaser", "buyer", "the vendor",
}

# Earliest possible GST invoice date (GST launched July 1, 2017)
GST_LAUNCH_DATE = date(2017, 6, 1)

# PAN pattern: first 3 letters + 4th letter (entity type) + 5th letter (name initial)
PAN_PATTERN = re.compile(r"^[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]$")


def compute_independent_confidence(data: dict) -> tuple[float, dict[str, float], list[str]]:
    """Score extraction quality without trusting the AI's self-confidence.

    Returns:
      - overall: float (0-1, minimum of all scores)
      - field_scores: dict of per-check scores
      - issues: list of human-readable problems found
    """
    scores: dict[str, float] = {}
    issues: list[str] = []

    _check_math_integrity(data, scores, issues)
    _check_gstin_sanity(data, scores, issues)
    _check_date_sanity(data, scores, issues)
    _check_vendor_presence(data, scores, issues)
    _check_line_items(data, scores, issues)
    _check_amount_ranges(data, scores, issues)
    _check_hsn_sac_codes(data, scores, issues)
    _check_tds_fields(data, scores, issues)
    _check_place_of_supply(data, scores, issues)

    overall = min(scores.values()) if scores else 0.5
    return round(overall, 2), scores, issues


def _check_math_integrity(data: dict, scores: dict, issues: list):
    """Verify line items sum to header totals within paise precision.
    This is the single strongest hallucination signal — AI models frequently
    generate line items that don't add up.
    """
    items = [it for it in (data.get("line_items") or []) if isinstance(it, dict)]
    total_taxable = float(data.get("total_taxable_value", 0) or 0)
    total_amount = float(data.get("total_amount", 0) or 0)
    total_tax = float(data.get("total_tax", 0) or 0)

    if not items:
        if total_amount > 0:
            # Single-line invoice with no line items — can't verify math
            scores["math_integrity"] = 0.5
            issues.append("No line items provided — cannot verify mathematical integrity")
        else:
            scores["math_integrity"] = 0.0
            issues.append("No line items and zero total amount — likely hallucination")
        return

    calc_taxable = sum(float(item.get("taxable_value", 0) or 0) for item in items)
    taxable_diff = abs(calc_taxable - total_taxable) if total_taxable > 0 else 0

    # Calculate expected tax from line items
    calc_tax = 0.0
    for item in items:
        rate = float(item.get("tax_rate", 0) or 0)
        taxable = float(item.get("taxable_value", 0) or 0)
        calc_tax += taxable * rate / 100.0

    if total_taxable <= 0 and total_amount > 0:
        scores["math_integrity"] = 0.3
        issues.append(f"Total taxable is ₹0.00 but total amount is ₹{total_amount:.2f} — inconsistent")
        return

    if taxable_diff > 5.0:
        scores["math_integrity"] = 0.0
        issues.append(f"Line items sum to ₹{calc_taxable:.2f} but header says ₹{total_taxable:.2f} (diff ₹{taxable_diff:.2f})")
        return
    elif taxable_diff > 1.0:
        scores["math_integrity"] = 0.2
        issues.append(f"Line items sum ₹{calc_taxable:.2f} vs header ₹{total_taxable:.2f} (diff ₹{taxable_diff:.2f})")
        return
    elif taxable_diff > 0.10:
        scores["math_integrity"] = 0.6
        issues.append(f"Minor math drift: ₹{calc_taxable:.2f} vs ₹{total_taxable:.2f}")

    # Check total = taxable + tax
    if total_taxable > 0 and total_tax > 0:
        expected_total = total_taxable + total_tax
        total_diff = abs(expected_total - total_amount)
        if total_diff > 5.0 and total_amount > 0:
            if scores.get("math_integrity", 1.0) > 0.3:
                scores["math_integrity"] = 0.3
            issues.append(f"Taxable ₹{total_taxable:.2f} + Tax ₹{total_tax:.2f} = ₹{expected_total:.2f} ≠ Total ₹{total_amount:.2f}")

    if "math_integrity" not in scores:
        scores["math_integrity"] = 1.0


def _check_gstin_sanity(data: dict, scores: dict, issues: list):
    """Validate GSTIN format + check if PAN initial matches vendor name."""
    gstin = (data.get("vendor_gstin") or data.get("gstin") or "").strip().upper()
    vendor_name = (data.get("vendor_name") or "").strip().upper()

    if not gstin:
        scores["gstin_validity"] = 0.7  # Missing GSTIN is common in India
        issues.append("No GSTIN provided")
        return

    result = validate_gstin(gstin)
    if not result.get("valid"):
        scores["gstin_validity"] = 0.0
        issues.append(f"GSTIN invalid: {result.get('message', 'checksum failed')}")
        return

    scores["gstin_validity"] = 1.0

    # Cross-check: PAN's 5th character (name initial) should match vendor name
    if vendor_name and len(gstin) >= 10:
        pan = gstin[2:12]  # Characters 3-12 form the PAN
        if len(pan) == 10 and PAN_PATTERN.match(pan):
            pan_name_char = pan[3]  # 5th char of PAN alphabet = name initial
            vendor_initials = "".join(
                w[0] for w in vendor_name.split()
                if w[0].isalpha()
            )[:3]
            if vendor_initials and pan_name_char not in vendor_initials:
                scores["gstin_name_match"] = 0.3
                issues.append(
                    f"GSTIN PAN initial '{pan_name_char}' not found in vendor name "
                    f"initials '{vendor_initials}' — possible hallucination"
                )


def _check_date_sanity(data: dict, scores: dict, issues: list):
    """Verify invoice date is reasonable: not pre-GST, not in the future, not too old."""
    date_str = data.get("invoice_date") or data.get("date") or ""
    if not date_str:
        scores["date_sanity"] = 0.5
        issues.append("No invoice date")
        return

    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            inv_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        elif re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
            inv_date = datetime.strptime(date_str, "%d/%m/%Y").date()
        else:
            scores["date_sanity"] = 0.2
            issues.append(f"Date format unrecognised: {date_str}")
            return
    except ValueError:
        scores["date_sanity"] = 0.0
        issues.append(f"Date is not a real calendar date: {date_str}")
        return

    today = date.today()
    if inv_date > today:
        scores["date_sanity"] = 0.0
        issues.append(f"Invoice date {date_str} is in the future — impossible")
        return

    if inv_date < GST_LAUNCH_DATE:
        scores["date_sanity"] = 0.0
        issues.append(f"Invoice date {date_str} is before GST launch (July 2017) — likely hallucinated")
        return

    if inv_date < date(2020, 1, 1):
        scores["date_sanity"] = 0.5
        issues.append(f"Invoice date {date_str} is over 5 years old — verify this is correct")
        return

    scores["date_sanity"] = 1.0


def _check_vendor_presence(data: dict, scores: dict, issues: list):
    """Vendor name must be present and not a generic placeholder."""
    vendor = (data.get("vendor_name") or "").strip()
    if not vendor:
        scores["vendor_presence"] = 0.0
        issues.append("Vendor name is empty — AI likely hallucinated the extraction")
        return

    if vendor.lower() in GENERIC_VENDOR_NAMES:
        scores["vendor_presence"] = 0.1
        issues.append(f"Vendor name '{vendor}' is a generic placeholder — not a real vendor")
        return

    if len(vendor) < 3:
        scores["vendor_presence"] = 0.3
        issues.append(f"Vendor name '{vendor}' is suspiciously short")
        return

    scores["vendor_presence"] = 1.0


def _check_line_items(data: dict, scores: dict, issues: list):
    """Every line item must have a description and positive value."""
    items = [it for it in (data.get("line_items") or []) if isinstance(it, dict)]
    if not items:
        scores["line_item_health"] = 0.3
        issues.append("No line items extracted")
        return

    empty_desc = sum(1 for it in items if not (it.get("description") or "").strip())
    zero_value = sum(1 for it in items if float(it.get("taxable_value", 0) or 0) <= 0)

    if empty_desc == len(items):
        scores["line_item_health"] = 0.0
        issues.append("All line items have empty descriptions — AI hallucinated these")
        return

    if empty_desc > len(items) / 2:
        scores["line_item_health"] = 0.2
        issues.append(f"{empty_desc} of {len(items)} line items have no description")
        return

    if zero_value == len(items):
        scores["line_item_health"] = 0.0
        issues.append("All line items have zero value — extraction failed")
        return

    if empty_desc > 0 or zero_value > 0:
        scores["line_item_health"] = 0.5
    else:
        scores["line_item_health"] = 1.0


def _check_amount_ranges(data: dict, scores: dict, issues: list):
    """Sanity-check that amounts are within plausible ranges."""
    total_amount = float(data.get("total_amount", 0) or 0)
    total_taxable = float(data.get("total_taxable_value", 0) or 0)
    total_tax = float(data.get("total_tax", 0) or 0)
    freight = float(data.get("freight", 0) or 0)
    tds = float(data.get("tds_amount", 0) or 0)

    if total_amount < 0:
        scores["amount_ranges"] = 0.0
        issues.append(f"Total amount is negative (₹{total_amount:.2f}) — impossible")
        return

    if total_amount > 0 and total_taxable > total_amount + 1:
        # Taxable exceeding total happens when AI reverses the values
        scores["amount_ranges"] = 0.0
        issues.append(f"Taxable value (₹{total_taxable:.2f}) exceeds total (₹{total_amount:.2f}) — values likely swapped")
        return

    if total_tax > 0 and total_tax > total_taxable * 0.5:
        # Tax > 50% of taxable is impossible (max GST slab is 28%)
        scores["amount_ranges"] = 0.0
        issues.append(f"Tax (₹{total_tax:.2f}) exceeds 50% of taxable (₹{total_taxable:.2f}) — inflated")
        return

    # Check individual tax rates against allowed slabs
    for item in data.get("line_items", []):
        if not isinstance(item, dict):
            continue
        rate = float(item.get("tax_rate", 0) or 0)
        if rate > 0 and rate not in ALLOWED_GST_SLABS and abs(rate - min(ALLOWED_GST_SLABS, key=lambda x: abs(x - rate))) > 0.5:
            scores["amount_ranges"] = 0.0
            issues.append(f"Tax rate {rate}% is not a valid GST slab — AI hallucinated the rate")
            return

    if freight > total_amount * 0.5:
        issues.append(f"Freight (₹{freight:.2f}) seems high relative to total (₹{total_amount:.2f})")

    if tds > total_amount * 0.2:
        issues.append(f"TDS (₹{tds:.2f}) seems high relative to total (₹{total_amount:.2f})")

    if "amount_ranges" not in scores:
        scores["amount_ranges"] = 1.0


def _check_hsn_sac_codes(data: dict, scores: dict, issues: list):
    """Validate HSN/SAC codes on line items are reasonable."""
    items = [it for it in (data.get("line_items") or []) if isinstance(it, dict)]
    if not items:
        scores["hsn_sac"] = 0.5  # No items to check
        return

    valid_hsn_lengths = {4, 6, 8}
    valid_sac_lengths = {4, 5, 6}
    issues_found = 0

    for item in items:
        code = (item.get("hsn_sac") or "").strip()
        is_service = item.get("is_service", False)
        if not code:
            continue  # Missing is warned elsewhere, not hallucination

        code_clean = code.replace(" ", "").replace("-", "")
        if not code_clean.isdigit():
            issues_found += 1
            issues.append(f"HSN/SAC '{code}' contains non-numeric characters — likely OCR error")
        elif is_service and len(code_clean) not in valid_sac_lengths:
            issues_found += 1
            issues.append(f"SAC code '{code}' has {len(code_clean)} digits (expected 4-6)")
        elif not is_service and len(code_clean) not in valid_hsn_lengths:
            issues_found += 1
            issues.append(f"HSN code '{code}' has {len(code_clean)} digits (expected 4/6/8)")

    if issues_found > 0:
        scores["hsn_sac"] = max(0.0, 1.0 - issues_found * 0.2)
    else:
        scores["hsn_sac"] = 1.0


def _check_tds_fields(data: dict, scores: dict, issues: list):
    """Validate TDS fields are reasonable."""
    tds_amount = float(data.get("tds_amount", 0) or 0)
    tds_rate = float(data.get("tds_rate", 0) or 0)
    total_amount = float(data.get("total_amount", 0) or 0)

    if tds_amount <= 0 and tds_rate <= 0:
        scores["tds_fields"] = 1.0  # No TDS — not a problem
        return

    # TDS rate sanity: common rates are 1, 2, 5, 10, 20, 30
    valid_tds_rates = {0.1, 1, 2, 5, 10, 20, 30}
    if tds_rate > 0 and tds_rate not in valid_tds_rates:
        # Check if it's close to a valid rate
        nearest = min(valid_tds_rates, key=lambda x: abs(x - tds_rate))
        if abs(tds_rate - nearest) > 1:
            scores["tds_fields"] = 0.3
            issues.append(f"TDS rate {tds_rate}% is unusual — valid rates are {sorted(valid_tds_rates)}")
            return

    # TDS amount sanity: should be <= total_amount * max_rate / 100
    if tds_amount > 0 and total_amount > 0:
        max_possible = total_amount * 0.30  # Max TDS is 30% (lottery winnings)
        if tds_amount > max_possible:
            scores["tds_fields"] = 0.2
            issues.append(f"TDS amount ₹{tds_amount:.2f} exceeds 30% of total ₹{total_amount:.2f} — likely hallucinated")
            return

    scores["tds_fields"] = 1.0


def _check_place_of_supply(data: dict, scores: dict, issues: list):
    """Validate place of supply is a valid Indian state."""
    from schemas import GST_STATE_CODES

    pos = data.get("place_of_supply", "")
    if not pos:
        scores["place_of_supply"] = 0.8  # Missing is a warning, not hallucination
        issues.append("Place of supply not provided — required for GST routing")
        return

    # Check if it's a state code (2 digits)
    if pos.strip().isdigit() and len(pos.strip()) == 2:
        if pos.strip() in GST_STATE_CODES:
            scores["place_of_supply"] = 1.0
        else:
            scores["place_of_supply"] = 0.3
            issues.append(f"Place of supply code '{pos}' is not a valid GST state code")
        return

    # Check if it's a state name
    pos_lower = pos.lower().strip()
    valid_names = [name.lower() for name in GST_STATE_CODES.values()]
    # Also check partial matches
    if any(pos_lower in name or name in pos_lower for name in valid_names):
        scores["place_of_supply"] = 1.0
    else:
        # Could be valid but unusual format — score conservatively
        scores["place_of_supply"] = 0.7
        issues.append(f"Place of supply '{pos}' could not be matched to a known state — verify")
