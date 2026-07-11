from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class VoucherType(str, Enum):
    PURCHASE = "Purchase"
    SALES = "Sales"
    JOURNAL = "Journal"
    PAYMENT = "Payment"
    RECEIPT = "Receipt"
    CREDIT_NOTE = "Credit Note"
    DEBIT_NOTE = "Debit Note"


class GSTType(str, Enum):
    CGST_SGST = "CGST_SGST"
    IGST = "IGST"
    EXEMPT = "Exempt"
    NIL_RATED = "Nil Rated"
    REVERSE_CHARGE = "Reverse Charge"
    COMPOSITION = "Composition"


class DocumentClass(str, Enum):
    GST_INVOICE = "gst_invoice"
    RETAIL_BILL = "retail_bill"
    EXPENSE_RECEIPT = "expense_receipt"
    PURCHASE_INVOICE = "purchase_invoice"
    SERVICE_INVOICE = "service_invoice"
    UNKNOWN = "unknown"


class TaxEntry(BaseModel):
    name: str = ""
    rate: float = 0.0
    amount: float = 0.0
    type: str = ""
    is_input: bool = True


class LineItem(BaseModel):
    description: str = ""
    quantity: float = 1.0
    rate: float = 0.0
    taxable_value: float = 0.0
    tax_rate: float = 0.0
    hsn_sac: str = ""
    is_service: bool = False
    discount: float = 0.0
    unit: str = "Nos"

    @field_validator("description", "hsn_sac", "unit", mode="before")
    @classmethod
    def coerce_str(cls, v):
        if v is None:
            return ""
        return str(v) if not isinstance(v, str) else v


class StandardizedInvoice(BaseModel):
    invoice_number: str = ""
    invoice_date: str = ""
    vendor_name: str = ""
    vendor_gstin: str = ""
    vendor_address: str = ""
    buyer_name: str = ""
    buyer_gstin: Optional[str] = None
    buyer_address: str = ""
    voucher_type: VoucherType = VoucherType.PURCHASE
    document_class: DocumentClass = DocumentClass.UNKNOWN
    place_of_supply: str = ""
    line_items: list[LineItem] = Field(default_factory=list)
    taxes: list[TaxEntry] = Field(default_factory=list)
    total_taxable_value: float = 0.0
    total_tax: float = 0.0
    total_amount: float = 0.0
    round_off: float = 0.0
    tds_amount: float = 0.0
    tds_rate: float = 0.0
    freight: float = 0.0
    freight_gst: bool = False
    gst_type: GSTType = GSTType.CGST_SGST
    is_service: bool = False
    is_sez: bool = Field(default=False, description="True if the supplier/buyer is located in an SEZ zone")
    is_lut: bool = Field(default=False, description="True if the transaction is covered under a Letter of Undertaking (LUT)")
    is_rcm: bool = Field(default=False, description="True if the transaction falls under Reverse Charge Mechanism (RCM)")
    original_invoice_number: Optional[str] = Field(default=None, description="The original invoice number being amended (Required for Credit/Debit Notes)")
    original_invoice_date: Optional[str] = Field(default=None, description="The original invoice date in YYYY-MM-DD format being amended")
    reverse_charge: bool = False
    is_interstate: bool = False
    auto_create_stock_items: bool = False
    currency: str = "INR"
    exchange_rate: float = 1.0
    cess_amount: float = 0.0
    cess_rate: float = 0.0
    confidence: float = 0.0
    _provider: str = ""
    _model: str = ""

    @field_validator("invoice_number", "invoice_date", "vendor_name", "vendor_gstin", "vendor_address", "buyer_name", "buyer_address", "place_of_supply", mode="before")
    @classmethod
    def coerce_str(cls, v):
        if v is None:
            return ""
        return str(v) if not isinstance(v, str) else v


ALLOWED_GST_SLABS = {0, 0.1, 0.25, 3, 5, 12, 18, 28}


GST_STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman & Diu", "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (Old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar", "36": "Telangana",
    "37": "Andhra Pradesh (New)",
}


class BankTransactionSchema(BaseModel):
    transaction_date: str = ""
    description: str = ""
    cheque_ref_no: str = ""
    withdraw_amount: float = 0.0
    deposit_amount: float = 0.0
    balance: float = 0.0


class BankingRule(BaseModel):
    org_id: str = ""
    keyword: str = ""
    voucher_type: str = "Receipt"
    target_ledger: str = "Suspense"
    description: str = ""


class ProcessedBankTransaction(BankTransactionSchema):
    voucher_type: str = "Receipt"
    target_ledger: str = "Suspense"
    rule_applied: str = ""
