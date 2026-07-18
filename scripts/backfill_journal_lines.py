"""One-off backfill: derive journal lines for already-generated invoices.

Existing invoices in the DB have `xml_content` (Tally XML) but no `journal_lines`.
This script parses each voucher's ALLLEDGERENTRIES.LIST and writes the legs into
the `journal_lines` collection (the single source of truth for reporting), tagging
each ledger with an account type via the deterministic classifier.

Idempotent: re-running overwrites existing legs per invoice (keyed by invoice_id).

Usage:
    python scripts/backfill_journal_lines.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import xml.etree.ElementTree as ET

import database as db
from ledger_classifier import classify_ledger
from company_config import CompanyConfig


def _parse_voucher_legs(xml_str: str):
    """Return list of {ledger, debit, credit} from Tally XML voucher legs."""
    legs = []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return legs
    for entry in root.iter("ALLLEDGERENTRIES.LIST"):
        name_el = entry.find("LEDGERNAME")
        amt_el = entry.find("AMOUNT")
        if name_el is None or amt_el is None:
            continue
        ledger = (name_el.text or "").strip()
        if not ledger:
            continue
        try:
            amt = float(amt_el.text)
        except (ValueError, TypeError):
            continue
        legs.append({
            "ledger": ledger,
            "debit": round(amt, 2) if amt > 0 else 0.0,
            "credit": round(-amt, 2) if amt < 0 else 0.0,
        })
    return legs


async def backfill():
    if db.invoices is None:
        print("Database unavailable")
        return
    cursor = db.invoices.find({"xml_generated": True, "xml_content": {"$exists": True, "$ne": ""}})
    total = skipped = done = 0
    async for inv in cursor:
        total += 1
        xml_content = inv.get("xml_content")
        if not xml_content:
            skipped += 1
            continue
        legs = _parse_voucher_legs(xml_content)
        if not legs:
            skipped += 1
            continue
        user_id = inv.get("user_id", "")
        company_id = inv.get("company_name") or user_id
        client_id = inv.get("client_id", 0)
        dated = (inv.get("extracted", {}) or {}).get("date") or (inv.get("extracted", {}) or {}).get("invoice_date") or ""
        cfg = CompanyConfig(user_config=inv.get("company_config") or {})
        enriched = []
        seen = set()
        for ln in legs:
            parent = cfg.ledger_parent_group(ln["ledger"])
            atype = classify_ledger(ln["ledger"], parent)
            enriched.append({**ln, "account_type": atype, "user_id": user_id,
                             "client_id": client_id, "company_id": company_id,
                             "voucher_type": inv.get("voucher_type", ""), "date": dated})
            if ln["ledger"] not in seen:
                seen.add(ln["ledger"])
                await db.upsert_ledger_type(company_id, ln["ledger"], atype, parent)
        await db.replace_journal_lines(str(inv.get("display_id")), enriched)
        done += 1
    print(f"Backfill complete: {total} invoices scanned, {done} journal sets written, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(backfill())
