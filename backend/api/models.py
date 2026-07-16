"""Shared Pydantic models for invoice routes."""

from typing import Optional
from pydantic import BaseModel


class LineItemModel(BaseModel):
    description: str
    quantity: float
    rate: float
    taxable_value: float
    tax_rate: float
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    ledger_name: str = ""


class InvoiceDataLegacy(BaseModel):
    gstin: str = ""
    invoice_number: str = ""
    date: str = ""
    total_amount: float = 0
    vendor_name: str = ""
    vendor_address: Optional[str] = None
    buyer_gstin: str = ""
    buyer_name: str = ""
    voucher_type: str = ""
    line_items: list[LineItemModel] = []
    confidence: Optional[float] = None
    client_id: Optional[int] = None


class InvoiceUpdatePayload(BaseModel):
    gstin: str = ""
    invoice_number: str = ""
    date: str = ""
    total_amount: float = 0
    vendor_name: str = ""
    vendor_address: str = ""
    buyer_gstin: str = ""
    buyer_name: str = ""
    voucher_type: str = ""
    line_items: list[LineItemModel] = []
    freight: float = 0
    round_off: float = 0
    tds_amount: float = 0
    item_ledgers: list[str] = []
