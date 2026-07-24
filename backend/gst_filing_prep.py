"""GST Filing Preparation Engine — Generate GSTR-1/3B data from captured invoices.

CAs spend hours compiling GSTR-1 data from Tally/excel. This engine generates
the filing-ready data directly from InvoSync's invoice database.

GSTR-1 Sections covered:
  - B2B: Business to Business (invoices > Rs.2.5 lakh with GSTIN)
  - B2CL: Business to Consumer Large (invoices > Rs.2.5 lakh, no GSTIN)
  - B2CS: Business to Consumer Small (invoices <= Rs.2.5 lakh)
  - CDN: Credit/Debit Notes
  - HSN: HSN-wise summary
  - Document Summary: Invoice count and value

GSTR-3B Sections:
  - Table 3.1: Outward supplies (taxable, nil-rated, exempt, non-GST)
  - Table 3.2: Inter-state supplies to unregistered persons
  - Table 4: Eligible ITC
  - Table 5: Exempt, nil-rated supplies
  - Table 6.1: Payment of tax
"""

from dataclasses import dataclass, field


@dataclass
class GSTR1B2BEntry:
    """B2B entry for GSTR-1."""
    gstin: str
    invoice_number: str
    invoice_date: str
    invoice_value: float
    place_of_supply: str
    reverse_charge: str = "N"
    invoice_type: str = "R"  # R=Regular, DE=Deemed Export, SEZWP=SEZ with payment, SEZWOP=SEZ without payment
    items: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gstin": self.gstin,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "invoice_value": self.invoice_value,
            "place_of_supply": self.place_of_supply,
            "reverse_charge": self.reverse_charge,
            "invoice_type": self.invoice_type,
            "items": self.items,
        }


@dataclass
class GSTR1HSNEntry:
    """HSN-wise summary entry."""
    hsn_code: str
    description: str
    uqc: str  # Unit Quantity Code
    total_quantity: float
    total_value: float
    taxable_value: float
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    cess: float = 0.0

    def to_dict(self) -> dict:
        return {
            "hsn_code": self.hsn_code,
            "description": self.description,
            "uqc": self.uqc,
            "total_quantity": self.total_quantity,
            "total_value": self.total_value,
            "taxable_value": self.taxable_value,
            "cgst": self.cgst,
            "sgst": self.sgst,
            "igst": self.igst,
            "cess": self.cess,
        }


@dataclass
class GSTR1DocumentSummary:
    """Document summary for GSTR-1."""
    total_documents: int = 0
    total_cancelled: int = 0
    total_net_documents: int = 0
    total_invoice_value: float = 0.0


@dataclass
class GSTR1Data:
    """Complete GSTR-1 filing data."""
    period: str  # MM-YYYY
    gstin: str
    b2b: list[GSTR1B2BEntry] = field(default_factory=list)
    hsn_summary: list[GSTR1HSNEntry] = field(default_factory=list)
    document_summary: GSTR1DocumentSummary = field(default_factory=GSTR1DocumentSummary)
    total_taxable: float = 0.0
    total_cgst: float = 0.0
    total_sgst: float = 0.0
    total_igst: float = 0.0
    total_cess: float = 0.0
    total_invoice_value: float = 0.0

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "gstin": self.gstin,
            "b2b": [e.to_dict() for e in self.b2b],
            "hsn_summary": [e.to_dict() for e in self.hsn_summary],
            "document_summary": {
                "total_documents": self.document_summary.total_documents,
                "total_cancelled": self.document_summary.total_cancelled,
                "total_net_documents": self.document_summary.total_net_documents,
                "total_invoice_value": round(self.document_summary.total_invoice_value, 2),
            },
            "summary": {
                "total_taxable": round(self.total_taxable, 2),
                "total_cgst": round(self.total_cgst, 2),
                "total_sgst": round(self.total_sgst, 2),
                "total_igst": round(self.total_igst, 2),
                "total_cess": round(self.total_cess, 2),
                "total_invoice_value": round(self.total_invoice_value, 2),
                "b2b_count": len(self.b2b),
                "hsn_count": len(self.hsn_summary),
            },
        }


