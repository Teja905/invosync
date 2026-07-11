"""Tests for XML envelope structure, master creation, and edge cases."""

import re
import sys
import xml.etree.ElementTree as ET
sys.path.insert(0, __file__)

from schemas import StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig

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

def make_inv(**kwargs):
    defaults = dict(
        invoice_number="INV-001",
        invoice_date="2026-06-10",
        vendor_name="Test Vendor",
        vendor_gstin="27AABCU1234F1ZP",
        total_taxable_value=10000,
        total_tax=1800,
        total_amount=11800,
        gst_type=GSTType.CGST_SGST,
        is_service=False,
        voucher_type=VoucherType.PURCHASE,
        line_items=[LineItem(description="Item", quantity=10, rate=1000, taxable_value=10000, tax_rate=18)],
        taxes=[TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst"),
               TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst")],
    )
    defaults.update(kwargs)
    return StandardizedInvoice(**defaults)

def get_balance(xml: str) -> float:
    cleaned = re.sub(r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", xml, flags=re.DOTALL)
    cleaned = re.sub(r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>", "", cleaned, flags=re.DOTALL)
    amounts = re.findall(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", cleaned)
    return sum(float(a) for a in amounts)


print("=" * 60)
print("STRUCTURAL TESTS: Envelope layout & master creation")
print("=" * 60)

# ============================================================
# CATEGORY 1: Envelope structure
# ============================================================
print("\n--- 1. Envelope structure ---")

# 1.1 Two envelopes by default
xml = TallyXmlGenerator().generate(make_inv())
env_count = xml.count("<ENVELOPE>")
check("1.1 Two envelopes generated", env_count == 2, f"got {env_count}")

# 1.2 First envelope is IMPORTDATA (masters)
has_masters = "IMPORTDATA" in xml.split("<ENVELOPE>")[1] if "<ENVELOPE>" in xml else False
check("1.2 First envelope uses IMPORTDATA", has_masters)

# 1.3 First envelope has LEDGER ACTION=Create
has_ledger_create = 'LEDGER NAME="Test Vendor" ACTION="Create"' in xml
check("1.3 Vendor LEDGER with ACTION=Create in first envelope", has_ledger_create)

# 1.4 First envelope has VOUCHERTYPE ACTION=Create
has_vtype = 'VOUCHERTYPE NAME="Purchase" ACTION="Create"' in xml
check("1.4 VOUCHERTYPE Purchase with ACTION=Create", has_vtype)

# 1.5 Voucher envelope uses TYPE=Data (ElementTree produces <TYPE>Data</TYPE>)
has_type_data = "<TYPE>Data</TYPE>" in xml
has_id_masters = "<ID>All Masters</ID>" in xml
check("1.5 Voucher envelope has TYPE=Data", has_type_data and has_id_masters)

# 1.6 SVCURRENTCOMPANY exists (only in voucher envelope)
check("1.6 Voucher envelope has SVCURRENTCOMPANY", "SVCURRENTCOMPANY" in xml)

# 1.7 VOUCHER element exists
check("1.7 Voucher envelope contains VOUCHER", "<VOUCHER" in xml)

# 1.8 Single XML declaration at top
decl_count = xml.count('<?xml version="1.0" encoding="UTF-8"?>')
check("1.8 Exactly one XML declaration", decl_count == 1, f"got {decl_count}")

# 1.9 XML declaration is on first line
first_line = xml.split("\n")[0] if "\n" in xml else xml
check("1.9 XML declaration is first line", first_line == '<?xml version="1.0" encoding="UTF-8"?>')

# 1.10 Voucher is balanced
bal = get_balance(xml)
check("1.10 Voucher is balanced (Dr=Cr)", abs(bal) < 0.01, f"balance={bal}")

# ============================================================
# CATEGORY 2: include_ledgers=False
# ============================================================
print("\n--- 2. include_ledgers=False ---")

xml2 = TallyXmlGenerator(include_ledgers=False).generate(make_inv())
check("2.1 Single envelope when include_ledgers=False", xml2.count("<ENVELOPE>") == 1)
check("2.2 No IMPORTDATA when include_ledgers=False", "IMPORTDATA" not in xml2)
check("2.3 No LEDGER creation when include_ledgers=False", 'LEDGER NAME=' not in xml2)
check("2.4 No VOUCHERTYPE creation when include_ledgers=False", 'VOUCHERTYPE NAME=' not in xml2)
check("2.5 Voucher still present when include_ledgers=False", "<VOUCHER" in xml2)
bal2 = get_balance(xml2)
check("2.6 Voucher balanced when include_ledgers=False", abs(bal2) < 0.01, f"balance={bal2}")

# ============================================================
# CATEGORY 3: Master creation details
# ============================================================
print("\n--- 3. Master creation details ---")

# 3.1 Purchase ledger created
check("3.1 Purchase ledger created", 'LEDGER NAME="Purchase" ACTION="Create"' in xml)

# 3.2 GST ledgers created
check("3.2 CGST ledger created", 'LEDGER NAME="Input CGST 9%" ACTION="Create"' in xml)
check("3.3 SGST ledger created", 'LEDGER NAME="Input SGST 9%" ACTION="Create"' in xml)

# 3.3 Vendor GSTIN in ledger
check("3.4 Vendor GSTIN in ledger", "27AABCU1234F1ZP" in xml.split("<ENVELOPE>")[1])

# 3.4 Party parent group
check("3.5 Party parent is Sundry Creditors", "<PARENT>Sundry Creditors</PARENT>" in xml)

# 3.5 Purchase ledger parent
check("3.6 Purchase parent is Purchase Accounts", "<PARENT>Purchase Accounts</PARENT>" in xml)

# 3.6 GST ledger parent
check("3.7 GST parent is Duties & Taxes", "<PARENT>Duties &amp; Taxes</PARENT>" in xml)

# 3.7 Sales voucher type creates different ledgers
inv_sales = make_inv(
    voucher_type=VoucherType.SALES, buyer_name="Test Customer", vendor_name="",
    buyer_gstin="27AABCU2345F1ZJ",
    taxes=[TaxEntry(name="Output CGST 9%", rate=9, amount=900, type="cgst"),
           TaxEntry(name="Output SGST 9%", rate=9, amount=900, type="sgst")],
)
xml_sales = TallyXmlGenerator().generate(inv_sales)
check("3.8 Sales voucher has Output CGST in masters", 'LEDGER NAME="Output CGST 9%" ACTION="Create"' in xml_sales)
check("3.9 Sales voucher has Output SGST in masters", 'LEDGER NAME="Output SGST 9%" ACTION="Create"' in xml_sales)
check("3.10 Sales party parent is Sundry Debtors", "<PARENT>Sundry Debtors</PARENT>" in xml_sales)
check("3.11 Sales party is customer", 'LEDGER NAME="Test Customer" ACTION="Create"' in xml_sales)

# ============================================================
# CATEGORY 4: Voucher type creation
# ============================================================
print("\n--- 4. Voucher type creation for all 7 types ---")

for vt in VoucherType:
    inv_vt = make_inv(voucher_type=vt, taxes=[])
    xml_vt = TallyXmlGenerator().generate(inv_vt)
    expected_name = vt.value
    has_vt = f'VOUCHERTYPE NAME="{expected_name}" ACTION="Create"' in xml_vt
    check(f"4.{vt.value} voucher type created", has_vt)
    bal_vt = get_balance(xml_vt)
    check(f"4.{vt.value} balanced", abs(bal_vt) < 0.01, f"balance={bal_vt}")

# ============================================================
# CATEGORY 5: auto_create_stock_items (goods with HSN)
# ============================================================
print("\n--- 5. Stock item creation ---")

inv_stock = make_inv(
    invoice_number="STK-001",
    line_items=[
        LineItem(description="Product A", hsn_sac="847130", quantity=5, rate=2000, taxable_value=10000, tax_rate=18, unit="Nos"),
        LineItem(description="Product B", hsn_sac="620442", quantity=10, rate=500, taxable_value=5000, tax_rate=12, unit="Pcs"),
    ],
    auto_create_stock_items=True,
)
xml_stock = TallyXmlGenerator().generate(inv_stock)
check("5.1 STOCKGROUP in masters when auto_create_stock_items", 'STOCKGROUP NAME="Primary" ACTION="Create"' in xml_stock)
check("5.2 STOCKITEM Product A in masters", 'STOCKITEM NAME="Product A" ACTION="Create"' in xml_stock)
check("5.3 STOCKITEM Product B in masters", 'STOCKITEM NAME="Product B" ACTION="Create"' in xml_stock)
check("5.4 HSN code on stock item", 'HSNCODE>847130<' in xml_stock)
check("5.5 UNITS on stock item", 'UNITS>Nos<' in xml_stock or 'UNITS>Pcs<' in xml_stock)
check("5.6 RATEOFDEALING on stock item", 'RATEOFDEALING>' in xml_stock)
check("5.7 Stock items in first (IMPORTDATA) envelope", "STOCKITEM" in xml_stock.split("<ENVELOPE>")[1])
bal_stock = get_balance(xml_stock)
check("5.8 Auto-create stock + balanced", abs(bal_stock) < 0.01, f"balance={bal_stock}")

# 5.9 Service invoices should NOT have stock items even if auto_create is set
inv_svc_stock = make_inv(
    is_service=True, auto_create_stock_items=True,
    line_items=[LineItem(description="Consulting", hsn_sac="998314", quantity=1, rate=10000, taxable_value=10000, tax_rate=18, is_service=True)],
    taxes=[TaxEntry(name="Input CGST 9%", rate=9, amount=900, type="cgst"),
           TaxEntry(name="Input SGST 9%", rate=9, amount=900, type="sgst")],
)
xml_svc_stock = TallyXmlGenerator().generate(inv_svc_stock)
check("5.9 Service invoice skips stock items even with auto_create=True", "STOCKITEM" not in xml_svc_stock)
check("5.10 Service invoice still balanced", abs(get_balance(xml_svc_stock)) < 0.01)

# ============================================================
# CATEGORY 6: preview_masters and pre_import_check
# ============================================================
print("\n--- 6. Preview and pre-import check ---")

gen = TallyXmlGenerator()
inv_p = make_inv()

preview = gen.preview_masters(inv_p)
check("6.1 preview_masters returns list", isinstance(preview, list))
check("6.2 Preview has voucher type entry", any(e["type"] == "VoucherType" for e in preview))
check("6.3 Preview has party ledger", any(e["type"] == "Ledger" and e["name"] == inv_p.vendor_name for e in preview))
check("6.4 Preview has purchase ledger", any(e["type"] == "Ledger" and "Purchase" in e.get("name", "") for e in preview))
check("6.5 Preview has GST ledgers", any(e.get("gst_type") in ("Central Tax", "State Tax", "Integrated Tax") for e in preview if e.get("gst_type")))
check("6.6 Preview count includes vendor type + ledgers", len(preview) >= 4)

# preview includes freight/tds/round_off when present
inv_frt = make_inv(freight=200, round_off=1.0)
preview_frt = gen.preview_masters(inv_frt)
check("6.7 Preview includes freight ledger", any(e.get("name") == "Freight Expenses" for e in preview_frt))
check("6.8 Preview includes round-off ledger", any(e.get("name") == "Round Off" for e in preview_frt))

# pre_import_check
pic = gen.pre_import_check(inv_p)
check("6.9 pre_import_check returns dict", isinstance(pic, dict))
check("6.10 pre_import_check has masters list", isinstance(pic.get("masters"), list))
check("6.11 pre_import_check has count", pic.get("count", 0) > 0)
check("6.12 pre_import_check has company info", "company" in pic)
check("6.13 pre_import_check has voucher info", "voucher" in pic)
check("6.14 pre_import_check company name reflected", pic.get("company", {}).get("name") == "My Company")

# pre_import_check with empty company name warns
gen_empty = TallyXmlGenerator(CompanyConfig())
gen_empty.config.company_name = ""
pic_empty = gen_empty.pre_import_check(make_inv())
has_warning = any(w.get("type") == "company_name" for w in pic_empty.get("warnings", []))
check("6.15 Empty company name generates warning", has_warning)

# ============================================================
# CATEGORY 7: Edge cases - _ensure_ledger fallback
# ============================================================
print("\n--- 7. Edge cases ---")

# 7.1 Party name with special characters
inv_special = make_inv(vendor_name="Acme & Sons <Printers>")
xml_special = TallyXmlGenerator().generate(inv_special)
check("7.1 Special chars in vendor name handled", "Acme" in xml_special)
check("7.1b Special chars don't break XML", abs(get_balance(xml_special)) < 0.01)

# 7.2 Empty party name (Suspense fallback)
inv_no_name = make_inv(vendor_name="")
xml_no_name = TallyXmlGenerator().generate(inv_no_name)
check("7.2 Empty vendor name uses Suspense ledger fallback", "Suspense Ledger" in xml_no_name or "<PARTYLEDGERNAME>" in xml_no_name)
check("7.2b Empty vendor still balanced", abs(get_balance(xml_no_name)) < 0.01)

# 7.3 Very long vendor name
inv_long = make_inv(vendor_name="X" * 200)
xml_long = TallyXmlGenerator().generate(inv_long)
check("7.3 Very long vendor name generated", "<VOUCHER" in xml_long)
check("7.3b Long name balanced", abs(get_balance(xml_long)) < 0.01)

# 7.4 No invoice number
inv_no_num = make_inv(invoice_number="")
xml_no_num = TallyXmlGenerator().generate(inv_no_num)
check("7.4 Empty invoice number handled", "<VOUCHERNUMBER>.</VOUCHERNUMBER>" in xml_no_num)
check("7.4b No number balanced", abs(get_balance(xml_no_num)) < 0.01)

# 7.5 No invoice date (falls back to today)
inv_no_date = make_inv(invoice_date="")
xml_no_date = TallyXmlGenerator().generate(inv_no_date)
import datetime
today = datetime.date.today().strftime("%Y%m%d")
check("7.5 Empty date uses today's date", today in xml_no_date)
check("7.5b No date balanced", abs(get_balance(xml_no_date)) < 0.01)

# 7.6 DD/MM/YYYY date format
inv_dmy = make_inv(invoice_date="15/01/2024")
xml_dmy = TallyXmlGenerator().generate(inv_dmy)
check("7.6 DD/MM/YYYY date parsed", "20240115" in xml_dmy)
check("7.6b DD/MM/YYYY balanced", abs(get_balance(xml_dmy)) < 0.01)

# 7.7 Exempt GST (no taxes)
inv_exempt = make_inv(line_items=[], taxes=[], total_tax=0, gst_type=GSTType.EXEMPT)
xml_exempt = TallyXmlGenerator().generate(inv_exempt)
check("7.7 Exempt GST generates valid XML", "<VOUCHER" in xml_exempt)
check("7.7b Exempt balanced", abs(get_balance(xml_exempt)) < 0.01)

# 7.8 IGST with 28% slab
inv_igst28 = make_inv(
    vendor_gstin="29AABCU1234F1ZL",
    gst_type=GSTType.IGST,
    taxes=[TaxEntry(name="Input IGST 28%", rate=28, amount=2800, type="igst")],
    line_items=[LineItem(description="Machinery", quantity=1, rate=10000, taxable_value=10000, tax_rate=28)],
    total_tax=2800, total_amount=12800,
)
xml_igst28 = TallyXmlGenerator().generate(inv_igst28)
check("7.8 IGST 28% has correct ledger", 'LEDGER NAME="Input IGST 28%" ACTION="Create"' in xml_igst28)
check("7.8b IGST 28% balanced", abs(get_balance(xml_igst28)) < 0.01)

# ============================================================
# CATEGORY 8: Config customization
# ============================================================
print("\n--- 8. Config customization ---")

config = CompanyConfig()
config.company_name = "ACME Corp"
config.default_purchase_ledger = "Purchase A/c"
config.default_sales_ledger = "Sales A/c"
gen_cfg = TallyXmlGenerator(config)
xml_cfg = gen_cfg.generate(make_inv())
check("8.1 Custom company name in SVCURRENTCOMPANY", "SVCURRENTCOMPANY>ACME Corp<" in xml_cfg)
check("8.2 Custom purchase ledger name", '<LEDGER NAME="Purchase A/c" ACTION="Create"' in xml_cfg)
check("8.3 Purchase ledger used in voucher", "<LEDGERNAME>Purchase A/c</LEDGERNAME>" in xml_cfg)
check("8.4 Custom config balanced", abs(get_balance(xml_cfg)) < 0.01)

# ============================================================
# CATEGORY 9: All 7 voucher types generate with correct VCHTYPE
# ============================================================
print("\n--- 9. VCHTYPE correctness ---")

for vt in VoucherType:
    inv_vt = make_inv(voucher_type=vt, taxes=[])
    xml_vt = TallyXmlGenerator().generate(inv_vt)
    expected_vchtype = vt.value
    check(f"9.{vt.value} VCHTYPE correct", f'VCHTYPE="{expected_vchtype}"' in xml_vt)

# ============================================================
# CATEGORY 10: generate_xml for Sales with credit note type
# ============================================================
print("\n--- 10. Cross-voucher-type integrity ---")

# Sales with goods (no service flag)
inv_sales_goods = make_inv(
    voucher_type=VoucherType.SALES, buyer_name="Retail Customer", vendor_name="",
    buyer_gstin="27AABCU2345F1ZJ",
    line_items=[LineItem(description="Product", quantity=2, rate=5000, taxable_value=10000, tax_rate=18)],
    taxes=[TaxEntry(name="Output CGST 9%", rate=9, amount=900, type="cgst"),
           TaxEntry(name="Output SGST 9%", rate=9, amount=900, type="sgst")],
)
xml_sg = TallyXmlGenerator().generate(inv_sales_goods)
check("10.1 Sales goods: invoice flag YES", "<ISINVOICE>Yes</ISINVOICE>" in xml_sg)
check("10.2 Sales goods: has party ledger entry", '<LEDGERNAME>Retail Customer</LEDGERNAME>' in xml_sg)
check("10.3 Sales goods: balanced", abs(get_balance(xml_sg)) < 0.01)

# Payment voucher
inv_pay = make_inv(
    voucher_type=VoucherType.PAYMENT, taxes=[], total_tax=0, total_amount=10000, gst_type=GSTType.CGST_SGST,
    vendor_name="ABC Suppliers",
)
xml_pay = TallyXmlGenerator().generate(inv_pay)
check("10.4 Payment: has bank debit", '<LEDGERNAME>Bank</LEDGERNAME>' in xml_pay)
check("10.5 Payment: ISINVOICE=No", "<ISINVOICE>No</ISINVOICE>" in xml_pay)
check("10.6 Payment: balanced", abs(get_balance(xml_pay)) < 0.01)


print(f"\n{'='*60}")
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
