"""Test the validators package — XMLValidator, RoundTripValidator, AccountingValidator.

Exercises all 7 voucher types through: generation → validation → parse-back → compare.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from gst_engine import _compute_gstin_checksum
from validators.xml_validator import XMLValidator
from validators.round_trip import RoundTripValidator, ParsedVoucher
from validators.accounting_validator import AccountingValidator
from validators.base import ValidationResult, ValidationScore, ValidationCheck

_VALID_GSTIN_KA = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
_VALID_GSTIN_MH = "27AAFFC8126N1Z" + _compute_gstin_checksum("27AAFFC8126N1Z")


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def config():
    return CompanyConfig(user_config={"company_state_code": "27", "company_name": "Test Co"})


@pytest.fixture
def generator(config):
    return TallyXmlGenerator(config)


@pytest.fixture
def xml_validator():
    return XMLValidator()


@pytest.fixture
def rt_validator():
    return RoundTripValidator()


@pytest.fixture
def acct_validator():
    return AccountingValidator()


def _make_goods_invoice(voucher_type=VoucherType.PURCHASE, **kwargs) -> StandardizedInvoice:
    data = dict(
        voucher_type=voucher_type,
        invoice_number="INV-001",
        invoice_date="2026-06-15",
        vendor_name="Test Supplier",
        vendor_gstin=_VALID_GSTIN_KA,
        buyer_gstin=_VALID_GSTIN_KA,
        place_of_supply="29",
        buyer_name="Test Buyer",
        vendor_address="123 Vendor St",
        buyer_address="456 Buyer Ave",
        is_service=False,
            line_items=[
                LineItem(
                    description="Widget A",
                    quantity=10,
                    rate=100.0,
                    taxable_value=1000.0,
                    hsn_sac="84713000",
                    unit="Nos",
                ),
            ],
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=90.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=90.0, type="sgst"),
            ],
        )
    data.update(kwargs)
    return StandardizedInvoice(**data)


def _make_service_invoice(voucher_type=VoucherType.PURCHASE, **kwargs) -> StandardizedInvoice:
    data = dict(
        voucher_type=voucher_type,
        invoice_number="SVC-001",
        invoice_date="2026-06-15",
        vendor_name="IT Services Ltd",
        vendor_gstin=_VALID_GSTIN_KA,
        buyer_gstin=_VALID_GSTIN_KA,
        place_of_supply="29",
        is_service=True,
        buyer_name="Test Buyer",
        vendor_address="123 Vendor St",
        buyer_address="456 Buyer Ave",
        line_items=[
            LineItem(
                description="Consulting Services",
                quantity=1,
                rate=50000.0,
                taxable_value=50000.0,
                hsn_sac="998313",
                unit="Nos",
            ),
        ],
        total_taxable_value=50000.0,
        total_tax=9000.0,
        total_amount=59000.0,
        taxes=[
            TaxEntry(name="CGST", rate=9.0, amount=4500.0, type="cgst"),
            TaxEntry(name="SGST", rate=9.0, amount=4500.0, type="sgst"),
        ],
    )
    data.update(kwargs)
    return StandardizedInvoice(**data)


# ------------------------------------------------------------------ #
# XMLValidator Tests
# ------------------------------------------------------------------ #

class TestXMLValidatorStructure:

    def test_empty_xml(self, xml_validator):
        result = xml_validator.validate_structure("")
        assert not result.passed
        assert len(result.errors) > 0 or len(result.soft_errors) > 0

    def test_well_formed_xml(self, xml_validator, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        result = xml_validator.validate_structure(xml_str)
        assert result.passed, f"Structural errors: {result.errors}"

    def test_missing_declaration(self, xml_validator):
        xml = "<ENVELOPE><HEADER/><BODY/></ENVELOPE>"
        result = xml_validator.validate_structure(xml)
        assert any("declaration" in c.message.lower() for c in result.checks if not c.passed)

    def test_no_voucher_type(self, xml_validator):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><VOUCHER></VOUCHER></BODY></ENVELOPE>"""
        result = xml_validator.validate_structure(xml)
        assert any("vchtype" in c.message.lower() for c in result.checks if not c.passed)


