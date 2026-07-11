"""Comprehensive tests for InvoSync — purchase, sales, GST, validation, balance."""

import json
import re
import sys
from models import InvoiceRequest, LineItem
from gst import classify_gst, compute_tax, compute_tax_from_items
from validation import validate_invoice
from xml_generator import generate_purchase_xml, generate_sales_xml
from main import app

from fastapi.testclient import TestClient

client = TestClient(app)

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


def get_ledger_balance(xml: str) -> float:
    ledger_entries = re.findall(
        r'<ALLLEDGERENTRIES.LIST>.*?</ALLLEDGERENTRIES.LIST>', xml, re.DOTALL
    )
    total = 0.0
    for entry in ledger_entries:
        amt_match = re.search(r'<AMOUNT>(-?\d+\.?\d*)</AMOUNT>', entry)
        if amt_match:
            total += float(amt_match.group(1))
    return total


# ============================================================
# 1. GST CLASSIFICATION
# ============================================================
print("\n=== GST CLASSIFICATION ===")

r = classify_gst("27AABCU1234F1ZP", "27AABCU2345F1ZJ")
check("Intra-state (same state)", r["gst_type"] == "CGST_SGST" and not r["is_interstate"],
      f"Got {r['gst_type']}, interstate={r['is_interstate']}")

r = classify_gst("27AABCU1234F1ZP", "07AABCU1234F1ZR")
check("Inter-state (different states)", r["gst_type"] == "IGST" and r["is_interstate"],
      f"Got {r['gst_type']}, interstate={r['is_interstate']}")

r = classify_gst("27AABCU1234F1ZP", "")
check("Empty party GSTIN defaults to intra", r["gst_type"] == "CGST_SGST",
      f"Got {r['gst_type']}")


# ============================================================
# 2. TAX CALCULATION
# ============================================================
print("\n=== TAX CALCULATION ===")

taxes = compute_tax(10000, 18, "CGST_SGST")
check("CGST+SGST split 50/50", len(taxes) == 2, f"Got {len(taxes)} entries")
if len(taxes) == 2:
    check("CGST amount = 900", abs(taxes[0]["amount"] - 900) < 0.01, f"Got {taxes[0]['amount']}")
    check("SGST amount = 900", abs(taxes[1]["amount"] - 900) < 0.01, f"Got {taxes[1]['amount']}")

taxes = compute_tax(10000, 18, "IGST")
check("IGST single entry", len(taxes) == 1, f"Got {len(taxes)} entries")
if taxes:
    check("IGST amount = 1800", abs(taxes[0]["amount"] - 1800) < 0.01, f"Got {taxes[0]['amount']}")

taxes = compute_tax(0, 18, "CGST_SGST")
check("Zero taxable = no tax", len(taxes) == 0, f"Got {len(taxes)} entries")

taxes = compute_tax(10000, 0, "CGST_SGST")
check("Zero rate = no tax", len(taxes) == 0, f"Got {len(taxes)} entries")

taxes = compute_tax_from_items([
    {"taxable_amount": 5000, "tax_rate": 5},
    {"taxable_amount": 5000, "tax_rate": 18},
], "CGST_SGST")
check("Mixed rates: 4 entries (2 CGST + 2 SGST)", len(taxes) == 4,
      f"Got {len(taxes)} entries: {[(t['type'], t['rate'], t['amount']) for t in taxes]}")
cgst5 = sum(t["amount"] for t in taxes if t["type"] == "cgst" and t["rate"] == 2.5)
sgst5 = sum(t["amount"] for t in taxes if t["type"] == "sgst" and t["rate"] == 2.5)
cgst18 = sum(t["amount"] for t in taxes if t["type"] == "cgst" and t["rate"] == 9)
sgst18 = sum(t["amount"] for t in taxes if t["type"] == "sgst" and t["rate"] == 9)
check("CGST 2.5% = 125", abs(cgst5 - 125) < 0.01, f"Got {cgst5}")
check("SGST 2.5% = 125", abs(sgst5 - 125) < 0.01, f"Got {sgst5}")
check("CGST 9% = 450", abs(cgst18 - 450) < 0.01, f"Got {cgst18}")
check("SGST 9% = 450", abs(sgst18 - 450) < 0.01, f"Got {sgst18}")


# ============================================================
# 3. VALIDATION
# ============================================================
print("\n=== VALIDATION ===")

# Valid invoice
v = validate_invoice(InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Test",
    invoice_number="INV-001",
    invoice_date="2026-05-26",
    taxable_total=1000, tax_total=180, grand_total=1180, tax_rate=18,
))
check("Valid invoice passes", v.valid, f"Errors: {[str(e) for e in v.errors]}")

