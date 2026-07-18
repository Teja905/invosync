"""Deterministic chart-of-accounts classifier.

Maps a Tally ledger (and its parent group) to one of four accounting
categories used for reporting:

    Asset | Liability | Income | Expense

The classifier is rule-based on Tally's 28 universal groups — NOT keyword
guessing and NOT AI. Parent group is the most reliable signal because the
generator already knows which group each ledger is created under (e.g.
"Purchase Accounts", "Sundry Creditors", "Bank Accounts", "Duties & Taxes").

Keyword fallback is only used when a parent group is unknown (e.g. a ledger
the user already had in Tally before import) and is intentionally conservative:
anything it cannot confidently classify falls back to Expense (a CA can
re-tag later). This keeps reports balanced and never silently drops a line.
"""

from typing import Optional

# Tally's 28 universal groups -> account category.
# 15 primary groups + 13 sub-groups. Each maps cleanly to a balance-sheet /
# P&L side. Duties & Taxes is a Liability (GST payable is owed to govt).
GROUP_TO_TYPE = {
    # --- Assets ---
    "Cash in Hand": "Asset",
    "Bank Accounts": "Asset",
    "Deposits (Asset)": "Asset",
    "Loans & Advances (Asset)": "Asset",
    "Stock-in-Hand": "Asset",
    "Sundry Debtors": "Asset",
    "Fixed Assets": "Asset",
    "Investments": "Asset",
    # --- Liabilities ---
    "Capital Account": "Liability",
    "Reserves & Surplus": "Liability",
    "Loans (Liability)": "Liability",
    "Current Liabilities": "Liability",
    "Duties & Taxes": "Liability",
    "Provisions": "Liability",
    "Sundry Creditors": "Liability",
    # --- Income ---
    "Sales Accounts": "Income",
    "Indirect Income": "Income",
    "Direct Income": "Income",
    # --- Expense ---
    "Purchase Accounts": "Expense",
    "Direct Expenses": "Expense",
    "Indirect Expenses": "Expense",
}

# Sub-group parents (capitalised/aliased in real Tally) mapped explicitly.
GROUP_ALIASES = {
    "deposits": "Deposits (Asset)",
    "loans and advances": "Loans & Advances (Asset)",
    "loans": "Loans (Liability)",
    "sundry creditors": "Sundry Creditors",
    "sundry debtors": "Sundry Debtors",
    "duties and taxes": "Duties & Taxes",
    "duties & taxes": "Duties & Taxes",
    "purchase accounts": "Purchase Accounts",
    "sales accounts": "Sales Accounts",
    "bank accounts": "Bank Accounts",
    "cash in hand": "Cash in Hand",
    "fixed assets": "Fixed Assets",
    "current liabilities": "Current Liabilities",
    "capital account": "Capital Account",
    "indirect income": "Indirect Income",
    "direct income": "Direct Income",
    "direct expenses": "Direct Expenses",
    "indirect expenses": "Indirect Expenses",
    "stock in hand": "Stock-in-Hand",
    "reserves and surplus": "Reserves & Surplus",
    "investments": "Investments",
    "provisions": "Provisions",
}

# Conservative keyword fallback — only when no parent group is known.
# Maps ledger-name tokens -> category. Empty match -> Expense (default).
KEYWORD_FALLBACK = [
    ("income", "Income"),
    ("revenue", "Income"),
    ("sales", "Income"),
    ("service", "Income"),
    ("commission received", "Income"),
    ("interest received", "Income"),
    ("bank", "Asset"),
    ("cash", "Asset"),
    ("debtor", "Asset"),
    ("receivable", "Asset"),
    ("fixed asset", "Asset"),
    ("furniture", "Asset"),
    ("vehicle", "Asset"),
    ("capital", "Liability"),
    ("creditor", "Liability"),
    ("payable", "Liability"),
    ("loan", "Liability"),
    ("tds", "Liability"),
    ("gst", "Liability"),
    ("tax", "Liability"),
    ("provision", "Liability"),
    ("purchase", "Expense"),
    ("expense", "Expense"),
    ("salary", "Expense"),
    ("rent", "Expense"),
    ("freight", "Expense"),
    ("commission", "Expense"),
    ("interest", "Expense"),
    ("electricity", "Expense"),
    ("telephone", "Expense"),
    ("insurance", "Expense"),
    ("professional", "Expense"),
    ("legal", "Expense"),
]

DEFAULT_TYPE = "Expense"


def classify_ledger(ledger: str, parent_group: Optional[str] = None) -> str:
    """Return the account type for a ledger, preferring its parent group."""
    if parent_group:
        pg = parent_group.strip()
        if pg in GROUP_TO_TYPE:
            return GROUP_TO_TYPE[pg]
        alias = GROUP_ALIASES.get(pg.lower())
        if alias and alias in GROUP_TO_TYPE:
            return GROUP_TO_TYPE[alias]
    # Fallback: keyword scan on the ledger name (conservative).
    name = (ledger or "").lower()
    for token, atype in KEYWORD_FALLBACK:
        if token in name:
            return atype
    return DEFAULT_TYPE


def is_balance_sheet_type(account_type: str) -> bool:
    return account_type in ("Asset", "Liability")


def is_pnl_type(account_type: str) -> bool:
    return account_type in ("Income", "Expense")