class TestXMLValidatorBalance:

    def test_proper_balance(self, xml_validator, generator):
        for vt in VoucherType:
            inv = _make_goods_invoice(voucher_type=vt)
            xml_str = generator.generate(inv)
            result = xml_validator.validate_balance(xml_str)
            bal_errors = [c for c in result.checks if "unbalanced" in c.message.lower() and c.severity == "error"]
            assert len(bal_errors) == 0, f"{vt.value}: {bal_errors}"

    def test_imbalanced_xml(self, xml_validator):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
<BODY>
<VOUCHER VCHTYPE="Purchase">
<DATE>20260615</DATE>
<VOUCHERNUMBER>TEST-001</VOUCHERNUMBER>
<PARTYLEDGERNAME>Test Supplier</PARTYLEDGERNAME>
<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>Test Supplier</LEDGERNAME>
<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
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
<AMOUNT>100.00</AMOUNT>
</ALLLEDGERENTRIES.LIST>
</VOUCHER>
</BODY>
</ENVELOPE>"""
        result = xml_validator.validate_balance(xml)
        bal_errors = [c for c in result.checks if "unbalanced" in c.message.lower()]
        assert len(bal_errors) > 0


class TestXMLValidatorMasters:

    def test_masters_created(self, xml_validator, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        result = xml_validator.validate_masters(xml_str)
        master_checks = [c for c in result.checks if c.category == "masters"]
        assert len(master_checks) >= 2

    def test_service_no_stock(self, xml_validator, generator):
        inv = _make_service_invoice()
        xml_str = generator.generate(inv)
        result = xml_validator.validate_masters(xml_str)
        stock_msgs = [c for c in result.checks if "stock" in c.message.lower() and "item" in c.message.lower()]
        assert len(stock_msgs) == 0


# ------------------------------------------------------------------ #
# RoundTripValidator Tests
# ------------------------------------------------------------------ #

class TestRoundTripParse:

    def test_parse_goods_purchase(self, rt_validator, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        parsed = rt_validator.parse_voucher(xml_str)
        assert parsed is not None
        assert parsed.voucher_type == "Purchase"
        assert parsed.voucher_number == "INV-001"
        assert parsed.is_invoice is True
        assert len(parsed.entries) >= 3
        assert len(parsed.inventory_items) == 1

    def test_parse_service(self, rt_validator, generator):
        inv = _make_service_invoice()
        xml_str = generator.generate(inv)
        parsed = rt_validator.parse_voucher(xml_str)
        assert parsed is not None
        assert parsed.is_invoice is False
        assert len(parsed.inventory_items) == 0

    def test_parse_sales(self, rt_validator, generator):
        inv = _make_goods_invoice(voucher_type=VoucherType.SALES)
        xml_str = generator.generate(inv)
        parsed = rt_validator.parse_voucher(xml_str)
        assert parsed is not None
        assert parsed.voucher_type == "Sales"

    def test_parse_credit_note(self, rt_validator, generator):
        inv = _make_goods_invoice(voucher_type=VoucherType.CREDIT_NOTE,
                                  original_invoice_number="INV-ORIG-001",
                                  original_invoice_date="2026-06-01")
        xml_str = generator.generate(inv)
        parsed = rt_validator.parse_voucher(xml_str)
        assert parsed is not None
        assert parsed.voucher_type == "Credit Note"
        assert parsed.original_invoice_no == "INV-ORIG-001"

    def test_parse_debit_note(self, rt_validator, generator):
        inv = _make_goods_invoice(voucher_type=VoucherType.DEBIT_NOTE,
                                  original_invoice_number="INV-ORIG-002",
                                  original_invoice_date="2026-06-01")
        xml_str = generator.generate(inv)
        parsed = rt_validator.parse_voucher(xml_str)
        assert parsed is not None
        assert parsed.voucher_type == "Debit Note"

    def test_parse_all_types(self, rt_validator, generator):
        for vt in VoucherType:
            inv = _make_goods_invoice(voucher_type=vt)
            xml_str = generator.generate(inv)
            parsed = rt_validator.parse_voucher(xml_str)
            assert parsed is not None, f"Failed to parse {vt.value}"
            actual = parsed.voucher_type
            assert actual == vt.value or actual == vt.name, f"Expected {vt.value}, got {actual}"

    def test_parse_malformed_xml(self, rt_validator):
        assert rt_validator.parse_voucher("") is None
        assert rt_validator.parse_voucher("<broken>") is None
        assert rt_validator.parse_voucher("not xml at all") is None


class TestRoundTripValidation:

    def test_round_trip_goods_purchase(self, rt_validator, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        result = rt_validator.validate_round_trip(inv, xml_str)
        assert result.passed, f"Errors: {result.errors}"

    def test_round_trip_service(self, rt_validator, generator):
        inv = _make_service_invoice()
        xml_str = generator.generate(inv)
        result = rt_validator.validate_round_trip(inv, xml_str)
        assert result.passed

    def test_round_trip_sales(self, rt_validator, generator):
        inv = _make_goods_invoice(voucher_type=VoucherType.SALES)
        xml_str = generator.generate(inv)
        result = rt_validator.validate_round_trip(inv, xml_str)
        assert result.passed

    def test_round_trip_mismatch(self, rt_validator, generator):
        inv = _make_goods_invoice(voucher_type=VoucherType.PURCHASE)
        xml_str = generator.generate(inv)
        xml_str = xml_str.replace('VCHTYPE="Purchase"', 'VCHTYPE="Sales"')
        result = rt_validator.validate_round_trip(inv, xml_str)
        assert not result.passed
        assert any("vchtype" in c.message.lower() for c in result.checks if not c.passed)


# ------------------------------------------------------------------ #
# AccountingValidator Tests
# ------------------------------------------------------------------ #

class TestAccountingValidator:

    def test_valid_invoice_passes(self, acct_validator):
        inv = _make_goods_invoice()
        result = acct_validator.validate(inv)
        assert result.passed, f"Errors: {result.errors}"

    def test_negative_amounts(self, acct_validator):
        inv = _make_goods_invoice(total_amount=-100.0)
        result = acct_validator.validate(inv)
        assert not result.passed
        assert any("must be positive" in c.message.lower() for c in result.checks if not c.passed)

    def test_mismatch_tax_total(self, acct_validator):
        inv = _make_goods_invoice(total_tax=999.0)
        result = acct_validator.validate(inv)
        assert not result.passed
        assert any("computed tax" in c.message.lower() or "tax" in c.message.lower() for c in result.checks if not c.passed)

    def test_missing_line_items_warning(self, acct_validator):
        inv = _make_goods_invoice(line_items=[])
        result = acct_validator.validate(inv)
        assert len(result.warnings) > 0 or not result.passed

    def test_invalid_gst_rate(self, acct_validator):
        inv = _make_goods_invoice(line_items=[
            LineItem(
                description="Bad GST",
                quantity=1,
                rate=100.0,
                taxable_value=100.0,
                hsn_code="84713000",
                unit="Nos",
                tax_rate=14.0,
            ),
        ])
        result = acct_validator.validate(inv)
        assert len(result.warnings) > 0 or not result.passed

    def test_vendor_name_whitespace(self, acct_validator):
        inv = _make_goods_invoice(vendor_name="   ")
        result = acct_validator.validate(inv)
        assert not result.passed
        assert any("vendor name" in c.message.lower()
                    for c in result.checks if not c.passed)


# ------------------------------------------------------------------ #
# ValidationScore Tests
# ------------------------------------------------------------------ #

class TestValidationScore:

    def test_score_perfect(self):
        vr = ValidationResult()
        result = ValidationScore.from_validation(vr)
        assert result.score == 100
        assert result.passed

    def test_score_with_errors(self):
        vr = ValidationResult()
        vr.add_error("test_error", "Test error")
        result = ValidationScore.from_validation(vr)
        assert result.score < 100
        assert not result.passed

    def test_score_with_warnings(self):
        vr = ValidationResult()
        vr.add_warning("test_warning", category="test")
        result = ValidationScore.from_validation(vr)
        # Warnings don't make result fail, but score still reflects
        assert result.score == 100
        assert result.passed
        assert len(result.warnings) > 0

    def test_score_passed_threshold(self):
        vr = ValidationResult()
        vr.add_error("soft1", "Soft error 1", category="line_items")
        vr.add_error("soft2", "Soft error 2", category="line_items")
        result = ValidationScore.from_validation(vr)
        d = result.to_dict()
        assert "blocked" in d or "needs_review" in d or "production_ready" in d

    def test_score_integration(self, acct_validator, xml_validator, rt_validator, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)

        acct_score = acct_validator.score(inv)
        xml_score = xml_validator.score(xml_str)
        rt_score = rt_validator.score(inv, xml_str)

        for name, score in [("accounting", acct_score), ("xml", xml_score), ("round_trip", rt_score)]:
            assert 0 <= score.score <= 100, f"{name} score out of range: {score.score}"

    def test_unanimous_review(self, acct_validator, xml_validator, rt_validator, generator):
        inv = _make_goods_invoice(vendor_name="   ")
        xml_str = generator.generate(inv)

        scores = {
            "acct": acct_validator.score(inv),
            "xml": xml_validator.score(xml_str),
            "rt": rt_validator.score(inv, xml_str),
        }

        assert scores["acct"].score < 100
        min_score = min(s.score for s in scores.values())
        assert min_score < 100


# ------------------------------------------------------------------ #
# Golden File Tests
# ------------------------------------------------------------------ #

class TestGoldenFiles:

    @pytest.fixture
    def temp_golden_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir)

    def test_golden_created_first_run(self, temp_golden_dir, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        validator = XMLValidator(golden_dir=temp_golden_dir)
        result = validator.check_golden("purchase_test", xml_str)
        golden_path = Path(temp_golden_dir) / "purchase_test.xml"
        assert golden_path.exists()
        assert any("created" in c.message.lower() for c in result.checks)

    def test_golden_matches(self, temp_golden_dir, generator):
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        validator = XMLValidator(golden_dir=temp_golden_dir)
        validator.check_golden("match_test", xml_str)
        result = validator.check_golden("match_test", xml_str)
        assert any("match" in c.message.lower() and c.passed for c in result.checks)

    def test_golden_mismatch_detected(self, temp_golden_dir, generator):
        inv1 = _make_goods_invoice(invoice_number="VERSION-A")
        inv2 = _make_goods_invoice(invoice_number="VERSION-B")
        validator = XMLValidator(golden_dir=temp_golden_dir)

        xml1 = generator.generate(inv1)
        validator.check_golden("version_test", xml1)

        xml2 = generator.generate(inv2)
        result = validator.check_golden("version_test", xml2)
        # Should detect mismatch (VERSION-A vs VERSION-B) as a warning
        mismatch_msgs = [c.message for c in result.checks if "mismatch" in c.message.lower()]
        assert len(mismatch_msgs) > 0, f"No golden mismatch warning. Checks: {result.checks}"


# ------------------------------------------------------------------ #
# ValidationCheck Tests
# ------------------------------------------------------------------ #

class TestValidationCheck:

    def test_passed_check(self):
        c = ValidationCheck(name="test", category="test", message="ok", severity="info", passed=True)
        assert c.passed
        assert c.severity == "info"

    def test_failed_check(self):
        c = ValidationCheck(name="test", category="test", message="fail", severity="error", passed=False)
        assert not c.passed
        assert c.severity == "error"

    def test_warning_check(self):
        c = ValidationCheck(name="test", category="test", message="warn", severity="warning", passed=False)
        assert not c.passed
        assert c.severity == "warning"


# ------------------------------------------------------------------ #
# Result add methods
# ------------------------------------------------------------------ #

class TestValidationResultAdd:

    def test_add_error(self):
        vr = ValidationResult()
        vr.add_error("err1", "Error message", category="test")
        assert len(vr.checks) == 1
        assert not vr.checks[0].passed
        assert vr.checks[0].severity == "error"
        assert vr.checks[0].name == "err1"
        assert len(vr.errors) == 1

    def test_add_warning(self):
        vr = ValidationResult()
        vr.add_warning("Warning message", category="test")
        assert len(vr.checks) == 1
        assert vr.checks[0].passed
        assert vr.checks[0].severity == "warning"
        assert len(vr.warnings) == 1

    def test_add_info(self):
        vr = ValidationResult()
        vr.add_info("Info message", category="test")
        assert len(vr.checks) == 1
        assert vr.checks[0].passed
        assert vr.checks[0].severity == "info"

    def test_error_sets_passed_false(self):
        vr = ValidationResult()
        assert vr.passed
        vr.add_error("x", "x")
        assert not vr.passed

    def test_warning_does_not_set_passed_false(self):
        vr = ValidationResult()
        assert vr.passed
        vr.add_warning("warn")
        assert vr.passed

    def test_blocking_errors(self):
        vr = ValidationResult()
        vr.add_error("b1", "Balance error", category="balance")
        vr.add_error("s1", "Soft error", category="gst")
        assert len(vr.blocking_errors) == 1
        assert len(vr.soft_errors) == 1



# ------------------------------------------------------------------ #
# ValidationPipeline Tests
# ------------------------------------------------------------------ #

class TestValidationPipeline:

    def test_pipeline_runs_without_error(self, generator):
        """Pipeline runs end-to-end without crashing."""
        from validators.pipeline import ValidationPipeline
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        pipeline = ValidationPipeline(generator)
        report = pipeline.run(inv, xml_str)
        assert report.total_score >= 0
        assert report.total_score <= 100
        assert isinstance(report.passed, bool)
        assert isinstance(report.ready_for_tally, bool)
        assert report.invoice_number == "INV-001"

    def test_pipeline_detects_broken_invoice(self, generator):
        """Pipeline should flag issues with a broken invoice."""
        from validators.pipeline import ValidationPipeline
        inv = _make_goods_invoice(vendor_name="   ", total_amount=-100.0)
        xml_str = generator.generate(inv)
        pipeline = ValidationPipeline(generator)
        report = pipeline.run(inv, xml_str)
        assert len(report.errors) > 0 or len(report.blocking_errors) > 0

    def test_pipeline_report_has_all_scores(self, generator):
        """Report dict should have accounting, gst, xml, masters scores."""
        from validators.pipeline import ValidationPipeline
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        pipeline = ValidationPipeline(generator)
        d = pipeline.generate_report_only(inv, xml_str)
        scores = d.get("scores", {})
        assert "accounting" in scores
        assert "gst" in scores
        assert "xml" in scores
        assert "masters" in scores
        assert "total" in scores

    def test_human_report_contains_health_section(self, generator):
        """Human-readable report should look like a dashboard."""
        from validators.pipeline import ValidationPipeline
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        pipeline = ValidationPipeline(generator)
        text = pipeline.human_report(inv, xml_str)
        assert "Invoice Health" in text
        assert "Accounting:" in text
        assert "Ready for Tally:" in text
        assert "Invoice #INV-001" in text

    def test_pipeline_all_7_voucher_types(self, generator):
        """Pipeline runs on all 7 voucher types without error."""
        from validators.pipeline import ValidationPipeline
        for vt in VoucherType:
            inv = _make_goods_invoice(voucher_type=vt)
            xml_str = generator.generate(inv)
            pipeline = ValidationPipeline(generator)
            report = pipeline.run(inv, xml_str)
            assert report.total_score > 0, f"{vt.value}: score=0"
            assert report.voucher_type == vt.value, f"{vt.value}: type={report.voucher_type}"

    def test_to_dict_serializable(self, generator):
        """to_dict() should be JSON-serializable."""
        import json
        from validators.pipeline import ValidationPipeline
        inv = _make_goods_invoice()
        xml_str = generator.generate(inv)
        pipeline = ValidationPipeline(generator)
        d = pipeline.generate_report_only(inv, xml_str)
        serialized = json.dumps(d)
        assert len(serialized) > 0
        assert '"ready_for_tally"' in serialized
