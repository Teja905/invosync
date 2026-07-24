"""XML generator: GST ledger routing correctness — CGST/SGST vs IGST."""

import re
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from gst_engine import _compute_gstin_checksum


KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
MH_GSTIN = "27AAFFC8126N1Z" + _compute_gstin_checksum("27AAFFC8126N1Z")


def _ledger_names(xml: str) -> list[str]:
    return re.findall(r"<LEDGERNAME>([^<]+)</LEDGERNAME>", xml)


class TestCGSTSGSTRouting:
    """Intra-state purchases must have CGST+SGST ledgers, not IGST."""

    def test_cgst_sgst_ledgers_present(self, generator_no_ledgers):
        inv = StandardizedInvoice(
            vendor_name="KA Vendor",
            vendor_gstin=KA_GSTIN,
            buyer_gstin=KA_GSTIN,
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18)],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=90.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=90.0, type="SGST"),
            ],
        )
        xml = generator_no_ledgers.generate(inv)
        names = _ledger_names(xml)
        cgst = any("cgst" in n.lower() for n in names)
        sgst = any("sgst" in n.lower() for n in names)
        igst = any("igst" in n.lower() for n in names)
        assert cgst, f"CGST ledger missing; ledgers: {names}"
        assert sgst, f"SGST ledger missing; ledgers: {names}"
        assert not igst, f"IGST should not appear in intra-state; ledgers: {names}"

    def test_cgst_sgst_ledger_names_contain_rate(self, generator_no_ledgers):
        """CGST/SGST ledger names should indicate the rate (e.g. 'INPUT CGST 9%')."""
        inv = StandardizedInvoice(
            vendor_name="KA Vendor",
            vendor_gstin=KA_GSTIN,
            buyer_gstin=KA_GSTIN,
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=50.0,
            total_amount=1050.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=5)],
            taxes=[
                TaxEntry(name="CGST", rate=2.5, amount=25.0, type="CGST"),
                TaxEntry(name="SGST", rate=2.5, amount=25.0, type="SGST"),
            ],
        )
        xml = generator_no_ledgers.generate(inv)
        names = _ledger_names(xml)
        cgst_names = [n for n in names if "cgst" in n.lower()]
        sgst_names = [n for n in names if "sgst" in n.lower()]
        for n in cgst_names:
            assert "2.5" in n or "2" in n, f"CGST ledger '{n}' missing rate"
        for n in sgst_names:
            assert "2.5" in n or "2" in n, f"SGST ledger '{n}' missing rate"


class TestIGSTRouting:
    """Inter-state purchases must have IGST ledgers, not CGST/SGST."""

    def test_igst_ledger_present(self, generator_no_ledgers):
        inv = StandardizedInvoice(
            vendor_name="KA Vendor",
            vendor_gstin=KA_GSTIN,
            buyer_gstin=MH_GSTIN,
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.IGST,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18)],
            taxes=[TaxEntry(name="IGST", rate=18, amount=180.0, type="IGST")],
        )
        xml = generator_no_ledgers.generate(inv)
        names = _ledger_names(xml)
        igst = any("igst" in n.lower() for n in names)
        cgst = any("cgst" in n.lower() for n in names)
        sgst = any("sgst" in n.lower() for n in names)
        assert igst, f"IGST ledger missing; ledgers: {names}"
        assert not cgst, f"CGST should not appear in inter-state; ledgers: {names}"
        assert not sgst, f"SGST should not appear in inter-state; ledgers: {names}"

    def test_igst_ledger_name_contains_rate(self, generator_no_ledgers):
        """IGST ledger name should indicate the rate."""
        inv = StandardizedInvoice(
            vendor_name="KA Vendor",
            vendor_gstin=KA_GSTIN,
            buyer_gstin=MH_GSTIN,
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.IGST,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18)],
            taxes=[TaxEntry(name="IGST", rate=18, amount=180.0, type="IGST")],
        )
        xml = generator_no_ledgers.generate(inv)
        names = _ledger_names(xml)
        igst_names = [n for n in names if "igst" in n.lower()]
        for n in igst_names:
            assert "18" in n, f"IGST ledger '{n}' missing rate 18%"


class TestOutputGSTLedgers:
    """Sales vouchers should use OUTPUT GST ledgers, not INPUT."""

    def test_sales_uses_output_ledgers(self, generator_no_ledgers):
        inv = StandardizedInvoice(
            vendor_name="Customer Ltd",
            vendor_gstin=KA_GSTIN,
            buyer_gstin=KA_GSTIN,
            invoice_number="SAL-001",
            invoice_date="2025-01-01",
            total_taxable_value=2000.0,
            total_tax=360.0,
            total_amount=2360.0,
            voucher_type=VoucherType.SALES,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Service", taxable_value=2000.0, tax_rate=18)],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=180.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=180.0, type="SGST"),
            ],
        )
        xml = generator_no_ledgers.generate(inv)
        names = _ledger_names(xml)
        assert any("output" in n.lower() for n in names), f"Output ledger missing; ledgers: {names}"
        assert not any("input" in n.lower() for n in names), f"Input ledger should not appear in sales; ledgers: {names}"


class TestZeroRatedGST:
    """Zero-rated and nil-rated transactions must not generate GST ledgers."""

    def test_zero_rated_has_no_gst_ledgers(self, generator_no_ledgers):
        inv = StandardizedInvoice(
            vendor_name="Exempt Vendor",
            vendor_gstin=KA_GSTIN,
            buyer_gstin=KA_GSTIN,
            invoice_number="INV-001",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=0.0,
            total_amount=1000.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.EXEMPT,
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=0)],
        )
        xml = generator_no_ledgers.generate(inv)
        names = _ledger_names(xml)
        gst_ledgers = [n for n in names if any(t in n.lower() for t in ("cgst", "sgst", "igst", "gst"))]
        assert not gst_ledgers, f"No GST ledgers expected for zero-rated; got: {gst_ledgers}"
