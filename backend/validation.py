"""Validation engine for invoice extraction and Tally XML generation.

Stages:
  1. Document classification
  2. Extraction validation (fields, GSTIN, dates, amounts, tax, duplicates, confidence)
  3. Accounting mapping
  4. Tally XML validation
  5. Review decision engine
"""

import re
from datetime import date, datetime, timezone
from typing import Optional

COMPANY_STATE_CODE = None  # set by main.py at import time

PLACEHOLDER_PATTERNS = re.compile(
    r"\[.*?\]|\(.*?\)|<.*?>|^[-\s]*$|^(?:n/?a|n/a|none|null|undefined|tbd)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# STAGE 1 — Document Classification
# ---------------------------------------------------------------------------

def classify_document(data: dict) -> str:
    """Classify document type based on extracted fields."""
    gstin = (data.get("gstin") or "").strip()
    vendor = (data.get("vendor_name") or "").strip()
    items = data.get("line_items") or []
    total = data.get("total_amount") or 0

    has_gst = bool(gstin)
    has_items = len(items) > 0
    has_vendor = bool(vendor)

    if has_gst and has_vendor and has_items:
        return "gst_invoice"
    if not has_gst and has_vendor and has_items:
        return "retail_bill"
    if not has_gst and has_vendor and not has_items and total > 0:
        return "expense_receipt"
    if has_gst and has_vendor and not has_items:
        return "purchase_invoice"
    return "unknown"


# ---------------------------------------------------------------------------
# STAGE 2 — Extraction Validation Checks
# ---------------------------------------------------------------------------

def check_required_fields(data: dict) -> dict:
    required = ["vendor_name", "invoice_number", "date", "total_amount"]
    labels = {
        "vendor_name": "Vendor name",
        "invoice_number": "Invoice number",
        "date": "Invoice date",
        "total_amount": "Total amount",
    }
    missing = []
    for field in required:
        val = data.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(labels[field])
        elif field == "total_amount":
            try:
                if float(val) <= 0:
                    missing.append(labels[field])
            except (ValueError, TypeError):
                missing.append(labels[field])

    return {
        "pass": len(missing) == 0,
        "missing": missing,
        "message": f"Missing: {', '.join(missing)}" if missing else "All core fields present",
    }


def check_gstin(data: dict, doc_type: str) -> dict:
    gstin = (data.get("gstin") or "").strip()
    pattern = r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d[Z]{1}[A-Z\d]{1}$"

    if doc_type in ("gst_invoice", "purchase_invoice"):
        if not gstin:
            return {"pass": False, "message": "GSTIN required for GST invoice but missing"}
        if not re.match(pattern, gstin):
            return {"pass": False, "message": f"Invalid GSTIN format: {gstin}"}
        # Validate state code (first 2 digits)
        state_code = gstin[:2]
        valid_states = set(f"{i:02d}" for i in range(1, 38))  # 01-37
        if state_code not in valid_states:
            return {"pass": False, "message": f"Invalid GST state code: {state_code}"}
        return {"pass": True, "message": "GSTIN is valid", "state_code": state_code}

    # Retail bill / expense receipt — GSTIN is optional
    if gstin and not re.match(pattern, gstin):
        return {"pass": False, "message": f"GSTIN present but invalid format: {gstin}"}
    return {"pass": True, "message": "GSTIN not required for this document type"}


def check_date(data: dict) -> dict:
    date_str = (data.get("date") or "").strip()
    if not date_str:
        return {"pass": False, "message": "Date is missing"}

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return {"pass": False, "message": f"Date format must be YYYY-MM-DD, got: {date_str}"}

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"pass": False, "message": f"Invalid date: {date_str}"}

    today = date.today()
    warnings = []

    if dt > today:
        return {"pass": False, "message": f"Date is in the future: {date_str}"}
    if dt < date(2000, 1, 1):
        warnings.append(f"Date is unusually old: {date_str}")
    if (today - dt).days > 365 * 10:
        warnings.append(f"Date is more than 10 years old: {date_str}")

    if warnings:
        return {"pass": True, "warnings": warnings, "message": "; ".join(warnings)}
    return {"pass": True, "message": "Date is valid"}


