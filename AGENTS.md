# Invoice to Tally XML — Project Memory

## Quick Context
Full-stack app: extract invoice data from images via AI, validate, generate Tally Prime XML.

## Architecture

### Backend (Python FastAPI)
```
backend/
├── main.py              # FastAPI app, 21 routes (16 in main + 5 in auth), v3 endpoints
├── schemas.py           # Pydantic models: StandardizedInvoice, LineItem, TaxEntry, enums
├── gst_engine.py        # GSTIN validation, CGST/SGST/IGST detection, rate validation
├── xml_generator.py     # 7 voucher types, balanced XML, bill allocations
├── validation_layer.py  # Pre-export checks (balance, GST, dates, amounts)
├── company_config.py    # 80+ semantic ledger mappings, GST ledger names
├── ledger_mapping.py    # Keyword-based expense->ledger mapping
├── voucher_classifier.py # V1: always returns Purchase (user confirms)
├── ocr_postproc.py      # Date fix, GSTIN cleanup, math validation
├── extractors.py        # Gemini → OpenRouter → NVIDIA pipeline
├── validation.py        # Legacy validation (kept for backward compat)
├── database.py          # MongoDB Motor async layer
├── test_*.py            # 48 pytest tests + comprehensive scenario tests covering all modules
└── generate_samples.py  # Sample XML generator
```

### Frontend (React + Vite + Tailwind)
```
frontend/
├── src/App.jsx          # Login, onboarding, extract/edit, dashboard, admin, clients
├── src/auth.jsx         # AuthProvider, JWT, email/password auth
├── src/main.jsx         # React entry with provider wrapping
├── src/index.css        # Dark theme, glass cards, animated orbs, scrollbar
├── vite.config.js       # Dev proxy to backend
├── .env                 # VITE_GOOGLE_CLIENT_ID (unused)
├── package.json         # React, react-dropzone, @react-oauth/google
├── tailwind.config.js
└── index.html
```

## Key Decisions

### Voucher Type
- V1 always defaults to Purchase (85% of CA invoices)
- User overrides via dropdown after extraction
- `/api/v3/voucher-type/suggest` endpoint returns suggestion + rationale

### Tally XML Sign Convention
- Debit entries: ISDEEMEDPOSITIVE=Yes, AMOUNT=positive
- Credit entries: ISDEEMEDPOSITIVE=No, AMOUNT=negative
- Sum of all AMOUNTs (excluding BILLALLOCATIONS and ALLINVENTORYENTRIES) = 0
- Bill allocations track party invoices (BILLTYPE="New Ref")

### GST Engine
- State code 01-37 map, CGST+SGST for intra-state, IGST for inter-state
- Validates GSTIN format + checksum
- Validates rates against allowed slabs: 0, 0.1, 0.25, 3, 5, 12, 18, 28
- Never hardcodes percentages

### Service vs Goods
- Service invoices: ONLY ALLLEDGERENTRIES.LIST (no inventory)
- Goods invoices: ALLINVENTORYENTRIES.LIST with HSN, unit, GST class
- Classification via HSN/SAC code (99xx = service) + keyword scoring

### AI Extraction Pipeline
- OpenRouter (primary, model: `google/gemini-2.0-flash-001` via OpenRouter API)
- Gemini direct (fallback, model: `gemini-2.0-flash-001` when billing enabled)
- Post-processing fixes OCR confusions: dates, GSTIN, tax rates

## Common Issues & Fixes

### XML not balanced
Check: bill allocation amounts counting in balance check — use regex to strip BILLALLOCATIONS.LIST and ALLINVENTORYENTRIES.LIST before summing AMOUNTs.

### GSTIN validation fails
The checksum algorithm uses base-36 codepoints. Generate valid test GSTINs via `_compute_gstin_checksum()`. Example: `27AABCU1234F1ZP`.

