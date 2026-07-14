# InvoSync — CA Feature Guide

## What It Does
InvoSync converts invoice images/PDFs into Tally Prime XML with zero manual data entry. Upload a photo, review AI-extracted fields, confirm, and import to Tally with one click.

## For Detailed Setup Instructions
See **`CA_COMPLETE_GUIDE.md`** in the same folder for:
- One-time Tally setup (7 groups, port 9000, stock groups)
- First invoice walkthrough with screenshots
- What our code creates vs what you must create
- Testing XML before import
- Troubleshooting

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
   Download XML OR auto-sync via Connector
        |
   C# Connector (Windows tray app) pushes to Tally Prime
```

## What You Get

| Feature | Detail |
|---------|--------|
| OCR extraction | Gemini AI via OpenRouter — handles photos, scans, PDFs |
| Dual-pane review | Invoice image side-by-side with editable fields |
| GST statutory firewall | Hardcoded CGST Act rules — SEZ, LUT, RCM, UTGST |
| Tally XML | 7 voucher types, balanced, with ledger + stock masters |
| Auto Tally import | C# Windows tray app — polls cloud, pushes to port 9000 |
| Dashboard | Draft/Reviewed/Exported status — full audit trail |
| Correction memory | Learns your ledger preferences over time |
| Multi-company | Switch between multiple Tally companies |

## Ledgers Covered
- Purchase/Sales accounts (configurable via Settings)
- CGST/SGST/IGST (Input + Output, per slab)
- TDS, Freight, Round-off, Bank, Suspense
- Vendor/customer party ledgers with GSTIN + state

## Requirements
- Tally Prime (any version) with port 9000 enabled
- Windows 64-bit (for the Connector .exe)
- Internet (for cloud dashboard + AI extraction)

## Quick Setup
1. Read `CA_COMPLETE_GUIDE.md` for one-time Tally setup
2. Install the Connector from InvoSync Settings
3. Complete the Setup Wizard (login + Tally auto-detect)
4. Upload your first invoice — the connector handles the rest

## Security
- No Tally data leaves your LAN
- Connector runs locally, talks to cloud via HTTPS
- Full audit log per invoice (who reviewed, when, what changed)

## Support
- See `CA_COMPLETE_GUIDE.md` for troubleshooting
- Email: support@invosync.com
- Setup walkthrough: docs.invosync.com/setup
