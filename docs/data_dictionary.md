# InvoSync MongoDB Data Dictionary

**Database**: `invoice_tally`  
**Driver**: Motor (async) — `AsyncIOMotorClient`  
**URI**: `MONGODB_URI` env var (default `mongodb://localhost:27017`)

---

## Collection: `invoices`

Primary invoice storage. Each document = one processed invoice.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `display_id` | int | ✓ | Auto-incrementing human-readable ID (`next_id("display_id")`) |
| `user_id` | string | ✓ | Owner email or user_id |
| `client_id` | int | ✓ | FK to `clients.client_id` |
| `created_at` | datetime | ✓ | UTC timestamp of insertion |
| `extracted` | object | ✓ | Raw extracted data from AI pipeline (see InvoiceDataLegacy shape) |
| `validation` | object | ✓ | ValidationResult.to_dict() output |
| `file_hash` | string | – | SHA-256 hex digest of original upload (for dedup) |
| `status` | string | – | One of: `draft`, `validated`, `exported`, `error` |

**Standard sub-fields within `extracted`**:

| Nested Field | Type | Description |
|-------------|------|-------------|
| `extracted.voucher_type` | string | Purchase / Sales / Payment / Receipt / Journal / Credit Note / Debit Note |
| `extracted.invoice_number` | string | Invoice no. from document |
| `extracted.invoice_date` | string | DD/MM/YYYY or YYYY-MM-DD |
| `extracted.vendor_name` | string | Supplier name |
| `extracted.vendor_gstin` | string | 15-char GSTIN |
| `extracted.buyer_name` | string | Buyer name |
| `extracted.buyer_gstin` | string | 15-char GSTIN |
| `extracted.total_amount` | number | Grand total |
| `extracted.total_taxable_value` | number | Sum of taxable values |
| `extracted.total_cgst` | number | Total CGST |
| `extracted.total_sgst` | number | Total SGST |
| `extracted.total_igst` | number | Total IGST |
| `extracted.line_items` | array[{object}] | Per-item breakdown (see LineItem schema) |
| `extracted.taxes` | array[{object}] | Tax summary entries (see TaxEntry schema) |
| `extracted.is_sez` | bool | SEZ transaction flag |
| `extracted.is_lut` | bool | LUT transaction flag |
| `extracted.is_rcm` | bool | Reverse Charge flag |
| `extracted.is_interstate` | bool | Cross-state flag |
| `extracted.doc_type` | string | AI document classification |

**Indexes**:
- `display_id` — unique
- `user_id` + `file_hash` — unique sparse (dedup)
- `user_id` + `client_id` — for dashboard queries

---

## Collection: `clients`

Each document = one client of the CA firm.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `client_id` | int | ✓ | Auto-incrementing (`next_id("client_id")`) |
| `user_id` | string | ✓ | Owner (CA firm user) |
| `company_name` | string | ✓ | Client company legal name |
| `client_name` | string | ✓ | Contact person name |
| `gstin` | string | – | 15-char GSTIN |
| `created_at` | datetime | ✓ | UTC timestamp |
| `invoice_count` | int | ✓ | Running count (incremented on insert) |

**Indexes**:
- `client_id` — unique
- `user_id` — for listing

---

## Collection: `counters`

Auto-increment sequence tracking. Single document per sequence name.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | string | ✓ | Sequence name: `"display_id"` or `"client_id"` |
| `seq` | int | ✓ | Current counter value |

**Documents**:
- `{_id: "display_id", seq: N}`  
- `{_id: "client_id", seq: N}`

---

## Collection: `users`

User accounts (email/password auth).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | ✓ | Auto-generated |
| `email` | string | ✓ | Login email (unique) |
| `password_hash` | string | ✓ | Werkzeug scrypt hash |
| `company_name` | string | – | CA firm name |
| `company_gstin` | string | – | Firm's GSTIN |
| `company_state_code` | string | – | 2-digit state code |
| `company_state_name` | string | – | Full state name |
| `sales_ledger` | string | – | Default: "Sales" |
| `purchase_ledger` | string | – | Default: "Purchase" |
| `freight_ledger` | string | – | Default: "Freight Expenses" |
| `tds_ledger` | string | – | Default: "TDS Payable" |
| `round_off_ledger` | string | – | Default: "Round Off" |
| `bank_ledger` | string | – | Default: "Bank" |
| `suspense_ledger` | string | – | Default: "Suspense" |
| `sundry_creditors_group` | string | – | Default: "Sundry Creditors" |
| `sundry_debtors_group` | string | – | Default: "Sundry Debtors" |
| `purchase_accounts_group` | string | – | Default: "Purchase Accounts" |
| `sales_accounts_group` | string | – | Default: "Sales Accounts" |
| `duties_taxes_group` | string | – | Default: "Duties & Taxes" |
| `bank_accounts_group` | string | – | Default: "Bank Accounts" |
| `current_liabilities_group` | string | – | Default: "Current Liabilities" |

