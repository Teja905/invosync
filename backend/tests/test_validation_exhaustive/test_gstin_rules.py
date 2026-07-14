"""Validation rules: GSTIN format, checksum, and state code validation."""

import pytest
from validation_layer import validate_invoice_for_xml
from schemas import StandardizedInvoice, VoucherType
from gst_engine import _compute_gstin_checksum, validate_gstin


def test_gstin_valid_computed_checksum():
    """GSTIN with algorithmically correct checksum must pass."""
    gstin = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
    result = validate_gstin(gstin)
    assert result["valid"] is True, f"Valid GSTIN rejected: {result['message']}"


def test_gstin_invalid_checksum():
    """GSTIN with wrong last character must fail checksum."""
    gstin = "29AACCT3705E1ZJ"  # Correct checksum is different — use any deterministic wrong one
    # Force a wrong checksum by taking a real valid one and flipping last char
    valid = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
    wrong = valid[:-1] + ("K" if valid[-1] != "K" else "L")
    result = validate_gstin(wrong)
    assert result["valid"] is False
    assert "checksum" in result["message"].lower()


def test_gstin_wrong_length():
    """GSTIN must be exactly 15 characters."""
    gstin = "27AABCU1234D"  # 12 chars
    result = validate_gstin(gstin)
    assert result["valid"] is False
    assert "format" in result["message"].lower()


def test_gstin_invalid_state_code():
    """GSTIN with non-existent state code must be rejected."""
    # State codes 01-37 are valid; 99, 00, 38+ are not
    gstin = "99AABCU1234D1ZJ"
    result = validate_gstin(gstin)
    assert result["valid"] is False
    assert "state code" in result["message"].lower()


def test_gstin_lowercase_accepted():
    """Lowercase GSTIN should uppercase and pass."""
    valid = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
    result = validate_gstin(valid.lower())
    assert result["valid"] is True, "Lowercase GSTIN should be accepted"


def test_gstin_with_spaces_cleaned():
    """GSTIN with embedded spaces should be rejected (not cleaned by validate_gstin itself)."""
    valid = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
    spaced = valid[:5] + " " + valid[5:]
    result = validate_gstin(spaced)
    assert result["valid"] is False, "Spaces in GSTIN should not pass raw validation"


def test_gstin_validation_in_invoice_flow():
    """Invoice with invalid GSTIN must produce validation errors."""
    inv = StandardizedInvoice(
        vendor_name="Test Vendor",
        vendor_gstin="27AABCU1234D1ZZ",  # bad checksum
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        total_amount=1000.0,
        voucher_type=VoucherType.PURCHASE,
    )
    result = validate_invoice_for_xml(inv)
    gstin_errors = [e for e in result.errors if "gstin" in e.lower()]
    assert gstin_errors, f"Expected GSTIN errors but none found: {result.errors}"
