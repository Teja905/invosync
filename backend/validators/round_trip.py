"""RoundTripValidator — Generate XML → Parse back → Compare with original.

This catches generator bugs by ensuring every XML can be parsed back
into a structure that matches the original invoice data.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal

from schemas import StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry
from validators.base import ValidationResult, ValidationScore


@dataclass
class ParsedVoucher:
    """The minimum voucher structure extracted from XML."""
    voucher_type: str = ""
    voucher_number: str = ""
    date: str = ""
    is_invoice: bool = False
    entries: list[dict] = field(default_factory=list)
    inventory_items: list[dict] = field(default_factory=list)
    bill_allocations: list[dict] = field(default_factory=list)
    narration: str = ""
    party_ledger: str = ""
    original_invoice_no: str = ""
    original_invoice_date: str = ""


class RoundTripValidator:
    """Validates that generated XML can be parsed back and matches original data."""

    def parse_voucher(self, xml_str: str) -> Optional[ParsedVoucher]:
        """Extract voucher data from XML string."""
        # Find voucher section
        voucher_match = re.search(
            r"<VOUCHER\s+[^>]*VCHTYPE=\"([^\"]+)\"[^>]*>(.*?)</VOUCHER>",
            xml_str, re.DOTALL,
        )
        if not voucher_match:
            return None

        vch = ParsedVoucher(voucher_type=voucher_match.group(1))
        vbody = voucher_match.group(2)

        # Basic fields
        num = re.search(r"<VOUCHERNUMBER>([^<]+)</VOUCHERNUMBER>", vbody)
        if num:
            vch.voucher_number = num.group(1)

        date = re.search(r"<DATE>(\d{8})</DATE>", vbody)
        if date:
            d = date.group(1)
            vch.date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        is_inv = re.search(r"<ISINVOICE>([^<]+)</ISINVOICE>", vbody)
        if is_inv:
            vch.is_invoice = is_inv.group(1) == "Yes"

        party = re.search(r"<PARTYLEDGERNAME>([^<]+)</PARTYLEDGERNAME>", vbody)
        if party:
            vch.party_ledger = party.group(1)

        nar = re.search(r"<NARRATION>([^<]+)</NARRATION>", vbody)
        if nar:
            vch.narration = nar.group(1)

        oinv = re.search(r"<ORIGINALINVOICENO>([^<]+)</ORIGINALINVOICENO>", vbody)
        if oinv:
            vch.original_invoice_no = oinv.group(1)

        odate = re.search(r"<ORIGINALINVOICEDATE>(\d{8})</ORIGINALINVOICEDATE>", vbody)
        if odate:
            d = odate.group(1)
            vch.original_invoice_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        # Ledger entries
        for entry_match in re.finditer(
            r"<ALLLEDGERENTRIES\.LIST>(.*?)</ALLLEDGERENTRIES\.LIST>",
            vbody, re.DOTALL,
        ):
            entry_str = entry_match.group(1)
            entry = {}
            ledger = re.search(r"<LEDGERNAME>([^<]+)</LEDGERNAME>", entry_str)
            if ledger:
                entry["ledger"] = ledger.group(1)
            deemed = re.search(r"<ISDEEMEDPOSITIVE>([^<]+)</ISDEEMEDPOSITIVE>", entry_str)
            if deemed:
                entry["is_debit"] = deemed.group(1) == "Yes"
            amount = re.search(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", entry_str)
            if amount:
                entry["amount"] = float(amount.group(1))
            is_party = re.search(r"<ISPARTYLEDGER>([^<]+)</ISPARTYLEDGER>", entry_str)
            if is_party:
                entry["is_party"] = is_party.group(1) == "Yes"
            vch.entries.append(entry)

        # Inventory entries
        for inv_match in re.finditer(
            r"<ALLINVENTORYENTRIES\.LIST>(.*?)</ALLINVENTORYENTRIES\.LIST>",
            vbody, re.DOTALL,
        ):
            inv_str = inv_match.group(1)
            item = {}
            name = re.search(r"<STOCKITEMNAME>([^<]+)</STOCKITEMNAME>", inv_str)
            if name:
                item["name"] = name.group(1)
            hsn = re.search(r"<HSNCODE>([^<]+)</HSNCODE>", inv_str)
            if hsn:
                item["hsn"] = hsn.group(1)
            qty = re.search(r"<ACTUALQTY>(-?\d+)</ACTUALQTY>", inv_str)
            if qty:
                item["quantity"] = int(qty.group(1))
            rate = re.search(r"<RATE>([^<]+)</RATE>", inv_str)
            if rate:
                item["rate"] = float(rate.group(1))
            amt = re.search(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", inv_str)
            if amt:
                item["amount"] = float(amt.group(1))
            gst_rate = re.search(r"<GSTRATE>([^<]+)</GSTRATE>", inv_str)
            if gst_rate:
                item["gst_rate"] = float(gst_rate.group(1))
            vch.inventory_items.append(item)

        return vch

    def validate_round_trip(self, inv: StandardizedInvoice, xml_str: str) -> ValidationResult:
        """Validate that parsed XML matches the original invoice data."""
        result = ValidationResult()
        parsed = self.parse_voucher(xml_str)

        if not parsed:
            result.add_error("rt_parse", "Could not parse XML voucher", category="round_trip")
            return result

        # Voucher type
        expected_vt = inv.voucher_type.value
        if parsed.voucher_type != expected_vt:
            result.add_error("rt_voucher_type", f"VCHTYPE: expected '{expected_vt}', got '{parsed.voucher_type}'", category="round_trip")
        else:
            result.add_info(f"VCHTYPE match: {parsed.voucher_type}", category="round_trip")

        # Voucher number
        if parsed.voucher_number != inv.invoice_number:
            result.add_error("rt_voucher_number", f"VOUCHERNUMBER: expected '{inv.invoice_number}', got '{parsed.voucher_number}'", category="round_trip")

        # ISINVOICE
        is_goods = inv.voucher_type in (VoucherType.PURCHASE, VoucherType.SALES) and not inv.is_service and inv.line_items
        expected_invoice = "Yes" if is_goods else "No"
        got_invoice = "Yes" if parsed.is_invoice else "No"
        if got_invoice != expected_invoice:
            result.add_error("rt_isinvoice", f"ISINVOICE: expected '{expected_invoice}', got '{got_invoice}'", category="round_trip")

        # Debits ≈ taxable_value + tax + freight - tds + round_off
        debit_sum = sum(e.get("amount", 0) for e in parsed.entries if e.get("is_debit"))
        credit_sum = sum(abs(e.get("amount", 0)) for e in parsed.entries if not e.get("is_debit"))

        if abs(debit_sum - credit_sum) > 0.05:
            result.add_warning(f"Round-trip balance: Dr {debit_sum:.2f} ≠ Cr {credit_sum:.2f}", category="round_trip")

        # Count inventory items
        expected_items = len(inv.line_items) if not inv.is_service else 0
        got_items = len(parsed.inventory_items)
        if got_items != expected_items and expected_items > 0:
            result.add_warning(f"Inventory items: expected {expected_items}, got {got_items}", category="round_trip")

        result.add_info(f"Round-trip: {len(parsed.entries)} entries, {got_items} inventory items", category="round_trip")

        return result

    def validate(self, inv: StandardizedInvoice, xml_str: str) -> ValidationResult:
        """Full validation: structure + round-trip + balance."""
        result = ValidationResult()
        rt_result = self.validate_round_trip(inv, xml_str)
        for c in rt_result.checks:
            result.checks.append(c)
        result.passed = all(c.passed for c in result.checks if c.severity == "error")
        return result

    def score(self, inv: StandardizedInvoice, xml_str: str) -> ValidationScore:
        result = self.validate(inv, xml_str)
        return ValidationScore.from_validation(result)
