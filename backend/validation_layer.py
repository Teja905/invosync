"""Production validation layer orchestrating all pre-export checks."""

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from company_config import CompanyConfig
from ledger_mapping import LedgerMappingEngine
from rules_engine import RulesEngine
from schemas import (
    StandardizedInvoice, VoucherType, GSTType, DocumentClass,
    LineItem, TaxEntry, ALLOWED_GST_SLABS,
)
from gst_engine import validate_gstin, determine_gst_type, validate_tax_structure
from voucher_classifier import classify_document_detailed, classify_voucher_type

_config = CompanyConfig()
_rules_engine = RulesEngine()
_ledger_engine = LedgerMappingEngine(_config, _rules_engine)

# Checks that block XML generation even with force=true.
# Missing vendor name / total amount creates broken vouchers.
# Unbalanced debits/credits, invalid dates, and amount math failures create wrong accounting.
BLOCKING_CHECKS = {
    "voucher_balance", "date",
}

# Check names within mandatory_fields that indicate a critical missing field.
CRITICAL_MISSING = {"Vendor name", "Valid total amount"}

# Commercial tolerance thresholds for Indian GST compliance.
# Variances within ₹0.50 → warning only (auto-allocated to Round Off).
# Variances ₹0.50–₹1.00 → soft error (overridable with force=true).
# Variances > ₹1.00 → blocking error (hard stop).
COMMERCIAL_PAISE_TOLERANCE = Decimal("0.50")
CRITICAL_COMPLIANCE_TOLERANCE = Decimal("1.00")


class ValidationResult:
    def __init__(self):
        self.passed: bool = True
        self.checks: dict = {}
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.corrections: dict = {}

    def add_check(self, name: str, passed: bool, message: str, details: Optional[dict] = None):
        entry = {
            "pass": passed,
            "message": message,
            **(details or {}),
        }
        self.checks[name] = entry
        if not passed:
            self.passed = False
            self.errors.append(f"{name}: {message}")

    def add_warning(self, message: str):
        self.warnings.append(message)

    @property
    def blocking_errors(self) -> list[str]:
        """Errors that hard-block XML generation regardless of force."""
        result = []
        for name, check in self.checks.items():
            if check.get("pass", True):
                continue
            if name == "mandatory_fields":
                msg = check.get("message", "")
                if any(c in msg for c in CRITICAL_MISSING):
                    result.append(msg)
            elif name in BLOCKING_CHECKS:
                result.append(check["message"])
        return result

    @property
    def soft_errors(self) -> list[str]:
        """Errors that warn but allow override via force=true."""
        result = []
        for name, check in self.checks.items():
            if check.get("pass", True):
                continue
            if name == "mandatory_fields":
                msg = check.get("message", "")
                if not any(c in msg for c in CRITICAL_MISSING):
                    result.append(msg)
            elif name not in BLOCKING_CHECKS:
                result.append(check["message"])
        return result

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "warnings": self.warnings,
            "errors": self.errors,
            "corrections": self.corrections,
            "blocking_errors": self.blocking_errors,
            "soft_errors": self.soft_errors,
        }


def has_blocking_errors(result: ValidationResult) -> bool:
    return len(result.blocking_errors) > 0