### Service invoice has inventory entries
Set `is_service=True` on StandardizedInvoice. The XML generator checks this flag before adding ALLINVENTORYENTRIES.LIST.

## Deployment
```
Backend: Railway/Render — uvicorn main:app
Frontend: Vercel — build frontend/, set API_URL
Database: MongoDB Atlas free tier
Env vars: API keys, COMPANY_STATE_CODE, COMPANY_NAME
```

## Fixes Applied (2026-05-28)

### Fix 15 — Tally import ledger mismatch: all ledgers configurable + voucher type dropdown + pre-export ledger listing
- **company_config.py**: Added `get_tds_ledger()` (TDS_PAYABLE_LEDGER env), `get_round_off_ledger()` (ROUND_OFF_LEDGER env), `get_freight_ledger()` (FREIGHT_LEDGER env), `get_bank_ledger()` (BANK_LEDGER env), `get_suspense_ledger()` (SUSPENSE_LEDGER env) — all with sensible defaults
- **xml_generator.py**: Replaced all hardcoded "TDS Payable", "Round Off", "Freight Expenses", "Bank" with `self.config.get_*()` calls
- **main.py**: `_legacy_to_standard` now checks `data.get("voucher_type")` first; only falls back to `classify_voucher_type` if not provided. `InvoiceDataLegacy` unchanged (voucher_type passes through via `data` dict).
- **App.jsx**: Added voucher_type dropdown (Purchase/Sales/Payment/Receipt/Journal/Credit Note/Debit Note) in review screen, included in form state and payload
- **validation_layer.py**: Added `_list_referenced_ledgers()` — appends a warning per ledger that will be referenced in the XML (purchase, sales, freight, TDS, round-off, bank, GST, expense) so the CA can verify they exist in Tally before import
- **New env vars**: `TDS_PAYABLE_LEDGER`, `ROUND_OFF_LEDGER`, `FREIGHT_LEDGER`, `BANK_LEDGER`, `SUSPENSE_LEDGER`

### Fix 16 — PDF upload support
- **main.py**: `_is_valid_image` now accepts `%PDF` magic bytes; `/extract` endpoint accepts `application/pdf`
- **extractors.py**: `normalize_image` converts first page of PDF to JPEG via PyMuPDF (`fitz`) before sending to AI
- **App.jsx**: Dropzone accepts `.pdf`, text updated to mention PDFs
- **requirements.txt**: Added PyMuPDF

### Fix 14 — Edit Client UI + Pydantic v2 cleanup + null user_id guard
- **App.jsx:ClientPage**: Added Edit button per row, modal overlay with pre-filled fields, PUT /clients/{id} call to update company/contact/GSTIN
- **main.py**: Replaced deprecated `.dict()` calls with `.model_dump()` for Pydantic v2 compatibility (lines 261, 356, 458)
- **AGENTS.md**: Updated frontend section to reflect email/password auth (no Google OAuth)

### Fix 13 — `/generate-xml` now blocks on validation failure
- `main.py:generate_xml()` and `main.py:generate_xml_for()`: validation result is checked when `force=false`. Returns 422 JSON with errors instead of silently returning broken XML.
- `App.jsx:downloadXML()`: handles 422 response, parses validation errors, shows confirm dialog to retry with `force=true`.
- The existing dashboard already serves as the "needs review" section — decision column color-codes invoices, click to edit and retry.
- **validation_layer.py**: Service invoices don't need line_items mandatory; date accepts DD/MM/YYYY; amount math uses header taxable when no line items
- **gst_engine.py**: `validate_tax_structure` no longer flags empty tax list as error (exempt/nil-rated is valid)
- **xml_generator.py**: Date handles both YYYY-MM-DD and DD/MM/YYYY; sales party entry has BILLALLOCATIONS; sales ledger configurable via SALES_LEDGER env
- **Comprehensive test** (`test_comprehensive.py`): 71 scenarios covering all Indian invoice types — goods, services, mixed rates, freight, TDS, round-off, credit/debit notes, all 7 GST slabs, all 7 voucher types, real-world scenarios (restaurant, construction, IT services, medical, auto parts, contractor)
- Output GST ledger mappings added (Output CGST/SGST/IGST for each slab)

