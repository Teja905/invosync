# Edge Cases Tracker

## Fixed
- CGST/SGST vs IGST routing via buyer/vendor GSTIN comparison
- Sales invoice → Purchase voucher (GSTIN direction detection, Fix 17)
- Service invoice with inventory entries (is_service flag, Fix 19)
- Duplicate invoice detection (SHA-256 file hash)
- Empty/whitespace vendor name (Fix 25)
- Credit/Debit Note inventory support (Fix 17)
- Tally master creation before voucher (Fix 18, 19)
- XML declaration stripping before Tally push (Fix 22)
- Nested envelope wrapping (Fix 22)
- Pydantic v2 .dict() → .model_dump() (Fix 14)

## Known
- Reverse Charge (RCM): handled via is_rcm flag, needs (RCM) suffix on ledgers
- Exempt/Nil-rated: empty tax list allowed
- Rounding drift: auto-allocated to Round Off ledger
- Missing GSTIN: soft error, force-overridable

## Not Yet Tested
- Foreign currency invoices
- Discount pre/post GST
- SEZ with LUT
- Import of Services
- Composition dealer invoices
- E-commerce operator invoices
- TDS on multiple line items
- Partial credit notes (different rates per returned item)
