"""Context-aware ledger classification.

A CA doesn't just map keywords. They read the *meaning*:
- "Laptop" + ₹50,000  → Fixed Assets (capitalize)
- "Laptop" + ₹500     → Office Expenses (revenue)
- "Repairs" + any     → Repairs & Maintenance (revenue, even if large)
- "Annual Maintenance" + ₹1L → Repairs & Maintenance or Software Expenses

This module wraps the RulesEngine with business-context intelligence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from rules_engine import RulesEngine, MatchType, LedgerRule


# Amount threshold above which a capital-looking item is treated as Fixed Asset
CAPITAL_AMOUNT_THRESHOLD = 25_000.0

# Patterns that are ALWAYS capital (regardless of amount)
CAPITAL_KEYWORDS = re.compile(
    r"\b(machine|machinery|laptop|computer|server|printer|furniture|fixture|vehicle|car|scooter|bike|"
    r"equipment|acquisition|land|building|factory|plant|capital|asset|macbook|notebook|laptop)\b",
    re.IGNORECASE,
)

# Patterns that are ALWAYS revenue (never capitalize)
REVENUE_KEYWORDS = re.compile(
    r"\b(repair|repairs|maintenance|amc|service|consumable|stationery|rent|salary|wages|"
    r"freight|transport|food|meals|travel|hotel|conveyance|fuel|petrol|electricity|"
    r"telephone|mobile|internet|broadband|advertisement|advertising|legal|audit|"
    r"accounting|bookkeeping|commission|brokerage|insurance|premium|bank charges|"
    r"interest|late fee|penalty|donation|charity|subscription|membership|training|"
    r"seminar|workshop|software|hosting|cloud|license|professional)\b",
    re.IGNORECASE,
)


@dataclass
class ContextResult:
    ledger_name: str
    confidence: float
    context_type: str  # "capital" | "revenue" | "purchase"
    match_type: Optional[MatchType] = None
    rule: Optional[LedgerRule] = None
    explanation: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ledger_name": self.ledger_name,
            "confidence": self.confidence,
            "context_type": self.context_type,
            "match_type": self.match_type.value if self.match_type else None,
            "rule": self.rule.to_dict() if self.rule else None,
            "explanation": self.explanation,
            "suggestions": self.suggestions,
        }


class ContextClassifier:
    """Wraps RulesEngine with capital-vs-revenue business context.

    Decision tree:
    1. If description contains REVENUE_KEYWORDS → revenue expense (RulesEngine decides ledger)
    2. If description contains CAPITAL_KEYWORDS and amount >= threshold → Fixed Assets
    3. Otherwise → delegate to RulesEngine unchanged
    """

    def __init__(self, rules_engine: Optional[RulesEngine] = None, threshold: float = CAPITAL_AMOUNT_THRESHOLD):
        self.rules = rules_engine or RulesEngine()
        self.threshold = float(threshold)

    def classify(self, description: str, amount: float = 0.0) -> ContextResult:
        desc = (description or "").strip()
        if not desc:
            return ContextResult(
                ledger_name="",
                confidence=0.0,
                context_type="revenue",
                explanation="Empty description; cannot classify.",
            )

        lower_desc = desc.lower()

        # 1. Revenue keywords → always revenue, let RulesEngine pick the ledger
        if REVENUE_KEYWORDS.search(lower_desc):
            match = self.rules.match(desc)
            ctx = "revenue"
            if match.is_unmapped or not match.ledger_name or match.ledger_name == "__UNMAPPED__":
                ledger = "Office Expenses"
                conf = 0.50
                suggestions = ["Office Expenses", "Suspense", "Purchase"]
            else:
                ledger = match.ledger_name
                conf = match.confidence
                suggestions = match.suggestions or []
            return ContextResult(
                ledger_name=ledger,
                confidence=conf,
                context_type=ctx,
                match_type=match.match_type,
                rule=match.rule,
                explanation=f"Revenue keyword detected in '{desc}'. Ledger mapped by RulesEngine.",
                suggestions=suggestions,
            )

        # 2. Capital keywords + high amount → Fixed Assets
        if CAPITAL_KEYWORDS.search(lower_desc) and amount >= self.threshold:
            return ContextResult(
                ledger_name="Fixed Assets",
                confidence=0.90,
                context_type="capital",
                match_type=MatchType.KEYWORD,
                explanation=f"Capital asset detected (amount ₹{amount:,.2f} >= ₹{self.threshold:,.0f}). "
                            f"Should be capitalized and depreciated, not expensed.",
                suggestions=["Fixed Assets", "Office Expenses"],
            )

        # 3. Capital keyword but below threshold → still revenue, let RulesEngine decide
        if CAPITAL_KEYWORDS.search(lower_desc) and amount < self.threshold:
            match = self.rules.match(desc)
            ctx = "revenue"
            if match.is_unmapped or not match.ledger_name or match.ledger_name == "__UNMAPPED__":
                ledger = "Office Expenses"
                conf = 0.55
                suggestions = ["Office Expenses", "Fixed Assets", "Suspense"]
            else:
                ledger = match.ledger_name
                conf = match.confidence
                suggestions = match.suggestions or []
            return ContextResult(
                ledger_name=ledger,
                confidence=conf,
                context_type=ctx,
                match_type=match.match_type,
                rule=match.rule,
                explanation=f"Below capitalization threshold (₹{amount:,.2f} < ₹{self.threshold:,.0f}). "
                            f"Treated as revenue expense.",
                suggestions=suggestions,
            )

        # 4. No strong signal → if amount is high, default to capital; else revenue via RulesEngine
        match = self.rules.match(desc)
        if amount >= self.threshold:
            if match.is_unmapped or not match.ledger_name or match.ledger_name == "__UNMAPPED__":
                return ContextResult(
                    ledger_name="Fixed Assets",
                    confidence=0.75,
                    context_type="capital",
                    explanation=f"No explicit keyword matched, but amount ₹{amount:,.2f} >= threshold ₹{self.threshold:,.0f}. "
                                f"Defaulting to Fixed Assets for review.",
                    suggestions=["Fixed Assets", "Office Expenses"],
                )
            return ContextResult(
                ledger_name=match.ledger_name,
                confidence=match.confidence,
                context_type="revenue",
                match_type=match.match_type,
                rule=match.rule,
                explanation="Mapped by RulesEngine based on keyword match.",
                suggestions=match.suggestions or [],
            )
        if match.is_unmapped or not match.ledger_name or match.ledger_name == "__UNMAPPED__":
            return ContextResult(
                ledger_name="",
                confidence=0.0,
                context_type="revenue",
                explanation="No capital/revenue signal matched. RulesEngine could not map.",
                suggestions=["Office Expenses", "Purchase", "Suspense"],
            )
        return ContextResult(
            ledger_name=match.ledger_name,
            confidence=match.confidence,
            context_type="revenue",
            match_type=match.match_type,
            rule=match.rule,
            explanation="Mapped by RulesEngine based on keyword match.",
            suggestions=match.suggestions or [],
        )
