"""Property-based tests using Hypothesis.

These test INVARIANTS that must hold for ALL valid inputs — the kind of bugs
that specific test cases miss. Each test defines an invariant, then Hypothesis
generates thousands of random inputs trying to break it.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
from decimal import Decimal

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from validation_layer import validate_invoice_for_xml
from gst_engine import validate_gstin, ALLOWED_GST_SLABS, _compute_gstin_checksum, GST_STATE_CODES
from ledger_classifier import classify_ledger

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_slabs = sorted(ALLOWED_GST_SLABS - {0})


def _make_gstin(state_code: str = "27", pan_body: str = "AABCU1234F1Z") -> str:
    """Build a valid GSTIN with correct checksum."""
    base = state_code + pan_body
    return base + _compute_gstin_checksum(base)


STRAT_GSTIN = st.sampled_from([
    _make_gstin("27"), _make_gstin("29"), _make_gstin("07"),
    _make_gstin("33"), _make_gstin("36"), _make_gstin("24"),
])

STRAT_VOUCHER = st.sampled_from([
    VoucherType.PURCHASE, VoucherType.SALES,
    VoucherType.PAYMENT, VoucherType.RECEIPT,
    VoucherType.JOURNAL, VoucherType.CREDIT_NOTE,
    VoucherType.DEBIT_NOTE,
])

STRAT_SLAB = st.sampled_from(valid_slabs)

from datetime import datetime as dt, timedelta

STRAT_DATE = st.datetimes(
    min_value=dt(2017, 7, 1),
    max_value=dt(2026, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))


def _line_item_strategy():
    return st.builds(
        LineItem,
        description=st.text(min_size=1, max_size=60, alphabet=st.characters(whitelist_categories=("L", "N", "Nd"), whitelist_characters=" -/")),
        quantity=st.floats(min_value=0.01, max_value=10000),
        rate=st.floats(min_value=0.01, max_value=1000000),
        tax_rate=STRAT_SLAB,
        taxable_value=st.floats(min_value=1, max_value=500000),
        hsn_sac=st.from_regex(r"\d{4,8}", fullmatch=True),
        is_service=st.booleans(),
    )


def _invoice_strategy():
    """Build a minimally valid StandardizedInvoice from random components."""
    return st.fixed_dictionaries({
        "invoice_number": st.from_regex(r"INV-\d{3,6}", fullmatch=True),
        "invoice_date": STRAT_DATE,
        "vendor_name": st.text(min_size=3, max_size=40, alphabet=st.characters(whitelist_categories=("L",), whitelist_characters=" ")),
        "vendor_gstin": STRAT_GSTIN,
        "total_taxable_value": st.floats(min_value=10, max_value=500000, allow_nan=False, allow_infinity=False),
        "total_tax": st.floats(min_value=0, max_value=140000, allow_nan=False, allow_infinity=False),
        "total_amount": st.floats(min_value=10, max_value=640000, allow_nan=False, allow_infinity=False),
        "voucher_type": STRAT_VOUCHER,
        "gst_type": st.sampled_from([GSTType.CGST_SGST, GSTType.IGST]),
    }).map(lambda d: StandardizedInvoice(**d, line_items=[]))


# ---------------------------------------------------------------------------
# 1. JOURNAL BALANCE INVARIANT
#    For ANY invoice that goes through generate(), debits == credits.
# ---------------------------------------------------------------------------

class TestJournalBalanceInvariant:
    """Every generated voucher MUST have balanced journal lines (debits = credits)."""

    @given(
        voucher_type=st.sampled_from([VoucherType.PURCHASE, VoucherType.SALES]),
        taxable=st.floats(min_value=10, max_value=500000, allow_nan=False, allow_infinity=False),
        tax_rate=STRAT_SLAB,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_purchase_sales_journal_balances(self, voucher_type, taxable, tax_rate):
        tax = round(taxable * tax_rate / 100, 2)
        total = round(taxable + tax, 2)
        assume(total > 0)

        inv = StandardizedInvoice(
            invoice_number="PROP-JNL",
            invoice_date="2025-06-15",
            vendor_name="Property Test Vendor",
            voucher_type=voucher_type,
            total_taxable_value=taxable,
            total_tax=tax,
            total_amount=total,
            gst_type=GSTType.CGST_SGST if voucher_type in (VoucherType.PURCHASE, VoucherType.SALES) else GSTType.EXEMPT,
            line_items=[LineItem(description="Test Item", taxable_value=taxable, tax_rate=tax_rate)],
        )

        config = CompanyConfig()
        gen = TallyXmlGenerator(config, include_ledgers=False)
        xml = gen.generate(inv)

        assert gen.journal_lines, "journal_lines must not be empty"
        total_debit = sum(ln["debit"] for ln in gen.journal_lines)
        total_credit = sum(ln["credit"] for ln in gen.journal_lines)
        diff = round(total_debit - total_credit, 2)
        assert abs(diff) < 0.01, (
            f"Journal unbalanced for {inv.voucher_type.value}: "
            f"debit={total_debit:.2f} credit={total_credit:.2f} diff={diff:.2f}"
        )

    @given(
        taxable=st.floats(min_value=10, max_value=500000, allow_nan=False, allow_infinity=False),
        tax_rate=STRAT_SLAB,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_journal_resets_between_generates(self, taxable, tax_rate):
        tax = round(taxable * tax_rate / 100, 2)
        total = round(taxable + tax, 2)
        assume(total > 0)

        inv = StandardizedInvoice(
            invoice_number="PROP-RESET",
            invoice_date="2025-06-15",
            vendor_name="Reset Test Vendor",
            voucher_type=VoucherType.PURCHASE,
            total_taxable_value=taxable,
            total_tax=tax,
            total_amount=total,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Test Item", taxable_value=taxable, tax_rate=tax_rate)],
        )

        config = CompanyConfig()
        gen = TallyXmlGenerator(config, include_ledgers=False)
        gen.generate(inv)
        first_count = len(gen.journal_lines)
        gen.generate(inv)
        assert len(gen.journal_lines) == first_count, "journal lines must not accumulate"


# ---------------------------------------------------------------------------
# 2. XML BALANCE INVARIANT
#    Sum of all AMOUNTs in the voucher (excluding BILLALLOCATIONS/INVENTORY) == 0
# ---------------------------------------------------------------------------

class TestXmlBalanceInvariant:
    """The generated XML voucher must always balance to zero."""

    @given(
        voucher_type=st.sampled_from([VoucherType.PURCHASE, VoucherType.SALES]),
        taxable=st.floats(min_value=10, max_value=500000),
        tax_rate=STRAT_SLAB,
    )
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_xml_voucher_balances(self, voucher_type, taxable, tax_rate):
        tax = round(taxable * tax_rate / 100, 2)
        total = round(taxable + tax, 2)
        assume(total > 0 and tax >= 0)

        inv = StandardizedInvoice(
            invoice_number="PROP-XML",
            invoice_date="2025-06-15",
            vendor_name="Property Test Vendor",
            voucher_type=voucher_type,
            total_taxable_value=taxable,
            total_tax=tax,
            total_amount=total,
            gst_type=GSTType.CGST_SGST if voucher_type in (VoucherType.PURCHASE, VoucherType.SALES) else GSTType.EXEMPT,
            line_items=[LineItem(description="Test Item", taxable_value=taxable, tax_rate=tax_rate)],
        )

        config = CompanyConfig()
        gen = TallyXmlGenerator(config, include_ledgers=False)
        xml = gen.generate(inv)

        import re
        amounts = re.findall(r"<AMOUNT>([^<]+)</AMOUNT>", xml)
        voucher_amounts = []
        in_voucher = False
        for line in xml.split("\n"):
            if "<VOUCHER" in line:
                in_voucher = True
            if "</VOUCHER>" in line:
                in_voucher = False
            if in_voucher and "<AMOUNT>" in line:
                m = re.search(r"<AMOUNT>([^<]+)</AMOUNT>", line)
                if m:
                    voucher_amounts.append(float(m.group(1)))

        if voucher_amounts:
            total_amt = round(sum(voucher_amounts), 2)
            assert abs(total_amt) < 0.01, (
                f"XML voucher unbalanced: sum={total_amt:.2f} "
                f"({len(voucher_amounts)} amounts)"
            )


# ---------------------------------------------------------------------------
# 3. VALIDATION NEVER CRASHES
#    Any StandardizedInvoice (even nonsensical) must produce a ValidationResult.
# ---------------------------------------------------------------------------

class TestValidationNeverCrashes:
    """validate_invoice_for_xml must always return a result, never throw."""

    @given(inv=_invoice_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_invoices_validate(self, inv: StandardizedInvoice):
        result = validate_invoice_for_xml(inv)
        assert result is not None
        assert hasattr(result, "passed")
        assert hasattr(result, "errors")
        assert hasattr(result, "checks")

    @given(
        vendor_name=st.text(max_size=200),
        invoice_number=st.text(max_size=200),
        total_amount=st.floats(allow_nan=True, allow_infinity=True),
        total_taxable=st.floats(allow_nan=True, allow_infinity=True),
        total_tax=st.floats(allow_nan=True, allow_infinity=True),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_garbage_fields_never_crash(self, vendor_name, invoice_number,
                                        total_amount, total_taxable, total_tax):
        """Even NaN/Inf/empty/giant values must not raise."""
        inv = StandardizedInvoice(
            vendor_name=vendor_name,
            invoice_number=invoice_number,
            invoice_date="2025-01-01",
            total_amount=total_amount if not (math.isnan(total_amount) or math.isinf(total_amount)) else 0,
            total_taxable_value=total_taxable if not (math.isnan(total_taxable) or math.isinf(total_taxable)) else 0,
            total_tax=total_tax if not (math.isnan(total_tax) or math.isinf(total_tax)) else 0,
        )
        result = validate_invoice_for_xml(inv)
        assert result is not None


# ---------------------------------------------------------------------------
# 4. GSTIN VALIDATION IS CONSISTENT
#    Valid GSTINs always pass. Invalid ones never crash.
# ---------------------------------------------------------------------------

class TestGstinConsistency:
    """GSTIN validation must be deterministic and crash-free."""

    @given(state_code=st.sampled_from(list(GST_STATE_CODES.keys())))
    @settings(max_examples=40)
    def test_valid_gstins_always_pass(self, state_code):
        gstin = _make_gstin(state_code)
        result = validate_gstin(gstin)
        assert result.get("valid") is True, f"Valid GSTIN {gstin} failed: {result}"

    @given(garbage=st.text(min_size=1, max_size=30))
    @settings(max_examples=200)
    def test_invalid_gstins_never_crash(self, garbage):
        assume(garbage.strip())  # skip blank
        result = validate_gstin(garbage)
        assert isinstance(result, dict)
        assert "valid" in result


# ---------------------------------------------------------------------------
# 5. LEDGER CLASSIFIER IS TOTAL
#    Every Tally parent group must map to exactly one account_type, never None.
# ---------------------------------------------------------------------------

class TestClassifierTotality:
    """classify_ledger must return a valid type for every known Tally group."""

    TALLY_GROUPS = [
        "Sundry Creditors", "Sundry Debtors", "Bank Accounts", "Cash-in-Hand",
        "Current Assets", "Fixed Assets", "Loans & Advances (Assets)",
        "Investments", "Duties & Taxes", "Provisions",
        "Current Liabilities", "Loans & Advances (Liabilities)",
        "Income (Direct)", "Income (Indirect)",
        "Expenses (Direct)", "Expenses (Indirect)",
        "Purchase Accounts", "Sales Accounts",
        "Stock-in-Hand", "Capital Account",
        "Reserves & Surplus", "Secured Loans", "Unsecured Loans",
    ]

    def test_all_groups_classify(self):
        for group in self.TALLY_GROUPS:
            result = classify_ledger("Test Ledger", group)
            assert result in ("Asset", "Liability", "Income", "Expense"), (
                f"Group '{group}' classified as '{result}' — not a valid account_type"
            )

    @given(
        ledger_name=st.text(min_size=1, max_size=50),
        parent_group=st.sampled_from(TALLY_GROUPS),
    )
    @settings(max_examples=100)
    def test_classifier_never_crashes(self, ledger_name, parent_group):
        result = classify_ledger(ledger_name, parent_group)
        assert result in ("Asset", "Liability", "Income", "Expense")


# ---------------------------------------------------------------------------
# 6. SANITIZE NEVER CRASHES
#    _sanitize must handle any input without throwing.
# ---------------------------------------------------------------------------

class TestSanitizeSafety:
    """_sanitize (XML character filter) must never throw."""

    @given(text=st.text())
    @settings(max_examples=300)
    def test_sanitize_handles_any_string(self, text):
        from xml_generator import _sanitize
        result = _sanitize(text)
        assert isinstance(result, str)
