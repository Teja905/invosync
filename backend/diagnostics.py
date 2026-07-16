"""Smart Pre-Flight Diagnostics — checks Tally conditions BEFORE sync.
Every check returns structured data: title, status, message, fix_suggestion.
CAs never need to dig through .imp files again."""

import re
from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel


class PreFlightCheck(BaseModel):
    check_id: str
    title: str
    status: str  # "pass" | "fail" | "warn"
    message: str
    fix_suggestion: str = ""
    detail: str = ""


class MissingMaster(BaseModel):
    type: str  # "group" | "ledger"
    name: str
    parent: str = ""
    reason: str = ""
    confidence: int = 95


class PreFlightReport(BaseModel):
    safe_to_import: bool
    summary: str
    total_checks: int
    passed: int
    failed: int
    warnings: int
    checks: list[PreFlightCheck]
    masters_to_create: list[str] = []
    missing_masters: list[MissingMaster] = []


FINANCIAL_YEAR_MONTHS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    # year → ((start_month, start_day), (end_month, end_day))
    # Default India FY: April 1 – March 31
    2024: ((4, 1), (3, 31)),
    2025: ((4, 1), (3, 31)),
    2026: ((4, 1), (3, 31)),
    2027: ((4, 1), (3, 31)),
}

ALLOWED_GST_SLABS = [0, 0.1, 0.25, 3, 5, 12, 18, 28]


def _get_fy_range(invoice_date: date) -> tuple[date, date]:
    """Get financial year start/end for a given date."""
    fy_start_year = invoice_date.year
    if invoice_date.month < 4:
        fy_start_year -= 1
    start = date(fy_start_year, 4, 1)
    end = date(fy_start_year + 1, 3, 31)
    return start, end


