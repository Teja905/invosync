"""Validation rules: tax computation correctness — CGST/SGST split, IGST, rate slabs."""

from validation_layer import validate_invoice_for_xml
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from gst_engine import validate_tax_rate, ALLOWED_GST_SLABS, compute_gst_entries


class TestTaxRateValidation:
    def test_all_statutory_slabs_accepted(self):
        """Each allowed GST slab should pass rate validation."""
        for rate in ALLOWED_GST_SLABS:
            result = validate_tax_rate(rate)
            assert result["valid"] is True, f"Slab {rate}% should be valid"

    def test_non_statutory_slabs_rejected(self):
        """Rates not in {0, 0.1, 0.25, 3, 5, 12, 18, 28} must be rejected."""
        for rate in [1, 2, 4, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 19, 20, 21, 22, 24, 25, 26, 27, 29, 30]:
            result = validate_tax_rate(rate)
            assert result["valid"] is False, f"Rate {rate}% should be invalid"

    def test_near_slab_rounded(self):
        """Rates within 0.5% of a slab should get corrected."""
        result = validate_tax_rate(17.5)
        assert result.get("corrected_rate") == 18, f"Expected corrected to 18, got {result}"


class TestTaxComputationInInvoices:
    def test_cgst_sgst_split_correct(self):
        """CGST+SGST must equal half the total tax rate each."""
        inv = StandardizedInvoice(
            vendor_name="Test Vendor",
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18, quantity=1, rate=1000)],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=90.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=90.0, type="SGST"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        tax_errors = [e for e in result.errors if "tax" in e.lower()]
        assert not tax_errors, f"Tax errors on correct CGST/SGST split: {tax_errors}"

    def test_cgst_sgst_mismatch_flagged(self):
        """If CGST != SGST, validation should flag it."""
        inv = StandardizedInvoice(
            vendor_name="Test Vendor",
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18)],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=100.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=80.0, type="SGST"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        tax_errors = [e for e in (result.errors + result.warnings) if "cgst" in e.lower() or "sgst" in e.lower()]
        assert tax_errors, f"Expected CGST/SGST mismatch flagged: {result.errors}"

    def test_tax_total_matches_line_items(self):
        """Sum of taxable values across items must match header total_taxable_value."""
        inv = StandardizedInvoice(
            vendor_name="Test Vendor",
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[
                LineItem(description="Item A", taxable_value=600.0, tax_rate=18),
                LineItem(description="Item B", taxable_value=400.0, tax_rate=18),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=90.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=90.0, type="SGST"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        amount_errors = [e for e in result.errors if "amount" in e.lower() or "total" in e.lower()]
        assert not amount_errors, f"Unexpected amount errors: {amount_errors}"

    def test_compute_gst_entries_igst(self):
        """Interstate GST: compute_gst_entries should return IGST not CGST/SGST."""
        entries = compute_gst_entries(
            taxable_value=1000.0,
            tax_rate=18,
            gst_type=GSTType.IGST,
            is_rcm=False,
        )
        assert any("igst" in str(k).lower() for k in entries), f"Expected IGST entries, got {entries}"
        assert not any("cgst" in str(k).lower() for k in entries), f"Should not have CGST, got {entries}"

    def test_invalid_tax_rate_fails_check(self):
        """An invoice with an invalid (non-slotted) GST rate must fail the tax_rates validation check."""
        inv = StandardizedInvoice(
            vendor_name="Test Vendor",
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=1170.0,
            total_amount=2170.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[
                LineItem(description="Item A", taxable_value=1000.0, tax_rate=117),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=58.5, amount=585.0, type="CGST"),
                TaxEntry(name="SGST", rate=58.5, amount=585.0, type="SGST"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        tr = result.checks.get("tax_rates", {})
        assert tr.get("pass") is False, (
            f"Expected tax_rates check to fail for 117% rate, got: {tr}"
        )
