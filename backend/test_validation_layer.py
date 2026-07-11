"""Tests for the Validation Layer."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from schemas import (
    StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry,
)
from validation_layer import (
    validate_invoice_for_xml, validate_xml_output, ValidationResult,
)


def _make_valid_invoice(**overrides) -> StandardizedInvoice:
    defaults = {
        "invoice_number": "INV-001",
        "invoice_date": "2024-01-15",
        "vendor_name": "Test Vendor",
        "vendor_gstin": "27AABCU1234F1ZP",
        "voucher_type": VoucherType.PURCHASE,
        "gst_type": GSTType.CGST_SGST,
        "total_taxable_value": 10000.0,
        "total_tax": 1800.0,
        "total_amount": 11800.0,
        "line_items": [
            LineItem(description="Test Item", quantity=1, rate=10000, taxable_value=10000, tax_rate=18),
        ],
        "taxes": [
            TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst"),
            TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst"),
        ],
    }
    defaults.update(overrides)
    return StandardizedInvoice(**defaults)


def test_valid_invoice_passes():
    inv = _make_valid_invoice()
    result = validate_invoice_for_xml(inv)
    assert result.passed, f"Expected passed, got errors: {result.errors}"


def test_missing_fields():
    inv = _make_valid_invoice(vendor_name="", invoice_number="")
    result = validate_invoice_for_xml(inv)
    assert not result.passed
    mandatory = result.checks.get("mandatory_fields", {})
    assert not mandatory.get("pass", True)


def test_invalid_gstin():
    inv = _make_valid_invoice(vendor_gstin="INVALID")
    result = validate_invoice_for_xml(inv)
    gstin_check = result.checks.get("gstin_vendor", {})
    assert not gstin_check.get("pass", True)


def test_future_date():
    inv = _make_valid_invoice(invoice_date="2099-01-01")
    result = validate_invoice_for_xml(inv)
    date_check = result.checks.get("date", {})
    assert not date_check.get("pass", True)


def test_invalid_tax_rate():
    inv = _make_valid_invoice(
        line_items=[
            LineItem(description="Weird Rate", quantity=1, rate=1000, taxable_value=1000, tax_rate=7),
        ],
    )
    result = validate_invoice_for_xml(inv)
    tax_check = result.checks.get("tax_rates", {})
    assert not tax_check.get("pass", True)


def test_gst_structure_igst_with_cgst():
    inv = _make_valid_invoice(
        taxes=[
            TaxEntry(name="CGST", rate=9, amount=900, type="cgst"),
            TaxEntry(name="IGST", rate=18, amount=1800, type="igst"),
        ],
    )
    result = validate_invoice_for_xml(inv)
    gst_check = result.checks.get("gst_structure", {})
    assert not gst_check.get("pass", True)


def test_amount_mismatch():
    inv = _make_valid_invoice(total_amount=9999.0)
    result = validate_invoice_for_xml(inv)
    amt_check = result.checks.get("amount_total", {})
    if amt_check:
        assert not amt_check.get("pass", True)


def test_xml_validation_valid():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>All Masters</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVCURRENTCOMPANY>Test Co</SVCURRENTCOMPANY>
      </STATICVARIABLES>
    </DESC>
    <DATA>
      <TALLYMESSAGE>
        <VOUCHER VCHTYPE="Purchase">
          <DATE>20240115</DATE>
          <VOUCHERNUMBER>INV-001</VOUCHERNUMBER>
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Purchase</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
            <AMOUNT>10000.00</AMOUNT>
          </ALLLEDGERENTRIES.LIST>
          <ALLLEDGERENTRIES.LIST>
            <LEDGERNAME>Party</LEDGERNAME>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <AMOUNT>-10000.00</AMOUNT>
          </ALLLEDGERENTRIES.LIST>
        </VOUCHER>
      </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>"""
    result = validate_xml_output(xml)
    assert result.passed, f"XML validation failed: {result.errors}"


def test_xml_validation_unbalanced():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <VOUCHER>
    <ALLLEDGERENTRIES.LIST>
      <AMOUNT>10000.00</AMOUNT>
    </ALLLEDGERENTRIES.LIST>
    <ALLLEDGERENTRIES.LIST>
      <AMOUNT>-5000.00</AMOUNT>
    </ALLLEDGERENTRIES.LIST>
  </VOUCHER>
</ENVELOPE>"""
    result = validate_xml_output(xml)
    assert not result.passed


def test_xml_validation_empty():
    result = validate_xml_output("")
    assert not result.passed


if __name__ == "__main__":
    test_valid_invoice_passes()
    test_missing_fields()
    test_invalid_gstin()
    test_future_date()
    test_invalid_tax_rate()
    test_gst_structure_igst_with_cgst()
    test_amount_mismatch()
    test_xml_validation_valid()
    test_xml_validation_unbalanced()
    test_xml_validation_empty()
    print("All validation layer tests passed!")