## Production Hardening — Edge Case Tracker

Status legend: ✅ Done | 🔧 In Progress | 📋 Pending | ⏳ Future

### CAT 1 — GST Edge Cases
| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| CGST/SGST vs IGST detection | Critical | ✅ | Fixed via buyer_gstin model field |
| Missing GSTIN (warn not fail) | High | ✅ | Already handled — soft error, force-overridable |
| GST math mismatch (taxable+tax≠total) | High | ✅ | Already handled — soft error, force-overridable |
| Mixed tax rates per invoice | High | ✅ | Already handled — per-entry ledger iteration supports any mix |
| Reverse charge (GST by buyer) | Low | ⏳ | V2 feature |
| Exempt/Nil-rated handling | Medium | ✅ | Already handled — empty tax list allowed |

### CAT 2 — Accounting Edge Cases
| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| Duplicate invoice detection | High | ✅ | Already handled — /extract returns warning, generate endpoints check too |
| Credit/Debit notes (negatives) | Medium | ⏳ | V2 — need negative adjustments |
| Expense vs Purchase confusion | Medium | 📋 | Office rent, audit fees ≠ inventory — needs review |
| Cash vs Credit purchase | Low | ⏳ | Affects voucher type (Payment vs Purchase) |
| Bill-by-bill allocation | Medium | ✅ | Already handled via BILLALLOCATIONS |

### CAT 0 — Voucher Classification
| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| Sales invoice → Purchase voucher | Critical | ✅ | Fixed: GSTIN direction detection + InvoiceDataLegacy voucher_type field + logging |

### CAT 3 — Tally XML Edge Cases
| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| XML balanced (sum=0) | Critical | ✅ | Fixed with regex stripping |
| Missing ledger fallback | High | ✅ | Fix 18: XML now creates ledgers before voucher |
| Invalid XML characters | High | ✅ | Already sanitized |
| Company not open in Tally | Low | ⏳ | User education / import guide |
| Wrong voucher type | High | 🔧 | User confirms via dropdown + suggest endpoint |

### CAT 4 — Document Edge Cases
| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| Blurry photos | Medium | 📋 | Prompt user to retake; improve OCR fallback |
| Rotated/scanned upside down | Medium | 📋 | Preprocess with orientation detection |
| Multiple invoices in one PDF | Low | ⏳ | V2 — split and batch process |
| Handwritten notes mixed in | Low | ⏳ | Strip non-invoice text via layout analysis |
| Non-invoice uploads (PAN/bank) | Medium | 📋 | Document type detection — reject early |

### CAT 5 — Human Workflow Edge Cases
| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| Click generate without review | High | ✅ | Validation_layer blocks with errors |
| Accountant overrides AI | Critical | 📋 | Preserve manual edits; never silently overwrite |
| User switches tabs mid-flow | Low | 📋 | Auto-save draft extraction |
| Force-generate safety valve | High | ✅ | force=true bypasses all validation |

### CAT 6 — Future Scaling (not V1)
- Multi-company support (one CA firm, many clients)
- Team workflows (junior extracts → senior reviews)
- Audit logs (who changed what, when)
- Batch processing (upload 50 invoices at once)
- e-Invoice IRP JSON export
- Zoho Books / Busy / SAP export formats
- ML-based voucher type prediction

