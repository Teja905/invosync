"""Tests for TDS compliance engine and GSTR reconciliation engine."""

import pytest
from tds_engine import (
    detect_tds_applicability,
    validate_tds_deduction,
    suggest_tds_section,
    TDS_RULES,
)
from gstr_reconciler import (
    reconcile,
    parse_gstr2a_json,
    _normalize_gstin,
    _normalize_invoice_number,
    _normalize_date,
    GSTRInvoice,
)


# ===== TDS Engine Tests =====

class TestTDSDetection:
    """Test TDS applicability detection."""

    def test_professional_fees_194j(self):
        detections = detect_tds_applicability("Professional fees for audit", 50000, is_service=True)
        assert len(detections) > 0
        assert any(d.section == "194J(a)" for d in detections)

    def test_contractor_194c(self):
        detections = detect_tds_applicability("Contractor payment for building work", 100000, is_service=True)
        assert len(detections) > 0
        assert any(d.section == "194C" for d in detections)

    def test_commission_194h(self):
        detections = detect_tds_applicability("Sales commission for dealer", 20000)
        assert len(detections) > 0
        assert any(d.section == "194H" for d in detections)

    def test_rent_194i(self):
        detections = detect_tds_applicability("Office rent for April 2024", 50000)
        assert len(detections) > 0
        assert any("194I" in d.section for d in detections)

    def test_no_tds_for_general_goods(self):
        detections = detect_tds_applicability("Purchase of raw materials", 100000)
        # Should not trigger TDS for generic goods purchase
        applicable = [d for d in detections if d.is_applicable and d.confidence > 0.5]
        assert len(applicable) == 0

    def test_threshold_check(self):
        # Below threshold
        detections = detect_tds_applicability("Professional fees", 10000, is_service=True)
        for d in detections:
            if d.section == "194J(a)":
                assert not d.is_applicable

    def test_above_threshold(self):
        # Above threshold
        detections = detect_tds_applicability("Professional fees", 50000, is_service=True)
        for d in detections:
            if d.section == "194J(a)":
                assert d.is_applicable

    def test_confidence排序(self):
        detections = detect_tds_applicability("Professional fees for audit and accounting", 50000, is_service=True)
        if len(detections) > 1:
            assert detections[0].confidence >= detections[1].confidence


class TestTDSValidation:
    """Test TDS deduction validation."""

    def test_correct_deduction(self):
        result = validate_tds_deduction(
            tds_section="194J(a)",
            tds_amount=5000,
            payment_amount=50000,
            rate=10.0,
            vendor_pan="AABCU1234F",
        )
        assert result.is_compliant

    def test_incorrect_rate(self):
        result = validate_tds_deduction(
            tds_section="194J(a)",
            tds_amount=2500,
            payment_amount=50000,
            rate=5.0,  # Wrong rate for 194J
            vendor_pan="AABCU1234F",
        )
        assert len(result.warnings) > 0

    def test_missing_pan(self):
        result = validate_tds_deduction(
            tds_section="194J(a)",
            tds_amount=5000,
            payment_amount=50000,
            rate=10.0,
        )
        assert any("PAN" in w for w in result.warnings)

    def test_below_threshold(self):
        result = validate_tds_deduction(
            tds_section="194J(a)",
            tds_amount=1000,
            payment_amount=20000,  # Below 30000 threshold
            rate=10.0,
            vendor_pan="AABCU1234F",
        )
        assert any("threshold" in w.lower() for w in result.warnings)

    def test_unknown_section(self):
        result = validate_tds_deduction(
            tds_section="1999X",
            tds_amount=1000,
            payment_amount=50000,
            rate=10.0,
        )
        assert not result.is_compliant
        assert len(result.errors) > 0


class TestTDSSuggestion:
    """Test TDS section suggestion."""

    def test_suggest_professional(self):
        section = suggest_tds_section("Chartered accountant fees")
        assert section is not None
        assert "194J" in section

    def test_suggest_contractor(self):
        section = suggest_tds_section("Building contractor payment")
        assert section is not None
        assert "194C" in section

    def test_suggest_commission(self):
        section = suggest_tds_section("Commission payment to agent")
        assert section is not None
        assert "194H" in section


# ===== GSTR Reconciliation Tests =====

class TestGSTRNormalization:
    """Test normalization functions."""

    def test_normalize_gstin(self):
        assert _normalize_gstin(" 27aabcu1234f1zp ") == "27AABCU1234F1ZP"
        assert _normalize_gstin("") == ""

    def test_normalize_invoice_number(self):
        # The normalizer strips common prefixes and removes zeros
        assert _normalize_invoice_number("001") == "1"
        assert _normalize_invoice_number("0001") == "1"
        assert _normalize_invoice_number("12345") == "12345"

    def test_normalize_date_yyyy_mm_dd(self):
        assert _normalize_date("2024-04-01") == "2024-04-01"

    def test_normalize_date_dd_mm_yyyy(self):
        assert _normalize_date("01/04/2024") == "2024-04-01"

    def test_normalize_date_dd_mm_yyyy_dash(self):
        assert _normalize_date("01-04-2024") == "2024-04-01"

    def test_normalize_date_empty(self):
        assert _normalize_date("") == ""


