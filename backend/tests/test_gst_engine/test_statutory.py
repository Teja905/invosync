"""GST engine statutory tests: GSTIN validation, rate validation, tax computation."""

from gst_engine import (
    validate_gstin, validate_tax_rate, compute_gst_entries, compute_tax_from_items,
    _compute_gstin_checksum, _verify_gstin_checksum,
    aggregate_and_round_slab_taxes,
)
from schemas import GSTType, GST_STATE_CODES


class TestGSTINValidationEdgeCases:

    def test_none_gstin(self):
        result = validate_gstin(None)
        assert result["valid"] is False
        assert "empty" in result["message"].lower()

    def test_empty_gstin(self):
        result = validate_gstin("")
        assert result["valid"] is False

    def test_whitespace_gstin(self):
        result = validate_gstin("   ")
        assert result["valid"] is False

    def test_all_valid_states(self):
        """Every valid GST state code should be accepted."""
        for code in GST_STATE_CODES:
            pan_part = f"{code}ABCDE1234F1Z"
            gstin = pan_part + _compute_gstin_checksum(pan_part)
            result = validate_gstin(gstin)
            assert result["valid"], f"State {code} failed: {result['message']}"

    def test_invalid_characters_in_gstin(self):
        result = validate_gstin("27AABCU1234F1P@")
        assert result["valid"] is False

    def test_gstin_with_lowercase(self):
        pan_part = "27abcde1234f1z"
        checksum = _compute_gstin_checksum(pan_part.upper())
        gstin = pan_part + checksum
        result = validate_gstin(gstin)
        assert result["valid"] is True, f"Lowercase GSTIN should be valid: {result}"

    def test_checksum_verification(self):
        """_verify_gstin_checksum should match the computed checksum."""
        base = "27AABCU1234F1Z"
        cd = _compute_gstin_checksum(base)
        gstin = base + cd
        assert _verify_gstin_checksum(gstin), f"Checksum verification failed for {gstin}"
        assert not _verify_gstin_checksum(gstin[:-1] + "X"), "Wrong checksum should fail"

    def test_pan_validation_rejects_invalid(self):
        """GSTIN with invalid PAN structure should be rejected."""
        gstin = "2712345678901Z" + _compute_gstin_checksum("2712345678901Z")
        result = validate_gstin(gstin)
        assert result["valid"] is False


class TestRateValidationEdgeCases:

    def test_zero_rate_accepted(self):
        result = validate_tax_rate(0)
        assert result["valid"] is True

    def test_eighteen_accepted(self):
        result = validate_tax_rate(18)
        assert result["valid"] is True

    def test_mid_slab_rounded(self):
        result = validate_tax_rate(17.5)
        assert result["valid"] is True
        assert result.get("corrected_rate") == 18

    def test_near_slab_upper(self):
        result = validate_tax_rate(28.3)
        assert result["valid"] is True
        assert result.get("corrected_rate") == 28

    def test_far_from_slab_rejected(self):
        """Rate 1% away from any slab should be rejected."""
        result = validate_tax_rate(19)
        assert result["valid"] is False

    def test_negative_rate_rejected(self):
        result = validate_tax_rate(-5)
        assert result["valid"] is False

    def test_gstin_with_leading_trailing_spaces(self):
        """Leading/trailing spaces should be stripped by validate_gstin."""
        clean = "27AABCU1234F1Z" + _compute_gstin_checksum("27AABCU1234F1Z")
        result = validate_gstin(f"  {clean}  ")
        assert result["valid"] is True, f"GSTIN with outer spaces should be cleaned: {result}"


class TestCGSTSGSTSplitAccuracy:

    def test_even_split(self):
        """18% on Rs.1000 → Rs.90 CGST + Rs.90 SGST."""
        entries = compute_gst_entries(1000.0, 18, GSTType.CGST_SGST)
        assert len(entries) == 2
        assert any(e.type == "cgst" and e.amount == 90.0 for e in entries)
        assert any(e.type == "sgst" and e.amount == 90.0 for e in entries)

    def test_odd_split_resolved(self):
        """5% on Rs.199.99 — uneven split resolved (1-paisa rule)."""
        entries = compute_gst_entries(199.99, 5, GSTType.CGST_SGST)
        assert len(entries) == 2
        total = sum(e.amount for e in entries)
        assert abs(total - 10.0) < 0.01, f"Expected total tax Rs.10.00, got Rs.{total:.2f}"

    def test_igst_single_entry(self):
        """IGST on Rs.1000 at 18% → single Rs.180 entry."""
        entries = compute_gst_entries(1000.0, 18, GSTType.IGST)
        assert len(entries) == 1
        assert entries[0].type == "igst"
        assert entries[0].amount == 180.0

    def test_zero_taxable_no_entries(self):
        entries = compute_gst_entries(0.0, 18, GSTType.IGST)
        assert len(entries) == 0

    def test_round_off_integrity(self):
        """Sum of CGST + SGST must always equal total tax at slab level."""
        items = [
            {"taxable_value": 147.50, "tax_rate": 18},
            {"taxable_value": 252.00, "tax_rate": 18},
            {"taxable_value": 89.99, "tax_rate": 5},
            {"taxable_value": 310.00, "tax_rate": 5},
        ]
        slab_results = aggregate_and_round_slab_taxes(items, GSTType.CGST_SGST)
        for rate, result in slab_results.items():
            total = result.get("cgst_amount", 0) + result.get("sgst_amount", 0)
            expected_total = round(sum(
                item["taxable_value"] * rate / 100
                for item in items if abs(item["tax_rate"] - rate) < 0.01
            ), 2)
            assert abs(total - expected_total) < 0.02, (
                f"Slab {rate}: CGST+SGST Rs.{total:.2f} != expected Rs.{expected_total:.2f}"
            )


class TestTaxFromItems:

    def test_multi_slab_aggregation(self):
        """Multiple line items at different rates produce correct tax entries."""
        items = [
            {"taxable_value": 1000.0, "tax_rate": 18, "description": "Laptop"},
            {"taxable_value": 500.0, "tax_rate": 5, "description": "Books"},
        ]
        entries = compute_tax_from_items(items, GSTType.CGST_SGST)
        assert len(entries) >= 2  # at least CGST+SGST
        cgst = [e for e in entries if e.type == "cgst"]
        sgst = [e for e in entries if e.type == "sgst"]
        assert len(cgst) >= 1
        assert len(sgst) >= 1
        total_cgst = sum(e.amount for e in cgst)
        total_sgst = sum(e.amount for e in sgst)
        expected_total_tax = (1000 * 0.18 + 500 * 0.05)
        assert abs(total_cgst + total_sgst - expected_total_tax) < 0.02
