"""Tests for context_classifier.py — capital vs revenue classification."""

import pytest
from context_classifier import ContextClassifier, CAPITAL_AMOUNT_THRESHOLD
from rules_engine import RulesEngine, MatchType


@pytest.fixture
def classifier():
    return ContextClassifier()


class TestCapitalClassification:
    def test_laptop_high_amount_is_capital(self, classifier):
        result = classifier.classify("Dell Latitude 5540 Laptop", amount=75000)
        assert result.context_type == "capital"
        assert result.ledger_name == "Fixed Assets"
        assert result.confidence >= 0.85

    def test_laptop_low_amount_is_revenue(self, classifier):
        result = classifier.classify("Dell Mouse", amount=450)
        assert result.context_type == "revenue"

    def test_machinery_high_amount_is_capital(self, classifier):
        result = classifier.classify("CNC Machine", amount=500000)
        assert result.context_type == "capital"
        assert result.ledger_name == "Fixed Assets"

    def test_vehicle_high_amount_is_capital(self, classifier):
        result = classifier.classify("Maruti Swift Car", amount=600000)
        assert result.context_type == "capital"

    def test_furniture_high_amount_is_capital(self, classifier):
        result = classifier.classify("Executive Office Chair Furniture", amount=35000)
        assert result.context_type == "capital"

    def test_server_high_amount_is_capital(self, classifier):
        result = classifier.classify("Dell PowerEdge Server", amount=120000)
        assert result.context_type == "capital"


class TestRevenueClassification:
    def test_repairs_always_revenue(self, classifier):
        result = classifier.classify("AC Repair Services", amount=100000)
        assert result.context_type == "revenue"
        assert "Repairs" in result.ledger_name or "Maintenance" in result.ledger_name

    def test_maintenance_always_revenue(self, classifier):
        result = classifier.classify("Annual Maintenance Contract", amount=100000)
        assert result.context_type == "revenue"

    def test_rent_always_revenue(self, classifier):
        result = classifier.classify("Office Rent", amount=50000)
        assert result.context_type == "revenue"
        assert "Rent" in result.ledger_name

    def test_salary_always_revenue(self, classifier):
        result = classifier.classify("Monthly Salary", amount=50000)
        assert result.context_type == "revenue"

    def test_freight_always_revenue(self, classifier):
        result = classifier.classify("Logistics Freight", amount=10000)
        assert result.context_type == "revenue"

    def test_software_license_revenue(self, classifier):
        result = classifier.classify("Software License Annual", amount=5000)
        assert result.context_type == "revenue"
        assert "Software" in result.ledger_name or "Subscription" in result.ledger_name


class TestBoundaryCases:
    def test_capital_below_threshold_is_revenue(self, classifier):
        result = classifier.classify("Laptop", amount=20000)
        assert result.context_type == "revenue"

    def test_exact_threshold_is_capital(self, classifier):
        result = classifier.classify("Laptop", amount=CAPITAL_AMOUNT_THRESHOLD)
        assert result.context_type == "capital"

    def test_empty_description(self, classifier):
        result = classifier.classify("", amount=50000)
        assert result.ledger_name == ""
        assert result.confidence == 0.0

    def test_whitespace_description(self, classifier):
        result = classifier.classify("   ", amount=50000)
        assert result.ledger_name == ""
        assert result.confidence == 0.0

    def test_unknown_description_falls_back(self, classifier):
        result = classifier.classify("Random Unknown Expense XYZ", amount=1000)
        assert result.context_type == "revenue"


class TestConfidenceAndSuggestions:
    def test_capital_has_high_confidence(self, classifier):
        result = classifier.classify("Industrial Machinery", amount=75000)
        assert result.confidence >= 0.85

    def test_result_has_explanation(self, classifier):
        result = classifier.classify("Laptop", amount=75000)
        assert result.explanation
        assert "capital" in result.explanation.lower() or "Fixed Asset" in result.explanation

    def test_revenue_has_suggestions(self, classifier):
        result = classifier.classify("Repairs", amount=10000)
        assert result.suggestions or result.ledger_name


class TestIntegrationWithRulesEngine:
    def test_known_keyword_overrides_amount(self, classifier):
        """Revenue keywords should always return revenue, even with high amount."""
        result = classifier.classify("Computer Repair", amount=100000)
        assert result.context_type == "revenue"
        assert "Repairs" in result.ledger_name or "Maintenance" in result.ledger_name

    def test_unknown_keyword_amount_triggers_capital(self, classifier):
        """Unknown item with high amount → capital."""
        result = classifier.classify("Specialized Equipment XYZ", amount=75000)
        assert result.context_type == "capital"
        assert result.ledger_name == "Fixed Assets"
