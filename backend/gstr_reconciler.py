"""GSTR Reconciliation Engine — Match invoices against GSTR-2A/2B/3B data.

CAs spend hours manually matching purchase invoices against GSTR-2A/2B data
downloaded from the GST portal. This engine automates that matching.

GSTR-2A: Auto-drafted ITC (supplier uploads their sales, appears in buyer's 2A)
GSTR-2B: Static ITC statement (locked after due date)
GSTR-3B: Summary return filed by taxpayer

Reconciliation flow:
1. Import GSTR-2A/2B data (JSON or CSV from GST portal)
2. Match against InvoSync invoice data
3. Classify: Matched / Mismatched / Missing in 2A / Missing in Books
4. Generate reconciliation report for CA review
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
import re


@dataclass
class GSTRInvoice:
    """Invoice from GSTR-2A/2B data (as downloaded from GST portal)."""
    gstin: str
    invoice_number: str
    invoice_date: str
    invoice_value: float
    taxable_value: float
    place_of_supply: str
    rate: float
    igst: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0
    is_reverse_charge: str = "N"
    filing_period: str = ""
    source: str = "2A"  # 2A or 2B


@dataclass
class ReconciliationItem:
    """Result of matching one invoice."""
    status: str  # matched, mismatched, missing_in_2a, missing_in_books
    book_invoice: Optional[dict] = None
    gstr_invoice: Optional[GSTRInvoice] = None
    differences: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ReconciliationReport:
    """Full reconciliation report."""
    total_books: int = 0
    total_2a: int = 0
    matched: list[ReconciliationItem] = field(default_factory=list)
    mismatched: list[ReconciliationItem] = field(default_factory=list)
    missing_in_2a: list[ReconciliationItem] = field(default_factory=list)
    missing_in_books: list[ReconciliationItem] = field(default_factory=list)
    total_itc_matched: float = 0.0
    total_itc_disallowed: float = 0.0
    reconciliation_date: str = ""

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_books": self.total_books,
                "total_2a": self.total_2a,
                "matched_count": len(self.matched),
                "mismatched_count": len(self.mismatched),
                "missing_in_2a_count": len(self.missing_in_2a),
                "missing_in_books_count": len(self.missing_in_books),
                "match_percentage": round(
                    len(self.matched) / max(self.total_books, 1) * 100, 1
                ),
                "total_itc_matched": round(self.total_itc_matched, 2),
                "total_itc_disallowed": round(self.total_itc_disallowed, 2),
            },
            "matched": [
                {
                    "book": m.book_invoice,
                    "gstr": {
                        "gstin": m.gstr_invoice.gstin,
                        "invoice_number": m.gstr_invoice.invoice_number,
                        "invoice_date": m.gstr_invoice.invoice_date,
                        "invoice_value": m.gstr_invoice.invoice_value,
                        "taxable_value": m.gstr_invoice.taxable_value,
                        "igst": m.gstr_invoice.igst,
                        "cgst": m.gstr_invoice.cgst,
                        "sgst": m.gstr_invoice.sgst,
                    } if m.gstr_invoice else None,
                    "confidence": m.confidence,
                }
                for m in self.matched
            ],
            "mismatched": [
                {
                    "book": m.book_invoice,
                    "gstr": {
                        "gstin": m.gstr_invoice.gstin,
                        "invoice_number": m.gstr_invoice.invoice_number,
                        "invoice_value": m.gstr_invoice.invoice_value,
                    } if m.gstr_invoice else None,
                    "differences": m.differences,
                }
                for m in self.mismatched
            ],
            "missing_in_2a": [
                {"book": m.book_invoice, "reason": "Invoice in books but not in GSTR-2A/2B"}
                for m in self.missing_in_2a
            ],
            "missing_in_books": [
                {
                    "gstr": {
                        "gstin": m.gstr_invoice.gstin,
                        "invoice_number": m.gstr_invoice.invoice_number,
                        "invoice_value": m.gstr_invoice.invoice_value,
                    } if m.gstr_invoice else None,
                    "reason": "Entry in GSTR-2A/2B but not found in books",
                }
                for m in self.missing_in_books
            ],
            "reconciliation_date": self.reconciliation_date,
        }


def _normalize_gstin(gstin: str) -> str:
    return (gstin or "").strip().upper()


def _normalize_invoice_number(num: str) -> str:
    """Normalize invoice number for fuzzy matching."""
    n = num.strip().upper()
    # Remove common prefixes/suffixes
    n = re.sub(r"^(INV|BILL|BILLING|INVOICE)[\s\-/]*", "", n)
    # Remove leading zeros
    n = n.lstrip("0") or "0"
    # Remove spaces and dashes
    n = n.replace(" ", "").replace("-", "").replace("/", "")
    return n


def _normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD format."""
    if not date_str:
        return ""
    date_str = date_str.strip()
    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    # DD/MM/YYYY
    if re.match(r"^\d{2}/\d{2}/\d{4}$", date_str):
        parts = date_str.split("/")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    # DD-MM-YYYY
    if re.match(r"^\d{2}-\d{2}-\d{4}$", date_str):
        parts = date_str.split("-")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    # DDMMYYYY
    if re.match(r"^\d{8}$", date_str):
        return f"{date_str[4:8]}-{date_str[2:4]}-{date_str[0:2]}"
    return date_str


