"""Tests for HSN → GST rate mapping."""

import pytest
from hsn_rate_map import lookup_hsn, verify_hsn_rate, suggest_hsn, HSN_RATE_MAP


class TestHSNLookup:
    def test_computer_18_percent(self):
        info = lookup_hsn("8471")
        assert info is not None
        assert 18 in info["rates"]

    def test_petroleum_5_percent(self):
        info = lookup_hsn("2709")
        assert info is not None
        assert 5 in info["rates"]

    def test_cigarette_28_percent(self):
        info = lookup_hsn("2402")
        assert info is not None
        assert 28 in info["rates"]

    def test_milk_zero_percent(self):
        info = lookup_hsn("0401")
        assert info is not None
        assert 0 in info["rates"]

    def test_unknown_hsn(self):
        info = lookup_hsn("9999")
        assert info is None

    def test_prefix_match(self):
        # 8471 is exact match
        info = lookup_hsn("84710000")
        assert info is not None
        assert 18 in info["rates"]


class TestHSNRateVerification:
    def test_correct_rate(self):
        v = verify_hsn_rate("8471", 18)
        assert v["valid"] is True

    def test_wrong_rate(self):
        v = verify_hsn_rate("8471", 28)
        assert v["valid"] is False
        assert "typically has" in v["message"]

    def test_unknown_hsn(self):
        v = verify_hsn_rate("9999", 18)
        assert v["valid"] is True  # Can't verify, assume valid

    def test_multi_rate_hsn(self):
        # 0901 (coffee) can be 5% or 18%
        v = verify_hsn_rate("0901", 5)
        assert v["valid"] is True
        v = verify_hsn_rate("0901", 18)
        assert v["valid"] is True


class TestHSNSuggestion:
    def test_suggest_computer(self):
        results = suggest_hsn("laptop computer")
        assert len(results) > 0
        assert any(r["hsn"] == "8471" for r in results)

    def test_suggest_milk(self):
        results = suggest_hsn("milk and cream")
        assert len(results) > 0

    def test_suggest_unknown(self):
        results = suggest_hsn("xyzzy")
        assert len(results) == 0


class TestHSNRateMapIntegrity:
    def test_all_codes_are_4_digits(self):
        for code in HSN_RATE_MAP:
            assert len(code) == 4, f"HSN code '{code}' is not 4 digits"

    def test_all_have_rates(self):
        for code, info in HSN_RATE_MAP.items():
            assert len(info["rates"]) > 0, f"HSN code '{code}' has no rates"

    def test_all_rates_valid(self):
        valid_rates = {0, 0.1, 0.25, 3, 5, 12, 18, 28}
        for code, info in HSN_RATE_MAP.items():
            for rate in info["rates"]:
                assert rate in valid_rates, f"HSN '{code}' has invalid rate {rate}%"
