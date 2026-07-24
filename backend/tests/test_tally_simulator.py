"""Test TallySimulator — pre-flight checks that catch Tally import failures."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from gst_engine import _compute_gstin_checksum
from validators.tally_simulator import TallySimulator

_VALID_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")


@pytest.fixture
def config():
    return CompanyConfig(user_config={"company_state_code": "29", "company_name": "Test Co"})


@pytest.fixture
def generator(config):
    return TallyXmlGenerator(config)


@pytest.fixture
def sim():
    return TallySimulator()


@pytest.fixture
def goods_invoice():
    return StandardizedInvoice(
        invoice_number="INV-001",
        invoice_date="2026-06-15",
        vendor_name="Test Supplier",
        vendor_gstin=_VALID_GSTIN,
        buyer_gstin=_VALID_GSTIN,
        place_of_supply="29",
        is_service=False,
        total_taxable_value=1000.0,
        total_tax=180.0,
        total_amount=1180.0,
        line_items=[
            LineItem(description="Widget", quantity=10, rate=100.0, taxable_value=1000.0, hsn_sac="84713000", unit="Nos"),
        ],
        taxes=[
            TaxEntry(name="CGST", rate=9.0, amount=90.0, type="cgst"),
            TaxEntry(name="SGST", rate=9.0, amount=90.0, type="sgst"),
        ],
    )


class TestTallySimulator:

    def test_empty_xml(self, sim):
        r = sim.simulate_import("")
        assert not r.passed
        assert any("empty" in c.message.lower() for c in r.checks if not c.passed)

    def test_no_envelope(self, sim):
        r = sim.simulate_import("<broken/>")
        assert not r.passed

    def test_valid_purchase_xml(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        r = sim.simulate_import(xml_str, expected_vchtype="Purchase")
        if not r.passed:
            errors = [c.message for c in r.checks if not c.passed and c.severity == "error"]
            pytest.fail(f"Tally simulation failed: {errors}")

    def test_vchtype_mismatch(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        r = sim.simulate_import(xml_str, expected_vchtype="Sales")
        assert not r.passed
        assert any("vchtype" in c.message.lower() for c in r.checks if not c.passed)

    def test_missing_declaration(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        xml_str = xml_str.lstrip()
        if xml_str.startswith("<?xml"):
            xml_str = xml_str.split("?>", 1)[-1].strip()
        # Remove declaration
        xml_str = "\n".join(line for line in xml_str.split("\n") if not line.strip().startswith("<?xml"))
        r = sim.simulate_import(xml_str)
        assert any("declaration" in c.message.lower() for c in r.checks if not c.passed)

    def test_all_voucher_types(self, sim, generator):
        for vt in VoucherType:
            inv = StandardizedInvoice(
                invoice_number=f"INV-{vt.name}",
                invoice_date="2026-06-15",
                vendor_name="Test Supplier",
                vendor_gstin=_VALID_GSTIN,
                buyer_gstin=_VALID_GSTIN,
                place_of_supply="29",
                is_service=False,
                total_taxable_value=1000.0,
                total_tax=180.0,
                total_amount=1180.0,
                voucher_type=vt,
                line_items=[LineItem(description="Item", quantity=1, rate=1000.0, taxable_value=1000.0)],
                taxes=[
                    TaxEntry(name="CGST", rate=9.0, amount=90.0, type="cgst"),
                    TaxEntry(name="SGST", rate=9.0, amount=90.0, type="sgst"),
                ],
            )
            xml_str = generator.generate(inv)
            r = sim.simulate_import(xml_str, expected_vchtype=vt.value)
            if not r.passed:
                errors = [c.message for c in r.checks if not c.passed and c.severity == "error"]
                if errors:
                    pytest.fail(f"{vt.value}: {errors}")

    def test_ledger_master_creation(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        r = sim.simulate_import(xml_str)
        # All referenced ledgers should have masters
        ledger_errors = [c for c in r.checks if "ledger_refs" in (c.name or "") and not c.passed]
        assert len(ledger_errors) == 0, f"Missing ledger masters: {ledger_errors}"

    def test_company_name_present(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        r = sim.simulate_import(xml_str)
        assert any("SVCURRENTCOMPANY" in c.message or "company" in c.message.lower()
                    for c in r.checks if c.passed)

    def test_balance_check(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        r = sim.simulate_import(xml_str)
        balance_ok = any("balanced" in c.message.lower() and c.passed for c in r.checks)
        assert balance_ok, "Voucher not balanced according to Tally simulator"

    def test_date_format(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        r = sim.simulate_import(xml_str)
        date_ok = any("date" in c.message.lower() and c.passed for c in r.checks if c.severity == "info")
        assert date_ok, "Date format issue"

    def test_score(self, sim, generator, goods_invoice):
        xml_str = generator.generate(goods_invoice)
        score = sim.score(xml_str, "Purchase")
        assert 0 <= score.score <= 100
        assert isinstance(score.passed, bool)

    def test_imbalanced_voucher(self, sim):
        """Tally simulator should catch an imbalanced voucher."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
<BODY>
<VOUCHER VCHTYPE="Purchase">
<DATE>20260615</DATE>
<VOUCHERNUMBER>BAD-001</VOUCHERNUMBER>
<SVCURRENTCOMPANY>Test Co</SVCURRENTCOMPANY>
<PARTYLEDGERNAME>Test Supplier</PARTYLEDGERNAME>
<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Test Supplier</LEDGERNAME>
<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
<ISPARTYLEDGER>Yes</ISPARTYLEDGER>
<AMOUNT>-1000.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>
<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Purchase</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>1000.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>
<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Input CGST @ 9%</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<AMOUNT>180.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>
</VOUCHER>
</BODY>
</ENVELOPE>"""
        r = sim.simulate_import(xml, "Purchase")
        # Should flag unbalanced
        unbalanced = [c for c in r.checks if "unbalanced" in c.message.lower() and not c.passed]
        assert len(unbalanced) > 0
