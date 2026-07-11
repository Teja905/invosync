import xml.etree.ElementTree as ET
from models import InvoiceRequest
from gst import classify_gst, compute_tax, compute_tax_from_items


def _make_header() -> ET.Element:
    envelope = ET.Element("ENVELOPE")
    header = ET.SubElement(envelope, "HEADER")
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
    ET.SubElement(header, "TYPE").text = "Data"
    ET.SubElement(header, "ID").text = "All Masters"
    return envelope


def _make_voucher(envelope: ET.Element, company_name: str = "My Company") -> ET.Element:
    body = ET.SubElement(envelope, "BODY")
    import_data = ET.SubElement(body, "IMPORTDATA")
    req_desc = ET.SubElement(import_data, "REQUESTDESC")
    ET.SubElement(req_desc, "REPORTNAME").text = "Vouchers"
    req_data = ET.SubElement(import_data, "REQUESTDATA")
    tm = ET.SubElement(req_data, "TALLYMESSAGE")
    tm.set("xmlns:UDF", "TallyUDF")
    return tm


def _format_date(date_str: str) -> str:
    if "-" in date_str:
        parts = date_str.split("-")
        return f"{parts[0]}{parts[1]}{parts[2]}"
    elif "/" in date_str:
        parts = date_str.split("/")
        return f"{parts[2]}{parts[1]}{parts[0]}"
    return date_str


def _add_ledger_entry(voucher: ET.Element, ledger_name: str, amount: float, is_debit: bool,
                      bill_name: str = "", bill_type: str = ""):
    lst = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
    ET.SubElement(lst, "LEDGERNAME").text = ledger_name

    if is_debit:
        ET.SubElement(lst, "ISDEEMEDPOSITIVE").text = "Yes"
        ET.SubElement(lst, "AMOUNT").text = f"{amount:.2f}"
    else:
        ET.SubElement(lst, "ISDEEMEDPOSITIVE").text = "No"
        ET.SubElement(lst, "AMOUNT").text = f"{-amount:.2f}"

    if bill_name:
        bill_list = ET.SubElement(lst, "BILLALLOCATIONS.LIST")
        ET.SubElement(bill_list, "NAME").text = bill_name
        ET.SubElement(bill_list, "BILLTYPE").text = bill_type or "New Ref"
        ET.SubElement(bill_list, "AMOUNT").text = f"{amount:.2f}" if is_debit else f"{-amount:.2f}"


def _add_inventory_entry(voucher: ET.Element, item) -> None:
    inv_list = ET.SubElement(voucher, "ALLINVENTORYENTRIES.LIST")
    ET.SubElement(inv_list, "STOCKITEMNAME").text = item.description or "Item"
    if item.quantity:
        qty_str = f"{int(item.quantity)}" if item.quantity == int(item.quantity) else f"{item.quantity:.2f}"
        ET.SubElement(inv_list, "QUANTITY").text = qty_str
    if item.rate:
        ET.SubElement(inv_list, "RATE").text = f"{item.rate:.2f}"
    ET.SubElement(inv_list, "AMOUNT").text = f"{item.taxable_amount:.2f}"
    if item.hsn_sac:
        ET.SubElement(inv_list, "HSNCODE").text = item.hsn_sac
    if item.unit:
        ET.SubElement(inv_list, "UNIT").text = item.unit
    if item.tax_rate > 0:
        rate_int = int(item.tax_rate)
        ET.SubElement(inv_list, "GSTCLASS").text = f"{rate_int}%"


def generate_purchase_xml(data: InvoiceRequest, company_name: str = "My Company",
                          company_state: str = "") -> str:
    envelope = _make_header()
    tm = _make_voucher(envelope, company_name)

    voucher = ET.SubElement(tm, "VOUCHER")
    voucher.set("VCHTYPE", "Purchase")

    date_str = _format_date(data.invoice_date)
    ET.SubElement(voucher, "DATE").text = date_str
    ET.SubElement(voucher, "VOUCHERNUMBER").text = data.invoice_number
    ET.SubElement(voucher, "PARTYLEDGERNAME").text = data.party_name
    ET.SubElement(voucher, "PARTYGSTIN").text = data.party_gstin.upper()

    gst_info = classify_gst(data.company_gstin, data.party_gstin)
    gst_type = gst_info["gst_type"]

    if data.line_items:
        tax_entries = compute_tax_from_items(
            [{"taxable_amount": li.taxable_amount, "tax_rate": li.tax_rate} for li in data.line_items],
            gst_type
        )
    else:
        tax_entries = compute_tax(data.taxable_total, data.tax_rate, gst_type)

    tax_total_from_entries = sum(t["amount"] for t in tax_entries)
    party_amount = round(data.taxable_total + tax_total_from_entries, 2)

    _add_ledger_entry(
        voucher, data.party_name, party_amount,
        is_debit=False,
        bill_name=data.invoice_number,
        bill_type="New Ref"
    )

    _add_ledger_entry(voucher, "Purchase", data.taxable_total, is_debit=True)

    for tax in tax_entries:
        _add_ledger_entry(voucher, tax["name"], tax["amount"], is_debit=True)

    if data.line_items:
        for item in data.line_items:
            _add_inventory_entry(voucher, item)

    xml_bytes = ET.tostring(envelope, encoding="UTF-8", xml_declaration=True)
    return xml_bytes.decode("UTF-8")


def generate_sales_xml(data: InvoiceRequest, company_name: str = "My Company",
                       company_state: str = "") -> str:
    envelope = _make_header()
    tm = _make_voucher(envelope, company_name)

    voucher = ET.SubElement(tm, "VOUCHER")
    voucher.set("VCHTYPE", "Sales")

    date_str = _format_date(data.invoice_date)
    ET.SubElement(voucher, "DATE").text = date_str
    ET.SubElement(voucher, "VOUCHERNUMBER").text = data.invoice_number
    ET.SubElement(voucher, "PARTYLEDGERNAME").text = data.party_name
    ET.SubElement(voucher, "PARTYGSTIN").text = data.party_gstin.upper()

    gst_info = classify_gst(data.company_gstin, data.party_gstin)
    gst_type = gst_info["gst_type"]

    if data.line_items:
        tax_entries = compute_tax_from_items(
            [{"taxable_amount": li.taxable_amount, "tax_rate": li.tax_rate} for li in data.line_items],
            gst_type
        )
    else:
        tax_entries = compute_tax(data.taxable_total, data.tax_rate, gst_type)

    tax_total_from_entries = sum(t["amount"] for t in tax_entries)
    party_amount = round(data.taxable_total + tax_total_from_entries, 2)

    _add_ledger_entry(
        voucher, data.party_name, party_amount,
        is_debit=True,
        bill_name=data.invoice_number,
        bill_type="New Ref"
    )

    _add_ledger_entry(voucher, "Sales", data.taxable_total, is_debit=False)

    for tax in tax_entries:
        _add_ledger_entry(voucher, tax["name"], tax["amount"], is_debit=False)

    if data.line_items:
        for item in data.line_items:
            _add_inventory_entry(voucher, item)

    xml_bytes = ET.tostring(envelope, encoding="UTF-8", xml_declaration=True)
    return xml_bytes.decode("UTF-8")