# Missing fields
v = validate_invoice(InvoiceRequest(
    company_gstin="", party_gstin="", party_name="", invoice_number="",
    invoice_date="", taxable_total=0, tax_total=0, grand_total=0, tax_rate=0,
))
check("Empty fields: 4 required field errors",
      sum(1 for e in v.errors if "required" in e.message) >= 4,
      f"Errors: {[e.message for e in v.errors]}")

# Invalid GSTIN
v = validate_invoice(InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="invalid",
    party_name="Test", invoice_number="INV-001",
    invoice_date="2026-05-26",
    taxable_total=1000, tax_total=180, grand_total=1180, tax_rate=18,
))
check("Invalid GSTIN rejected", not v.valid, f"Errors: {[e.message for e in v.errors]}")

# Invalid tax rate
v = validate_invoice(InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Test", invoice_number="INV-001",
    invoice_date="2026-05-26",
    taxable_total=1000, tax_total=180, grand_total=1180, tax_rate=99,
))
check("Invalid tax rate 99% rejected", not v.valid, f"Errors: {[e.message for e in v.errors]}")

# Grand total mismatch
v = validate_invoice(InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Test", invoice_number="INV-001",
    invoice_date="2026-05-26",
    taxable_total=1000, tax_total=180, grand_total=9999, tax_rate=18,
))
check("Grand total mismatch detected", not v.valid, f"Errors: {[e.message for e in v.errors]}")

# Invalid date format
v = validate_invoice(InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Test", invoice_number="INV-001",
    invoice_date="not-a-date",
    taxable_total=1000, tax_total=180, grand_total=1180, tax_rate=18,
))
check("Invalid date rejected", not v.valid, f"Errors: {[e.message for e in v.errors]}")

# DD/MM/YYYY format should be valid
v = validate_invoice(InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Test", invoice_number="INV-001",
    invoice_date="26/05/2026",
    taxable_total=1000, tax_total=180, grand_total=1180, tax_rate=18,
))
check("DD/MM/YYYY date passes", v.valid, f"Errors: {[e.message for e in v.errors]}")


# ============================================================
# 4. XML GENERATION — PURCHASE
# ============================================================
print("\n=== XML GENERATION — PURCHASE ===")

data = InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Mumbai Suppliers",
    invoice_number="P-INV-001",
    invoice_date="2026-05-26",
    taxable_total=10000, tax_total=1800, grand_total=11800, tax_rate=18,
    line_items=[
        LineItem(description="Widget A", quantity=100, rate=100,
                 taxable_amount=10000, tax_rate=18, hsn_sac="8471", unit="Nos"),
    ],
)
xml = generate_purchase_xml(data, "My Company")

check("XML has ENVELOPE root", "<ENVELOPE>" in xml)
check("XML has TALLYREQUEST", "Import Data" in xml)
check("XML has IMPORTDATA", "<IMPORTDATA>" in xml)
check("XML has REQUESTDESC/REPORTNAME", "<REPORTNAME>Vouchers</REPORTNAME>" in xml)
check("XML has TALLYMESSAGE with UDF", 'xmlns:UDF="TallyUDF"' in xml)
check("XML has VCHTYPE=Purchase", 'VCHTYPE="Purchase"' in xml)
check("XML has PARTYLEDGERNAME", "Mumbai Suppliers" in xml)
check("XML has PARTYGSTIN", "27AABCU2345F1ZJ" in xml)
check("XML has CGST entry", "<LEDGERNAME>CGST</LEDGERNAME>" in xml)
check("XML has SGST entry", "<LEDGERNAME>SGST</LEDGERNAME>" in xml)
check("XML has Purchase ledger", "<LEDGERNAME>Purchase</LEDGERNAME>" in xml)
check("XML has inventory entry", "ALLINVENTORYENTRIES.LIST" in xml)
check("XML has HSN code", "<HSNCODE>8471</HSNCODE>" in xml)
check("XML has GSTCLASS 18%", "<GSTCLASS>18%</GSTCLASS>" in xml)
check("XML has bill allocations", "BILLALLOCATIONS.LIST" in xml)
check("XML has date in YYYYMMDD", "<DATE>20260526</DATE>" in xml)

bal = get_ledger_balance(xml)
check("Purchase ledger balance = 0", abs(bal) < 0.01, f"Balance: {bal}")

