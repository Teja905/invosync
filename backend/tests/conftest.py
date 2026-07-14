"""Shared fixtures for the InvoSync enterprise test suite."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator, CompanyConfig
from gst_engine import _compute_gstin_checksum

# Valid statutorily-correct test GSTINs (computes proper checksum digit)
KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
MH_GSTIN = "27AAFFC8126N1Z" + _compute_gstin_checksum("27AAFFC8126N1Z")


@pytest.fixture
def config() -> CompanyConfig:
    return CompanyConfig()


@pytest.fixture
def generator(config: CompanyConfig) -> TallyXmlGenerator:
    return TallyXmlGenerator(config)


@pytest.fixture
def generator_no_ledgers(config: CompanyConfig) -> TallyXmlGenerator:
    return TallyXmlGenerator(config, include_ledgers=False)


@pytest.fixture
def valid_gstins() -> dict:
    return {"ka": KA_GSTIN, "mh": MH_GSTIN}


@pytest.fixture
def base_invoice(valid_gstins: dict) -> dict:
    return dict(
        vendor_name="Test Vendor",
        vendor_gstin=valid_gstins["ka"],
        buyer_gstin=valid_gstins["ka"],
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        total_taxable_value=1000.0,
        total_tax=180.0,
        total_amount=1180.0,
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
    )


@pytest.fixture
def sample_invoice(base_invoice: dict) -> StandardizedInvoice:
    return StandardizedInvoice(
        **base_invoice,
        line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18)],
        taxes=[
            TaxEntry(name="CGST", rate=9, amount=90.0, type="CGST"),
            TaxEntry(name="SGST", rate=9, amount=90.0, type="SGST"),
        ],
    )