def check_amount(data: dict) -> dict:
    """Verify subtotal + taxes ≈ total with ±2 tolerance.
    Handles both per-line-item cgst/sgst/igst fields and top-level taxes list.
    """
    total = data.get("total_amount")
    try:
        total = float(total)
    except (ValueError, TypeError):
        return {"pass": False, "message": "Total amount is not a valid number"}

    items = data.get("line_items") or []
    if not items:
        return {"pass": True, "message": "No line items to verify against (single amount entry)"}

    calc_taxable = 0.0
    calc_tax = 0.0
    for item in items:
        try:
            calc_taxable += float(item.get("taxable_value", 0))
            # Per-item tax fields
            calc_tax += float(item.get("cgst") or 0)
            calc_tax += float(item.get("sgst") or 0)
            calc_tax += float(item.get("igst") or 0)
        except (ValueError, TypeError):
            pass

    # Also sum top-level taxes list (TaxEntry format) if present and per-item was zero
    if calc_tax == 0.0:
        for t in data.get("taxes") or []:
            try:
                calc_tax += float(t.get("amount", 0) if isinstance(t, dict) else getattr(t, "amount", 0))
            except (ValueError, TypeError):
                pass

    calc_total = calc_taxable + calc_tax
    diff = abs(calc_total - total)
    tolerance = 2.0

    if diff <= tolerance:
        return {"pass": True, "message": f"Total ₹{total:.2f} matches calculated ₹{calc_total:.2f} (diff ₹{diff:.2f})", "computed_total": round(calc_total, 2), "tolerance_used": tolerance}
    else:
        return {"pass": False, "message": f"Total ₹{total:.2f} ≠ calculated ₹{calc_total:.2f} (diff ₹{diff:.2f}, tolerance ₹{tolerance:.2f})", "computed_total": round(calc_total, 2), "tolerance_used": tolerance}


def check_tax_structure(data: dict, doc_type: str) -> dict:
    items = data.get("line_items") or []
    if not items:
        return {"pass": True, "message": "No line items to verify tax structure"}

    has_cgst = any(item.get("cgst") is not None and float(item["cgst"]) > 0 for item in items if item.get("cgst") is not None)
    has_sgst = any(item.get("sgst") is not None and float(item["sgst"]) > 0 for item in items if item.get("sgst") is not None)
    has_igst = any(item.get("igst") is not None and float(item["igst"]) > 0 for item in items if item.get("igst") is not None)
    gstin = (data.get("gstin") or "").strip()

    issues = []

    # CGST without SGST (or vice versa) is suspicious
    if has_cgst and not has_sgst:
        issues.append("CGST present but SGST is missing")
    if has_sgst and not has_cgst:
        issues.append("SGST present but CGST is missing")

    # IGST with CGST/SGST is wrong structure
    if has_igst and (has_cgst or has_sgst):
        issues.append("IGST should not coexist with CGST/SGST")

    # Determine expected tax type from GSTIN
    if gstin:
        match = re.match(r"^(\d{2})", gstin)
        if match:
            vendor_state = match.group(1)
            company_state = "27"  # default, overridden by env
            if COMPANY_STATE_CODE:
                company_state = COMPANY_STATE_CODE
            if vendor_state == company_state:
                # Intra-state: expect CGST+SGST
                if has_igst and not has_cgst and not has_sgst:
                    issues.append(f"Intra-state transaction (state {vendor_state}) but IGST used instead of CGST+SGST")
            else:
                # Inter-state: expect IGST
                if (has_cgst or has_sgst) and not has_igst:
                    issues.append(f"Inter-state transaction (vendor state {vendor_state}) but CGST/SGST used instead of IGST")

    if issues:
        return {"pass": False, "issues": issues, "message": "; ".join(issues)}
    return {"pass": True, "message": "Tax structure is consistent"}


def check_duplicate(data: dict, existing_invoices: list) -> dict:
    vendor = (data.get("vendor_name") or "").strip().lower()
    inv_no = (data.get("invoice_number") or "").strip().lower()
    total = data.get("total_amount")

    if not vendor or not inv_no:
        return {"pass": True, "message": "Insufficient data for duplicate check"}

    for existing in existing_invoices:
        ed = existing.get("extracted", {})
        ev = (ed.get("vendor_name") or "").strip().lower()
        ei = (ed.get("invoice_number") or "").strip().lower()
        et = ed.get("total_amount")

        if ev == vendor and ei == inv_no:
            match = True
            if total is not None and et is not None:
                try:
                    if abs(float(total) - float(et)) > 2:
                        match = False
                except (ValueError, TypeError):
                    pass
            if match:
                dup_id = existing.get("id") or existing.get("_id") or ""
                return {
                    "pass": False,
                    "duplicate_id": str(dup_id),
                    "message": f"Duplicate: vendor '{data.get('vendor_name')}' invoice '{inv_no}' already exists (ID: {dup_id})",
                }

    return {"pass": True, "message": "No duplicate detected"}