def _pre_validate_tax_routing(inv: StandardizedInvoice, result: ValidationResult):
    """Enforce statutory GST routing rules before any other check.
    These are legally non-negotiable under CGST Act, 2017.
    """
    issues = []

    vendor_code = (inv.vendor_gstin or "")[:2].strip()
    buyer_code = (inv.buyer_gstin or "")[:2].strip()

    has_cgst_sgst = any(t.type in ("cgst", "sgst") for t in inv.taxes)
    has_igst = any(t.type == "igst" for t in inv.taxes)

    # Rule 1: SEZ override — must use IGST only
    if inv.is_sez and has_cgst_sgst:
        issues.append("SEZ transaction: CGST/SGST not allowed. Use IGST only.")

    # Rule 2: Intra-state (codes match) — must use CGST+SGST, reject IGST
    # SEZ overrides: IGST is correct even when state codes match
    if vendor_code and buyer_code and vendor_code == buyer_code and not inv.is_sez:
        if has_igst:
            issues.append(
                f"Intra-state supply (Code {vendor_code}): IGST not allowed. "
                f"Use CGST + SGST."
            )
        if not has_cgst_sgst and not has_igst and inv.taxes:
            issues.append(
                f"Intra-state supply: expected CGST + SGST entries, got none."
            )

    # Rule 3: Inter-state (codes differ) — must use IGST, reject CGST/SGST
    if vendor_code and buyer_code and vendor_code != buyer_code:
        if has_cgst_sgst:
            issues.append(
                f"Inter-state supply (Code {vendor_code} -> {buyer_code}): "
                f"CGST/SGST not allowed. Use IGST only."
            )

    # Rule 4: LUT / Composition — zero-tax only
    if inv.is_lut:
        if any(t.amount > 0 for t in inv.taxes):
            issues.append("LUT transaction: all tax amounts must be zero.")
        for item in inv.line_items:
            if item.tax_rate > 0:
                issues.append(
                    f"LUT transaction: item '{item.description}' has tax rate "
                    f"{item.tax_rate}% — must be 0%."
                )
                break

    # Rule 5: RCM — tax ledgers should use (RCM) naming
    if inv.is_rcm:
        rcm_names = [t.name for t in inv.taxes if "(RCM)" not in (t.name or "")]
        if rcm_names:
            result.add_warning(
                f"RCM transaction: tax ledgers should include '(RCM)' suffix for clarity. "
                f"Affected: {', '.join(rcm_names[:3])}"
            )

    if issues:
        result.add_check("statutory_routing", False, "; ".join(issues))
    else:
        result.add_check("statutory_routing", True, "Statutory tax routing valid")


def validate_invoice_for_xml(inv: StandardizedInvoice) -> ValidationResult:
    result = ValidationResult()

    _pre_validate_tax_routing(inv, result)
    _check_mandatory_fields(inv, result)
    _check_voucher_balance(inv, result)
    _check_gstin(inv, result)
    _check_dates(inv, result)
    _check_tax_rates(inv, result)
    _check_gst_structure(inv, result)
    _check_amount_math(inv, result)
    _check_line_items(inv, result)
    _check_voucher_type(inv, result)
    _check_ledger_fallback(inv, result)
    _check_expense_classification(inv, result)
    _list_referenced_ledgers(inv, result)
    _check_adjustment_note_linkage(inv, result)

    return result


def _check_mandatory_fields(inv: StandardizedInvoice, result: ValidationResult):
    missing = []
    voucher_type = inv.voucher_type.value if inv.voucher_type else ""
    
    # Vendor name optional for Journal vouchers
    if voucher_type != "Journal":
        if not inv.vendor_name or not inv.vendor_name.strip():
            missing.append("Vendor name")
    
    if not inv.invoice_number:
        missing.append("Invoice number")
    if not inv.invoice_date:
        missing.append("Invoice date")
    
    # Credit/Debit notes can have negative totals
    if voucher_type not in ("Credit Note", "Debit Note"):
        if inv.total_amount <= 0:
            missing.append("Valid total amount")
    
    if not inv.is_service and not inv.line_items:
        missing.append("Line items")
    if missing:
        result.add_check("mandatory_fields", False, f"Missing: {', '.join(missing)}")
    else:
        result.add_check("mandatory_fields", True, "All mandatory fields present")