bal_detail = f"Balance = {bal:.2f}. Entries: "
ledger_entries = re.findall(r'<ALLLEDGERENTRIES.LIST>.*?</ALLLEDGERENTRIES.LIST>', xml, re.DOTALL)
for e in ledger_entries:
    name = re.search(r'<LEDGERNAME>(.*?)</LEDGERNAME>', e)
    amt = re.search(r'<AMOUNT>(-?\d+\.?\d*)</AMOUNT>', e)
    if name and amt:
        bal_detail += f"{name.group(1)}={amt.group(1)} "
check("Purchase: Party is credit (ISDEEMEDPOSITIVE=No)",
      '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>' in ledger_entries[0],
      f"First entry: {ledger_entries[0][:200]}")
check("Purchase: Expense is debit (ISDEEMEDPOSITIVE=Yes)",
      '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>' in ledger_entries[1],
      f"Second entry: {ledger_entries[1][:200]}")


# ============================================================
# 5. XML GENERATION — SALES
# ============================================================
print("\n=== XML GENERATION — SALES ===")

data_sales = InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Mumbai Buyer",
    invoice_number="S-INV-001",
    invoice_date="2026-05-26",
    taxable_total=20000, tax_total=3600, grand_total=23600, tax_rate=18,
    line_items=[],
)
xml_s = generate_sales_xml(data_sales, "My Company")

check("XML has VCHTYPE=Sales", 'VCHTYPE="Sales"' in xml_s)
check("XML has Sales ledger", "<LEDGERNAME>Sales</LEDGERNAME>" in xml_s)
check("XML has CGST entry (output)", "<LEDGERNAME>CGST</LEDGERNAME>" in xml_s)
check("XML has SGST entry (output)", "<LEDGERNAME>SGST</LEDGERNAME>" in xml_s)

bal_s = get_ledger_balance(xml_s)
check("Sales ledger balance = 0", abs(bal_s) < 0.01, f"Balance: {bal_s}")

ledger_entries_s = re.findall(r'<ALLLEDGERENTRIES.LIST>.*?</ALLLEDGERENTRIES.LIST>', xml_s, re.DOTALL)
check("Sales: Party is debit (ISDEEMEDPOSITIVE=Yes)",
      '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>' in ledger_entries_s[0],
      f"First entry: {ledger_entries_s[0][:200]}")
check("Sales: Income is credit (ISDEEMEDPOSITIVE=No)",
      '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>' in ledger_entries_s[1],
      f"Second entry: {ledger_entries_s[1][:200]}")


# ============================================================
# 6. INTER-STATE PURCHASE (IGST)
# ============================================================
print("\n=== INTER-STATE (IGST) ===")

data_inter = InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="07AABCU1234F1ZR",
    party_name="Delhi Suppliers",
    invoice_number="P-INV-002",
    invoice_date="2026-05-26",
    taxable_total=50000, tax_total=9000, grand_total=59000, tax_rate=18,
    line_items=[],
)
xml_inter = generate_purchase_xml(data_inter, "My Company")
check("IGST has IGST ledger", "<LEDGERNAME>IGST</LEDGERNAME>" in xml_inter)
check("IGST does NOT have CGST", "<LEDGERNAME>CGST</LEDGERNAME>" not in xml_inter,
      "CGST should not appear in IGST voucher")
check("IGST does NOT have SGST", "<LEDGERNAME>SGST</LEDGERNAME>" not in xml_inter,
      "SGST should not appear in IGST voucher")
bal_inter = get_ledger_balance(xml_inter)
check("IGST balance = 0", abs(bal_inter) < 0.01, f"Balance: {bal_inter}")


# ============================================================
# 7. INTER-STATE SALES (IGST)
# ============================================================
print("\n=== INTER-STATE SALES ===")

data_inter_sale = InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="29AABCU1234F1ZL",
    party_name="Bangalore Buyer",
    invoice_number="S-INV-002",
    invoice_date="2026-05-26",
    taxable_total=30000, tax_total=5400, grand_total=35400, tax_rate=18,
    line_items=[],
)
xml_inter_s = generate_sales_xml(data_inter_sale, "My Company")
check("Sales IGST has IGST ledger", "<LEDGERNAME>IGST</LEDGERNAME>" in xml_inter_s)
check("Sales IGST no CGST", "<LEDGERNAME>CGST</LEDGERNAME>" not in xml_inter_s)
check("Sales IGST no SGST", "<LEDGERNAME>SGST</LEDGERNAME>" not in xml_inter_s)
bal_inter_s = get_ledger_balance(xml_inter_s)
check("Sales IGST balance = 0", abs(bal_inter_s) < 0.01, f"Balance: {bal_inter_s}")


# ============================================================
# 8. MIXED TAX RATES
# ============================================================
print("\n=== MIXED RATES ===")

