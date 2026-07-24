"""Rule engine for deterministic ledger mapping with confidence scoring.

LLM extracts facts. Rules Engine makes accounting decisions.

Architecture:
  Invoice → LLM Extraction → Schema Validation → Rules Engine → Voucher Builder → XML

The Rules Engine replaces hardcoded if/else with configurable rules,
returns structured results with confidence scores, and never silently
falls back to a default ledger.
"""

import difflib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MatchType(Enum):
    EXACT = "exact"
    KEYWORD = "keyword"
    PARTIAL = "partial"
    FUZZY = "fuzzy"


CONFIDENCE_MAP = {
    MatchType.EXACT: 1.0,
    MatchType.KEYWORD: 0.85,
    MatchType.PARTIAL: 0.60,
    MatchType.FUZZY: 0.40,
}


@dataclass
class LedgerRule:
    pattern: str
    target_ledger: str
    match_type: MatchType = MatchType.KEYWORD
    confidence: float = 0.85
    is_active: bool = True
    category: str = "expense"

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "target_ledger": self.target_ledger,
            "match_type": self.match_type.value,
            "confidence": self.confidence,
            "is_active": self.is_active,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LedgerRule":
        return cls(
            pattern=d["pattern"],
            target_ledger=d["target_ledger"],
            match_type=MatchType(d.get("match_type", "keyword")),
            confidence=d.get("confidence", 0.85),
            is_active=d.get("is_active", True),
            category=d.get("category", "expense"),
        )


@dataclass
class MatchResult:
    ledger_name: str
    confidence: float
    match_type: Optional[MatchType] = None
    rule: Optional[LedgerRule] = None
    is_unmapped: bool = False
    suggestions: list[str] = field(default_factory=list)

    def needs_review(self, threshold: float = 0.80) -> bool:
        return self.is_unmapped or self.confidence < threshold

    def to_dict(self) -> dict:
        return {
            "ledger_name": self.ledger_name,
            "confidence": self.confidence,
            "match_type": self.match_type.value if self.match_type else None,
            "is_unmapped": self.is_unmapped,
            "suggestions": self.suggestions,
            "needs_review": self.needs_review(),
        }