def _check_voucher_balance(inv: StandardizedInvoice, result: ValidationResult):
    issues = []
    voucher_type = inv.voucher_type.value if inv.voucher_type else ""

    # Credit/Debit notes can have negative totals
    if voucher_type not in ("Credit Note", "Debit Note"):
        if inv.total_amount <= 0:
            issues.append(f"Total amount must be positive: Rs.{inv.total_amount:.2f}")

    if voucher_type not in ("Credit Note", "Debit Note"):
        if inv.total_taxable_value > inv.total_amount + 1:
            issues.append(f"Taxable value Rs.{inv.total_taxable_value:.2f} exceeds total Rs.{inv.total_amount:.2f}")

    total_tax = sum(t.amount for t in inv.taxes)
    if total_tax > 0 and total_tax > inv.total_taxable_value * 0.5:
        issues.append(f"Tax Rs.{total_tax:.2f} seems high relative to taxable Rs.{inv.total_taxable_value:.2f}")

    # Negative tax entries are allowed for Credit/Debit notes
    if voucher_type not in ("Credit Note", "Debit Note"):
        for t in inv.taxes:
            if t.amount < 0:
                issues.append(f"Negative tax entry: {t.name} Rs.{t.amount:.2f}")

    if inv.tds_amount < 0:
        issues.append(f"TDS amount is negative: Rs.{inv.tds_amount:.2f}")

    computed = inv.total_taxable_value + total_tax + inv.freight + inv.round_off - inv.tds_amount
    diff = Decimal(str(abs(computed - inv.total_amount)))

    if diff > Decimal("0.00"):
        if diff <= COMMERCIAL_PAISE_TOLERANCE:
            result.add_warning(
                f"Minor rounding drift of ₹{diff:.2f} between components and total. "
                f"Auto-allocated to Round Off ledger."
            )
        elif diff <= CRITICAL_COMPLIANCE_TOLERANCE:
            result.add_check(
                "voucher_soft_balance", False,
                f"Total variance ₹{diff:.2f}: components Rs.{computed:.2f} "
                f"≠ invoice total Rs.{inv.total_amount:.2f}. "
                f"Requires confirmation or force override.",
            )
        else:
            issues.append(
                f"Critical Math Mismatch: components Rs.{computed:.2f} "
                f"≠ invoice total Rs.{inv.total_amount:.2f} (diff Rs.{diff:.2f}). "
                f"File generation blocked."
            )

    if issues:
        result.add_check("voucher_balance", False, "; ".join(issues))
    else:
        result.add_check("voucher_balance", True, f"Voucher structurally valid: Rs.{computed:.2f} = Rs.{inv.total_amount:.2f}")


def _check_gstin(inv: StandardizedInvoice, result: ValidationResult):
    if inv.vendor_gstin:
        gst_result = validate_gstin(inv.vendor_gstin)
        if not gst_result["valid"]:
            result.add_check("gstin_vendor", False, gst_result["message"])
        else:
            result.add_check("gstin_vendor", True, "Vendor GSTIN valid")
    else:
        result.add_check("gstin_vendor", True, "No vendor GSTIN provided (non-GST invoice)")
    if inv.buyer_gstin:
        gst_result = validate_gstin(inv.buyer_gstin)
        if not gst_result["valid"]:
            result.add_check("gstin_buyer", False, f"Buyer GSTIN: {gst_result['message']}")
        else:
            result.add_check("gstin_buyer", True, "Buyer GSTIN valid")


def _check_dates(inv: StandardizedInvoice, result: ValidationResult):
    date_str = inv.invoice_date
    if not date_str:
        result.add_check("date", False, "Invoice date missing")
        return
    fmt = "%Y-%m-%d"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        fmt = "%Y-%m-%d"
    elif re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
        fmt = "%d/%m/%Y"
    else:
        result.add_check("date", False, f"Date format invalid: {date_str} (expected YYYY-MM-DD or DD/MM/YYYY)")
        return
    try:
        dt = datetime.strptime(date_str, fmt).date()
    except ValueError:
        result.add_check("date", False, f"Invalid date: {date_str}")
        return
    today = date.today()
    issues = []
    if dt > today:
        issues.append(f"Future date: {date_str}")
    if dt < date(2000, 1, 1):
        issues.append(f"Unusually old date: {date_str}")
    if (today - dt).days > 365 * 10:
        issues.append(f"More than 10 years old: {date_str}")
    if issues:
        result.add_check("date", False, "; ".join(issues))
    else:
        result.add_check("date", True, "Date valid")


