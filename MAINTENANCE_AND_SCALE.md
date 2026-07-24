# InvoSync — Maintenance & Scale Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    InvoSync Platform                         │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│  Frontend   │   Backend   │  Connector  │   Database        │
│  React/Vite │  FastAPI    │  .NET 10    │   MongoDB Atlas   │
│  Port 5173  │  Port 8000  │  Port 9000  │   Atlas M0 Free   │
└─────────────┴─────────────┴─────────────┴───────────────────┘
```

### Data Flow
```
Invoice Image → AI Extraction → Validation → Journal Lines → Tally XML → Tally Import
                                    ↓
                              GSTR Reconciliation ← GST Portal JSON
                                    ↓
                              Compliance Calendar → Deadline Tracking
                                    ↓
                              Firm Dashboard → CA Review
```

---

## 1. Code Quality Rules

### Never Break These Invariants

| Rule | Where Enforced | What Happens If Violated |
|------|---------------|------------------------|
| **XML balance = 0** | `xml_generator.py` balance check | Tally rejects import — vouchers don't balance |
| **GSTIN checksum valid** | `gst_engine.py:_verify_gstin_checksum` | Wrong GSTIN → wrong CGST/SGST vs IGST routing |
| **Date-aware GST rates** | `gst_engine.py:get_valid_slabs_for_date` | Wrong tax rate → wrong amount → balance broken |
| **Debit = Credit in journal** | `xml_generator.py:_record_journal` | Reports show unbalanced trial balance |
| **No negative debits/credits** | `xml_generator.py:_add_debit_entry/_add_credit_entry` | Tally XML malformed |
| **Bill allocation amounts match voucher** | `xml_generator.py:_add_bill_allocation` | Tally rejects import |
| **Vendor name in XML is escaped** | `xml_generator.py:_make_ledger` | Names with `&` or `<` break XML parsing |

### Validation Layer Philosophy

```
BLOCKING ERRORS (force=true cannot override):
  - Voucher balance != 0
  - Date invalid (future, pre-GST, format wrong)
  - Hallucination confidence < 0.40 (data is unreliable)
  - Missing vendor name (creates orphan entries)
  - Missing total amount (cannot compute anything)

SOFT ERRORS (force=true overrides):
  - Amount mismatch (₹0.50-₹1.00 variance)
  - Tax rate not in standard slabs
  - Missing GSTIN
  - Low confidence (0.40-0.70)

WARNINGS (never block):
  - TDS may be applicable
  - HSN/SAC code missing
  - Ledger not found in Tally
  - Duplicate invoice number pattern
```

### Adding New Validation Checks

```python
# In validation_layer.py, add to validate_invoice_for_xml():
def _check_new_rule(inv: StandardizedInvoice, result: ValidationResult):
    # Check something
    if something_wrong:
        result.add_check("rule_name", False, "Error message")
    else:
        result.add_check("rule_name", True, "Passed message")

# Then add to validate_invoice_for_xml():
_check_new_rule(inv, result)
```

---

## 2. Tally XML Correctness

### XML Structure (what Tally expects)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>Company Name</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Purchase" ACTION="Create">
            <DATE>20240415</DATE>
            <VOUCHERNUMBER>INV-001</VOUCHERNUMBER>
            <ALLLEDGERENTRIES.LIST>
              <ALLLEDGERENTRIES>
                <LEDGERNAME>Vendor Name</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>-118000.00</AMOUNT>
              </ALLLEDGERENTRIES>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

### Sign Convention (CRITICAL)

```
DEBIT entries:  ISDEEMEDPOSITIVE=Yes,  AMOUNT = positive number
CREDIT entries: ISDEEMEDPOSITIVE=No,   AMOUNT = negative number

Sum of all AMOUNTs (excluding BILLALLOCATIONS and ALLINVENTORYENTRIES) = 0
```

### Common Tally Import Errors

| Error | Cause | Fix |
|-------|-------|-----|
| "Partially imported with errors" | Ledger doesn't exist in Tally | XML includes `<LEDGER ACTION="Create">` before voucher |
| "Voucher type not found" | Voucher type doesn't exist | XML includes `<VOUCHERTYPE ACTION="Create">` |
| "Company name mismatch" | SVCURRENTCOMPANY wrong | Must match Tally company name exactly |
| "Date format invalid" | Wrong date format | Use YYYYMMDD (e.g., 20240415) |
| "Amounts don't balance" | Debit != Credit | Balance check before XML generation |
| "Invalid XML characters" | Vendor name with `&` | `_sanitize()` strips invalid chars |

### Testing XML Correctness

```bash
# Run balance tests (all 7 voucher types)
python -m pytest tests/test_xml_generator/test_balance_invariants.py -v

