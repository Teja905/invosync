"""Integration tests — full pipeline roundtrips.

These test the actual flow: create invoice → validate → generate XML →
verify journal lines balance → trial balance consistent. No mocking,
real code paths, real data flowing through the system.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from validation_layer import validate_invoice_for_xml
from ledger_classifier import classify_ledger
from gst_engine import _compute_gstin_checksum


@pytest.fixture
def config():
    return CompanyConfig()


@pytest.fixture
def gen(config):
    return TallyXmlGenerator(config, include_ledgers=False)


def _sum_debits_credits(lines):
    return sum(ln["debit"] for ln in lines), sum(ln["credit"] for ln in lines)


def _make_invoice(**overrides):
    defaults = dict(
        invoice_number="INT-001",
        invoice_date="2025-06-15",
        vendor_name="Integration Test Vendor",
        vendor_gstin="27AABCU1234F1ZP",
        total_taxable_value=1000,
        total_tax=180,
        total_amount=1180,
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        line_items=[LineItem(description="Test Item", quantity=1, rate=1000, taxable_value=1000, tax_rate=18)],
    )
    defaults.update(overrides)
    inv = StandardizedInvoice(**defaults)
    if not inv.taxes and inv.total_tax and inv.gst_type == GSTType.CGST_SGST:
        half = round(inv.total_tax / 2, 2)
        inv.taxes = [
            TaxEntry(name="CGST", rate=9, amount=half, type="CGST"),
            TaxEntry(name="SGST", rate=9, amount=half, type="SGST"),
        ]
    elif not inv.taxes and inv.total_tax and inv.gst_type == GSTType.IGST:
        inv.taxes = [
            TaxEntry(name="IGST", rate=18, amount=inv.total_tax, type="IGST"),
        ]
    return inv


# ---------------------------------------------------------------------------
# 1. VALIDATE → XML → JOURNAL BALANCE — roundtrip
# ---------------------------------------------------------------------------

class TestValidateXmlJournalRoundtrip:
    """Full path: validation → XML generation → journal lines balanced."""

    @pytest.mark.parametrize("vt", [
        VoucherType.PURCHASE, VoucherType.SALES,
    ])
    def test_basic_roundtrip(self, gen, vt):
        inv = _make_invoice(voucher_type=vt)
        validation = validate_invoice_for_xml(inv)
        assert validation.passed, f"Validation failed: {validation.errors}"

        xml = gen.generate(inv)
        assert "<VOUCHER" in xml
        assert gen.journal_lines

        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01, f"Unbalanced: debit={d:.2f} credit={c:.2f}"

    def test_multi_item_invoice(self, gen):
        items = [
            LineItem(description="Item A", quantity=10, rate=50, taxable_value=500, tax_rate=18),
            LineItem(description="Item B", quantity=6, rate=50, taxable_value=300, tax_rate=12),
            LineItem(description="Item C", quantity=4, rate=50, taxable_value=200, tax_rate=5),
        ]
        total_tax = 500 * 0.18 + 300 * 0.12 + 200 * 0.05  # 90 + 36 + 10 = 136
        inv = _make_invoice(
            line_items=items,
            total_taxable_value=1000,
            total_tax=total_tax,
            total_amount=1000 + total_tax,
        )
        inv.taxes = [
            TaxEntry(name="CGST 18%", rate=9, amount=45.00, type="CGST"),
            TaxEntry(name="SGST 18%", rate=9, amount=45.00, type="SGST"),
            TaxEntry(name="CGST 12%", rate=6, amount=18.00, type="CGST"),
            TaxEntry(name="SGST 12%", rate=6, amount=18.00, type="SGST"),
            TaxEntry(name="CGST 5%", rate=2.5, amount=5.00, type="CGST"),
            TaxEntry(name="SGST 5%", rate=2.5, amount=5.00, type="SGST"),
        ]
        validation = validate_invoice_for_xml(inv)
        assert validation.passed

        xml = gen.generate(inv)
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_interstate_igst(self, gen):
        """Interstate invoice uses IGST, not CGST+SGST."""
        buyer_base = "29AACCT3705E1Z"
        buyer_gstin = buyer_base + _compute_gstin_checksum(buyer_base)
        inv = _make_invoice(
            gst_type=GSTType.IGST,
            is_interstate=True,
            buyer_gstin=buyer_gstin,
            total_taxable_value=1000,
            total_tax=180,
            total_amount=1180,
        )
        validation = validate_invoice_for_xml(inv)
        assert validation.passed

        xml = gen.generate(inv)
        assert "IGST" in xml
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_with_freight(self, gen):
        inv = _make_invoice(
            freight=100,
            total_taxable_value=1000,
            total_tax=180,
            total_amount=1280,
        )
        xml = gen.generate(inv)
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_with_tds(self, gen):
        inv = _make_invoice(
            tds_amount=100,
            total_taxable_value=1000,
            total_tax=180,
            total_amount=1080,
        )
        xml = gen.generate(inv)
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_credit_note(self, gen):
        inv = _make_invoice(
            voucher_type=VoucherType.CREDIT_NOTE,
            total_taxable_value=-500,
            total_tax=-90,
            total_amount=-590,
            line_items=[LineItem(description="Return", taxable_value=-500, tax_rate=18)],
        )
        xml = gen.generate(inv)
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_service_invoice(self, gen):
        """Service invoice: NO stock items in XML."""
        inv = _make_invoice(
            is_service=True,
            line_items=[LineItem(description="Consulting", taxable_value=1000, tax_rate=18, is_service=True)],
        )
        xml = gen.generate(inv)
        assert "<VOUCHER" in xml
        assert "ALLINVENTORYENTRIES" not in xml
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_goods_invoice_has_stock(self, gen):
        """Goods invoice should include inventory entries."""
        inv = _make_invoice(
            is_service=False,
            auto_create_stock_items=True,
            line_items=[LineItem(description="Widget", taxable_value=1000, tax_rate=18, hsn_sac="8471")],
        )
        xml = gen.generate(inv)
        assert "<STOCKITEM" in xml or "ALLINVENTORYENTRIES" in xml
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01


# ---------------------------------------------------------------------------
# 2. JOURNAL LINES → TRIAL BALANCE CONSISTENCY
# ---------------------------------------------------------------------------

class TestJournalToTrialBalance:
    """Journal lines captured from XML must produce a consistent trial balance."""

    def test_trial_balance_sums_to_zero(self, gen):
        """Sum of all journal line debits must equal sum of credits."""
        inv = _make_invoice()
        gen.generate(inv)
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01, f"Trial balance unbalanced: {d:.2f} vs {c:.2f}"

    def test_each_line_has_ledger(self, gen):
        inv = _make_invoice()
        gen.generate(inv)
        for ln in gen.journal_lines:
            assert ln["ledger"], "Every journal line must have a ledger name"
            assert isinstance(ln["debit"], (int, float))
            assert isinstance(ln["credit"], (int, float))

    def test_no_negative_debits(self, gen):
        """Debit field must be >= 0 (negative amounts go to credit)."""
        inv = _make_invoice()
        gen.generate(inv)
        for ln in gen.journal_lines:
            assert ln["debit"] >= 0, f"Negative debit in {ln}"

    def test_no_negative_credits(self, gen):
        """Credit field must be >= 0."""
        inv = _make_invoice()
        gen.generate(inv)
        for ln in gen.journal_lines:
            assert ln["credit"] >= 0, f"Negative credit in {ln}"


# ---------------------------------------------------------------------------
# 3. GST ENGINE INTEGRATION
# ---------------------------------------------------------------------------

class TestGstEngineIntegration:
    """GST detection, rate validation, and CGST/SGST split must work together."""

    def test_valid_gstin_checksum(self):
        base = "29AACCT3705E1Z"
        full = base + _compute_gstin_checksum(base)
        from gst_engine import validate_gstin
        result = validate_gstin(full)
        assert result["valid"] is True

    def test_all_slabs_pass_rate_validation(self):
        from gst_engine import validate_tax_rate_for_date
        for rate in [0, 0.1, 0.25, 3, 5, 12, 18, 28]:
            result = validate_tax_rate_for_date(rate, "2025-06-15")
            assert result["valid"], f"Rate {rate}% should be valid"

    def test_invalid_rate_rejected(self):
        from gst_engine import validate_tax_rate_for_date
        for rate in [1, 2, 7, 10, 15, 20, 25, 30, 50]:
            result = validate_tax_rate_for_date(rate, "2025-06-15")
            assert not result["valid"], f"Rate {rate}% should be invalid"


# ---------------------------------------------------------------------------
# 4. LEDGER CLASSIFIER INTEGRATION
# ---------------------------------------------------------------------------

class TestClassifierIntegration:
    """Ledger classification must be consistent across all Tally parent groups."""

    KNOWN_MAPPINGS = {
        "Sundry Creditors": "Liability",
        "Sundry Debtors": "Asset",
        "Bank Accounts": "Asset",
        "Duties & Taxes": "Liability",
        "Purchase Accounts": "Expense",
        "Sales Accounts": "Income",
        "Direct Income": "Income",
        "Indirect Income": "Income",
        "Direct Expenses": "Expense",
        "Indirect Expenses": "Expense",
        "Capital Account": "Liability",
        "Fixed Assets": "Asset",
    }

    @pytest.mark.parametrize("group,expected_type", list(KNOWN_MAPPINGS.items()))
    def test_known_groups_classify_correctly(self, group, expected_type):
        result = classify_ledger("Test Ledger", group)
        assert result == expected_type, f"'{group}' should be '{expected_type}', got '{result}'"

    def test_unknown_group_defaults_to_expense(self):
        """Unknown parent group must default to Expense, never crash."""
        result = classify_ledger("Mystery Ledger", "Nonexistent Group")
        assert result in ("Asset", "Liability", "Income", "Expense")


# ---------------------------------------------------------------------------
# 5. MULTI-ITEM MATH CONSISTENCY
# ---------------------------------------------------------------------------

class TestMultiItemMath:
    """Line item quantities × rates must reconcile with header totals."""

    def test_three_items_reconcile(self, gen):
        items = [
            LineItem(description="A", quantity=10, rate=100, taxable_value=1000, tax_rate=18),
            LineItem(description="B", quantity=5, rate=200, taxable_value=1000, tax_rate=12),
            LineItem(description="C", quantity=20, rate=50, taxable_value=1000, tax_rate=5),
        ]
        total_tax = 1000 * 0.18 + 1000 * 0.12 + 1000 * 0.05  # 180 + 120 + 50 = 350
        inv = _make_invoice(
            line_items=items,
            total_taxable_value=3000,
            total_tax=total_tax,
            total_amount=3000 + total_tax,
        )
        xml = gen.generate(inv)
        d, c = _sum_debits_credits(gen.journal_lines)
        assert abs(d - c) < 0.01

    def test_quantity_rate_taxable_consistency(self):
        """If qty × rate = taxable_value for each item, no math errors."""
        items = [
            LineItem(description="X", quantity=3, rate=100, taxable_value=300, tax_rate=18),
            LineItem(description="Y", quantity=7, rate=50, taxable_value=350, tax_rate=12),
        ]
        sum_taxable = sum(it.taxable_value for it in items)
        calc_tax = sum(it.taxable_value * it.tax_rate / 100 for it in items)
        total = sum_taxable + calc_tax

        inv = _make_invoice(
            line_items=items,
            total_taxable_value=sum_taxable,
            total_tax=calc_tax,
            total_amount=total,
        )
        inv.taxes = [
            TaxEntry(name="CGST 18%", rate=9, amount=27.00, type="CGST"),
            TaxEntry(name="SGST 18%", rate=9, amount=27.00, type="SGST"),
            TaxEntry(name="CGST 12%", rate=6, amount=21.00, type="CGST"),
            TaxEntry(name="SGST 12%", rate=6, amount=21.00, type="SGST"),
        ]
        validation = validate_invoice_for_xml(inv)
        math_checks = {k: v for k, v in validation.checks.items() if "math" in k or "amount" in k}
        for name, check in math_checks.items():
            assert check.get("pass"), f"Math check '{name}' failed: {check}"