def check_low_confidence(data: dict) -> dict:
    confidence = data.get("confidence")
    if confidence is None:
        return {"pass": True, "message": "No confidence score available"}

    issues = []
    if confidence < 0.3:
        issues.append(f"Very low confidence: {confidence:.0%}")
    elif confidence < 0.6:
        issues.append(f"Moderate confidence: {confidence:.0%} — review recommended")

    # Check for empty/blank fields that suggest poor extraction
    empty_count = 0
    for field in ["vendor_name", "invoice_number", "date"]:
        if not (data.get(field) or "").strip():
            empty_count += 1
    if empty_count > 1 and confidence < 0.7:
        issues.append(f"{empty_count} core fields empty despite {confidence:.0%} confidence")

    if issues:
        return {"pass": False, "issues": issues, "message": "; ".join(issues)}
    return {"pass": True, "message": "Confidence is acceptable"}


def check_placeholders(data: dict) -> dict:
    """Detect placeholder/bogus values that should block auto-generation."""
    fields_to_check = [
        "vendor_name", "invoice_number", "vendor_gstin", "gstin",
        "buyer_name", "buyer_gstin",
    ]
    line_items = data.get("line_items") or []
    found = []
    for field in fields_to_check:
        val = (data.get(field) or "").strip()
        if val and PLACEHOLDER_PATTERNS.match(val):
            found.append(f"{field} contains placeholder: '{val}'")
    for i, item in enumerate(line_items):
        desc = (item.get("description") or "").strip()
        if desc and PLACEHOLDER_PATTERNS.match(desc):
            found.append(f"line_item[{i}] description is placeholder: '{desc}'")
    if found:
        return {"pass": False, "found": found, "message": "; ".join(found), "needs_review": True}
    return {"pass": True, "message": "No placeholders detected"}


# ---------------------------------------------------------------------------
# STAGE 3 — Accounting Mapping
# ---------------------------------------------------------------------------

def map_accounts(data: dict, doc_type: str) -> dict:
    """Determine voucher type, party ledger, purchase ledger, and GST ledgers."""
    vendor = (data.get("vendor_name") or "").strip()

    if doc_type in ("gst_invoice", "purchase_invoice"):
        voucher_type = "Purchase"
        party_ledger = vendor
        purchase_ledger = "Purchase"
        gst_ledgers = {"cgst": "CGST", "sgst": "SGST", "igst": "IGST"}
    elif doc_type == "retail_bill":
        voucher_type = "Expense"
        party_ledger = vendor
        purchase_ledger = "Office Expenses"
        gst_ledgers = {}
    elif doc_type == "expense_receipt":
        voucher_type = "Expense"
        party_ledger = vendor
        purchase_ledger = "Office Expenses"
        gst_ledgers = {}
    else:
        voucher_type = "Purchase"
        party_ledger = vendor or "Unknown Supplier"
        purchase_ledger = "Purchase"
        gst_ledgers = {"cgst": "CGST", "sgst": "SGST", "igst": "IGST"}

    return {
        "voucher_type": voucher_type,
        "party_ledger": party_ledger,
        "purchase_ledger": purchase_ledger,
        "gst_ledgers": gst_ledgers,
    }


# ---------------------------------------------------------------------------
# STAGE 4 — Tally XML Validation
# ---------------------------------------------------------------------------