class PreFlightDiagnostics:
    """Runs all pre-flight checks on invoice data + cached Tally masters."""

    def __init__(self, invoice_data: dict, ledger_cache: list, group_cache: list,
                 voucher_type_cache: list, stock_item_cache: list,
                 user_config: Optional[dict] = None):
        self.data = invoice_data
        self.ledger_cache = ledger_cache
        self.group_cache = group_cache
        self.voucher_type_cache = voucher_type_cache
        self.stock_item_cache = stock_item_cache
        self.user_config = user_config or {}

    def _ledger_names(self) -> set[str]:
        names = set()
        for entry in self.ledger_cache:
            if isinstance(entry, dict):
                names.add(entry.get("name", "").lower())
            else:
                names.add(entry.lower() if isinstance(entry, str) else str(entry).lower())
        return names

    def _ledger_parents(self) -> set[str]:
        parents = set()
        for entry in self.ledger_cache:
            if isinstance(entry, dict):
                p = entry.get("parent", "")
                if p:
                    parents.add(p.lower())
        return parents

    def _group_names(self) -> set[str]:
        return {g.lower() if isinstance(g, str) else g.get("name", "").lower() for g in self.group_cache if g}

    def run_all(self) -> PreFlightReport:
        checks: list[PreFlightCheck] = []
        checks.append(self._check_vendor_name())
        checks.append(self._check_invoice_number())
        checks.append(self._check_date_range())
        checks.append(self._check_name_trim())
        checks.append(self._check_voucher_type())
        checks.append(self._check_ledgers())
        checks.append(self._check_groups())
        checks.append(self._check_gst_rates())
        checks.append(self._check_vendor_gstin())

        passed = sum(1 for c in checks if c.status == "pass")
        failed = sum(1 for c in checks if c.status == "fail")
        warnings = sum(1 for c in checks if c.status == "warn")
        safe = failed == 0

        summary = "All checks passed" if safe else f"{failed} check(s) failed — review issues before import"

        return PreFlightReport(
            safe_to_import=safe,
            summary=summary,
            total_checks=len(checks),
            passed=passed,
            failed=failed,
            warnings=warnings,
            checks=checks,
            masters_to_create=self._compute_masters_to_create(),
            missing_masters=self._compute_missing_masters(),
        )

    # ---- Individual checks ----

    def _check_vendor_name(self) -> PreFlightCheck:
        name = (self.data.get("vendor_name") or "").strip()
        if not name:
            return PreFlightCheck(
                check_id="vendor_name", title="Vendor Name",
                status="fail", message="Vendor name is missing",
                fix_suggestion="Enter the vendor/supplier name as it appears on the invoice",
            )
        return PreFlightCheck(
            check_id="vendor_name", title="Vendor Name",
            status="pass", message=f"Vendor: {name}",
        )

    def _check_invoice_number(self) -> PreFlightCheck:
        inv_no = (self.data.get("invoice_number") or "").strip()
        if not inv_no:
            return PreFlightCheck(
                check_id="invoice_number", title="Invoice Number",
                status="fail", message="Invoice number is missing",
                fix_suggestion="Enter the invoice number as shown on the document",
            )
        return PreFlightCheck(
            check_id="invoice_number", title="Invoice Number",
            status="pass", message=f"Invoice #: {inv_no}",
        )

    def _check_date_range(self) -> PreFlightCheck:
        raw_date = (self.data.get("invoice_date") or "").strip()
        if not raw_date:
            return PreFlightCheck(
                check_id="date_range", title="Invoice Date",
                status="fail", message="Invoice date is missing",
                fix_suggestion="Enter the invoice date in DD/MM/YYYY or YYYY-MM-DD format",
            )
        parsed = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(raw_date, fmt).date()
                break
            except ValueError:
                continue
        if not parsed:
            return PreFlightCheck(
                check_id="date_range", title="Invoice Date",
                status="fail", message=f"Could not parse date: '{raw_date}'",
                fix_suggestion="Use DD/MM/YYYY format (e.g., 15/04/2025)",
            )
        fy_start, fy_end = _get_fy_range(parsed)
        if parsed < fy_start or parsed > fy_end:
            fy_label = f"{fy_start.year}-{fy_end.year}"
            return PreFlightCheck(
                check_id="date_range", title="Invoice Date",
                status="fail",
                message=f"Date {parsed} is outside current financial year ({fy_label})",
                fix_suggestion=f"Tally's current financial year is {fy_label}. Verify the date is correct, or adjust Tally's financial year settings.",
            )
        return PreFlightCheck(
            check_id="date_range", title="Invoice Date",
            status="pass", message=f"Date {parsed} is within financial year",
        )

    def _check_name_trim(self) -> PreFlightCheck:
        """Check for leading/trailing spaces in key name fields — common Tally import killer."""
        issues = []
        for field, label in [("vendor_name", "Vendor Name"), ("invoice_number", "Invoice Number")]:
            val = self.data.get(field, "")
            if isinstance(val, str) and val != val.strip():
                issues.append(f"{label} has leading/trailing spaces: '{val}'")
        if issues:
            return PreFlightCheck(
                check_id="name_trim", title="Name Trimming",
                status="fail",
                message="; ".join(issues),
                fix_suggestion="Remove leading and trailing spaces from all text fields. Tally is strict about extra whitespace.",
            )
        return PreFlightCheck(
            check_id="name_trim", title="Name Trimming",
            status="pass", message="No extra whitespace in name fields",
        )

    def _check_voucher_type(self) -> PreFlightCheck:
        vtype = (self.data.get("voucher_type") or "Purchase").strip()
        if self.voucher_type_cache:
            vt_lower = {v.lower() for v in self.voucher_type_cache}
            if vtype.lower() not in vt_lower:
                vt_list = ", ".join(sorted(self.voucher_type_cache)[:10])
                return PreFlightCheck(
                    check_id="voucher_type_exists", title="Voucher Type",
                    status="fail",
                    message=f"Voucher type '{vtype}' not found in Tally",
                    fix_suggestion=f"Voucher types in Tally: {vt_list}. Create '{vtype}' in Tally or select an existing type.",
                )
        return PreFlightCheck(
            check_id="voucher_type_exists", title="Voucher Type",
            status="pass", message=f"Voucher type '{vtype}' is available in Tally",
        )

    def _check_ledgers(self) -> PreFlightCheck:
        ledger_names = self._ledger_names()
        if not ledger_names:
            return PreFlightCheck(
                check_id="ledger_exists", title="Ledger Check",
                status="warn", message="No ledger cache available — cannot verify ledger existence",
                fix_suggestion="Connect and sync Tally masters first via the connector",
            )

        missing = []
        # Vendor ledger
        vendor = (self.data.get("vendor_name") or "").strip()
        if vendor and vendor.lower() not in ledger_names:
            missing.append(f"Vendor ledger '{vendor}'")

        # Purchase/Sales ledgers from config
        purchase = self.user_config.get("purchase_ledger", "Purchase")
        if purchase.lower() not in ledger_names:
            missing.append(f"Purchase ledger '{purchase}'")

        sales = self.user_config.get("sales_ledger", "Sales")
        if sales.lower() not in ledger_names:
            missing.append(f"Sales ledger '{sales}'")

        # Bank ledger
        bank = self.user_config.get("bank_ledger", "Bank")
        if bank.lower() not in ledger_names:
            missing.append(f"Bank ledger '{bank}'")

        # Line item description-based ledgers
        for item in self.data.get("line_items") or []:
            desc = (item.get("description") or "").strip()
            if desc and desc.lower() not in ledger_names:
                missing.append(f"Expense ledger '{desc}' (line item)")

        if missing:
            return PreFlightCheck(
                check_id="ledger_exists", title="Ledger Check",
                status="fail",
                message=f"{len(missing)} ledger(s) not found in Tally",
                detail="\n".join(missing),
                fix_suggestion="These ledgers will be auto-created during import. Verify they don't already exist under different names.",
            )
        return PreFlightCheck(
            check_id="ledger_exists", title="Ledger Check",
            status="pass", message="All referenced ledgers exist in Tally",
        )

    def _check_groups(self) -> PreFlightCheck:
        group_names = self._group_names()
        ledger_parents = self._ledger_parents()
        if not ledger_parents:
            return PreFlightCheck(
                check_id="group_exists", title="Parent Group Check",
                status="warn", message="No ledger parent data available — skipping group check",
                fix_suggestion="Sync Tally masters with parent groups enabled (requires connector v3.2+)",
            )

        if not group_names:
            return PreFlightCheck(
                check_id="group_exists", title="Parent Group Check",
                status="warn", message="No group cache available — cannot verify parent groups",
                fix_suggestion="Sync Tally group masters via the connector",
            )

        missing = []
        for parent in sorted(ledger_parents):
            if parent not in group_names:
                # Check if it's a well-known Tally group (might not be in export)
                if parent not in ("primary",):
                    missing.append(parent)

        if missing:
            return PreFlightCheck(
                check_id="group_exists", title="Parent Group Check",
                status="fail" if len(missing) > 2 else "warn",
                message=f"{len(missing)} parent group(s) referenced by ledgers not found in Tally",
                detail="\n".join(missing),
                fix_suggestion="These groups will be auto-created during import. If they already exist, verify the exact name matches Tally.",
            )
        return PreFlightCheck(
            check_id="group_exists", title="Parent Group Check",
            status="pass", message="All parent groups exist in Tally",
        )

    def _check_gst_rates(self) -> PreFlightCheck:
        issues = []
        for item in self.data.get("line_items") or []:
            for tax in item.get("tax_entries") or []:
                rate = abs(float(tax.get("rate") or 0))
                if rate > 0 and rate not in ALLOWED_GST_SLABS:
                    # Check if it's a split rate (CGST 9% = 18% total)
                    if rate * 2 not in ALLOWED_GST_SLABS and rate not in [r / 2 for r in ALLOWED_GST_SLABS]:
                        issues.append(f"Rate {rate}% in '{item.get('description', '?')}' is not a valid GST slab ({ALLOWED_GST_SLABS})")
        if issues:
            return PreFlightCheck(
                check_id="gst_rates", title="GST Rate Validation",
                status="fail", message="; ".join(issues),
                fix_suggestion=f"Allowed GST slabs: {ALLOWED_GST_SLABS}%. Verify the rate with the original invoice.",
            )
        return PreFlightCheck(
            check_id="gst_rates", title="GST Rate Validation",
            status="pass", message="All GST rates are valid",
        )

    def _check_vendor_gstin(self) -> PreFlightCheck:
        gstin = (self.data.get("vendor_gstin") or self.data.get("gstin") or "").strip().upper()
        if not gstin:
            return PreFlightCheck(
                check_id="vendor_gstin", title="Vendor GSTIN",
                status="warn", message="Vendor GSTIN is missing — intra-state assumed",
                fix_suggestion="If this is an inter-state purchase, the GSTIN is needed for correct IGST routing. Add it if available.",
            )
        # Length check
        if len(gstin) != 15:
            return PreFlightCheck(
                check_id="vendor_gstin", title="Vendor GSTIN",
                status="fail", message=f"Invalid GSTIN length: {len(gstin)} (expected 15 characters)",
                fix_suggestion="GSTIN must be exactly 15 characters: 2-digit state code + 10-digit PAN + 1 entity code + 1 Z + 1 checksum",
            )
        # State code check
        state_code = gstin[:2]
        if not state_code.isdigit() or int(state_code) < 1 or int(state_code) > 37:
            return PreFlightCheck(
                check_id="vendor_gstin", title="Vendor GSTIN",
                status="fail", message=f"Invalid state code '{state_code}' in GSTIN — must be 01-37",
                fix_suggestion="The first 2 digits of the GSTIN must be a valid Indian state code (01-37)",
            )
        # PAN check
        pan = gstin[2:12]
        if not re.match(r'^[A-Z]{5}\d{4}[A-Z]$', pan):
            return PreFlightCheck(
                check_id="vendor_gstin", title="Vendor GSTIN",
                status="warn", message=f"GSTIN PAN '{pan}' has unexpected format",
                fix_suggestion="Verify the GSTIN is correct — the PAN portion should be 5 letters + 4 digits + 1 letter",
            )
        return PreFlightCheck(
            check_id="vendor_gstin", title="Vendor GSTIN",
            status="pass", message=f"GSTIN {gstin} is valid",
        )

    def _compute_masters_to_create(self) -> list[str]:
        masters = set()
        ledger_names = self._ledger_names()
        vendor = (self.data.get("vendor_name") or "").strip()
        if vendor and vendor.lower() not in ledger_names:
            masters.add(f"Ledger: {vendor}")
        for item in self.data.get("line_items") or []:
            desc = (item.get("description") or "").strip()
            if desc and desc.lower() not in ledger_names:
                masters.add(f"Ledger: {desc}")
        vtype = (self.data.get("voucher_type") or "Purchase").strip()
        if self.voucher_type_cache and vtype.lower() not in {v.lower() for v in self.voucher_type_cache}:
            masters.add(f"Voucher Type: {vtype}")
        return sorted(masters)

    def _compute_missing_masters(self) -> list[MissingMaster]:
        """Return structured list of missing groups and ledgers with suggested parents.
        Used by the frontend to show the 'Create All' dialog."""
        from constants.tally_groups import GROUP_TO_ROLE, UNIVERSAL_GROUPS
        from ledger_mapping import LedgerDiscoveryEngine

        def _is_universal(name: str) -> bool:
            return name.strip().lower() in {g.lower() for g in UNIVERSAL_GROUPS}

        def _confidence(parent: str) -> int:
            return 95 if _is_universal(parent) else 85

        missing: list[MissingMaster] = []
        ledger_names = self._ledger_names()
        group_names = self._group_names()
        engine = LedgerDiscoveryEngine()
        seen_groups: set[str] = set()
        corrections = (self.user_config or {}).get("correction_memory", {}) or {}

        # Check vendor ledger
        vendor = (self.data.get("vendor_name") or "").strip()
        if vendor and vendor.lower() not in ledger_names:
            expected_parent = "Sundry Creditors"
            if expected_parent.lower() not in group_names and expected_parent.lower() not in seen_groups:
                missing.append(MissingMaster(
                    type="group", name=expected_parent, parent="Current Liabilities",
                    reason="Vendor ledger needs Sundry Creditors group",
                    confidence=95,
                ))
                seen_groups.add(expected_parent.lower())
            missing.append(MissingMaster(
                type="ledger", name=vendor, parent=expected_parent,
                reason="Vendor ledger from invoice",
                confidence=95,
            ))

        # Check line item ledgers
        for item in self.data.get("line_items") or []:
            desc = (item.get("description") or "").strip()
            if desc and desc.lower() not in ledger_names:
                expected_parent = engine._suggest_parent_for_ledger(desc, corrections=corrections)
                conf = _confidence(expected_parent or "Purchase Accounts")
                if expected_parent and expected_parent.lower() not in group_names and expected_parent.lower() not in seen_groups:
                    # Find universal parent for this group
                    universal_parent = "Primary"
                    for g, r in GROUP_TO_ROLE.items():
                        if g.lower() == expected_parent.lower():
                            universal_parent = "Expenses"
                            break
                    missing.append(MissingMaster(
                        type="group", name=expected_parent, parent=universal_parent,
                        reason=f"Group needed for '{desc}' ledger",
                        confidence=min(conf, 90),
                    ))
                    seen_groups.add(expected_parent.lower())
                missing.append(MissingMaster(
                    type="ledger", name=desc, parent=expected_parent or "Purchase Accounts",
                    reason="Line item ledger from invoice",
                    confidence=conf,
                ))

        # Check purchase ledger from config
        purchase = self.user_config.get("purchase_ledger", "Purchase")
        if purchase.lower() not in ledger_names:
            expected_parent = "Purchase Accounts"
            if expected_parent.lower() not in group_names and expected_parent.lower() not in seen_groups:
                missing.append(MissingMaster(
                    type="group", name=expected_parent, parent="Direct Expenses",
                    reason="Purchase ledger needs Purchase Accounts group",
                    confidence=95,
                ))
                seen_groups.add(expected_parent.lower())
            if not any(m.name == purchase and m.type == "ledger" for m in missing):
                missing.append(MissingMaster(
                    type="ledger", name=purchase, parent=expected_parent,
                    reason="Default purchase ledger from config",
                    confidence=95,
                ))

        return missing


def check_date_range(raw_date: str) -> tuple[Optional[bool], str]:
    """Utility: standalone date range check. Returns (passes, message)."""
    if not raw_date:
        return None, "No date provided"
    parsed = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(raw_date, fmt).date()
            break
        except ValueError:
            continue
    if not parsed:
        return None, f"Cannot parse date '{raw_date}'"
    fy_start, fy_end = _get_fy_range(parsed)
    if parsed < fy_start or parsed > fy_end:
        return False, f"Date {parsed} is outside FY {fy_start.year}-{fy_end.year}"
    return True, f"Date {parsed} is within FY"