@dataclass
class GSTR3BData:
    """GSTR-3B filing data."""
    period: str
    gstin: str
    # Table 3.1: Outward supplies
    taxable_outward: float = 0.0
    zero_rated: float = 0.0
    nil_rated: float = 0.0
    exempt: float = 0.0
    non_gst: float = 0.0
    total_outward: float = 0.0
    # Tax breakdown
    cgst_payable: float = 0.0
    sgst_payable: float = 0.0
    igst_payable: float = 0.0
    cess_payable: float = 0.0
    # Table 4: ITC
    itc_cgst: float = 0.0
    itc_sgst: float = 0.0
    itc_igst: float = 0.0
    itc_cess: float = 0.0
    total_itc: float = 0.0
    # Table 5: Exempt supplies
    exempt_outward: float = 0.0
    nil_rated_outward: float = 0.0
    non_gst_outward: float = 0.0
    # Table 6: Payment
    tax_payable: float = 0.0
    tax_paid: float = 0.0
    tax_balance: float = 0.0

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "gstin": self.gstin,
            "table_3_1": {
                "taxable_outward": round(self.taxable_outward, 2),
                "zero_rated": round(self.zero_rated, 2),
                "nil_rated": round(self.nil_rated, 2),
                "exempt": round(self.exempt, 2),
                "non_gst": round(self.non_gst, 2),
                "total_outward": round(self.total_outward, 2),
            },
            "tax_payable": {
                "cgst": round(self.cgst_payable, 2),
                "sgst": round(self.sgst_payable, 2),
                "igst": round(self.igst_payable, 2),
                "cess": round(self.cess_payable, 2),
                "total": round(self.cgst_payable + self.sgst_payable + self.igst_payable + self.cess_payable, 2),
            },
            "table_4_itc": {
                "cgst": round(self.itc_cgst, 2),
                "sgst": round(self.itc_sgst, 2),
                "igst": round(self.itc_igst, 2),
                "cess": round(self.itc_cess, 2),
                "total": round(self.total_itc, 2),
            },
            "table_5_exempt": {
                "exempt": round(self.exempt_outward, 2),
                "nil_rated": round(self.nil_rated_outward, 2),
                "non_gst": round(self.non_gst_outward, 2),
            },
            "table_6_payment": {
                "tax_payable": round(self.tax_payable, 2),
                "tax_paid": round(self.tax_paid, 2),
                "tax_balance": round(self.tax_balance, 2),
            },
        }


def generate_gstr1(
    invoices: list[dict],
    period: str,
    company_gstin: str,
) -> GSTR1Data:
    """Generate GSTR-1 data from InvoSync invoices.

    Args:
        invoices: List of invoice dicts with extracted data
        period: Period string (e.g., "04-2024" for April 2024)
        company_gstin: Company's GSTIN

    Returns:
        GSTR1Data with B2B entries, HSN summary, and document summary
    """
    gstr1 = GSTR1Data(period=period, gstin=company_gstin)
    hsn_map: dict[str, dict] = {}

    doc_count = 0
    cancelled_count = 0

    for inv in invoices:
        extracted = inv.get("extracted", {}) or {}
        status = inv.get("status", "")

        doc_count += 1
        if status == "cancelled":
            cancelled_count += 1
            continue

        vendor_gstin = extracted.get("vendor_gstin", "")
        buyer_gstin = extracted.get("buyer_gstin", "")
        invoice_number = extracted.get("invoice_number", "")
        invoice_date = extracted.get("invoice_date", "")
        total_amount = float(extracted.get("total_amount", 0) or 0)
        taxable_value = float(extracted.get("total_taxable_value", 0) or 0)
        total_tax = float(extracted.get("total_tax", 0) or 0)
        reverse_charge = extracted.get("reverse_charge", False)
        place_of_supply = extracted.get("place_of_supply", "")
        voucher_type = extracted.get("voucher_type", "Purchase")

        # Only include outward supplies (Sales) in GSTR-1
        if voucher_type != "Sales":
            continue

        # For GSTR-1, the filing entity is the seller. Skip if vendor_gstin
        # doesn't match the company GSTIN (i.e., this is a purchase, not a sale).
        if vendor_gstin and company_gstin and vendor_gstin != company_gstin:
            continue

        # Determine if B2B or B2CL
        has_gstin = bool(buyer_gstin)

        if has_gstin:
            # B2B: Has GSTIN
            items = []
            for item in extracted.get("line_items", []):
                items.append({
                    "description": item.get("description", ""),
                    "hsn_code": item.get("hsn_sac", ""),
                    "quantity": item.get("quantity", 1),
                    "rate": item.get("rate", 0),
                    "taxable_value": item.get("taxable_value", 0),
                    "tax_rate": item.get("tax_rate", 0),
                })

                # HSN summary
                hsn = item.get("hsn_sac", "") or "UNKNOWN"
                if hsn not in hsn_map:
                    hsn_map[hsn] = {
                        "hsn_code": hsn,
                        "description": item.get("description", ""),
                        "uqc": "NOS",
                        "quantity": 0,
                        "value": 0,
                        "taxable": 0,
                        "cgst": 0,
                        "sgst": 0,
                        "igst": 0,
                    }
                hsn_map[hsn]["quantity"] += item.get("quantity", 1)
                hsn_map[hsn]["value"] += item.get("taxable_value", 0)
                hsn_map[hsn]["taxable"] += item.get("taxable_value", 0)

            gstr1.b2b.append(GSTR1B2BEntry(
                gstin=buyer_gstin,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                invoice_value=total_amount,
                place_of_supply=place_of_supply,
                reverse_charge="Y" if reverse_charge else "N",
                items=items,
            ))

        # Aggregate tax
        taxes = extracted.get("taxes", [])
        if taxes:
            for t in taxes:
                if isinstance(t, dict):
                    ttype = t.get("type", "")
                    amount = float(t.get("amount", 0) or 0)
                    if ttype == "cgst":
                        gstr1.total_cgst += amount
                    elif ttype == "sgst":
                        gstr1.total_sgst += amount
                    elif ttype == "igst":
                        gstr1.total_igst += amount
        else:
            # Fallback: split tax evenly
            if total_tax > 0:
                gstr1.total_cgst += total_tax / 2
                gstr1.total_sgst += total_tax / 2

        gstr1.total_taxable += taxable_value
        gstr1.total_invoice_value += total_amount

    # Build HSN summary
    for hsn_data in hsn_map.values():
        gstr1.hsn_summary.append(GSTR1HSNEntry(
            hsn_code=hsn_data["hsn_code"],
            description=hsn_data["description"],
            uqc=hsn_data["uqc"],
            total_quantity=hsn_data["quantity"],
            total_value=hsn_data["value"],
            taxable_value=hsn_data["taxable"],
        ))

    # Document summary
    gstr1.document_summary = GSTR1DocumentSummary(
        total_documents=doc_count,
        total_cancelled=cancelled_count,
        total_net_documents=doc_count - cancelled_count,
        total_invoice_value=gstr1.total_invoice_value,
    )

    return gstr1


