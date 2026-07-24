"""TallySimulator — pre-flight check that emulates Tally Prime import validation.

Every check here catches issues that Tally would silently reject or partially import.
Runs on every XML generation automatically as part of the pipeline.
"""

import re
from dataclasses import dataclass

from validators.base import ValidationResult, ValidationScore


@dataclass
class TallySimulator:
    """Simulates Tally Prime import validation without needing a live Tally instance.

    Checks:
      - Required XML tags (declaration, envelope, header, body, voucher)
      - Voucher type master existence
      - Ledger references (every voucher entry has a matching master creation)
      - Stock item references (every inventory entry has a matching master)
      - Voucher balance (debits + credits = 0)
      - ISDEEMEDPOSITIVE correctness
      - Party ledger has ISPARTYLEDGER
      - Bill allocations for party entries
      - GST ledger naming conventions
      - Company name presence
    """

    def simulate_import(self, xml_str: str, expected_vchtype: str = "") -> ValidationResult:
        """Run all Tally import checks against the XML string.

        Args:
            xml_str: The full XML content (may include masters envelope + voucher envelope).
            expected_vchtype: If provided, checks VCHTYPE matches.

        Returns:
            ValidationResult with pass/fail per check.
        """
        result = ValidationResult()

        if not xml_str:
            result.add_error("xml_empty", "XML content is empty — nothing to import", category="tally")
            return result

        # ── 1. Structure: declaration, envelopes ───────────────── #
        if not xml_str.strip().startswith("<?xml"):
            result.add_error("xml_declaration", "Missing XML declaration — Tally may reject", category="tally")
        if "<ENVELOPE>" not in xml_str:
            result.add_error("xml_envelope", "No <ENVELOPE> — Tally won't process this", category="tally")

        # Parse envelope sections
        envelopes = re.findall(r"<ENVELOPE>(.*?)</ENVELOPE>", xml_str, re.DOTALL)
        if not envelopes:
            result.add_error("xml_envelopes", "Cannot parse ENVELOPE sections", category="tally")
            return result

        masters_xml = ""
        voucher_xml = ""
        for env in envelopes:
            if 'VOUCHERTYPE NAME=' in env or 'LEDGER NAME=' in env:
                masters_xml = env
            if "<VOUCHER " in env:
                voucher_xml = env

        # ── 2. Voucher type check ──────────────────────────────── #
        has_voucher_type_master = "<VOUCHERTYPE" in masters_xml
        voucher_type_in_env = ""
        vt_match = re.search(r'<VOUCHER\s+[^>]*VCHTYPE="([^"]+)"', voucher_xml)
        if vt_match:
            voucher_type_in_env = vt_match.group(1)
            result.add_info(f"Voucher type in envelope: {voucher_type_in_env}", category="tally")

        if not has_voucher_type_master:
            result.add_warning(
                f"No VOUCHERTYPE master for '{voucher_type_in_env}' — "
                f"Tally will reject if this type doesn't already exist in company data",
                category="tally",
            )
        else:
            vt_master_match = re.search(r'<VOUCHERTYPE\s+[^>]*NAME="([^"]+)"', masters_xml)
            if vt_master_match:
                result.add_info(f"Voucher type master created: {vt_master_match.group(1)}", category="tally")

        if expected_vchtype and voucher_type_in_env != expected_vchtype:
            result.add_error(
                "vchtype_mismatch",
                f"Expected VCHTYPE='{expected_vchtype}', got '{voucher_type_in_env}'",
                category="tally",
            )

        # ── 3. Ledger references ───────────────────────────────── #
        created_ledgers = set(re.findall(r'<LEDGER\s+[^>]*NAME="([^"]+)"', masters_xml))
        referenced_ledgers = set(re.findall(r"<LEDGERNAME>([^<]+)</LEDGERNAME>", voucher_xml))

        if referenced_ledgers:
            missing = referenced_ledgers - created_ledgers
            if missing:
                result.add_error(
                    "ledger_refs",
                    f"Ledgers referenced in voucher but not created as masters: {', '.join(sorted(missing)[:5])}",
                    category="tally",
                )
            else:
                result.add_info(f"All {len(referenced_ledgers)} referenced ledgers have masters", category="tally")

        # ── 4. Stock item references ───────────────────────────── #
        created_stock_items = set(re.findall(r'<STOCKITEM\s+[^>]*NAME="([^"]+)"', masters_xml))
        referenced_stock_items = set(
            re.findall(r"<STOCKITEMNAME>([^<]+)</STOCKITEMNAME>", voucher_xml)
        )

        if referenced_stock_items:
            missing_stock = referenced_stock_items - created_stock_items
            if missing_stock:
                result.add_error(
                    "stock_refs",
                    f"Stock items referenced in voucher but not created: {', '.join(sorted(missing_stock)[:5])}",
                    category="tally",
                )
            else:
                result.add_info(f"All {len(referenced_stock_items)} referenced stock items have masters", category="tally")

        # ── 5. Voucher balance ─────────────────────────────────── #
        balance_result = self._check_voucher_balance(voucher_xml)
        for c in balance_result.checks:
            result.checks.append(c)
        if not balance_result.passed:
            result.passed = False

        # ── 6. ISDEEMEDPOSITIVE correctness ───────────────────── #
        entry_pattern = re.findall(
            r"<ALLLEDGERENTRIES\.LIST>(.*?)</ALLLEDGERENTRIES\.LIST>",
            voucher_xml, re.DOTALL,
        )
        for i, entry in enumerate(entry_pattern):
            deemed = re.search(r"<ISDEEMEDPOSITIVE>([^<]+)</ISDEEMEDPOSITIVE>", entry)
            amount = re.search(r"<AMOUNT>(-?\d+\.?\d*)</AMOUNT>", entry)
            ledger = re.search(r"<LEDGERNAME>([^<]+)</LEDGERNAME>", entry)

            if not deemed:
                result.add_error(f"entry_{i}_deemed", f"Entry {i+1}: missing ISDEEMEDPOSITIVE", category="tally")
                continue
            deemed_val = deemed.group(1)
            if deemed_val not in ("Yes", "No"):
                result.add_error(f"entry_{i}_deemed_val", f"Entry {i+1}: ISDEEMEDPOSITIVE='{deemed_val}' (must be Yes/No)", category="tally")

            if amount and ledger:
                amt = float(amount.group(1))
                lname = ledger.group(1)
                if deemed_val == "No":
                    # Credit entries should have negative amounts for non-party
                    is_party = "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>" in entry
                    if not is_party and amt >= 0:
                        result.add_warning(
                            f"Entry '{lname}': ISDEEMEDPOSITIVE=No but amount >= 0 ({amt})",
                            category="tally",
                        )

        # ── 7. Party ledger has ISPARTYLEDGER ──────────────────── #
        for i, entry in enumerate(entry_pattern):
            ledger_name = re.search(r"<LEDGERNAME>([^<]+)</LEDGERNAME>", entry)
            is_party = "<ISPARTYLEDGER>" in entry
            if is_party and ledger_name:
                pval = re.search(r"<ISPARTYLEDGER>([^<]+)</ISPARTYLEDGER>", entry)
                if pval and pval.group(1) == "Yes":
                    result.add_info(f"Party ledger: {ledger_name.group(1)}", category="tally")

        # ── 8. Bill allocations for party entries ──────────────── #
        party_entries = [
            e for e in entry_pattern
            if re.search(r"<ISPARTYLEDGER>Yes</ISPARTYLEDGER>", e)
        ]
        for i, entry in enumerate(party_entries):
            has_billalloc = "<BILLALLOCATIONS.LIST>" in entry
            if not has_billalloc:
                ledger = re.search(r"<LEDGERNAME>([^<]+)</LEDGERNAME>", entry)
                lname = ledger.group(1) if ledger else f"Party entry {i+1}"
                result.add_warning(
                    f"No BILLALLOCATIONS for party ledger '{lname}' — "
                    f"Tally may not track outstanding properly",
                    category="tally",
                )

        # ── 9. GST ledger naming ───────────────────────────────── #
        gst_ledgers = [
            l for l in referenced_ledgers
            if any(kw in l.lower() for kw in ("cgst", "sgst", "igst"))
        ]
        for l in gst_ledgers:
            if "@" not in l and "%" not in l:
                result.add_warning(
                    f"GST ledger '{l}' doesn't include rate in name — "
                    f"Tally may not auto-identify the tax rate",
                    category="tally",
                )

        # ── 10. Company name ───────────────────────────────────── #
        if "<SVCURRENTCOMPANY>" in voucher_xml:
            company_match = re.search(r"<SVCURRENTCOMPANY>([^<]+)</SVCURRENTCOMPANY>", voucher_xml)
            if company_match:
                result.add_info(f"Company name present: {company_match.group(1)}", category="tally")
            else:
                result.add_error(
                    "company_missing",
                    "No <SVCURRENTCOMPANY> — Tally won't know which company to import into",
                    category="tally",
                )
        else:
            result.add_error(
                "company_missing",
                "No <SVCURRENTCOMPANY> — Tally won't know which company to import into",
                category="tally",
            )

        # ── 11. Date format ────────────────────────────────────── #
        date_match = re.search(r"<DATE>(\d{8})</DATE>", voucher_xml)
        if date_match:
            d = date_match.group(1)
            if not (len(d) == 8 and d.isdigit()):
                result.add_error(
                    "date_format",
                    f"Date '{d}' not in Tally format YYYYMMDD",
                    category="tally",
                )
            else:
                year = int(d[:4])
                month = int(d[4:6])
                day = int(d[6:8])
                if year < 2017 or year > 2030:
                    result.add_error(
                        "date_format",
                        f"Date '{d}' has suspicious year {year} — GST era is 2017+",
                        category="tally",
                    )
                elif 1 <= month <= 12 and 1 <= day <= 31:
                    result.add_info(f"Date format valid: {d}", category="tally")
                else:
                    result.add_error(
                        "date_format",
                        f"Date '{d}' has invalid month/day",
                        category="tally",
                    )
        else:
            result.add_error(
                "date_format",
                "No <DATE> found in voucher",
                category="tally",
            )

        # Summary
        passes = len([c for c in result.checks if c.passed and c.severity != "info"])
        fails = len([c for c in result.checks if not c.passed and c.severity == "error"])
        result.passed = fails == 0
        if fails > 0:
            result.add_info(
                f"Tally simulation: {passes} checks passed, {fails} issues that would cause import failure",
                category="tally",
            )
        else:
            result.add_info(f"Tally simulation: all {passes} checks passed — XML ready for import", category="tally")

        return result

    def _check_voucher_balance(self, section: str) -> ValidationResult:
        """Internal: voucher debit/credit balance check."""
        result = ValidationResult()

        cleaned = re.sub(
            r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>",
            "", section, flags=re.DOTALL,
        )
        cleaned = re.sub(
            r"<BILLALLOCATIONS\.LIST>.*?</BILLALLOCATIONS\.LIST>",
            "", cleaned, flags=re.DOTALL,
        )

        amounts = re.findall(
            r"<ALLLEDGERENTRIES\.LIST>.*?<AMOUNT>(-?\d+\.?\d*)</AMOUNT>.*?</ALLLEDGERENTRIES\.LIST>",
            cleaned, re.DOTALL,
        )

        if not amounts:
            result.add_error("no_entries", "No ledger entries in voucher — Tally needs at least 2", category="tally")
            return result

        total = sum(float(a) for a in amounts)
        if abs(total) > 0.05:
            result.add_error(
                "unbalanced",
                f"Voucher unbalanced: sum of ALL amounts = Rs.{total:.2f} (must be 0.00)",
                category="tally",
            )
        else:
            result.add_info(f"Voucher balanced: sum = Rs.{total:.2f}", category="tally")

        return result

    def score(self, xml_str: str, expected_vchtype: str = "") -> ValidationScore:
        result = self.simulate_import(xml_str, expected_vchtype)
        return ValidationScore.from_validation(result)
