"""Company configuration system for ledger mappings, defaults, and tax settings."""

import json
import os
from typing import Optional

from schemas import VoucherType


DEFAULT_LEDGER_MAPPINGS = {
    "professional services": "Professional Charges",
    "professional fees": "Professional Charges",
    "consultation fees": "Professional Charges",
    "consulting fees": "Professional Charges",
    "consulting": "Professional Charges",
    "development": "Professional Charges",
    "audit fees": "Audit Expenses",
    "audit": "Audit Expenses",
    "cloud hosting": "Software Expenses",
    "hosting": "Software Expenses",
    "server": "Software Expenses",
    "software": "Software Expenses",
    "software license": "Software Expenses",
    "advertisement": "Advertisement Expenses",
    "advertising": "Advertisement Expenses",
    "rent": "Rent Expenses",
    "rental": "Rent Expenses",
    "office rent": "Rent Expenses",
    "electricity": "Electricity Expenses",
    "power": "Electricity Expenses",
    "telephone": "Telephone Expenses",
    "mobile": "Telephone Expenses",
    "broadband": "Telephone Expenses",
    "internet": "Telephone Expenses",
    "travel": "Travel Expenses",
    "travelling": "Travel Expenses",
    "conveyance": "Conveyance Expenses",
    "fuel": "Conveyance Expenses",
    "petrol": "Conveyance Expenses",
    "office supplies": "Office Expenses",
    "stationery": "Office Expenses",
    "printing": "Office Expenses",
    "food": "Food Expenses",
    "meals": "Food Expenses",
    "entertainment": "Entertainment Expenses",
    "legal fees": "Legal Expenses",
    "legal": "Legal Expenses",
    "accounting": "Accounting Expenses",
    "bookkeeping": "Accounting Expenses",
    "commission": "Commission Expenses",
    "brokerage": "Commission Expenses",
    "insurance": "Insurance Expenses",
    "premium": "Insurance Expenses",
    "repairs": "Repairs & Maintenance",
    "maintenance": "Repairs & Maintenance",
    "repair": "Repairs & Maintenance",
    "amc": "Repairs & Maintenance",
    "wages": "Direct Wages",
    "salary": "Salary Expenses",
    "labour": "Direct Wages",
    "freight": "Freight Expenses",
    "transportation": "Freight Expenses",
    "transport": "Freight Expenses",
    "carriage": "Freight Expenses",
    "loading": "Freight Expenses",
    "unloading": "Freight Expenses",
    "commission on sales": "Selling Expenses",
    "discount": "Discount Expenses",
    "bank charges": "Bank Charges",
    "interest": "Interest Expenses",
    "late fee": "Interest Expenses",
    "penalty": "Penalty Expenses",
    "donation": "Donation Expenses",
    "charity": "Donation Expenses",
    "subscription": "Subscription Expenses",
    "membership": "Subscription Expenses",
    "training": "Training Expenses",
    "seminar": "Training Expenses",
    "workshop": "Training Expenses",
    "purchase": "Purchase",
    "raw material": "Purchase",
    "raw materials": "Purchase",
    "stock": "Purchase",
    "trading goods": "Purchase",
    "merchandise": "Purchase",
    "goods": "Purchase",
    "equipment": "Fixed Assets",
    "furniture": "Fixed Assets",
    "fixtures": "Fixed Assets",
    "computer": "Fixed Assets",
    "laptop": "Fixed Assets",
    "printer": "Fixed Assets",
    "machinery": "Fixed Assets",
    "plant": "Fixed Assets",
    "vehicle": "Fixed Assets",
    "car": "Fixed Assets",
}

