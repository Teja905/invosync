# InvoSync — One-Page CA Guide

## What It Does
InvoSync converts invoice images/PDFs into Tally Prime XML with zero manual data entry. Upload a photo, review AI-extracted fields, confirm, and import to Tally with one click.

## Workflow (30 seconds per invoice)

```
Upload invoice photo/PDF
        |
   AI extracts: vendor, GSTIN, items, tax, totals
        |
   Review in dual-pane: image (left) vs fields (right)
        |
   Assign ledger to each line item
        |
   Click "Review & Confirm" — statutory firewall checks:
     - SEZ -> IGST only | Intra-state -> CGST+SGST
     - Inter-state -> IGST | LUT -> 0% tax
   Status: Draft -> Validated
        |
   Download XML or auto-sync via Connector
        |
   C# Connector (Windows service) pushes to Tally Prime
```

## What You Get

| Feature | Detail |
|---------|--------|
| OCR extraction | Gemini AI via OpenRouter — handles photos, scans, PDFs |
| Dual-pane review | Invoice image side-by-side with editable fields |
| GST statutory firewall | Hardcoded CGST Act rules — SEZ, LUT, RCM, UTGST |
| Tally XML | 7 voucher types, balanced, with ledger + stock masters |
| Auto Tally import | C# Windows service — polls cloud, pushes to port 9000 |
| Dashboard | Draft/Reviewed/Exported status — full audit trail |

## Ledgers Covered
- Purchase/Sales accounts (configurable via Settings)
- CGST/SGST/IGST (Input + Output, per slab)
- TDS, Freight, Round-off, Bank, Suspense
- Vendor/customer party ledgers with GSTIN + state

## Requirements
- Tally Prime (any version) with port 9000 enabled
- Windows 64-bit (for the Connector .exe)
- Internet (for cloud dashboard + AI extraction)

## One-Click Setup
1. Run `InvoSyncSetup.exe` — installs Windows service
2. Open Tally Prime — enable port 9000
3. Log into cloud dashboard at app.invosync.com
4. Upload your first invoice — the connector handles the rest

## Security
- No Tally data leaves your LAN
- Connector runs locally, talks to cloud via HTTPS
- Full audit log per invoice (who reviewed, when, what changed)

## Support
- Email: support@invosync.com
- Setup walkthrough: docs.invosync.com/setup
- Pilot firms get 3 months free + dedicated onboarding
