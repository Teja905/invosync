# InvoSync — Why AI Accounting Actually Works (And Stays Safe)

> Internal positioning doc. Use this to answer the objections CAs, partners, and
> skeptical developers raise. Every claim below maps to a concrete control in the code.

---

## Objection 1: "AI is not feasible for accounting — it makes mistakes."

**Our answer:** AI never *does* the accounting. It *drafts* it. A human always reviews and
confirms before anything touches Tally.

| Control | What it does |
|---------|--------------|
| **Validation gate** | XML generation is blocked on critical errors (unbalanced voucher, missing date, bad math). `validation_layer.py` |
| **Confidence scoring** | Every field gets a 0–1 confidence. Low scores trigger a "Needs Review" badge. Frontend highlights them in yellow. |
| **Force-override safety valve** | Even when validation fails, the CA can override with `force=true` — but only *explicitly*. The machine never auto-commits. |
| **Audit trail + undo** | Every confirm / generate / sync is logged with a snapshot. One click reverts it. `audit_log.py`, `POST /invoices/{id}/undo`. |
| **Learning loop** | When a CA corrects a ledger mapping, the system remembers it forever. Accuracy climbs from 60% → 95%+. `ledger_learner.py`. |

**Bottom line:** The AI is a junior apprentice. The CA is the signing partner. The software
is built so the apprentice can suggest, but never sign.

---

## Objection 2: "You're sending my clients' private data to third-party AI tools."

**Our answer:** We treat PII as radioactive. It is redacted from logs and never written in clear text anywhere it can leak.

| Control | What it does |
|---------|--------------|
| **PII redaction in logs** | GSTIN, PAN, Aadhaar, email, phone, IFSC are auto-masked in every log line (`XXXXX…`). `core/pii.py` + `PIIRedactingFilter`. |
| **PII never in prompts beyond need** | The AI sees the invoice image to read it (unavoidable for OCR), but extracted PII is never echoed back into logs or error messages. |
| **Data residency** | Invoices, GSTINs, and amounts live in *your* MongoDB. They are not trained on, not resold, not sent to the AI after extraction. |
| **Self-host option** | The extraction provider is configurable (OpenRouter / Gemini / local model). A CA firm can point it at a private endpoint. |
| **No PII in error responses** | 422/500 responses carry a `request_id`, never the raw payload. |

**Bottom line:** The AI reads the paper; it never owns the client. PII stays in your database.

---

## Objection 3: "It won't survive 1000 users / it leaks under load."

**Our answer:** The service is built for multi-tenant scale, not a demo.

| Control | What it does |
|---------|--------------|
| **Connection pooling** | MongoDB client uses a bounded pool (`maxPoolSize=50`, configurable). No socket exhaustion. `database.py`. |
| **Global rate limiting** | Every endpoint is capped at 120 req/min/IP by default; extraction tighter at 15/min. `slowapi`. |
| **Bounded concurrency** | Background extraction runs at most `MAX_CONCURRENT_EXTRACTIONS` (semaphore), so a spike can't OOM the box. `background/worker.py`. |
| **Per-user data isolation** | All queries are scoped by `user_id`; one tenant can't see another's invoices. |
| **Crash-proof loops** | The extraction worker and cleanup loops restart themselves on any error — they never silently die at 3 AM. `background/worker.py`, `background/cleanup.py`. |

**Bottom line:** 1000 users means 1000 separate, rate-limited, pooled, isolated sessions — not one shared fragile process.

---

## Objection 4: "It crashes at 3 AM for no reason."

**Our answer:** We eliminated the two silent-death paths.

1. **Worker loop** — previously, any exception escaping `while True` killed extraction forever.
   Now it's caught, logged, and the loop restarts after 5s.
2. **Cleanup loop** — same treatment; stale-task eviction can't stop.
3. **Per-request safety** — the HTTP middleware wraps every request in try/except; one bad
   request can't take down the server.
4. **Observability** — every log line carries a `[req_id]`; every 500 is recorded in the
   audit log with `GET /api/v3/admin/errors` for post-mortems.

**Bottom line:** The app is designed to *degrade*, not *die*.

---

## Objection 5: "It's not reliable — I can't trust it with real books."

**Our answer:** Reliability is a feature, not a hope.

- **Offline resilience** — if the backend drops, the frontend shows a banner and keeps the
  draft in localStorage. Work is never lost. `OfflineBanner.jsx`.
- **Graceful shutdown** — `lifespan` context manager closes the DB cleanly on restart.
- **Balanced XML guarantee** — every generated voucher sums to zero before it's allowed out.
  `xml_generator.py` + `validate_xml_output`.
- **Tally-safe masters** — missing ledgers/groups are created *before* the voucher, so Tally
  imports don't partially fail. `api/tally_sync.py`.

---

## The One-Line Pitch

> **InvoSync uses AI to draft, validation to guard, and humans to sign. Your data stays
> yours, the app never dies, and the books stay correct.**

---

## Honest Limitations (don't oversell)

- AI extraction is 85–95% accurate, not 100%. That's why review exists.
- Reverse-charge and e-invoice IRP export are roadmap items, not shipping.
- Self-hosted AI model requires the CA firm to provision it; we don't ship the model.