def _check_tax_rates(inv: StandardizedInvoice, result: ValidationResult):
    rates_seen = set()
    for item in inv.line_items:
        r = item.tax_rate
        if r == 0:
            continue
        rates_seen.add(r)
        if r not in ALLOWED_GST_SLABS:
            near = min(ALLOWED_GST_SLABS, key=lambda x: abs(x - r))
            if abs(r - near) <= 0.5:
                result.add_warning(f"Tax rate {r}% corrected to {near}% for '{item.description}'")
                result.corrections[f"line_item_rate_{item.description}"] = near
            else:
                result.add_check(
                    "tax_rates", False,
                    f"Invalid GST rate {r}% for '{item.description}'. Allowed: {sorted(ALLOWED_GST_SLABS)}",
                )
    if rates_seen and not result.checks.get("tax_rates", {}).get("pass", True):
        pass
    else:
        if "tax_rates" not in result.checks:
            result.add_check("tax_rates", True, "All tax rates valid")


def _check_gst_structure(inv: StandardizedInvoice, result: ValidationResult):
    issues = validate_tax_structure(inv.taxes)
    if issues:
        result.add_check("gst_structure", False, "; ".join(issues))
    else:
        has_taxes = len(inv.taxes) > 0
        if has_taxes:
            result.add_check("gst_structure", True, "GST structure valid")


def _check_amount_math(inv: StandardizedInvoice, result: ValidationResult):
    if inv.line_items:
        calc_taxable = sum(item.taxable_value for item in inv.line_items)
        if abs(calc_taxable - inv.total_taxable_value) > 0.10:
            result.add_check(
                "amount_taxable", False,
                f"Line items taxable Rs.{calc_taxable:.2f} != header taxable Rs.{inv.total_taxable_value:.2f}",
            )
        else:
            if "amount_taxable" not in result.checks:
                result.add_check("amount_taxable", True, f"Taxable amount valid: Rs.{calc_taxable:.2f}")
    else:
        calc_taxable = inv.total_taxable_value
    calc_tax = sum(t.amount for t in inv.taxes)
    if abs(calc_tax - inv.total_tax) > 0.10:
        result.add_check(
            "amount_tax", False,
            f"Computed tax Rs.{calc_tax:.2f} != header tax Rs.{inv.total_tax:.2f}",
        )
    else:
        if "amount_tax" not in result.checks:
            result.add_check("amount_tax", True, f"Tax amount valid: Rs.{calc_tax:.2f}")
    calc_total = calc_taxable + calc_tax + inv.freight + inv.round_off - inv.tds_amount
    diff = Decimal(str(abs(calc_total - inv.total_amount)))
    if diff > Decimal("0.00"):
        if diff <= COMMERCIAL_PAISE_TOLERANCE:
            if "amount_total" not in result.checks:
                result.add_check("amount_total", True, f"Total amount valid: Rs.{calc_total:.2f}")
            result.add_warning(
                f"Minor rounding drift of ₹{diff:.2f} between computed total and header. "
                f"Auto-allocated to Round Off ledger."
            )
        elif diff <= CRITICAL_COMPLIANCE_TOLERANCE:
            result.add_check(
                "amount_total", False,
                f"Total variance ₹{diff:.2f}: computed Rs.{calc_total:.2f} "
                f"≠ header Rs.{inv.total_amount:.2f}. Requires confirmation or force override.",
            )
        else:
            result.add_check(
                "voucher_balance", False,
                f"Critical Math Mismatch: computed total Rs.{calc_total:.2f} "
                f"≠ header total Rs.{inv.total_amount:.2f} (diff Rs.{diff:.2f}). "
                f"File generation blocked.",
            )
    else:
        if "amount_total" not in result.checks:
            result.add_check("amount_total", True, f"Total amount valid: Rs.{calc_total:.2f}")


def _check_line_items(inv: StandardizedInvoice, result: ValidationResult):
    for i, item in enumerate(inv.line_items):
        if not item.description:
            result.add_check(f"line_item_{i}_desc", False, f"Line item {i+1} missing description")
        if item.quantity <= 0 and item.taxable_value > 0:
            result.add_warning(f"Line item '{item.description}': quantity missing, using taxable value")
        calc_taxable = round(item.quantity * item.rate, 2)
        if item.quantity > 0 and abs(calc_taxable - item.taxable_value) > 0.10:
            result.add_check(
                f"line_item_{i}_math", False,
                f"'{item.description}': qtyxrate Rs.{calc_taxable:.2f} != taxable Rs.{item.taxable_value:.2f}",
            )