DEFAULT_GST_LEDGER_MAPPINGS = {
    "cgst_0.0": "Input CGST 0%",
    "cgst_0.1": "Input CGST 0.1%",
    "cgst_0.25": "Input CGST 0.25%",
    "cgst_1.5": "Input CGST 1.5%",
    "cgst_2.5": "Input CGST 2.5%",
    "cgst_3": "Input CGST 3%",
    "cgst_5": "Input CGST 5%",
    "cgst_12": "Input CGST 12%",
    "cgst_18": "Input CGST 18%",
    "cgst_28": "Input CGST 28%",
    "sgst_0.0": "Input SGST 0%",
    "sgst_0.1": "Input SGST 0.1%",
    "sgst_0.25": "Input SGST 0.25%",
    "sgst_1.5": "Input SGST 1.5%",
    "sgst_2.5": "Input SGST 2.5%",
    "sgst_3": "Input SGST 3%",
    "sgst_5": "Input SGST 5%",
    "sgst_12": "Input SGST 12%",
    "sgst_18": "Input SGST 18%",
    "sgst_28": "Input SGST 28%",
    "igst_0.0": "Input IGST 0%",
    "igst_0.1": "Input IGST 0.1%",
    "igst_0.25": "Input IGST 0.25%",
    "igst_1.5": "Input IGST 1.5%",
    "igst_2.5": "Input IGST 2.5%",
    "igst_3": "Input IGST 3%",
    "igst_5": "Input IGST 5%",
    "igst_12": "Input IGST 12%",
    "igst_18": "Input IGST 18%",
    "igst_28": "Input IGST 28%",
}

DEFAULT_OUTPUT_GST_LEDGER_MAPPINGS = {
    "cgst_0.0": "Output CGST 0%",
    "cgst_0.1": "Output CGST 0.1%",
    "cgst_0.25": "Output CGST 0.25%",
    "cgst_1.5": "Output CGST 1.5%",
    "cgst_2.5": "Output CGST 2.5%",
    "cgst_3": "Output CGST 3%",
    "cgst_5": "Output CGST 5%",
    "cgst_12": "Output CGST 12%",
    "cgst_18": "Output CGST 18%",
    "cgst_28": "Output CGST 28%",
    "sgst_0.0": "Output SGST 0%",
    "sgst_0.1": "Output SGST 0.1%",
    "sgst_0.25": "Output SGST 0.25%",
    "sgst_1.5": "Output SGST 1.5%",
    "sgst_2.5": "Output SGST 2.5%",
    "sgst_3": "Output SGST 3%",
    "sgst_5": "Output SGST 5%",
    "sgst_12": "Output SGST 12%",
    "sgst_18": "Output SGST 18%",
    "sgst_28": "Output SGST 28%",
    "igst_0.0": "Output IGST 0%",
    "igst_0.1": "Output IGST 0.1%",
    "igst_0.25": "Output IGST 0.25%",
    "igst_1.5": "Output IGST 1.5%",
    "igst_2.5": "Output IGST 2.5%",
    "igst_3": "Output IGST 3%",
    "igst_5": "Output IGST 5%",
    "igst_12": "Output IGST 12%",
    "igst_18": "Output IGST 18%",
    "igst_28": "Output IGST 28%",
}


