"""XMLValidator — structural XML checks, golden file comparison, and Tally compatibility."""

import os
import re
from pathlib import Path
from typing import Optional

from validators.base import ValidationResult, ValidationScore


class XMLValidator:
    """Validates generated XML against structural, content, and golden-file rules."""

    def __init__(self, golden_dir: Optional[str] = None):
        self.golden_dir = golden_dir or self._default_golden_dir()

    def _default_golden_dir(self) -> str:
        return str(Path(__file__).parent.parent / "golden")

    # ------------------------------------------------------------------ #
    # Structure validation
    # ------------------------------------------------------------------ #

    def validate_structure(self, xml_str: str) -> ValidationResult:
        """Rule 1-25: XML structural integrity checks."""
        result = ValidationResult()

        if not xml_str:
            result.add_error("xml_empty", "XML content is empty", category="xml")
            return result

        # Declaration
        if not xml_str.strip().startswith("<?xml"):
            result.add_error("xml_declaration", "Missing XML declaration (<?xml ...?>)", category="xml")

        # Envelope
        if "<ENVELOPE>" not in xml_str:
            result.add_error("xml_envelope", "Missing <ENVELOPE> root element", category="xml")
        envelopes = re.findall(r"<ENVELOPE>", xml_str)
        if len(envelopes) < 1:
            result.add_error("xml_envelope_count", "No ENVELOPE found", category="xml")
        elif len(envelopes) > 2:
            result.add_warning(f"Multiple ENVELOPEs ({len(envelopes)}) — expected 1-2", category="xml")

        # HEADER and BODY
        if "<HEADER>" not in xml_str:
            result.add_error("xml_header", "Missing <HEADER> in envelope", category="xml")
        if "<BODY>" not in xml_str:
            result.add_error("xml_body", "Missing <BODY> in envelope", category="xml")
        if "<TALLYREQUEST>" not in xml_str:
            result.add_error("xml_tallyrequest", "Missing <TALLYREQUEST>", category="xml")

        # Voucher
        voucher_match = re.search(r'<VOUCHER\s+[^>]*VCHTYPE="([^"]+)"', xml_str)
        if not voucher_match:
            result.add_error("xml_voucher", "Missing <VOUCHER VCHTYPE=\"...\">", category="xml")
        else:
            vchtype = voucher_match.group(1)
            result.add_info(f"Voucher type: {vchtype}", category="xml")

        # Voucher type master
        vt_match = re.search(r'<VOUCHERTYPE\s+[^>]*NAME="([^"]+)"', xml_str)
        if vt_match:
            result.add_info(f"Voucher type master: {vt_match.group(1)}", category="xml")
        else:
            result.add_warning("No VOUCHERTYPE master — Tally may reject if type doesn't exist", category="xml")

        # Mandatory tags in voucher
        voucher_section = self._extract_voucher_section(xml_str)
        if voucher_section:
            self._check_voucher_tags(voucher_section, result)

        return result

    def _extract_voucher_section(self, xml_str: str) -> Optional[str]:
        """Extract the voucher section for detailed checks."""
        envelopes = re.findall(r"<ENVELOPE>.*?</ENVELOPE>", xml_str, re.DOTALL)
        if not envelopes:
            return None
        if len(envelopes) >= 2:
            return envelopes[-1]
        # If only one envelope, it might contain both masters and voucher
        # Check if it has VOUCHER
        if "<VOUCHER" in envelopes[0]:
            return envelopes[0]
        return None

    def _check_voucher_tags(self, section: str, result: ValidationResult):
        """Check mandatory tags within voucher section."""
        mandatory_tags = {
            "DATE": "Voucher date",
            "VOUCHERNUMBER": "Voucher number",
            "PARTYLEDGERNAME": "Party ledger name",
            "ALLLEDGERENTRIES.LIST": "Ledger entries",
        }
        for tag, label in mandatory_tags.items():
            if f"<{tag}>" not in section:
                result.add_error(f"xml_missing_{tag.lower()}", f"Missing <{tag}> ({label})", category="xml")
            else:
                result.add_info(f"<{tag}> present: {label}", category="xml")

        # ISINVOICE present and valid
        is_inv = re.search(r"<ISINVOICE>([^<]+)</ISINVOICE>", section)
        if is_inv:
            val = is_inv.group(1)
            if val not in ("Yes", "No"):
                result.add_error("xml_isinvoice", f"ISINVOICE must be Yes/No, got '{val}'", category="xml")
            else:
                result.add_info(f"ISINVOICE={val}", category="xml")

        # Check inventory entries match ISINVOICE
        has_inv_entries = "ALLINVENTORYENTRIES.LIST" in section
        if is_inv and is_inv.group(1) == "Yes" and not has_inv_entries:
            result.add_warning("ISINVOICE=Yes but no ALLINVENTORYENTRIES.LIST", category="xml")
        if is_inv and is_inv.group(1) == "No" and has_inv_entries:
            result.add_warning("ISINVOICE=No but ALLINVENTORYENTRIES.LIST present", category="xml")

        # SVCURRENTCOMPANY
        if "<SVCURRENTCOMPANY>" not in section:
            result.add_error("xml_svcurrentcompany", "Missing <SVCURRENTCOMPANY> — Tally won't know which company", category="xml")

        # All entries have ISDEEMEDPOSITIVE and AMOUNT
        entries = re.findall(
            r"<ALLLEDGERENTRIES\.LIST>.*?</ALLLEDGERENTRIES\.LIST>",
            section, re.DOTALL,
        )
        for i, entry in enumerate(entries):
            if "<ISDEEMEDPOSITIVE>" not in entry:
                result.add_error(f"xml_entry_{i}_deemed", f"Entry {i+1} missing ISDEEMEDPOSITIVE", category="xml")
            if "<AMOUNT>" not in entry:
                result.add_error(f"xml_entry_{i}_amount", f"Entry {i+1} missing AMOUNT", category="xml")
            if "<LEDGERNAME>" not in entry:
                result.add_error(f"xml_entry_{i}_ledger", f"Entry {i+1} missing LEDGERNAME", category="xml")

    # ------------------------------------------------------------------ #
    # Balance validation
    # ------------------------------------------------------------------ #

    def validate_balance(self, xml_str: str) -> ValidationResult:
        """Rule 26-30: XML debit/credit balance check."""
        result = ValidationResult()
        section = self._extract_voucher_section(xml_str)
        if not section:
            result.add_error("xml_no_voucher", "Cannot extract voucher section for balance check", category="xml")
            return result

        cleaned = re.sub(r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", section, flags=re.DOTALL)
        cleaned = re.sub(r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>", "", cleaned, flags=re.DOTALL)

        entries = re.findall(
            r"<ALLLEDGERENTRIES\.LIST>.*?<ISDEEMEDPOSITIVE>(.*?)</ISDEEMEDPOSITIVE>.*?<AMOUNT>(-?\d+\.?\d*)</AMOUNT>.*?</ALLLEDGERENTRIES\.LIST>",
            cleaned, re.DOTALL,
        )

        if entries:
            debit_total = 0.0
            credit_total = 0.0
            for deemed, amt_str in entries:
                amt = float(amt_str)
                if deemed.strip() == "Yes":
                    debit_total += amt
                else:
                    credit_total += amt
            balance = debit_total + credit_total
            if abs(balance) > 0.05:
                result.add_error("xml_balance", f"XML unbalanced: Dr Rs.{debit_total:.2f} + Cr Rs.{credit_total:.2f} = Rs.{balance:.2f}", category="xml")
            else:
                result.add_info(f"XML balanced: Dr Rs.{debit_total:.2f} + Cr Rs.{credit_total:.2f} = Rs.{balance:.2f}", category="xml")
        else:
            result.add_error("xml_no_entries", "No ALLLEDGERENTRIES.LIST found in voucher", category="xml")

        return result

    # ------------------------------------------------------------------ #
    # Masters validation
    # ------------------------------------------------------------------ #

    def validate_masters(self, xml_str: str) -> ValidationResult:
        """Rule 31-40: Master creation validation."""
        result = ValidationResult()

        # Check voucher type master
        if "<VOUCHERTYPE" in xml_str:
            result.add_info("Voucher type master included", category="masters")
        else:
            result.add_warning("No VOUCHERTYPE master — Tally may reject if type is missing", category="masters")

        # Check stock group for goods
        if "<STOCKGROUP" in xml_str:
            result.add_info("Stock group master included", category="masters")

        # Check stock items
        stock_items = re.findall(r"<STOCKITEM\s+[^>]*NAME=\"([^\"]+)\"", xml_str)
        if stock_items:
            result.add_info(f"Stock item masters: {len(stock_items)} created ({', '.join(stock_items[:3])})", category="masters")

        # Check ledgers
        ledgers = re.findall(r"<LEDGER\s+[^>]*NAME=\"([^\"]+)\"", xml_str)
        if ledgers:
            result.add_info(f"Ledger masters: {len(ledgers)} created ({', '.join(ledgers[:5])})", category="masters")

        # Check for duplicate ledgers
        if len(ledgers) != len(set(ledgers)):
            result.add_warning("Duplicate ledger names in masters", category="masters")

        return result

    # ------------------------------------------------------------------ #
    # Golden file comparison
    # ------------------------------------------------------------------ #

    def check_golden(self, test_name: str, generated_xml: str) -> ValidationResult:
        """Compare generated XML against golden reference.
        Creates golden file if it doesn't exist (first-run)."""
        result = ValidationResult()
        golden_path = Path(self.golden_dir) / f"{test_name}.xml"

        if not golden_path.exists():
            # First run — create golden file
            golden_path.parent.mkdir(parents=True, exist_ok=True)
            golden_path.write_text(generated_xml, encoding="utf-8")
            result.add_info(f"Golden file created: {golden_path}", category="golden")
            return result

        golden = golden_path.read_text(encoding="utf-8")

        # Normalize for comparison (remove variable content)
        def normalize(xml: str) -> str:
            # Normalize dates
            xml = re.sub(r"<DATE>\d{8}</DATE>", "<DATE>YYYYMMDD</DATE>", xml)
            # Normalize whitespace
            xml = re.sub(r">\s+<", "><", xml)
            return xml.strip()

        g_norm = normalize(golden)
        x_norm = normalize(generated_xml)

        if g_norm == x_norm:
            result.add_info(f"Golden match: {test_name}", category="golden")
        else:
            # Find differences
            g_lines = g_norm.split("\n")
            x_lines = x_norm.split("\n")
            diffs = []
            for i, (g, x) in enumerate(zip(g_lines, x_lines)):
                if g != x:
                    diffs.append(f"Line {i+1}: golden ≠ generated")
                    if len(diffs) >= 3:
                        break
            if not diffs and len(g_lines) != len(x_lines):
                diffs.append(f"Line count: golden {len(g_lines)} vs generated {len(x_lines)}")
            result.add_warning(f"Golden mismatch: {test_name}. {'; '.join(diffs[:3])}", category="golden")

        return result

    # ------------------------------------------------------------------ #
    # Full validation pipeline
    # ------------------------------------------------------------------ #

    def validate(self, xml_str: str, test_name: Optional[str] = None) -> ValidationResult:
        """Run all XML validations."""
        result = self.validate_structure(xml_str)
        balance_result = self.validate_balance(xml_str)
        for c in balance_result.checks:
            result.checks.append(c)
        masters_result = self.validate_masters(xml_str)
        for c in masters_result.checks:
            result.checks.append(c)
        if test_name:
            golden_result = self.check_golden(test_name, xml_str)
            for c in golden_result.checks:
                result.checks.append(c)

        result.passed = all(c.passed for c in result.checks if c.severity == "error")
        return result

    def score(self, xml_str: str, test_name: Optional[str] = None) -> ValidationScore:
        result = self.validate(xml_str, test_name)
        return ValidationScore.from_validation(result)
