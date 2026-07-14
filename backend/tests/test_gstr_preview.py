"""Tests for gstr_preview.py."""

import pytest
from schemas import StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry
from gstr_preview import GSTRPreviewGenerator, generate_gstr_preview


_MH_GSTIN = "27AABCU1234F1ZP"
_KA_GSTIN = "29AACCT3705E1ZM"


def _make_invoice(**overrides):
    data = dict(
        invoice_number="INV-001",
        invoice_date="2026-06-15",
        vendor_name="ABC Suppliers",
        vendor_gstin=_MH_GSTIN,
        buyer_name="XYZ Ltd",
        buyer_gstin=_KA_GSTIN,
        place_of_supply="29",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.IGST,
        is_service=False,
        is_rcm=False,
        is_sez=False,
        is_lut=False,
        is_interstate=True,
        total_taxable_value=100000.0,
        total_tax=18000.0,
        total_amount=118000.0,
        cess_amount=0.0,
        line_items=[
            LineItem(description="Laptop", quantity=1, rate=100000.0, taxable_value=100000.0,
                     tax_rate=18, hsn_sac="847130", unit="Nos", is_service=False),
        ],
        taxes=[
            TaxEntry(name="IGST", rate=18.0, amount=18000.0, type="igst"),
        ],
    )
    data.update(overrides)
    return StandardizedInvoice(**data)


class TestGSTR1SectionDetection:
    def test_b2b_with_both_gstins(self):
        inv = _make_invoice(buyer_gstin=_KA_GSTIN, vendor_gstin=_MH_GSTIN)
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr1_entries[0].section == "B2B"

    def test_b2c_without_buyer_gstin(self):
        inv = _make_invoice(buyer_gstin="")
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr1_entries[0].section == "B2C"

    def test_export_with_sez_buyer(self):
        inv = _make_invoice(buyer_gstin="96AACCT3705E1ZM", is_sez=True)
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr1_entries[0].section == "Export"

    def test_rcm_section(self):
        inv = _make_invoice(is_rcm=True)
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr1_entries[0].section == "RCM"

    def test_debit_note_is_rcm_section(self):
        inv = _make_invoice(voucher_type=VoucherType.DEBIT_NOTE)
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr1_entries[0].section == "RCM"


class TestGSTR3BTotals:
    def test_purchase_totals_are_input(self):
        inv = _make_invoice(
            voucher_type=VoucherType.PURCHASE,
            taxes=[TaxEntry(name="IGST", rate=18.0, amount=18000.0, type="igst")],
        )
        preview = GSTRPreviewGenerator(inv).generate()
        g3 = preview.gstr3b
        assert g3.output_igst == 18000.0
        assert g3.input_igst == 18000.0

    def test_sales_totals_are_output_only(self):
        inv = _make_invoice(
            voucher_type=VoucherType.SALES,
            taxes=[TaxEntry(name="IGST", rate=18.0, amount=18000.0, type="igst")],
        )
        preview = GSTRPreviewGenerator(inv).generate()
        g3 = preview.gstr3b
        assert g3.output_igst == 18000.0
        assert g3.input_igst == 0.0

    def test_cgst_sgst_split(self):
        inv = _make_invoice(
            gst_type=GSTType.CGST_SGST,
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=9000.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=9000.0, type="sgst"),
            ],
        )
        preview = GSTRPreviewGenerator(inv).generate()
        g3 = preview.gstr3b
        assert g3.output_cgst == 9000.0
        assert g3.output_sgst == 9000.0
        assert g3.output_igst == 0.0

    def test_cess_added(self):
        inv = _make_invoice(cess_amount=500.0)
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr3b.cess == 500.0

    def test_rcm_liable(self):
        inv = _make_invoice(is_rcm=True, total_tax=18000.0)
        preview = GSTRPreviewGenerator(inv).generate()
        assert preview.gstr3b.rcm_liable == 18000.0


class TestWarnings:
    def test_b2c_warning(self):
        inv = _make_invoice(buyer_gstin="", gst_type=GSTType.IGST)
        preview = GSTRPreviewGenerator(inv).generate()
        assert any("B2C" in w for w in preview.warnings)

    def test_interstate_cgst_warning(self):
        inv = _make_invoice(is_interstate=True, gst_type=GSTType.CGST_SGST)
        preview = GSTRPreviewGenerator(inv).generate()
        assert any("Interstate" in w for w in preview.warnings)

    def test_export_place_warning(self):
        inv = _make_invoice(place_of_supply="96")
        preview = GSTRPreviewGenerator(inv).generate()
        assert any("Foreign" in w or "export" in w.lower() for w in preview.warnings)


class TestGSTR1Summary:
    def test_summary_counts(self):
        inv = _make_invoice(buyer_gstin=_KA_GSTIN)
        preview = GSTRPreviewGenerator(inv).generate()
        summary = preview.to_dict()["gstr1"]["summary"]
        assert summary["b2b_count"] == 1
        assert summary["b2c_count"] == 0

    def test_convenience_function(self):
        inv = _make_invoice()
        result = generate_gstr_preview(inv)
        assert "gstr1" in result
        assert "gstr3b" in result
        assert result["invoice_count"] == 1
