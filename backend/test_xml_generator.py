"""Tests for the Tally XML Generator."""

import sys
import os
import re
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(__file__))

from schemas import (
    StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry,
)
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig


def test_purchase_voucher_goods_intra():
    config = CompanyConfig()
    config.state_code = "27"
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="INV-001",
        invoice_date="2024-01-15",
        vendor_name="ABC Traders",
        vendor_gstin="27AABCU1234F1ZP",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        is_service=False,
        total_taxable_value=10000.0,
        total_tax=1800.0,
        total_amount=11800.0,
        line_items=[
            LineItem(description="Product X", quantity=10, rate=1000, taxable_value=10000, tax_rate=18),
        ],
        taxes=[
            TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst"),
        ],
    )
    xml_str = gen.generate(inv)
    assert "<?xml" in xml_str
    assert "<ENVELOPE>" in xml_str
    assert 'VCHTYPE="Purchase"' in xml_str
    assert "<VOUCHERNUMBER>INV-001</VOUCHERNUMBER>" in xml_str
    assert "<DATE>20240115</DATE>" in xml_str
    assert "<PARTYLEDGERNAME>ABC Traders</PARTYLEDGERNAME>" in xml_str
    assert "<PARTYGSTIN>27AABCU1234F1ZP</PARTYGSTIN>" in xml_str
    assert "<ALLINVENTORYENTRIES.LIST>" not in xml_str  # MVP: ledger-only
    assert "<LEDGERNAME>Purchase</LEDGERNAME>" in xml_str
    assert "<LEDGERNAME>Input CGST 9%</LEDGERNAME>" in xml_str
    assert "<LEDGERNAME>Input SGST 9%</LEDGERNAME>" in xml_str
    assert "<LEDGERNAME>ABC Traders</LEDGERNAME>" in xml_str
    _assert_balanced(xml_str)
    print("PASS: test_purchase_voucher_goods_intra")


def test_purchase_voucher_service():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="SVC-001",
        invoice_date="2024-02-20",
        vendor_name="XYZ Consulting",
        vendor_gstin="27AABCU1234F1ZP",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        is_service=True,
        total_taxable_value=50000.0,
        total_tax=9000.0,
        total_amount=59000.0,
        line_items=[
            LineItem(description="Professional Consulting Fees", quantity=1, rate=50000, taxable_value=50000, tax_rate=18, is_service=True),
        ],
        taxes=[
            TaxEntry(name="Input CGST 9%", rate=9, amount=4500, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=4500, type="sgst"),
        ],
    )
    xml_str = gen.generate(inv)
    assert 'VCHTYPE="Purchase"' in xml_str
    assert "<ALLINVENTORYENTRIES.LIST>" not in xml_str, "Service invoice should NOT have inventory entries"
    assert "<ALLLEDGERENTRIES.LIST>" in xml_str
    assert "<LEDGERNAME>Professional Charges</LEDGERNAME>" in xml_str
    assert "<LEDGERNAME>Purchase</LEDGERNAME>" not in xml_str, "Service invoice should not use Purchase ledger"
    assert "Input CGST 9%" in xml_str
    assert "Input SGST 9%" in xml_str
    _assert_balanced(xml_str)
    print("PASS: test_purchase_voucher_service")


def test_purchase_voucher_interstate():
    config = CompanyConfig()
    config.state_code = "27"
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="IGST-001",
        invoice_date="2024-03-10",
        vendor_name="Karnataka Goods",
        vendor_gstin="29AABCU1234F1ZL",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.IGST,
        is_interstate=True,
        is_service=False,
        total_taxable_value=20000.0,
        total_tax=3600.0,
        total_amount=23600.0,
        line_items=[
            LineItem(description="Equipment", quantity=2, rate=10000, taxable_value=20000, tax_rate=18),
        ],
        taxes=[
            TaxEntry(name="Input IGST 18%", rate=18, amount=3600, type="igst"),
        ],
    )
    xml_str = gen.generate(inv)
    assert "Input IGST 18%" in xml_str
    assert "CGST" not in xml_str.split("<LEDGERNAME>")[1] if len(xml_str.split("<LEDGERNAME>")) > 1 else True
    _assert_balanced(xml_str)
    print("PASS: test_purchase_voucher_interstate")


def test_mixed_gst_rates():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="MIX-001",
        invoice_date="2024-04-01",
        vendor_name="Mixed Supplier",
        vendor_gstin="27AABCU1234F1ZP",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        total_taxable_value=8000.0,
        total_tax=840.0,
        total_amount=8840.0,
        line_items=[
            LineItem(description="Item at 5%", quantity=1, rate=5000, taxable_value=5000, tax_rate=5),
            LineItem(description="Item at 12%", quantity=1, rate=3000, taxable_value=3000, tax_rate=12),
        ],
        taxes=[
            TaxEntry(name="Input CGST 2.5%", rate=2.5, amount=125, type="cgst"),
            TaxEntry(name="Input SGST 2.5%", rate=2.5, amount=125, type="sgst"),
            TaxEntry(name="Input CGST 6%", rate=6, amount=180, type="cgst"),
            TaxEntry(name="Input SGST 6%", rate=6, amount=180, type="sgst"),
        ],
    )
    xml_str = gen.generate(inv)
    _assert_balanced(xml_str)
    print("PASS: test_mixed_gst_rates")


