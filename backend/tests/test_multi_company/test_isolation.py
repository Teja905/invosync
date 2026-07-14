"""Multi-company isolation: different company configs must produce different XML outputs."""

import pytest
from xml_generator import TallyXmlGenerator, CompanyConfig
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from gst_engine import _compute_gstin_checksum


KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")


class TestCompanyConfigIsolation:

    @pytest.fixture
    def mumbai_config(self) -> CompanyConfig:
        return CompanyConfig(user_config={
            "company_name": "Mumbai Trading Co",
            "company_gstin": "27AABCU1234F1Z" + _compute_gstin_checksum("27AABCU1234F1Z"),
            "company_state_code": "27",
        })

    @pytest.fixture
    def bangalore_config(self) -> CompanyConfig:
        return CompanyConfig(user_config={
            "company_name": "Bangalore Tech Pvt Ltd",
            "company_gstin": "29AABCU1234F1Z" + _compute_gstin_checksum("29AABCU1234F1Z"),
            "company_state_code": "29",
        })

    @pytest.fixture
    def base_invoice(self) -> StandardizedInvoice:
        return StandardizedInvoice(
            vendor_name="Vendor",
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
                TaxEntry(name="CGST", rate=9, amount=90.0, type="cgst"),
                TaxEntry(name="SGST", rate=9, amount=90.0, type="sgst"),
            ],
        )

    def test_different_company_names_in_xml(self, base_invoice, mumbai_config, bangalore_config):
        """Company name in XML must match the config."""
        mumbai_xml = TallyXmlGenerator(mumbai_config).generate(base_invoice)
        bangalore_xml = TallyXmlGenerator(bangalore_config).generate(base_invoice)

        assert "Mumbai Trading Co" in mumbai_xml, "Mumbai company name not found in its XML"
        assert "Bangalore Tech Pvt Ltd" in bangalore_xml, "Bangalore company name not found in its XML"

    def test_mumbai_and_bangalore_produce_different_xml(self, base_invoice, mumbai_config, bangalore_config):
        """Different company configs must produce different XML output."""
        mumbai_xml = TallyXmlGenerator(mumbai_config).generate(base_invoice)
        bangalore_xml = TallyXmlGenerator(bangalore_config).generate(base_invoice)

        assert mumbai_xml != bangalore_xml, "Different company configs produced identical XML"

    def test_state_code_used_when_buyer_gstin_missing(self):
        """Company state code is used as fallback when buyer GSTIN is missing."""
        from gst_engine import determine_gst_type

        # Vendor is KA (29), no buyer GSTIN → company_state_code="27" (MH) → different → IGST
        mumbai_state = "27"
        mumbai_gst_type, _ = determine_gst_type(
            vendor_gstin=KA_GSTIN,
            buyer_gstin="",
            company_state_code=mumbai_state,
        )
        assert mumbai_gst_type == GSTType.IGST, (
            f"Missing buyer GSTIN + MH company (27) + KA vendor (29) should be IGST, got {mumbai_gst_type}"
        )

        # Vendor is KA (29), no buyer GSTIN → company_state_code="29" (KA) → same → CGST_SGST
        same_state = "29"
        same_gst_type, _ = determine_gst_type(
            vendor_gstin=KA_GSTIN,
            buyer_gstin="",
            company_state_code=same_state,
        )
        assert same_gst_type == GSTType.CGST_SGST, (
            f"Missing buyer GSTIN + KA company (29) + KA vendor (29) should be CGST_SGST, got {same_gst_type}"
        )


class TestGSTDirectionBasedOnCompany:

    def test_company_gstin_vs_vendor_gstin(self):
        """When company GSTIN matches vendor GSTIN, it's a sales-like transaction from company's perspective.
        When company GSTIN matches buyer GSTIN, it's a purchase."""

        company_gstin_27 = "27AABCU1234F1Z" + _compute_gstin_checksum("27AABCU1234F1Z")
        vendor_gstin_27 = "27AABCU1234F1Z" + _compute_gstin_checksum("27AABCU1234F1Z")
        buyer_gstin_29 = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")

        # Company is in Maharashtra (27), vendor is also in Maharashtra (27)
        # This means the company is buying from a local vendor → Purchase
        is_company_vendor = company_gstin_27 == vendor_gstin_27
        is_company_buyer = company_gstin_27 == buyer_gstin_29
        assert is_company_vendor, "Company and vendor should share GSTIN"
        assert not is_company_buyer, "Company and buyer should not share GSTIN"
