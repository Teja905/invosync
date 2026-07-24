"""Tests for core/hallucination_guard.py — independent confidence scoring.

Covers: math integrity, GSTIN↔vendor cross-check, date sanity, field presence,
line-item health, amount ranges, and the weakest-link overall score.
"""

from core.hallucination_guard import compute_independent_confidence


class TestMathIntegrity:
    def test_perfect_math(self):
        data = {
            "line_items": [{"description": "Item A", "taxable_value": 100, "tax_rate": 18}],
            "total_taxable_value": 100,
            "total_tax": 18,
            "total_amount": 118,
            "vendor_name": "ABC Traders",
            "invoice_date": "2026-06-15",
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["math_integrity"] == 1.0
        assert overall >= 0.7

    def test_line_items_dont_match_header(self):
        data = {
            "line_items": [
                {"description": "Item A", "taxable_value": 100, "tax_rate": 18},
                {"description": "Item B", "taxable_value": 200, "tax_rate": 5},
            ],
            "total_taxable_value": 100,
            "total_tax": 18,
            "total_amount": 118,
            "vendor_name": "ABC Traders",
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["math_integrity"] < 0.5
        assert any("sum" in i.lower() for i in issues)

    def test_no_line_items_with_total(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_taxable_value": 100,
            "total_tax": 18,
            "total_amount": 118,
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["math_integrity"] == 0.5

    def test_no_line_items_zero_total(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_taxable_value": 0,
            "total_tax": 0,
            "total_amount": 0,
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["math_integrity"] == 0.0

    def test_taxable_zero_but_total_positive(self):
        data = {
            "line_items": [{"description": "Item A", "taxable_value": 100, "tax_rate": 18}],
            "total_taxable_value": 0,
            "total_tax": 18,
            "total_amount": 118,
            "vendor_name": "ABC Traders",
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["math_integrity"] <= 0.3

    def test_tax_plus_taxable_doesnt_match_total(self):
        data = {
            "line_items": [{"description": "Item A", "taxable_value": 100, "tax_rate": 18}],
            "total_taxable_value": 100,
            "total_tax": 18,
            "total_amount": 200,
            "vendor_name": "ABC Traders",
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("math_integrity", 1.0) <= 0.5
        assert any("tax" in i.lower() and "total" in i.lower() for i in issues)

    def test_minor_math_drift(self):
        data = {
            "line_items": [{"description": "Item A", "taxable_value": 100.05, "tax_rate": 18}],
            "total_taxable_value": 100,
            "total_tax": 18,
            "total_amount": 118,
            "vendor_name": "ABC Traders",
            "invoice_date": "2026-06-15",
        }
        overall, scores, issues = compute_independent_confidence(data)
        # 5 paise diff is within 0.10 tolerance — no penalty
        assert scores["math_integrity"] == 1.0


class TestGstinSanity:
    def test_valid_gstin(self):
        data = {"vendor_name": "ABC Traders", "vendor_gstin": "27AABCU1234F1ZP"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["gstin_validity"] == 1.0

    def test_missing_gstin(self):
        data = {"vendor_name": "ABC Traders", "vendor_gstin": ""}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["gstin_validity"] == 0.7

    def test_invalid_gstin_format(self):
        data = {"vendor_name": "ABC Traders", "vendor_gstin": "ABC123"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("gstin_validity", 1.0) == 0.0

    def test_gstin_pan_matches_vendor_initials(self):
        # GSTIN 27AABCU1234F1ZP → PAN = AABCU1234F → pan[3] = 'C'
        # Vendor "C Unlimited Traders" → initials = "CUT" → 'C' is in 'CUT' → no penalty
        data = {"vendor_name": "C Unlimited Traders", "vendor_gstin": "27AABCU1234F1ZP"}
        overall, scores, issues = compute_independent_confidence(data)
        assert "gstin_name_match" not in scores  # No penalty — initials match

    def test_gstin_pan_mismatches_vendor_initials(self):
        # GSTIN 27AABCU1234F1ZP → PAN = AABCU1234F → pan[3] = 'C'
        # Vendor "XYZ Corporation" → initials = "XC" → 'C' IS in 'XC' → matches!
        # Need a vendor where none of the initials match pan[3]
        data = {"vendor_name": "D E F Corporation", "vendor_gstin": "27AABCU1234F1ZP"}
        overall, scores, issues = compute_independent_confidence(data)
        assert "gstin_name_match" in scores
        assert scores["gstin_name_match"] <= 0.5

    def test_short_vendor_name_gstin_check(self):
        # Single-char vendor won't trigger the name match (no initial to compare)
        # But it will get a low vendor_presence score instead
        data = {"vendor_name": "A", "vendor_gstin": "27AABCU1234F1ZP", "invoice_date": "2026-06-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["vendor_presence"] == 0.3  # Short name penalty


class TestDateSanity:
    def test_valid_recent_date(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "2026-06-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 1.0

    def test_dd_mm_yyyy_format(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "15/06/2026"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 1.0

    def test_future_date(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "2099-01-01"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 0.0

    def test_pre_gst_date(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "2016-01-01"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 0.0

    def test_missing_date(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": ""}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 0.5

    def test_unrecognised_date_format(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "Jan 15 2026"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] <= 0.3

    def test_invalid_calendar_date(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "2026-02-30"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 0.0

    def test_old_but_valid_date(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "2019-03-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["date_sanity"] == 0.5


class TestVendorPresence:
    def test_valid_vendor(self):
        data = {"vendor_name": "ABC Traders", "invoice_date": "2026-06-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["vendor_presence"] == 1.0

    def test_empty_vendor(self):
        data = {"vendor_name": "", "invoice_date": "2026-06-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["vendor_presence"] == 0.0

    def test_generic_vendor(self):
        data = {"vendor_name": "vendor", "invoice_date": "2026-06-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["vendor_presence"] == 0.1

    def test_short_vendor(self):
        data = {"vendor_name": "AB", "invoice_date": "2026-06-15"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["vendor_presence"] == 0.3


class TestLineItems:
    def test_all_items_valid(self):
        data = {
            "vendor_name": "ABC Traders",
            "line_items": [
                {"description": "Item A", "taxable_value": 100, "tax_rate": 18},
                {"description": "Item B", "taxable_value": 200, "tax_rate": 5},
            ],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["line_item_health"] == 1.0

    def test_no_line_items(self):
        data = {"vendor_name": "ABC Traders"}
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["line_item_health"] == 0.3

    def test_all_empty_descriptions(self):
        data = {
            "vendor_name": "ABC Traders",
            "line_items": [
                {"description": "", "taxable_value": 100},
                {"description": "", "taxable_value": 200},
            ],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["line_item_health"] == 0.0
        assert any("empty description" in i.lower() for i in issues)

    def test_some_empty_descriptions(self):
        data = {
            "vendor_name": "ABC Traders",
            "line_items": [
                {"description": "", "taxable_value": 100},
                {"description": "Item B", "taxable_value": 200},
            ],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["line_item_health"] == 0.5

    def test_all_zero_value(self):
        data = {
            "vendor_name": "ABC Traders",
            "line_items": [
                {"description": "Item A", "taxable_value": 0},
                {"description": "Item B", "taxable_value": 0},
            ],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["line_item_health"] == 0.0


class TestAmountRanges:
    def test_normal_amounts(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": 118,
            "total_taxable_value": 100,
            "total_tax": 18,
            "freight": 0,
            "tds_amount": 0,
            "line_items": [{"description": "A", "taxable_value": 100, "tax_rate": 18}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("amount_ranges", 1.0) >= 0.5

    def test_negative_total(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": -100,
            "total_taxable_value": 100,
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("amount_ranges", 1.0) == 0.0

    def test_taxable_exceeds_total(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": 100,
            "total_taxable_value": 500,
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("amount_ranges", 1.0) == 0.0

    def test_tax_exceeds_50pct_of_taxable(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": 200,
            "total_taxable_value": 100,
            "total_tax": 60,
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("amount_ranges", 1.0) == 0.0

    def test_invalid_gst_rate(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": 200,
            "total_taxable_value": 100,
            "line_items": [{"description": "A", "taxable_value": 100, "tax_rate": 37}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores.get("amount_ranges", 1.0) == 0.0

    def test_high_freight_warning(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": 1000,
            "total_taxable_value": 800,
            "freight": 600,
            "line_items": [{"description": "A", "taxable_value": 800, "tax_rate": 18}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert any("freight" in i.lower() for i in issues)

    def test_high_tds_warning(self):
        data = {
            "vendor_name": "ABC Traders",
            "total_amount": 1000,
            "total_taxable_value": 800,
            "tds_amount": 300,
            "line_items": [{"description": "A", "taxable_value": 800, "tax_rate": 18}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert any("tds" in i.lower() for i in issues)


class TestOverallScore:
    def test_overall_is_minimum_of_all_scores(self):
        data = {
            "vendor_name": "ABC Cable Traders",
            "invoice_date": "2026-06-15",
            "vendor_gstin": "27AABCU1234F1ZP",
            "total_amount": 118,
            "total_taxable_value": 100,
            "total_tax": 18,
            "line_items": [{"description": "Item A", "taxable_value": 100, "tax_rate": 18}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert overall == min(scores.values())
        assert overall >= 0.7  # All checks should pass

    def test_single_bad_score_drags_overall(self):
        data = {
            "vendor_name": "",  # Critical failure
            "invoice_date": "2026-06-15",
            "total_amount": 118,
            "total_taxable_value": 100,
            "total_tax": 18,
            "line_items": [{"description": "Item A", "taxable_value": 100, "tax_rate": 18}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert overall == 0.0  # Vendor empty = hard block

    def test_empty_data_returns_scores(self):
        data = {}
        overall, scores, issues = compute_independent_confidence(data)
        assert isinstance(overall, float)
        assert 0 <= overall <= 1

    def test_missing_vendor_gstin_fallsback_to_gstin(self):
        data = {
            "vendor_name": "ABC Traders",
            "gstin": "27AABCU1234F1ZP",
            "invoice_date": "2026-06-15",
            "total_amount": 100,
            "total_taxable_value": 100,
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert scores["gstin_validity"] == 1.0

    def test_ai_says_high_but_independent_low(self):
        """AI self-confidence says 0.95 but math is wrong — independent should be low."""
        data = {
            "confidence": 0.95,
            "vendor_name": "ABC Traders",
            "invoice_date": "2026-06-15",
            "total_taxable_value": 100,
            "total_tax": 18,
            "total_amount": 9999,
            "line_items": [{"description": "Item A", "taxable_value": 100, "tax_rate": 18}],
        }
        overall, scores, issues = compute_independent_confidence(data)
        assert overall <= 0.5
        assert overall != data["confidence"]
