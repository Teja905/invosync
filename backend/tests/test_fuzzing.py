"""Fuzz tests — malformed / adversarial inputs must never crash the system.

These tests send deliberately broken data through every public validation
and generation function. The contract is: garbage in → graceful error out,
never an unhandled exception.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import json
import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from validation_layer import validate_invoice_for_xml, ValidationResult
from gst_engine import validate_gstin, validate_tax_structure, get_valid_slabs_for_date
from core.hallucination_guard import compute_independent_confidence
from core.pii import redact_pii
from ocr_postproc import fix_gstin
from voucher_classifier import classify_voucher_type


# ---------------------------------------------------------------------------
# 1. VALIDATION LAYER — garbage inputs
# ---------------------------------------------------------------------------

class TestValidationFuzz:
    """Every validation input combination must produce a result, never crash."""

    def _make_inv(self, **overrides):
        defaults = dict(
            invoice_number="INV-001",
            invoice_date="2025-06-15",
            vendor_name="Test Vendor",
            vendor_gstin="",
            total_taxable_value=100,
            total_tax=18,
            total_amount=118,
            voucher_type=VoucherType.PURCHASE,
        )
        defaults.update(overrides)
        return StandardizedInvoice(**defaults)

    def test_extremely_long_vendor_name(self):
        inv = self._make_inv(vendor_name="A" * 10000)
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_empty_everything(self):
        inv = StandardizedInvoice()
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_negative_total_amount(self):
        inv = self._make_inv(total_amount=-999, total_taxable_value=-999)
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_zero_amounts(self):
        inv = self._make_inv(total_amount=0, total_tax=0, total_taxable_value=0)
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_huge_amounts(self):
        inv = self._make_inv(total_amount=1e15, total_taxable_value=1e15, total_tax=1.8e14)
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_unicode_vendor_name(self):
        inv = self._make_inv(vendor_name="भारतीय व्यापार कंपनी ₹500")
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_script_in_vendor_name(self):
        inv = self._make_inv(vendor_name="<script>alert('xss')</script>")
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_all_voucher_types(self):
        for vt in VoucherType:
            inv = self._make_inv(voucher_type=vt)
            result = validate_invoice_for_xml(inv)
            assert isinstance(result, ValidationResult)

    def test_nan_amounts(self):
        """NaN must not crash validation."""
        inv = StandardizedInvoice(
            vendor_name="Test",
            total_amount=float("nan"),
            total_taxable_value=float("nan"),
            total_tax=float("nan"),
        )
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_inf_amounts(self):
        """Infinity must not crash validation."""
        inv = StandardizedInvoice(
            vendor_name="Test",
            total_amount=float("inf"),
            total_taxable_value=float("inf"),
            total_tax=float("inf"),
        )
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_date_edge_cases(self):
        for d in ["", "not-a-date", "2025-13-01", "2025-00-00", "9999-99-99",
                   "2025/06/15", "15-06-2025", "06/15/2025", "2025-06-31",
                   "2017-06-30", "2017-07-01"]:
            inv = self._make_inv(invoice_date=d)
            result = validate_invoice_for_xml(inv)
            assert isinstance(result, ValidationResult)

    def test_zero_quantity_line_items(self):
        inv = self._make_inv(
            line_items=[LineItem(description="Item", quantity=0, rate=100, taxable_value=100)],
        )
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)

    def test_negative_line_item_values(self):
        inv = self._make_inv(
            line_items=[LineItem(description="Item", quantity=-5, rate=-100, taxable_value=-500)],
        )
        result = validate_invoice_for_xml(inv)
        assert isinstance(result, ValidationResult)


# ---------------------------------------------------------------------------
# 2. GSTIN VALIDATION — fuzz
# ---------------------------------------------------------------------------

class TestGstinFuzz:
    """GSTIN validation must handle any string without crashing."""

    FUZZ_INPUTS = [
        "", " ", "null", "undefined", "None", "0",
        "12345", "27AABCU1234D1Z", "27AABCU1234D1Z123",
        "XXAABCU1234D1Z1", "\x00\x01\x02",
        "A" * 200, "27AABCU1234F1ZP" * 10,
        json.dumps({"foo": "bar"}),
        "27" + "\u0000" * 13,
    ]

    @pytest.mark.parametrize("gstin", FUZZ_INPUTS)
    def test_invalid_gstins_never_crash(self, gstin):
        result = validate_gstin(gstin)
        assert isinstance(result, dict)
        assert "valid" in result

    def test_valid_gstin_always_passes(self):
        from gst_engine import _compute_gstin_checksum
        base = "27AABCU1234F1Z"
        gstin = base + _compute_gstin_checksum(base)
        result = validate_gstin(gstin)
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# 3. HALLUCINATION GUARD — fuzz
# ---------------------------------------------------------------------------

class TestHallucinationGuardFuzz:
    """compute_independent_confidence must never crash on any dict shape."""

    FUZZ_DATA = [
        {},
        {"vendor_name": ""},
        {"total_amount": float("nan")},
        {"line_items": [{"description": "", "taxable_value": float("inf")}]},
        {"vendor_gstin": "NOT_A_GSTIN", "invoice_date": "yesterday"},
        {"total_amount": -1, "total_taxable_value": -2, "total_tax": 999},
        {"line_items": [None, None, None]},
        {"invoice_date": ""},
        {"total_amount": 0, "total_taxable_value": 0},
        {"vendor_name": "A" * 10000, "vendor_gstin": "X" * 20},
    ]

    @pytest.mark.parametrize("data", FUZZ_DATA)
    def test_never_crashes(self, data):
        overall, scores, issues = compute_independent_confidence(data)
        assert isinstance(overall, float)
        assert 0 <= overall <= 1
        assert isinstance(scores, dict)
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# 4. OCR POST-PROCESSING — fuzz
# ---------------------------------------------------------------------------

class TestOcrPostprocFuzz:
    """fix_gstin must handle any string."""

    FUZZ_STRINGS = [
        "", "hello", "12345",
        "27AABCU1234F1ZP", "27AABCU1234D1Z",
        "2O25-O6-15", "INV OOl",
        "\x00\x01\x02", "A" * 5000,
    ]

    @pytest.mark.parametrize("s", FUZZ_STRINGS)
    def test_never_crashes(self, s):
        result = fix_gstin(s)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 5. PII REDACTION — fuzz
# ---------------------------------------------------------------------------

class TestPiiFuzz:
    """redact_pii must handle any input type without crashing."""

    FUZZ_INPUTS = [
        "", None, 123, 3.14, True, [],
        "My GSTIN is 27AABCU1234F1ZP",
        "Email: test@example.com",
        "Phone: 9876543210",
        "PAN: AABCU1234F",
        "Aadhaar: 1234 5678 9012",
        "IFSC: SBIN0001234",
        "No PII here",
        "A" * 5000,
    ]

    @pytest.mark.parametrize("s", FUZZ_INPUTS)
    def test_never_crashes(self, s):
        result = redact_pii(s)
        # Should return a string (or the original type if not string-like)
        assert result is not None or s is None


# ---------------------------------------------------------------------------
# 6. XML GENERATOR — edge-case invoices
# ---------------------------------------------------------------------------

class TestXmlGeneratorFuzz:
    """XML generation must not crash on unusual but valid invoices."""

    def _gen(self, **overrides):
        defaults = dict(
            invoice_number="FUZZ-001",
            invoice_date="2025-06-15",
            vendor_name="Fuzz Vendor",
            total_taxable_value=100,
            total_tax=18,
            total_amount=118,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[LineItem(description="Item", taxable_value=100, tax_rate=18)],
        )
        defaults.update(overrides)
        inv = StandardizedInvoice(**defaults)
        config = CompanyConfig()
        gen = TallyXmlGenerator(config, include_ledgers=False)
        return gen.generate(inv)

    def test_zero_tax(self):
        xml = self._gen(total_tax=0, total_amount=100)
        assert "<VOUCHER" in xml

    def test_zero_taxable_zero_tax(self):
        xml = self._gen(total_taxable_value=0, total_tax=0, total_amount=0)
        assert "<VOUCHER" in xml

    def test_empty_line_items(self):
        xml = self._gen(line_items=[], total_amount=500, total_taxable_value=500, total_tax=0)
        assert "<VOUCHER" in xml

    def test_extremely_large_amount(self):
        xml = self._gen(total_taxable_value=999999999, total_tax=179999999.82, total_amount=1179999998.82)
        assert "<VOUCHER" in xml

    def test_unicode_in_vendor(self):
        xml = self._gen(vendor_name="भारतीय कंपनी Ltd")
        assert "<VOUCHER" in xml

    def test_special_chars_in_description(self):
        xml = self._gen(
            line_items=[LineItem(description="Item <with> & \"special\" 'chars'", taxable_value=100, tax_rate=18)],
            total_taxable_value=100, total_tax=18, total_amount=118,
        )
        assert "<VOUCHER" in xml

    def test_all_voucher_types_produce_valid_xml(self):
        for vt in VoucherType:
            xml = self._gen(voucher_type=vt, total_tax=0, total_amount=100)
            assert "<VOUCHER" in xml, f"Missing VOUCHER element for {vt.value}"

    def test_journal_lines_reset(self):
        config = CompanyConfig()
        gen = TallyXmlGenerator(config, include_ledgers=False)
        inv1 = StandardizedInvoice(
            invoice_number="J1", invoice_date="2025-01-01",
            vendor_name="V1", total_amount=100, total_taxable_value=100,
            total_tax=0, voucher_type=VoucherType.PURCHASE,
            line_items=[LineItem(description="A", taxable_value=100, tax_rate=0)],
        )
        inv2 = StandardizedInvoice(
            invoice_number="J2", invoice_date="2025-01-01",
            vendor_name="V2", total_amount=200, total_taxable_value=200,
            total_tax=0, voucher_type=VoucherType.SALES,
            line_items=[LineItem(description="B", taxable_value=200, tax_rate=0)],
        )
        gen.generate(inv1)
        count1 = len(gen.journal_lines)
        gen.generate(inv2)
        assert len(gen.journal_lines) == count1, "journal lines accumulated across generates"


# ---------------------------------------------------------------------------
# 7. CLASSIFIER — fuzz
# ---------------------------------------------------------------------------

class TestClassifierFuzz:
    """classify_voucher_type must never crash."""

    FUZZ_INPUTS = [
        "", "tax invoice", "TAX INVOICE", "bill", "receipt",
        "proforma", "debit note", "credit note", "purchase order",
        "A" * 5000, "1234567890",
    ]

    @pytest.mark.parametrize("desc", FUZZ_INPUTS)
    def test_never_crashes(self, desc):
        result = classify_voucher_type({"description": desc, "line_items": [{"description": desc}]})
        assert isinstance(result, tuple)
        assert len(result) == 2
