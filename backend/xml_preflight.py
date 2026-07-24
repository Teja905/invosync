"""XML pre-flight validator — checks generated Tally XML for common import-blocking issues.

No Tally license required. Runs purely against XML structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


@dataclass
class PreFlightIssue:
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str
    fix: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class PreFlightReport:
    passed: bool
    issues: list[PreFlightIssue] = field(default_factory=list)
    xml_length: int = 0
    voucher_type: str = ""
    has_ledgers: bool = False
    has_stock_items: bool = False

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "xml_length": self.xml_length,
            "voucher_type": self.voucher_type,
            "has_ledgers": self.has_ledgers,
            "has_stock_items": self.has_stock_items,
            "issue_count": len(self.issues),
            "errors": [i.to_dict() for i in self.issues if i.severity == "error"],
            "warnings": [i.to_dict() for i in self.issues if i.severity == "warning"],
            "info": [i.to_dict() for i in self.issues if i.severity == "info"],
        }


class XMLPreFlightValidator:
    """Validate Tally XML before export/push."""

    def __init__(self, xml: str):
        self.xml = xml or ""
        self.issues: list[PreFlightIssue] = []

    def validate(self) -> PreFlightReport:
        if not self.xml.strip():
            self.issues.append(PreFlightIssue("error", "EMPTY_XML", "Generated XML is empty", fix="Regenerate XML"))
            return PreFlightReport(passed=False, issues=self.issues)

        self.xml_length = len(self.xml)

        try:
            root = ET.fromstring(self.xml)
        except ET.ParseError as e:
            self.issues.append(PreFlightIssue("error", "MALFORMED_XML", f"XML parse error: {e}", fix="Fix XML generation"))
            return PreFlightReport(passed=False, issues=self.issues, xml_length=self.xml_length)

        self._check_envelope(root)
        self._check_voucher_type(root)
        self._check_party_ledger(root)
        self._check_balance(root)
        self._check_ledgers_section(root)
        self._check_stock_items(root)
        self._check_gst_ledgers(root)
        self._check_bill_allocations(root)
        self._check_company_name(root)

        passed = not any(i.severity == "error" for i in self.issues)
        voucher_type = self._extract_voucher_type(root)
        has_ledgers = self._has_section(root, "LEDGER")
        has_stock_items = self._has_section(root, "STOCKITEM")

        return PreFlightReport(
            passed=passed,
            issues=self.issues,
            xml_length=self.xml_length,
            voucher_type=voucher_type,
            has_ledgers=has_ledgers,
            has_stock_items=has_stock_items,
        )

    def _check_envelope(self, root: ET.Element):
        if root.tag != "ENVELOPE":
            self.issues.append(PreFlightIssue("error", "NO_ENVELOPE", "Root element is not <ENVELOPE>", fix="Wrap XML in ENVELOPE tag"))

    def _check_voucher_type(self, root: ET.Element):
        voucher = root.find(".//VOUCHER")
        if voucher is None:
            self.issues.append(PreFlightIssue("error", "NO_VOUCHER", "No <VOUCHER> element found", fix="Include voucher in XML"))
            return
        vch_type = voucher.get("VCHTYPE", "")
        if not vch_type:
            self.issues.append(PreFlightIssue("warning", "MISSING_VCHTYPE", "Voucher has no VCHTYPE attribute", fix="Set VCHTYPE on VOUCHER"))

    def _check_party_ledger(self, root: ET.Element):
        for ledger in root.findall(".//ALLLEDGERENTRIES.LIST"):
            is_party = ledger.findtext("ISPARTYLEDGER")
            if is_party == "Yes":
                ledger_name = ledger.findtext("LEDGERNAME", "").strip()
                if not ledger_name:
                    self.issues.append(PreFlightIssue("error", "EMPTY_PARTY_LEDGER", "Party ledger has no LEDGERNAME", fix="Set LEDGERNAME for party entry"))
                return
        self.issues.append(PreFlightIssue("warning", "NO_PARTY_LEDGER", "No party ledger marked with ISPARTYLEDGER=Yes", fix="Mark one ledger entry as party"))

    def _check_balance(self, root: ET.Element):
        amounts = []
        for ledger in root.findall(".//ALLLEDGERENTRIES.LIST"):
            amt_text = ledger.findtext("AMOUNT", "0").strip()
            try:
                amounts.append(float(amt_text))
            except ValueError:
                pass
        if amounts:
            total = sum(amounts)
            if abs(total) > 0.01:
                self.issues.append(PreFlightIssue("error", "UNBALANCED_VOUCHER", f"Voucher not balanced: sum of AMOUNTs = {total:.2f}, expected 0", fix="Adjust debit/credit entries to balance"))

    def _check_ledgers_section(self, root: ET.Element):
        has_masters = self._has_section(root, "VOUCHERTYPE") or self._has_section(root, "LEDGER")
        if not has_masters:
            self.issues.append(PreFlightIssue("warning", "NO_MASTERS", "No ledger or voucher type masters in XML", fix="Add master creation envelope before voucher"))

    def _check_stock_items(self, root: ET.Element):
        has_inventory = bool(root.findall(".//ALLINVENTORYENTRIES.LIST"))
        has_stock = self._has_section(root, "STOCKITEM")
        if has_inventory and not has_stock:
            self.issues.append(PreFlightIssue("warning", "STOCK_ITEMS_MISSING", "Invoice has inventory entries but no stock items created", fix="Add STOCKITEM masters before voucher"))

    def _check_gst_ledgers(self, root: ET.Element):
        ledger_names = [e.findtext("LEDGERNAME", "").lower() for e in root.findall(".//ALLLEDGERENTRIES.LIST")]
        has_gst = any("cgst" in n or "sgst" in n or "igst" in n for n in ledger_names)
        voucher = root.find(".//VOUCHER")
        vch_type = (voucher.get("VCHTYPE", "") if voucher is not None else "").lower()
        is_purchase = vch_type in ("purchase", "debit note")
        is_sales = vch_type in ("sales", "credit note")
        if (is_purchase or is_sales) and not has_gst:
            self.issues.append(PreFlightIssue("warning", "NO_GST_LEDGERS", "GST invoice has no CGST/SGST/IGST ledger entries", fix="Add tax ledger entries"))

    def _check_bill_allocations(self, root: ET.Element):
        for ledger in root.findall(".//ALLLEDGERENTRIES.LIST"):
            bill = ledger.find("BILLALLOCATIONS.LIST")
            if bill is not None:
                name = bill.findtext("NAME", "").strip()
                bill_type = bill.findtext("BILLTYPE", "").strip()
                if not name:
                    self.issues.append(PreFlightIssue("warning", "EMPTY_BILL_NAME", "Bill allocation has empty NAME", fix="Set BILLNAME in bill allocation"))
                if bill_type != "New Ref":
                    self.issues.append(PreFlightIssue("info", "NON_STANDARD_BILL_TYPE", f"Bill type is '{bill_type}', expected 'New Ref'", fix="Use BILLTYPE='New Ref' for new references"))

    def _check_company_name(self, root: ET.Element):
        company = root.findtext(".//REQUESTDATA/TALLYMESSAGE/COMPANY", "").strip()
        if not company:
            company = root.findtext(".//COMPANY", "").strip()
        if not company:
            self.issues.append(PreFlightIssue("warning", "NO_COMPANY", "No COMPANY name found in XML", fix="Add <COMPANY>Name</COMPANY>"))

    def _has_section(self, root: ET.Element, tag: str) -> bool:
        return bool(root.findall(f".//{tag}"))

    def _extract_voucher_type(self, root: ET.Element) -> str:
        voucher = root.find(".//VOUCHER")
        if voucher is not None:
            return voucher.get("VCHTYPE", "")
        return ""


def validate_xml_preflight(xml: str) -> dict:
    """Convenience function for API usage."""
    validator = XMLPreFlightValidator(xml)
    return validator.validate().to_dict()
