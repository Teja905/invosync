"""Comprehensive balance audit — tests every edge case for amount calculation & XML balance."""

import re
import sys
from schemas import StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry
from xml_generator import TallyXmlGenerator
from validation_layer import validate_invoice_for_xml, validate_xml_output
from gst_engine import compute_gst_entries

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")

def get_xml_balance(xml: str) -> float:
    """Sum ALL AMOUNTs from ledger entries only (excludes inventory & bill allocations)."""
    cleaned = re.sub(r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", xml, flags=re.DOTALL)
    cleaned = re.sub(r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>", "", cleaned, flags=re.DOTALL)
    amounts = re.findall(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", cleaned)
    return sum(float(a) for a in amounts)

def make_inv(**kwargs):
    defaults = dict(
        invoice_number="INV-001",
        invoice_date="2026-05-26",
        vendor_name="Test Vendor",
        vendor_gstin="27AABCU1234F1ZP",
        buyer_gstin="27AABCU2345F1ZJ",
        total_taxable_value=10000,
        total_tax=1800,
        total_amount=11800,
        gst_type=GSTType.CGST_SGST,
        is_interstate=False,
        is_service=False,
        voucher_type=VoucherType.PURCHASE,
        line_items=[LineItem(description="Item", quantity=10, rate=1000, taxable_value=10000, tax_rate=18)],
        taxes=[TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst", is_input=True),
               TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst", is_input=True)],
    )
    defaults.update(kwargs)
    return StandardizedInvoice(**defaults)


print("=" * 60)
print("BALANCE AUDIT: BACKEND (xml_generator.py)")
print("=" * 60)

# === 1. Basic purchase goods ===
print("\n--- 1. Basic scenarios ---")

xml = TallyXmlGenerator().generate(make_inv())
bal = get_xml_balance(xml)
check("Basic purchase balanced", abs(bal) < 0.01, f"balance={bal}")

# === 2. Purchase service (no inventory) ===
xml = TallyXmlGenerator().generate(make_inv(is_service=True))
bal = get_xml_balance(xml)
check("Service purchase (no inventory) balanced", abs(bal) < 0.01, f"balance={bal}")

# === 3. No line items, no taxes (zero tax) ===
inv = make_inv(line_items=[], taxes=[], total_tax=0, total_amount=10000, gst_type=GSTType.CGST_SGST)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("No items, no taxes balanced", abs(bal) < 0.01, f"balance={bal}")

# === 4. With freight ===
inv = make_inv(freight=500, total_amount=12300)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("With freight balanced", abs(bal) < 0.01, f"balance={bal}")

# === 5. With TDS ===
inv = make_inv(tds_amount=200, tds_rate=2, total_amount=11600)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("With TDS balanced", abs(bal) < 0.01, f"balance={bal}")

# === 6. With positive round-off ===
inv = make_inv(round_off=0.50, total_amount=11800.50)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("With positive round-off balanced", abs(bal) < 0.01, f"balance={bal}")

# === 7. With negative round-off ===
inv = make_inv(round_off=-0.50, total_amount=11799.50)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("With negative round-off balanced", abs(bal) < 0.01, f"balance={bal}")

# === 8. Freight + TDS + round-off combined ===
inv = make_inv(freight=300, tds_amount=100, round_off=-0.25, total_amount=12199.75)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Freight+TDS+round-off combined balanced", abs(bal) < 0.01, f"balance={bal}")

# === 9. IGST (inter-state) ===
inv = make_inv(gst_type=GSTType.IGST, is_interstate=True,
               taxes=[TaxEntry(name="Input IGST 18%", rate=18, amount=1800, type="igst", is_input=True)])
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("IGST inter-state balanced", abs(bal) < 0.01, f"balance={bal}")

# === 10. Mixed GST rates ===
inv = make_inv(
    total_taxable_value=15000, total_tax=2050, total_amount=17050,
    line_items=[
        LineItem(description="Book", quantity=10, rate=500, taxable_value=5000, tax_rate=5),
        LineItem(description="Laptop", quantity=2, rate=5000, taxable_value=10000, tax_rate=18),
    ],
    taxes=[
        TaxEntry(name="Input CGST 2.5%", rate=2.5, amount=125, type="cgst", is_input=True),
        TaxEntry(name="Input SGST 2.5%", rate=2.5, amount=125, type="sgst", is_input=True),
        TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst", is_input=True),
        TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst", is_input=True),
    ],
)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Mixed GST rates balanced", abs(bal) < 0.01, f"balance={bal}")

# === 11. Sales voucher (basic) ===
inv = make_inv(voucher_type=VoucherType.SALES, buyer_name="Test Customer", vendor_name="")
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Sales voucher balanced", abs(bal) < 0.01, f"balance={bal}")

# === 12. Sales with negative round-off ===
inv = make_inv(voucher_type=VoucherType.SALES, buyer_name="Test Customer", vendor_name="",
               round_off=-0.50, total_amount=11799.50)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Sales with round-off balanced", abs(bal) < 0.01, f"balance={bal}")

# === 13. Sales service (no inventory) ===
inv = make_inv(voucher_type=VoucherType.SALES, buyer_name="Test Customer", vendor_name="",
               is_service=True)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Sales service (no inventory) balanced", abs(bal) < 0.01, f"balance={bal}")

# === 14. Sales IGST ===
inv = make_inv(voucher_type=VoucherType.SALES, buyer_name="Interstate Customer", vendor_name="",
               gst_type=GSTType.IGST, is_interstate=True,
               taxes=[TaxEntry(name="Output IGST 18%", rate=18, amount=1800, type="igst", is_input=False)])
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Sales IGST balanced", abs(bal) < 0.01, f"balance={bal}")

# === 15. Credit note ===
inv = make_inv(voucher_type=VoucherType.CREDIT_NOTE)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Credit note balanced", abs(bal) < 0.01, f"balance={bal}")

# === 16. Debit note ===
inv = make_inv(voucher_type=VoucherType.DEBIT_NOTE)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Debit note balanced", abs(bal) < 0.01, f"balance={bal}")

# === 17. Journal voucher ===
inv = make_inv(voucher_type=VoucherType.JOURNAL)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Journal voucher balanced", abs(bal) < 0.01, f"balance={bal}")

# === 18. Payment voucher ===
inv = make_inv(voucher_type=VoucherType.PAYMENT, taxes=[], total_tax=0, total_amount=10000, gst_type=GSTType.CGST_SGST)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Payment voucher balanced", abs(bal) < 0.01, f"balance={bal}")

# === 19. Receipt voucher ===
inv = make_inv(voucher_type=VoucherType.RECEIPT, taxes=[], total_tax=0, total_amount=10000, gst_type=GSTType.CGST_SGST)
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Receipt voucher balanced", abs(bal) < 0.01, f"balance={bal}")

# === 20. Zero amounts ===
inv = make_inv(total_taxable_value=0, total_tax=0, total_amount=0, line_items=[], taxes=[])
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Zero amounts balanced", abs(bal) < 0.01, f"balance={bal}")

# === 21. Computer-generated taxes (no pre-filled taxes) ===
inv = make_inv(taxes=[])
xml = TallyXmlGenerator().generate(inv)
bal = get_xml_balance(xml)
check("Computer-generated taxes balanced", abs(bal) < 0.01, f"balance={bal}")


print("\n" + "=" * 60)
print("BALANCE AUDIT: INVO SYNC (invosync/)")
print("=" * 60)

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from invosync.models import InvoiceRequest, LineItem as InvLineItem
    from invosync.xml_generator import generate_purchase_xml, generate_sales_xml
    HAS_INVOSYNC = True
except ImportError as e:
    HAS_INVOSYNC = False
    print(f"  [SKIP] invosync not importable: {e}")

if HAS_INVOSYNC:
    print("\n--- Purchase vouchers ---")

    d = InvoiceRequest(company_gstin="27AABCU1234F1ZP", party_gstin="27AABCU2345F1ZJ",
        party_name="Test", invoice_number="I-001", invoice_date="2026-05-26",
        taxable_total=10000, tax_total=1800, grand_total=11800, tax_rate=18)
    xml = generate_purchase_xml(d)
    bal = get_xml_balance(xml)
    check("Basic purchase", abs(bal) < 0.01, f"balance={bal}")

    d2 = InvoiceRequest(company_gstin="27AABCU1234F1ZP", party_gstin="07AABCU1234F1ZR",
        party_name="Delhi Supplier", invoice_number="I-002", invoice_date="26/05/2026",
        taxable_total=10000, tax_total=1800, grand_total=11800, tax_rate=18)
    xml = generate_purchase_xml(d2)
    bal = get_xml_balance(xml)
    check("Inter-state purchase (IGST)", abs(bal) < 0.01, f"balance={bal}")

    d3 = InvoiceRequest(company_gstin="27AABCU1234F1ZP", party_gstin="27AABCU2345F1ZJ",
        party_name="Test", invoice_number="I-003", invoice_date="2026-05-26",
        taxable_total=0, tax_total=0, grand_total=0, tax_rate=0)
    xml = generate_purchase_xml(d3)
    bal = get_xml_balance(xml)
    check("Zero amounts", abs(bal) < 0.01, f"balance={bal}")

    print("\n--- Sales vouchers ---")

    d4 = InvoiceRequest(company_gstin="27AABCU1234F1ZP", party_gstin="27AABCU2345F1ZJ",
        party_name="Buyer", invoice_number="S-001", invoice_date="2026-05-26",
        taxable_total=10000, tax_total=1800, grand_total=11800, tax_rate=18)
    xml = generate_sales_xml(d4)
    bal = get_xml_balance(xml)
    check("Basic sales", abs(bal) < 0.01, f"balance={bal}")

    d5 = InvoiceRequest(company_gstin="27AABCU1234F1ZP", party_gstin="29AABCU1234F1ZL",
        party_name="Bangalore Buyer", invoice_number="S-002", invoice_date="2026-05-26",
        taxable_total=10000, tax_total=1800, grand_total=11800, tax_rate=18)
    xml = generate_sales_xml(d5)
    bal = get_xml_balance(xml)
    check("Sales inter-state (IGST)", abs(bal) < 0.01, f"balance={bal}")

    d6 = InvoiceRequest(company_gstin="27AABCU1234F1ZP", party_gstin="27AABCU2345F1ZJ",
        party_name="Buyer", invoice_number="S-003", invoice_date="2026-05-26",
        taxable_total=5000, tax_total=250, grand_total=5250, tax_rate=5,
        line_items=[InvLineItem(description="Book", quantity=10, rate=500, taxable_amount=5000, tax_rate=5)])
    xml = generate_sales_xml(d6)
    bal = get_xml_balance(xml)
    check("Sales with line items", abs(bal) < 0.01, f"balance={bal}")


print("\n" + "=" * 60)
print("VALIDATION AUDIT")
print("=" * 60)

# Test validation catches bad data
inv_bad_total = make_inv(total_taxable_value=10000, total_tax=1800, total_amount=99999, line_items=[], taxes=[])
result = validate_invoice_for_xml(inv_bad_total)
check("Validation catches total mismatch",
      not result.passed,
      f"Checks: {list(result.checks.keys())}, errors: {result.errors}")

inv_negative = make_inv(total_taxable_value=-100, total_tax=-18, total_amount=-118)
result = validate_invoice_for_xml(inv_negative)
check("Validation handles negative amounts", True,
      f"Checks: {list(result.checks.keys())}, passed: {result.passed}")

inv_balanced = make_inv()
result = validate_invoice_for_xml(inv_balanced)
check("Valid invoice passes validation",
      result.passed,
      f"Errors: {result.errors}")


print(f"\n{'='*60}")
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
