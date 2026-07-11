# Invoice to Tally XML

Extract invoice data from images using Gemini AI and generate Tally Prime Purchase Voucher XML.

## Setup

### 1. API Key

Copy `.env` and set your Gemini API key:

```
GEMINI_API_KEY=your_actual_key
```

### 2. Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Gemini API key (required) |
| `COMPANY_STATE_CODE` | `27` | Your company's GST state code (Maharashtra) |
| `COMPANY_NAME` | `My Company` | Company name in XML header |
| `PURCHASE_LEDGER` | `Purchase` | Purchase account ledger name |
| `CGST_LEDGER` | `CGST` | CGST ledger name |
| `SGST_LEDGER` | `SGST` | SGST ledger name |
| `IGST_LEDGER` | `IGST` | IGST ledger name |
| `VOUCHER_TYPE` | `Purchase` | Voucher type in Tally |

### 3. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Runs on `http://localhost:8000`.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev


Runs on `http://localhost:5173`.

## Usage

1. Open `http://localhost:5173` in a browser.
2. **Extract tab** — Drag & drop an invoice image onto the upload zone.
3. Review and edit the extracted fields. GSTIN is optional (leave empty if not on invoice).
4. Click **Validate & Download XML**.
5. **Dashboard tab** — view all processed invoices, re-download XML, or generate XML for extracted invoices.
6. Click any row in the Dashboard to edit that invoice's data in the Extract tab.

## Endpoints

- `POST /extract` — Upload an invoice image, returns extracted JSON.
- `POST /generate-xml` — Send validated invoice data, returns Tally XML.
- `POST /generate-xml/{id}` — Generate XML for an existing record.
- `POST /invoices/{id}/generate` — Validate stored data and generate XML server-side.
- `GET /invoices` — List all processed invoices.
- `GET /invoices/{id}` — Get full invoice data.
- `GET /invoices/{id}/xml` — Download generated XML.
- `GET /health` — Health check.

## XML Generation

- Root `<ENVELOPE>` with `<HEADER>` and `<BODY>`.
- Debit: Purchase account + CGST/SGST (intra-state) or IGST (inter-state).
- Credit: Supplier account.
- Tax type determined by comparing vendor GSTIN state code with `COMPANY_STATE_CODE`.
- All ledger names are configurable via environment variables.
- Inventory entries for each line item with stock name, quantity, rate, amount, and GST class.