# Default rules built from existing keyword mappings
def build_default_rules() -> list[LedgerRule]:
    return [
        # Professional Services
        LedgerRule("professional services", "Professional Charges", MatchType.KEYWORD, 0.90),
        LedgerRule("professional fees", "Professional Charges", MatchType.KEYWORD, 0.90),
        LedgerRule("consultation fees", "Professional Charges", MatchType.KEYWORD, 0.90),
        LedgerRule("consulting fees", "Professional Charges", MatchType.KEYWORD, 0.90),
        LedgerRule("consulting", "Professional Charges", MatchType.KEYWORD, 0.85),
        LedgerRule("development", "Professional Charges", MatchType.KEYWORD, 0.80),

        # Audit
        LedgerRule("audit fees", "Audit Expenses", MatchType.KEYWORD, 0.90),
        LedgerRule("audit", "Audit Expenses", MatchType.KEYWORD, 0.80),

        # Software & IT
        LedgerRule("cloud hosting", "Software Expenses", MatchType.KEYWORD, 0.90),
        LedgerRule("hosting", "Software Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("server", "Software Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("software", "Software Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("software license", "Software Expenses", MatchType.KEYWORD, 0.90),

        # Advertisement
        LedgerRule("advertisement", "Advertisement Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("advertising", "Advertisement Expenses", MatchType.KEYWORD, 0.85),

        # Rent
        LedgerRule("rent", "Rent Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("rental", "Rent Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("office rent", "Rent Expenses", MatchType.KEYWORD, 0.90),

        # Utilities
        LedgerRule("electricity", "Electricity Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("power", "Electricity Expenses", MatchType.KEYWORD, 0.75),
        LedgerRule("telephone", "Telephone Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("mobile", "Telephone Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("broadband", "Telephone Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("internet", "Telephone Expenses", MatchType.KEYWORD, 0.85),

        # Travel
        LedgerRule("travel", "Travel Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("travelling", "Travel Expenses", MatchType.KEYWORD, 0.85),

        # Conveyance
        LedgerRule("conveyance", "Conveyance Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("fuel", "Conveyance Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("petrol", "Conveyance Expenses", MatchType.KEYWORD, 0.85),

        # Office
        LedgerRule("office supplies", "Office Expenses", MatchType.KEYWORD, 0.90),
        LedgerRule("stationery", "Office Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("printing", "Office Expenses", MatchType.KEYWORD, 0.85),

        # Food & Entertainment
        LedgerRule("food", "Food Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("meals", "Food Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("entertainment", "Entertainment Expenses", MatchType.KEYWORD, 0.85),

        # Legal
        LedgerRule("legal fees", "Legal Expenses", MatchType.KEYWORD, 0.90),
        LedgerRule("legal", "Legal Expenses", MatchType.KEYWORD, 0.80),

        # Accounting
        LedgerRule("accounting", "Accounting Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("bookkeeping", "Accounting Expenses", MatchType.KEYWORD, 0.85),

        # Commission
        LedgerRule("commission", "Commission Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("brokerage", "Commission Expenses", MatchType.KEYWORD, 0.85),

        # Insurance
        LedgerRule("insurance", "Insurance Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("premium", "Insurance Expenses", MatchType.KEYWORD, 0.75),

        # Maintenance
        LedgerRule("repairs", "Repairs & Maintenance", MatchType.KEYWORD, 0.85),
        LedgerRule("maintenance", "Repairs & Maintenance", MatchType.KEYWORD, 0.85),
        LedgerRule("repair", "Repairs & Maintenance", MatchType.KEYWORD, 0.85),
        LedgerRule("amc", "Repairs & Maintenance", MatchType.KEYWORD, 0.85),

        # Wages & Salary
        LedgerRule("wages", "Direct Wages", MatchType.KEYWORD, 0.85),
        LedgerRule("salary", "Salary Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("labour", "Direct Wages", MatchType.KEYWORD, 0.85),

        # Freight
        LedgerRule("freight", "Freight Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("transportation", "Freight Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("transport", "Freight Expenses", MatchType.KEYWORD, 0.80),
        LedgerRule("carriage", "Freight Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("loading", "Freight Expenses", MatchType.KEYWORD, 0.75),
        LedgerRule("unloading", "Freight Expenses", MatchType.KEYWORD, 0.75),

        # Selling
        LedgerRule("commission on sales", "Selling Expenses", MatchType.KEYWORD, 0.90),

        # Financial
        LedgerRule("bank charges", "Bank Charges", MatchType.KEYWORD, 0.90),
        LedgerRule("interest", "Interest Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("late fee", "Interest Expenses", MatchType.KEYWORD, 0.85),

        # Penalty
        LedgerRule("penalty", "Penalty Expenses", MatchType.KEYWORD, 0.85),

        # Donation
        LedgerRule("donation", "Donation Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("charity", "Donation Expenses", MatchType.KEYWORD, 0.85),

        # Subscription
        LedgerRule("subscription", "Subscription Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("membership", "Subscription Expenses", MatchType.KEYWORD, 0.85),

        # Training
        LedgerRule("training", "Training Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("seminar", "Training Expenses", MatchType.KEYWORD, 0.85),
        LedgerRule("workshop", "Training Expenses", MatchType.KEYWORD, 0.85),

        # Purchase (goods)
        LedgerRule("purchase", "Purchase", MatchType.KEYWORD, 0.85),
        LedgerRule("raw material", "Purchase", MatchType.KEYWORD, 0.90),
        LedgerRule("raw materials", "Purchase", MatchType.KEYWORD, 0.90),
        LedgerRule("stock", "Purchase", MatchType.KEYWORD, 0.75),
        LedgerRule("trading goods", "Purchase", MatchType.KEYWORD, 0.85),
        LedgerRule("merchandise", "Purchase", MatchType.KEYWORD, 0.85),
        LedgerRule("goods", "Purchase", MatchType.KEYWORD, 0.75),

        # Fixed Assets
        LedgerRule("equipment", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("furniture", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("fixtures", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("computer", "Fixed Assets", MatchType.KEYWORD, 0.80),
        LedgerRule("laptop", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("printer", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("machinery", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("plant", "Fixed Assets", MatchType.KEYWORD, 0.80),
        LedgerRule("vehicle", "Fixed Assets", MatchType.KEYWORD, 0.85),
        LedgerRule("car", "Fixed Assets", MatchType.KEYWORD, 0.75),
    ]


class RulesEngine:
    """Deterministic rule engine for ledger mapping with confidence scoring.

    Never silently falls back to a default. Returns MatchResult with
    is_unmapped=True when no rule matches, along with suggestions.
    """

    def __init__(self, rules: Optional[list[LedgerRule]] = None):
        self._rules: list[LedgerRule] = rules if rules is not None else build_default_rules()
        self._corrections: dict[str, str] = {}

    def add_rule(self, rule: LedgerRule):
        self._rules.append(rule)

    def remove_rule(self, pattern: str, target_ledger: str) -> bool:
        for i, r in enumerate(self._rules):
            if r.pattern == pattern and r.target_ledger == target_ledger:
                del self._rules[i]
                return True
        return False

    def update_rule(self, old_pattern: str, old_target: str, new_rule: LedgerRule) -> bool:
        for i, r in enumerate(self._rules):
            if r.pattern == old_pattern and r.target_ledger == old_target:
                self._rules[i] = new_rule
                return True
        return False

    def get_rules(self, category: Optional[str] = None) -> list[LedgerRule]:
        if category:
            return [r for r in self._rules if r.category == category and r.is_active]
        return [r for r in self._rules if r.is_active]

    def add_correction(self, description: str, ledger: str):
        self._corrections[description.strip().lower()] = ledger

    def _get_all_target_ledgers(self) -> list[str]:
        seen = set()
        result = []
        for r in self._rules:
            if r.target_ledger not in seen:
                seen.add(r.target_ledger)
                result.append(r.target_ledger)
        return sorted(result)

    COMMON_LEDGERS = [
        "Professional Charges", "Office Expenses", "Purchase", "Travel Expenses",
        "Software Expenses", "Legal Expenses", "Freight Expenses", "Rent Expenses",
        "Electricity Expenses", "Telephone Expenses", "Food Expenses",
        "Repairs & Maintenance", "Salary Expenses", "Fixed Assets",
        "Audit Expenses", "Commission Expenses", "Insurance Expenses",
        "Interest Expenses", "Bank Charges", "Advertisement Expenses",
        "Training Expenses", "Subscription Expenses", "Donation Expenses",
    ]

    def suggest_ledgers(self, description: str, top_n: int = 3) -> list[str]:
        key = description.lower().strip()
        scored = []

        # Check corrections first (100% confidence)
        if key in self._corrections:
            scored.append((self._corrections[key], 1.0))

        # Check active rules — keyword match
        for rule in self._rules:
            if not rule.is_active:
                continue
            if rule.pattern in key or key in rule.pattern:
                scored.append((rule.target_ledger, CONFIDENCE_MAP.get(rule.match_type, 0.85)))

        # Fuzzy match against all known ledgers
        all_ledgers = self._get_all_target_ledgers()
        fuzzy = difflib.get_close_matches(key, [l.lower() for l in all_ledgers], n=2, cutoff=0.5)
        for match in fuzzy:
            idx = [l.lower() for l in all_ledgers].index(match)
            scored.append((all_ledgers[idx], 0.35))

        # Deduplicate and sort by confidence descending
        seen = set()
        unique = []
        for ledger, conf in scored:
            if ledger not in seen:
                seen.add(ledger)
                unique.append((ledger, conf))
        unique.sort(key=lambda x: -x[1])

        # If no match at all, return common ledgers as generic suggestions
        if not unique:
            return self.COMMON_LEDGERS[:top_n]

        return [l for l, _ in unique[:top_n]]

    def match(self, description: str) -> MatchResult:
        """Match a description to a ledger with confidence scoring.

        Priority: corrections → exact → keyword → partial → fuzzy
        Never returns a silent default. Returns is_unmapped=True when no match found.
        """
        if not description or not description.strip():
            return MatchResult(
                ledger_name="",
                confidence=0.0,
                is_unmapped=True,
                suggestions=self._get_all_target_ledgers()[:5],
            )

        key = description.lower().strip()

        # 1. Corrections (user-taught) — 100% confidence
        if key in self._corrections:
            ledger = self._corrections[key]
            return MatchResult(ledger, 1.0, MatchType.EXACT)

        best: Optional[tuple[str, float, MatchType, Optional[LedgerRule]]] = None

        for rule in self._rules:
            if not rule.is_active:
                continue

            rpat = rule.pattern.lower()
            conf = CONFIDENCE_MAP.get(rule.match_type, 0.85)

            # Exact match
            if rpat == key:
                if best is None or conf > best[1]:
                    best = (rule.target_ledger, 1.0, MatchType.EXACT, rule)
                continue

            # Keyword containment
            if rpat in key:
                if best is None or conf > best[1]:
                    best = (rule.target_ledger, conf, MatchType.KEYWORD, rule)
                continue

            # Partial (description contains rule pattern)
            if key in rpat:
                partial_conf = conf * 0.8
                if best is None or partial_conf > best[1]:
                    best = (rule.target_ledger, partial_conf, MatchType.PARTIAL, rule)
                continue

        # 3. Fuzzy match against all known ledgers
        all_ledgers = self._get_all_target_ledgers()
        fuzzy_matches = difflib.get_close_matches(key, [l.lower() for l in all_ledgers], n=1, cutoff=0.5)
        fuzzy_conf = 0.40
        if fuzzy_matches and (best is None or fuzzy_conf > best[1]):
            idx = [l.lower() for l in all_ledgers].index(fuzzy_matches[0])
            best = (all_ledgers[idx], fuzzy_conf, MatchType.FUZZY, None)

        if best:
            return MatchResult(best[0], best[1], best[2], best[3])

        # No match — return structured unmapped result with suggestions
        return MatchResult(
            ledger_name="__UNMAPPED__",
            confidence=0.0,
            is_unmapped=True,
            suggestions=self.suggest_ledgers(description, top_n=5),
        )
