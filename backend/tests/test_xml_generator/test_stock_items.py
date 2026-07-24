"""XML generator: stock item creation for goods invoices."""

import re
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType


def _has_stock_group(xml: str) -> bool:
    return "<STOCKGROUP" in xml


def _has_stock_item(xml: str) -> bool:
    return "<STOCKITEM" in xml


def _stock_item_names(xml: str) -> list[str]:
    return re.findall(r"<NAME>([^<]+)</NAME>", xml)


class TestStockItemCreation:
    """Goods invoices should create stock items when auto_create_stock_items is True."""

    def test_stock_group_created_for_goods(self, generator):
        inv = StandardizedInvoice(
            vendor_name="Vendor",
            vendor_gstin="29AACCT3705E1ZJ",
            buyer_gstin="29AACCT3705E1ZJ",
            invoice_number="STK-001",
            invoice_date="2025-01-01",
            total_taxable_value=2000.0,
            total_tax=360.0,
            total_amount=2360.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[
                LineItem(description="Product A", taxable_value=1000.0, tax_rate=18, hsn_sac="8471", quantity=2, rate=500),
                LineItem(description="Product B", taxable_value=1000.0, tax_rate=18, hsn_sac="8473", quantity=1, rate=1000),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=180.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=180.0, type="SGST"),
            ],
            auto_create_stock_items=True,
            is_service=False,
        )
        xml = generator.generate(inv)
        assert _has_stock_group(xml), "STOCKGROUP should be created for goods"
        assert _has_stock_item(xml), "STOCKITEM should be created for goods"
        names = _stock_item_names(xml)
        assert "Product A" in names, f"Product A missing in stock items: {names}"
        assert "Product B" in names, f"Product B missing in stock items: {names}"

    def test_stock_items_have_hsn(self, generator):
        inv = StandardizedInvoice(
            vendor_name="Vendor",
            vendor_gstin="29AACCT3705E1ZJ",
            buyer_gstin="29AACCT3705E1ZJ",
            invoice_number="STK-002",
            invoice_date="2025-01-01",
            total_taxable_value=1000.0,
            total_tax=180.0,
            total_amount=1180.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[
                LineItem(description="Widget", taxable_value=1000.0, tax_rate=18, hsn_sac="8471", quantity=1, rate=1000),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=90.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=90.0, type="SGST"),
            ],
            auto_create_stock_items=True,
            is_service=False,
        )
        xml = generator.generate(inv)
        # Stock item should reference the HSN
        assert "8471" in xml, "HSN code missing in stock item XML"

    def test_service_invoice_skips_stock_items(self, generator):
        """Service invoices must not create stock items even if flag is set."""
        inv = StandardizedInvoice(
            vendor_name="Consultant",
            vendor_gstin="29AACCT3705E1ZJ",
            buyer_gstin="29AACCT3705E1ZJ",
            invoice_number="SVC-001",
            invoice_date="2025-01-01",
            total_taxable_value=10000.0,
            total_tax=1800.0,
            total_amount=11800.0,
            voucher_type=VoucherType.PURCHASE,
            gst_type=GSTType.CGST_SGST,
            line_items=[
                LineItem(description="Consulting Services", taxable_value=10000.0, tax_rate=18, is_service=True),
            ],
            taxes=[
                TaxEntry(name="CGST", rate=9, amount=900.0, type="CGST"),
                TaxEntry(name="SGST", rate=9, amount=900.0, type="SGST"),
            ],
            auto_create_stock_items=True,
            is_service=True,
        )
        xml = generator.generate(inv)
        assert not _has_stock_group(xml), "STOCKGROUP should not be created for services"
        assert not _has_stock_item(xml), "STOCKITEM should not be created for services"
