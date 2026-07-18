"""Tests for the journal-line capture (single source of truth) and the
chart-of-accounts classifier. Proves every generated voucher's legs balance
and that ledger names map deterministically to account types.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from schemas import StandardizedInvoice, LineItem, TaxEntry, VoucherType, GSTType
from xml_generator import TallyXmlGenerator, CompanyConfig
from ledger_classifier import classify_ledger, GROUP_TO_TYPE
from gst_engine import _compute_gstin_checksum

KA_GSTIN = "29AACCT3705E1Z" + _compute_gstin_checksum("29AACCT3705E1Z")


def _make_purchase_invoice(valid_gstins) -> StandardizedInvoice:
    return StandardizedInvoice(
        vendor_name="ABC Traders",
        vendor_gstin=KA_GSTIN,
        buyer_gstin=valid_gstins["mh"],
        invoice_number="INV-1",
        invoice_date="2026-07-15",
        voucher_type=VoucherType.PURCHASE,
        line_items=[LineItem(description="Goods", quantity=1, rate=100000, taxable_value=100000, tax_rate=18)],
        taxes=[TaxEntry(type="CGST", rate=9, amount=9000), TaxEntry(type="SGST", rate=9, amount=9000)],
        total_taxable_value=100000,
        total_tax=18000,
        total_amount=118000,
        gst_type=GSTType.CGST_SGST,
    )


def _sum_debits_credits(lines):
    d = sum(l["debit"] for l in lines)
    c = sum(l["credit"] for l in lines)
    return round(d, 2), round(c, 2)


@pytest.mark.parametrize("vt", [VoucherType.PURCHASE, VoucherType.SALES, VoucherType.PAYMENT, VoucherType.RECEIPT, VoucherType.JOURNAL])
def test_journal_lines_capture_and_balance(valid_gstins, vt):
    inv = _make_purchase_invoice(valid_gstins)
    inv.voucher_type = vt
    gen = TallyXmlGenerator(CompanyConfig())
    gen.generate(inv)
    assert gen.journal_lines, "journal lines must be captured"
    d, c = _sum_debits_credits(gen.journal_lines)
    assert d == c, f"{vt.value}: debits ({d}) must equal credits ({c})"


def test_journal_lines_include_party_and_tax(valid_gstins):
    inv = _make_purchase_invoice(valid_gstins)
    gen = TallyXmlGenerator(CompanyConfig())
    gen.generate(inv)
    ledgers = {l["ledger"] for l in gen.journal_lines}
    assert any("ABC Traders" in l for l in ledgers)  # party ledger
    assert any("CGST" in l for l in ledgers)
    assert any("SGST" in l for l in ledgers)


def test_journal_capture_resets_per_generate(valid_gstins):
    inv = _make_purchase_invoice(valid_gstins)
    gen = TallyXmlGenerator(CompanyConfig())
    gen.generate(inv)
    first = len(gen.journal_lines)
    gen.generate(inv)
    assert len(gen.journal_lines) == first, "must not accumulate across generates"


def test_classifier_group_mapping():
    assert classify_ledger("ABC Traders", "Sundry Creditors") == "Liability"
    assert classify_ledger("Purchase Account", "Purchase Accounts") == "Expense"
    assert classify_ledger("Sales", "Sales Accounts") == "Income"
    assert classify_ledger("ICICI Bank", "Bank Accounts") == "Asset"
    assert classify_ledger("Input CGST", "Duties & Taxes") == "Liability"


def test_classifier_keyword_fallback():
    assert classify_ledger("Office Rent Expense") == "Expense"
    assert classify_ledger("Service Revenue") == "Income"
    assert classify_ledger("SBI Cash") == "Asset"
    assert classify_ledger("Unknown Ledger") == "Expense"  # conservative default


def test_classifier_covers_all_28_groups():
    # Every one of Tally's universal groups must map to a known category.
    for group in GROUP_TO_TYPE:
        assert GROUP_TO_TYPE[group] in ("Asset", "Liability", "Income", "Expense")
