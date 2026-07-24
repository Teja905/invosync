"""Tests for GST filing preparation engine."""

import pytest
from gst_filing_prep import (
    generate_gstr1,
    generate_gstr3b,
    GSTR1B2BEntry,
    GSTR1HSNEntry,
)


class TestGSTR1Generation:
    def _make_sales_invoice(self, **overrides):
        base = {
            "extracted": {
                "vendor_gstin": "27AABCU1234F1ZP",
                "buyer_gstin": "27AABCU9876K1ZQ",
                "invoice_number": "INV-001",
                "invoice_date": "2024-04-15",
                "total_amount": 118000,
                "total_taxable_value": 100000,
                "total_tax": 18000,
                "voucher_type": "Sales",
                "place_of_supply": "27-Maharashtra",
                "reverse_charge": False,
                "taxes": [
                    {"type": "cgst", "amount": 9000, "rate": 9},
                    {"type": "sgst", "amount": 9000, "rate": 9},
                ],
                "line_items": [
                    {"description": "Product A", "hsn_sac": "8471", "quantity": 10, "rate": 10000, "taxable_value": 100000, "tax_rate": 18},
                ],
            },
            "status": "exported",
        }
        base.update(overrides)
        return base

    def test_b2b_entry_count(self):
        invoices = [self._make_sales_invoice() for _ in range(3)]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        assert len(gstr1.b2b) == 3

    def test_b2b_gstin(self):
        invoices = [self._make_sales_invoice()]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        assert gstr1.b2b[0].gstin == "27AABCU9876K1ZQ"

    def test_b2b_amount(self):
        invoices = [self._make_sales_invoice()]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        assert gstr1.b2b[0].invoice_value == 118000

    def test_excludes_purchase_invoices(self):
        inv = self._make_sales_invoice()
        inv["extracted"]["voucher_type"] = "Purchase"
        gstr1 = generate_gstr1([inv], "04-2024", "27AABCU1234F1ZP")
        assert len(gstr1.b2b) == 0

    def test_hsn_summary(self):
        invoices = [self._make_sales_invoice()]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        assert len(gstr1.hsn_summary) == 1
        assert gstr1.hsn_summary[0].hsn_code == "8471"
        assert gstr1.hsn_summary[0].total_quantity == 10

    def test_tax_totals(self):
        invoices = [self._make_sales_invoice()]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        assert gstr1.total_cgst == 9000
        assert gstr1.total_sgst == 9000
        assert gstr1.total_taxable == 100000

    def test_document_summary(self):
        invoices = [self._make_sales_invoice()]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        assert gstr1.document_summary.total_documents == 1
        assert gstr1.document_summary.total_cancelled == 0

    def test_cancelled_invoice(self):
        inv = self._make_sales_invoice()
        inv["status"] = "cancelled"
        gstr1 = generate_gstr1([inv], "04-2024", "27AABCU1234F1ZP")
        assert len(gstr1.b2b) == 0
        assert gstr1.document_summary.total_cancelled == 1

    def test_empty_invoices(self):
        gstr1 = generate_gstr1([], "04-2024", "27AABCU1234F1ZP")
        assert len(gstr1.b2b) == 0
        assert gstr1.total_taxable == 0

    def test_serialization(self):
        invoices = [self._make_sales_invoice()]
        gstr1 = generate_gstr1(invoices, "04-2024", "27AABCU1234F1ZP")
        d = gstr1.to_dict()
        assert "period" in d
        assert "b2b" in d
        assert "hsn_summary" in d
        assert "summary" in d


class TestGSTR3BGeneration:
    def _make_sales_invoice(self):
        return {
            "extracted": {
                "voucher_type": "Sales",
                "total_amount": 118000,
                "total_taxable_value": 100000,
                "total_tax": 18000,
                "taxes": [
                    {"type": "cgst", "amount": 9000, "rate": 9},
                    {"type": "sgst", "amount": 9000, "rate": 9},
                ],
            },
            "status": "exported",
        }

    def test_outward_supplies(self):
        invoices = [self._make_sales_invoice()]
        gstr3b = generate_gstr3b(invoices, [], "04-2024", "27AABCU1234F1ZP")
        assert gstr3b.taxable_outward == 100000
        assert gstr3b.total_outward == 118000

    def test_tax_payable(self):
        invoices = [self._make_sales_invoice()]
        gstr3b = generate_gstr3b(invoices, [], "04-2024", "27AABCU1234F1ZP")
        assert gstr3b.cgst_payable == 9000
        assert gstr3b.sgst_payable == 9000

    def test_itc_from_journal_lines(self):
        journal_lines = [
            {"ledger": "Input CGST @ 9%", "debit": 9000, "credit": 0},
            {"ledger": "Input SGST @ 9%", "debit": 9000, "credit": 0},
        ]
        gstr3b = generate_gstr3b([], journal_lines, "04-2024", "27AABCU1234F1ZP")
        assert gstr3b.itc_cgst == 9000
        assert gstr3b.itc_sgst == 9000
        assert gstr3b.total_itc == 18000

    def test_empty(self):
        gstr3b = generate_gstr3b([], [], "04-2024", "27AABCU1234F1ZP")
        assert gstr3b.taxable_outward == 0
        assert gstr3b.total_itc == 0

    def test_serialization(self):
        gstr3b = generate_gstr3b([], [], "04-2024", "27AABCU1234F1ZP")
        d = gstr3b.to_dict()
        assert "table_3_1" in d
        assert "tax_payable" in d
        assert "table_4_itc" in d
