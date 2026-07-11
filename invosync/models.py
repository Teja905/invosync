from pydantic import BaseModel, Field
from typing import Optional


class LineItem(BaseModel):
    description: str = ""
    quantity: float = 1.0
    rate: float = 0.0
    taxable_amount: float = 0.0
    tax_rate: float = 0.0
    hsn_sac: str = ""
    unit: str = "Nos"


class InvoiceRequest(BaseModel):
    company_gstin: str
    party_gstin: str
    party_name: str
    invoice_number: str
    invoice_date: str
    taxable_total: float
    tax_total: float
    grand_total: float
    tax_rate: float
    line_items: list[LineItem] = Field(default_factory=list)


class ValidationError(BaseModel):
    field: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GSTClassification(BaseModel):
    gst_type: str
    is_interstate: bool
    company_state: str
    party_state: str
    entries: list[dict]


class XmlResponse(BaseModel):
    success: bool
    xml: str = ""
    errors: list[str] = Field(default_factory=list)
    gst_classification: Optional[GSTClassification] = None