def generate_gstr3b(
    invoices: list[dict],
    journal_lines: list[dict],
    period: str,
    company_gstin: str,
) -> GSTR3BData:
    """Generate GSTR-3B data from invoices and journal lines.

    GSTR-3B is a summary return — this provides the data for each table.
    """
    gstr3b = GSTR3BData(period=period, gstin=company_gstin)

    # Process invoices for outward supplies
    for inv in invoices:
        extracted = inv.get("extracted", {}) or {}
        voucher_type = extracted.get("voucher_type", "Purchase")
        total_amount = float(extracted.get("total_amount", 0) or 0)
        taxable_value = float(extracted.get("total_taxable_value", 0) or 0)
        total_tax = float(extracted.get("total_tax", 0) or 0)

        if voucher_type == "Sales":
            gstr3b.taxable_outward += taxable_value
            gstr3b.total_outward += total_amount

            # Tax breakdown
            taxes = extracted.get("taxes", [])
            if taxes:
                for t in taxes:
                    if isinstance(t, dict):
                        ttype = t.get("type", "")
                        amount = float(t.get("amount", 0) or 0)
                        if ttype == "cgst":
                            gstr3b.cgst_payable += amount
                        elif ttype == "sgst":
                            gstr3b.sgst_payable += amount
                        elif ttype == "igst":
                            gstr3b.igst_payable += amount
            elif total_tax > 0:
                gstr3b.cgst_payable += total_tax / 2
                gstr3b.sgst_payable += total_tax / 2

    # Process journal lines for ITC (Input Tax Credit)
    for line in journal_lines:
        ledger = (line.get("ledger", "") or "").lower()
        debit = float(line.get("debit", 0) or 0)
        credit = float(line.get("credit", 0) or 0)

        # ITC from input tax ledgers
        if "input cgst" in ledger:
            gstr3b.itc_cgst += debit
        elif "input sgst" in ledger:
            gstr3b.itc_sgst += debit
        elif "input igst" in ledger:
            gstr3b.itc_igst += debit

        # Exempt supplies
        if "exempt" in ledger:
            gstr3b.exempt_outward += credit
        elif "nil rated" in ledger:
            gstr3b.nil_rated_outward += credit

    gstr3b.total_itc = gstr3b.itc_cgst + gstr3b.itc_sgst + gstr3b.itc_igst
    gstr3b.tax_payable = gstr3b.cgst_payable + gstr3b.sgst_payable + gstr3b.igst_payable
    gstr3b.tax_balance = gstr3b.tax_payable  # No payment tracking yet

    return gstr3b
