"""Validation rules: place of supply, interstate vs intrastate routing."""

import pytest
from validation_layer import validate_invoice_for_xml
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from gst_engine import determine_gst_type, _extract_state_code, _compute_gstin_checksum


KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
MH_GSTIN = "27AAFFC8126N1Z" + _compute_gstin_checksum("27AAFFC8126N1Z")
TN_GSTIN = "33ABCDE1234F1Z" + _compute_gstin_checksum("33ABCDE1234F1Z")


class TestDetermineGstType:
    def test_same_state_cgst_sgst(self):
        """Same-state buyer and vendor => CGST_SGST."""
        gst_type, is_sez = determine_gst_type(KA_GSTIN, KA_GSTIN)
        assert gst_type == GSTType.CGST_SGST, f"Expected CGST_SGST, got {gst_type}"

    def test_different_state_igst(self):
        """Different-state buyer and vendor => IGST."""
        gst_type, _ = determine_gst_type(KA_GSTIN, MH_GSTIN)
        assert gst_type == GSTType.IGST, f"Expected IGST, got {gst_type}"

    def test_kerala_to_tamilnadu_igst(self):
        """Kerala(32) to Tamil Nadu(33) => IGST."""
        kl = "32ABCDE1234F1Z" + _compute_gstin_checksum("32ABCDE1234F1Z")
        tn = "33ABCDE1234F1Z" + _compute_gstin_checksum("33ABCDE1234F1Z")
        gst_type, _ = determine_gst_type(kl, tn)
        assert gst_type == GSTType.IGST

    def test_sez_forces_igst(self):
        """SEZ transaction => IGST regardless of same state."""
        gst_type, is_sez = determine_gst_type(KA_GSTIN, KA_GSTIN, is_sez=True)
        assert gst_type == GSTType.IGST, f"SEZ should force IGST, got {gst_type}"
        assert is_sez is True

    def test_lut_means_exempt(self):
        """LUT-covered transactions => EXEMPT."""
        gst_type, _ = determine_gst_type(KA_GSTIN, KA_GSTIN, is_lut=True)
        assert gst_type == GSTType.EXEMPT

    def test_missing_buyer_gstin_defaults_company_state(self):
        """Missing buyer GSTIN defaults to company state code (27/MH).
        Use a vendor with state 27 (same as company default) to get CGST_SGST."""
        mh_vendor = "27ABCDE1234F1Z" + _compute_gstin_checksum("27ABCDE1234F1Z")
        gst_type, _ = determine_gst_type(mh_vendor, "")
        assert gst_type == GSTType.CGST_SGST, f"Same state as company default should be CGST_SGST, got {gst_type}"

    def test_extract_state_code(self):
        """State code extraction from valid GSTIN."""
        code = _extract_state_code(KA_GSTIN)
        assert code == "29"


class TestPlaceOfSupplyInValidation:
    def test_interstate_marked_as_igst_passes(self):
        """Interstate invoice marked IGST should pass validation."""
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
        result = validate_invoice_for_xml(inv)
        routing_errors = [e for e in result.errors if "interstate" in e.lower() or "igst" in e.lower() or "routing" in e.lower()]
        assert not routing_errors, f"Unexpected routing errors: {routing_errors}"

    def test_interstate_wrongly_marked_cgst_sgst_fails(self):
        """Interstate invoice wrongly marked CGST_SGST should be flagged."""
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
            gst_type=GSTType.CGST_SGST,  # wrong — should be IGST
            line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18, quantity=1, rate=1000)],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=90.0, type="cgst"),
                TaxEntry(name="SGST", rate=9, amount=90.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        routing_errors = [e for e in result.errors if "interstate" in e.lower() or "igst" in e.lower() or "cgst/sgst" in e.lower()]
        assert routing_errors, f"Expected interstate routing error, got errors={result.errors}"