## Production Principles (learned 2026-05-28)
1. **Business rules > AI** — GST detection, math validation, and duplicate checks are more reliable than hoping AI gets it right
2. **Warn, don't fail** — Missing GSTIN, slight math mismatch, missing ledger: flag for review, never hard-block
3. **The product IS the workflow** — AI extraction is 20% of value; the 80% is validation safeguards + human review + Tally-correct output
4. **Real-world iteration** — Don't solve all edge cases before launch. Prioritize by frequency of real failure
5. **Preserve human edits** — Once an accountant corrects a field, never overwrite with AI guesses
6. **Force override is essential** — Sometimes the accountant knows best. Always provide a safety valve

### Fix 17 — Voucher classification audit: Sales invoice → Purchase voucher bug

#### Root Cause
Triple break in the pipeline:

1. **`InvoiceDataLegacy` (main.py:88) had no `voucher_type` field** → Pydantic silently dropped user's dropdown selection from frontend
2. **`_normalize_to_standard` (extractors.py:196) ignored `document_type` from AI** → always defaulted to Purchase
3. **No logging at decision points** → invisible bug

#### Fixes
- **main.py**: Added `voucher_type: str = ""` to `InvoiceDataLegacy` — user's dropdown selection now passes through to `_legacy_to_standard`
- **extractors.py**: Added `VoucherType` import; added GSTIN-based direction detection: if `vendor_gstin == COMPANY_GSTIN` → Sales, if `buyer_gstin == COMPANY_GSTIN` → Purchase; map `document_type` (retail_bill/expense_receipt/proforma/purchase_invoice → Purchase; tax_invoice/service_invoice → ambiguous, defaults to Purchase)
- **extractors.py**, **main.py**, **xml_generator.py**: Added `VOUCHER CLASSIFICATION` logging at all 3 decision points showing extracted type → chosen type → XML type

#### Behavior Change
- Sales invoices where vendor GSTIN matches COMPANY_GSTIN now auto-detect as Sales voucher
- User's dropdown selection in review screen is preserved through to XML
- All other documents still default to Purchase (conservative V1 rule)
- 170+ tests pass (86 comprehensive + 24 balance + 26 south Indian + 8 module-level + new ledger tests)

#### Verification
When uploading a Sales invoice:
```
VOUCHER CLASSIFICATION: document_type='tax_invoice' vendor_gstin='27COMPANY1234F1ZP' company_gstin='27COMPANY1234F1ZP' > voucher_type=Sales
VOUCHER CLASSIFICATION (legacy): user_voucher_type='Sales' > final_voucher_type=Sales
VOUCHER CLASSIFICATION (XML): voucher_type=Sales invoice=SALE-001 vendor=Customer Ltd
```

### Fix 18 — Tally Import Fix: Ledger creation before voucher

#### Root Cause
Tally XML import shows "Partially imported with errors" because every ledger referenced in a voucher must either already exist in Tally OR be created in the same XML file before the voucher. The generator only produced voucher XML — no ledger creation.

#### Fixes
- **company_config.py**: Added `get_sundry_creditors_group()`, `get_sundry_debtors_group()`, `get_purchase_accounts_group()`, `get_duties_taxes_group()` — all configurable via env vars (`SUNDRY_CREDITORS_GROUP`, `SUNDRY_DEBTORS_GROUP`, `PURCHASE_ACCOUNTS_GROUP`, `DUTIES_TAXES_GROUP`). Added `determine_tax_category()` for GSTIN-based CGST/SGST vs IGST detection.
- **xml_generator.py**: Added `_build_masters_envelope()`, `_make_ledger()`, `_generate_all_ledgers_xml()` — generates `<LEDGER ACTION="Create">` blocks for vendor (with GSTIN/state), purchase account, and GST tax ledgers. Added `include_ledgers=True` config to `__init__`. Modified `generate()` to prepend ledger creation envelopes before the voucher envelope.
- **Output**: Single downloadable XML file with two `<ENVELOPE>` blocks — first creates ledgers (REPORTNAME="All Masters"), second creates voucher (REPORTNAME="Vouchers").

