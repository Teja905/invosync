"""Tests for xml_preflight.py."""

import pytest
from xml_preflight import XMLPreFlightValidator, validate_xml_preflight


SIMPLE_PURCHASE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>All Masters</REPORTNAME>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE>
          <LEDGER NAME="ABC Suppliers" ACTION="Create">
            <NAME>ABC Suppliers</NAME>
            <PARENT>Sundry Creditors</PARENT>
          </LEDGER>
        </TALLYMESSAGE>
        <TALLYMESSAGE>
          <VOUCHER VCHTYPE="Purchase">
            <DATE>20260615</DATE>
            <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Purchase</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>100000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>ABC Suppliers</LEDGERNAME>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>-100000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
"""

IMBALANCED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <BODY>
    <IMPORTDATA>
      <REQUESTDATA>
        <TALLYMESSAGE>
          <VOUCHER VCHTYPE="Purchase">
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Purchase</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>100000.00</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
"""

MALFORMED_XML = "<ENVELOPE><BODY><UNCLOSED"


class TestPreFlightPass:
    def test_valid_purchase_passes(self):
        report = validate_xml_preflight(SIMPLE_PURCHASE_XML)
        assert report["passed"] is True
        assert report["voucher_type"] == "Purchase"
        assert report["has_ledgers"] is True

    def test_report_fields(self):
        report = validate_xml_preflight(SIMPLE_PURCHASE_XML)
        assert "xml_length" in report
        assert "errors" in report
        assert "warnings" in report
        assert "info" in report


class TestPreFlightErrors:
    def test_empty_xml(self):
        report = validate_xml_preflight("")
        assert report["passed"] is False
        assert any(i["code"] == "EMPTY_XML" for i in report["errors"])

    def test_malformed_xml(self):
        report = validate_xml_preflight(MALFORMED_XML)
        assert report["passed"] is False
        assert any(i["code"] == "MALFORMED_XML" for i in report["errors"])

    def test_no_envelope(self):
        xml = "<ROOT></ROOT>"
        report = validate_xml_preflight(xml)
        assert any(i["code"] == "NO_ENVELOPE" for i in report["errors"])

    def test_unbalanced_voucher(self):
        report = validate_xml_preflight(IMBALANCED_XML)
        assert any(i["code"] == "UNBALANCED_VOUCHER" for i in report["errors"])


class TestPreFlightWarnings:
    def test_no_masters_warning(self):
        xml = """<?xml version="1.0"?>
        <ENVELOPE>
          <BODY>
            <IMPORTDATA>
              <REQUESTDATA>
                <TALLYMESSAGE>
                  <VOUCHER VCHTYPE="Purchase">
                    <ALLLEDGERENTRIES.LIST>
                      <LEDGERNAME>Purchase</LEDGERNAME>
                      <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                      <AMOUNT>100.00</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
                    <ALLLEDGERENTRIES.LIST>
                      <LEDGERNAME>Supplier</LEDGERNAME>
                      <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                      <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                      <AMOUNT>-100.00</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
                  </VOUCHER>
                </TALLYMESSAGE>
              </REQUESTDATA>
            </IMPORTDATA>
          </BODY>
        </ENVELOPE>
        """
        report = validate_xml_preflight(xml)
        assert any(i["code"] == "NO_MASTERS" for i in report["warnings"])

    def test_no_gst_ledgers_warning(self):
        xml = SIMPLE_PURCHASE_XML.replace("Purchase", "Sales")
        report = validate_xml_preflight(xml.replace('VCHTYPE="Purchase"', 'VCHTYPE="Sales"'))
        assert any(i["code"] == "NO_GST_LEDGERS" for i in report["warnings"])

    def test_no_company_warning(self):
        xml = SIMPLE_PURCHASE_XML.replace("All Masters", "Vouchers")
        report = validate_xml_preflight(xml)
        assert any(i["code"] == "NO_COMPANY" for i in report["warnings"])


class TestPreFlightInfo:
    def test_bill_type_info(self):
        xml = (
            '<ENVELOPE><BODY><IMPORTDATA><REQUESTDATA><TALLYMESSAGE>'
            '<VOUCHER VCHTYPE="Purchase">'
            '<ALLLEDGERENTRIES.LIST>'
            '<LEDGERNAME>Purchase</LEDGERNAME>'
            '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>'
            '<AMOUNT>100.00</AMOUNT>'
            '<BILLALLOCATIONS.LIST><NAME>INV-001</NAME><BILLTYPE>Old Ref</BILLTYPE><AMOUNT>100.00</AMOUNT></BILLALLOCATIONS.LIST>'
            '</ALLLEDGERENTRIES.LIST>'
            '<ALLLEDGERENTRIES.LIST>'
            '<LEDGERNAME>Supplier</LEDGERNAME>'
            '<ISPARTYLEDGER>Yes</ISPARTYLEDGER>'
            '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
            '<AMOUNT>-100.00</AMOUNT>'
            '</ALLLEDGERENTRIES.LIST>'
            '</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>'
        )
        report = validate_xml_preflight(xml)
        assert any(i["code"] == "NON_STANDARD_BILL_TYPE" for i in report["info"])
