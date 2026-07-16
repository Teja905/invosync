# Production Runbook — InvoSync (Invoice → Tally XML)

> On-call reference. If you are reading this at 3 AM, start at **Section 1**.

---

## 1. Health Checks (first 60 seconds)

| Check | How | Healthy signal |
|-------|-----|----------------|
| App alive | `GET /health` | `{"status":"ok"}` |
| DB connected | `GET /health` includes `database: true` | database connected |
| Background worker | `GET /api/v3/admin/metrics/live` → `worker_alive` | `true` |
| Queue depth | `GET /api/v3/admin/metrics/live` → `queue_depth` | stable or falling |
| Error rate | `GET /api/v3/admin/metrics/live` → `error_rate_pct` | `< 5%` over 10m |
| Recent errors | `GET /api/v3/admin/errors` | empty or known |
| Prometheus | `GET /metrics` | text exposition format |

The frontend shows a red **"Backend unreachable"** banner when `/health` fails 3×.
When it clears, queued offline actions auto-replay (see Section 6).

---

## 2. Common Incidents

### 2.1 App won't start / crashes immediately
- Check env: `OPENROUTER_API_KEY` or `GEMINI_API_KEY` (extraction needs one; falls back gracefully if both missing).
- Check `MONGO_URI`. If Mongo is unreachable the app still boots but **does not persist** invoices (logs a warning).
- Check logs: every request carries `[req_id]`; unhandled 500s go to `audit_logs` (action=`error`) and Sentry (if `SENTRY_DSN` set).

### 2.2 Background worker dead (no extraction happening)
- `worker_alive: false` means no heartbeat in 120s.
- The worker loop is **crash-proof**: any escaped exception is caught, logged, and the loop restarts after 5s. If it stays dead, the process itself is likely down → restart the service/container.
- Check `queue_depth` — if it keeps rising, extraction is slower than ingest. Raise `MAX_CONCURRENT_EXTRACTIONS` (default 3) or scale replicas.

### 2.3 DB connection exhaustion under load
- Symptoms: `ServerSelectionTimeoutError`, rising latency, `queue_depth` climbs.
- Pool is bounded: `maxPoolSize=50`, `minPoolSize=5`, `maxIdleTimeMS=30000` (override via `MONGO_MAX_POOL` / `MONGO_MIN_POOL`).
- Check MongoDB Atlas metrics (connections used vs limit). If at limit, either raise Atlas tier or lower `MONGO_MAX_POOL`.

### 2.4 Rate limit hit (HTTP 429)
- Global default `120/min/IP`; extraction tighter at `15/min/IP`.
- Legitimate bursts: raise `default_limits` in `api/app_state.py` or add per-route `@limiter.limit(...)`.
- If behind a proxy, ensure `X-Forwarded-For` is trusted or clients share an IP (one IP = one bucket).

### 2.5 PII leak suspected
- PII (GSTIN/PAN/Aadhaar/email/phone/IFSC) is redacted from **all** logs via `PIIRedactingFilter` and from Sentry via `before_send`.
- Verify: `grep` recent logs for a known GSTIN pattern `2[0-9]A` — should never appear in clear text.
- If found, audit the specific logger/module and add `redact_pii()` at the call site.

### 2.6 Tally import partially fails ("Partially imported with errors")
- Usually missing masters. Frontend runs `POST /api/v3/sync/preflight-diagnostics` before sync and prompts to auto-create ledgers/stock items.
- XML already includes ledger + voucher-type + stock-item masters (Fix 18/19), so most mismatches are company-name or parent-group mismatches — check `company_config` settings.

---

## 3. Recovery

### Restart (Render / Railway)
- Redeploy or restart the service. Startup connects Mongo, loads `LedgerLearner`, auto-migrates env config, and launches workers.

### Restart (Uncle's desktop / on-prem connector)
- `InvoSyncTallyConnector.exe` — tray icon → "Restart". Logs at `%APPDATA%/InvoSync/`.

### Restore from backup
- Backups rotate: hourly (24h) / daily (30d) / monthly (12mo) via `scripts/backup_schedule.py`.
- Restore = stop app, restore Mongo dump, restart.

### Replay failed extraction jobs
- Stale jobs are evicted after `task_ttl` (3600s) by `run_cleanup_loop` (also crash-proof).
- To reprocess: re-upload the invoice; extraction is idempotent per `file_hash` (duplicate detection).

---

## 4. Escalation

| Severity | Example | Action |
|----------|---------|--------|
| P1 (down) | App 500s, worker dead | Restart; page on-call; open Sentry issue |
| P2 (degraded) | Error rate > 5%, queue rising | Check DB/API keys; scale if needed |
| P3 (annoyance) | Single invoice fails extraction | Re-upload; check AI provider key |

No formal 3 AM call rotation yet — single on-call. Add responders in `docs/COMPANY_POSITIONING.md` contact section when team grows.

---

## 5. Monitoring You Already Have

- **Live metrics**: `/api/v3/admin/metrics/live` — request rate, error rate, queue depth, worker liveness, invoices/xml/sync counters.
- **Prometheus**: `/metrics` — scrape with Prometheus + Grafana (no extra dependency needed).
- **Error feed**: `/api/v3/admin/errors` — last N server errors from `audit_logs`.
- **Audit trail**: `audit_logs` collection (90-day TTL) — every invoice action with snapshot for undo.
- **Sentry** (optional): set `SENTRY_DSN` to get error aggregation + traces.

---

## 6. Offline Behavior (frontend)

- When `/health` fails, a sticky banner appears. Drafts are auto-saved to `localStorage`.
- Mutations (confirm-review, undo, bulk map/generate/sync/delete, sync-now) are **queued** in `localStorage` and replayed FIFO when connectivity returns.
- Users can click **"Retry now"** in the banner to force a replay.
- No data is lost while offline.

---

## 7. Key Env Vars

| Var | Purpose |
|-----|---------|
| `MONGO_URI` | Database connection |
| `MONGO_MAX_POOL` / `MONGO_MIN_POOL` | Connection pool sizing |
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` | AI providers (swappable) |
| `SENTRY_DSN` | Optional error tracking |
| `ENVIRONMENT` | `development` / `production` (affects Sentry) |
| `ALLOWED_ORIGINS` | CORS allow-list |
| `MAX_CONCURRENT_EXTRACTIONS` | Worker concurrency (default 3) |
| `PRODUCTION_MODE` | Enables `/admin/alerts` persistence |
| `COMPANY_STATE_CODE`, `COMPANY_NAME` | Tally XML defaults |
| `TALLY_*` / `*_LEDGER` / `*_GROUP` | Tally master naming |

---
*Generated as part of Fix 29 operational-maturity hardening. Keep this file updated whenever an incident reveals a new procedure.*