#### Behavior Change
- XML now includes both ledger creation and voucher in one file
- Vendor ledger: name from vendor_name, parent "Sundry Creditors", includes GSTIN + state
- Purchase ledger: "Purchase Account" (configurable), parent "Purchase Accounts"
- Tax ledgers: "Input CGST/SGST @ X%" or "Input IGST X%", parent "Duties & Taxes"
- All ledger names match exactly what the voucher references
- Voucher balance = 0.00 always maintained
- Backward compatible: `include_ledgers=False` returns just voucher XML
- 170+ tests pass

#### Ledger parent groups (configurable via env vars)
```
SUNDRY_CREDITORS_GROUP="Sundry Creditors"
SUNDRY_DEBTORS_GROUP="Sundry Debtors"
PURCHASE_ACCOUNTS_GROUP="Purchase Accounts"
DUTIES_TAXES_GROUP="Duties & Taxes"
```

#### Uncle Questions (needed before production import)
1. What's the exact company name in your Tally? (SVCURRENTCOMPANY)
2. What do you call your purchase ledger group? (PURCHASE_ACCOUNTS_GROUP)
3. What do you call your creditors group? (SUNDRY_CREDITORS_GROUP)
4. Do you already have GST tax ledgers? If yes, what are they named?

### Fix 19 — Tally Import Fix: Voucher type + stock item + parent group creation

#### Root Cause
Three gaps in the generated XML caused Tally Prime to reject imports:

1. **No voucher type master** — `<VOUCHER VCHTYPE="Credit Note">` references a type that may not exist in Tally's company data. Even standard types (Credit Note, Debit Note) can be missing in minimal/clean company setups.
2. **No stock item creation** — `ALLINVENTORYENTRIES.LIST` references stock items (Product X, etc.) that don't exist in Tally. Stock items must be created as masters first.
3. **Hardcoded parent group names** — `"Sales Accounts"`, `"Bank Accounts"`, `"Current Liabilities"` were hardcoded strings, not configurable. If the Tally company uses different group names (or translated names), the ledger creation fails.

#### Fixes
- **xml_generator.py**: Added `_make_voucher_type()` — generates `<VOUCHERTYPE NAME="..." ACTION="Create">` with `ISACTIVE=Yes` in the masters envelope before the voucher.
- **xml_generator.py**: Added `_make_stock_item()` — for goods invoices, creates `<STOCKITEM>` with HSN code, units, rate of dealing, and GST class per line item.
- **xml_generator.py**: Added `_make_stock_group()` — creates `STOCKGROUP "Primary"` as parent for stock items.
- **xml_generator.py**: Added `_generate_all_masters_xml()` — orchestrates the full masters envelope in order: VOUCHERTYPE → STOCKGROUP → STOCKITEM → LEDGERs.
- **xml_generator.py**: Renamed `_generate_all_ledgers_xml()` → `_build_ledger_elements()` (returns list of elements instead of string).
- **xml_generator.py**: Replaced hardcoded `"Sales Accounts"` → `self.config.get_sales_accounts_group()`, `"Bank Accounts"` → `self.config.get_bank_accounts_group()`, `"Current Liabilities"` → `self.config.get_current_liabilities_group()`.
- **company_config.py**: Added `get_sales_accounts_group()` (env `SALES_ACCOUNTS_GROUP`), `get_bank_accounts_group()` (env `BANK_ACCOUNTS_GROUP`), `get_current_liabilities_group()` (env `CURRENT_LIABILITIES_GROUP`).
- **auth.py**: Added `sales_accounts_group`, `bank_accounts_group`, `current_liabilities_group` to `ProfileUpdate`.
- **main.py**: Added new fields to `_COMPANY_CONFIG_FIELDS`.