def _check_voucher_type(inv: StandardizedInvoice, result: ValidationResult):
    doc_class = classify_document_detailed({
        "vendor_gstin": inv.vendor_gstin,
        "gstin": inv.vendor_gstin,
        "vendor_name": inv.vendor_name,
        "line_items": [li.model_dump() for li in inv.line_items],
        "total_amount": inv.total_amount,
    })
    if doc_class == DocumentClass.UNKNOWN:
        result.add_warning("Document type unclear, defaulting to Purchase")


def _check_ledger_fallback(inv: StandardizedInvoice, result: ValidationResult):
    for item in inv.line_items:
        if not item.description:
            continue
        match = _ledger_engine.map_expense_ledger_scored(item.description, amount=item.taxable_value)
        if not match.ledger_name or match.confidence == 0.0:
            result.add_warning(
                f"Unmapped: '{item.description}' — no matching ledger found. "
                f"Suggestions: {', '.join(match.suggestions[:3])}. "
                f"Will use Suspense ledger pending your review."
            )
        elif match.confidence < 0.80:
            result.add_warning(
                f"Low confidence ({match.confidence*100:.0f}%) for '{item.description}' "
                f"→ '{match.ledger_name}'. Please confirm this is correct."
            )


def _check_expense_classification(inv: StandardizedInvoice, result: ValidationResult):
    if not inv.is_service:
        return
    if inv.voucher_type.value != "Purchase":
        return
    from voucher_classifier import SERVICE_KEYWORDS
    svc_items = []
    for item in inv.line_items:
        desc = (item.description or "").lower()
        if any(kw in desc for kw in SERVICE_KEYWORDS):
            svc_items.append(item.description)
    if svc_items:
        result.add_warning(
            f"Service expense detected: {'; '.join(svc_items[:3])}. "
            f"Voucher type is Purchase but these appear to be service expenses "
            f"(rent, fees, consulting, etc.). Consider reviewing the ledger."
        )


