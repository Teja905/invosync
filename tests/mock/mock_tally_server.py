import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI(title="InvoSync Tally Prime Emulator Engine")


@app.post("/")
async def handle_tally_xml_import(request: Request):
    xml_body = await request.body()
    xml_str = xml_body.decode("utf-8")

    print("\n" + "="*60)
    print("[MOCK TALLY 9000] RECEIVED INCOMING XML PACKET:")
    print("="*60)
    print(xml_str)
    print("="*60)

    if "List of Companies" in xml_str or "<TYPE>Company</TYPE>" in xml_str:
        print("[ACTION] Parsing Open Company List Request.")
        mock_tally_response = """<ENVELOPE>
            <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
            <BODY>
                <DATA>
                    <COLLECTION>
                        <COMPANY>
                            <NAME>InvoSync Test Logistics Pvt Ltd</NAME>
                        </COMPANY>
                    </COLLECTION>
                </DATA>
            </BODY>
        </ENVELOPE>"""
    else:
        print("[ACTION] Parsing Transaction Voucher Import Request.")
        mock_tally_response = """<RESPONSE>
            <CREATED>1</CREATED>
            <ALTERED>0</ALTERED>
            <DELETED>0</DELETED>
            <ERRORS>0</ERRORS>
        </RESPONSE>"""

    return Response(content=mock_tally_response, media_type="application/xml")


if __name__ == "__main__":
    print("Initializing Local Tally Prime Port 9000 Simulator...")
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="warning")
