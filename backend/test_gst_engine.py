"""Tests for the GST Engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from gst_engine import (
    validate_gstin, determine_gst_type, validate_tax_rate,
    compute_gst_entries, compute_tax_from_items, validate_tax_structure,
)
from schemas import GSTType, TaxEntry


def test_gstin_valid():
    result = validate_gstin("27AABCU1234F1ZP")
    assert result["valid"] is True, f"Expected valid, got: {result}"
    assert result["state_code"] == "27"
    assert result["state_name"] == "Maharashtra"


def test_gstin_invalid_format():
    result = validate_gstin("INVALID")
    assert result["valid"] is False


def test_gstin_empty():
    result = validate_gstin("")
    assert result["valid"] is False


def test_gstin_wrong_state_code():
    result = validate_gstin("99AABCU1234F1ZP")
    assert result["valid"] is False


def test_determine_gst_type_intra():
    gst_type, is_interstate = determine_gst_type("27ABCD5678G2ZZ", "27ABCD5678G2ZZ", "27")
    assert gst_type == GSTType.CGST_SGST
    assert is_interstate is False


def test_determine_gst_type_inter():
    gst_type, is_interstate = determine_gst_type("29ABCD1234F1ZM", "27ABCD5678G2ZZ", "27")
    assert gst_type == GSTType.IGST
    assert is_interstate is True


def test_determine_gst_type_no_buyer_gstin():
    gst_type, is_interstate = determine_gst_type("27ABCD1234F1Z5", "", "27")
    assert gst_type == GSTType.CGST_SGST
    assert is_interstate is False


def test_tax_rate_valid():
    for rate in [0, 5, 12, 18, 28]:
        result = validate_tax_rate(rate)
        assert result["valid"] is True, f"Rate {rate} should be valid"


def test_tax_rate_invalid():
    result = validate_tax_rate(7)
    assert result["valid"] is False


def test_tax_rate_rounding():
    result = validate_tax_rate(17.8)
    assert result["valid"] is True
    assert result["corrected_rate"] == 18


def test_compute_gst_cgst_sgst():
    entries = compute_gst_entries(10000, 18, GSTType.CGST_SGST)
    assert len(entries) == 2
    cgst = [e for e in entries if e.type == "cgst"][0]
    sgst = [e for e in entries if e.type == "sgst"][0]
    assert cgst.amount == 900.0
    assert sgst.amount == 900.0
    assert cgst.rate == 9.0
    assert sgst.rate == 9.0


def test_compute_gst_igst():
    entries = compute_gst_entries(10000, 18, GSTType.IGST)
    assert len(entries) == 1
    assert entries[0].type == "igst"
    assert entries[0].amount == 1800.0
    assert entries[0].rate == 18.0


def test_compute_tax_from_items():
    items = [
        {"description": "Item A", "taxable_value": 5000, "tax_rate": 18},
        {"description": "Item B", "taxable_value": 3000, "tax_rate": 12},
    ]
    entries = compute_tax_from_items(items, GSTType.CGST_SGST)
    total_tax = sum(e.amount for e in entries)
    expected_cgst = (5000 * 9 / 100) + (3000 * 6 / 100)
    expected_sgst = (5000 * 9 / 100) + (3000 * 6 / 100)
    assert abs(total_tax - (expected_cgst + expected_sgst)) < 0.01


def test_validate_tax_structure_cgst_sgst():
    taxes = [
        TaxEntry(name="CGST", rate=9, amount=900, type="cgst"),
        TaxEntry(name="SGST", rate=9, amount=900, type="sgst"),
    ]
    issues = validate_tax_structure(taxes)
    assert len(issues) == 0


def test_validate_tax_structure_cgst_only():
    taxes = [
        TaxEntry(name="CGST", rate=9, amount=900, type="cgst"),
    ]
    issues = validate_tax_structure(taxes)
    assert len(issues) > 0


def test_validate_tax_structure_cgst_igst_conflict():
    taxes = [
        TaxEntry(name="CGST", rate=9, amount=900, type="cgst"),
        TaxEntry(name="IGST", rate=18, amount=1800, type="igst"),
    ]
    issues = validate_tax_structure(taxes)
    assert any("IGST" in i for i in issues)


if __name__ == "__main__":
    test_gstin_valid()
    test_gstin_invalid_format()
    test_gstin_empty()
    test_gstin_wrong_state_code()
    test_determine_gst_type_intra()
    test_determine_gst_type_inter()
    test_determine_gst_type_no_buyer_gstin()
    test_tax_rate_valid()
    test_tax_rate_invalid()
    test_tax_rate_rounding()
    test_compute_gst_cgst_sgst()
    test_compute_gst_igst()
    test_compute_tax_from_items()
    test_validate_tax_structure_cgst_sgst()
    test_validate_tax_structure_cgst_only()
    test_validate_tax_structure_cgst_igst_conflict()
    print("All GST engine tests passed!")
