"""Reporting endpoints derived from persisted journal lines.

These are *verification* dashboards, not an attempt to replace Tally's full
reporting stack. They prove the generated accounting is internally consistent
(Trial Balance balances to zero) and let a CA sanity-check P&L / Balance Sheet
before trusting the import.

All figures come from `journal_lines` — the single source of truth captured at
XML-generation time — never from re-parsing Tally XML. Reversed (undone)
entries are excluded so reports never double-count.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

import database as db
from api.deps import get_authenticated_user
from core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


class ReportRequest(BaseModel):
    company_id: Optional[str] = None
    client_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def _base_query(user_id: str, req: ReportRequest) -> dict:
    q = {"user_id": user_id, "reversed": False}
    if req.company_id:
        q["company_id"] = req.company_id
    if req.client_id is not None:
        q["client_id"] = req.client_id
    if req.start_date or req.end_date:
        q["date"] = {}
        if req.start_date:
            q["date"]["$gte"] = req.start_date
        if req.end_date:
            q["date"]["$lte"] = req.end_date
    return q


@router.post("/trial-balance")
async def trial_balance(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Aggregate ledger debits/credits. `is_balanced` must always be true."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    lines = await db.list_journal_lines(
        user_id=user_id,
        company_id=req.company_id,
        client_id=req.client_id,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    rows = {}
    total_debit = total_credit = 0.0
    for ln in lines:
        if ln.get("reversed"):
            continue
        ledger = ln["ledger"]
        d = float(ln.get("debit", 0.0) or 0.0)
        c = float(ln.get("credit", 0.0) or 0.0)
        row = rows.setdefault(ledger, {"ledger": ledger, "debit": 0.0, "credit": 0.0, "account_type": ln.get("account_type", "Expense")})
        row["debit"] += d
        row["credit"] += c
        total_debit += d
        total_credit += c
    tb_rows = [
        {"ledger": r["ledger"], "debit": round(r["debit"], 2), "credit": round(r["credit"], 2), "account_type": r["account_type"]}
        for r in rows.values()
    ]
    diff = round(total_debit - total_credit, 2)
    return {
        "rows": sorted(tb_rows, key=lambda x: x["ledger"]),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "difference": diff,
        "is_balanced": abs(diff) < 0.01,
    }


@router.post("/pnl")
async def profit_and_loss(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Income minus Expenses for the period (derived from typed ledgers)."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    lines = await db.list_journal_lines(
        user_id=user_id,
        company_id=req.company_id,
        client_id=req.client_id,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    income = expense = 0.0
    income_lines = {}
    expense_lines = {}
    for ln in lines:
        if ln.get("reversed"):
            continue
        atype = ln.get("account_type", "Expense")
        d = float(ln.get("debit", 0.0) or 0.0)
        c = float(ln.get("credit", 0.0) or 0.0)
        net = c - d  # credit increases income/liability, debit increases expense/asset
        if atype == "Income":
            income += net
            income_lines[ln["ledger"]] = round(income_lines.get(ln["ledger"], 0.0) + net, 2)
        elif atype == "Expense":
            expense += -net
            expense_lines[ln["ledger"]] = round(expense_lines.get(ln["ledger"], 0.0) - net, 2)
    profit = round(income - expense, 2)
    return {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "profit": profit,
        "income_breakdown": [{"ledger": k, "amount": v} for k, v in income_lines.items()],
        "expense_breakdown": [{"ledger": k, "amount": v} for k, v in expense_lines.items()],
    }


@router.post("/balance-sheet")
async def balance_sheet(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Assets vs Liabilities + (derived) Capital for the period."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    lines = await db.list_journal_lines(
        user_id=user_id,
        company_id=req.company_id,
        client_id=req.client_id,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    assets = liabilities = 0.0
    asset_lines = {}
    liability_lines = {}
    for ln in lines:
        if ln.get("reversed"):
            continue
        atype = ln.get("account_type", "Expense")
        d = float(ln.get("debit", 0.0) or 0.0)
        c = float(ln.get("credit", 0.0) or 0.0)
        net = d - c  # debit increases asset, credit increases liability
        if atype == "Asset":
            assets += net
            asset_lines[ln["ledger"]] = round(asset_lines.get(ln["ledger"], 0.0) + net, 2)
        elif atype == "Liability":
            liabilities += -net
            liability_lines[ln["ledger"]] = round(liability_lines.get(ln["ledger"], 0.0) - net, 2)
    return {
        "assets": round(assets, 2),
        "liabilities": round(liabilities, 2),
        "asset_breakdown": [{"ledger": k, "amount": v} for k, v in asset_lines.items()],
        "liability_breakdown": [{"ledger": k, "amount": v} for k, v in liability_lines.items()],
        "balanced": abs(round(assets - liabilities, 2)) < 0.01,
    }
