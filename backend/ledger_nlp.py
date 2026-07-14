"""Semantic NLP Ledger-Mapping Engine — token overlap + partial word match + trigram coverage."""

import re
from difflib import SequenceMatcher

_NOISE = {"FOR", "THE", "MONTH", "OF", "IN", "CONNECTION", "WITH", "SERVICES", "CHARGES", "SVC", "CHRG", "A", "AN", "AND", "TO", "ON", "AT", "BY", "PER", "AS", "IS", "WAS", "BEEN", "BEING", "FROM", "VIDE", "NO", "NOT", "OR", "BUT", "IF", "SO"}
_AMOUNT_RE = re.compile(r"\d+(\.\d+)?")
_PUNCT_RE = re.compile(r"[^A-Z0-9\s]")


def _ngrams(s: str, n: int = 3) -> set:
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def clean_and_tokenize(text: str) -> set:
    if not text:
        return set()
    cleaned = _PUNCT_RE.sub(" ", text.upper())
    return {w for w in cleaned.split() if w not in _NOISE and len(w) > 1 and not _AMOUNT_RE.fullmatch(w)}


def _partial_token_score(desc_tokens: set, ledger_tokens: set) -> float:
    """Fraction of the smaller set's tokens that are substrings of the other."""
    if not desc_tokens or not ledger_tokens:
        return 0.0
    smaller = desc_tokens if len(desc_tokens) <= len(ledger_tokens) else ledger_tokens
    larger = desc_tokens if len(desc_tokens) > len(ledger_tokens) else ledger_tokens
    hits = sum(1 for s in smaller if any(s in l or l in s for l in larger))
    return hits / len(smaller) if smaller else 0.0


def resolve_contextual_ledger_nlp(item_description: str, active_tally_ledgers: list[str]) -> str:
    """Maps fuzzy invoice descriptions to Tally ledger names using 4 signals:
    1. Token Jaccard (exact word overlap)
    2. Partial token match (substring/"stemming" — PRINT matches PRINTING)
    3. Trigram coverage (fraction of shorter string's trigrams found in both)
    4. SequenceMatcher (overall string similarity)
    """
    if not active_tally_ledgers:
        return "Suspense Account"

    desc_tokens = clean_and_tokenize(item_description)
    if not desc_tokens:
        return "Suspense Account"

    desc_str = " ".join(sorted(desc_tokens))
    desc_grams = _ngrams(desc_str)

    best_match = "Suspense Account"
    best_score = 0.0

    for ledger in active_tally_ledgers:
        ledger_tokens = clean_and_tokenize(ledger)
        if not ledger_tokens:
            continue
        ledger_str = " ".join(sorted(ledger_tokens))

        # 1. Token Jaccard
        inter = desc_tokens & ledger_tokens
        union = desc_tokens | ledger_tokens
        jaccard = len(inter) / len(union) if union else 0.0

        # 2. Partial/substring token match (handles PRINT → PRINTING, COMPUTER → COMPUT)
        partial = _partial_token_score(desc_tokens, ledger_tokens)

        # 3. Trigram coverage — fraction of the SHORTER string's trigrams present in both
        ledger_grams = _ngrams(ledger_str)
        t_inter = desc_grams & ledger_grams
        min_len = min(len(desc_grams), len(ledger_grams))
        trigram_cov = len(t_inter) / min_len if min_len else 0.0

        # 4. Sequence matcher
        seq = SequenceMatcher(None, desc_str, ledger_str).ratio()

        combined = jaccard * 0.35 + partial * 0.25 + trigram_cov * 0.25 + seq * 0.15

        if combined > best_score:
            best_score = combined
            best_match = ledger

    return best_match if best_score >= 0.18 else "Suspense Account"
