"""Validation rules: vendor name must be present and reasonable."""

import pytest
from validation_layer import validate_invoice_for_xml
from schemas import StandardizedInvoice, VoucherType


def test_vendor_name_required():
    """Invoice without vendor name must fail validation with blocking error."""
    inv = StandardizedInvoice(
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        vendor_name="",
        total_amount=1000.0,
        voucher_type=VoucherType.PURCHASE,
    )
    result = validate_invoice_for_xml(inv)
    assert not result.passed, "Empty vendor name must fail"
    error_text = " ".join(result.errors).lower()
    assert "vendor name" in error_text, f"Expected 'vendor name' in errors: {result.errors}"
    assert result.blocking_errors, "Empty vendor name must be a blocking error"


def test_vendor_name_valid_characters():
    """Standard vendor names with special chars should pass."""
    inv = StandardizedInvoice(
        vendor_name="ABC Corp & Sons Pvt Ltd",
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        total_amount=1000.0,
        voucher_type=VoucherType.PURCHASE,
    )
    result = validate_invoice_for_xml(inv)
    # Should not fail on vendor name (may fail on other mandatory fields)
    vendor_errors = [e for e in result.errors if "vendor" in e.lower()]
    assert not vendor_errors, f"Vendor-specific errors: {vendor_errors}"


def test_vendor_name_whitespace_only():
    """Whitespace-only vendor name should be treated as empty."""
    inv = StandardizedInvoice(
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        vendor_name="   ",
        total_amount=1000.0,
        voucher_type=VoucherType.PURCHASE,
    )
    result = validate_invoice_for_xml(inv)
    error_text = " ".join(result.errors).lower()
    assert "vendor name" in error_text


def test_vendor_name_special_chars_xml_safe():
    """Vendor names with XML-special chars should be escaped in output."""
    # The validation should pass; XML escaping happens in generator
    inv = StandardizedInvoice(
        vendor_name="Acme & Sons <Printers>",
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        total_amount=1000.0,
        voucher_type=VoucherType.PURCHASE,
    )
    result = validate_invoice_for_xml(inv)
    vendor_errors = [e for e in result.errors if "vendor" in e.lower()]
    assert not vendor_errors, f"XML-special chars in name should not cause validation errors: {vendor_errors}"
