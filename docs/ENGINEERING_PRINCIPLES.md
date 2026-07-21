# Engineering Principles

> *"When a CA uploads an invoice, they don't even think about whether it will work. They simply trust that it will."*

---

## Order of Priority

1. **Correctness** — Never generate incorrect accounting. If AI isn't confident, ask the CA, learn from the correction.
2. **Reliability** — Every failure is expected and handled. OCR down → queue. AI rate-limited → fallback. DB restarts → reconnect. Connector crashes → clean recovery.
3. **Speed** — Perceived speed matters more than raw latency. Show progress, never silent waiting.
4. **Observability** — Every failure is traceable to a root cause. Request IDs, invoice IDs, durations, error categories, retry counts.

---

## Non-Negotiable Rules

1. **Never lose customer data.**
2. **Never guess accounting.** Every auto-filled field must be reviewable and overridable.
3. **Every change has tests.**
4. **Every production incident gets a root-cause analysis.**
5. **Performance is measured, not assumed.**
6. **Customer trust is worth more than one extra feature.**

---

## What Trust Means for a CA

> *"I can process 5,000 invoices this month without worrying that the software will lose data, generate incorrect accounting entries, or go down on the last GST filing day."*

If a feature request doesn't serve that sentence, reconsider it.

---

## Architecture Decisions That Follow

| Principle | Implementation |
|-----------|---------------|
| Correctness | `journal_lines` as single source of truth; balanced XML enforced at generation; `force=true` safety valve |
| Reliability | Crash-proof background loops, auto-reconnect, bounded connection pool, offline mutation queue, idempotent operations |
| Speed | Progress feedback (not silent waiting), background jobs, indexed queries, route-based code splitting |
| Observability | Request IDs in every log line, structured logging, audit trail per invoice, metrics endpoint, Prometheus scrape |
| Security | PII redaction in logs, encrypted secrets, authentication/authorization per user, audit logs |
| Operations | Health checks, automated backups, disaster recovery, runbook for every common incident |

---

## Build Culture, Not Just Code

When the team grows beyond one, these principles are the hiring filter:

- Ship with care, not speed.
- Question features that reduce correctness.
- Every "just this once" shortcut becomes a pattern.
- The product is the workflow — AI extraction is 20% of the value; the 80% is validation, review, and Tally-correct output.

---

## The AI Era

AI is changing how software is written. It is **not** changing what customers value.

Customers still want: correct results, fast responses, stable systems, helpful support, honest communication.

AI helps build faster. It does not replace disciplined engineering.

---

## The Competitive Advantage

Not *"we have the most AI."*

But: *"when a CA uploads an invoice, it just works. Every time."*

That's the kind of advantage competitors find difficult to copy.
