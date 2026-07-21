# InvoSync — Kilo Code Context Brief

> **⚡ Read `docs/ENGINEERING_PRINCIPLES.md` first.** Every decision in this project answers to: correctness > reliability > speed > observability. Never guess accounting. Never lose data. Trust is the product.

You are working on **InvoSync**: an invoice-to-Tally-Prime-XML SaaS that has pivoted into a **CA practice portal**. Read `AGENTS.md` for the full living memory (architecture, fixes 1–31, edge-case tracker). This file is the short version so you don't overengineer.

## What the product actually is
- Extract invoice data from images/PDFs via AI → validate → generate balanced Tally Prime XML.
- **Pivot (2026-07):** system-of-record *view* for client financials. Authoritative books stay in Tally. InvoSync derives Trial Balance / P&L / Balance Sheet from invoices already captured, as **verification dashboards** — NOT a replacement for Tally's reporting.
- Lock-in hook = client portal. Don't try to rebuild Tally's entire ledger/stock/depreciation engine.

## Hard constraints (do NOT violate)
- **Stack is MongoDB (Motor, async). NOT Postgres.** No SQL, no triggers, no migrations. Use collections + aggregation + app-level balance checks.
- **PII must never leak to logs or third-party AI.** GSTIN/PAN/Aadhaar/email/phone/IFSC are redacted by `core/pii.py` + `PIIRedactingFilter`. Never `print()` PII.
- **Correctness is a liability.** Date-aware GST rates, immutable entries (reversal not delete — `reversed=True`), never show unbalanced numbers.
- **Single source of truth = `journal_lines`** (captured at XML-gen time in `xml_generator.py`). Reports read these, never raw XML.
- AI provider keys are placeholders in `.env`. `is_quota_error()` handles Gemini quota. Don't hardcode keys.
- Background loops are crash-proof (try/except + auto-restart). Don't add unbounded work.

## Engineering principles (learned the hard way)
1. **Business rules > AI.** GST detection, math validation, duplicate checks beat hoping AI is right.
2. **Warn, don't fail.** Missing GSTIN / tiny math mismatch / missing ledger → flag for review, never hard-block. `force=true` is the safety valve.
3. **Preserve human edits.** Once a CA corrects a field, never overwrite with AI guesses.
4. **The product IS the workflow** — extraction is ~20%, the 80% is validation safeguards + human review + Tally-correct output.
5. **Don't overengineer.** No premature MCP server, no inventory valuation, no multi-currency UI yet. Ship the journal infra, delay the portal UI until after pilot.

## Before you build anything
- Read `docs/ENGINEERING_PRINCIPLES.md` and ask: does this make the system more correct, more reliable, or faster for the CA? If no, the answer is no.
- Check `AGENTS.md` "Production Hardening — Edge Case Tracker" — most ideas are already tracked with status (✅/🔧/📋/⏳). Don't re-solve solved problems.
- Reuse existing modules: `xml_generator.py`, `gst_engine.py`, `validation_layer.py`, `company_config.py`, `ledger_classifier.py`, `api/journal_persist.py`, `api/reports.py`.
- Run `python -m pytest tests/ -q` (NOT the root-level `test_*.py` scripts — they call `sys.exit` and break collection).
- Match code style: `get_logger(__name__)`, async Motor, Pydantic v2 (`model_dump()` not `.dict()`), env-configurable everything.

## When NOT to add code
- Don't add a new ledger/stock/depreciation engine — that's Tally's job.
- Don't replace Tally reporting with a full accounting system.
- Don't add AI to classify ledgers — `ledger_classifier.py` is deterministic by design.
- Don't introduce new external services without the user's explicit say-so.