#### Generated XML Order
```
Envelope 1: REPORTNAME="All Masters"
  ├── VOUCHERTYPE "Purchase" (ACTION=Create)
  ├── STOCKGROUP "Primary" (ACTION=Create, parent=Primary)
  ├── STOCKITEM "Product X" (ACTION=Create, with HSN/units/rate)
  ├── LEDGER "ABC Suppliers" (parent=Sundry Creditors, with GSTIN)
  ├── LEDGER "Purchase" (parent=Purchase Accounts)
  ├── LEDGER "Input CGST/SGST @ X%" (parent=Duties & Taxes, with TAXTYPE/GSTTYPE)
  └── [Freight/TDS/Round-Off ledgers as needed]

Envelope 2: REPORTNAME="Vouchers"
  └── VOUCHER VCHTYPE="Purchase" (balanced, with bill allocations)
```

#### New Env Vars
```
SALES_ACCOUNTS_GROUP="Sales Accounts"
BANK_ACCOUNTS_GROUP="Bank Accounts"
CURRENT_LIABILITIES_GROUP="Current Liabilities"
```

#### Behavior Change
- Every XML now includes voucher type creation — Tally will create the voucher type if it doesn't exist.
- Every goods invoice XML includes stock group + stock items — Tally can resolve inventory entries.
- All parent group names are configurable per-user via Settings page or env vars.
- Service invoices correctly skip stock item creation.
- Backward compatible: `include_ledgers=False` still returns just voucher XML (no masters at all).
- 48+24+26+85 = 183 tests pass.

## Fix 22 — TallyPusher 3-bug fix + mock pipeline + CA guide + backup schedule

### 3 Bugs Fixed in TallyPusher.cs
1. **Double envelope wrapping**: `PushAsync` wrapped backend XML (already had `<ENVELOPE>`) in another `<ENVELOPE>`. Tally rejected nested envelopes. Fixed: send XML directly, no wrapping.
2. **Wrong HttpClient injected**: Constructor took `HttpClient http` (unnamed, no base address). Posts went to `localhost:80` instead of `localhost:9000`. Fixed: changed to `IHttpClientFactory` and creates named `"Tally"` client.
3. **XML declaration in payload**: Backend stores `<?xml version="1.0" encoding="UTF-8"?>` which Tally can't parse. Fixed: `Regex.Replace(xml, xmlDeclPattern, "")` strips declaration before POST.

### New Files
| File | Purpose |
|------|---------|
| `tally-connector/InvoSyncTallyConnector.sln` | Visual Studio solution (v17) |
| `docs/CA_FEATURE_GUIDE.md` | One-page CA pitch doc |
| `scripts/backup_schedule.py` | Automated backup with hourly/daily/monthly rotation |
| `scripts/invosync-backup.service` | systemd oneshot service for Linux |
| `scripts/invosync-backup.timer` | systemd hourly timer |
| `scripts/invosync-backup-task.xml` | Windows Task Scheduler import XML |
| `tests/mock/mock_tally_server.py` | Tally Prime port 9000 emulator (relocated) |
| `tests/mock/mock_backend.py` | Cloud API port 8000 emulator (relocated) |
| `tests/mock/test_local_pipeline.py` | E2E pipeline diagnostic (relocated) |

### Build Output
- .NET 10 SDK: `dotnet publish` produces 75 MB self-contained `.exe` at `tally-connector/InvoSyncTallyConnector/bin/Release/net10.0/win-x64/publish/InvoSyncTallyConnector.exe`
- 16/16 pipeline tests pass (poll → verify state → push → confirm)

### Backup Strategy
- Hourly: last 24h (prunes beyond)
- Daily: last 30d (one per day)
- Monthly: last 12mo (one per month)
- Script at `scripts/backup_schedule.py` — cron/systemd/Task Scheduler compatible

