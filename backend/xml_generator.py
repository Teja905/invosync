"""Production-grade Tally XML Generator with full GST and Indian accounting compliance."""

import re as _re
from datetime import date
from typing import Optional

import xml.etree.ElementTree as ET

from core.logging import get_logger
from schemas import (
    StandardizedInvoice, VoucherType, GSTType, LineItem, TaxEntry, GST_STATE_CODES,
)
from company_config import CompanyConfig
from ledger_mapping import LedgerMappingEngine
from gst_engine import compute_tax_from_items

logger = get_logger(__name__)

_INVALID_XML_RE = _re.compile(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


def _sanitize(text: str) -> str:
    """Remove characters that would crash Tally XML parser. Safe for ElementTree paths (auto-escapes entities)."""
    if not text:
        return ""
    s = str(text).strip()
    s = _INVALID_XML_RE.sub("", s)
    return s


def safe_xml_string(text: str) -> str:
    """Full XML sanitization for raw f-string paths: strip invalid chars + escape XML entities.
    Use this for raw XML string formatting (ElementTree auto-escapes, so use _sanitize there instead)."""
    if not text:
        return ""
    s = str(text).strip()
    s = _INVALID_XML_RE.sub("", s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', "&quot;").replace("'", "&apos;")
    return s


def _ensure_ledger(name: str) -> str:
    """Return a safe ledger name; fallback to Suspense if empty or bogus."""
    cleaned = _sanitize(name)
    if not cleaned or cleaned.lower() in ("", "none", "null", "undefined", "n/a"):
        return _SUSPENSE
    return cleaned


_SUSPENSE = "Suspense Ledger"


class TallyXmlGenerator:
    def __init__(self, config: Optional[CompanyConfig] = None, include_ledgers: bool = True):
        self.config = config or CompanyConfig()
        self.ledger_engine = LedgerMappingEngine(self.config)
        self.include_ledgers = include_ledgers
        self.masters_created = False
        self.journal_lines: Optional[list] = None

    def generate(self, inv: StandardizedInvoice, company_name: str = "",
                 reuse_masters: Optional[bool] = None) -> str:
        self.journal_lines = []  # single source of truth for the ledger legs
        envelopes: list[ET.Element] = []
        active_company = company_name or self.config.company_name
        if reuse_masters is None:
            reuse_masters = self.masters_created
        if self.include_ledgers:
            master_elems = self._collect_master_elements(inv, reuse_masters=reuse_masters)
            if master_elems:
                master_tree = self._build_masters_envelope(master_elems)
                envelopes.append(master_tree.getroot())
        voucher_env = self._build_voucher_envelope([self._build_voucher_msg(inv)], active_company)
        envelopes.append(voucher_env)

        # Balance verification: if journal lines don't sum to zero, add round-off
        if self.journal_lines:
            total = sum(j["debit"] - j["credit"] for j in self.journal_lines)
            if abs(total) > 0.01:
                logger.warning("XML imbalance detected: %.2f — adding round-off entry", total)
                voucher_el = voucher_env.find(".//VOUCHER")
                if voucher_el is None:
                    logger.error(
                        "Imbalance %.2f but VOUCHER element missing — cannot auto round-off",
                        total,
                    )
                else:
                    round_off_ledger = self.config.get_round_off_ledger()
                    if total > 0:
                        # More debits than credits → add credit round-off
                        self._add_credit_entry(voucher_el, round_off_ledger, abs(total))
                    else:
                        # More credits than debits → add debit round-off
                        self._add_debit_entry(voucher_el, round_off_ledger, abs(total))
                    # Re-check; if still off, leave a hard log for operators
                    recheck = sum(j["debit"] - j["credit"] for j in self.journal_lines)
                    if abs(recheck) > 0.01:
                        logger.error(
                            "XML still unbalanced after round-off: %.2f (invoice=%s)",
                            recheck,
                            getattr(inv, "invoice_number", ""),
                        )

        return self._combine_envelopes(envelopes)

    def _build_voucher_envelope(self, tallymessages: list[ET.Element], company_name: str = "") -> ET.Element:
        """Standard Tally voucher import envelope.
        Vouchers MUST be imported under REPORTNAME='Vouchers' (not 'All Masters');
        using the wrong report name causes 'partially imported with errors' in Tally Prime."""
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
        body = ET.SubElement(envelope, "BODY")
        importdata = ET.SubElement(body, "IMPORTDATA")
        reqdesc = ET.SubElement(importdata, "REQUESTDESC")
        ET.SubElement(reqdesc, "REPORTNAME").text = "Vouchers"
        sv = ET.SubElement(reqdesc, "STATICVARIABLES")
        ET.SubElement(sv, "SVCURRENTCOMPANY").text = company_name or self.config.company_name
        reqdata = ET.SubElement(importdata, "REQUESTDATA")
        for msg in tallymessages:
            reqdata.append(msg)
        return envelope

    @staticmethod
    def _combine_envelopes(envelopes: list[ET.Element]) -> str:
        parts = ['<?xml version="1.0" encoding="UTF-8"?>']
        for env in envelopes:
            parts.append(ET.tostring(env, encoding="UTF-8").decode("UTF-8"))
        return "\n".join(parts)

    def _collect_master_elements(self, inv: StandardizedInvoice,
                                 reuse_masters: bool = False) -> list[ET.Element]:
        masters: list[ET.Element] = []
        seen_stock: set[str] = set()

        if reuse_masters:
            # Kinetic mode: only create the party ledger + new stock items
            # Skip voucher type, standard ledgers (already exist in Tally)
            self._build_ledger_elements(inv, masters, reuse_masters=True)
            # Stock items: create if auto-requested (Tally handles duplicates for stock)
            if inv.auto_create_stock_items and not inv.is_service and inv.line_items:
                masters.append(self._make_stock_group("Primary"))
                for item in inv.line_items:
                    name = (item.description or "").strip()
                    if name and name not in seen_stock:
                        seen_stock.add(name)
                        masters.append(self._make_stock_item(item))
            return masters

        # 1. Voucher type
        masters.append(self._make_voucher_type(inv.voucher_type.value))

        # 2. Stock items — always for goods invoices, opt-in for services
        if not inv.is_service and inv.line_items:
            masters.append(self._make_stock_group("Primary"))
            for item in inv.line_items:
                name = (item.description or "").strip()
                if name and name not in seen_stock:
                    seen_stock.add(name)
                    masters.append(self._make_stock_item(item))

        # 3. Ledgers (all types)
        self._build_ledger_elements(inv, masters, reuse_masters=False)

        return masters

    def _generate_all_masters_xml(self, inv: StandardizedInvoice) -> str:
        return self._to_string(self._build_masters_envelope(self._collect_master_elements(inv)))

    def pre_import_check(self, inv: StandardizedInvoice) -> dict:
        """Run readiness checks before XML generation. Returns warnings and masters."""
        masters = self.preview_masters(inv)
        warnings = []

        # 1. Company name sanity
        cname = self.config.company_name
        if not cname or cname == "My Company":
            warnings.append({
                "type": "company_name",
                "severity": "high",
                "message": f"Company name is '{cname or 'empty'}'. Open Tally > press F1 > check company name > update Settings to match exactly (case-sensitive).",
            })
        elif len(cname) < 5:
            warnings.append({
                "type": "company_name",
                "severity": "medium",
                "message": f"Company name '{cname}' seems short. Verify it matches Tally's company name exactly.",
            })

        # 2. Company GSTIN
        if not self.config.company_gstin:
            warnings.append({
                "type": "company_gstin",
                "severity": "high",
                "message": "Company GSTIN is not set. GSTIN-based voucher classification and GST registration won't work.",
            })

        # 3. Verify vendor ledger will be created
        party_name = inv.vendor_name or inv.buyer_name or ""
        if len(party_name) > 50:
            warnings.append({
                "type": "vendor_name",
                "severity": "low",
                "message": f"Vendor name '{party_name[:50]}...' is very long. Tally may truncate long names.",
            })
        if not party_name:
            warnings.append({
                "type": "vendor_name",
                "severity": "high",
                "message": "No vendor/buyer name found. Party ledger will use a fallback name.",
            })

        # 4. Verify XML will balance
        try:
            from validation_layer import validate_invoice_for_xml
            val_result = validate_invoice_for_xml(inv)
            if not val_result.passed:
                warnings.append({
                    "type": "validation",
                    "severity": "high",
                    "message": f"XML validation found issues: {'; '.join(val_result.errors[:3])}",
                })
        except Exception:
            pass

        return {
            "masters": masters,
            "count": len(masters),
            "warnings": warnings,
            "company": {
                "name": cname,
                "gstin": self.config.company_gstin,
                "state_code": self.config.state_code,
            },
            "voucher": {
                "type": inv.voucher_type.value,
                "party": party_name,
                "amount": inv.total_taxable_value + sum(t.amount for t in (inv.taxes or [])),
                "item_count": len(inv.line_items) if inv.line_items else 0,
            },
        }

    def preview_masters(self, inv: StandardizedInvoice) -> list[dict]:
        """Return human-readable list of masters that will be created."""
        preview: list[dict] = []

        # Voucher type
        preview.append({
            "type": "VoucherType",
            "name": inv.voucher_type.value,
            "action": "Create",
        })

        # Stock items (goods only, opt-in)
        if inv.auto_create_stock_items and not inv.is_service and inv.line_items:
            preview.append({
                "type": "StockGroup",
                "name": "Primary",
                "action": "Create",
            })
            seen = set()
            for item in inv.line_items:
                name = (item.description or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    preview.append({
                        "type": "StockItem",
                        "name": name,
                        "action": "Create",
                        "hsn": item.hsn_sac,
                        "unit": item.unit,
                    })

        # Party ledger
        vt = inv.voucher_type
        if vt == VoucherType.SALES:
            party_name = inv.buyer_name or inv.vendor_name
            party_parent = self.config.get_sundry_debtors_group()
            party_gstin = inv.buyer_gstin
        else:
            party_name = inv.vendor_name or inv.buyer_name
            party_parent = self.config.get_sundry_creditors_group()
            party_gstin = inv.vendor_gstin or inv.buyer_gstin
        preview.append({
            "type": "Ledger",
            "name": party_name,
            "parent": party_parent,
            "action": "Create",
            "gstin": party_gstin,
        })

        # Transaction ledger
        if vt in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
            preview.append({
                "type": "Ledger",
                "name": self.ledger_engine.map_purchase_ledger(),
                "parent": self.config.get_purchase_accounts_group(),
                "action": "Create",
            })
        elif vt == VoucherType.SALES:
            preview.append({
                "type": "Ledger",
                "name": self.ledger_engine.map_sales_ledger(),
                "parent": self.config.get_sales_accounts_group(),
                "action": "Create",
            })

        # GST tax ledgers
        if vt == VoucherType.JOURNAL:
            is_input = False
        else:
            is_input = vt in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE)
        taxes = self._compute_taxes_if_needed(inv)
        for tax in taxes:
            ln = self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input)
            preview.append({
                "type": "Ledger",
                "name": ln,
                "parent": self.config.get_duties_taxes_group(),
                "action": "Create",
                "gst_type": self._gst_type_name(tax.type),
            })

        # Cess
        if inv.cess_amount > 0:
            is_input = vt in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE)
            preview.append({
                "type": "Ledger",
                "name": self.config.get_cess_ledger(is_input),
                "parent": self.config.get_duties_taxes_group(),
                "action": "Create",
                "gst_type": "Cess",
            })

        # Auxiliary ledgers
        if inv.freight > 0:
            preview.append({
                "type": "Ledger",
                "name": self.config.get_freight_ledger(),
                "parent": self.config.get_purchase_accounts_group(),
                "action": "Create",
            })
        if inv.tds_amount > 0:
            preview.append({
                "type": "Ledger",
                "name": self.config.get_tds_ledger(),
                "parent": self.config.get_current_liabilities_group(),
                "action": "Create",
            })
        if inv.round_off != 0:
            preview.append({
                "type": "Ledger",
                "name": self.config.get_round_off_ledger(),
                "parent": self.config.get_purchase_accounts_group(),
                "action": "Create",
            })

        return preview

    def _make_voucher_type(self, vchtype_name: str) -> ET.Element:
        tm = ET.Element("TALLYMESSAGE")
        vt = ET.SubElement(tm, "VOUCHERTYPE")
        vt.set("NAME", _sanitize(vchtype_name))
        vt.set("ACTION", "Create")
        ET.SubElement(vt, "NAME").text = _sanitize(vchtype_name)
        ET.SubElement(vt, "ISACTIVE").text = "Yes"
        return tm

    def _make_stock_group(self, name: str) -> ET.Element:
        tm = ET.Element("TALLYMESSAGE")
        sg = ET.SubElement(tm, "STOCKGROUP")
        sg.set("NAME", _sanitize(name))
        sg.set("ACTION", "Create")
        ET.SubElement(sg, "NAME").text = _sanitize(name)
        ET.SubElement(sg, "PARENT").text = "Primary"
        return tm

    def _make_stock_item(self, item: LineItem) -> ET.Element:
        tm = ET.Element("TALLYMESSAGE")
        si = ET.SubElement(tm, "STOCKITEM")
        name = _sanitize(item.description or "Item")
        si.set("NAME", name)
        si.set("ACTION", "Create")
        ET.SubElement(si, "NAME").text = name
        ET.SubElement(si, "PARENT").text = "Primary"
        if item.hsn_sac:
            ET.SubElement(si, "HSNCODE").text = _sanitize(item.hsn_sac)
        ET.SubElement(si, "UNITS").text = _sanitize(item.unit or "Nos")
        ET.SubElement(si, "RATEOFDEALING").text = f"{item.rate:.2f}" if item.rate else "0.00"
        ET.SubElement(si, "GSTCLASS").text = "HSN" if item.hsn_sac.strip() else ""
        return tm

    def _build_masters_envelope(self, elements: list[ET.Element]) -> ET.ElementTree:
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
        body = ET.SubElement(envelope, "BODY")
        importdata = ET.SubElement(body, "IMPORTDATA")
        reqdesc = ET.SubElement(importdata, "REQUESTDESC")
        ET.SubElement(reqdesc, "REPORTNAME").text = "All Masters"
        reqdata = ET.SubElement(importdata, "REQUESTDATA")
        for el in elements:
            reqdata.append(el)
        return ET.ElementTree(envelope)

    def _build_single_envelope(self, tallymessages: list[ET.Element], company_name: str = "") -> str:
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
        ET.SubElement(header, "TYPE").text = "Data"
        ET.SubElement(header, "ID").text = "All Masters"
        body = ET.SubElement(envelope, "BODY")
        desc = ET.SubElement(body, "DESC")
        sv = ET.SubElement(desc, "STATICVARIABLES")
        ET.SubElement(sv, "SVCURRENTCOMPANY").text = company_name or self.config.company_name
        data = ET.SubElement(body, "DATA")
        for msg in tallymessages:
            data.append(msg)
        return self._to_string(ET.ElementTree(envelope))

    def _make_ledger(self, name: str, parent: str, **extra) -> ET.Element:
        tm = ET.Element("TALLYMESSAGE")
        ledger = ET.SubElement(tm, "LEDGER")
        ledger.set("NAME", _sanitize(name))
        ledger.set("ACTION", "Create")
        ET.SubElement(ledger, "NAME").text = _sanitize(name)
        ET.SubElement(ledger, "PARENT").text = _sanitize(parent)
        for key, val in extra.items():
            if val:
                el = ET.SubElement(ledger, key.upper().replace("_", ""))
                el.text = _sanitize(str(val))
        return tm

    def _build_ledger_elements(self, inv: StandardizedInvoice,
                               ledgers: list[ET.Element], reuse_masters: bool = False) -> None:
        seen: set[str] = set()

        def add_once(name: str, parent: str, **kw):
            if name not in seen:
                seen.add(name)
                ledgers.append(self._make_ledger(name, parent, **kw))

        vt = inv.voucher_type

        # -- Party ledger (vendor or buyer) — ALWAYS created (new party = new ledger) --
        if vt == VoucherType.SALES:
            party_name = inv.buyer_name or inv.vendor_name
            party_parent = self.config.get_sundry_debtors_group()
            party_gstin = inv.buyer_gstin
        else:
            party_name = inv.vendor_name or inv.buyer_name
            party_parent = self.config.get_sundry_creditors_group()
            party_gstin = inv.vendor_gstin or inv.buyer_gstin
        party_kw = {}
        if party_gstin:
            party_kw["GSTIN"] = party_gstin
            party_kw["GSTREGISTRATIONTYPE"] = "Regular"
            sc = party_gstin[:2]
            sn = GST_STATE_CODES.get(sc, "")
            if sn:
                party_kw["STATENAME"] = sn
        add_once(party_name, party_parent, **party_kw)

        if reuse_masters:
            return  # Only party ledger needed when masters already exist

        # -- Main transaction ledger --
        if vt in (VoucherType.PURCHASE, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
            add_once(self.ledger_engine.map_purchase_ledger(), self.config.get_purchase_accounts_group())
        elif vt == VoucherType.SALES:
            add_once(self.ledger_engine.map_sales_ledger(), self.config.get_sales_accounts_group())
        elif vt == VoucherType.JOURNAL:
            desc = inv.line_items[0].description if inv.line_items else inv.invoice_number
            add_once(self.ledger_engine.map_expense_ledger(desc), self.config.get_purchase_accounts_group())
        if vt in (VoucherType.PAYMENT, VoucherType.RECEIPT):
            add_once(self.config.get_bank_ledger(), self.config.get_bank_accounts_group())

        # -- GST tax ledgers --
        if vt == VoucherType.JOURNAL:
            is_input = False
        else:
            is_input = vt in (VoucherType.PURCHASE, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE)
        taxes = self._compute_taxes_if_needed(inv)
        for tax in taxes:
            ln = self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input)
            add_once(ln, self.config.get_duties_taxes_group(),
                     TAXTYPE="GST", GSTTYPE=self._gst_type_name(tax.type))

        # -- Cess ledger --
        if inv.cess_amount > 0:
            is_input = vt in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE)
            add_once(self.config.get_cess_ledger(is_input), self.config.get_duties_taxes_group(),
                     TAXTYPE="GST", GSTTYPE="Cess")

        # -- Auxiliary ledgers --
        if inv.freight > 0:
            add_once(self.config.get_freight_ledger(), self.config.get_purchase_accounts_group())
        if inv.tds_amount > 0:
            add_once(self.config.get_tds_ledger(), self.config.get_current_liabilities_group())
        if inv.round_off != 0:
            add_once(self.config.get_round_off_ledger(), self.config.get_purchase_accounts_group())

        # -- Auto-create ledgers for service line items that will be individually debited --
        if inv.is_service and inv.line_items:
            for item in inv.line_items:
                if not item.is_service:
                    continue
                ln = item.ledger_name.strip() if item.ledger_name.strip() else ""
                if not ln:
                    ln = self.ledger_engine.map_expense_ledger(item.description)
                if ln and ln not in seen:
                    add_once(ln, "Primary")

    @staticmethod
    def _gst_type_name(tax_type: str) -> str:
        mapping = {
            "cgst": "Central Tax",
            "sgst": "State Tax",
            "igst": "Integrated Tax",
            "cess": "Cess",
        }
        return mapping.get(tax_type.lower(), "Central Tax")

    def _build_voucher_msg(self, inv: StandardizedInvoice) -> ET.Element:
        logger.info("VOUCHER CLASSIFICATION (XML): voucher_type=%s invoice=%s vendor=%s",
                    inv.voucher_type.value, inv.invoice_number, inv.vendor_name)
        vt = inv.voucher_type
        if vt == VoucherType.SALES:
            tm, voucher = self._make_voucher("Sales", inv)
            self._fill_sales_voucher_body(voucher, inv)
        elif vt == VoucherType.JOURNAL:
            tm, voucher = self._make_voucher("Journal", inv)
            self._fill_journal_voucher_body(voucher, inv)
        elif vt == VoucherType.PAYMENT:
            tm, voucher = self._make_voucher("Payment", inv)
            self._fill_payment_voucher_body(voucher, inv)
        elif vt == VoucherType.RECEIPT:
            tm, voucher = self._make_voucher("Receipt", inv)
            self._fill_receipt_voucher_body(voucher, inv)
        elif vt == VoucherType.CREDIT_NOTE:
            tm, voucher = self._make_voucher("Credit Note", inv)
            self._fill_credit_note_body(voucher, inv)
        elif vt == VoucherType.DEBIT_NOTE:
            tm, voucher = self._make_voucher("Debit Note", inv)
            self._fill_debit_note_body(voucher, inv)
        else:
            tm, voucher = self._make_voucher("Purchase", inv)
            self._fill_purchase_voucher_body(voucher, inv)
        return tm

    def _generate_voucher(self, inv: StandardizedInvoice) -> str:
        msgs = [self._build_voucher_msg(inv)]
        return self._build_single_envelope(msgs)

    def _build_envelope(self, body_xml: ET.Element, company_name: str = "") -> ET.ElementTree:
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
        ET.SubElement(header, "TYPE").text = "Data"
        ET.SubElement(header, "ID").text = "All Masters"
        body = ET.SubElement(envelope, "BODY")
        desc = ET.SubElement(body, "DESC")
        sv = ET.SubElement(desc, "STATICVARIABLES")
        ET.SubElement(sv, "SVCURRENTCOMPANY").text = company_name or self.config.company_name
        data = ET.SubElement(body, "DATA")
        data.append(body_xml)
        return ET.ElementTree(envelope)

    def _make_voucher(self, vchtype: str, inv: Optional[StandardizedInvoice] = None) -> tuple:
        tm = ET.Element("TALLYMESSAGE")
        voucher = ET.SubElement(tm, "VOUCHER")
        voucher.set("VCHTYPE", vchtype)
        voucher.set("ACTION", "Create")
        ET.SubElement(voucher, "VOUCHERTYPENAME").text = vchtype
        ET.SubElement(voucher, "PERSISTEDVIEW").text = "Accounting Voucher View"
        # ISINVOICE=Yes only for Purchase/Sales goods invoices; No for services and non-inventory voucher types
        has_inventory = False
        if inv and not inv.is_service and inv.line_items:
            if inv.voucher_type in (VoucherType.PURCHASE, VoucherType.SALES):
                has_inventory = True
        ET.SubElement(voucher, "ISINVOICE").text = "Yes" if has_inventory else "No"
        return tm, voucher

    def _add_basic_fields(self, voucher: ET.Element, inv: StandardizedInvoice):
        raw = (inv.invoice_date or "").strip()
        if not raw:
            raw = date.today().strftime("%Y-%m-%d")
        parts = _re.split(r"[-/]", raw)
        if len(parts) == 3:
            if len(parts[0]) == 4:
                date_str = f"{parts[0]}{parts[1]}{parts[2]}"
            else:
                date_str = f"{parts[2]}{parts[1]}{parts[0]}"
        else:
            date_str = raw if _re.match(r"^\d{8}$", raw) else date.today().strftime("%Y%m%d")
        if not _re.match(r"^\d{8}$", date_str):
            date_str = date.today().strftime("%Y%m%d")
        ET.SubElement(voucher, "DATE").text = date_str
        ET.SubElement(voucher, "VOUCHERNUMBER").text = _sanitize(inv.invoice_number) or "."
        if inv.voucher_type == VoucherType.DEBIT_NOTE:
            party_name = inv.buyer_name or inv.vendor_name
            relation = "from"
        elif inv.voucher_type == VoucherType.SALES:
            party_name = inv.buyer_name or inv.vendor_name
            relation = "to"
        else:
            party_name = inv.vendor_name or inv.buyer_name
            relation = "from"
        narration = f"{inv.voucher_type.value} {relation} {party_name}"
        if inv.invoice_number:
            narration += f" - Invoice {inv.invoice_number}"
        if inv.invoice_date:
            narration += f" dated {inv.invoice_date}"
        ET.SubElement(voucher, "NARRATION").text = _sanitize(narration)

    def _add_original_invoice_refs(self, voucher: ET.Element, inv: StandardizedInvoice):
        """Inject ORIGINALINVOICENO and ORIGINALINVOICEDATE for Credit/Debit Notes."""
        if inv.voucher_type not in (VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
            return
        if not inv.original_invoice_number:
            return
        ET.SubElement(voucher, "ORIGINALINVOICENO").text = _sanitize(inv.original_invoice_number)
        if inv.original_invoice_date:
            raw = inv.original_invoice_date.strip()
            parts = _re.split(r"[-/]", raw)
            formatted = ""
            if len(parts) == 3:
                if len(parts[0]) == 4:
                    formatted = f"{parts[0]}{parts[1]}{parts[2]}"
                else:
                    formatted = f"{parts[2]}{parts[1]}{parts[0]}"
            if _re.match(r"^\d{8}$", raw):
                formatted = raw
            if formatted:
                ET.SubElement(voucher, "ORIGINALINVOICEDATE").text = formatted

    def _add_party_ledger(self, voucher: ET.Element, party_name: str, amount: float, invoice_number: str = "", is_debit: bool = False, currency: str = "INR", exchange_rate: float = 1.0):
        lst = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(lst, "LEDGERNAME").text = _ensure_ledger(party_name)
        ET.SubElement(lst, "ISPARTYLEDGER").text = "Yes"
        ET.SubElement(lst, "ISDEEMEDPOSITIVE").text = "Yes" if is_debit else "No"
        signed_amt = amount if is_debit else -amount
        if currency and currency != "INR" and exchange_rate > 0:
            foreign_amt = signed_amt / exchange_rate
            ET.SubElement(lst, "AMOUNT").text = f"{foreign_amt:.2f} {currency} @ Rs. {exchange_rate:.2f}"
            ET.SubElement(lst, "ORIGINALAMOUNT").text = f"{signed_amt:.2f}"
        else:
            ET.SubElement(lst, "AMOUNT").text = f"{signed_amt:.2f}"
        bill_list = ET.SubElement(lst, "BILLALLOCATIONS.LIST")
        ET.SubElement(bill_list, "NAME").text = _sanitize(invoice_number) or "REF"
        ET.SubElement(bill_list, "BILLTYPE").text = "New Ref"
        ET.SubElement(bill_list, "AMOUNT").text = f"{-amount if not is_debit else amount:.2f}"
        self._record_journal(party_name, signed_amt)

    def _add_debit_entry(self, voucher: ET.Element, ledger_name: str, amount: float):
        if amount <= 0:
            logger.warning("Debit entry skipped: ledger=%s amount=%.2f (non-positive)", ledger_name, amount)
            return
        lst = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(lst, "LEDGERNAME").text = _ensure_ledger(ledger_name)
        ET.SubElement(lst, "ISDEEMEDPOSITIVE").text = "Yes"
        ET.SubElement(lst, "AMOUNT").text = f"{amount:.2f}"
        self._record_journal(ledger_name, amount)

    def _add_credit_entry(self, voucher: ET.Element, ledger_name: str, amount: float):
        if amount <= 0:
            logger.warning("Credit entry skipped: ledger=%s amount=%.2f (non-positive)", ledger_name, amount)
            return
        lst = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(lst, "LEDGERNAME").text = _ensure_ledger(ledger_name)
        ET.SubElement(lst, "ISDEEMEDPOSITIVE").text = "No"
        ET.SubElement(lst, "AMOUNT").text = f"{-amount:.2f}"
        self._record_journal(ledger_name, -amount)

    def _record_journal(self, ledger_name: str, signed_amount: float):
        """Capture a ledger leg as a journal line (single source of truth).

        signed_amount > 0 -> Debit, < 0 -> Credit. Stored so reports (Trial
        Balance, P&L, Balance Sheet) can be derived without re-parsing XML.
        """
        if self.journal_lines is None:
            self.journal_lines = []
        self.journal_lines.append({
            "ledger": _ensure_ledger(ledger_name),
            "debit": round(signed_amount, 2) if signed_amount > 0 else 0.0,
            "credit": round(-signed_amount, 2) if signed_amount < 0 else 0.0,
        })

    def _add_tax_ledger_entries(self, voucher: ET.Element, taxes: list[TaxEntry], is_input: bool = True, is_rcm: bool = False):
        for tax in taxes:
            ledger = self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input, is_rcm)
            self._add_debit_entry(voucher, ledger, tax.amount)

    def _add_cess_entries(self, voucher: ET.Element, inv: StandardizedInvoice, is_debit: bool = True):
        if inv.cess_amount <= 0:
            return
        ledger = self.config.get_cess_ledger(is_input=(inv.voucher_type in (VoucherType.PURCHASE, VoucherType.JOURNAL, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE)))
        if is_debit:
            self._add_debit_entry(voucher, ledger, inv.cess_amount)
        else:
            self._add_credit_entry(voucher, ledger, inv.cess_amount)

    def _add_inventory_entries(self, voucher: ET.Element, inv: StandardizedInvoice):
        if inv.is_service or not inv.line_items:
            return
        if inv.voucher_type not in (VoucherType.PURCHASE, VoucherType.SALES, VoucherType.CREDIT_NOTE, VoucherType.DEBIT_NOTE):
            return
        for item in inv.line_items:
            inv_entry = ET.SubElement(voucher, "ALLINVENTORYENTRIES.LIST")
            ET.SubElement(inv_entry, "STOCKITEMNAME").text = _ensure_ledger(item.description)
            if item.hsn_sac:
                ET.SubElement(inv_entry, "HSNCODE").text = item.hsn_sac
            batch = ET.SubElement(inv_entry, "BATCHALLOCATIONS.LIST")
            if item.tax_rate:
                ET.SubElement(batch, "GSTRATE").text = f"{item.tax_rate:.2f}"
            ET.SubElement(batch, "GSTCLASS").text = "HSN"
            ET.SubElement(batch, "BATCHNAME").text = "Primary"
            ET.SubElement(batch, "BATCHEXPIRY").text = ""
            ET.SubElement(batch, "INDENTNO").text = ""
            ET.SubElement(batch, "ORDERNO").text = ""
            ET.SubElement(batch, "ORDERDATE").text = ""
            ET.SubElement(inv_entry, "AMOUNT").text = f"{item.taxable_value:.2f}"
            ET.SubElement(inv_entry, "ACTUALQTY").text = self._fmt_qty(item.quantity)
            ET.SubElement(inv_entry, "BILLEDQTY").text = self._fmt_qty(item.quantity)
            ET.SubElement(inv_entry, "RATE").text = f"{item.rate:.2f}"

    def _fmt_qty(self, qty: float) -> str:
        if qty == int(qty):
            return f"{int(qty)}"
        return f"{qty:.2f}"

    def _get_company_gstin(self) -> str:
        return self.config.company_gstin

    def _compute_taxes_if_needed(self, inv: StandardizedInvoice) -> list[TaxEntry]:
        if inv.gst_type in (GSTType.EXEMPT, GSTType.NIL_RATED, GSTType.COMPOSITION):
            return []
        if inv.taxes:
            return inv.taxes
        if inv.line_items and inv.gst_type in (GSTType.CGST_SGST, GSTType.IGST):
            config_dict = dict(self.config.gst_ledger_mappings)
            config_dict["company_state_code"] = self.config.state_code
            computed = compute_tax_from_items(
                [item.model_dump() for item in inv.line_items],
                inv.gst_type,
                config_dict,
                is_input=inv.voucher_type in (VoucherType.PURCHASE, VoucherType.JOURNAL),
                is_rcm=inv.is_rcm,
            )
            return computed
        return []

    def _get_total_debits(self, taxable: float, taxes: list[TaxEntry], extras: list[tuple[str, float]]) -> float:
        total = taxable
        for t in taxes:
            total += t.amount
        for _, amt in extras:
            total += amt
        return total

    # -----------------------------------------------------------------------
    # Voucher-specific generators
    # -----------------------------------------------------------------------

    def _add_expense_debits(self, voucher: ET.Element, inv: StandardizedInvoice) -> float:
        """Add debit entries for taxable value, splitting across expense ledgers for service items.
        Returns the total taxable amount actually debited."""
        purchase_ledger = self.ledger_engine.map_purchase_ledger()
        if inv.is_service and inv.line_items:
            ledger_amounts = {}
            for item in inv.line_items:
                if item.is_service or item.taxable_value <= 0:
                    continue
                ledger_amounts[purchase_ledger] = ledger_amounts.get(purchase_ledger, 0) + item.taxable_value
            for item in inv.line_items:
                if not item.is_service or item.taxable_value <= 0:
                    continue
                led = (item.ledger_name.strip() or self.ledger_engine.map_expense_ledger(item.description))
                ledger_amounts[led] = ledger_amounts.get(led, 0) + item.taxable_value
            if not ledger_amounts:
                ledger_amounts[purchase_ledger] = inv.total_taxable_value
            taxable_debited = 0
            for led, amt in ledger_amounts.items():
                self._add_debit_entry(voucher, led, amt)
                taxable_debited += amt
            return taxable_debited
        self._add_debit_entry(voucher, purchase_ledger, inv.total_taxable_value)
        return inv.total_taxable_value

    def _fill_purchase_voucher_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        self._add_basic_fields(voucher, inv)
        self._add_inventory_entries(voucher, inv)
        party_name = self.ledger_engine.map_party_ledger(inv.vendor_name)
        ET.SubElement(voucher, "PARTYLEDGERNAME").text = party_name
        if inv.vendor_gstin:
            ET.SubElement(voucher, "PARTYGSTIN").text = inv.vendor_gstin
        taxes = self._compute_taxes_if_needed(inv)
        paid_taxable = self._add_expense_debits(voucher, inv)
        self._add_tax_ledger_entries(voucher, taxes, is_input=True, is_rcm=inv.is_rcm)
        additional_debits = []
        if inv.cess_amount > 0:
            self._add_debit_entry(voucher, self.config.get_cess_ledger(), inv.cess_amount)
            additional_debits.append(("cess", inv.cess_amount))
        if inv.freight > 0:
            self._add_debit_entry(voucher, self.config.get_freight_ledger(), inv.freight)
            additional_debits.append(("freight", inv.freight))
        if inv.tds_amount > 0:
            self._add_credit_entry(voucher, self.config.get_tds_ledger(), inv.tds_amount)
            additional_debits.append(("tds", -inv.tds_amount))
        if inv.round_off != 0:
            if inv.round_off > 0:
                self._add_debit_entry(voucher, self.config.get_round_off_ledger(), abs(inv.round_off))
            else:
                self._add_credit_entry(voucher, self.config.get_round_off_ledger(), abs(inv.round_off))
            additional_debits.append(("round_off", inv.round_off))
        total_debits = self._get_total_debits(paid_taxable, taxes, additional_debits)
        self._add_party_ledger(voucher, party_name, total_debits, inv.invoice_number, currency=inv.currency, exchange_rate=inv.exchange_rate)

    def _generate_purchase_voucher(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Purchase", inv)
        self._fill_purchase_voucher_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _fill_sales_voucher_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        """Balanced Sales voucher: party debited (Dr), sales income + output GST credited (Cr).

        Double-entry: Debtor Dr (grand total) = Sales Cr (taxable) + Output GST Cr (tax)
        + freight Cr + round-off adjustment. Sum of signed AMOUNTs must equal 0.
        """
        self._add_basic_fields(voucher, inv)
        self._add_inventory_entries(voucher, inv)
        party_name = self.ledger_engine.map_party_ledger(inv.buyer_name or inv.vendor_name)
        ET.SubElement(voucher, "PARTYLEDGERNAME").text = party_name
        if inv.buyer_gstin:
            ET.SubElement(voucher, "PARTYGSTIN").text = inv.buyer_gstin

        taxes = self._compute_taxes_if_needed(inv)
        sales_ledger = self.ledger_engine.map_sales_ledger()

        # Credit side: sales income (taxable value)
        self._add_credit_entry(voucher, sales_ledger, inv.total_taxable_value)
        # Credit side: output GST
        for tax in taxes:
            ledger = self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input=False, is_rcm=inv.is_rcm)
            self._add_credit_entry(voucher, ledger, tax.amount)
        # Credit side: cess
        if inv.cess_amount > 0:
            self._add_credit_entry(voucher, self.config.get_cess_ledger(is_input=False), inv.cess_amount)
        # Credit side: freight charged to the customer
        credited_total = inv.total_taxable_value + sum(t.amount for t in taxes) + inv.cess_amount
        if inv.freight > 0:
            self._add_credit_entry(voucher, self.config.get_freight_ledger(), inv.freight)
            credited_total += inv.freight
        # Round-off adjustment
        if inv.round_off != 0:
            if inv.round_off > 0:
                self._add_credit_entry(voucher, self.config.get_round_off_ledger(), abs(inv.round_off))
                credited_total += abs(inv.round_off)
            else:
                self._add_debit_entry(voucher, self.config.get_round_off_ledger(), abs(inv.round_off))
                credited_total -= abs(inv.round_off)

        # Debit side: party (debtor) for the full amount receivable
        self._add_party_ledger(
            voucher, party_name, credited_total, inv.invoice_number,
            is_debit=True, currency=inv.currency, exchange_rate=inv.exchange_rate,
        )

    def _generate_sales_voucher(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Sales", inv)
        self._fill_sales_voucher_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _fill_journal_voucher_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        """Journal voucher: output-side double entry (Dr party, Cr income + output tax).
        No PARTYLEDGERNAME in header — Tally rejects Journal vouchers with header party allocation.
        """
        self._add_basic_fields(voucher, inv)
        taxes = self._compute_taxes_if_needed(inv)

        desc = inv.line_items[0].description if inv.line_items else inv.invoice_number
        income_ledger = self.ledger_engine.map_expense_ledger(desc)

        self._add_credit_entry(voucher, income_ledger, inv.total_taxable_value)
        for tax in taxes:
            ledger = self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input=False, is_rcm=inv.is_rcm)
            self._add_credit_entry(voucher, ledger, tax.amount)

        credited_total = inv.total_taxable_value + sum(t.amount for t in taxes)
        if inv.round_off != 0:
            if inv.round_off > 0:
                self._add_credit_entry(voucher, self.config.get_round_off_ledger(), abs(inv.round_off))
                credited_total += abs(inv.round_off)
            else:
                self._add_debit_entry(voucher, self.config.get_round_off_ledger(), abs(inv.round_off))
                credited_total -= abs(inv.round_off)

        party_name = self.ledger_engine.map_party_ledger(inv.vendor_name or inv.buyer_name or "Party")
        self._add_party_ledger(
            voucher, party_name, credited_total, inv.invoice_number,
            is_debit=True, currency=inv.currency, exchange_rate=inv.exchange_rate,
        )

    def _generate_journal_voucher(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Journal", inv)
        self._fill_journal_voucher_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _fill_payment_voucher_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        """Payment: Bank Cr (money goes out), Party Dr (liability cleared).
        ISDEEMEDPOSITIVE=Yes for party (debit), No for bank (credit)."""
        self._add_basic_fields(voucher, inv)
        party_name = inv.vendor_name or "Party"
        # Bank is CREDITED (money leaves bank)
        self._add_credit_entry(voucher, self.config.get_bank_ledger(), inv.total_amount)
        # Party is DEBITED (liability to vendor is cleared)
        self._add_party_ledger(voucher, party_name, inv.total_amount, inv.invoice_number,
                               is_debit=True, currency=inv.currency, exchange_rate=inv.exchange_rate)

    def _generate_payment_voucher(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Payment", inv)
        self._fill_payment_voucher_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _fill_receipt_voucher_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        """Receipt: Bank Dr (money comes in), Party Cr (debtor pays).
        ISDEEMEDPOSITIVE=Yes for bank (debit), No for party (credit)."""
        self._add_basic_fields(voucher, inv)
        party_name = inv.buyer_name or inv.vendor_name or "Party"
        # Bank is DEBITED (money enters bank)
        self._add_debit_entry(voucher, self.config.get_bank_ledger(), inv.total_amount)
        # Party is CREDITED (debtor's balance reduced)
        self._add_party_ledger(voucher, party_name, inv.total_amount, inv.invoice_number,
                               is_debit=False, currency=inv.currency, exchange_rate=inv.exchange_rate)

    def _generate_receipt_voucher(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Receipt", inv)
        self._fill_receipt_voucher_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _fill_credit_note_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        self._add_basic_fields(voucher, inv)
        self._add_original_invoice_refs(voucher, inv)
        party_name = self.ledger_engine.map_party_ledger(inv.vendor_name)
        ET.SubElement(voucher, "PARTYLEDGERNAME").text = party_name
        taxes = self._compute_taxes_if_needed(inv)
        purchase_ledger = self.ledger_engine.map_purchase_ledger()
        if inv.is_service:
            primary_desc = inv.line_items[0].description if inv.line_items else ""
            purchase_ledger = self.ledger_engine.map_expense_ledger(primary_desc)
        self._add_credit_entry(voucher, purchase_ledger, abs(inv.total_taxable_value))
        for tax in taxes:
            self._add_credit_entry(voucher, self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input=True), abs(tax.amount))
        if inv.cess_amount > 0:
            self._add_credit_entry(voucher, self.config.get_cess_ledger(), abs(inv.cess_amount))
        total_credits = abs(inv.total_taxable_value) + sum(abs(t.amount) for t in taxes) + abs(inv.cess_amount)
        self._add_party_ledger(voucher, party_name, total_credits, inv.invoice_number, is_debit=True, currency=inv.currency, exchange_rate=inv.exchange_rate)
        self._add_inventory_entries(voucher, inv)

    def _generate_credit_note(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Credit Note", inv)
        self._fill_credit_note_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _fill_debit_note_body(self, voucher: ET.Element, inv: StandardizedInvoice):
        self._add_basic_fields(voucher, inv)
        self._add_original_invoice_refs(voucher, inv)
        party_name = self.ledger_engine.map_party_ledger(inv.vendor_name)
        ET.SubElement(voucher, "PARTYLEDGERNAME").text = party_name
        taxes = self._compute_taxes_if_needed(inv)
        purchase_ledger = self.ledger_engine.map_purchase_ledger()
        if inv.is_service:
            primary_desc = inv.line_items[0].description if inv.line_items else ""
            purchase_ledger = self.ledger_engine.map_expense_ledger(primary_desc)
        self._add_debit_entry(voucher, purchase_ledger, abs(inv.total_taxable_value))
        for tax in taxes:
            self._add_debit_entry(voucher, self.ledger_engine.map_gst_ledger(tax.type, tax.rate, is_input=True), abs(tax.amount))
        if inv.cess_amount > 0:
            self._add_debit_entry(voucher, self.config.get_cess_ledger(), abs(inv.cess_amount))
        total_debits = abs(inv.total_taxable_value) + sum(abs(t.amount) for t in taxes) + abs(inv.cess_amount)
        self._add_party_ledger(voucher, party_name, total_debits, inv.invoice_number, currency=inv.currency, exchange_rate=inv.exchange_rate)
        self._add_inventory_entries(voucher, inv)

    def _generate_debit_note(self, inv: StandardizedInvoice) -> str:
        tm, voucher = self._make_voucher("Debit Note", inv)
        self._fill_debit_note_body(voucher, inv)
        tree = self._build_envelope(tm)
        return self._to_string(tree)

    def _to_string(self, tree: ET.ElementTree) -> str:
        xml_bytes = ET.tostring(tree.getroot(), encoding="UTF-8", xml_declaration=True)
        return xml_bytes.decode("UTF-8")


def resolve_voucher_expense_ledger(invoice_doc: dict) -> str:
    custom = invoice_doc.get("custom_ledger_override", "")
    if custom:
        return _sanitize(custom)
    return _sanitize(invoice_doc.get("expense_ledger_default", "Purchase Accounts"))


def generate_tally_bank_xml(processed_txs: list[dict], bank_ledger_name: str = "Bank", company_name: str = "") -> str:
    xml_entries = []
    for tx in processed_txs:
        # FIX: sanitize tally_date before XML injection
        raw_date = str(tx.get("transaction_date", "")).replace("-", "").strip()
        tally_date = _re.sub(r"[^0-9]", "", raw_date)[:8]  # only digits, max 8 chars
        vch_type = safe_xml_string(tx.get("voucher_type", "Receipt"))
        target_ledger = tx.get("target_ledger", "Suspense")
        desc = safe_xml_string(tx.get("description", ""))
        deposit = float(tx.get("deposit_amount", 0))
        withdraw = float(tx.get("withdraw_amount", 0))

        if vch_type == "Receipt":
            bank_amount = f"-{abs(deposit):.2f}"
            party_amount = f"{abs(deposit):.2f}"
            bank_deemed = "Yes"
            party_deemed = "No"
        else:
            bank_amount = f"{abs(withdraw):.2f}"
            party_amount = f"-{abs(withdraw):.2f}"
            bank_deemed = "No"
            party_deemed = "Yes"

        xml_entries.append(f"""<TALLYMESSAGE xmlns:UDF="TallyUDF">
<VOUCHER VCHTYPE="{vch_type}" ACTION="Create">
<DATE>{tally_date}</DATE>
<VOUCHERTYPE>{vch_type}</VOUCHERTYPE>
<NARRATION>Bank Entry: {desc}</NARRATION>
<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>{safe_xml_string(bank_ledger_name)}</LEDGERNAME>
<ISDEEMEDPOSITIVE>{bank_deemed}</ISDEEMEDPOSITIVE>
<AMOUNT>{bank_amount}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>{safe_xml_string(target_ledger)}</LEDGERNAME>
<ISDEEMEDPOSITIVE>{party_deemed}</ISDEEMEDPOSITIVE>
<AMOUNT>{party_amount}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
</VOUCHER>
</TALLYMESSAGE>""")

    inner = "\n".join(xml_entries)
    svc = f"<SVCURRENTCOMPANY>{safe_xml_string(company_name)}</SVCURRENTCOMPANY>" if company_name else ""
    return f"""<ENVELOPE>
<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
<BODY>
<IMPORTDATA>
<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>{svc}</REQUESTDESC>
<REQUESTDATA>
{inner}
</REQUESTDATA>
</IMPORTDATA>
</BODY>
</ENVELOPE>"""
