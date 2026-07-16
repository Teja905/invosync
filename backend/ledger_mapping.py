"""Semantic ledger mapping engine with RulesEngine for confidence-scored matching.

LLM extracts facts. RulesEngine makes accounting decisions.
Every mapping returns a confidence score. Below 80% triggers user review.
Never silently falls back to Office Expenses.

NOTE: This engine now leverages Tally's 28 universal groups for 95% confidence
on parent-group-based detection. See constants/tally_groups.py for the full list."""

import difflib
import re
from typing import Optional

from pydantic import BaseModel

from company_config import CompanyConfig
from constants.tally_groups import (
    UNIVERSAL_GROUPS,
    GROUP_TO_ROLE,
    ROLE_TO_EXPECTED_GROUPS,
    COMMON_LEDGER_NAMES,
    UNIVERSAL_LEDGERS,
    DEFAULT_LEDGERS,
)
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


# ---------------------------------------------------------------------------
# LedgerDiscoveryEngine — parent-group-based auto-detection (Suvit-like)
# ---------------------------------------------------------------------------

# Parent group patterns → canonical role
PARENT_CATEGORY_MAP: list[tuple[list[str], str]] = [
    (["purchase accounts", "purchase", "direct expenses", "cogs", "cost of goods sold",
      "purchase a/c", "trading account"], "PURCHASE"),
    (["sales accounts", "sales", "direct income", "revenue", "revenue accounts",
      "sales a/c", "income (direct)"], "SALES"),
    (["bank accounts", "bank", "current account", "bank a/c", "banks"], "BANK"),
    (["sundry debtors", "debtors", "accounts receivable", "receivables",
      "sundry debtors (control)"], "DEBTORS"),
    (["sundry creditors", "creditors", "accounts payable", "payables",
      "sundry creditors (control)"], "CREDITORS"),
    (["duties & taxes", "duties and taxes", "tax payable", "tax liabilities"], "GST"),
    (["fixed assets", "fixed asset", "assets (fixed)"], "FIXED_ASSETS"),
    (["current assets", "current asset", "assets (current)", "cash in hand",
      "cash"], "ASSETS"),
    (["current liabilities", "current liability", "liabilities (current)",
      "duties & taxes"], "LIABILITIES"),
]

# Which role maps to which settings field
ROLE_TO_SETTINGS_FIELD = {
    "PURCHASE": "purchase_ledger",
    "SALES": "sales_ledger",
    "BANK": "bank_ledger",
    "DEBTORS": "debtors_ledger",
    "CREDITORS": "creditors_ledger",
    "GST_INPUT": "input_gst_ledger",
    "GST_OUTPUT": "output_gst_ledger",
}

# LEDGER_NAME → (role, gst_type) for well-known ledgers that don't need parent group matching
WELL_KNOWN_LEDGERS: dict[str, tuple[str, str]] = {
    "purchase": ("PURCHASE", ""),
    "purchase a/c": ("PURCHASE", ""),
    "local purchases": ("PURCHASE", ""),
    "purchases (local)": ("PURCHASE", ""),
    "purchases (interstate)": ("PURCHASE", ""),
    "sales": ("SALES", ""),
    "sales a/c": ("SALES", ""),
    "local sales": ("SALES", ""),
    "sales (local)": ("SALES", ""),
    "sales (interstate)": ("SALES", ""),
    "bank": ("BANK", ""),
    "bank a/c": ("BANK", ""),
    "hdfc bank": ("BANK", ""),
    "icici bank": ("BANK", ""),
    "state bank of india": ("BANK", ""),
    "sbi": ("BANK", ""),
    "sundry debtors": ("DEBTORS", ""),
    "sundry creditors": ("CREDITORS", ""),
    "input cgst": ("GST_INPUT", "Input"),
    "input sgst": ("GST_INPUT", "Input"),
    "input igst": ("GST_INPUT", "Input"),
    "output cgst": ("GST_OUTPUT", "Output"),
    "output sgst": ("GST_OUTPUT", "Output"),
    "output igst": ("GST_OUTPUT", "Output"),
}

