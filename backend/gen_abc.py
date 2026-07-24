import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xml_generator import TallyXmlGenerator, CompanyConfig
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from gst_engine import _compute_gstin_checksum

# Company config matches ABC Electronics (MH)
config = CompanyConfig(user_config={
    "company_name": "ABC Electronics",
    "company_gstin": "27AABCU1234D1Z" + _compute_gstin_checksum("27AABCU1234D1Z"),
    "company_state_code": "27",
})

generator = TallyXmlGenerator(config, include_ledgers=True)

inv = StandardizedInvoice(
    voucher_type=VoucherType.PURCHASE,
    invoice_number="INV-2025-001",
    invoice_date="2025-07-15",
    vendor_name="ABC Electronics",
    vendor_gstin="27AABCU1234D1Z" + _compute_gstin_checksum("27AABCU1234D1Z"),
    vendor_address="123, Electronics Market, Mumbai - 400001",
    buyer_name="M/s. Tech Solutions Pvt Ltd",
    buyer_gstin="29XXXXX1234D1Z1",
    buyer_address="Bangalore, Karnataka",
    place_of_supply="Karnataka",
    gst_type=GSTType.IGST,
    is_interstate=True,
    is_service=False,
    total_taxable_value=233500.00,
    total_tax=42030.00,
    total_amount=275530.00,
    auto_create_stock_items=True,
    line_items=[
        LineItem(description="Laptop - Dell XPS", hsn_sac="847130", quantity=2, rate=85000, taxable_value=170000.00, tax_rate=18, unit="Nos"),
        LineItem(description="Monitor - 24 inch", hsn_sac="852852", quantity=3, rate=15000, taxable_value=45000.00, tax_rate=18, unit="Nos"),
        LineItem(description="Keyboard - Wireless", hsn_sac="847160", quantity=5, rate=2500, taxable_value=12500.00, tax_rate=18, unit="Nos"),
        LineItem(description="Software - Windows", hsn_sac="852351", quantity=5, rate=1200, taxable_value=6000.00, tax_rate=18, unit="Nos"),
    ],
    taxes=[
        TaxEntry(name="Input IGST 18%", rate=18, amount=42030.00, type="igst", is_input=True),
    ],
)

xml = generator.generate(inv)
print(xml)
