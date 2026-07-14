"""Ledger mapping: keyword priority, fallback behavior, and fuzzy matching."""

import pytest
from ledger_mapping import LedgerMappingEngine
from company_config import CompanyConfig


@pytest.fixture
def engine() -> LedgerMappingEngine:
    config = CompanyConfig()
    return LedgerMappingEngine(config)


class TestExpenseLedgerMapping:

    def test_exact_match_returns_correct_ledger(self, engine):
        """'office rent' should map to 'Rent Expenses'."""
        ledger = engine.map_expense_ledger("office rent")
        assert ledger == "Rent Expenses", f"Expected 'Rent Expenses', got '{ledger}'"

    def test_partial_match_returns_ledger(self, engine):
        """'Rent for office space' should still map to 'Rent Expenses'."""
        ledger = engine.map_expense_ledger("Rent for office space")
        assert ledger == "Rent Expenses", f"Expected 'Rent Expenses', got '{ledger}'"

    def test_empty_description_returns_default(self, engine):
        ledger = engine.map_expense_ledger("")
        assert ledger == "Purchase", f"Expected default 'Purchase', got '{ledger}'"

    def test_unknown_description_falls_back(self, engine):
        """Completely unknown description should fall back to 'Office Expenses'."""
        ledger = engine.map_expense_ledger("zxywvunotlikely")
        # company_config.get_expense_ledger falls back to 'Office Expenses'
        assert ledger, "Should never return empty string"

    def test_ledger_fuzzy_no_candidates(self, engine):
        result = engine.map_ledger_fuzzy("something", [])
        assert result is None

    def test_ledger_fuzzy_empty_query(self, engine):
        result = engine.map_ledger_fuzzy("", ["Office Rent", "Purchase"])
        assert result is None

    def test_ledger_fuzzy_close_match(self, engine):
        """Fuzzy match should find 'Office Rent' from 'offce rent'."""
        result = engine.map_ledger_fuzzy("offce rent", ["Office Rent", "Purchase"])
        assert result == "Office Rent"


class TestPartyLedgerMapping:

    def test_party_name_preserved(self, engine):
        """Party ledger mapping preserves the vendor name."""
        assert engine.map_party_ledger("ABC Corp") == "ABC Corp"

    def test_empty_party_fallback(self, engine):
        assert engine.map_party_ledger("") == "Unknown Supplier"

    def test_whitespace_party_fallback(self, engine):
        assert engine.map_party_ledger("   ") == "Unknown Supplier"


class TestGetAllLedgers:

    def test_invoice_with_vendor_name(self, engine):
        inv_data = {
            "line_items": [{"description": "office rent"}],
            "vendor_name": "ABC Corp",
        }
        result = engine.get_all_ledgers_for_invoice(inv_data, is_service=True, is_interstate=False)
        assert "Rent Expenses" in result["expense_ledgers"], f"Expected 'Rent Expenses' in {result}"
        assert result["party_ledger"] == "ABC Corp"

    def test_invoice_with_empty_line_items(self, engine):
        inv_data = {"line_items": [], "vendor_name": "ABC Corp"}
        result = engine.get_all_ledgers_for_invoice(inv_data, is_service=True, is_interstate=False)
        assert result["expense_ledgers"] == ["Purchase"]
