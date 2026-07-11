"""Tests for OCR post-processing."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from ocr_postproc import (
    fix_gstin, fix_invoice_number, fix_date, fix_tax_rate,
    post_process_extracted, validate_invoice_math,
)


def test_fix_gstin_ocr_confusion():
    assert fix_gstin("27AAB-CU1234F1Z5") == "27AABCU1234F1Z5"


def test_fix_gstin_cleans_special_chars():
    result = fix_gstin("27 AAB CU1 234 F1Z 5")
    assert result == "27AABCU1234F1Z5"


def test_fix_invoice_number():
    assert fix_invoice_number("INV-001") == "1NV-001"
    assert fix_invoice_number("INV 001") == "1NV001"
    assert fix_invoice_number("lNV-001") == "1NV-001"


def test_fix_date_yyyy_mm_dd():
    assert fix_date("2024-01-15") == "2024-01-15"


def test_fix_date_dd_mm_yyyy():
    assert fix_date("15/01/2024") == "2024-01-15"


def test_fix_date_dd_mm_yy():
    result = fix_date("15-01-24")
    assert result == "2024-01-15"


def test_fix_date_yyyymmdd():
    assert fix_date("20240115") == "2024-01-15"


def test_fix_tax_rate_normal():
    assert fix_tax_rate(18) == 18


def test_fix_tax_rate_high_value():
    assert fix_tax_rate(180) == 18


def test_fix_tax_rate_none():
    assert fix_tax_rate(None) is None


def test_post_process_extracted():
    data = {
        "gstin": "27 AAB CU1234 F1Z 5",
        "invoice_number": "lNV-001",
        "date": "15/01/2024",
        "total_amount": 11800.0,
        "total_taxable_value": 10000.0,
        "vendor_name": "Test Vendor",
        "line_items": [
            {"description": "Item 1", "quantity": 0, "rate": 1000, "taxable_value": 10000, "tax_rate": 18},
        ],
    }
    result = post_process_extracted(data)
    assert result["gstin"] == "27AABCU1234F1Z5"
    assert result["invoice_number"] == "1NV-001"
    assert result["date"] == "2024-01-15"
    assert result["line_items"][0]["quantity"] == 1.0
    assert result["line_items"][0]["tax_rate"] == 18


def test_validate_invoice_math_ok():
    data = {
        "total_amount": 11800.0,
        "line_items": [
            {"description": "Test", "taxable_value": 10000.0, "cgst": 900.0, "sgst": 900.0, "igst": 0},
        ],
    }
    issues = validate_invoice_math(data)
    assert len(issues) == 0


def test_validate_invoice_math_mismatch():
    data = {
        "total_amount": 10000.0,
        "line_items": [
            {"description": "Test", "taxable_value": 10000.0, "cgst": 900.0, "sgst": 900.0, "igst": 0},
        ],
    }
    issues = validate_invoice_math(data)
    assert len(issues) > 0


if __name__ == "__main__":
    test_fix_gstin_ocr_confusion()
    test_fix_gstin_cleans_special_chars()
    test_fix_invoice_number()
    test_fix_date_yyyy_mm_dd()
    test_fix_date_dd_mm_yyyy()
    test_fix_date_dd_mm_yy()
    test_fix_date_yyyymmdd()
    test_fix_tax_rate_normal()
    test_fix_tax_rate_high_value()
    test_fix_tax_rate_none()
    test_post_process_extracted()
    test_validate_invoice_math_ok()
    test_validate_invoice_math_mismatch()
    print("All OCR post-processing tests passed!")