# Keywords within ledger names that hint at role (boosts confidence from 60→80)
ROLE_KEYWORDS: dict[str, list[str]] = {
    "PURCHASE": ["purchase", "purchases", "trading", "cost of goods", "cogs", "direct expense",
                 "raw material", "consumption", "stock purchase"],
    "SALES": ["sales", "income", "revenue", "service income", "consulting income",
              "commission income", "interest income", "other income"],
    "BANK": ["bank", "current account", "saving", "savings account", "current a/c"],
    "DEBTORS": ["debtor", "receivable", "receivables", "trade receivable"],
    "CREDITORS": ["creditor", "payable", "payables", "trade payable", "supplier"],
}

# GST type keywords
GST_TYPE_KEYWORDS: dict[str, list[str]] = {
    "Input": ["input cgst", "input sgst", "input igst", "itc", "input tax credit",
              "cgst input", "sgst input", "igst input"],
    "Output": ["output cgst", "output sgst", "output igst", "cgst output",
               "sgst output", "igst output", "cgst (output)", "sgst (output)", "igst (output)"],
}


class ScoredSuggestion(BaseModel):
    ledger_name: str
    confidence: int  # 0-100
    parent_category: str
    match_reason: str


class LedgerDiscoveryEngine:
    """Discovers which ledger in a Tally chart-of-accounts best matches a given role,
    using parent-group matching + name keywords + GST type.

    Scoring tiers (new as of Fix 26 — universal groups):
      95%  — parent is one of Tally's 28 universal groups AND maps directly to role
      90%  — well-known ledger exact name match (existing)
      85%  — common ledger name match (e.g. "SBI" → BANK)
      60%  — pattern-based parent category match (existing fallback)
      60→80 — +20 keyword bonus
      80→95 — +15 GST type bonus (GST_INPUT/GST_OUTPUT)
    """

    def __init__(self, config: Optional[CompanyConfig] = None):
        self.config = config or CompanyConfig()

    def _is_universal_group(self, parent: str) -> bool:
        """Check if the parent group is one of Tally's 28 universal groups."""
        return parent.strip().lower() in {g.lower() for g in UNIVERSAL_GROUPS}

    def _categorize_by_parent(self, parent: str) -> str:
        """Map a Tally parent group name to a canonical role category.
        Checks universal groups first (exact match), then falls back to pattern matching."""
        pl = parent.strip().lower()

        # 1. Exact check against universal groups (bulletproof for all Indian Tally)
        for group_name, role in GROUP_TO_ROLE.items():
            if group_name.lower() == pl:
                return role

        # 2. Fallback: pattern matching (catches custom-named groups)
        for patterns, role in PARENT_CATEGORY_MAP:
            for pat in patterns:
                if pat == pl or (pat in pl) or (pl in pat):
                    return role
        return "OTHER"

    def _match_common_ledger_name(self, name: str, target_role: str) -> bool:
        """Check if the ledger name is in the common names list for this role."""
        nl = name.strip().lower()
        common = COMMON_LEDGER_NAMES.get(target_role, [])
        return any(cn.lower() == nl for cn in common)

    def _detect_gst_type(self, name: str, parent: str) -> str:
        """Detect whether a ledger is Input GST, Output GST, or neither."""
        nl = name.strip().lower()
        for gst_type, keywords in GST_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in nl:
                    return gst_type
        # Check parent hints
        pl = parent.strip().lower()
        if "input" in pl or "itc" in pl:
            return "Input"
        if "output" in pl:
            return "Output"
        # Check if name contains @ or % followed by a number (GST rate ledgers)
        if re.search(r'[@%]\s*\d+', name):
            if "input" in name.lower() or "itc" in name.lower():
                return "Input"
            if "output" in name.lower():
                return "Output"
            # Ambiguous — check parent
            if "duties" in pl or "tax" in pl:
                return "Input"  # Conservative: assume input
        return ""

    def _expected_groups_for_role(self, role: str) -> list[str]:
        """Return list of universal group names expected for a given role."""
        base_role = "GST" if role in ("GST_INPUT", "GST_OUTPUT") else role
        return ROLE_TO_EXPECTED_GROUPS.get(base_role, [])

    def score_ledger_for_role(self, ledger: dict, target_role: str) -> ScoredSuggestion:
        """Score a single ledger entry against a target role. Returns ScoredSuggestion."""
        name = ledger.get("name", "")
        parent = ledger.get("parent", "")
        gst_type = ledger.get("gst_type", "") or self._detect_gst_type(name, parent)
        nl = name.strip().lower()
        pl = parent.strip().lower()

        # ── TIER 1: Well-known ledger exact match (90-95%) ──
        if nl in WELL_KNOWN_LEDGERS:
            w_role, w_gst = WELL_KNOWN_LEDGERS[nl]
            if w_role == target_role:
                cat = self._categorize_by_parent(parent) or target_role
                if target_role in ("GST_INPUT", "GST_OUTPUT") and w_gst:
                    return ScoredSuggestion(
                        ledger_name=name, confidence=95,
                        parent_category=cat,
                        match_reason=f"Well-known {target_role} ledger (exact name match)",
                    )
                return ScoredSuggestion(
                    ledger_name=name, confidence=90,
                    parent_category=cat,
                    match_reason=f"Well-known {target_role} ledger",
                )

        # ── TIER 2: Universal group match (95%) ──
        target_is_gst = target_role in ("GST_INPUT", "GST_OUTPUT")
        target_base = "GST" if target_is_gst else target_role

        expected_groups = self._expected_groups_for_role(target_role)
        if parent and self._is_universal_group(parent):
            # Check exact role mapping from GROUP_TO_ROLE
            mapped_role = GROUP_TO_ROLE.get(parent.strip(), None)
            # Also check normalized for case differences
            if mapped_role is None:
                for g, r in GROUP_TO_ROLE.items():
                    if g.lower() == pl:
                        mapped_role = r
                        break

            if mapped_role == target_base:
                return ScoredSuggestion(
                    ledger_name=name, confidence=95,
                    parent_category=target_base,
                    match_reason=f"Parent '{parent}' is a universal group -> {target_base} (95%)",
                )
            if expected_groups and any(e.lower() == pl for e in expected_groups):
                return ScoredSuggestion(
                    ledger_name=name, confidence=95,
                    parent_category=target_base,
                    match_reason=f"Parent '{parent}' is in expected groups for {target_base}",
                )

        # ── TIER 3: Common ledger name match (85%) ──
        if self._match_common_ledger_name(name, target_role):
            cat = self._categorize_by_parent(parent) or target_base
            return ScoredSuggestion(
                ledger_name=name, confidence=85,
                parent_category=cat,
                match_reason=f"Common {target_role} ledger name '{name}' (85%)",
            )

        # ── TIER 4: Pattern-based parent category match (60%) ──
        category = self._categorize_by_parent(parent)

        score = 0
        reason = ""

        if category == target_base:
            score = 60
            reason = f"Parent group '{parent}' matches {target_base} (pattern)"
        elif target_base == "GST" and category in ("GST", "LIABILITIES"):
            score = 40
            reason = f"Parent group '{parent}' partially matches GST (category={category})"
        else:
            # ── TIER 5: No match at all ──
            # One more check: maybe it's a universal ledger (Cash, P&L) under unexpected role
            if nl in {u.lower() for u in UNIVERSAL_LEDGERS}:
                return ScoredSuggestion(
                    ledger_name=name, confidence=30,
                    parent_category=category,
                    match_reason=f"Universal ledger '{name}' but parent '{parent}' doesn't match {target_base}",
                )
            return ScoredSuggestion(
                ledger_name=name, confidence=0, parent_category=category,
                match_reason=f"Parent '{parent}' is category '{category}', not '{target_base}'",
            )

        # ── Keyword bonus: 60→80 ──
        if target_role in ROLE_KEYWORDS:
            kw_list = ROLE_KEYWORDS[target_role]
            if any(kw in nl for kw in kw_list):
                score = max(score, 80)
                reason += " + name keyword match"

        # ── GST type bonus: 80→95 ──
        if target_is_gst:
            expected_gst = "Input" if target_role == "GST_INPUT" else "Output"
            if gst_type == expected_gst:
                score = max(score, 95)
                reason += f" + GST type '{gst_type}' matches"
            elif gst_type:
                score = max(score, 70)
                reason += f" + GST type '{gst_type}' (different from expected '{expected_gst}')"

        return ScoredSuggestion(
            ledger_name=name, confidence=score,
            parent_category=category,
            match_reason=reason,
        )

    def validate_selection(self, ledger_name: str, parent: str,
                           target_role: str) -> ScoredSuggestion:
        """Validate a user's ledger selection for a given role.
        Same scoring as score_ledger_for_role but takes explicit name + parent."""
        return self.score_ledger_for_role(
            {"name": ledger_name, "parent": parent, "gst_type": ""},
            target_role,
        )

    def expected_parent_groups_text(self, target_role: str) -> str:
        """Return human-readable text of expected parent groups for a role."""
        groups = self._expected_groups_for_role(target_role)
        if not groups:
            return ""
        return f"Expected under: {' / '.join(groups)}"

    def _suggest_parent_for_ledger(self, description: str, corrections: dict | None = None) -> str:
        """Given a ledger description/name, suggest the most likely parent group name.
        Uses keyword matching, role inference, and optional user corrections.
        Returns a Tally group name.

        Priority chain:
          1. User corrections (if provided) — 100% trust
          2. Well-known ledgers matching (from UNIVERSAL_GROUPS)
          3. Common ledger name matching (COMMON_LEDGER_NAMES)
          4. Context classifier inference (ML-based)
          5. Expanded keyword heuristics (comprehensive list above)
          6. Noise-stripped keyword matching
          7. Default "Purchase Accounts" fallback
        """
        dl = description.strip().lower()
        if not dl:
            return "Purchase Accounts"

        # 0. User corrections (highest priority — the CA already told us)
        if corrections and dl in {k.strip().lower() for k in corrections}:
            corrected_ledger = next(corrections[k] for k in corrections if k.strip().lower() == dl)
            # Determine parent group for the corrected ledger
            for role, names in COMMON_LEDGER_NAMES.items():
                if corrected_ledger.lower() in {n.lower() for n in names}:
                    expected = self._expected_groups_for_role(role)
                    if expected:
                        return expected[0]
            # Check well-known ledgers
            if corrected_ledger.lower() in WELL_KNOWN_LEDGERS:
                w_role = WELL_KNOWN_LEDGERS[corrected_ledger.lower()][0]
                expected = self._expected_groups_for_role(w_role)
                if expected:
                    return expected[0]
            # If we can't map the corrected ledger to a parent, return it as-is
            return "Purchase Accounts"

        # Check well-known ledgers first
        if dl in WELL_KNOWN_LEDGERS:
            w_role = WELL_KNOWN_LEDGERS[dl][0]
            expected = self._expected_groups_for_role(w_role)
            if expected:
                return expected[0]

        # Check common ledger names
        for role, names in COMMON_LEDGER_NAMES.items():
            if any(cn.lower() == dl for cn in names):
                expected = self._expected_groups_for_role(role)
                if expected:
                    return expected[0]

        # ── Keyword-based heuristics (checked BEFORE ML classifier for determinism) ──
        expense_keywords = [
            # Rent & Property
            "rent", "lease",
            # Utilities
            "electricity", "power", "water", "gas",
            "telephone", "internet", "broadband", "mobile",
            # Employees
            "salary", "wages", "bonus", "staff", "employee",
            "contractor", "consultant", "hr",
            # Marketing & Advertising
            "advertisement", "advertising", "marketing", "promotion",
            "publicity", "campaign", "brand", "digital marketing",
            "google ads", "facebook ads", "social media",
            # Maintenance & Repairs
            "maintenance", "repair", "service", "amc",
            "annual maintenance", "upkeep", "renovation",
            # Insurance
            "insurance", "premium", "policy", "coverage",
            # Professional Services
            "legal", "advocate", "lawyer", "professional fees",
            "consultancy", "consultation", "audit", "accounting",
            "tax", "gst", "tds", "filing",
            # Travel & Transportation
            "travel", "tour", "conveyance", "transport",
            "logistics", "courier", "postage", "delivery",
            "freight", "shipping",
            # Office
            "stationery", "printing", "photocopy", "office supplies",
            "furniture", "equipment",
            # Training
            "training", "development", "workshop", "seminar",
            "webinar", "course",
            # Software & Technology
            "software", "subscription", "license", "saas",
            "it services", "data", "cybersecurity",
            "it support",
            # General
            "expense", "cost", "charges", "fee", "payment",
            "commission", "brokerage",
        ]
        purchase_keywords = [
            "purchase", "raw material", "stock", "inventory", "goods",
            "hardware", "equipment", "supplies", "materials",
            "commodity", "product", "merchandise", "trading",
            "procurement", "wholesale", "component", "part",
            "packaging", "consumables",
            "cloud", "hosting", "domain", "server",
            "chair", "desk",
        ]
        sales_keywords = [
            "sales", "service", "income", "revenue",
            "consulting income", "commission income",
            "subscription revenue", "product sales",
            "service income", "professional income",
            "interest income", "other income",
        ]

        if any(kw in dl for kw in expense_keywords):
            return "Indirect Expenses"
        if any(kw in dl for kw in purchase_keywords):
            return "Purchase Accounts"
        if any(kw in dl for kw in sales_keywords):
            return "Sales Accounts"

        # ── Strip common noise words and try broader match ──
        noise_words = ["of", "and", "the", "for", "in", "to", "a", "an", "&", "-"]
        cleaned = " ".join(w for w in dl.replace("-", " ").split() if w not in noise_words)
        if cleaned != dl:
            if any(kw in cleaned for kw in expense_keywords):
                return "Indirect Expenses"
            if any(kw in cleaned for kw in purchase_keywords):
                return "Purchase Accounts"
            if any(kw in cleaned for kw in sales_keywords):
                return "Sales Accounts"

        # ── Context classifier (ML-based, least predictable — last resort) ──
        try:
            from context_classifier import ContextClassifier
            ctx = ContextClassifier()
            result = ctx.classify(description)
            if result.ledger_name and result.ledger_name != "__UNMAPPED__":
                for role, names in COMMON_LEDGER_NAMES.items():
                    if result.ledger_name.lower() in {n.lower() for n in names}:
                        expected = self._expected_groups_for_role(role)
                        if expected:
                            return expected[0]
        except Exception:
            pass

        return "Purchase Accounts"

    def discover_for_role(self, role: str, ledgers: list[dict]) -> list[ScoredSuggestion]:
        """Score all ledgers for a given role, return sorted by confidence descending."""
        scored = []
        for ledger in ledgers:
            if isinstance(ledger, str):
                ledger = {"name": ledger, "parent": "", "gst_type": ""}
            result = self.score_ledger_for_role(ledger, role)
            scored.append(result)
        scored.sort(key=lambda x: -x.confidence)
        return scored

    def discover_all(self, ledgers: list[dict]) -> dict[str, list[ScoredSuggestion]]:
        """Discover best ledgers for all known roles."""
        results = {}
        for role_key in ("PURCHASE", "SALES", "BANK", "DEBTORS", "CREDITORS", "GST_INPUT", "GST_OUTPUT"):
            suggestions = self.discover_for_role(role_key, ledgers)
            results[role_key] = suggestions[:5]  # Top 5 per role
        return results


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