**Indexes**:
- `email` — unique

---

## Collection: `corrections`

Manually saved corrections to extracted invoices (preserve human overrides).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | string | ✓ | Owner |
| `invoice_display_id` | int | ✓ | FK to invoices |
| `original` | object | ✓ | Snapshot of extracted data before edit |
| `corrected` | object | ✓ | User's corrected values |
| `created_at` | datetime | ✓ | UTC timestamp |

---

## Schema Types (Pydantic)

### StandardizedInvoice (used for validation + XML generation)
```
Field                  Type        Notes
─────────────────────────────────────────────────
voucher_type           VoucherType Enum(Purchase/Sales/...)
invoice_number         string
invoice_date           string
vendor_name            string
vendor_gstin           string      15 chars
vendor_state_code      string      2 digits
buyer_name             string
buyer_gstin            string      15 chars
buyer_state_code       string      2 digits
total_amount           Decimal     Grand total
total_taxable_value    Decimal
total_cgst             Decimal
total_sgst             Decimal
total_igst             Decimal
line_items             list[LineItem]
taxes                  list[TaxEntry]
is_sez                 bool
is_lut                 bool
is_rcm                 bool
is_interstate          bool
is_service             bool
reverse_charge         bool
document_class         DocumentClass Enum
gst_type               GSTType     CGST_SGST / IGST / NONE
adjustment_notes       list[str]   Linked invoices for credit/debit notes
```

### LineItem
```
Field           Type      Notes
─────────────────────────────────
description     string
hsn_sac         string
quantity        Decimal
rate            Decimal
taxable_value   Decimal
tax_rate        Decimal    Allowed: 0, 0.1, 0.25, 3, 5, 12, 18, 28
cgst_rate       Decimal
sgst_rate       Decimal
igst_rate       Decimal
unit            string     e.g. "Nos", "Kg", "Ltr", "Box"
```

### TaxEntry
```
Field    Type      Notes
─────────────────────────
name     string    Ledger name, e.g. "Input IGST 12%"
type     string    cgst / sgst / igst / cess
rate     Decimal   Tax rate percentage
amount   Decimal   Tax amount in rupees
```

---

## ValidationResult (embedded in invoice document)

```
{
  "passed": bool,
  "document_type": string,
  "checks": {
    "statutory_routing":   {"pass": bool, "message": string},
    "mandatory_fields":    {"pass": bool, "message": string},
    "voucher_balance":     {"pass": bool, "message": string},
    "gstin":               {"pass": bool, "message": string},
    "dates":               {"pass": bool, "message": string},
    "tax_rates":           {"pass": bool, "message": string},
    "gst_structure":       {"pass": bool, "message": string},
    "amount_math":         {"pass": bool, "message": string},
    "line_items":          {"pass": bool, "message": string},
    "voucher_type":        {"pass": bool, "message": string},
    "ledger_fallback":     {"pass": bool, "message": string},
    "expense_class":       {"pass": bool, "message": string},
    "referenced_ledgers":  {"pass": bool, "message": list[str]},
    "adjustment_links":    {"pass": bool, "message": string},
  },
  "warnings": [string],
  "soft_errors": [string],
  "blocking_errors": [string]
}
```

---

## Backup Schema (via `scripts/backup_mongo.py`)

Each collection is exported as a gzipped JSON array of documents.

```
backups/invo_sync_backup_{YYYYMMDD_HHMMSS}/
├── _meta.json               # {backup_time, uri_redacted, database, collections, total_docs}
├── invoices.json.gz
├── clients.json.gz
├── counters.json.gz
├── users.json.gz
└── corrections.json.gz
```
