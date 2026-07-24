import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from schemas import StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry
from xml_generator import TallyXmlGenerator
from company_config import CompanyConfig

config = CompanyConfig()
config.company_name = "My Company"
config.state_code = "27"
gen = TallyXmlGenerator(config)

outdir = os.path.join(os.path.dirname(__file__), "..", "sample_xml")
os.makedirs(outdir, exist_ok=True)

def save(name, xml):
    path = os.path.join(outdir, name)
    with open(path, "w") as f:
        f.write(xml)
    print(f"Generated {path}")

# Sample 1: Purchase of Goods (Intra-state, 18% GST)
inv1 = StandardizedInvoice(
    invoice_number="PUR-2024-001",
    invoice_date="2024-01-15",
    vendor_name="ABC Traders",
    vendor_gstin="27AABCU1234F1ZP",
    vendor_address="Mumbai, Maharashtra",
    voucher_type=VoucherType.PURCHASE,
    gst_type=GSTType.CGST_SGST,
    is_service=False,
    total_taxable_value=100000.0,
    total_tax=18000.0,
    total_amount=118000.0,
    line_items=[
        LineItem(description="Steel Rods 12mm", quantity=500, rate=200, taxable_value=100000, tax_rate=18, hsn_sac="7214", unit="Kgs"),
    ],
    taxes=[
        TaxEntry(name="Input CGST 9%", rate=9, amount=9000, type="cgst"),
        TaxEntry(name="Input SGST 9%", rate=9, amount=9000, type="sgst"),
    ],
)
save("purchase_goods_intra_18.xml", gen.generate(inv1))

# Sample 2: Service Invoice (Professional Fees)
inv2 = StandardizedInvoice(
    invoice_number="SVC-2024-001",
    invoice_date="2024-02-20",
    vendor_name="XYZ Consulting LLP",
    vendor_gstin="27AABCU1234F1ZP",
    vendor_address="Pune, Maharashtra",
    voucher_type=VoucherType.PURCHASE,
    gst_type=GSTType.CGST_SGST,
    is_service=True,
    total_taxable_value=50000.0,
    total_tax=9000.0,
    total_amount=59000.0,
    line_items=[
        LineItem(description="Professional Consulting Services", quantity=1, rate=50000, taxable_value=50000, tax_rate=18, is_service=True),
    ],
    taxes=[
        TaxEntry(name="Input CGST 9%", rate=9, amount=4500, type="cgst"),
        TaxEntry(name="Input SGST 9%", rate=9, amount=4500, type="sgst"),
    ],
)
save("service_invoice_intra_18.xml", gen.generate(inv2))

# Sample 3: Inter-state Purchase with IGST
inv3 = StandardizedInvoice(
    invoice_number="IGST-2024-001",
    invoice_date="2024-03-10",
    vendor_name="Karnataka Industrial Supplies",
    vendor_gstin="29AABCU1234F1ZL",
    vendor_address="Bengaluru, Karnataka",
    voucher_type=VoucherType.PURCHASE,
    gst_type=GSTType.IGST,
    is_interstate=True,
    is_service=False,
    total_taxable_value=75000.0,
    total_tax=13500.0,
    total_amount=88500.0,
    line_items=[
        LineItem(description="Industrial Machinery", quantity=1, rate=75000, taxable_value=75000, tax_rate=18, hsn_sac="8479", unit="Nos"),
    ],
    taxes=[
        TaxEntry(name="Input IGST 18%", rate=18, amount=13500, type="igst"),
    ],
)
save("purchase_interstate_igst.xml", gen.generate(inv3))

# Sample 4: Mixed GST Rates (5% + 12%)
inv4 = StandardizedInvoice(
    invoice_number="MIX-2024-001",
    invoice_date="2024-04-05",
    vendor_name="MultiRate Supplies",
    vendor_gstin="27AABCU1234F1ZP",
    voucher_type=VoucherType.PURCHASE,
    gst_type=GSTType.CGST_SGST,
    is_service=False,
    total_taxable_value=25000.0,
    total_tax=2100.0,
    total_amount=27100.0,
    line_items=[
        LineItem(description="Essential Food Item", quantity=100, rate=50, taxable_value=5000, tax_rate=5, hsn_sac="1905", unit="Kgs"),
        LineItem(description="Electronic Gadget", quantity=10, rate=2000, taxable_value=20000, tax_rate=12, hsn_sac="8517", unit="Nos"),
    ],
    taxes=[
        TaxEntry(name="Input CGST 2.5%", rate=2.5, amount=125, type="cgst"),
        TaxEntry(name="Input SGST 2.5%", rate=2.5, amount=125, type="sgst"),
        TaxEntry(name="Input CGST 6%", rate=6, amount=1200, type="cgst"),
        TaxEntry(name="Input SGST 6%", rate=6, amount=1200, type="sgst"),
    ],
)
save("purchase_mixed_rates.xml", gen.generate(inv4))

# Sample 5: TDS Deduction
inv5 = StandardizedInvoice(
    invoice_number="TDS-2024-001",
    invoice_date="2024-05-15",
    vendor_name="Legal Associates",
    vendor_gstin="27AABCU1234F1ZP",
    voucher_type=VoucherType.PURCHASE,
    gst_type=GSTType.CGST_SGST,
    is_service=True,
    total_taxable_value=100000.0,
    total_tax=18000.0,
    total_amount=118000.0,
    tds_amount=10000.0,
    tds_rate=10.0,
    line_items=[
        LineItem(description="Legal Retainer Fees", quantity=1, rate=100000, taxable_value=100000, tax_rate=18, is_service=True),
    ],
    taxes=[
        TaxEntry(name="Input CGST 9%", rate=9, amount=9000, type="cgst"),
        TaxEntry(name="Input SGST 9%", rate=9, amount=9000, type="sgst"),
    ],
)
save("purchase_with_tds.xml", gen.generate(inv5))

# Sample 6: Credit Note
inv6 = StandardizedInvoice(
    invoice_number="CN-2024-001",
    invoice_date="2024-06-01",
    vendor_name="Returns Vendor",
    vendor_gstin="27AABCU1234F1ZP",
    voucher_type=VoucherType.CREDIT_NOTE,
    gst_type=GSTType.CGST_SGST,
    is_service=False,
    total_taxable_value=20000.0,
    total_tax=3600.0,
    total_amount=23600.0,
    line_items=[
        LineItem(description="Returned Goods", quantity=10, rate=2000, taxable_value=20000, tax_rate=18, hsn_sac="8471", unit="Nos"),
    ],
    taxes=[
        TaxEntry(name="Input CGST 9%", rate=9, amount=1800, type="cgst"),
        TaxEntry(name="Input SGST 9%", rate=9, amount=1800, type="sgst"),
    ],
)
save("credit_note.xml", gen.generate(inv6))

print("\nAll sample XML files generated successfully!")