def _match_amounts(book_amount: float, gstr_amount: float, tolerance: float = 1.0) -> bool:
    """Check if amounts match within tolerance (paise precision)."""
    return abs(Decimal(str(book_amount)) - Decimal(str(gstr_amount))) <= Decimal(str(tolerance))


def reconcile(
    book_invoices: list[dict],
    gstr_invoices: list[GSTRInvoice],
    tolerance: float = 1.0,
) -> ReconciliationReport:
    """Match book invoices against GSTR-2A/2B data.

    Matching strategy (GSTIN-first, multi-field):
      1. Group both sources by vendor GSTIN (the primary key)
      2. Within each GSTIN group, match by invoice number (exact → fuzzy)
      3. For matched invoice numbers, verify amounts (taxable, tax, total)
      4. Unmatched → classify as Missing in 2A or Missing in Books

    This prevents false matches where two different vendors have the same
    invoice amount but different GSTINs.

    Args:
        book_invoices: List of invoice dicts from InvoSync
        gstr_invoices: List of GSTRInvoice from parsed GSTR-2A/2B JSON
        tolerance: Amount matching tolerance in Rs. (default: Rs.1)

    Returns:
        ReconciliationReport with matched, mismatched, and missing items
    """
    report = ReconciliationReport(
        total_books=len(book_invoices),
        total_2a=len(gstr_invoices),
        reconciliation_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    # Step 1: Group GSTR invoices by GSTIN
    gstr_by_gstin: dict[str, list[GSTRInvoice]] = {}
    for g in gstr_invoices:
        gstin = _normalize_gstin(g.gstin)
        gstr_by_gstin.setdefault(gstin, []).append(g)

    # Track which GSTR invoices have been matched
    matched_gstr: set[int] = set()  # indices into gstr_invoices

    for book in book_invoices:
        book_gstin = _normalize_gstin(book.get("vendor_gstin", ""))
        book_inv_num = book.get("invoice_number", "")
        book_tax = float(book.get("total_tax", 0) or 0)

        # Step 2: Get GSTR invoices for this GSTIN only
        gstin_group = gstr_by_gstin.get(book_gstin, [])

        if not gstin_group:
            # No GSTR entries for this GSTIN at all
            report.missing_in_2a.append(ReconciliationItem(
                status="missing_in_2a",
                book_invoice=book,
            ))
            continue

        # Step 3: Match by invoice number within GSTIN group
        book_inv_norm = _normalize_invoice_number(book_inv_num)
        best_match = None
        best_diffs = []

        for idx, g in enumerate(gstr_invoices):
            if id(g) in {id(x) for x in []}:
                continue  # Skip already matched (by identity)
            g_idx = id(g)
            if g_idx in matched_gstr:
                continue

            gstin = _normalize_gstin(g.gstin)
            if gstin != book_inv_norm and gstin != book_gstin:
                continue

            g_inv_norm = _normalize_invoice_number(g.invoice_number)

            # Exact invoice number match
            if book_inv_norm and g_inv_norm and book_inv_norm == g_inv_norm:
                diffs = _verify_amounts(book, g, tolerance)
                if len(diffs) < len(best_diffs) or not best_match:
                    best_match = g
                    best_diffs = diffs
                continue

            # Fuzzy invoice number match (one contains the other, or edit distance <= 2)
            if book_inv_norm and g_inv_norm:
                if book_inv_norm in g_inv_norm or g_inv_norm in book_inv_norm:
                    diffs = _verify_amounts(book, g, tolerance)
                    if len(diffs) < len(best_diffs) or not best_match:
                        best_match = g
                        best_match_idx = idx
                        best_diffs = diffs
                    continue

        if best_match is not None:
            matched_gstr.add(id(best_match))
            if not best_diffs:
                report.matched.append(ReconciliationItem(
                    status="matched",
                    book_invoice=book,
                    gstr_invoice=best_match,
                    confidence=1.0,
                ))
                report.total_itc_matched += book_tax
            elif len(best_diffs) <= 1:
                report.matched.append(ReconciliationItem(
                    status="matched",
                    book_invoice=book,
                    gstr_invoice=best_match,
                    differences=best_diffs,
                    confidence=0.9,
                ))
                report.total_itc_matched += book_tax
            else:
                report.mismatched.append(ReconciliationItem(
                    status="mismatched",
                    book_invoice=book,
                    gstr_invoice=best_match,
                    differences=best_diffs,
                ))
                report.total_itc_disallowed += book_tax
        else:
            # No invoice number match within this GSTIN group
            report.missing_in_2a.append(ReconciliationItem(
                status="missing_in_2a",
                book_invoice=book,
            ))

    # Step 4: Find GSTR entries with no book match
    for g in gstr_invoices:
        if id(g) not in matched_gstr:
            report.missing_in_books.append(ReconciliationItem(
                status="missing_in_books",
                gstr_invoice=g,
            ))

    return report


def _verify_amounts(book: dict, g: GSTRInvoice, tolerance: float) -> list[str]:
    """Verify amounts between a book invoice and GSTR entry. Returns list of differences."""
    differences = []
    book_amount = float(book.get("total_amount", 0) or 0)
    book_taxable = float(book.get("total_taxable_value", 0) or 0)
    book_tax = float(book.get("total_tax", 0) or 0)
    book_date = _normalize_date(book.get("invoice_date", ""))

    if not _match_amounts(book_amount, g.invoice_value, tolerance):
        diff = abs(Decimal(str(book_amount)) - Decimal(str(g.invoice_value)))
        differences.append(f"Total: books={book_amount:.2f} vs 2A={g.invoice_value:.2f} (diff Rs.{diff:.2f})")

    if not _match_amounts(book_taxable, g.taxable_value, tolerance):
        differences.append(f"Taxable: books={book_taxable:.2f} vs 2A={g.taxable_value:.2f}")

    gstr_tax = g.igst + g.cgst + g.sgst
    if not _match_amounts(book_tax, gstr_tax, tolerance):
        differences.append(f"Tax: books={book_tax:.2f} vs 2A={gstr_tax:.2f}")

    gstr_date = _normalize_date(g.invoice_date)
    if book_date and gstr_date and book_date != gstr_date:
        differences.append(f"Date: books={book_date} vs 2A={gstr_date}")

    return differences


def parse_gstr2a_json(data: dict) -> list[GSTRInvoice]:
    """Parse GSTR-2A JSON downloaded from GST portal.

    The GST portal exports GSTR-2A as:
    {
      "b2b": [
        {
          "ctin": "27AABCU1234F1ZP",
          "trdnm": "Vendor Name",
          "inv": [
            {
              "inum": "INV-001",
              "idt": "01-04-2024",
              "val": 118000,
              "pos": "27-Maharashtra",
              "typ": "R",
              "itms": [
                {
                  "num": 1,
                  "itm_det": {
                    "rt": 18,
                    "txval": 100000,
                    "iamt": 0,
                    "camt": 9000,
                    "samt": 9000,
                    "csamt": 0
                  }
                }
              ]
            }
          ]
        }
      ]
    }
    """
    invoices = []

    # B2B section (business to business)
    b2b = data.get("b2b", [])
    for supplier in b2b:
        gstin = supplier.get("ctin", "")
        for inv in supplier.get("inv", []):
            inv_num = inv.get("inum", "")
            inv_date = inv.get("idt", "")
            inv_val = float(inv.get("val", 0) or 0)
            pos = inv.get("pos", "")
            is_rcm = inv.get("typ", "") == "R"

            total_taxable = 0.0
            total_igst = 0.0
            total_cgst = 0.0
            total_sgst = 0.0
            total_cess = 0.0
            rate = 0.0

            for item in inv.get("itms", []):
                det = item.get("itm_det", {})
                rt = float(det.get("rt", 0) or 0)
                txval = float(det.get("txval", 0) or 0)
                iamt = float(det.get("iamt", 0) or 0)
                camt = float(det.get("camt", 0) or 0)
                samt = float(det.get("samt", 0) or 0)
                csamt = float(det.get("csamt", 0) or 0)

                total_taxable += txval
                total_igst += iamt
                total_cgst += camt
                total_sgst += samt
                total_cess += csamt
                if rt > 0:
                    rate = rt

            invoices.append(GSTRInvoice(
                gstin=gstin,
                invoice_number=inv_num,
                invoice_date=inv_date,
                invoice_value=inv_val,
                taxable_value=total_taxable,
                place_of_supply=pos,
                rate=rate,
                igst=total_igst,
                cgst=total_cgst,
                sgst=total_sgst,
                cess=total_cess,
                is_reverse_charge="Y" if is_rcm else "N",
                source="2A",
            ))

    # B2BA section (amended invoices)
    b2ba = data.get("b2ba", [])
    for supplier in b2ba:
        gstin = supplier.get("ctin", "")
        for inv in supplier.get("inv", []):
            inv_num = inv.get("inum", "")
            inv_date = inv.get("idt", "")
            inv_val = float(inv.get("val", 0) or 0)

            total_taxable = 0.0
            total_igst = 0.0
            total_cgst = 0.0
            total_sgst = 0.0
            rate = 0.0

            for item in inv.get("itms", []):
                det = item.get("itm_det", {})
                rt = float(det.get("rt", 0) or 0)
                txval = float(det.get("txval", 0) or 0)
                iamt = float(det.get("iamt", 0) or 0)
                camt = float(det.get("camt", 0) or 0)
                samt = float(det.get("samt", 0) or 0)

                total_taxable += txval
                total_igst += iamt
                total_cgst += camt
                total_sgst += samt
                if rt > 0:
                    rate = rt

            invoices.append(GSTRInvoice(
                gstin=gstin,
                invoice_number=inv_num,
                invoice_date=inv_date,
                invoice_value=inv_val,
                taxable_value=total_taxable,
                place_of_supply="",
                rate=rate,
                igst=total_igst,
                cgst=total_cgst,
                sgst=total_sgst,
                source="2A",
            ))

    return invoices