### What Changed
- **Dual-pane layout**: Invoice image displayed on the left, editable extracted fields on the right, side-by-side like Vyapar TaxOne's review screen.
- **Draft → Validated state machine**: After extraction, invoices start as `draft`. User must explicitly click "Review & Confirm" to transition to `validated`. XML download is only shown after confirmation.
- **Mandatory ledger mapping**: Each line item now has a required ledger dropdown (select from Tally-ledgers or common ledgers). Review is blocked until every item has a ledger assigned.
- **Mismatch/confidence highlighting**: Fields with confidence <0.6 get yellow borders. Low-confidence (<0.7) triggers a "Needs Review" badge and yellow container ring. A separate confidence card shows the AI confidence bar with warning text.
- **Dashboard status badges**: "Draft" (yellow), "Reviewed" (green), "Exported" (blue) badges replace the old decision-only display. Draft invoices show "Review" button.

### Backend
- **`database.py`**: `insert_invoice()` now accepts `image_data` (base64 string). Invoice documents store `image_data`, `item_ledgers`, `reviewed_at`, `reviewed_by`.
- **`main.py`**:
  - `/extract` stores image as base64 in the invoice document. Returns `_image_available` flag.
  - `GET /invoices/{id}/image` — returns the stored invoice image as JPEG.
  - `PUT /invoices/{id}` — updates extracted data + item_ledgers.
  - `POST /api/v3/invoices/{id}/confirm-review` — validates mandatory fields + ledger assignment, transitions status from `draft` to `validated`. Returns 422 with specific errors if validation fails.

### Frontend
- **`App.jsx:ExtractPage`**:
  - After extraction, shows a `grid-cols-1 lg:grid-cols-2` layout: image card (left) + fields card (right).
  - Image card: loads from `/invoices/{id}/image` endpoint. Shows placeholder when no image.
  - Right card: all field inputs + confidence highlights (yellow borders for <0.6) + ledger dropdown per item.
  - "Review & Confirm" button sends to `/api/v3/invoices/{id}/confirm-review`. On success, button becomes "Download XML".
  - Error display block for review failures.
- **`App.jsx:DashboardPage`**: Status column now shows colored badges: Draft (yellow `tag-yellow`), Reviewed (green `tag-green`), Exported (blue `tag-blue`). XML action column shows "Review" for draft invoices that redirects to the review workspace.

### Flow
1. Upload invoice → extraction populates fields → dual-pane shows image + fields
2. User edits fields, assigns ledgers to each line item → clicks "Review & Confirm"
3. Backend validates: vendor name, invoice number, date, total amount, line items present, all ledgers assigned
4. If valid → status becomes `validated` → "Download XML" button appears
5. If invalid → error messages shown in red block, user fixes and retries
6. Dashboard shows review status. Clicking "Review" on a draft invoice loads the workspace.

### Fix 20 — Production logging: replaced all print() with structured logging + request middleware
- **core/logging.py**: `get_logger(name)` — single stdout handler with timestamp/level format. No file handlers (cloud containers log to stdout). Exported as `get_logger(__name__)` in every module.
- **core/debug.py**: `@time_it` decorator — logs function duration in ms. Works for sync and async. Applied to `ExtractionPipeline.extract()` and `/extract` route.
- **main.py**: Replaced all 10 `print()` calls with `logger.info/debug/error`. Added `@app.middleware("http")` logging middleware that logs every request with method, path, status code, and duration in ms.
- **extractors.py**: Replaced 4 `print()` calls with `logger.info/warning`.
- **xml_generator.py**: Replaced 1 `print()` with `logger.info`.
- **Not done** (rejected from advice): custom exception classes (plain `HTTPException` is fine), file logging (disappears in containers), `exc_info=True` on every call (bloats logs), `@retry` on AI calls (same image won't fix API errors), folder restructure (premature for current scale).
- Verdict on the advice: ~60% good, ~40% enterprise cargo-cult. We took what helps at 3 AM.

## How to Add a New Edge Case
1. Add it to the tracker above with severity + status
2. If severity=High, add it to the "Next Sprints" section
3. Update this file with status changes as work progresses
4. Treat this as a living roadmap — revisit monthly