def test_with_freight_and_roundoff():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="FRT-001",
        invoice_date="2024-05-15",
        vendor_name="Freight Supplier",
        vendor_gstin="27AABCU1234F1ZP",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        total_taxable_value=10000.0,
        total_tax=1800.0,
        total_amount=11999.0,
        freight=200.0,
        round_off=-1.0,
        line_items=[
            LineItem(description="Goods", quantity=1, rate=10000, taxable_value=10000, tax_rate=18),
        ],
        taxes=[
            TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst"),
        ],
    )
    xml_str = gen.generate(inv)
    assert "Freight Expenses" in xml_str
    assert "Round Off" in xml_str
    _assert_balanced(xml_str)
    print("PASS: test_with_freight_and_roundoff")


def test_credit_note():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="CN-001",
        invoice_date="2024-06-01",
        vendor_name="Return Supplier",
        vendor_gstin="27AABCU1234F1ZP",
        voucher_type=VoucherType.CREDIT_NOTE,
        gst_type=GSTType.CGST_SGST,
        total_taxable_value=5000.0,
        total_tax=900.0,
        total_amount=5900.0,
        line_items=[
            LineItem(description="Returned Item", quantity=1, rate=5000, taxable_value=5000, tax_rate=18),
        ],
        taxes=[
            TaxEntry(name="Input CGST 9%", rate=9, amount=450, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=450, type="sgst"),
        ],
    )
    xml_str = gen.generate(inv)
    assert 'VCHTYPE="Credit Note"' in xml_str
    _assert_balanced(xml_str)
    print("PASS: test_credit_note")


def test_tds_deduction():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="TDS-001",
        invoice_date="2024-07-01",
        vendor_name="TDS Vendor",
        vendor_address="Mumbai",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        total_taxable_value=100000.0,
        total_tax=18000.0,
        total_amount=118000.0,
        tds_amount=10000.0,
        line_items=[
            LineItem(description="Professional Services", quantity=1, rate=100000, taxable_value=100000, tax_rate=18, is_service=True),
        ],
        taxes=[
            TaxEntry(name="Input CGST 9%", rate=9, amount=9000, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=9000, type="sgst"),
        ],
        is_service=True,
    )
    xml_str = gen.generate(inv)
    assert "TDS Payable" in xml_str
    _assert_balanced(xml_str)
    print("PASS: test_tds_deduction")


def test_voucher_balance_debits_equals_credits():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    inv = StandardizedInvoice(
        invoice_number="BAL-001",
        invoice_date="2024-08-01",
        vendor_name="Balance Test",
        vendor_gstin="27AABCU1234F1ZP",
        voucher_type=VoucherType.PURCHASE,
        gst_type=GSTType.CGST_SGST,
        total_taxable_value=15000.0,
        total_tax=2700.0,
        total_amount=17700.0,
        line_items=[
            LineItem(description="Test Item", quantity=3, rate=5000, taxable_value=15000, tax_rate=18),
        ],
        taxes=[
            TaxEntry(name="Input CGST 9%", rate=9, amount=1350, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=1350, type="sgst"),
        ],
    )
    xml_str = gen.generate(inv)
    # _assert_balanced already verifies this; just print details
    _assert_balanced(xml_str)
    print("PASS: test_voucher_balance_debits_equals_credits (balanced via _assert_balanced)")


def _assert_balanced(xml_str: str):
    no_inv = re.sub(
        r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>",
        "", xml_str, flags=re.DOTALL,
    )
    no_ba = re.sub(
        r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>",
        "", no_inv, flags=re.DOTALL,
    )
    amounts = re.findall(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", no_ba)
    debits = sum(float(a) for a in amounts if float(a) >= 0)
    credits = sum(abs(float(a)) for a in amounts if float(a) < 0)
    assert abs(debits - credits) < 0.10, f"Voucher NOT balanced: Dr={debits:.2f} Cr={credits:.2f}"


def test_various_gst_slabs():
    config = CompanyConfig()
    gen = TallyXmlGenerator(config)
    for rate in [5, 12, 18, 28]:
        half = rate / 2
        inv = StandardizedInvoice(
            invoice_number=f"SLAB-{rate}",
            invoice_date="2024-09-01",
            vendor_name="Slab Test",
            vendor_gstin="27AABCU1234F1ZP",
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            total_taxable_value=10000.0,
            total_tax=rate * 100,
            total_amount=10000 + rate * 100,
            line_items=[
                LineItem(description=f"Item at {rate}%", quantity=1, rate=10000, taxable_value=10000, tax_rate=rate),
            ],
            taxes=[
                TaxEntry(name=f"Input CGST {half}%", rate=half, amount=rate * 50, type="cgst"),
                TaxEntry(name=f"Input SGST {half}%", rate=half, amount=rate * 50, type="sgst"),
            ],
        )
        xml_str = gen.generate(inv)
        _assert_balanced(xml_str)
        assert f"Input CGST {half:.0f}%" in xml_str or f"Input CGST {half}" in xml_str
        assert f"Input SGST {half:.0f}%" in xml_str or f"Input SGST {half}" in xml_str
        print(f"PASS: GST slab {rate}%")


if __name__ == "__main__":
    test_purchase_voucher_goods_intra()
    test_purchase_voucher_service()
    test_purchase_voucher_interstate()
    test_mixed_gst_rates()
    test_with_freight_and_roundoff()
    test_credit_note()
    test_tds_deduction()
    test_voucher_balance_debits_equals_credits()
    test_various_gst_slabs()
    print("\n=== ALL XML GENERATOR TESTS PASSED ===")
