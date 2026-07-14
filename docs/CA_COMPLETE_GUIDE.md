# InvoSync — Complete CA Guide
## From First Setup to Automated Tally Import

---

## Table of Contents
1. [What Is InvoSync?](#1-what-is-invosync)
2. [What You Need](#2-what-you-need)
3. [One-Time Tally Setup (5 minutes)](#3-one-time-tally-setup-5-minutes)
4. [How It Works — The Big Picture](#4-how-it-works--the-big-picture)
5. [The Connector — Auto Import Explained](#5-the-connector--auto-import-explained)
6. [What Our Code Creates Automatically](#6-what-our-code-creates-automatically)
7. [Testing XML Before Import](#7-testing-xml-before-import)
8. [Step-by-Step: First Invoice](#8-step-by-step-first-invoice)
9. [Troubleshooting](#9-troubleshooting)
10. [Advanced Settings](#10-advanced-settings)

---

## 1. What Is InvoSync?

InvoSync is an AI-powered tool that converts invoice images/PDFs into Tally Prime vouchers automatically.

**The problem it solves:**
- Manual data entry in Tally is slow and error-prone
- Bookkeepers spend 5–10 minutes per invoice typing vendor, items, GST, amounts
- Wrong ledger selection, tax calculation mistakes, and duplicate entries are common

**What InvoSync does:**
1. You upload an invoice photo/PDF
2. AI extracts vendor name, GSTIN, line items, tax rates, and totals
3. You review and confirm in a side-by-side view (image left, fields right)
4. Our backend generates a balanced Tally XML with all masters (ledgers, stock items, voucher types)
5. The Windows Connector auto-pushes the XML to Tally Prime over HTTP
6. The voucher appears in Tally — zero manual typing

**Time saved:** 5–10 minutes → 30 seconds per invoice.

---

## 2. What You Need

| Requirement | Details |
|-------------|---------|
| **Tally Prime** | Any recent version (Prime 3.0+ recommended). Must allow remote access on port 9000. |
| **Windows 64-bit** | For the Connector desktop app (`.exe`). |
| **Internet** | For cloud dashboard and AI extraction (OpenRouter/Gemini). |
| **Company in Tally** | The Tally company where vouchers will be imported. |

**No Tally license restrictions apply** for XML import. The educational version works fine.

---

## 3. One-Time Tally Setup (5 minutes)

You only do this **once** per Tally company.

### Step 3.1 — Enable Port 9000

1. Open **Tally Prime**
2. Press **F12** (Gateway of Tally) → **Settings**
3. Go to **Connectivity** → **Tally.NET Settings**
4. Set:
   - **Port**: `9000`
   - **Allow Remote Access**: `Yes`
5. Press **Ctrl+A** to save
6. **Close and reopen Tally Prime**

### Step 3.2 — Verify 7 Groups Exist

Go to **Gateway of Tally → Accounts Info → Groups** and ensure these exist:

| # | Group Name | Exact Spelling | Purpose |
|---|-----------|----------------|---------|
| 1 | **Sundry Creditors** | Case-sensitive | Holds all vendor ledgers (for Purchase, Credit Note, Debit Note) |
| 2 | **Sundry Debtors** | Case-sensitive | Holds all customer ledgers (for Sales, Receipt) |
| 3 | **Purchase Accounts** | Case-sensitive | Holds Purchase ledger, Freight, Round-Off |
| 4 | **Sales Accounts** | Case-sensitive | Holds Sales ledger |
| 5 | **Bank Accounts** | Case-sensitive | Holds Bank ledger for Payment/Receipt |
| 6 | **Current Liabilities** | Case-sensitive | Holds TDS Payable ledger |
| 7 | **Duties & Taxes** | Case-sensitive | Holds all GST ledgers (CGST/SGST/IGST) |

> **If any group is missing:** Create it manually. The exact name matters — it is case-sensitive.

### Step 3.3 — Enable Stock Groups (for goods invoices)

1. In Tally, press **F11** (Features)
2. Go to **Inventory Features**
3. Enable **"Maintain Stock Groups"** = Yes
4. Save with **Ctrl+A**

> The default stock group **"Primary"** is built into Tally. Do NOT rename or delete it.

### Step 3.4 — Note Your Company Name

Look at the Tally title bar. The company name is case-sensitive and must match exactly in InvoSync settings.

Example: If Tally shows **"My Firm & Co."**, enter exactly that in InvoSync Settings.

---

## 4. How It Works — The Big Picture

```
┌──────────────────────────────────────────────────────────────────┐
│                        INVOICE UPLOAD                            │
│  You drop an invoice image/PDF into InvoSync web app             │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                     AI EXTRACTION (5-10 sec)                     │
│  - Vendor name, GSTIN, address                                  │
│  - Invoice number, date, due date                               │
│  - Line items: description, qty, rate, taxable value, tax rate  │
│  - Freight, round-off, TDS if present                           │
│  - Document type: tax invoice, retail bill, expense receipt     │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    DUAL-PANE REVIEW                              │
│  Left side : Invoice image (zoomable)                           │
│  Right side: Editable extracted fields                          │
│  - Yellow borders = low confidence (< 60%)                      │
│  - Red borders  = validation error                               │
│  - Confidence bar shows AI certainty                             │
│  - Assign Tally ledger to each line item (dropdown)             │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│              "REVIEW & CONFIRM" — STATUTORY FIREWALL             │
│  Backend validates before export:                                │
│  ✓ Vendor name + invoice number + date present                  │
│  ✓ Total amount matches line items + tax                         │
│  ✓ CGST+SGST for intra-state, IGST for inter-state              │
│  ✓ Tax rates are valid slabs (0, 5, 12, 18, 28%)                │
│  ✓ GSTIN format + checksum valid                                 │
│  ✓ Every line item has a ledger assigned                         │
│  If any check fails → blocked with specific error message        │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    XML GENERATION                                │
│  Two envelopes in one file:                                      │
│                                                                  │
│  Envelope 1: ALL MASTERS (creates everything in Tally)          │
│  ├── Voucher Type (Purchase/Sales/etc.)                         │
│  ├── Stock Group "Primary"                                       │
│  ├── Stock Items (Laptop, Monitor, etc. with HSN)               │
│  ├── Party Ledger (vendor/customer with GSTIN)                  │
│  ├── Transaction Ledger (Purchase, Sales, etc.)                 │
│  ├── GST Tax Ledgers (Input CGST 18%, Output IGST 5%, etc.)     │
│  ├── Auxiliary Ledgers (Freight, TDS, Round-Off) if present     │
│                                                                  │
│  Envelope 2: VOUCHER (the actual accounting entry)              │
│  ├── Balanced double-entry (sum of all amounts = 0)             │
│  ├── Bill allocations for party ledger                           │
│  ├── Inventory entries for goods                                 │
│  └── Ledger entries with correct debit/credit signs             │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    AUTO IMPORT TO TALLY                          │
│  The Windows Connector (tray app) does the rest:                 │
│  1. Polls InvoSync cloud every 30 seconds                        │
│  2. Finds validated invoices                                     │
│  3. Pushes XML to Tally Prime on port 9000                      │
│  4. Tally imports masters first, then voucher                    │
│  5. Connector reports success/failure back to cloud              │
│  6. You see "Today: N ✓" in the connector tray icon             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. The Connector — Auto Import Explained

### What Is the Connector?

A lightweight Windows desktop app (`.exe`) that runs in the background. It sits in your system tray and automatically pushes validated invoices from InvoSync into Tally Prime.

### How to Install

1. Download `InvoSyncTallyConnector.exe` from InvoSync Settings page
2. Double-click to run
3. First launch opens a **Setup Wizard**:
   - Step 1: Welcome
   - Step 2: Log into your InvoSync account
   - Step 3: Auto-detect Tally on port 9000
   - Step 4: Select which Tally company to import into
   - Step 5: Optionally start with Windows
   - Step 6: Done
4. After setup, the connector minimizes to the system tray

### How Auto-Import Works

```
Every 30 seconds:
   Connector → Backend: "Any validated invoices pending?"
   Backend    → Connector: "Yes, here are 3 invoices"
   Connector  → Tally: POST XML (port 9000)
   Tally      → Connector: "Imported successfully"
   Connector  → Backend: "Mark invoice #5 as exported"
   You see:   Tray tooltip "Today: 3 ✓"
```

### What You See in the Connector

| Element | Meaning |
|---------|---------|
| **● Connector** (green) | Connected to InvoSync cloud |
| **● Tally** (green) | Tally Prime reachable on port 9000 |
| **● InvoSync** (green) | Logged in, session valid |
| **Today: 47 ✓** | 47 invoices pushed successfully today |
| **Pending: 3** | 3 invoices waiting to push |
| **Failed: 0** | No failures |
| **Last sync: 2m ago** | Time since last successful push |

### Right-Click Tray Menu

| Option | Action |
|--------|--------|
| **Sync Now** | Immediately push all pending invoices (don't wait 30s) |
| **View Pending** | See which invoices are queued |
| **Open Web App** | Opens InvoSync dashboard in browser |
| **View Logs** | Opens today's log file in Notepad |
| **Check for Updates** | Checks if a newer connector version exists |
| **About** | Version info |
| **Exit** | Closes the connector |

---

## 6. What Our Code Creates Automatically

### The XML Has Two Parts

Every generated XML file contains **two `<ENVELOPE>` blocks**. Tally processes them in order:

#### Envelope 1: `REPORTNAME="All Masters"`

This creates **all required masters** before the voucher. You do NOT need to create these manually (except the 7 parent groups listed in Section 3).

| Master | Example | Condition |
|--------|---------|-----------|
| Voucher Type | `Purchase` | Always (if missing in Tally) |
| Stock Group | `Primary` | Goods invoices only |
| Stock Item | `Laptop - Dell` with HSN `847130` | Goods invoices, per unique item |
| Party Ledger | `ABC Electronics` with GSTIN `27AABCU1234D1ZT` | Always (vendor for purchase, customer for sales) |
| Transaction Ledger | `Purchase` | Always |
| GST Tax Ledger | `Input CGST @ 18%` | When tax exists |
| Freight Ledger | `Freight Expenses` | When `freight > 0` |
| TDS Ledger | `TDS Payable` | When `tds_amount > 0` |
| Round-Off Ledger | `Round Off` | When `round_off != 0` |
| Cess Ledger | `Input Cess` | When `cess_amount > 0` |

#### Envelope 2: `REPORTNAME="Vouchers"`

This creates the **actual voucher** with balanced accounting entries:

```xml
<VOUCHER VCHTYPE="Purchase">
  <DATE>20250701</DATE>
  <VOUCHERNUMBER>INV-2025-001</VOUCHERNUMBER>
  <PARTYLEDGERNAME>ABC Electronics</PARTYLEDGERNAME>
  <PARTYGSTIN>27AABCU1234D1ZT</PARTYGSTIN>

  <!-- Debit entries (purchase amount + tax) -->
  <ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>Purchase</LEDGERNAME>
    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <AMOUNT>155000.00</AMOUNT>
  </ALLLEDGERENTRIES.LIST>

  <ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>Input IGST 18%</LEDGERNAME>
    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
    <AMOUNT>27900.00</AMOUNT>
  </ALLLEDGERENTRIES.LIST>

  <!-- Credit entry (party + bill allocation) -->
  <ALLLEDGERENTRIES.LIST>
    <LEDGERNAME>ABC Electronics</LEDGERNAME>
    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
    <AMOUNT>-182900.00</AMOUNT>
    <BILLALLOCATIONS.LIST>
      <NAME>INV-2025-001</NAME>
      <BILLTYPE>New Ref</BILLTYPE>
      <AMOUNT>-182900.00</AMOUNT>
    </BILLALLOCATIONS.LIST>
  </ALLLEDGERENTRIES.LIST>

  <!-- Inventory entries (goods only) -->
  <ALLINVENTORYENTRIES.LIST>
    <STOCKITEMNAME>Laptop - Dell</STOCKITEMNAME>
    <HSNCODE>847130</HSNCODE>
    <QUANTITY>2</QUANTITY>
    <RATE>50000.00</RATE>
    <AMOUNT>100000.00</AMOUNT>
  </ALLINVENTORYENTRIES.LIST>
</VOUCHER>
```

### Debit vs Credit Convention

| Entry Type | ISDEEMEDPOSITIVE | AMOUNT | Effect in Tally |
|------------|-------------------|--------|-----------------|
| Debit (Purchase, Expense, GST) | `Yes` | Positive number | **Debit** |
| Credit (Vendor, Customer) | `No` | Negative number | **Credit** |

**Balance check:** After removing `<BILLALLOCATIONS.LIST>` and `<ALLINVENTORYENTRIES.LIST>`, the sum of all `<AMOUNT>` values must be exactly `0`.

---

## 7. Testing XML Before Import

### Method A: Download XML from Web App (Recommended for Testing)

1. In the InvoSync web app, after reviewing an invoice, click **Download XML**
2. Save the `.xml` file
3. Open Tally Prime
4. Go to **Gateway of Tally → Import of Data → Vouchers**
5. Select the downloaded XML file
6. Press **Enter** to import

**What to verify in Tally:**
- Voucher appears with correct date and number
- All ledgers are created (check under Accounts Info → Ledgers)
- Stock items are created (if goods invoice)
- Debit and credit amounts balance to zero
- Bill allocation shows the invoice number

### Method B: Use the Connector (Production)

1. Click **Review & Confirm** in the web app
2. Ensure the connector is running (system tray icon)
3. Wait up to 30 seconds for auto-push, or right-click tray → **Sync Now**
4. Open Tally → **Gateway of Tally → Display Voucher Register**
5. Find the invoice by number

### Method C: Command-Line Test (No Tally Needed)

```powershell
# Generate a sample XML locally
cd C:\Users\Admin\Desktop\Project-Pauldirac\backend
python generate_test_invoice.py

# Output: test_invoice_abc_electronics.xml
```

You can inspect this file to see the exact XML structure before importing into Tally.

---

## 8. Step-by-Step: First Invoice

### Prerequisites
- [ ] Tally Prime open with your company
- [ ] Port 9000 enabled (F12 → Connectivity → Port 9000)
- [ ] 7 groups exist (see Section 3)
- [ ] Connector installed and running (system tray)

### Steps

1. **Open InvoSync** in your browser (`http://localhost:5173` or your deployed URL)

2. **Go to Settings** (top navigation)
   - Enter your **Company Name** (exactly as in Tally title bar)
   - Enter your **Company GSTIN**
   - Select your **State Code**
   - Click **Save Settings**

3. **Go to Clients** → **Add Client**
   - Company Name: e.g., `ABC Electronics`
   - Contact Person: e.g., `Rajesh Kumar`
   - GSTIN: optional

4. **Go to Extract** tab
   - Select the client from dropdown
   - Drop an invoice image/PDF into the upload zone
   - Wait 5–10 seconds for AI extraction

5. **Review the extracted data**
   - Left: Invoice image (verify against AI data)
   - Right: Editable fields
   - Yellow borders = low confidence — verify carefully
   - Assign a **ledger** to each line item (dropdown)

6. **Click "Review & Confirm"**
   - Backend runs statutory checks
   - If blocked: fix the errors shown in red
   - If passed: status becomes `Validated` (green)

7. **Download XML** (button appears after confirmation)
   - Click to download the `.xml` file
   - Test import in Tally (Method A above)

8. **Or let the Connector auto-push**
   - The connector detects the validated invoice
   - Auto-pushes to Tally within 30 seconds
   - You see "Today: 1 ✓" in the tray tooltip

9. **Verify in Tally**
   - Gateway of Tally → Display Voucher Register
   - Find your invoice by number
   - All ledgers and items should be present

---

## 9. Troubleshooting

### "Tally not reachable" in Connector

**Cause:** Port 9000 not enabled or Tally not open.

**Fix:**
1. Open Tally Prime
2. F12 → Connectivity → Tally.NET Settings
3. Port = `9000`, Allow Remote Access = `Yes`
4. Close and reopen Tally

### "Partially imported with errors" in Tally

**Cause:** One of the 7 parent groups is missing or misspelled.

**Fix:**
1. Check Tally's import error message
2. Go to Accounts Info → Groups
3. Verify exact names (case-sensitive):
   - Sundry Creditors
   - Sundry Debtors
   - Purchase Accounts
   - Sales Accounts
   - Bank Accounts
   - Current Liabilities
   - Duties & Taxes

### Voucher type missing in Tally

**Cause:** The voucher type (e.g., "Credit Note") doesn't exist in Tally.

**Fix:** InvoSync auto-creates it in the XML. If Tally still rejects, create it manually:
- Gateway of Tally → Accounts Info → Voucher Types → Create
- Or re-import the XML with "Create Masters" enabled

### Duplicate ledger warning

**Cause:** You manually created a ledger that InvoSync also tries to create.

**Fix:** Tally usually accepts this with a warning. To avoid warnings, let InvoSync create the ledger the first time, then reuse it.

### XML import works but amounts are wrong

**Cause:** The AI extracted incorrect quantities or rates.

**Fix:** In the InvoSync review screen, correct the line items before clicking "Review & Confirm". The XML is a direct reflection of what you confirm.

### Connector shows "Failed" in tray

**Cause:** Tally rejected the XML (usually due to missing masters or wrong company name).

**Fix:**
1. Right-click tray → **View Logs**
2. Check the error message
3. Fix the underlying issue in Tally (missing group, wrong company name)
4. Right-click tray → **Sync Now** to retry

---

## 10. Advanced Settings

### Environment Variables (Backend)

These can be set in the backend `.env` to match your Tally company's naming:

```env
# Parent groups (must exist in Tally — case-sensitive)
SUNDRY_CREDITORS_GROUP="Sundry Creditors"
SUNDRY_DEBTORS_GROUP="Sundry Debtors"
PURCHASE_ACCOUNTS_GROUP="Purchase Accounts"
SALES_ACCOUNTS_GROUP="Sales Accounts"
BANK_ACCOUNTS_GROUP="Bank Accounts"
CURRENT_LIABILITIES_GROUP="Current Liabilities"
DUTIES_TAXES_GROUP="Duties & Taxes"

# Default ledger names (InvoSync auto-creates these if missing)
TDS_PAYABLE_LEDGER="TDS Payable"
ROUND_OFF_LEDGER="Round Off"
FREIGHT_LEDGER="Freight Expenses"
BANK_LEDGER="Bank"
SUSPENSE_LEDGER="Suspense"

# Company identity
COMPANY_NAME="My Company"
COMPANY_GSTIN="27AABCU1234F1ZP"
COMPANY_STATE_CODE="27"
```

### Per-User Settings (Web App)

In InvoSync Settings, each user can configure:
- Company name, GSTIN, state code
- Default purchase/sales/bank ledgers
- Tally password (if port 9000 is protected)

### Correction Memory

If AI maps a description to the wrong ledger, add a correction in Settings → Ledger Corrections:
- Example: "AWS Cloud" → "Software Expenses"
- InvoSync remembers this and uses it for all future invoices

### Multi-Company

You can manage multiple Tally companies:
- Each company has isolated settings and invoices
- Switch companies via the dropdown in the top navigation
- The connector imports into whichever company is active

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│  FIRST TIME SETUP (once per company)                        │
│                                                             │
│  1. Tally: F12 → Connectivity → Port 9000, Allow Remote    │
│  2. Tally: Create 7 groups (Sundry Creditors, Debtors,     │
│     Purchase Accounts, Sales Accounts, Bank Accounts,       │
│     Current Liabilities, Duties & Taxes)                    │
│  3. Tally: F11 → Enable "Maintain Stock Groups"             │
│  4. InvoSync: Settings → Enter company name, GSTIN, state  │
│  5. Install connector, complete setup wizard                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  EVERY INVOICE (30 seconds)                                 │
│                                                             │
│  1. Upload invoice → AI extracts                            │
│  2. Review fields, assign ledgers                           │
│  3. Click "Review & Confirm"                                │
│  4. Download XML OR let connector auto-push                 │
│  5. Verify in Tally                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  CONNECTOR TRAY ICON MEANINGS                               │
│                                                             │
│  ● Green  = All good                                        │
│  ● Yellow = Tally not reachable (check port 9000)          │
│  ● Red    = Connector offline (restart .exe)                │
│                                                             │
│  Right-click → Sync Now   (force immediate push)            │
│  Right-click → View Logs   (debug errors)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Support

- **Email:** support@invosync.com
- **Setup walkthrough:** docs.invosync.com/setup
- **Pilot firms:** 3 months free + dedicated onboarding
