# Architecture

```
User uploads invoice image
        │
        ▼
Frontend (React + Vite)
        │
        ├── POST /extract ──────────────────┐
        │                                    │
        ▼                                    ▼
Backend (FastAPI)                    AI Extraction Pipeline
         │                             Gemini
        │                                    │
        │                                    ▼
        │                            OCR Post-Processing
        │                             (dates, GSTIN, tax rates)
        │                                    │
        │                                    ▼
        │                            StandardizedInvoice schema
        │                                    │
        ├── POST /api/v3/voucher-type/suggest
        │     → Returns "Purchase" + rationale
        │     → User confirms or overrides
        │                                    │
        ▼                                    ▼
Validation Layer ────► XML Generator ────► Tally XML
  Check: balance          │
  Check: GSTIN            ├── Purchase voucher (goods → inventory)
  Check: tax rates        ├── Purchase voucher (services → ledger only)
  Check: amounts match    ├── Sales, Journal, Payment, etc.
  Check: XML structure    └── Bill allocations for party tracking
        │
        ▼
MongoDB (invoice history, dashboard)
```

## Data Flow

```
Image → AI Extractor → Raw JSON → OCR Post-Process → StandardizedInvoice
  → Validation → XML Generator → Tally XML string → Download/Import
```

## Module Dependencies

```
schemas.py (no deps — base types)
    ├── gst_engine.py
    ├── company_config.py
    ├── voucher_classifier.py
    ├── ocr_postproc.py
    │
    ├── ledger_mapping.py (depends on company_config)
    ├── xml_generator.py (depends on schemas, company_config, ledger_mapping, gst_engine)
    ├── validation_layer.py (depends on schemas, gst_engine, voucher_classifier)
    │
    ├── extractors.py (depends on schemas, ocr_postproc, gst_engine)
    └── main.py (depends on everything)
```
