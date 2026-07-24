"""Debug: inspect generated XML structure."""
import sys
import re
sys.path.insert(0, '.')
from schemas import StandardizedInvoice, LineItem, TaxEntry
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig
from gst_engine import _compute_gstin_checksum

gstin = '29AACCT3705E1Z' + _compute_gstin_checksum('29AACCT3705E1Z')
cfg = CompanyConfig(user_config={'company_state_code': '29', 'company_name': 'Test Co'})
gen = TallyXmlGenerator(cfg)
inv = StandardizedInvoice(
    invoice_number='INV-001', invoice_date='2026-06-15',
    vendor_name='Test Supplier', vendor_gstin=gstin, buyer_gstin=gstin,
    place_of_supply='29', is_service=False,
    total_taxable_value=1000.0, total_tax=180.0, total_amount=1180.0,
    line_items=[LineItem(description='Widget', quantity=10, rate=100.0, taxable_value=1000.0, hsn_sac='84713000', unit='Nos')],
    taxes=[TaxEntry(name='CGST', rate=9.0, amount=90.0, type='cgst'), TaxEntry(name='SGST', rate=9.0, amount=90.0, type='sgst')],
)
xml_str = gen.generate(inv)

print("=== SVCURRENTCOMPANY ===")
if '<SVCURRENTCOMPANY>' in xml_str:
    m = re.search(r'<SVCURRENTCOMPANY>([^<]+)', xml_str)
    print('Found:', m.group(1) if m else 'empty')
else:
    print('NOT FOUND')

print("\n=== LEDGER masters ===")
ledgers = re.findall(r'<LEDGER[^>]+NAME="([^"]+)"', xml_str)
for l in ledgers:
    print(f'  {l}')

print("\n=== LEDGERNAME refs in voucher ===")
refs = re.findall(r'<LEDGERNAME>([^<]+)</LEDGERNAME>', xml_str)
for r in set(refs):
    print(f'  {r}')

print("\n=== DATES ===")
dates = re.findall(r'<DATE>(\d+)</DATE>', xml_str)
for d in dates:
    print(f'  {d}')

print("\n=== STOCKITEM masters ===")
stocks = re.findall(r'<STOCKITEM[^>]+NAME="([^"]+)"', xml_str)
for s in stocks:
    print(f'  {s}')

print("\n=== STOCKITEMNAME refs ===")
srefs = re.findall(r'<STOCKITEMNAME>([^<]+)</STOCKITEMNAME>', xml_str)
for s in set(srefs):
    print(f'  {s}')
