"""GSTR preview endpoint."""

from bson.objectid import ObjectId
from fastapi import APIRouter, HTTPException, Depends

import database as db
from api.deps import get_authenticated_user
from gstr_preview import generate_gstr_preview
from schemas import StandardizedInvoice

router = APIRouter()


@router.get("/api/v3/invoices/{invoice_id}/gstr-preview")
async def get_gstr_preview(invoice_id: str, current_user: dict = Depends(get_authenticated_user)):
    """Generate GSTR-1 and GSTR-3B preview for an invoice."""
    invoice = await db.invoices.find_one({"_id": ObjectId(invoice_id)})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv = StandardizedInvoice(**invoice.get("data", {}))
    preview = generate_gstr_preview(inv)
    return preview
