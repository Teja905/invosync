"""Ledger creation endpoints — single-ledger XML for inline 'Create Ledger' buttons."""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from api.deps import get_authenticated_user
from api.app_state import company_config as _company_config
from core.logging import get_logger
from xml_generator import safe_xml_string

router = APIRouter()
logger = get_logger(__name__)


class LedgerCreateRequest(BaseModel):
    name: str
    parent: str = "Primary"
    gstin: str = ""
    state_name: str = ""
    company_name: str = ""
    tax_type: str = ""
    gst_type: str = ""


@router.post("/api/v3/ledgers/create")
async def create_ledger(
    data: LedgerCreateRequest,
    current_user: dict = Depends(get_authenticated_user),
):
    """Generate a Tally XML envelope to create a single ledger in Tally."""
    if not data.name or not data.name.strip():
        raise HTTPException(400, "Ledger name is required")
    name = safe_xml_string(data.name.strip())
    parent = safe_xml_string(data.parent.strip()) if data.parent.strip() else "Primary"
    company = data.company_name or _company_config.company_name or "My Company"
    company_safe = safe_xml_string(company)
    gstin = safe_xml_string(data.gstin.strip().upper()) if data.gstin.strip() else ""
    state = safe_xml_string(data.state_name.strip()) if data.state_name.strip() else ""

    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append("<ENVELOPE>")
    parts.append("<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>")
    parts.append("<BODY><IMPORTDATA><REQUESTDESC>")
    parts.append("<REPORTNAME>All Masters</REPORTNAME>")
    parts.append(f"<STATICVARIABLES><SVCURRENTCOMPANY>{company_safe}</SVCURRENTCOMPANY></STATICVARIABLES>")
    parts.append("</REQUESTDESC><REQUESTDATA>")
    parts.append("<TALLYMESSAGE>")
    parts.append(f'<LEDGER NAME="{name}" ACTION="Create">')
    parts.append(f"<NAME>{name}</NAME>")
    parts.append(f"<PARENT>{parent}</PARENT>")
    if gstin:
        parts.append(f"<GSTIN>{gstin}</GSTIN>")
        parts.append("<GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE>")
        if state:
            parts.append(f"<STATENAME>{state}</STATENAME>")
    if data.tax_type:
        parts.append(f"<TAXTYPE>{safe_xml_string(data.tax_type)}</TAXTYPE>")
    if data.gst_type:
        parts.append(f"<GSTTYPE>{safe_xml_string(data.gst_type)}</GSTTYPE>")
    parts.append("<ISACTIVE>Yes</ISACTIVE>")
    parts.append("</LEDGER>")
    parts.append("</TALLYMESSAGE>")
    parts.append("</REQUESTDATA></IMPORTDATA></BODY>")
    parts.append("</ENVELOPE>")

    xml_str = "\n".join(parts)
    logger.info("Ledger creation XML generated for '%s' (parent=%s)", data.name, parent)
    return Response(
        content=xml_str,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="ledger_{name}.xml"',
            "X-Ledger-Name": name,
            "X-Ledger-Parent": parent,
        },
    )
