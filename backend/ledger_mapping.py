"""Semantic ledger mapping engine with RulesEngine for confidence-scored matching.

LLM extracts facts. RulesEngine makes accounting decisions.
Every mapping returns a confidence score. Below 80% triggers user review.
Never silently falls back to Office Expenses."""

import difflib
import re
from typing import Optional

from company_config import CompanyConfig
from rules_engine import RulesEngine, MatchResult
from context_classifier import ContextClassifier, ContextResult


class LedgerMappingEngine:
    def __init__(self, config: Optional[CompanyConfig] = None, rules_engine: Optional[RulesEngine] = None):
        self.config = config or CompanyConfig()
        self.rules = rules_engine or RulesEngine()
        self.context = ContextClassifier(rules_engine=self.rules)

    def map_expense_ledger(self, description: str) -> str:
        """Legacy: returns ledger name. Unmapped → 'Suspense' (safe fallback, flagged for review).
        New code should use map_expense_ledger_scored for confidence data."""
        result = self.map_expense_ledger_scored(description)
        if result.ledger_name == "__UNMAPPED__" or not result.ledger_name:
            return self.config.get_suspense_ledger()
        return result.ledger_name

    def map_expense_ledger_scored(self, description: str, amount: float = 0.0) -> ContextResult:
        """Context-aware ledger mapping with capital vs revenue classification."""
        desc = (description or "").strip()
        if not desc:
            return ContextResult(
                ledger_name=self.config.default_purchase_ledger,
                confidence=0.50,
                context_type="revenue",
                explanation="Empty description; defaulting to purchase ledger.",
                suggestions=["Purchase", "Office Expenses", "Professional Charges"],
            )
        return self.context.classify(description, amount=amount)

    def map_purchase_ledger(self, description: str = "") -> str:
        return self.config.get_purchase_ledger(description)

    def map_sales_ledger(self) -> str:
        return self.config.get_sales_ledger()

    def map_gst_ledger(self, tax_type: str, rate: float, is_input: bool = True, is_rcm: bool = False) -> str:
        return self.config.get_gst_ledger(tax_type, rate, is_input, is_rcm)

    def map_party_ledger(self, party_name: str) -> str:
        if not party_name or not party_name.strip():
            return "Unknown Supplier"
        return party_name.strip()

    def map_ledger_fuzzy(self, raw: str, candidates: list[str]) -> Optional[str]:
        if not raw or not candidates:
            return None
        best = difflib.get_close_matches(raw.lower(), [c.lower() for c in candidates], n=1, cutoff=0.6)
        if best:
            idx = [c.lower() for c in candidates].index(best[0])
            return candidates[idx]
        return None

    def get_all_ledgers_for_invoice(self, inv_data: dict, is_service: bool, is_interstate: bool) -> dict:
        line_items = inv_data.get("line_items", [])
        expense_ledgers = set()
        low_confidence = []
        for item in line_items:
            desc = item.get("description", "")
            amt = float(item.get("taxable_value") or item.get("amount") or 0)
            result = self.map_expense_ledger_scored(desc, amount=amt)
            if result.ledger_name and result.ledger_name != "__UNMAPPED__":
                expense_ledgers.add(result.ledger_name)
            if result.confidence < 0.80 or result.context_type == "capital":
                low_confidence.append({
                    "description": desc,
                    "confidence": result.confidence,
                    "context_type": result.context_type,
                    "suggested_ledger": result.ledger_name,
                    "explanation": result.explanation,
                })
        return {
            "expense_ledgers": list(expense_ledgers) if expense_ledgers else ["Purchase"],
            "party_ledger": self.map_party_ledger(inv_data.get("vendor_name", "")),
            "low_confidence": low_confidence,
        }


def apply_banking_rules_to_transactions(transactions: list[dict], active_rules: list[dict]) -> list[dict]:
    sorted_rules = sorted(active_rules, key=lambda r: len(r.get("keyword", "")), reverse=True)
    processed = []
    for tx in transactions:
        tx_copy = dict(tx)
        desc = str(tx.get("description", "")).upper()
        deposit = float(tx.get("deposit_amount", 0))
        withdraw = float(tx.get("withdraw_amount", 0))
        if deposit > 0:
            tx_copy["voucher_type"] = "Receipt"
            tx_copy["target_ledger"] = "Suspense"
        else:
            tx_copy["voucher_type"] = "Payment"
            tx_copy["target_ledger"] = "Suspense"
        for rule in sorted_rules:
            keyword = str(rule.get("keyword", "")).upper()
            if keyword and keyword in desc:
                tx_copy["voucher_type"] = rule.get("voucher_type", tx_copy["voucher_type"])
                tx_copy["target_ledger"] = rule.get("target_ledger", tx_copy["target_ledger"])
                tx_copy["rule_applied"] = rule.get("keyword", "")
                break
        processed.append(tx_copy)
    return processed
