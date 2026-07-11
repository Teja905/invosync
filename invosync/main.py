"""InvoSync — Production-ready TallyPrime XML Generator for Purchase & Sales Vouchers.

Endpoints:
  POST /generate-purchase-xml  — Generate Tally XML for purchase voucher
  POST /generate-sales-xml     — Generate Tally XML for sales voucher
  GET  /health                 — Health check
"""

import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import InvoiceRequest, XmlResponse, GSTClassification
from xml_generator import generate_purchase_xml, generate_sales_xml
from gst import classify_gst, compute_tax, compute_tax_from_items, GST_STATE_CODES
from validation import validate_invoice

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("invosync")

app = FastAPI(
    title="InvoSync — TallyPrime XML Generator",
    description="Generates 100% TallyPrime-compatible XML for Purchase and Sales vouchers with full GST support.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COMPANY_NAME = os.getenv("COMPANY_NAME", "My Company")
COMPANY_STATE = os.getenv("COMPANY_STATE_CODE", "27")


def _build_response(xml: str, data: InvoiceRequest) -> XmlResponse:
    gst_info = classify_gst(data.company_gstin, data.party_gstin)
    if data.line_items:
        tax_entries = compute_tax_from_items(
            [{"taxable_amount": li.taxable_amount, "tax_rate": li.tax_rate} for li in data.line_items],
            gst_info["gst_type"]
        )
    else:
        tax_entries = compute_tax(data.taxable_total, data.tax_rate, gst_info["gst_type"])
    gst_class = GSTClassification(
        gst_type=gst_info["gst_type"],
        is_interstate=gst_info["is_interstate"],
        company_state=GST_STATE_CODES.get(gst_info["company_state"], gst_info["company_state"]),
        party_state=GST_STATE_CODES.get(gst_info["party_state"], gst_info["party_state"]),
        entries=tax_entries,
    )
    return XmlResponse(success=True, xml=xml, gst_classification=gst_class)


@app.get("/health")
def health():
    return {"status": "ok", "service": "invosync"}


@app.post("/generate-purchase-xml", response_model=XmlResponse)
def purchase_xml_endpoint(data: InvoiceRequest):
    validation = validate_invoice(data)
    if not validation.valid:
        error_messages = [f"{e.field}: {e.message}" for e in validation.errors]
        for w in validation.warnings:
            logger.warning(f"Purchase XML warning: {w}")
        raise HTTPException(status_code=400, detail={
            "success": False,
            "errors": error_messages,
            "warnings": validation.warnings,
        })

    for w in validation.warnings:
        logger.warning(f"Purchase XML warning: {w}")

    try:
        xml = generate_purchase_xml(data, COMPANY_NAME, COMPANY_STATE)
    except Exception as e:
        logger.exception("Failed to generate purchase XML")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "errors": [f"XML generation failed: {str(e)}"],
        })

    return _build_response(xml, data)


@app.post("/generate-sales-xml", response_model=XmlResponse)
def sales_xml_endpoint(data: InvoiceRequest):
    validation = validate_invoice(data)
    if not validation.valid:
        error_messages = [f"{e.field}: {e.message}" for e in validation.errors]
        for w in validation.warnings:
            logger.warning(f"Sales XML warning: {w}")
        raise HTTPException(status_code=400, detail={
            "success": False,
            "errors": error_messages,
            "warnings": validation.warnings,
        })

    for w in validation.warnings:
        logger.warning(f"Sales XML warning: {w}")

    try:
        xml = generate_sales_xml(data, COMPANY_NAME, COMPANY_STATE)
    except Exception as e:
        logger.exception("Failed to generate sales XML")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "errors": [f"XML generation failed: {str(e)}"],
        })

    return _build_response(xml, data)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
