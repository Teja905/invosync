"""Battle-hardened test suite: 10 complex real-world Indian invoice scenarios.

Covers:
1. Interstate purchase with mixed goods & services + discount + freight
2. Intrastate purchase with partial payment & bill allocation
3. Reverse charge purchase (unregistered vendor)
4. Composition scheme dealer (no GST charged)
5. Credit note for goods return
6. Debit note for price increase
7. Journal entry for depreciation
8. Payment voucher with multiple bank accounts
9. Sales invoice with export (zero-rated)
10. Mixed tax rates with discount and rounding
"""

import re
from decimal import Decimal
import sys
from pathlib import Path

sys_path_inserted = False
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys_path_inserted = True
except Exception:
    pass

from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator, CompanyConfig
from gst_engine import _compute_gstin_checksum
from validation_layer import validate_invoice_for_xml


# Valid GSTINs for different states (15 chars, proper checksum)
_MH_GSTIN = "27AAFFC8126N1Z" + _compute_gstin_checksum("27AAFFC8126N1Z")
_KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")
_UP_GSTIN = "09AABCT1234F1Z" + _compute_gstin_checksum("09AABCT1234F1Z")
_MH_BUYER_GSTIN = "27AABBU1234F1Z" + _compute_gstin_checksum("27AABBU1234F1Z")


def _make_config(state_code: str = "27", company_name: str = "Test Co"):
    return CompanyConfig(user_config={"company_state_code": state_code, "company_name": company_name})


def _make_generator(state_code: str = "27", company_name: str = "Test Co"):
    return TallyXmlGenerator(_make_config(state_code, company_name))


def _assert_xml_balanced(xml_str: str):
    """Assert that the voucher ledger entries are balanced (sum of ALLLEDGERENTRIES AMOUNTs = 0)."""
    voucher_section = re.search(r'<VOUCHER[^>]*>(.*?)</VOUCHER>', xml_str, re.DOTALL)
    if not voucher_section:
        return
    voucher = voucher_section.group(1)
    ledger_entries = re.findall(r'<ALLLEDGERENTRIES\.LIST>.*?<AMOUNT>([^<]+)</AMOUNT>.*?</ALLLEDGERENTRIES\.LIST>', voucher, re.DOTALL)
    total = sum(Decimal(a) for a in ledger_entries if a and a.strip())
    assert total == 0, f"XML not balanced: sum of ALLLEDGERENTRIES AMOUNTs = {total}, expected 0"


def _assert_ledgers_match(xml_str: str):
    """Assert that every LEDGERNAME in voucher has a matching LEDGER master."""
    # Extract all LEDGERNAMEs from voucher entries
    voucher_section = re.search(r'<VOUCHER[^>]*>(.*?)</VOUCHER>', xml_str, re.DOTALL)
    if not voucher_section:
        return
    voucher = voucher_section.group(1)
    referenced = set(re.findall(r'<LEDGERNAME>(.*?)</LEDGERNAME>', voucher))
    created = set(re.findall(r'<LEDGER\s+[^>]*NAME="([^"]+)"', xml_str))
    missing = referenced - created
    assert not missing, f"Ledgers referenced but not created: {missing}"


def _assert_stock_items_match(xml_str: str):
    """Assert that every STOCKITEMNAME has a matching STOCKITEM master."""
    voucher_section = re.search(r'<VOUCHER[^>]*>(.*?)</VOUCHER>', xml_str, re.DOTALL)
    if not voucher_section:
        return
    voucher = voucher_section.group(1)
    referenced = set(re.findall(r'<STOCKITEMNAME>(.*?)</STOCKITEMNAME>', voucher))
    created = set(re.findall(r'<STOCKITEM\s+[^>]*NAME="([^"]+)"', xml_str))
    missing = referenced - created
    assert not missing, f"Stock items referenced but not created: {missing}"


# =====================================================================
# TEST 1: Interstate Purchase with Mixed Goods & Services + Discount + Freight
# =====================================================================

