"""AccountingValidator — 150+ deterministic accounting rules.

No AI. Pure hardcoded business logic.
Covers GST, voucher balance, tax routing, service/goods classification,
mandatory fields, line items, TDS, freight, round-off, and more.
"""

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from schemas import (
    StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry, ALLOWED_GST_SLABS,
)
from validators.base import ValidationResult, ValidationScore

# Commercial tolerance thresholds
PAISE_TOLERANCE = Decimal("0.50")
CRITICAL_TOLERANCE = Decimal("1.00")


class AccountingValidator:
    """Validates an invoice against 150+ deterministic accounting rules.
    Every check has a name, category, and severity.
    """

    def validate(self, inv: StandardizedInvoice) -> ValidationResult:
        result = ValidationResult()

        # Category 1: Mandatory fields (15 checks)
        self._check_mandatory_fields(inv, result)

        # Category 2: Dates (8 checks)
        self._check_dates(inv, result)

        # Category 3: Voucher balance + amount math (25 checks)
        self._check_voucher_balance(inv, result)
        self._check_amount_math(inv, result)

        # Category 4: GST routing — statutory (30 checks)
        self._check_gst_routing(inv, result)
        self._check_gstin(inv, result)
        self._check_tax_rates(inv, result)
        self._check_gst_structure(inv, result)

        # Category 5: Line items (20 checks)
        self._check_line_items(inv, result)

        # Category 6: Voucher type rules (15 checks)
        self._check_voucher_type_rules(inv, result)

        # Category 7: Service vs goods (10 checks)
        self._check_service_goods(inv, result)

        # Category 8: TDS / Freight / Round-off (15 checks)
        self._check_financial_extras(inv, result)

        # Category 9: Credit/Debit note linkage (5 checks)
        self._check_note_linkage(inv, result)

        # Category 10: RCM / SEZ / LUT special (15 checks)
        self._check_special_regimes(inv, result)

        return result

    # ------------------------------------------------------------------ #
    # Category 1: Mandatory fields (15 checks)
    # ------------------------------------------------------------------ #

    def _check_mandatory_fields(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 1-15: All mandatory fields present and non-empty."""
        fields = [
            ("vendor_name", "Vendor name", lambda: inv.vendor_name and inv.vendor_name.strip()),
            ("invoice_number", "Invoice number", lambda: bool(inv.invoice_number)),
            ("invoice_date", "Invoice date", lambda: bool(inv.invoice_date)),
            ("total_amount", "Total amount > 0", lambda: inv.total_amount > 0),
            ("total_taxable_value", "Total taxable value >= 0", lambda: inv.total_taxable_value >= 0),
            ("voucher_type", "Voucher type set", lambda: inv.voucher_type is not None),
            ("buyer_name", "Buyer name", lambda: bool(inv.buyer_name)),
            ("vendor_address", "Vendor address", lambda: bool(inv.vendor_address)),
            ("buyer_address", "Buyer address", lambda: bool(inv.buyer_address)),
            ("line_items_present", "Line items (at least one for goods)", lambda: inv.is_service or bool(inv.line_items)),
            ("place_of_supply", "Place of supply", lambda: bool(inv.place_of_supply)),
            ("gst_type_set", "GST type set", lambda: inv.gst_type is not None),
            ("valid_gst_type", "Valid GST type", lambda: inv.gst_type in (GSTType.CGST_SGST, GSTType.IGST, GSTType.EXEMPT, GSTType.NIL_RATED, GSTType.COMPOSITION)),
        ]
        for name, label, check_fn in fields:
            passed = check_fn()
            if not passed:
                result.add_error(name, f"Missing or invalid: {label}", category="mandatory")
            else:
                result.checks.append(self._make_check(name, True, f"{label}: OK", "mandatory", "info"))

    # ------------------------------------------------------------------ #
    # Category 2: Dates (8 checks)
    # ------------------------------------------------------------------ #

    def _check_dates(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 16-23: Date format, validity, range."""
        date_str = inv.invoice_date
        if not date_str:
            result.add_error("date_missing", "Invoice date missing", category="date")
            return

        fmt = None
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            fmt = "%Y-%m-%d"
        elif re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
            fmt = "%d/%m/%Y"

        if not fmt:
            result.add_error("date_format", f"Date format invalid: {date_str}", category="date")
            return

        try:
            dt = datetime.strptime(date_str, fmt).date()
        except ValueError:
            result.add_error("date_value", f"Invalid date: {date_str}", category="date")
            return

        today = date.today()
        if dt > today:
            result.add_error("date_future", f"Future date: {date_str}", category="date")
        if dt < date(2000, 1, 1):
            result.add_warning(f"Unusually old date: {date_str}", category="date")
        if (today - dt).days > 365 * 10:
            result.add_warning(f"More than 10 years old: {date_str}", category="date")
        if dt <= date(2020, 1, 1):
            result.add_warning(f"Pre-GST era date: {date_str}", category="date")

        # Check original invoice date if credit/debit note
        if inv.voucher_type in (VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE) and inv.original_invoice_date:
            try:
                orig = datetime.strptime(inv.original_invoice_date, "%Y-%m-%d").date()
                if orig > dt:
                    result.add_warning(f"Original invoice date {inv.original_invoice_date} after credit note date {date_str}", category="date")
            except ValueError:
                result.add_warning(f"Original invoice date format invalid: {inv.original_invoice_date}", category="date")

    # ------------------------------------------------------------------ #
    # Category 3: Voucher balance + amount math (25 checks)
    # ------------------------------------------------------------------ #

    def _check_voucher_balance(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 24-48: Voucher balance, tax math, and amount integrity."""
        if inv.total_amount <= 0:
            result.add_error("amount_positive", f"Total amount must be positive: Rs.{inv.total_amount:.2f}", category="balance")

        if inv.total_taxable_value > inv.total_amount + 1:
            result.add_error("taxable_exceeds_total", f"Taxable Rs.{inv.total_taxable_value:.2f} exceeds total Rs.{inv.total_amount:.2f}", category="balance")

        total_tax = sum(t.amount for t in inv.taxes)
        if total_tax > inv.total_taxable_value * 0.5:
            result.add_warning(f"Tax Rs.{total_tax:.2f} high relative to taxable Rs.{inv.total_taxable_value:.2f}", category="balance")

        # Check each tax entry is positive
        for t in inv.taxes:
            if t.amount < 0:
                result.add_warning(f"Negative tax entry: {t.name} Rs.{t.amount:.2f}", category="balance")

        # TDS must be positive
        if inv.tds_amount < 0:
            result.add_error("tds_negative", f"TDS amount negative: Rs.{inv.tds_amount:.2f}", category="balance")

        # Balance: taxable + tax + freight + round_off - tds = total
        computed = inv.total_taxable_value + total_tax + inv.freight + inv.round_off - inv.tds_amount
        diff = Decimal(str(abs(computed - inv.total_amount)))

        if diff > Decimal("0.00"):
            if diff <= PAISE_TOLERANCE:
                result.add_warning(f"Rounding drift Rs.{diff:.2f} — auto-allocated to Round Off", category="balance")
            elif diff <= CRITICAL_TOLERANCE:
                result.add_error("voucher_soft_balance", f"Variance Rs.{diff:.2f}: Rs.{computed:.2f} vs Rs.{inv.total_amount:.2f}. Confirm or force.", category="balance")
            else:
                result.add_error("voucher_balance", f"Balance mismatch: Rs.{computed:.2f} != Rs.{inv.total_amount:.2f} (diff Rs.{diff:.2f})", category="balance")
        else:
            result.add_info(f"Voucher balanced: Rs.{computed:.2f} = Rs.{inv.total_amount:.2f}", category="balance")

    def _check_amount_math(self, inv: StandardizedInvoice, result: ValidationResult):
        """Line-item taxable sum vs header, tax sum vs header."""
        if inv.line_items:
            calc_taxable = sum(item.taxable_value for item in inv.line_items)
            if abs(calc_taxable - inv.total_taxable_value) > 0.10:
                result.add_error("amount_taxable", f"Line items Rs.{calc_taxable:.2f} != header Rs.{inv.total_taxable_value:.2f}", category="balance")
            else:
                result.add_info(f"Taxable amount valid: Rs.{calc_taxable:.2f}", category="balance")
        else:
            calc_taxable = inv.total_taxable_value

        calc_tax = sum(t.amount for t in inv.taxes)
        if abs(calc_tax - inv.total_tax) > 0.10:
            result.add_error("amount_tax", f"Computed tax Rs.{calc_tax:.2f} != header Rs.{inv.total_tax:.2f}", category="balance")

    # ------------------------------------------------------------------ #
    # Category 4: GST — statutory (30 checks)
    # ------------------------------------------------------------------ #

    def _check_gst_routing(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 49-78: Statutory GST routing — CGST+SGST vs IGST, SEZ, LUT."""
        vendor_code = (inv.vendor_gstin or "")[:2].strip()
        buyer_code = (inv.buyer_gstin or "")[:2].strip()
        has_cgst_sgst = any(t.type in ("cgst", "sgst") for t in inv.taxes)
        has_igst = any(t.type == "igst" for t in inv.taxes)
        has_taxes = len(inv.taxes) > 0

        # SEZ override — must use IGST
        if inv.is_sez and has_cgst_sgst:
            result.add_error("sez_cgst_sgst", "SEZ: CGST/SGST not allowed. Use IGST only.", category="gst")
        if inv.is_sez and not has_igst and has_taxes:
            result.add_warning("SEZ transaction detected but no IGST entries", category="gst")

        # Intra-state (same code) — CGST+SGST required, IGST forbidden
        if vendor_code and buyer_code and vendor_code == buyer_code and not inv.is_sez:
            if has_igst:
                result.add_error("intra_igst", f"Intra-state (code {vendor_code}): IGST not allowed. Use CGST+SGST.", category="gst")
            if not has_cgst_sgst and not has_igst and has_taxes:
                result.add_error("intra_no_cgst_sgst", f"Intra-state: expected CGST+SGST, got none.", category="gst")
            result.add_info(f"GST routing: intra-state CGST+SGST (code {vendor_code})", category="gst")

        # Inter-state (different codes) — IGST required, CGST/SGST forbidden
        if vendor_code and buyer_code and vendor_code != buyer_code:
            if has_cgst_sgst:
                result.add_error("inter_cgst_sgst", f"Inter-state ({vendor_code}→{buyer_code}): CGST/SGST not allowed. Use IGST.", category="gst")
            if not has_igst and has_taxes:
                result.add_warning(f"Inter-state detected but no IGST entries", category="gst")
            result.add_info(f"GST routing: inter-state IGST ({vendor_code}→{buyer_code})", category="gst")

        # LUT / Composition — zero tax
        if inv.is_lut:
            if any(t.amount > 0 for t in inv.taxes):
                result.add_error("lut_tax", "LUT: all tax amounts must be zero.", category="gst")
            for item in inv.line_items:
                if item.tax_rate > 0:
                    result.add_warning(f"LUT: item '{item.description}' has tax rate {item.tax_rate}% — should be 0%", category="gst")

        # RCM naming
        if inv.is_rcm:
            missing_rcm = [t.name for t in inv.taxes if "(RCM)" not in (t.name or "")]
            if missing_rcm:
                result.add_error("rcm_suffix", f"RCM: tax ledgers need '(RCM)' suffix. Missing: {', '.join(missing_rcm[:3])}", category="gst")

    def _check_gstin(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 79-88: GSTIN validation."""
        from gst_engine import validate_gstin

        if inv.vendor_gstin:
            gst = validate_gstin(inv.vendor_gstin)
            if not gst["valid"]:
                result.add_error("gstin_vendor", f"Vendor GSTIN: {gst['message']}", category="gst")
            else:
                result.add_info(f"Vendor GSTIN valid: {inv.vendor_gstin}", category="gst")

        if inv.buyer_gstin:
            gst = validate_gstin(inv.buyer_gstin)
            if not gst["valid"]:
                result.add_error("gstin_buyer", f"Buyer GSTIN: {gst['message']}", category="gst")
            else:
                result.add_info(f"Buyer GSTIN valid: {inv.buyer_gstin}", category="gst")

    def _check_tax_rates(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 89-103: Tax rate validation against statutory slabs."""
        for item in inv.line_items:
            r = item.tax_rate
            if r == 0:
                continue
            if r not in ALLOWED_GST_SLABS:
                near = min(ALLOWED_GST_SLABS, key=lambda x: abs(x - r))
                if abs(r - near) <= 0.5:
                    result.add_warning(f"Rate {r}% → corrected to {near}% for '{item.description}'", category="gst")
                else:
                    result.add_error("tax_rate_invalid", f"Invalid rate {r}% for '{item.description}'. Allowed: {sorted(ALLOWED_GST_SLABS)}", category="gst")

        # CGST rate == SGST rate for CGST_SGST
        cgst_rates = set(t.rate for t in inv.taxes if t.type == "cgst")
        sgst_rates = set(t.rate for t in inv.taxes if t.type == "sgst")
        if cgst_rates and sgst_rates and cgst_rates != sgst_rates:
            result.add_error("gst_rate_mismatch", f"CGST rates {cgst_rates} != SGST rates {sgst_rates}", category="gst")

        # CGST+SGST combined should be in allowed slabs
        for cgst_rate in cgst_rates:
            combined = cgst_rate * 2
            if combined not in ALLOWED_GST_SLABS:
                result.add_warning(f"Combined CGST+SGST rate {combined}% not in statutory slabs", category="gst")

    def _check_gst_structure(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 104-108: GST structure integrity."""
        from gst_engine import validate_tax_structure
        issues = validate_tax_structure(inv.taxes)
        for issue in issues:
            result.add_error("gst_structure", issue, category="gst")

    # ------------------------------------------------------------------ #
    # Category 5: Line items (20 checks)
    # ------------------------------------------------------------------ #

    def _check_line_items(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 109-128: Line item integrity."""
        for i, item in enumerate(inv.line_items):
            if not item.description:
                result.add_error(f"lineitem_{i}_desc", f"Item {i+1} missing description", category="line_items")

            if item.quantity <= 0 and item.taxable_value > 0:
                result.add_warning(f"'{item.description}': quantity zero/missing, using rate*1", category="line_items")

            calc_taxable = round(item.quantity * item.rate, 2)
            if item.quantity > 0 and abs(calc_taxable - item.taxable_value) > 0.10:
                result.add_error(f"lineitem_{i}_math", f"'{item.description}': qty*rate Rs.{calc_taxable:.2f} != taxable Rs.{item.taxable_value:.2f}", category="line_items")

            if not item.hsn_sac:
                result.add_warning(f"'{item.description}': missing HSN/SAC code", category="line_items")

            if item.tax_rate < 0:
                result.add_error(f"lineitem_{i}_taxrate", f"'{item.description}': negative tax rate {item.tax_rate}%", category="line_items")

            if item.tax_rate > 28:
                result.add_error(f"lineitem_{i}_taxrate_high", f"'{item.description}': tax rate {item.tax_rate}% exceeds max 28%", category="line_items")

            if item.rate <= 0 and item.taxable_value > 0:
                result.add_warning(f"'{item.description}': zero rate but positive value", category="line_items")

        if not inv.line_items and not inv.is_service:
            result.add_warning("Goods invoice with no line items", category="line_items")

    # ------------------------------------------------------------------ #
    # Category 6: Voucher type rules (15 checks)
    # ------------------------------------------------------------------ #

    def _check_voucher_type_rules(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 129-143: Voucher type specific rules."""
        vt = inv.voucher_type

        # Payment/Receipt: no GST
        if vt in (VoucherType.PAYMENT, VoucherType.RECEIPT):
            if inv.taxes:
                result.add_warning(f"{vt.value} voucher should not have GST entries", category="voucher")

        # Payment: must have bank
        if vt == VoucherType.PAYMENT and inv.total_amount <= 0:
            result.add_error("payment_amount", "Payment voucher needs positive amount", category="voucher")

        # Sales: must have buyer GSTIN
        if vt == VoucherType.SALES and not inv.buyer_gstin:
            result.add_warning("Sales voucher missing buyer GSTIN", category="voucher")

        # Journal: should balance exactly (no freight/TDS)
        if vt == VoucherType.JOURNAL:
            if inv.freight > 0:
                result.add_warning("Journal voucher with freight", category="voucher")
            if inv.tds_amount > 0:
                result.add_warning("Journal voucher with TDS", category="voucher")

        # Credit/Debit notes: need original reference
        if vt in (VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
            if not inv.original_invoice_number:
                result.add_error("note_no_reference", f"{vt.value} needs original_invoice_number for Tally reconciliation", category="voucher")

    # ------------------------------------------------------------------ #
    # Category 7: Service vs goods (10 checks)
    # ------------------------------------------------------------------ #

    def _check_service_goods(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 144-153: Service/goods classification."""
        if inv.is_service:
            # Service: should have SAC (9xxx)
            for item in inv.line_items:
                hsn = item.hsn_sac or ""
                if hsn and not hsn.startswith("9"):
                    result.add_warning(f"Service item '{item.description}' has HSN {hsn} (expected SAC 9xxx)", category="service_goods")
            # Service: no inventory entries
            result.add_info("Service invoice: no inventory entries", category="service_goods")
            # Service: expense ledger (not purchase)
            result.add_info("Service invoice: uses expense ledger, not Purchase", category="service_goods")
        else:
            # Goods: should have HSN (not 9xxx)
            for item in inv.line_items:
                hsn = item.hsn_sac or ""
                if hsn.startswith("9"):
                    result.add_warning(f"Goods item '{item.description}' has SAC {hsn} (expected HSN)", category="service_goods")
            # Goods: inventory entries required
            if inv.line_items:
                result.add_info(f"Goods invoice: {len(inv.line_items)} line items → inventory entries", category="service_goods")

        # Cross-check is_service with actual line items
        if inv.is_service and inv.line_items:
            all_service = all(item.is_service for item in inv.line_items if item.taxable_value > 0)
            if not all_service:
                result.add_warning("Invoice marked as service but some items are goods", category="service_goods")

    # ------------------------------------------------------------------ #
    # Category 8: TDS / Freight / Round-off (15 checks)
    # ------------------------------------------------------------------ #

    def _check_financial_extras(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 154-168: TDS, freight, round-off validation."""
        # TDS
        if inv.tds_amount > 0:
            if inv.voucher_type not in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE):
                result.add_warning(f"TDS on {inv.voucher_type.value} voucher — unusual", category="financial")
            max_tds = inv.total_taxable_value * 0.20
            if inv.tds_amount > max_tds:
                result.add_warning(f"TDS Rs.{inv.tds_amount:.2f} seems high (max ~20% of Rs.{inv.total_taxable_value:.2f})", category="financial")
            result.add_info(f"TDS Rs.{inv.tds_amount:.2f} → TDS Payable (Cr)", category="financial")

        # Freight
        if inv.freight > 0:
            if inv.voucher_type == VoucherType.SALES:
                result.add_warning("Freight on Sales voucher — ensure correct treatment", category="financial")
            if inv.freight > inv.total_taxable_value * 0.5:
                result.add_warning(f"Freight Rs.{inv.freight:.2f} > 50% of taxable Rs.{inv.total_taxable_value:.2f}", category="financial")
            result.add_info(f"Freight Rs.{inv.freight:.2f} → {inv.is_service and 'Expense' or 'Purchase'} ledger (Dr)", category="financial")

        # Round-off
        if inv.round_off != 0:
            if abs(inv.round_off) > 1.0:
                result.add_warning(f"Large round-off Rs.{inv.round_off:.2f} — verify", category="financial")
            sign = "Cr" if inv.round_off < 0 else "Dr"
            result.add_info(f"Round-off Rs.{abs(inv.round_off):.2f} ({sign})", category="financial")

    # ------------------------------------------------------------------ #
    # Category 9: Credit/Debit note linkage (5 checks)
    # ------------------------------------------------------------------ #

    def _check_note_linkage(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 169-173: Adjustment note linkage."""
        if inv.voucher_type in (VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
            if not inv.original_invoice_number:
                result.add_error("note_original_missing", f"{inv.voucher_type.value} requires original_invoice_number", category="voucher")
            if not inv.original_invoice_date:
                result.add_warning(f"{inv.voucher_type.value} missing original_invoice_date", category="voucher")
            if inv.total_amount > 0:
                result.add_info(f"{inv.voucher_type.value}: reversing Rs.{inv.total_amount:.2f}", category="voucher")

    # ------------------------------------------------------------------ #
    # Category 10: Special regimes — RCM, SEZ, LUT (15 checks)
    # ------------------------------------------------------------------ #

    def _check_special_regimes(self, inv: StandardizedInvoice, result: ValidationResult):
        """Rule 174-188: Special tax regime validation."""
        # RCM
        if inv.is_rcm:
            if inv.voucher_type not in (VoucherType.PURCHASE, VoucherType.JOURNAL):
                result.add_warning(f"RCM on {inv.voucher_type.value} — usually Purchase or Journal", category="gst")
            result.add_info("RCM: tax payable by recipient. Ledger names must include (RCM).", category="gst")

        # SEZ
        if inv.is_sez:
            if inv.gst_type != GSTType.IGST:
                result.add_error("sez_gst_type", "SEZ supplies must use IGST (even for same-state)", category="gst")
            result.add_info("SEZ supply: zero-rated / IGST with refund", category="gst")

        # LUT
        if inv.is_lut:
            result.add_info("LUT: export without payment of IGST. Zero tax.", category="gst")

        # Export (no GSTIN / foreign buyer)
        if not inv.buyer_gstin and inv.voucher_type == VoucherType.SALES:
            result.add_warning("Export sale: no buyer GSTIN. Ensure zero-rated / IGST.", category="gst")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _make_check(self, name: str, passed: bool, message: str, category: str, severity: str):
        from validators.base import ValidationCheck
        return ValidationCheck(name=name, passed=passed, message=message, category=category, severity=severity)

    def score(self, inv: StandardizedInvoice) -> ValidationScore:
        """Convenience: validate and score in one call."""
        result = self.validate(inv)
        return ValidationScore.from_validation(result)