# Run GST ledger routing tests
python -m pytest tests/test_xml_generator/test_gst_ledgers.py -v

# Run stock item tests
python -m pytest tests/test_xml_generator/test_stock_items.py -v

# Run Tally simulator (pre-flight check)
python -m pytest tests/test_tally_simulator.py -v
```

---

## 3. Tally Connector (Better Than Suvit)

### Connector Architecture

```
┌─────────────────────────────────────────────────┐
│              InvoSync Connector (.NET 10)        │
├─────────────────────────────────────────────────┤
│  PollingService (30s interval)                  │
│    ├── Fetch pending invoices from backend      │
│    ├── Push XML to Tally :9000                  │
│    ├── Pull Tally masters → sync to backend     │
│    └── Flush offline queue on reconnect         │
├─────────────────────────────────────────────────┤
│  Resilience Stack                               │
│    ├── CircuitBreaker (3 failures → 30s cooldown)│
│    ├── SyncWatchdog (2min stuck → auto-restart) │
│    ├── AutoRecoveryService (30s Tally health poll)│
│    ├── OfflineQueue (SQLite WAL, dead-letter)   │
│    ├── SessionManager (DPAPI encrypted)         │
│    └── NetworkMonitor (OS events + debounce)    │
├─────────────────────────────────────────────────┤
│  UI (WinForms Dark Theme)                       │
│    ├── Status dots (Connector/Tally/InvoSync)   │
│    ├── Activity grid with Undo/Retry buttons    │
│    ├── Sync animation (pulsing indicator)       │
│    └── System tray with context menu            │
└─────────────────────────────────────────────────┘
```

### What Makes It Better Than Suvit

| Feature | Suvit/VyaparTaxOne | InvoSync Connector |
|---------|-------------------|-------------------|
| Offline queue | Basic retry | SQLite WAL + dead-letter + auto-flush |
| Tally health check | Manual | 30-second auto-recovery |
| Sync stuck detection | None | 2-minute watchdog + auto-restart |
| Session persistence | Crashes lose login | DPAPI encrypted session.json |
| Undo push | Not available | Delete voucher from Tally via XML |
| Network recovery | Manual reconnect | OS events + auto-flush offline queue |
| Diagnostic report | None | Full system report (CPU, RAM, queue, logs) |
| Auto-update | Version mismatch errors | SHA256 verified download + batch swap |

### Connector Build & Deploy

```bash
# Build
cd tally-connector/InvoSyncTallyConnector
dotnet publish -c Release -r win-x64 --self-contained

# Output: bin/Release/net10.0/win-x64/publish/InvoSyncTallyConnector.exe
# Size: ~75MB (self-contained, no .NET runtime needed on user machine)

# Run
.\InvoSyncTallyConnector.exe

# First run: Setup Wizard guides through login + Tally detection
```

### Connector Testing

```bash
# Build check
dotnet build 2>&1 | grep -c "error"  # Should be 0

# Pipeline test (requires mock server)
cd tests/mock
python mock_backend.py &    # Terminal 1: mock API on :8000
python mock_tally_server.py & # Terminal 2: mock Tally on :9000
python test_local_pipeline.py  # Terminal 3: run pipeline test
```

---

## 4. Database Schema & Indexes

### Collections

```javascript
// invoices — core invoice data
{
  _id: ObjectId,
  user_id: String,           // owner
  client_id: String,         // client reference
  company_id: String,        // Tally company name
  display_id: String,        // human-readable ID (INV-0001)
  file_hash: String,         // SHA-256 for dedup
  status: String,            // draft | validated | exported | synced
  extracted: { ... },        // AI extraction result
  journal_lines: [ ... ],    // captured ledger legs
  xml_content: String,       // generated Tally XML
  image_data: String,        // base64 (legacy) or storage_key
  storage_key: String,       // S3/local path
  item_ledgers: [ ... ],     // user-assigned ledgers per line item
  reviewed_at: Date,
  created_at: Date,
}

// journal_lines — reporting source of truth
{
  _id: ObjectId,
  user_id: String,
  client_id: String,
  company_id: String,
  invoice_id: String,
  ledger: String,
  debit: Number,
  credit: Number,
  account_type: String,      // Asset | Liability | Income | Expense
  voucher_type: String,
  date: String,
  line_no: Number,
  reversed: Boolean,         // immutable undo
  created_at: Date,
}

// compliance_tasks — deadline tracking
{
  _id: ObjectId,
  user_id: String,
  client_id: String,
  client_name: String,
  task_id: String,           // e.g., "gstr1-2024-04"
  title: String,
  description: String,
  due_date: String,          // YYYY-MM-DD
  category: String,          // gst | tds | it | roc
  priority: String,          // critical | high | medium | low
  frequency: String,         // monthly | quarterly | annual
  status: String,            // pending | in_progress | completed | overdue
  assigned_to: String,
  fy_start: Number,
  created_at: Date,
}