class TestGSTRParsing:
    """Test GSTR-2A JSON parsing."""

    def test_parse_b2b(self):
        data = {
            "b2b": [
                {
                    "ctin": "27AABCU1234F1ZP",
                    "trdnm": "Test Vendor",
                    "inv": [
                        {
                            "inum": "INV-001",
                            "idt": "01-04-2024",
                            "val": 118000,
                            "pos": "27-Maharashtra",
                            "typ": "N",
                            "itms": [
                                {
                                    "num": 1,
                                    "itm_det": {
                                        "rt": 18,
                                        "txval": 100000,
                                        "iamt": 0,
                                        "camt": 9000,
                                        "samt": 9000,
                                        "csamt": 0,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        invoices = parse_gstr2a_json(data)
        assert len(invoices) == 1
        assert invoices[0].gstin == "27AABCU1234F1ZP"
        assert invoices[0].invoice_number == "INV-001"
        assert invoices[0].taxable_value == 100000
        assert invoices[0].cgst == 9000
        assert invoices[0].sgst == 9000

    def test_parse_empty(self):
        invoices = parse_gstr2a_json({})
        assert len(invoices) == 0

    def test_parse_multiple_suppliers(self):
        data = {
            "b2b": [
                {"ctin": "27AABCU1234F1ZP", "inv": [{"inum": "INV-001", "val": 118000, "itms": [{"itm_det": {"txval": 100000, "camt": 9000, "samt": 9000}}]}]},
                {"ctin": "29AABCT1234F1ZM", "inv": [{"inum": "INV-002", "val": 59000, "itms": [{"itm_det": {"txval": 50000, "camt": 4500, "samt": 4500}}]}]},
            ]
        }
        invoices = parse_gstr2a_json(data)
        assert len(invoices) == 2


class TestGSTRReconciliation:
    """Test reconciliation matching."""

    def test_perfect_match(self):
        books = [
            {"vendor_gstin": "27AABCU1234F1ZP", "invoice_number": "INV-001", "total_amount": 118000, "total_taxable_value": 100000, "total_tax": 18000}
        ]
        gstr = [
            GSTRInvoice(gstin="27AABCU1234F1ZP", invoice_number="INV-001", invoice_date="01-04-2024", invoice_value=118000, taxable_value=100000, place_of_supply="27", rate=18, cgst=9000, sgst=9000)
        ]
        report = reconcile(books, gstr)
        assert len(report.matched) == 1
        assert len(report.mismatched) == 0
        assert len(report.missing_in_2a) == 0

    def test_missing_in_2a(self):
        books = [
            {"vendor_gstin": "27AABCU1234F1ZP", "invoice_number": "INV-001", "total_amount": 118000, "total_taxable_value": 100000, "total_tax": 18000}
        ]
        gstr = []  # Nothing in GSTR
        report = reconcile(books, gstr)
        assert len(report.missing_in_2a) == 1

    def test_missing_in_books(self):
        books = []
        gstr = [
            GSTRInvoice(gstin="27AABCU1234F1ZP", invoice_number="INV-001", invoice_date="01-04-2024", invoice_value=118000, taxable_value=100000, place_of_supply="27", rate=18, cgst=9000, sgst=9000)
        ]
        report = reconcile(books, gstr)
        assert len(report.missing_in_books) == 1

    def test_amount_mismatch(self):
        """Single amount difference is a 'matched' with lower confidence, not a mismatch."""
        books = [
            {"vendor_gstin": "27AABCU1234F1ZP", "invoice_number": "INV-001", "total_amount": 120000, "total_taxable_value": 100000, "total_tax": 18000}
        ]
        gstr = [
            GSTRInvoice(gstin="27AABCU1234F1ZP", invoice_number="INV-001", invoice_date="01-04-2024", invoice_value=118000, taxable_value=100000, place_of_supply="27", rate=18, cgst=9000, sgst=9000)
        ]
        report = reconcile(books, gstr)
        # Single difference = matched with lower confidence (not mismatched)
        assert len(report.matched) == 1
        assert report.matched[0].confidence == 0.9
        assert len(report.mismatched) == 0

    def test_gstin_match_with_different_invoice_number(self):
        books = [
            {"vendor_gstin": "27AABCU1234F1ZP", "invoice_number": "INV-001", "total_amount": 118000, "total_taxable_value": 100000, "total_tax": 18000}
        ]
        gstr = [
            GSTRInvoice(gstin="27AABCU1234F1ZP", invoice_number="INV-12345", invoice_date="01-04-2024", invoice_value=118000, taxable_value=100000, place_of_supply="27", rate=18, cgst=9000, sgst=9000)
        ]
        report = reconcile(books, gstr)
        # Should match by GSTIN + amount even if invoice number differs
        assert len(report.matched) == 1

    def test_empty_inputs(self):
        report = reconcile([], [])
        assert report.total_books == 0
        assert report.total_2a == 0
        assert len(report.matched) == 0

    def test_summary_generation(self):
        books = [
            {"vendor_gstin": "27AABCU1234F1ZP", "invoice_number": "INV-001", "total_amount": 118000, "total_taxable_value": 100000, "total_tax": 18000}
        ]
        gstr = [
            GSTRInvoice(gstin="27AABCU1234F1ZP", invoice_number="INV-001", invoice_date="01-04-2024", invoice_value=118000, taxable_value=100000, place_of_supply="27", rate=18, cgst=9000, sgst=9000)
        ]
        report = reconcile(books, gstr)
        d = report.to_dict()
        assert d["summary"]["total_books"] == 1
        assert d["summary"]["matched_count"] == 1
        assert d["summary"]["match_percentage"] == 100.0
