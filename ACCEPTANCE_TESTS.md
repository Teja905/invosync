# InvoSync — Acceptance Test Checklist

**Purpose:** Verify InvoSync is ready for paying customers before pilot launch.

**Rule:** Don't launch until you've processed 20 real invoices and imported 10 real XMLs into Tally.

---

## Day 1: Find Your CA Partner

### The Pitch

> "Hi [Name], I'm building InvoSync — an AI platform that reads invoices and generates Tally XML. I'm looking for 3 CAs to test it before launch. I'll give you 3 months of Professional tier (₹2,999/month) free in exchange for 10 hours of testing. You'd just process your real invoices and tell me what works. Are you interested?"

### Questions to Ask

| Question | Why |
|----------|-----|
| "How many invoices per client per month?" | Know volume |
| "What formats do you receive?" | Know input variety |
| "What do you hate about your current workflow?" | Value prop |
| "Can you share 20-30 invoices for testing?" | Get real data |
| "Do you have Tally Prime?" | XML import verification |

---

## Day 2: Real Invoice Extraction Test

### Test Matrix

| Test | Type | Qty | Target |
|------|------|-----|--------|
| T1 | Clean PDF (software-generated) | 5 | ≥95% accuracy |
| T2 | Scanned/photo (thermal receipt) | 5 | ≥80% accuracy |
| T3 | Handwritten with stamps | 3 | ≥70% accuracy |
| T4 | Multi-page (PO + invoice + challan) | 3 | ≥85% accuracy |
| T5 | Multi-item (10+ line items) | 4 | ≥90% accuracy |

### Field Accuracy Tracker

| Invoice | Vendor | GSTIN | Invoice # | Date | Total | Tax | HSN | TDS | Status |
|---------|--------|-------|-----------|------|-------|-----|-----|-----|--------|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| ... | | | | | | | | | |

### Acceptance Criteria

| Field | Minimum |
|-------|---------|
| Vendor Name | ≥90% |
| Vendor GSTIN | ≥95% |
| Invoice Number | ≥95% |
| Date | ≥95% |
| Total Amount | ≥98% |
| Tax Amount | ≥95% |
| HSN/SAC | ≥85% |
| TDS Rate | ≥85% |
| **Overall** | **≥85%** |

---

## Day 3: Tally XML Import Test

### Steps

1. Install Tally Prime (Educational version OK)
2. Create test company "InvoSync Test Co"
3. Generate 10 XMLs from InvoSync
4. Import each XML (Gateway → Import Data → Vouchers)
5. Verify in Tally: vouchers exist, ledgers correct, GST split correct, balances match

### Import Tracker

| XML # | Imported? | Error Message | Root Cause | Fix |
|-------|-----------|---------------|------------|-----|
| 1 | | | | |
| 2 | | | | |
| ... | | | | |

### Acceptance Criteria

| Score | Decision |
|-------|----------|
| ≥9/10 clean | Launch ready |
| 7-8/10 clean | 1 week of fixes needed |
| <7/10 clean | Don't launch — major XML issues |

---

## Day 4: GSTR Reconciliation Test

### Steps

1. CA exports GSTR-2A JSON from GST portal (1 client, 1 month)
2. Upload to InvoSync
3. Run reconciliation against 20 invoices
4. Verify matches manually with CA

### Match Classification

| Type | Meaning | Acceptable % |
|------|---------|--------------|
| Matched | In both InvoSync and GSTR-2A | ≥85% |
| Amount Mismatch | Same vendor, different amount | ≤5% |
| Missing in Books | In GSTR-2A but not InvoSync | ≤5% |
| Missing in GSTR-2A | In InvoSync but not GSTR-2A | ≤5% |

### Verification Table

| Invoice | InvoSync Amount | GSTR-2A Amount | Match? | Notes |
|---------|----------------|----------------|--------|-------|
| 1 | | | | |
| 2 | | | | |
| ... | | | | |

---

## Day 5: TDS Verification

### Steps

1. CA provides 10 invoices where TDS applies
2. Run TDS detection in InvoSync
3. Compare with actual TDS deducted by CA

### TDS Test Cases

| Section | Invoice Type | Expected |
|---------|-------------|----------|
| 194C | Contractor | 194C |
| 194J(a) | Professional fees | 194J(a) |
| 194J(b) | Technical services | 194J(b) |
| 194H | Commission | 194H |
| 194I(a) | Rent - Plant | 194I(a) |
| 194I(b) | Rent - Building | 194I(b) |
| 194A | Interest | 194A |

### TDS Accuracy Tracker

| Invoice | Actual Section | InvoSync Suggested | Match? |
|---------|---------------|--------------------|----|
| 1 | | | |
| 2 | | | |
| ... | | | |

---

## Final Scorecard

| Requirement | Target | Actual | Pass? |
|-------------|--------|--------|-------|
| XML import success | ≥99% | | |
| Debit/Credit balance | 100% | | |
| No data loss | 100% | | |
| Real invoice field accuracy | ≥95% | | |
| Real Tally report matches | 100% | | |
| Pilot CA satisfaction | "I'd use this daily" | | |
| Critical production crashes | 0 | | |
| Security issues | 0 high-severity | | |
| Backup and restore tested | Yes | | |
| End-to-end workflow proven | Yes | | |

---

## Launch Decision

| Score | Decision | Pricing |
|-------|----------|---------|
| ≥85% all tests | LAUNCH | ₹2,999/month |
| ≥80% core, ≥70% GSTR/TDS | LAUNCH WITH LABELS | ₹999 core, ₹2,999 verified |
| <80% core | FIX FIRST | ₹0 |

---

## What to Tell the CA After Testing

> "Thank you. Here's what we found:
> - Extraction accuracy on clean PDFs: [X]%
> - Extraction accuracy on thermal receipts: [X]%
> - XML imports into Tally: [X]/10 clean
> - GSTR reconciliation: [X]% matched
> - TDS detection: [X]% accurate
>
> We'll fix these issues and come back in 2 weeks. You'll get 3 months free when we launch."

---

## The One Rule

**Don't launch until you've processed 20 real invoices and imported 10 real XMLs into Tally.**

Everything else is guesswork. This is reality.

---

*Created: 2026-07-23*
*Status: Ready for execution*