def validate_xml(xml_str: str, data: dict) -> list:
    """Validate generated XML before returning to client."""
    issues = []
    if not xml_str:
        issues.append("XML content is empty")
        return issues

    if not xml_str.strip().startswith("<?xml"):
        issues.append("XML declaration missing")

    if "<ENVELOPE>" not in xml_str:
        issues.append("Root <ENVELOPE> element missing")

    # Check balanced debits/credits
    amounts = re.findall(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", xml_str)
    debit_total = 0.0
    credit_total = 0.0
    for amt_str in amounts:
        try:
            amt = float(amt_str)
            if amt >= 0:
                debit_total += amt
            else:
                credit_total += abs(amt)
        except ValueError:
            issues.append(f"Non-numeric amount in XML: {amt_str}")

    if abs(debit_total - credit_total) > 0.01:
        issues.append(f"Voucher not balanced: debits ₹{debit_total:.2f} ≠ credits ₹{credit_total:.2f}")

    # Check date format in XML
    dates = _re.findall(r"<DATE>(\d{8})</DATE>", xml_str)
    for d in dates:
        if not _re.match(r"^\d{8}$", d):
            issues.append(f"Invalid date format in XML: {d}")

    # Check for unsafe characters in text content
    text_contents = _re.findall(r">([^<]+)<", xml_str)
    for text in text_contents:
        if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            issues.append(f"XML contains control characters in: '{text[:50]}...'")

    return issues


# ---------------------------------------------------------------------------
# STAGE 5 — Review Decision Engine
# ---------------------------------------------------------------------------

def decide_review(validation_results: dict) -> dict:
    """Weighted confidence — only core fields affect HIGH/LOW."""
    checks = validation_results.get("checks", {})
    doc_type = validation_results.get("document_type", "unknown")

    passed = 0
    failed = 0
    critical_failures = []
    needs_review = False

    for name, result in checks.items():
        if result.get("pass", False):
            passed += 1
        else:
            failed += 1
            if name in ("required_fields", "amount"):
                critical_failures.append(name)
        if result.get("needs_review"):
            needs_review = True

    total_checks = passed + failed
    score = passed / total_checks if total_checks > 0 else 0.0

    core_ok = (
        checks.get("required_fields", {}).get("pass", True)
        and checks.get("amount", {}).get("pass", True)
    )

    if core_ok and failed == 0 and not needs_review:
        decision = "high"
        action = "generate_auto"
        label = "High Confidence"
        color = "green"
    elif core_ok and not needs_review:
        decision = "medium"
        action = "review_dashboard"
        label = "Medium Confidence"
        color = "yellow"
    elif needs_review:
        decision = "medium"
        action = "review_dashboard"
        label = "Needs Review"
        color = "yellow"
    else:
        decision = "low"
        action = "manual_review"
        label = "Low Confidence"
        color = "red"

    return {
        "decision": decision,
        "action": action,
        "label": label,
        "color": color,
        "score": round(score, 2),
        "passed": passed,
        "failed": failed,
        "total": total_checks,
        "critical_failures": critical_failures,
        "needs_review": needs_review,
        "summary": _build_summary(decision, doc_type, critical_failures, checks),
    }


def _build_summary(decision: str, doc_type: str, critical_failures: list, checks: dict) -> str:
    if decision == "high":
        return "All validations passed. Ready for XML generation."
    parts = [f"Document classified as '{doc_type}'."]
    if critical_failures:
        parts.append(f"Critical issues in: {', '.join(critical_failures)}.")
    # Collect warning messages
    warnings = []
    for name, result in checks.items():
        if result.get("pass") and result.get("warnings"):
            warnings.extend(result["warnings"])
    if warnings:
        parts.append(f"Warnings: {'; '.join(warnings)}.")
    if decision == "low":
        parts.append("Manual review required before XML generation.")
    elif decision == "medium":
        parts.append("Review recommended before XML generation.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main validation orchestrator
# ---------------------------------------------------------------------------

def run_full_validation(data: dict, existing_invoices: list) -> dict:
    """Run all validation stages and return results."""
    doc_type = classify_document(data)

    checks = {
        "required_fields": check_required_fields(data),
        "gstin": check_gstin(data, doc_type),
        "date": check_date(data),
        "amount": check_amount(data),
        "tax_structure": check_tax_structure(data, doc_type),
        "duplicate": check_duplicate(data, existing_invoices),
        "low_confidence": check_low_confidence(data),
        "placeholders": check_placeholders(data),
    }

    accounts = map_accounts(data, doc_type)
    decision = decide_review({"checks": checks, "document_type": doc_type})

    return {
        "document_type": doc_type,
        "checks": checks,
        "accounts": accounts,
        "decision": decision,
    }