// audit_logs — immutable audit trail (90-day TTL)
{
  _id: ObjectId,
  user_id: String,
  resource_type: String,     // invoice | user | config
  resource_id: String,
  action: String,            // create | update | delete | confirm | generate | sync
  details: String,
  snapshot: Object,          // pre-action state for undo
  created_at: Date,          // TTL index: expireAfterSeconds: 7776000
}
```

### Critical Indexes

```javascript
// Deduplication (unique)
db.invoices.createIndex({ user_id: 1, file_hash: 1 }, { unique: true, sparse: true })

// Dashboard listing
db.invoices.createIndex({ user_id: 1, created_at: -1 })

// Connector polling
db.invoices.createIndex({ status: 1, priority_sync: -1 })

// Report queries
db.journal_lines.createIndex({ user_id: 1, company_id: 1, date: 1, reversed: 1 })

// Compliance calendar
db.compliance_tasks.createIndex({ user_id: 1, fy_start: 1, client_id: 1, due_date: 1 })

// Audit trail (with TTL)
db.audit_logs.createIndex({ created_at: 1 }, { expireAfterSeconds: 7776000 })
```

---

## 5. Scaling Roadmap

### Phase 1: Current (1-50 firms)
- MongoDB Atlas M0 (512MB free tier)
- Single backend instance on Render
- No caching needed
- SQLite for connector offline queue

### Phase 2: Growth (50-200 firms)
- [ ] Upgrade to MongoDB Atlas M10 (dedicated RAM)
- [ ] Add Redis for session cache + rate limiting
- [ ] Add worker pool (2-4 background workers)
- [ ] Add CDN for frontend static assets
- [ ] Add health check monitoring (UptimeRobot)

### Phase 3: Scale (200-1000 firms)
- [ ] Horizontal scaling (2+ backend instances)
- [ ] Redis for distributed rate limiting
- [ ] MongoDB Atlas M20+ (auto-scaling)
- [ ] Dedicated Tally connector fleet
- [ ] A/B testing framework
- [ ] Feature flags (LaunchDarkly or custom)

### Phase 4: Enterprise (1000+ firms)
- [ ] Multi-region deployment (India + Southeast Asia)
- [ ] Dedicated databases per large customers
- [ ] SSO/SAML integration
- [ ] SOC 2 compliance
- [ ] SLA guarantees (99.9% uptime)

---

## 6. Monitoring & Alerting

### What to Monitor

| Metric | Threshold | Action |
|--------|-----------|--------|
| Request rate | > 1000/min | Check for abuse |
| Error rate | > 1% | Investigate logs |
| Response time (p95) | > 5s | Scale up or optimize |
| MongoDB connections | > 40 of 50 | Increase pool size |
| Queue depth | > 100 | Add workers |
| Worker heartbeat | Stale > 5min | Restart worker |
| AI extraction failures | > 3 in 5min | Check API keys/quota |
| Disk usage (S3) | > 80% | Archive old images |

### Health Check Endpoint

```
GET /health
Response: { "status": "ok", "version": "3.2", "db": "connected", "uptime": 86400 }
```

### Logs

```bash
# View live logs
heroku logs --tail  # or
docker logs -f invosync-backend

# Search for errors
grep -i "error" logs/invosync-*.log

# Search for specific request
grep "req_id=abc123" logs/invosync-*.log
```

---

## 7. Backup & Recovery

### MongoDB Backup

```bash
# Manual backup
mongodump --uri="$MONGODB_URI" --out=backups/$(date +%Y%m%d)

# Automated (cron)
0 2 * * * /path/to/scripts/backup_schedule.py --retain-hourly 24 --retain-daily 30