def _list_referenced_ledgers(inv: StandardizedInvoice, result: ValidationResult):
    ledgers: set[str] = set()
    for item in inv.line_items:
        if item.is_service:
            ledgers.add(_ledger_engine.map_expense_ledger(item.description))
        else:
            ledgers.add(_ledger_engine.map_purchase_ledger(item.description))
    if inv.cess_amount > 0:
        is_input = inv.voucher_type in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE)
        ledgers.add(_config.get_cess_ledger(is_input))
    if inv.freight > 0:
        ledgers.add(_config.get_freight_ledger())
    if inv.tds_amount > 0:
        ledgers.add(_config.get_tds_ledger())
    if inv.round_off != 0:
        ledgers.add(_config.get_round_off_ledger())
    if inv.voucher_type in (VoucherType.PAYMENT, VoucherType.RECEIPT):
        ledgers.add(_config.get_bank_ledger())
    if inv.voucher_type in (VoucherType.PURCHASE, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
        ledgers.add(_ledger_engine.map_purchase_ledger())
    if inv.voucher_type == VoucherType.SALES:
        ledgers.add(_ledger_engine.map_sales_ledger())
    for tax in inv.taxes:
        is_input = inv.voucher_type in (
            VoucherType.PURCHASE, VoucherType.JOURNAL,
            VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE,
        )
        ledgers.add(_config.get_gst_ledger(tax.type, tax.rate, is_input))
    for ledger in sorted(ledgers):
        result.add_warning(f"Ledger '{ledger}' will be referenced in XML")


def _extract_voucher_envelope(xml_str: str) -> str:
    """Extract only the voucher envelope from combined XML.
    In combined XML, the second <ENVELOPE> contains the voucher.
    In standalone voucher XML, the only <ENVELOPE> is the voucher."""
    envelopes = re.findall(r"<ENVELOPE>.*?</ENVELOPE>", xml_str, re.DOTALL)
    if not envelopes:
        return xml_str
    if len(envelopes) >= 2:
        return envelopes[-1]
    return envelopes[0]


def validate_xml_output(xml_str: str) -> ValidationResult:
    result = ValidationResult()
    if not xml_str:
        result.add_check("xml_content", False, "XML content is empty")
        return result
    if not xml_str.strip().startswith("<?xml"):
        result.add_check("xml_declaration", False, "Missing XML declaration")
    if "<ENVELOPE>" not in xml_str:
        result.add_check("xml_envelope", False, "Missing <ENVELOPE> root")
    if "<VOUCHER" not in xml_str:
        result.add_check("xml_voucher", False, "Missing <VOUCHER> element")

    voucher_xml = _extract_voucher_envelope(xml_str)
    voucher_xml = re.sub(
        r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>",
        "", voucher_xml, flags=re.DOTALL,
    )
    voucher_xml = re.sub(
        r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>",
        "", voucher_xml, flags=re.DOTALL,
    )

    entries = re.findall(
        r"<ALLLEDGERENTRIES\.LIST>.*?<ISDEEMEDPOSITIVE>(.*?)</ISDEEMEDPOSITIVE>.*?<AMOUNT>(-?\d+\.?\d*)</AMOUNT>.*?</ALLLEDGERENTRIES\.LIST>",
        voucher_xml, re.DOTALL,
    )
    if entries:
        debit_total = 0.0
        credit_total = 0.0
        for deemed, amt_str in entries:
            amt = float(amt_str)
            if deemed.strip() == "Yes":
                debit_total += amt
            else:
                credit_total += amt
        if abs(debit_total + credit_total) > 0.05:
            result.add_check(
                "xml_balance", False,
                f"XML unbalanced: ISDEEMEDPOSITIVE=Yes sum Rs.{debit_total:.2f} "
                f"+ ISDEEMEDPOSITIVE=No sum Rs.{credit_total:.2f} "
                f"= Rs.{debit_total + credit_total:.2f} (expected 0)",
            )
        else:
            result.add_check("xml_balance", True, "XML voucher balanced")
    else:
        amounts = re.findall(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", voucher_xml)
        if amounts:
            debit_total = 0.0
            credit_total = 0.0
            for amt_str in amounts:
                amt = float(amt_str)
                if amt >= 0:
                    debit_total += amt
                else:
                    credit_total += abs(amt)
            if abs(debit_total - credit_total) > 0.05:
                result.add_check(
                    "xml_balance", False,
                    f"XML unbalanced: positive AMOUNTs Rs.{debit_total:.2f}"
                    f" != negative AMOUNTs Rs.{credit_total:.2f}",
                )
            else:
                result.add_check("xml_balance", True, "XML voucher balanced")

    dates = re.findall(r"<DATE>(\d{8})</DATE>", voucher_xml)
    for d in dates:
        year = int(d[:4])
        month = int(d[4:6])
        day = int(d[6:8])
        if month < 1 or month > 12:
            result.add_check("xml_date", False, f"Invalid XML date: month {month} in {d}")
            break
        if day < 1 or day > 31:
            result.add_check("xml_date", False, f"Invalid XML date: day {day} in {d}")
            break
    return result


def _check_adjustment_note_linkage(inv: StandardizedInvoice, result: ValidationResult) -> None:
    """Credit/Debit Notes must reference the original invoice for Tally compliance."""
    if inv.voucher_type not in (VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
        return
    if not inv.original_invoice_number:
        result.add_check(
            "original_invoice_reference", False,
            f"Voucher type '{inv.voucher_type.value}' requires an original_invoice_number "
            f"linking to the invoice being amended. Without this, Tally cannot reconcile the adjustment."
        )


def verify_unbreakable_double_entry_balance(items: list, header_total: float, header_taxable: float) -> bool:
    """Verify line-item taxable sum matches header taxable to exact paisa precision."""
    dec_items_sum = sum(Decimal(str(item.taxable_value)) for item in items)
    dec_header = Decimal(str(header_taxable))
    items_rounded = dec_items_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    header_rounded = dec_header.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if items_rounded != header_rounded:
        raise ValueError(
            f"Voucher Integrity Violation: line items total Rs.{items_rounded} "
            f"!= header taxable Rs.{header_rounded}"
        )
    return True
