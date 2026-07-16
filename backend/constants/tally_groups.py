"""Tally's 28 universal groups (15 primary + 13 sub) that exist in every Tally Prime instance.
These names are identical across all Indian Tally companies — same spelling, same hierarchy.
Every time you categorize a ledger by parent group, check here first for 95% confidence."""

# ── The 28 universal groups ──

PRIMARY_GROUPS = {
    "Current Assets",
    "Current Liabilities",
    "Fixed Assets",
    "Investments",
    "Loans & Advances (Assets)",
    "Miscellaneous Expenses (Assets)",
    "Profit & Loss A/c",
    "Reserves & Surplus",
    "Share Capital",
    "Secured Loans",
    "Stock-in-hand",
    "Suspense A/c",
    "Unsecured Loans",
    "Direct Incomes",
    "Direct Expenses",
}

SUB_GROUPS = {
    "Indirect Incomes",
    "Indirect Expenses",
    "Sales Accounts",
    "Purchase Accounts",
    "Duties & Taxes",
    "Bank Accounts",
    "Bank OD A/c",
    "Cash-in-hand",
    "Sundry Debtors",
    "Sundry Creditors",
    "Branch / Divisions",
    "Capital Account",
    "Revenue Accounts",
}

UNIVERSAL_GROUPS = PRIMARY_GROUPS | SUB_GROUPS

# Which PRIMARY group each sub-group falls under
SUB_GROUP_PARENT = {
    "Indirect Incomes": "Profit & Loss A/c",
    "Indirect Expenses": "Profit & Loss A/c",
    "Sales Accounts": "Direct Incomes",
    "Purchase Accounts": "Direct Expenses",
    "Duties & Taxes": "Current Liabilities",
    "Bank Accounts": "Current Assets",
    "Bank OD A/c": "Current Liabilities",
    "Cash-in-hand": "Current Assets",
    "Sundry Debtors": "Current Assets",
    "Sundry Creditors": "Current Liabilities",
    "Branch / Divisions": "Current Assets",
    "Capital Account": "Reserves & Surplus",
    "Revenue Accounts": "Direct Incomes",
}

# ── Group → canonical role mapping (the Suvit secret) ──

GROUP_TO_ROLE = {
    "Purchase Accounts": "PURCHASE",
    "Direct Expenses": "PURCHASE",
    "Sales Accounts": "SALES",
    "Direct Incomes": "SALES",
    "Revenue Accounts": "SALES",
    "Bank Accounts": "BANK",
    "Bank OD A/c": "BANK",
    "Sundry Debtors": "DEBTORS",
    "Sundry Creditors": "CREDITORS",
    "Duties & Taxes": "GST",
    "Cash-in-hand": "CASH",
    "Stock-in-hand": "INVENTORY",
    "Fixed Assets": "FIXED_ASSETS",
    "Current Assets": "ASSETS",
    "Current Liabilities": "LIABILITIES",
    "Indirect Expenses": "EXPENSE",
    "Indirect Incomes": "INCOME",
}

# Reverse map: canonical role → expected universal groups
ROLE_TO_EXPECTED_GROUPS = {
    "PURCHASE": ["Purchase Accounts", "Direct Expenses"],
    "SALES": ["Sales Accounts", "Direct Incomes", "Revenue Accounts"],
    "BANK": ["Bank Accounts", "Bank OD A/c"],
    "DEBTORS": ["Sundry Debtors"],
    "CREDITORS": ["Sundry Creditors"],
    "GST": ["Duties & Taxes"],
    "CASH": ["Cash-in-hand"],
    "INVENTORY": ["Stock-in-hand"],
    "FIXED_ASSETS": ["Fixed Assets"],
    "EXPENSE": ["Indirect Expenses"],
    "INCOME": ["Indirect Incomes"],
}

# ── Common ledger names per role ──

COMMON_LEDGER_NAMES = {
    "PURCHASE": [
        "Purchase", "Purchases", "Purchase A/c", "Purchase Account",
        "Raw Material Purchase", "Trading Purchase", "Trading Account",
        "Local Purchases", "Interstate Purchases", "Inter State Purchases",
        "Cost of Goods Sold", "COGS", "Cost Of Goods Sold",
    ],
    "SALES": [
        "Sales", "Sales A/c", "Sales Account", "Sales Revenue",
        "Local Sales", "Interstate Sales", "Inter State Sales",
        "Service Income", "Consulting Income", "Service Revenue",
    ],
    "BANK": [
        "Bank", "Bank A/c", "Bank Account", "Current Account",
        "SBI", "State Bank of India", "HDFC Bank", "ICICI Bank",
        "Axis Bank", "Kotak Bank", "Yes Bank", "Canara Bank",
        "PNB", "Punjab National Bank", "BOB", "Bank of Baroda",
    ],
    "DEBTORS": [
        "Sundry Debtors", "Debtors", "Accounts Receivable",
        "Trade Receivables", "Receivables", "Sundry Debtors (Control)",
    ],
    "CREDITORS": [
        "Sundry Creditors", "Creditors", "Accounts Payable",
        "Trade Payables", "Payables", "Sundry Creditors (Control)",
    ],
    "CASH": [
        "Cash", "Cash-in-hand", "Petty Cash", "Cash In Hand",
    ],
    "INVENTORY": [
        "Stock-in-hand", "Inventory", "Closing Stock",
        "Stock In Hand",
    ],
    "FIXED_ASSETS": [
        "Fixed Assets", "Plant & Machinery", "Office Equipment",
        "Computer Equipment", "Furniture & Fixtures", "Vehicles",
        "Land & Building", "Buildings",
    ],
    "EXPENSE": [
        "Indirect Expenses", "Office Expenses", "Salary", "Salaries",
        "Rent", "Rent Expenses", "Electricity", "Electricity Expenses",
        "Telephone Expenses", "Travel Expenses", "Legal Expenses",
        "Audit Fees", "Professional Charges", "Professional Fees",
        "Advertisement Expenses", "Advertisement",
    ],
    "INCOME": [
        "Indirect Incomes", "Interest Income", "Commission Income",
        "Discount Received", "Other Income", "Miscellaneous Income",
    ],
}

# ── Default ledgers for initial setup ──

DEFAULT_LEDGERS = {
    "PURCHASE": "Purchase",
    "SALES": "Sales",
    "BANK": "Bank",
    "DEBTORS": "Sundry Debtors",
    "CREDITORS": "Sundry Creditors",
    "GST_INPUT": "Input CGST @ 9%",
    "GST_OUTPUT": "Output CGST @ 9%",
    "CASH": "Cash",
    "INVENTORY": "Stock-in-hand",
    "EXPENSE": "Indirect Expenses",
    "INCOME": "Indirect Incomes",
}

# ── 2 universal ledgers — exist in every Tally company ──

UNIVERSAL_LEDGERS = {
    "Cash",
    "Profit & Loss A/c",
}


# ── Tally XML Escape ──

def EscapeXmlForTally(s: str) -> str:
    """Escape a string for use in Tally XML content."""
    return (s
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))
