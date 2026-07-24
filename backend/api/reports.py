"""Reporting endpoints derived from persisted journal lines.

These are *verification* dashboards, not an attempt to replace Tally's full
reporting stack. They prove the generated accounting is internally consistent
(Trial Balance balances to zero) and let a CA sanity-check P&L / Balance Sheet
before trusting the import.

All figures come from `journal_lines` — the single source of truth captured at
XML-generation time — never from re-parsing Tally XML. Reversed (undone)
entries are excluded so reports never double-count.

Caching: 60-second TTL in-memory cache (no Redis). Invalidate on new XML gen.
"""

import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import database as db
from api.deps import get_authenticated_user
from core.cache import report_cache
from core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


class ReportRequest(BaseModel):
    company_id: Optional[str] = None
    client_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class TallyTBRow(BaseModel):
    ledger: str
    debit: float = 0.0
    credit: float = 0.0


class TallyTBPush(BaseModel):
    company_id: str
    rows: list[TallyTBRow]


def _cache_key(user_id: str, req: ReportRequest, report_type: str) -> str:
    raw = json.dumps({
        "user_id": user_id,
        "company_id": req.company_id,
        "client_id": req.client_id,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "type": report_type,
    }, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _base_query(user_id: str, req: ReportRequest) -> dict:
    q = {"user_id": user_id}
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


async def _load_lines(user_id: str, req: ReportRequest) -> list:
    """Load journal lines with reversed_filter=True so the compound index is used."""
    return await db.list_journal_lines(
        user_id=user_id,
        company_id=req.company_id,
        client_id=req.client_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reversed_filter=True,
    )


@router.post("/trial-balance")
async def trial_balance(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Aggregate ledger debits/credits. `is_balanced` must always be true."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    key = _cache_key(user_id, req, "tb")

    async def _fetch():
        lines = await _load_lines(user_id, req)
        rows = {}
        total_debit = total_credit = 0.0
        for ln in lines:
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

    return await report_cache.get_or_set(key, _fetch)


@router.post("/pnl")
async def profit_and_loss(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Income minus Expenses for the period (derived from typed ledgers)."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    key = _cache_key(user_id, req, "pnl")

    async def _fetch():
        lines = await _load_lines(user_id, req)
        income = expense = 0.0
        income_lines = {}
        expense_lines = {}
        for ln in lines:
            atype = ln.get("account_type", "Expense")
            d = float(ln.get("debit", 0.0) or 0.0)
            c = float(ln.get("credit", 0.0) or 0.0)
            net = c - d
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

    return await report_cache.get_or_set(key, _fetch)


@router.post("/balance-sheet")
async def balance_sheet(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Assets vs Liabilities + (derived) Capital for the period."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    key = _cache_key(user_id, req, "bs")

    async def _fetch():
        lines = await _load_lines(user_id, req)
        assets = liabilities = 0.0
        asset_lines = {}
        liability_lines = {}
        for ln in lines:
            atype = ln.get("account_type", "Expense")
            d = float(ln.get("debit", 0.0) or 0.0)
            c = float(ln.get("credit", 0.0) or 0.0)
            net = d - c
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

    return await report_cache.get_or_set(key, _fetch)


@router.post("/client-dashboard")
async def client_dashboard(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Aggregated dashboard for client portal: TB summary, P&L, BS in one call."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    key = _cache_key(user_id, req, "dashboard")

    async def _fetch():
        lines = await _load_lines(user_id, req)
        if not lines:
            return {
                "total_invoices": 0,
                "trial_balance": {"rows": [], "is_balanced": True},
                "pnl": {"income": 0, "expense": 0, "profit": 0},
                "balance_sheet": {"assets": 0, "liabilities": 0, "balanced": True},
            }

        tb = {}
        income = expense = 0.0
        assets = liabilities = 0.0
        unique_invoices = set()

        for ln in lines:
            ledger = ln["ledger"]
            atype = ln.get("account_type", "Expense")
            d = float(ln.get("debit", 0.0) or 0.0)
            c = float(ln.get("credit", 0.0) or 0.0)
            net_pnl = c - d
            net_bs = d - c

            row = tb.setdefault(ledger, {"debit": 0.0, "credit": 0.0})
            row["debit"] += d
            row["credit"] += c

            if atype == "Income":
                income += net_pnl
            elif atype == "Expense":
                expense += -net_pnl
            elif atype == "Asset":
                assets += net_bs
            elif atype == "Liability":
                liabilities += -net_bs

            if ln.get("invoice_id"):
                unique_invoices.add(str(ln["invoice_id"]))

        total_d = sum(r["debit"] for r in tb.values())
        total_c = sum(r["credit"] for r in tb.values())
        diff = round(total_d - total_c, 2)

        return {
            "total_invoices": len(unique_invoices),
            "trial_balance": {
                "rows": [
                    {"ledger": k, "debit": round(v["debit"], 2), "credit": round(v["credit"], 2)}
                    for k, v in sorted(tb.items())
                ],
                "is_balanced": abs(diff) < 0.01,
            },
            "pnl": {
                "income": round(income, 2),
                "expense": round(expense, 2),
                "profit": round(income - expense, 2),
            },
            "balance_sheet": {
                "assets": round(assets, 2),
                "liabilities": round(liabilities, 2),
                "balanced": abs(round(assets - liabilities, 2)) < 0.01,
            },
        }

    return await report_cache.get_or_set(key, _fetch)


# ---------------------------------------------------------------------------
# Diff View: InvoSync journal_lines vs Tally Trial Balance
# ---------------------------------------------------------------------------

async def _get_invosync_tb(user_id: str, req: ReportRequest) -> dict:
    """Get InvoSync trial balance from journal_lines."""
    lines = await _load_lines(user_id, req)
    rows = {}
    for ln in lines:
        ledger = ln["ledger"]
        d = float(ln.get("debit", 0.0) or 0.0)
        c = float(ln.get("credit", 0.0) or 0.0)
        row = rows.setdefault(ledger, {"ledger": ledger, "debit": 0.0, "credit": 0.0})
        row["debit"] += d
        row["credit"] += c
    return {r["ledger"]: {"debit": round(r["debit"], 2), "credit": round(r["credit"], 2)} for r in rows.values()}


@router.post("/api/v3/sync/tally-tb")
async def push_tally_tb(body: TallyTBPush, current_user: dict = Depends(get_authenticated_user)):
    """Connector pushes Tally trial balance data for diff comparison."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    rows = [{"ledger": r.ledger, "debit": r.debit, "credit": r.credit} for r in body.rows]
    snap_id = await db.store_tally_snapshot(user_id, body.company_id, rows)
    if not snap_id:
        return {"ok": False, "message": "Database not available"}
    logger.info("Tally TB snapshot stored: company=%s rows=%d snap_id=%s", body.company_id, len(rows), snap_id)
    return {"ok": True, "snapshot_id": snap_id, "rows": len(rows)}


@router.post("/trial-balance/diff")
async def trial_balance_diff(req: ReportRequest, current_user: dict = Depends(get_authenticated_user)):
    """Compare InvoSync journal_lines TB against Tally's TB snapshot. Shows match/mismatch per ledger."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    company_id = req.company_id or ""

    invosync_tb = await _get_invosync_tb(user_id, req)
    tally_snap = await db.get_latest_tally_snapshot(user_id, company_id) if company_id else None

    if not tally_snap:
        return {
            "status": "no_tally_data",
            "message": "No Tally TB snapshot available. Push Tally TB via connector first.",
            "invosync_rows": [{"ledger": k, "debit": v["debit"], "credit": v["credit"]} for k, v in sorted(invosync_tb.items())],
            "tally_rows": [],
            "diff": [],
            "match_count": 0,
            "mismatch_count": 0,
            "only_in_invosync": [],
            "only_in_tally": [],
        }

    tally_tb = {r["ledger"]: {"debit": r.get("debit", 0), "credit": r.get("credit", 0)} for r in tally_snap.get("rows", [])}

    all_ledgers = set(invosync_tb.keys()) | set(tally_tb.keys())
    diff = []
    match_count = 0
    mismatch_count = 0
    only_in_invosync = []
    only_in_tally = []

    for ledger in sorted(all_ledgers):
        iv = invosync_tb.get(ledger)
        tl = tally_tb.get(ledger)
        if iv and tl:
            d_diff = round(iv["debit"] - tl["debit"], 2)
            c_diff = round(iv["credit"] - tl["credit"], 2)
            matched = abs(d_diff) < 0.01 and abs(c_diff) < 0.01
            if matched:
                match_count += 1
            else:
                mismatch_count += 1
            diff.append({
                "ledger": ledger,
                "invosync_debit": iv["debit"],
                "invosync_credit": iv["credit"],
                "tally_debit": tl["debit"],
                "tally_credit": tl["credit"],
                "debit_diff": d_diff,
                "credit_diff": c_diff,
                "matched": matched,
            })
        elif iv:
            only_in_invosync.append(ledger)
            mismatch_count += 1
        elif tl:
            only_in_tally.append(ledger)
            mismatch_count += 1

    total_diff = abs(sum(r["debit_diff"] for r in diff)) + abs(sum(r["credit_diff"] for r in diff))

    return {
        "status": "compared",
        "snapshot_date": tally_snap.get("created_at"),
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "total_diff": round(total_diff, 2),
        "all_match": mismatch_count == 0,
        "diff": diff,
        "only_in_invosync": only_in_invosync,
        "only_in_tally": only_in_tally,
        "invosync_total_debit": round(sum(v["debit"] for v in invosync_tb.values()), 2),
        "invosync_total_credit": round(sum(v["credit"] for v in invosync_tb.values()), 2),
        "tally_total_debit": round(sum(v["debit"] for v in tally_tb.values()), 2),
        "tally_total_credit": round(sum(v["credit"] for v in tally_tb.values()), 2),
    }


class FirmDashboardRequest(BaseModel):
    """Request body for firm-level dashboard."""
    company_id: Optional[str] = None


@router.post("/firm-dashboard")
async def firm_dashboard(req: FirmDashboardRequest, current_user: dict = Depends(get_authenticated_user)):
    """CA firm-level dashboard showing all clients with compliance status.

    Returns per-client summary: invoice count, total amount, TDS status,
    last activity, compliance health score.
    """
    user_id = current_user.get("user_id", current_user.get("email", ""))

    # Load all invoices for this user/firm
    query = {"user_id": user_id}
    if req.company_id:
        query["company_id"] = req.company_id

    try:
        if db.invoices is None:
            return {"clients": [], "summary": {}}
        cursor = db.invoices.find(query, sort=[("created_at", -1)])
        all_invoices = await cursor.to_list(length=10000)
    except Exception:
        return {"clients": [], "summary": {}}

    # Group by client
    clients = {}
    for inv in all_invoices:
        cid = str(inv.get("client_id", "unassigned"))
        cname = inv.get("client_name", "Unassigned")
        company = inv.get("company_name", "")

        if cid not in clients:
            clients[cid] = {
                "client_id": cid,
                "client_name": cname,
                "company_name": company,
                "invoice_count": 0,
                "total_amount": 0.0,
                "total_tax": 0.0,
                "total_tds": 0.0,
                "draft_count": 0,
                "validated_count": 0,
                "exported_count": 0,
                "low_confidence_count": 0,
                "last_invoice_date": None,
                "voucher_types": {},
                "gst_types": {},
            }

        c = clients[cid]
        c["invoice_count"] += 1
        extracted = inv.get("extracted", {}) or {}
        c["total_amount"] += float(extracted.get("total_amount", 0) or 0)
        c["total_tax"] += float(extracted.get("total_tax", 0) or 0)
        c["total_tds"] += float(extracted.get("tds_amount", 0) or 0)

        status = inv.get("status", "draft")
        if status == "draft":
            c["draft_count"] += 1
        elif status == "validated":
            c["validated_count"] += 1
        elif status == "exported":
            c["exported_count"] += 1

        confidence = float(extracted.get("confidence", 1.0) or 1.0)
        if confidence < 0.7:
            c["low_confidence_count"] += 1

        inv_date = inv.get("created_at")
        if inv_date and (not c["last_invoice_date"] or str(inv_date) > str(c["last_invoice_date"])):
            c["last_invoice_date"] = inv_date

        vtype = extracted.get("voucher_type", "Purchase")
        c["voucher_types"][vtype] = c["voucher_types"].get(vtype, 0) + 1

        gst = extracted.get("gst_type", "CGST_SGST")
        c["gst_types"][gst] = c["gst_types"].get(gst, 0) + 1

    # Compute compliance health score per client
    for cid, c in clients.items():
        total = c["invoice_count"] or 1
        # Health: low confidence ratio, review progress, TDS completeness
        confidence_penalty = (c["low_confidence_count"] / total) * 30
        review_score = (c["validated_count"] + c["exported_count"]) / total * 40
        draft_penalty = (c["draft_count"] / total) * 30
        tds_score = 0.0
        if c["total_tds"] > 0:
            tds_score = 30  # TDS was specified — good
        elif c["total_amount"] > 50000:
            tds_score = 10  # Large amount but no TDS — might need review

        health = max(0, min(100, int(review_score + tds_score - confidence_penalty - draft_penalty + 30)))
        c["compliance_health"] = health

    # Firm summary
    total_invoices = sum(c["invoice_count"] for c in clients.values())
    total_amount = sum(c["total_amount"] for c in clients.values())
    total_draft = sum(c["draft_count"] for c in clients.values())
    total_validated = sum(c["validated_count"] for c in clients.values())
    total_exported = sum(c["exported_count"] for c in clients.values())
    avg_health = sum(c["compliance_health"] for c in clients.values()) / max(len(clients), 1)

    return {
        "clients": sorted(clients.values(), key=lambda x: x["total_amount"], reverse=True),
        "summary": {
            "total_clients": len(clients),
            "total_invoices": total_invoices,
            "total_amount": round(total_amount, 2),
            "total_tax": round(sum(c["total_tax"] for c in clients.values()), 2),
            "total_tds": round(sum(c["total_tds"] for c in clients.values()), 2),
            "draft_pending": total_draft,
            "validated_ready": total_validated,
            "exported_to_tally": total_exported,
            "avg_compliance_health": round(avg_health, 1),
        },
    }


class GSTRReconRequest(BaseModel):
    """Request body for GSTR reconciliation."""
    company_id: Optional[str] = None
    client_id: Optional[int] = None
    gstr_data: dict = {}  # GSTR-2A/2B JSON from GST portal
    period: str = ""  # e.g. "04-2024" (April 2024)


@router.post("/gstr-reconcile")
async def gstr_reconcile(req: GSTRReconRequest, current_user: dict = Depends(get_authenticated_user)):
    """Reconcile book invoices against GSTR-2A/2B data from the GST portal.

    Upload GSTR-2A/2B JSON from the GST portal, and this endpoint matches
    it against invoices captured in InvoSync. Shows matched, mismatched,
    and missing entries for CA review.
    """
    from gstr_reconciler import reconcile, parse_gstr2a_json

    user_id = current_user.get("user_id", current_user.get("email", ""))

    # Load book invoices
    try:
        if db.invoices is None:
            return {"error": "Database not available"}
        query = {"user_id": user_id}
        if req.company_id:
            query["company_id"] = req.company_id
        if req.client_id is not None:
            query["client_id"] = req.client_id
        cursor = db.invoices.find(query)
        all_invoices = await cursor.to_list(length=10000)
    except Exception:
        return {"error": "Failed to load invoices"}

    # Convert to reconciler format
    book_invoices = []
    for inv in all_invoices:
        extracted = inv.get("extracted", {}) or {}
        book_invoices.append({
            "vendor_gstin": extracted.get("vendor_gstin", ""),
            "invoice_number": extracted.get("invoice_number", ""),
            "invoice_date": extracted.get("invoice_date", ""),
            "total_amount": float(extracted.get("total_amount", 0) or 0),
            "total_taxable_value": float(extracted.get("total_taxable_value", 0) or 0),
            "total_tax": float(extracted.get("total_tax", 0) or 0),
        })

    # Parse GSTR data
    gstr_invoices = parse_gstr2a_json(req.gstr_data)

    if not gstr_invoices:
        return {
            "error": "No invoices found in GSTR data. Ensure the JSON follows the GST portal format with 'b2b' section.",
        }

    # Run reconciliation
    report = reconcile(book_invoices, gstr_invoices)

    return report.to_dict()