# Restore
mongorestore --uri="$MONGODB_URI" backups/20240415/
```

### S3/Image Backup

```bash
# Sync images to backup bucket
aws s3 sync s3://invosync-images s3://invosync-backup --storage-class GLACIER
```

### Recovery Procedures

| Scenario | Recovery Time | Steps |
|----------|--------------|-------|
| Backend crash | < 1 min | Render auto-restarts. Check logs. |
| MongoDB down | < 5 min | Atlas auto-failover. Check connection pool. |
| S3 outage | < 10 min | Images unavailable. Invoices still work (metadata in DB). |
| Tally connector crash | < 1 min | Auto-restart (crash shield). Offline queue preserves data. |
| Full data loss | < 1 hour | Restore from MongoDB backup + S3 sync. |

---

## 8. Security Checklist

### Before Every Deploy

- [ ] `JWT_SECRET` is set (not default)
- [ ] `ADMIN_EMAILS` is set
- [ ] `AUTH_ENABLED=true` in production
- [ ] CORS origins are specific (not `*`)
- [ ] Rate limiting is enabled
- [ ] PII filter is attached to logging
- [ ] Sentry DSN is configured
- [ ] MongoDB IP whitelist is set
- [ ] S3 bucket has proper IAM policies

### Data Protection

| Data | Storage | Encryption | Retention |
|------|---------|------------|-----------|
| User passwords | MongoDB | PBKDF2 + salt | Never deleted |
| JWT tokens | localStorage | HTTPS only | 72h expiry |
| GSTIN/PAN | MongoDB | At rest (Atlas) | Per user data |
| Invoice images | S3/local | HTTPS in transit | Until deleted |
| Audit logs | MongoDB | TTL index | 90 days |
| Session (connector) | AppData | DPAPI encryption | Until logout |
| Tally password | Backend memory | Never persisted | Request-scoped |

---

## 9. Deployment Checklist

### Backend (Render/Fly.io)

```bash
# Environment variables needed
MONGODB_URI=mongodb+srv://...
JWT_SECRET=<random-64-chars>
ADMIN_EMAILS=ca@example.com
COMPANY_STATE_CODE=27
COMPANY_GSTIN=27AABCU1234F1ZP
COMPANY_NAME=Your Firm Name
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=...
AUTH_ENABLED=true
CORS_ORIGINS=https://yourdomain.com
SENTRY_DSN=https://...
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET=invosync-images
S3_ENDPOINT=https://...
```

### Frontend (Vercel)

```bash
# Environment variables
VITE_API_URL=https://your-backend.onrender.com
```

### Tally Connector (User's PC)

```
1. Download InvoSyncConnector.exe
2. Run → Setup Wizard appears
3. Enter email/password → login
4. Wizard detects Tally on port 9000
5. Select active company
6. Connector runs in system tray
7. Auto-starts on Windows boot
```

---

## 10. Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| "XML not balanced" | Bill allocations counted in balance | Regex strips BILLALLOCATIONS before sum |
| "GSTIN validation fails" | Checksum algorithm wrong | Use `_compute_gstin_checksum()` |
| "Tally import partial" | Ledger doesn't exist | XML includes ledger creation |
| "Extraction returns empty" | API key expired/quota | Check `OPENROUTER_API_KEY` |
| "Connector can't reach backend" | Render sleeping | Keep-alive workflow pings every 5 min |
| "MongoDB connection timeout" | Pool exhausted | Increase `MONGO_MAX_POOL` |
| "Rate limit 429" | Too many requests | Increase `slowapi` limits |
| "Frontend shows blank" | Build error | Run `npm run build` locally first |

---

## 11. Feature Roadmap (Prioritized)

### Must Have (Before Pilot)
- [x] Invoice extraction → Tally XML
- [x] TDS compliance (15 sections)
- [x] GSTR reconciliation
- [x] Compliance calendar
- [x] Firm dashboard
- [x] Tally connector with offline queue
- [ ] Real CA testing (manual — can't automate)
- [ ] HSN → GST rate lookup (top 100 codes)

### Should Have (Month 1-2)
- [ ] Client onboarding flow (bulk import from Excel)
- [ ] Notice management (parse IT/GST notices)
- [ ] Bank reconciliation (match payments vs invoices)
- [ ] Multi-company support (one CA, many Tally companies)
- [ ] Export reports as PDF

### Nice to Have (Month 3-6)
- [ ] Auto-GSTR-1/3B filing (via GST portal API)
- [ ] Auto-ITR preparation
- [ ] WhatsApp reminders to clients
- [ ] Time tracking for CA firm
- [ ] Billing/invoicing for CA firm

---

## 12. Cost Breakdown (Monthly)

### Free Tier (Current)
| Service | Cost |
|---------|------|
| MongoDB Atlas M0 | Free (512MB) |
| Render Backend | Free (750 hrs) |
| Vercel Frontend | Free |
| OpenRouter API | Pay-per-use (~$5-20/mo) |
| **Total** | **~$5-20/mo** |

### Growth Tier (50+ firms)
| Service | Cost |
|---------|------|
| MongoDB Atlas M10 | ~$57/mo |
| Render Starter | ~$25/mo |
| Vercel Pro | ~$20/mo |
| OpenRouter API | ~$50-100/mo |
| S3 (images) | ~$5/mo |
| **Total** | **~$160-210/mo** |

### Revenue at Growth Tier
- 50 firms × Rs 2,999/mo = Rs 1,49,950/mo (~$1,800/mo)
- Cost: $210/mo
- **Margin: 88%**

---

*Last updated: 2026-07-23*
*Version: 3.2*
*Author: InvoSync Engineering*
