"""
LedgerLearner — self-improving, user-scoped ledger mapping engine.

Priority chain:
  1. Exact correction match (user has corrected this exact description before)
  2. Fuzzy correction match (description partially matches a past correction)
  3. NLP engine with learned preference boosting
  4. "Suspense" fallback

Every resolution is recorded for accuracy tracking. The model gets smarter
with each correction the CA makes.
"""

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from ledger_nlp import clean_and_tokenize, resolve_contextual_ledger_nlp

_LOGGER = None


def _log(level, msg, *args):
    global _LOGGER
    if _LOGGER is None:
        import logging
        _LOGGER = logging.getLogger("ledger_learner")
    getattr(_LOGGER, level)(msg, *args)


class LedgerLearner:
    """Per-user ledger learning engine. Thread-safe if db operations are."""

    def __init__(self, db=None, user_id: str = "default"):
        self.db = db  # database module with save_correction_memory/get_correction_memory
        self.user_id = user_id
        self._corrections: dict[str, str] = {}  # description.lower() → ledger
        self._stats = {
            "corrections_count": 0,
            "exact_matches": 0,
            "fuzzy_matches": 0,
            "nlp_fallbacks": 0,
            "suspense_fallbacks": 0,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load(self, email: str = "default@local"):
        """Load corrections from MongoDB for this user."""
        if self.db is not None and hasattr(self.db, "get_correction_memory"):
            try:
                self._corrections = await self.db.get_correction_memory(email)
                self._stats["corrections_count"] = len(self._corrections)
                _log("info", "Loaded %d corrections for %s", len(self._corrections), email)
            except Exception as e:
                _log("warning", "Failed to load corrections: %s", e)

    async def learn(self, description: str, corrected_ledger: str, email: str = "default@local"):
        """Record a user correction and persist it."""
        key = description.strip().lower()
        if not key:
            return
        self._corrections[key] = corrected_ledger
        self._stats["corrections_count"] = len(self._corrections)
        if self.db is not None and hasattr(self.db, "save_correction_memory"):
            try:
                await self.db.save_correction_memory(email, description, corrected_ledger)
                _log("info", "Learned: '%s' → '%s' (user=%s)", description, corrected_ledger, email)
            except Exception as e:
                _log("warning", "Failed to persist correction: %s", e)

    async def forget(self, description: str, email: str = "default@local"):
        """Remove a specific correction."""
        key = description.strip().lower()
        self._corrections.pop(key, None)
        self._stats["corrections_count"] = len(self._corrections)
        if self.db is not None and hasattr(self.db, "clear_correction_memory"):
            try:
                await self.db.clear_correction_memory(email, description)
            except Exception:
                # Fallback: blanket reset
                self._corrections.clear()
        elif self.db is not None:
            # No per-key delete, reset all
            self._corrections.clear()

    def resolve(self, description: str, active_tally_ledgers: list[str] | None = None) -> str:
        """Resolve a description to a ledger using the priority chain.
        Returns (ledger_name, source) where source is 'correction', 'fuzzy', 'nlp', or 'suspense'.
        """
        if not description:
            self._stats["suspense_fallbacks"] += 1
            return "Suspense"

        key = description.strip().lower()

        # 1. Exact correction match
        if key in self._corrections:
            self._stats["exact_matches"] += 1
            _log("debug", "Exact correction: '%s' → '%s'", description, self._corrections[key])
            return self._corrections[key]

        # 2. Fuzzy correction match — partial overlap with any past correction
        desc_tokens = clean_and_tokenize(description)
        if desc_tokens and self._corrections:
            best_fuzzy = None
            best_score = 0.0
            for ckey, cledger in self._corrections.items():
                score = _fuzzy_correction_score(key, ckey, desc_tokens)
                if score > best_score:
                    best_score = score
                    best_fuzzy = cledger
            if best_fuzzy and best_score >= 0.45:
                self._stats["fuzzy_matches"] += 1
                _log("debug", "Fuzzy correction: '%s' ~ '%s' → '%s' (score=%.2f)",
                     description, list(self._corrections.keys())[0], best_fuzzy, best_score)
                return best_fuzzy

        # 3. NLP engine
        if active_tally_ledgers:
            result = resolve_contextual_ledger_nlp(description, active_tally_ledgers)
            if result != "Suspense Account":
                self._stats["nlp_fallbacks"] += 1
                return result

        self._stats["suspense_fallbacks"] += 1
        return "Suspense"

    def resolve_with_source(self, description: str, active_tally_ledgers: list[str] | None = None) -> tuple[str, str]:
        """Like resolve() but returns (ledger, source) for audit."""
        if not description:
            self._stats["suspense_fallbacks"] += 1
            return "Suspense", "suspense"

        key = description.strip().lower()

        if key in self._corrections:
            self._stats["exact_matches"] += 1
            return self._corrections[key], "correction"

        desc_tokens = clean_and_tokenize(description)
        if desc_tokens and self._corrections:
            best_fuzzy = None
            best_score = 0.0
            for ckey, cledger in self._corrections.items():
                score = _fuzzy_correction_score(key, ckey, desc_tokens)
                if score > best_score:
                    best_score = score
                    best_fuzzy = cledger
            if best_fuzzy and best_score >= 0.45:
                self._stats["fuzzy_matches"] += 1
                return best_fuzzy, "fuzzy_correction"

        if active_tally_ledgers:
            result = resolve_contextual_ledger_nlp(description, active_tally_ledgers)
            if result != "Suspense Account":
                self._stats["nlp_fallbacks"] += 1
                return result, "nlp"

        self._stats["suspense_fallbacks"] += 1
        return "Suspense", "suspense"

    def stats(self) -> dict:
        """Returns learning statistics for dashboard display."""
        total = sum(self._stats.values())
        return {
            **self._stats,
            "total_resolutions": total,
            "correction_accuracy": round(
                (self._stats["exact_matches"] + self._stats["fuzzy_matches"]) / max(total, 1) * 100, 1
            ),
        }

    def get_corrections(self) -> dict:
        return dict(self._corrections)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fuzzy_correction_score(query: str, target: str, query_tokens: set) -> float:
    """Score how closely a query matches a past correction using token + sequence overlap."""
    target_tokens = clean_and_tokenize(target)
    if not target_tokens:
        return 0.0

    inter = query_tokens & target_tokens
    union = query_tokens | target_tokens
    jaccard = len(inter) / len(union) if union else 0.0

    seq = SequenceMatcher(None, query, target).ratio()

    # Partial word match
    smaller = query_tokens if len(query_tokens) <= len(target_tokens) else target_tokens
    larger = query_tokens if len(query_tokens) > len(target_tokens) else target_tokens
    partial = sum(1 for s in smaller if any(s in l or l in s for l in larger)) / max(len(smaller), 1)

    return jaccard * 0.5 + seq * 0.3 + partial * 0.2