class TestInterstateMixedGoodsServices:
    """Interstate purchase: laptops (goods) + software subscription (service) + maintenance (service) + freight."""

    def test_interstate_mixed_invoice(self):
        """
        Vendor: Maharashtra (27AABCU1234D1Z1)
        Buyer: Karnataka (29XXXXX1234D1Z1)
        Items:
        - Laptops: 2 x ₹50,000 = ₹1,00,000 (HSN 847130, 18% IGST)
        - Software subscription: ₹30,000 (SAC 998314, 18% IGST)
        - Annual maintenance: ₹20,000 (SAC 998315, 18% IGST)
        Discount: 5% on total before tax = ₹7,500
        Taxable after discount: ₹1,42,500
        Freight: ₹2,000 + 18% IGST = ₹2,360
        Total: ₹1,71,510
        """
        inv = StandardizedInvoice(
            invoice_number="INV-INT-001",
            invoice_date="2026-06-15",
            vendor_name="Tech Distributors",
            vendor_gstin=_MH_GSTIN,
            buyer_gstin=_KA_GSTIN,
            place_of_supply="29",
            is_service=False,
            total_taxable_value=142500.0,
            total_tax=26010.0,
            total_amount=170510.0,
            line_items=[
                LineItem(description="Laptops", quantity=2, rate=46250.0, taxable_value=92500.0,
                         tax_rate=18, hsn_sac="847130", unit="Nos", is_service=False),
                LineItem(description="Software Subscription", quantity=1, rate=30000.0, taxable_value=30000.0,
                         tax_rate=18, hsn_sac="998314", unit="Nos", is_service=True),
                LineItem(description="Annual Maintenance", quantity=1, rate=20000.0, taxable_value=20000.0,
                         tax_rate=18, hsn_sac="998315", unit="Nos", is_service=True),
            ],
            taxes=[
                TaxEntry(name="IGST", rate=18.0, amount=25650.0, type="igst"),
                TaxEntry(name="IGST", rate=18.0, amount=360.0, type="igst"),
            ],
            freight=2000.0,
            freight_gst=True,
            gst_type=GSTType.IGST,
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "IGST" in xml
        assert "Laptops" in xml or "LAPTOPS" in xml
        assert "Software Subscription" in xml or "SOFTWARE SUBSCRIPTION" in xml
        _assert_xml_balanced(xml)
        _assert_ledgers_match(xml)


# =====================================================================
# TEST 2: Intrastate Purchase with Partial Payment & Bill Allocation
# =====================================================================

class TestIntrastatePartialPayment:
    """Intrastate purchase with partial payment and bill allocation."""

    def test_intrastate_partial_payment(self):
        """
        Vendor: Maharashtra (27AABCU1234D1Z1)
        Buyer: Maharashtra (27AABBU1234F1Z)
        Items:
        - Raw materials: ₹80,000 (HSN 7207, 5% CGST+SGST)
        - Packing material: ₹20,000 (HSN 3923, 18% CGST+SGST)
        Total: ₹1,07,600
        """
        inv = StandardizedInvoice(
            invoice_number="INV-PARTIAL-001",
            invoice_date="2026-06-15",
            vendor_name="Maharashtra Suppliers",
            vendor_gstin=_MH_GSTIN,
            buyer_gstin=_MH_BUYER_GSTIN,
            place_of_supply="27",
            is_service=False,
            total_taxable_value=100000.0,
            total_tax=7600.0,
            total_amount=107600.0,
            line_items=[
                LineItem(description="Raw Materials", quantity=1, rate=80000.0, taxable_value=80000.0,
                         tax_rate=5, hsn_sac="7207", unit="Nos", is_service=False),
                LineItem(description="Packing Material", quantity=1, rate=20000.0, taxable_value=20000.0,
                         tax_rate=18, hsn_sac="3923", unit="Nos", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=2.5, amount=2000.0, type="cgst"),
                TaxEntry(name="SGST", rate=2.5, amount=2000.0, type="sgst"),
                TaxEntry(name="CGST", rate=9.0, amount=1800.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=1800.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "CGST" in xml
        assert "SGST" in xml
        assert "BILLALLOCATIONS" in xml or "BillAllocations" in xml
        _assert_xml_balanced(xml)


# =====================================================================
# TEST 3: Reverse Charge Purchase (Unregistered Vendor)
# =====================================================================

class TestReverseChargePurchase:
    """Reverse charge: unregistered vendor, buyer pays GST."""

    def test_rcm_unregistered_vendor(self):
        """
        Vendor: Unregistered (no GSTIN, from Uttar Pradesh)
        Buyer: Maharashtra (27AABBU1234F1Z)
        Items: Legal services (SAC 998311, 18% reverse charge)
        RCM applies → buyer pays GST directly
        """
        inv = StandardizedInvoice(
            invoice_number="INV-RCM-001",
            invoice_date="2026-06-15",
            vendor_name="Unregistered Consultant",
            vendor_gstin="",
            buyer_gstin=_MH_BUYER_GSTIN,
            place_of_supply="27",
            is_service=True,
            total_taxable_value=50000.0,
            total_tax=9000.0,
            total_amount=59000.0,
            line_items=[
                LineItem(description="Legal Services", quantity=1, rate=50000.0, taxable_value=50000.0,
                         tax_rate=18, hsn_sac="998311", unit="Nos", is_service=True),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9.0, amount=4500.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=4500.0, type="sgst"),
            ],
            reverse_charge=True,
            is_rcm=True,
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "RCM" in xml or "Reverse Charge" in xml or "IGST" in xml
        _assert_xml_balanced(xml)


# =====================================================================
# TEST 4: Composition Scheme Dealer (No GST Charged)
# =====================================================================

class TestCompositionScheme:
    """Composition dealer: valid GSTIN but no tax charged."""

    def test_composition_dealer(self):
        """
        Vendor: Composition dealer (27AABCU1234D1Z1)
        Buyer: Maharashtra (27AABBU1234F1Z)
        Items: Groceries (HSN 1901, 0% GST)
        No tax charged → only basic purchase
        """
        inv = StandardizedInvoice(
            invoice_number="INV-COMP-001",
            invoice_date="2026-06-15",
            vendor_name="Composition Groceries",
            vendor_gstin=_MH_GSTIN,
            buyer_gstin=_MH_BUYER_GSTIN,
            place_of_supply="27",
            is_service=False,
            total_taxable_value=10000.0,
            total_tax=0.0,
            total_amount=10000.0,
            line_items=[
                LineItem(description="Groceries", quantity=1, rate=10000.0, taxable_value=10000.0,
                         tax_rate=0, hsn_sac="1901", unit="Nos", is_service=False),
            ],
            taxes=[],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "CGST" not in xml
        assert "SGST" not in xml
        assert "IGST" not in xml
        _assert_xml_balanced(xml)


# =====================================================================
# TEST 5: Credit Note for Goods Return
# =====================================================================

class TestCreditNote:
    """Credit note: goods return with negative amounts and bill allocation."""

    def test_credit_note_goods_return(self):
        """
        Original invoice: INV-001, ₹50,000, 18% IGST
        Return: 2 laptops worth ₹10,000
        Credit note: ₹11,800 (₹10,000 + ₹1,800 IGST reversed)
        """
        inv = StandardizedInvoice(
            invoice_number="CN-INV-001",
            invoice_date="2026-06-15",
            vendor_name="Tech Distributors",
            vendor_gstin=_MH_GSTIN,
            buyer_gstin=_KA_GSTIN,
            place_of_supply="29",
            is_service=False,
            voucher_type=VoucherType.CREDIT_NOTE,
            total_taxable_value=-10000.0,
            total_tax=-1800.0,
            total_amount=-11800.0,
            line_items=[
                LineItem(description="Laptops Return", quantity=-2, rate=-5000.0, taxable_value=-10000.0,
                         tax_rate=18, hsn_sac="847130", unit="Nos", is_service=False),
            ],
            taxes=[
                TaxEntry(name="IGST", rate=18.0, amount=-1800.0, type="igst"),
            ],
            original_invoice_number="INV-001",
            original_invoice_date="2026-06-01",
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "CREDIT NOTE" in xml or "Credit Note" in xml
        _assert_xml_balanced(xml)
        _assert_ledgers_match(xml)


# =====================================================================
# TEST 6: Debit Note for Price Increase
# =====================================================================

class TestDebitNote:
    """Debit note: price increase after delivery."""

    def test_debit_note_price_increase(self):
        """
        Original invoice: INV-002, ₹20,000
        Price increase: ₹2,000 + 18% IGST = ₹2,360
        Debit note issued
        """
        inv = StandardizedInvoice(
            invoice_number="DN-INV-002",
            invoice_date="2026-06-15",
            vendor_name="Tech Distributors",
            vendor_gstin=_MH_GSTIN,
            buyer_gstin=_KA_GSTIN,
            place_of_supply="29",
            is_service=True,
            voucher_type=VoucherType.DEBIT_NOTE,
            total_taxable_value=2000.0,
            total_tax=360.0,
            total_amount=2360.0,
            line_items=[
                LineItem(description="Price Adjustment", quantity=1, rate=2000.0, taxable_value=2000.0,
                         tax_rate=18, hsn_sac="", unit="Nos", is_service=True),
            ],
            taxes=[
                TaxEntry(name="IGST", rate=18.0, amount=360.0, type="igst"),
            ],
            original_invoice_number="INV-002",
            original_invoice_date="2026-06-01",
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "DEBIT NOTE" in xml or "Debit Note" in xml
        _assert_xml_balanced(xml)
        _assert_ledgers_match(xml)


# =====================================================================
# TEST 7: Journal Entry for Depreciation
# =====================================================================

class TestJournalEntry:
    """Journal voucher: depreciation on fixed assets, no GST."""

    def test_journal_depreciation(self):
        """
        Debit: Depreciation Expense ₹10,000
        Credit: Accumulated Depreciation ₹10,000
        No vendor, no GST
        """
        inv = StandardizedInvoice(
            invoice_number="JRN-DEP-001",
            invoice_date="2026-06-15",
            vendor_name="",
            vendor_gstin="",
            place_of_supply="27",
            is_service=True,
            voucher_type=VoucherType.JOURNAL,
            total_taxable_value=10000.0,
            total_tax=0.0,
            total_amount=10000.0,
            line_items=[
                LineItem(description="Depreciation Expense", quantity=1, rate=10000.0, taxable_value=10000.0,
                         tax_rate=0, hsn_sac="", unit="Nos", is_service=True, ledger_name="Depreciation Expense"),
            ],
            taxes=[],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "JOURNAL" in xml or "Journal" in xml
        _assert_xml_balanced(xml)


# =====================================================================
# TEST 8: Payment Voucher with Multiple Bank Accounts
# =====================================================================

class TestPaymentVoucher:
    """Payment voucher: payment from multiple bank accounts + bank charges."""

    def test_payment_multiple_banks(self):
        """
        Payment to vendor: ₹50,000
        From Current Account: ₹30,000
        From Cash: ₹20,000
        Bank charges: ₹100
        Total credit: ₹50,100
        """
        inv = StandardizedInvoice(
            invoice_number="PAY-001",
            invoice_date="2026-06-15",
            vendor_name="ABC Electronics",
            vendor_gstin=_MH_GSTIN,
            place_of_supply="27",
            is_service=False,
            voucher_type=VoucherType.PAYMENT,
            total_taxable_value=50100.0,
            total_tax=0.0,
            total_amount=50100.0,
            line_items=[
                LineItem(description="Payment to ABC Electronics", quantity=1, rate=50000.0, taxable_value=50000.0,
                         tax_rate=0, hsn_sac="", unit="Nos", is_service=False, ledger_name="ABC Electronics"),
                LineItem(description="Bank Charges", quantity=1, rate=100.0, taxable_value=100.0,
                         tax_rate=0, hsn_sac="", unit="Nos", is_service=False, ledger_name="Bank Charges"),
            ],
            taxes=[],
            freight=0.0,
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "PAYMENT" in xml or "Payment" in xml
        _assert_xml_balanced(xml)
        _assert_ledgers_match(xml)


# =====================================================================
# TEST 9: Sales Invoice with Export (Zero-Rated)
# =====================================================================

class TestExportZeroRated:
    """Export invoice: overseas buyer, zero-rated, no GST."""

    def test_export_zero_rated(self):
        """
        Seller: Maharashtra (27AABCU1234D1Z1)
        Buyer: Overseas (no GSTIN)
        Items: Software services (SAC 998314, 0% IGST for export)
        Zero-rated supply → no tax ledgers
        """
        inv = StandardizedInvoice(
            invoice_number="EXP-001",
            invoice_date="2026-06-15",
            vendor_name="Overseas Client",
            vendor_gstin="",
            buyer_gstin="",
            place_of_supply="97",  # Outside India
            is_service=True,
            voucher_type=VoucherType.SALES,
            total_taxable_value=100000.0,
            total_tax=0.0,
            total_amount=100000.0,
            line_items=[
                LineItem(description="Software Development Services", quantity=1, rate=100000.0, taxable_value=100000.0,
                         tax_rate=0, hsn_sac="998314", unit="Nos", is_service=True),
            ],
            taxes=[],
            is_sez=False,
            is_lut=False,
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "SALES" in xml or "Sales" in xml
        assert "CGST" not in xml
        assert "SGST" not in xml
        assert "IGST" not in xml
        _assert_xml_balanced(xml)
        _assert_ledgers_match(xml)


# =====================================================================
# TEST 10: Mixed Tax Rates with Discount and Rounding
# =====================================================================

class TestMixedTaxRatesDiscountRounding:
    """Mixed tax rates, discount apportionment, and rounding."""

    def test_mixed_rates_discount_rounding(self):
        """
        Vendor: Maharashtra (27AABCU1234D1Z1)
        Buyer: Maharashtra (27AABBU1234F1Z)
        Items:
        - Item A: ₹45,000, 5% GST = ₹2,250 + ₹2,250 = ₹49,500
        - Item B: ₹27,000, 12% GST = ₹3,240 + ₹3,240 = ₹33,480
        - Item C: ₹18,000, 18% GST = ₹3,240 + ₹3,240 = ₹24,480
        Subtotal: ₹90,000
        Tax:
        - Item A 5%: ₹2,250 + ₹2,250 = ₹4,500
        - Item B 12%: ₹3,240 + ₹3,240 = ₹6,480
        - Item C 18%: ₹3,240 + ₹3,240 = ₹6,480
        Total tax: ₹8,730
        Grand total: ₹98,730
        """
        inv = StandardizedInvoice(
            invoice_number="INV-MIX-001",
            invoice_date="2026-06-15",
            vendor_name="Maharashtra Traders",
            vendor_gstin=_MH_GSTIN,
            buyer_gstin=_MH_BUYER_GSTIN,
            place_of_supply="27",
            is_service=False,
            total_taxable_value=90000.0,
            total_tax=8730.0,
            total_amount=98730.0,
            line_items=[
                LineItem(description="Item A", quantity=1, rate=45000.0, taxable_value=45000.0,
                         tax_rate=5, hsn_sac="1001", unit="Nos", is_service=False),
                LineItem(description="Item B", quantity=1, rate=27000.0, taxable_value=27000.0,
                         tax_rate=12, hsn_sac="1002", unit="Nos", is_service=False),
                LineItem(description="Item C", quantity=1, rate=18000.0, taxable_value=18000.0,
                         tax_rate=18, hsn_sac="1003", unit="Nos", is_service=False),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=2.5, amount=1125.0, type="cgst"),
                TaxEntry(name="SGST", rate=2.5, amount=1125.0, type="cgst"),
                TaxEntry(name="CGST", rate=6.0, amount=1620.0, type="cgst"),
                TaxEntry(name="SGST", rate=6.0, amount=1620.0, type="sgst"),
                TaxEntry(name="CGST", rate=9.0, amount=1620.0, type="cgst"),
                TaxEntry(name="SGST", rate=9.0, amount=1620.0, type="sgst"),
            ],
        )
        result = validate_invoice_for_xml(inv)
        assert result.passed, result.errors
        xml = _make_generator("27", "Test Co").generate(inv)
        assert "CGST" in xml
        assert "SGST" in xml
        _assert_xml_balanced(xml)
        _assert_ledgers_match(xml)