class CompanyConfig:
    def __init__(self, env_prefix: str = "", user_config: Optional[dict] = None):
        self._ep = env_prefix
        self._user_config = user_config or {}
        self.state_code: str = self._user_config.get("company_state_code") or os.getenv(f"{env_prefix}COMPANY_STATE_CODE", "27")
        self.company_name: str = self._user_config.get("company_name") or os.getenv(f"{env_prefix}COMPANY_NAME", "My Company")
        self.company_gstin: str = self._user_config.get("company_gstin") or os.getenv(f"{env_prefix}COMPANY_GSTIN", "")
        self.masters_created: bool = bool(self._user_config.get("masters_created", False))
        self.default_voucher_type: VoucherType = VoucherType.PURCHASE
        self.default_purchase_ledger: str = self._user_config.get("purchase_ledger") or os.getenv(f"{env_prefix}PURCHASE_LEDGER", "Purchase")
        self.default_sales_ledger: str = self._user_config.get("sales_ledger") or os.getenv(f"{env_prefix}SALES_LEDGER", "Sales")
        self.default_cgst_ledger: str = os.getenv(f"{env_prefix}CGST_LEDGER", "Input CGST")
        self.default_sgst_ledger: str = os.getenv(f"{env_prefix}SGST_LEDGER", "Input SGST")
        self.default_igst_ledger: str = os.getenv(f"{env_prefix}IGST_LEDGER", "Input IGST")
        self.gst_ledger_mappings: dict = dict(DEFAULT_GST_LEDGER_MAPPINGS)
        self.output_gst_ledger_mappings: dict = dict(DEFAULT_OUTPUT_GST_LEDGER_MAPPINGS)
        self.ledger_mappings: dict = dict(DEFAULT_LEDGER_MAPPINGS)
        custom_mappings = os.getenv(f"{env_prefix}CUSTOM_LEDGER_MAPPINGS")
        if custom_mappings:
            try:
                overrides = json.loads(custom_mappings)
                self.ledger_mappings.update(overrides)
            except (json.JSONDecodeError, TypeError):
                pass
        custom_gst_mappings = os.getenv(f"{env_prefix}CUSTOM_GST_LEDGER_MAPPINGS")
        if custom_gst_mappings:
            try:
                overrides = json.loads(custom_gst_mappings)
                self.gst_ledger_mappings.update(overrides)
            except (json.JSONDecodeError, TypeError):
                pass
        custom_output_gst_mappings = os.getenv(f"{env_prefix}CUSTOM_OUTPUT_GST_LEDGER_MAPPINGS")
        if custom_output_gst_mappings:
            try:
                overrides = json.loads(custom_output_gst_mappings)
                self.output_gst_ledger_mappings.update(overrides)
            except (json.JSONDecodeError, TypeError):
                pass

    def get_purchase_ledger(self, description: str = "") -> str:
        if not description:
            return self.default_purchase_ledger
        return self.default_purchase_ledger

    def get_sales_ledger(self) -> str:
        return self.default_sales_ledger

    def get_expense_ledger(self, description: str, learner=None) -> str:
        key = description.lower().strip()
        # Check LedgerLearner first (self-improving, user-scoped corrections)
        if learner is not None and hasattr(learner, "resolve"):
            result = learner.resolve(description)
            if result != "Suspense":
                return result
        # Check user corrections (legacy path)
        corrections = self._user_config.get("correction_memory") or {}
        if isinstance(corrections, dict):
            for pattern, ledger in corrections.items():
                if pattern.lower() in key or key in pattern.lower():
                    return ledger
        for pattern, ledger in self.ledger_mappings.items():
            if pattern in key or key in pattern:
                return ledger
        return "Office Expenses"

    def add_correction(self, description: str, ledger: str):
        """Add a correction to memory (stored in user_config's correction_memory)."""
        corrections = self._user_config.get("correction_memory") or {}
        if not isinstance(corrections, dict):
            corrections = {}
        key = description.strip().lower()
        if key:
            corrections[key] = ledger
            self._user_config["correction_memory"] = corrections

    def get_tds_ledger(self) -> str:
        return self._user_config.get("tds_ledger") or os.getenv(f"{self._ep}TDS_PAYABLE_LEDGER", "TDS Payable")

    def get_round_off_ledger(self) -> str:
        return self._user_config.get("round_off_ledger") or os.getenv(f"{self._ep}ROUND_OFF_LEDGER", "Round Off")

    def get_freight_ledger(self) -> str:
        return self._user_config.get("freight_ledger") or os.getenv(f"{self._ep}FREIGHT_LEDGER", "Freight Expenses")

    def get_bank_ledger(self) -> str:
        return self._user_config.get("bank_ledger") or os.getenv(f"{self._ep}BANK_LEDGER", "Bank")

    def get_cess_ledger(self, is_input: bool = True) -> str:
        direction = "Input" if is_input else "Output"
        return self._user_config.get("cess_ledger") or os.getenv(f"{self._ep}CESS_LEDGER", f"{direction} Cess")

    def get_suspense_ledger(self) -> str:
        return self._user_config.get("suspense_ledger") or os.getenv(f"{self._ep}SUSPENSE_LEDGER", "Suspense")

    def get_sundry_creditors_group(self) -> str:
        return self._user_config.get("sundry_creditors_group") or os.getenv(f"{self._ep}SUNDRY_CREDITORS_GROUP", "Sundry Creditors")

    def get_sundry_debtors_group(self) -> str:
        return self._user_config.get("sundry_debtors_group") or os.getenv(f"{self._ep}SUNDRY_DEBTORS_GROUP", "Sundry Debtors")

    def get_purchase_accounts_group(self) -> str:
        return self._user_config.get("purchase_accounts_group") or os.getenv(f"{self._ep}PURCHASE_ACCOUNTS_GROUP", "Purchase Accounts")

    def get_sales_accounts_group(self) -> str:
        return self._user_config.get("sales_accounts_group") or os.getenv(f"{self._ep}SALES_ACCOUNTS_GROUP", "Sales Accounts")

    def get_bank_accounts_group(self) -> str:
        return self._user_config.get("bank_accounts_group") or os.getenv(f"{self._ep}BANK_ACCOUNTS_GROUP", "Bank Accounts")

    def get_current_liabilities_group(self) -> str:
        return self._user_config.get("current_liabilities_group") or os.getenv(f"{self._ep}CURRENT_LIABILITIES_GROUP", "Current Liabilities")

    def get_duties_taxes_group(self) -> str:
        return self._user_config.get("duties_taxes_group") or os.getenv(f"{self._ep}DUTIES_TAXES_GROUP", "Duties & Taxes")

    @staticmethod
    def _gst_rate_key(rate: float) -> str:
        if rate == int(rate):
            return str(int(rate))
        return f"{rate}"

    def get_gst_ledger(self, tax_type: str, rate: float, is_input: bool = True, is_rcm: bool = False) -> str:
        direction = "Input" if is_input else "Output"
        rate_key = self._gst_rate_key(rate)
        key = f"{tax_type}_{rate_key}"
        rcm_key = f"{tax_type}_{rate_key}_rcm"
        mappings = self.gst_ledger_mappings if is_input else self.output_gst_ledger_mappings
        if is_rcm and rcm_key in mappings:
            return mappings[rcm_key]
        if key in mappings:
            name = mappings[key]
            if is_rcm:
                name += " (RCM)"
            return name
        rcm_suffix = " (RCM)" if is_rcm else ""
        return f"{direction} {tax_type.upper()}{rcm_suffix} {rate:g}%"

    def to_env_config(self) -> dict:
        return {
            "company_name": self.company_name,
            "company_gstin": self.company_gstin,
            "company_state_code": self.state_code,
            "masters_created": self.masters_created,
            "purchase_ledger": self.default_purchase_ledger,
            "sales_ledger": self.default_sales_ledger,
            "bank_ledger": self.get_bank_ledger(),
            "tds_ledger": self.get_tds_ledger(),
            "round_off_ledger": self.get_round_off_ledger(),
            "freight_ledger": self.get_freight_ledger(),
            "suspense_ledger": self.get_suspense_ledger(),
            "sundry_creditors_group": self.get_sundry_creditors_group(),
            "sundry_debtors_group": self.get_sundry_debtors_group(),
            "purchase_accounts_group": self.get_purchase_accounts_group(),
            "sales_accounts_group": self.get_sales_accounts_group(),
            "bank_accounts_group": self.get_bank_accounts_group(),
            "current_liabilities_group": self.get_current_liabilities_group(),
            "duties_taxes_group": self.get_duties_taxes_group(),
            "cess_ledger": self.get_cess_ledger(),
        }

    def determine_tax_category(self, vendor_gstin: str, buyer_gstin: str) -> str:
        """Return 'CGST_SGST' if both GSTINs have same state code, 'IGST' otherwise."""
        v_code = (vendor_gstin or "")[:2].strip()
        b_code = (buyer_gstin or "")[:2].strip()
        if v_code and b_code and v_code == b_code:
            return "CGST_SGST"
        return "IGST"
