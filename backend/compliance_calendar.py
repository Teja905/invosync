"""Compliance Calendar Engine — Auto-generate and track deadlines for Indian tax compliance.

Covers:
  - GST: GSTR-1, GSTR-3B, GSTR-9, GSTR-9C
  - TDS: 26Q, 27Q, 24Q filing + payment deadlines
  - ITR: Individual, Company, LLP filing deadlines
  - ROC: Annual return, financial statements
  - Professional Tax: State-wise deadlines
  - Advance Tax: Quarterly instalment deadlines

Deadline logic follows Income Tax Act, CGST Act, and respective rules
as amended for AY 2025-26 / FY 2024-25.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import calendar


@dataclass
class ComplianceTask:
    id: str
    title: str
    description: str
    due_date: str  # YYYY-MM-DD
    category: str  # gst, tds, it, roc, pt, advance_tax
    priority: str  # critical, high, medium, low
    frequency: str  # monthly, quarterly, annual, one-time
    client_id: Optional[str] = None
    client_name: Optional[str] = ""
    status: str = "pending"  # pending, in_progress, completed, overdue, extension_filed
    assigned_to: str = ""
    notes: str = ""
    is_recurring: bool = True
    advance_warning_days: int = 7  # Days before due date to start reminding

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date,
            "category": self.category,
            "priority": self.priority,
            "frequency": self.frequency,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "status": self.status,
            "assigned_to": self.assigned_to,
            "notes": self.notes,
            "is_recurring": self.is_recurring,
        }


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


# ===== GST Deadlines =====

def gst_gstr1_deadlines(fy_start: int) -> list[ComplianceTask]:
    """GSTR-1 filing deadlines for a financial year.

    GSTR-1 due: 11th of following month (for outward supplies)
    E.g., April 2024 return → due 11th May 2024
    """
    tasks = []
    months = [(fy_start, m) for m in range(4, 13)] + [(fy_start + 1, m) for m in range(1, 4)]
    for year, month in months:
        due_year, due_month = _next_month(year, month)
        tasks.append(ComplianceTask(
            id=f"gstr1-{year}-{month:02d}",
            title=f"GSTR-1 Filing — {calendar.month_name[month]} {year}",
            description=f"File GSTR-1 (outward supplies) for {calendar.month_name[month]} {year}",
            due_date=f"{due_year}-{due_month:02d}-11",
            category="gst",
            priority="critical",
            frequency="monthly",
        ))
    return tasks


def gst_gstr3b_deadlines(fy_start: int) -> list[ComplianceTask]:
    """GSTR-3B filing deadlines for a financial year.

    GSTR-3B due: 20th of following month (for summary return)
    """
    tasks = []
    months = [(fy_start, m) for m in range(4, 13)] + [(fy_start + 1, m) for m in range(1, 4)]
    for year, month in months:
        due_year, due_month = _next_month(year, month)
        tasks.append(ComplianceTask(
            id=f"gstr3b-{year}-{month:02d}",
            title=f"GSTR-3B Filing — {calendar.month_name[month]} {year}",
            description=f"File GSTR-3B (summary return) for {calendar.month_name[month]} {year}",
            due_date=f"{due_year}-{due_month:02d}-20",
            category="gst",
            priority="critical",
            frequency="monthly",
        ))
    return tasks


def gst_payment_deadlines(fy_start: int) -> list[ComplianceTask]:
    """GST payment deadlines — 20th of following month."""
    tasks = []
    months = [(fy_start, m) for m in range(4, 13)] + [(fy_start + 1, m) for m in range(1, 4)]
    for year, month in months:
        due_year, due_month = _next_month(year, month)
        tasks.append(ComplianceTask(
            id=f"gst-pay-{year}-{month:02d}",
            title=f"GST Payment — {calendar.month_name[month]} {year}",
            description=f"Deposit GST (CGST + SGST + IGST) for {calendar.month_name[month]} {year}",
            due_date=f"{due_year}-{due_month:02d}-20",
            category="gst",
            priority="critical",
            frequency="monthly",
        ))
    return tasks


def gst_annual_return_deadlines(fy_start: int) -> list[ComplianceTask]:
    """GSTR-9/9C annual return deadlines.

    GSTR-9 due: 31st December of following FY
    GSTR-9C (reconciliation): 31st December of following FY
    """
    return [
        ComplianceTask(
            id=f"gstr9-{fy_start}",
            title=f"GSTR-9 Annual Return — FY {fy_start}-{str(fy_start+1)[-2:]}",
            description=f"File GSTR-9 (annual return) for FY {fy_start}-{str(fy_start+1)[-2:]}",
            due_date=f"{fy_start + 1}-12-31",
            category="gst",
            priority="high",
            frequency="annual",
        ),
        ComplianceTask(
            id=f"gstr9c-{fy_start}",
            title=f"GSTR-9C Reconciliation — FY {fy_start}-{str(fy_start+1)[-2:]}",
            description=f"File GSTR-9C (reconciliation statement) for FY {fy_start}-{str(fy_start+1)[-2:]}",
            due_date=f"{fy_start + 1}-12-31",
            category="gst",
            priority="high",
            frequency="annual",
        ),
    ]


# ===== TDS Deadlines =====

def tds_quarterly_deadlines(fy_start: int) -> list[ComplianceTask]:
    """TDS return filing deadlines (26Q/27Q/24Q).

    Q1 (Apr-Jun): due 31st July
    Q2 (Jul-Sep): due 31st October
    Q3 (Oct-Dec): due 31st January
    Q4 (Jan-Mar): due 31st May
    """
    quarters = [
        (f"{fy_start}-04-01", f"{fy_start}-06-30", "Q1", f"{fy_start}-07-31"),
        (f"{fy_start}-07-01", f"{fy_start}-09-30", "Q2", f"{fy_start}-10-31"),
        (f"{fy_start}-10-01", f"{fy_start}-12-31", "Q3", f"{fy_start + 1}-01-31"),
        (f"{fy_start + 1}-01-01", f"{fy_start + 1}-03-31", "Q4", f"{fy_start + 1}-05-31"),
    ]
    tasks = []
    for start, end, qname, due in quarters:
        tasks.append(ComplianceTask(
            id=f"tds-{qname}-{fy_start}",
            title=f"TDS Return Filing ({qname}) — {start} to {end}",
            description=f"File TDS return (26Q/27Q/24Q) for {qname}: {start} to {end}",
            due_date=due,
            category="tds",
            priority="critical",
            frequency="quarterly",
        ))
    return tasks


def tds_payment_deadlines(fy_start: int) -> list[ComplianceTask]:
    """TDS payment deadlines.

    Due by 7th of following month (for March: 30th April).
    """
    tasks = []
    months = [(fy_start, m) for m in range(4, 13)] + [(fy_start + 1, m) for m in range(1, 4)]
    for year, month in months:
        due_year, due_month = _next_month(year, month)
        # March TDS due 30th April
        if month == 3:
            due_day = 30
        else:
            due_day = 7
        tasks.append(ComplianceTask(
            id=f"tds-pay-{year}-{month:02d}",
            title=f"TDS Payment — {calendar.month_name[month]} {year}",
            description=f"Deposit TDS deducted in {calendar.month_name[month]} {year}",
            due_date=f"{due_year}-{due_month:02d}-{due_day:02d}",
            category="tds",
            priority="critical",
            frequency="monthly",
        ))
    return tasks


# ===== ITR Deadlines =====

def itr_deadlines(fy_start: int) -> list[ComplianceTask]:
    """ITR filing deadlines for different entity types.

    Individual/HUF (no audit): 31st July
    Company/LLP (with audit): 31st October
    Transfer pricing cases: 30th November
    """
    return [
        ComplianceTask(
            id=f"itr-individual-{fy_start}",
            title=f"ITR Filing — Individuals & HUFs (no audit) — AY {fy_start+1}-{str(fy_start+2)[-2:]}",
            description=f"File ITR-1/2/3/4 for individuals and HUFs not requiring audit. AY {fy_start+1}-{str(fy_start+2)[-2:]}",
            due_date=f"{fy_start + 1}-07-31",
            category="it",
            priority="critical",
            frequency="annual",
        ),
        ComplianceTask(
            id=f"itr-audit-{fy_start}",
            title=f"ITR Filing — Companies & LLPs (with audit) — AY {fy_start+1}-{str(fy_start+2)[-2:]}",
            description=f"File ITR-5/6/7 for companies and LLPs requiring audit. AY {fy_start+1}-{str(fy_start+2)[-2:]}",
            due_date=f"{fy_start + 1}-10-31",
            category="it",
            priority="critical",
            frequency="annual",
        ),
        ComplianceTask(
            id=f"itr-transfer-{fy_start}",
            title=f"ITR Filing — Transfer Pricing Cases — AY {fy_start+1}-{str(fy_start+2)[-2:]}",
            description=f"File ITR for transfer pricing cases. AY {fy_start+1}-{str(fy_start+2)[-2:]}",
            due_date=f"{fy_start + 1}-11-30",
            category="it",
            priority="high",
            frequency="annual",
        ),
    ]


def advance_tax_deadlines(fy_start: int) -> list[ComplianceTask]:
    """Advance tax instalment deadlines.

    1st instalment (15%): 15th June
    2nd instalment (45%): 15th September
    3rd instalment (75%): 15th December
    4th instalment (100%): 15th March
    """
    instalments = [
        ("15%", f"{fy_start}-06-15", "1st"),
        ("45%", f"{fy_start}-09-15", "2nd"),
        ("75%", f"{fy_start}-12-15", "3rd"),
        ("100%", f"{fy_start + 1}-03-15", "4th"),
    ]
    tasks = []
    for pct, due, ord_name in instalments:
        tasks.append(ComplianceTask(
            id=f"adv-tax-{ord_name}-{fy_start}",
            title=f"Advance Tax — {ord_name} Instalment ({pct})",
            description=f"Pay advance tax — {ord_name} instalment ({pct} of estimated tax). Due: {due}",
            due_date=due,
            category="advance_tax",
            priority="high",
            frequency="annual",
        ))
    return tasks


# ===== ROC Deadlines =====

def roc_deadlines(fy_start: int) -> list[ComplianceTask]:
    """ROC filing deadlines (MCA).

    Annual Return (MGT-7): 60 days from AGM
    Financial Statements (AOC-4): 30 days from AGM
    Typically AGM is by 30th September → MGT-7 by 29th November, AOC-4 by 30th October
    """
    return [
        ComplianceTask(
            id=f"roc-aoc4-{fy_start}",
            title=f"ROC — Financial Statements (AOC-4) — FY {fy_start}-{str(fy_start+1)[-2:]}",
            description="File AOC-4 (financial statements) with ROC. Due within 30 days of AGM.",
            due_date=f"{fy_start + 1}-10-30",
            category="roc",
            priority="high",
            frequency="annual",
        ),
        ComplianceTask(
            id=f"roc-mgt7-{fy_start}",
            title=f"ROC — Annual Return (MGT-7) — FY {fy_start}-{str(fy_start+1)[-2:]}",
            description="File MGT-7 (annual return) with ROC. Due within 60 days of AGM.",
            due_date=f"{fy_start + 1}-11-29",
            category="roc",
            priority="high",
            frequency="annual",
        ),
    ]


# ===== Master Generator =====

def generate_compliance_calendar(
    fy_start: int,
    client_id: Optional[str] = None,
    client_name: str = "",
    include_gst: bool = True,
    include_tds: bool = True,
    include_itr: bool = True,
    include_roc: bool = False,
    include_advance_tax: bool = True,
) -> list[ComplianceTask]:
    """Generate a complete compliance calendar for a financial year.

    Args:
        fy_start: Financial year start (e.g., 2024 for FY 2024-25)
        client_id: Optional client ID to attach tasks to
        client_name: Optional client name
        include_gst: Include GST deadlines
        include_tds: Include TDS deadlines
        include_itr: Include ITR deadlines
        include_roc: Include ROC deadlines (companies only)
        include_advance_tax: Include advance tax deadlines

    Returns:
        List of ComplianceTask sorted by due date
    """
    tasks = []

    if include_gst:
        tasks.extend(gst_gstr1_deadlines(fy_start))
        tasks.extend(gst_gstr3b_deadlines(fy_start))
        tasks.extend(gst_payment_deadlines(fy_start))
        tasks.extend(gst_annual_return_deadlines(fy_start))

    if include_tds:
        tasks.extend(tds_quarterly_deadlines(fy_start))
        tasks.extend(tds_payment_deadlines(fy_start))

    if include_itr:
        tasks.extend(itr_deadlines(fy_start))

    if include_advance_tax:
        tasks.extend(advance_tax_deadlines(fy_start))

    if include_roc:
        tasks.extend(roc_deadlines(fy_start))

    # Attach client info
    for task in tasks:
        task.client_id = client_id
        task.client_name = client_name

    # Sort by due date
    tasks.sort(key=lambda t: t.due_date)
    return tasks


def get_upcoming_tasks(
    tasks: list[ComplianceTask],
    days_ahead: int = 30,
    reference_date: Optional[date] = None,
) -> list[ComplianceTask]:
    """Get tasks due within the next N days."""
    ref = reference_date or date.today()
    cutoff = ref + timedelta(days=days_ahead)
    return [
        t for t in tasks
        if t.status in ("pending", "in_progress")
        and ref <= date.fromisoformat(t.due_date) <= cutoff
    ]


def get_overdue_tasks(
    tasks: list[ComplianceTask],
    reference_date: Optional[date] = None,
) -> list[ComplianceTask]:
    """Get tasks that are past due."""
    ref = reference_date or date.today()
    return [
        t for t in tasks
        if t.status in ("pending", "in_progress")
        and date.fromisoformat(t.due_date) < ref
    ]


def get_task_summary(tasks: list[ComplianceTask]) -> dict:
    """Get a summary of tasks by category and status."""
    summary = {
        "total": len(tasks),
        "pending": sum(1 for t in tasks if t.status == "pending"),
        "in_progress": sum(1 for t in tasks if t.status == "in_progress"),
        "completed": sum(1 for t in tasks if t.status == "completed"),
        "overdue": 0,
        "by_category": {},
        "by_priority": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    }

    ref = date.today()
    for t in tasks:
        if t.status != "completed" and date.fromisoformat(t.due_date) < ref:
            summary["overdue"] += 1
        cat = summary["by_category"].setdefault(t.category, {"total": 0, "pending": 0, "completed": 0})
        cat["total"] += 1
        if t.status == "pending":
            cat["pending"] += 1
        elif t.status == "completed":
            cat["completed"] += 1
        if t.priority in summary["by_priority"]:
            summary["by_priority"][t.priority] += 1

    return summary
