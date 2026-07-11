import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="InvoSync Cloud Production API Emulator")


@app.get("/api/v3/sync/pending")
async def serve_mock_validated_sync_payload():
    print("[MOCK BACKEND 8000] C# Polling Client connected. Serving pending validated invoices...")

    mock_pending = {
        "count": 1,
        "invoices": [
            {
                "display_id": 7712,
                "status": "validated",
                "vendor_name": "Maruti Suzuki Distributors",
                "invoice_number": "INV-EMULATED-99",
                "voucher_type": "Purchase",
                "total_amount": 11800.00,
                "xml_content": """<ENVELOPE>
                    <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
                    <BODY>
                        <IMPORTDATA>
                            <REQUESTDESC>
                                <REPORTNAME>Vouchers</REPORTNAME>
                                <STATICVARIABLES>
                                    <SVCURRENTCOMPANY>InvoSync Test Logistics Pvt Ltd</SVCURRENTCOMPANY>
                                </STATICVARIABLES>
                            </REQUESTDESC>
                            <REQUESTDATA>
                                <TALLYMESSAGE xmlns:UDF="TallyUDF">
                                    <VOUCHER VCHTYPE="Purchase" ACTION="Create">
                                        <DATE>20260710</DATE>
                                        <VOUCHERNUMBER>INV-EMULATED-99</VOUCHERNUMBER>
                                        <PARTYLEDGERNAME>Maruti Suzuki Distributors</PARTYLEDGERNAME>
                                        <ALLLEDGERENTRIES.LIST>
                                            <LEDGERNAME>Maruti Suzuki Distributors</LEDGERNAME>
                                            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                                            <AMOUNT>11800.00</AMOUNT>
                                        </ALLLEDGERENTRIES.LIST>
                                        <ALLLEDGERENTRIES.LIST>
                                            <LEDGERNAME>Purchase Accounts</LEDGERNAME>
                                            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                                            <AMOUNT>-11800.00</AMOUNT>
                                        </ALLLEDGERENTRIES.LIST>
                                    </VOUCHER>
                                </TALLYMESSAGE>
                            </REQUESTDATA>
                        </IMPORTDATA>
                    </BODY>
                </ENVELOPE>""",
            }
        ],
    }
    return JSONResponse(content=mock_pending)


@app.post("/api/v3/sync/confirm/{display_id}")
async def handle_mock_sync_confirmation(display_id: int):
    print(f"[MOCK BACKEND 8000] SUCCESS: C# Client confirmed Invoice #{display_id} is live in Tally Prime database.")
    return {"status": "ok", "message": f"Invoice #{display_id} marked as exported"}


@app.post("/api/v3/sync/error/{display_id}")
async def handle_mock_sync_errors(display_id: int, request: Request):
    body = await request.json()
    error_msg = (body or {}).get("error", "Unknown Tally error")
    print(f"[MOCK BACKEND 8000] REJECTION: C# Client reported a Tally import error for Invoice #{display_id}.")
    print(f"   Root Cause: {error_msg}")
    return {"status": "ok", "message": f"Sync error recorded for invoice #{display_id}"}


if __name__ == "__main__":
    print("Initializing InvoSync Cloud API Port 8000 Simulator...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
