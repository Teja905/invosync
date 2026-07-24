"""Regression tests for company_config.py."""

from company_config import CompanyConfig, DEFAULT_LEDGER_MAPPINGS


class TestPurchaseLedgerMapping:
    def test_get_purchase_ledger_defaults_without_description(self):
        cfg = CompanyConfig()
        assert cfg.get_purchase_ledger("") == "Purchase"
        assert cfg.get_purchase_ledger() == "Purchase"

    def test_get_purchase_ledger_maps_known_descriptions(self):
        cfg = CompanyConfig()
        assert cfg.get_purchase_ledger("raw material") == "Purchase"
        assert cfg.get_purchase_ledger("Raw Material") == "Purchase"
        assert cfg.get_purchase_ledger("equipment") == "Fixed Assets"
        assert cfg.get_purchase_ledger("machinery") == "Fixed Assets"

    def test_get_purchase_ledger_falls_back_to_default(self):
        cfg = CompanyConfig()
        assert cfg.get_purchase_ledger("something completely unknown") == "Purchase"
        assert cfg.get_purchase_ledger("consulting fees") == "Professional Charges"
        assert cfg.get_purchase_ledger("rent") == "Rent Expenses"


class TestCompanyConfigDefaults:
    def test_default_state_code(self):
        cfg = CompanyConfig()
        assert cfg.state_code == "27"

    def test_default_company_name(self):
        cfg = CompanyConfig()
        assert cfg.company_name == "My Company"

    def test_user_config_overrides(self):
        cfg = CompanyConfig(user_config={
            "company_name": "Test Ltd",
            "company_state_code": "36",
            "purchase_ledger": "Purchases",
        })
        assert cfg.company_name == "Test Ltd"
        assert cfg.state_code == "36"
        assert cfg.default_purchase_ledger == "Purchases"
