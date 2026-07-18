"""Shared helper to persist derived journal lines after XML generation.

Called from every XML-generation path (generate-xml, confirm-review, bulk
generate). Keeps the `journal_lines` collection as the single source of truth
for reporting and seeds the chart-of-accounts `ledger_types` mapping.
"""

from typing import Optional

from ledger_classifier import classify_ledger

from api.helpers import resolve_config  # noqa: F401  (kept for symmetry)


async def persist_journal(
    db,
    invoice_id,
    user_id: str,
    company_id: str,
    client_id,
    standard,
    xml_gen,
    usr_cfg,
    date_override: Optional[str] = None,
    voucher_type_override: Optional[str] = None,
):
    """Persist the ledger legs captured during XML generation.

    No-op if no legs were captured (e.g. preview-only calls that skip master
    building). Idempotent: re-generating overwrites previous legs for the
    invoice so reports never double-count.
    """
    if not getattr(xml_gen, "journal_lines", None):
        return
    try:
        dated = (date_override or getattr(standard, "invoice_date", "") or "").strip()
        vt = voucher_type_override or (standard.voucher_type.value if hasattr(standard.voucher_type, "value") else str(getattr(standard, "voucher_type", "")))
        enriched = []
        seen_ledgers = set()
        for line in xml_gen.journal_lines:
            ledger = line["ledger"]
            parent = usr_cfg.ledger_parent_group(ledger) if usr_cfg else ""
            account_type = classify_ledger(ledger, parent)
            enriched.append({
                **line,
                "account_type": account_type,
                "user_id": user_id,
                "client_id": client_id,
                "company_id": company_id,
                "voucher_type": vt,
                "date": dated,
            })
            if ledger not in seen_ledgers:
                seen_ledgers.add(ledger)
                await db.upsert_ledger_type(company_id, ledger, account_type, parent)
        await db.replace_journal_lines(str(invoice_id), enriched)
    except Exception as e:  # never block generation on reporting persistence
        import logging
        logging.getLogger(__name__).error("Journal line persistence error: %s", e)