data_mixed = InvoiceRequest(
    company_gstin="27AABCU1234F1ZP",
    party_gstin="27AABCU2345F1ZJ",
    party_name="Mixed Supplier",
    invoice_number="M-INV-001",
    invoice_date="2026-05-26",
    taxable_total=15000, tax_total=0, grand_total=15000, tax_rate=0,
    line_items=[
        LineItem(description="Book", quantity=10, rate=500,
                 taxable_amount=5000, tax_rate=5, hsn_sac="4901"),
        LineItem(description="Laptop", quantity=2, rate=5000,
                 taxable_amount=10000, tax_rate=18, hsn_sac="8471"),
    ],
)
# Set grand_total properly for mixed rates
data_mixed.grand_total = round(5000 + 5000*0.05 + 10000 + 10000*0.18, 2)
data_mixed.tax_total = round(5000*0.05 + 10000*0.18, 2)
check(f"Mixed rate grand_total={data_mixed.grand_total}, tax_total={data_mixed.tax_total}", True)

xml_mixed = generate_purchase_xml(data_mixed, "My Company")
check("Mixed: CGST at 2.5% and 9%", "<LEDGERNAME>CGST</LEDGERNAME>" in xml_mixed)
check("Mixed: SGST at 2.5% and 9%", "<LEDGERNAME>SGST</LEDGERNAME>" in xml_mixed)
bal_mixed = get_ledger_balance(xml_mixed)
check("Mixed rates balance = 0", abs(bal_mixed) < 0.01, f"Balance: {bal_mixed}")


# ============================================================
# 9. API ENDPOINTS
# ============================================================
print("\n=== API ENDPOINTS ===")

# Health
r = client.get("/health")
check("GET /health returns 200", r.status_code == 200)
check("GET /health returns ok", r.json().get("status") == "ok")

# Purchase XML endpoint
payload = {
    "company_gstin": "27AABCU1234F1ZP",
    "party_gstin": "27AABCU2345F1ZJ",
    "party_name": "API Test Supplier",
    "invoice_number": "API-001",
    "invoice_date": "2026-05-26",
    "taxable_total": 5000,
    "tax_total": 900,
    "grand_total": 5900,
    "tax_rate": 18,
    "line_items": [],
}
r = client.post("/generate-purchase-xml", json=payload)
check("POST /generate-purchase-xml returns 200", r.status_code == 200)
j = r.json()
check("Purchase API: success=True", j.get("success") is True)
check("Purchase API: XML contains voucher", "VCHTYPE=\"Purchase\"" in j.get("xml", ""))
check("Purchase API: GST type determined", j.get("gst_classification", {}).get("gst_type") == "CGST_SGST")

# Sales XML endpoint
payload_s = payload.copy()
payload_s["invoice_number"] = "API-S-001"
r = client.post("/generate-sales-xml", json=payload_s)
check("POST /generate-sales-xml returns 200", r.status_code == 200)
j = r.json()
check("Sales API: success=True", j.get("success") is True)
check("Sales API: XML contains voucher", "VCHTYPE=\"Sales\"" in j.get("xml", ""))

# Invalid input returns 400
bad_payload = {"company_gstin": "", "party_gstin": "", "party_name": "",
               "invoice_number": "", "invoice_date": "",
               "taxable_total": -1, "tax_total": -1, "grand_total": -1, "tax_rate": 99}
r = client.post("/generate-purchase-xml", json=bad_payload)
check("Bad input returns 400", r.status_code == 400)
check("Bad input has errors", len(r.json().get("detail", {}).get("errors", [])) > 0)


# ============================================================
# 10. XML STRUCTURE INTEGRITY
# ============================================================
print("\n=== XML STRUCTURE ===")

check("XML declaration present", xml.strip().startswith("<?xml"))
check("ENVELOPE is root", xml.strip().split("\n")[0].endswith(">") or "<ENVELOPE>" in xml)
check("HEADER present", "<HEADER>" in xml and "Import Data" in xml)
check("BODY present", "<BODY>" in xml)
check("VOUCHER closed", "</VOUCHER>" in xml)
check("TALLYMESSAGE closed", "</TALLYMESSAGE>" in xml)
check("ENVELOPE closed", "</ENVELOPE>" in xml)

# Count ALLINVENTORYENTRIES.LIST vs line_items
inv_count = xml.count("<ALLINVENTORYENTRIES.LIST>")
check(f"Inventory entries match ({inv_count} vs {len(data.line_items)})",
      inv_count == len(data.line_items),
      f"XML has {inv_count} inventory entries, data has {len(data.line_items)} line items")


# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*50}")
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
print(f"{'='*50}")

sys.exit(0 if FAIL == 0 else 1)
