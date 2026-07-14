"""GSTR compliance preview — pure calculation, no Tally dependency.

Generates:
- GSTR-1 section-wise breakdown (B2B / B2C / Export / RCM)
- GSTR-3B monthly summary (outward supplies, output tax, input tax)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from schemas import StandardizedInvoice, VoucherType, GSTType


@dataclass
class GSTR1Entry:
    invoice_number: str
    invoice_date: str
    buyer_gstin: str
    buyer_name: str
    place_of_supply: str
    taxable_value: float
    tax_amount: float
    gst_type: str
    section: str  # "B2B" | "B2C" | "Export" | "RCM"
    is_rcm: bool = False
    is_sez: bool = False
    is_lut: bool = False

    def to_dict(self) -> dict:
        return {
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "buyer_gstin": self.buyer_gstin,
            "buyer_name": self.buyer_name,
            "place_of_supply": self.place_of_supply,
            "taxable_value": self.taxable_value,
            "tax_amount": self.tax_amount,
            "gst_type": self.gst_type,
            "section": self.section,
            "is_rcm": self.is_rcm,
            "is_sez": self.is_sez,
            "is_lut": self.is_lut,
        }


@dataclass
class GSTR3BSummary:
    total_taxable_value: float = 0.0
    total_tax: float = 0.0
    output_cgst: float = 0.0
    output_sgst: float = 0.0
    output_igst: float = 0.0
    input_cgst: float = 0.0
    input_sgst: float = 0.0
    input_igst: float = 0.0
    cess: float = 0.0
    rcm_liable: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_taxable_value": round(self.total_taxable_value, 2),
            "total_tax": round(self.total_tax, 2),
            "output_cgst": round(self.output_cgst, 2),
            "output_sgst": round(self.output_sgst, 2),
            "output_igst": round(self.output_igst, 2),
            "input_cgst": round(self.input_cgst, 2),
            "input_sgst": round(self.input_sgst, 2),
            "input_igst": round(self.input_igst, 2),
            "cess": round(self.cess, 2),
            "rcm_liable": round(self.rcm_liable, 2),
        }


@dataclass
class GSTRPreview:
    gstr1_entries: list[GSTR1Entry] = field(default_factory=list)
    gstr3b: GSTR3BSummary = field(default_factory=GSTR3BSummary)
    invoice_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gstr1": {
                "entries": [e.to_dict() for e in self.gstr1_entries],
                "summary": {
                    "b2b_count": sum(1 for e in self.gstr1_entries if e.section == "B2B"),
                    "b2c_count": sum(1 for e in self.gstr1_entries if e.section == "B2C"),
                    "export_count": sum(1 for e in self.gstr1_entries if e.section == "Export"),
                    "rcm_count": sum(1 for e in self.gstr1_entries if e.section == "RCM"),
                    "total_taxable": round(sum(e.taxable_value for e in self.gstr1_entries), 2),
                    "total_tax": round(sum(e.tax_amount for e in self.gstr1_entries), 2),
                },
            },
            "gstr3b": self.gstr3b.to_dict(),
            "invoice_count": self.invoice_count,
            "warnings": self.warnings,
        }


class GSTRPreviewGenerator:
    """Generate GSTR-1 and GSTR-3B previews from one or more invoices."""

    def __init__(self, invoice: StandardizedInvoice):
        self.invoice = invoice

    def _determine_section(self, inv: StandardizedInvoice) -> str:
        if inv.is_rcm or inv.voucher_type == VoucherType.CREDIT_NOTE or inv.voucher_type == VoucherType.DEBIT_NOTE:
            return "RCM"
        if inv.gst_type == GSTType.EXEMPT or inv.gst_type == GSTType.NIL_RATED or inv.gst_type == GSTType.COMPOSITION:
            return "B2C"
        if inv.is_sez or (inv.buyer_gstin and inv.buyer_gstin.startswith("96")):
            return "Export"
        if inv.buyer_gstin and len(inv.buyer_gstin) == 15:
            return "B2B"
        return "B2C"

    def _split_tax_by_type(self, inv: StandardizedInvoice) -> tuple[float, float, float]:
        cgst = sum(t.amount for t in inv.taxes if t.type.lower() == "cgst")
        sgst = sum(t.amount for t in inv.taxes if t.type.lower() == "sgst")
        igst = sum(t.amount for t in inv.taxes if t.type.lower() == "igst")
        return cgst, sgst, igst

    def generate(self) -> GSTRPreview:
        inv = self.invoice
        preview = GSTRPreview(invoice_count=1)

        section = self._determine_section(inv)
        cgst, sgst, igst = self._split_tax_by_type(inv)

        gstr1_entry = GSTR1Entry(
            invoice_number=inv.invoice_number,
            invoice_date=inv.invoice_date,
            buyer_gstin=inv.buyer_gstin or "",
            buyer_name=inv.buyer_name or inv.vendor_name or "",
            place_of_supply=inv.place_of_supply,
            taxable_value=inv.total_taxable_value,
            tax_amount=inv.total_tax,
            gst_type=inv.gst_type.value if hasattr(inv.gst_type, "value") else str(inv.gst_type),
            section=section,
            is_rcm=inv.is_rcm,
            is_sez=inv.is_sez,
            is_lut=inv.is_lut,
        )
        preview.gstr1_entries.append(gstr1_entry)

        g3 = preview.gstr3b
        g3.total_taxable_value += inv.total_taxable_value
        g3.total_tax += inv.total_tax
        g3.output_cgst += cgst
        g3.output_sgst += sgst
        g3.output_igst += igst
        g3.cess += inv.cess_amount or 0.0

        if inv.is_rcm:
            g3.rcm_liable += inv.total_tax

        if inv.voucher_type in (VoucherType.PURCHASE, VoucherType.CREDIT_NOTE):
            g3.input_cgst += cgst
            g3.input_sgst += sgst
            g3.input_igst += igst

        if not inv.buyer_gstin and inv.gst_type not in (GSTType.EXEMPT, GSTType.NIL_RATED, GSTType.COMPOSITION):
            preview.warnings.append(
                "B2C invoice: no buyer GSTIN. Will not appear in B2B section of GSTR-1."
            )

        if inv.is_interstate and inv.gst_type == GSTType.CGST_SGST:
            preview.warnings.append(
                "Interstate invoice marked as CGST/SGST. Expected IGST. Please verify."
            )

        if inv.place_of_supply == "96":
            preview.warnings.append(
                "Place of supply is 96 (Foreign). Ensure export documentation is attached."
            )

        return preview


def generate_gstr_preview(invoice: StandardizedInvoice) -> dict:
    """Convenience function for API usage."""
    generator = GSTRPreviewGenerator(invoice)
    return generator.generate().to_dict()
