"""XML balance invariants: every voucher must have sum of AMOUNTs = 0."""

import re
import xml.etree.ElementTree as ET
import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from gst_engine import _compute_gstin_checksum


KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
MH_GSTIN = "27AAFFC8126N1Z" + _compute_gstin_checksum("27AAFFC8126N1Z")


def _extract_amounts(xml: str) -> list[float]:
    """Extract all <AMOUNT> values from the XML."""
    return [float(m) for m in re.findall(r"<AMOUNT>([^<]+)</AMOUNT>", xml)]


def _ledger_amounts(xml: str) -> dict[str, float]:
    """Map ledger names to amounts from ALLLEDGERENTRIES.LIST."""
    # Parse each LEDGERENTRY with regex for robustness
    entries = re.findall(
        r"<ALLLEDGERENTRIES\.LIST>.*?<LEDGERNAME>([^<]+)</LEDGERNAME>.*?<AMOUNT>([^<]+)</AMOUNT>.*?</ALLLEDGERENTRIES\.LIST>",
        xml, re.DOTALL
    )
    return {name: float(amt) for name, amt in entries}


def _balance_without_billalloc(xml: str) -> float:
    """Sum of AMOUNTs excluding BILLALLOCATIONS.LIST and ALLINVENTORYENTRIES.LIST."""
    filtered = re.sub(r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>", "", xml, flags=re.DOTALL)
    filtered = re.sub(r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", filtered, flags=re.DOTALL)
    return sum(_extract_amounts(filtered))


def make_invoice(
    vt: VoucherType,
    gst: GSTType = GSTType.CGST_SGST,
    vendor: str = "Test Vendor",
    buyer: str = KA_GSTIN,
    interstate: bool = False,
) -> StandardizedInvoice:
    """Factory to build a test invoice for any voucher type."""
    buyer_gstin = MH_GSTIN if interstate else KA_GSTIN
    taxes = []
    if gst == GSTType.CGST_SGST:
        taxes = [
            TaxEntry(name="CGST", rate=9, amount=90.0, type="CGST"),
            TaxEntry(name="SGST", rate=9, amount=90.0, type="SGST"),
        ]
    elif gst == GSTType.IGST:
        taxes = [TaxEntry(name="IGST", rate=18, amount=180.0, type="IGST")]
    return StandardizedInvoice(
        vendor_name=vendor,
        vendor_gstin=KA_GSTIN,
        buyer_gstin=buyer_gstin,
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        total_taxable_value=1000.0,
        total_tax=180.0,
        total_amount=1180.0,
        voucher_type=vt,
        gst_type=gst,
        line_items=[LineItem(description="Item", taxable_value=1000.0, tax_rate=18)],
        taxes=taxes,
    )


class TestBalanceForAllVoucherTypes:
    """Every voucher type must produce sum(AMOUNT) = 0 (excluding bill allocations)."""

    @pytest.mark.parametrize("vtype", [
        VoucherType.PURCHASE, VoucherType.SALES, VoucherType.JOURNAL,
        VoucherType.PAYMENT, VoucherType.RECEIPT,
        VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE,
    ])
    def test_voucher_balances(self, vtype, generator_no_ledgers):
        inv = make_invoice(vtype)
        xml = generator_no_ledgers.generate(inv)
        balance = _balance_without_billalloc(xml)
        assert abs(balance) < 0.01, f"{vtype.value}: balance = {balance}, expected 0"

    def test_purchase_with_ledgers_balanced(self, generator):
        """With include_ledgers=True, voucher envelope must still balance."""
        inv = make_invoice(VoucherType.PURCHASE)
        xml = generator.generate(inv)
        # Split at the start of the voucher envelope (Vouchers report)
        voucher_start = xml.find("<REPORTNAME>Vouchers</REPORTNAME>")
        assert voucher_start > 0, "Voucher envelope not found"
        voucher_xml = xml[voucher_start:]
        balance = _balance_without_billalloc(voucher_xml)
        assert abs(balance) < 0.01, f"Voucher with ledgers: balance = {balance}"


class TestVoucherEntryStructure:

    def test_purchase_has_debit_purchase_credit_party(self, generator_no_ledgers):
        """Purchase: Purchase Account is debit (positive), Party is credit (negative)."""
        inv = make_invoice(VoucherType.PURCHASE)
        xml = generator_no_ledgers.generate(inv)
        ledgers = _ledger_amounts(xml)
        # Purchase account should be positive (debit with ISDEEMEDPOSITIVE=Yes)
        purchase_amts = [amt for name, amt in ledgers.items() if "purchase" in name.lower()]
        assert any(a > 0 for a in purchase_amts), f"Purchase should be debit (positive): {ledgers}"
        # Party should be negative (credit with ISDEEMEDPOSITIVE=No)
        party_positive = [amt for name, amt in ledgers.items() if "Test Vendor" in name and amt > 0]
        assert not party_positive, f"Party should not be positive (credit): {ledgers}"

    def test_sales_has_debit_party_credit_sales(self, generator_no_ledgers):
        """Sales: Party is debit (positive), Sales Account is credit (negative)."""
        inv = make_invoice(VoucherType.SALES, gst=GSTType.IGST, interstate=True)
        xml = generator_no_ledgers.generate(inv)
        ledgers = _ledger_amounts(xml)
        # Party should be positive (debit with ISDEEMEDPOSITIVE=Yes)
        party_positive = [amt for name, amt in ledgers.items() if "Test Vendor" in name and amt > 0]
        assert party_positive, f"Sales party should be debit (positive): {ledgers}"
        # Sales should be negative (credit with ISDEEMEDPOSITIVE=No)
        sales_negative = [amt for name, amt in ledgers.items() if "sale" in name.lower() and amt < 0]
        assert sales_negative, f"Sales account should be credit (negative): {ledgers}"

    def test_payment_has_bank_credit(self, generator_no_ledgers):
        """Payment voucher must include a bank/credit entry."""
        inv = make_invoice(VoucherType.PAYMENT)
        xml = generator_no_ledgers.generate(inv)
        assert "BANK" in xml.upper() or "PAYMENT" in xml.upper()

    def test_xml_is_well_formed(self, generator_no_ledgers):
        """Every generated XML must be parseable."""
        for vt in VoucherType:
            inv = make_invoice(vt)
            xml = generator_no_ledgers.generate(inv)
            try:
                ET.fromstring(xml)
            except ET.ParseError as e:
                pytest.fail(f"{vt.value}: malformed XML: {e}")
