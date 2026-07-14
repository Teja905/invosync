# Tally XML Import Rules

## Envelope Structure
- XML must start with `<?xml version="1.0" encoding="UTF-8"?>`
- Each `<ENVELOPE>` must contain `<HEADER>` and `<BODY>`
- `<HEADER>` must contain `<TALLYREQUEST>Import Data</TALLYREQUEST>`
- Masters envelope: `REPORTNAME="All Masters"`
- Voucher envelope: `REPORTNAME="Vouchers"`

## Master Creation Order
1. `<VOUCHERTYPE>` — must be created before any voucher references it
2. `<STOCKGROUP>` — parent "Primary" must exist before stock items
3. `<STOCKITEM>` — must be created before inventory entries reference them
4. `<LEDGER>` — must be created before voucher entries reference them

## Voucher Rules
- `<VOUCHER>` must have `VCHTYPE` attribute matching a created voucher type
- `<SVCURRENTCOMPANY>` must match the Tally company name exactly
- `<DATE>` must be in `YYYYMMDD` format (no separators)
- `<VOUCHERNUMBER>` is required
- `<PARTYLEDGERNAME>` must reference a created ledger
- `ISINVOICE=Yes` requires `ALLINVENTORYENTRIES.LIST`; `No` forbids it

## Ledger Entry Rules
- Every `<ALLLEDGERENTRIES.LIST>` needs: `LEDGERNAME`, `ISDEEMEDPOSITIVE`, `AMOUNT`
- `ISDEEMEDPOSITIVE=Yes` = Debit entry (positive amount)
- `ISDEEMEDPOSITIVE=No` = Credit entry (negative amount)
- Party ledgers should have `<ISPARTYLEDGER>Yes</ISPARTYLEDGER>`
- Party entries need `<BILLALLOCATIONS.LIST>` for outstanding tracking

## Balance Invariant
- Sum of all AMOUNTs (excluding BILLALLOCATIONS and ALLINVENTORYENTRIES) must equal 0.00

## GST Ledger Naming
- Include rate in the name: "Input CGST @ 9%", "Input IGST 18%"
- CGST/SGST for intra-state (same state code)
- IGST for inter-state (different state codes)
- RCM ledgers must include "(RCM)" in the name

## Common Import Failures
1. Ledger referenced but not created as master
2. Stock item referenced but not created
3. Voucher type doesn't exist in company
4. Company name mismatch
5. Date format wrong (needs YYYYMMDD)
6. XML declaration present in payload (Tally can't parse it)
