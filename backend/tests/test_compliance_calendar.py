"""Tests for compliance calendar engine."""

import pytest
from datetime import date
from compliance_calendar import (
    generate_compliance_calendar,
    get_upcoming_tasks,
    get_overdue_tasks,
    get_task_summary,
    gst_gstr1_deadlines,
    gst_gstr3b_deadlines,
    tds_quarterly_deadlines,
    itr_deadlines,
    advance_tax_deadlines,
)


class TestGSTDeadlines:
    def test_gstr1_count(self):
        tasks = gst_gstr1_deadlines(2024)
        assert len(tasks) == 12  # 12 months in FY

    def test_gstr3b_count(self):
        tasks = gst_gstr3b_deadlines(2024)
        assert len(tasks) == 12

    def test_gstr1_first_deadline(self):
        tasks = gst_gstr1_deadlines(2024)
        # April 2024 GSTR-1 due 11th May 2024
        assert tasks[0].due_date == "2024-05-11"
        assert tasks[0].category == "gst"
        assert tasks[0].priority == "critical"

    def test_gstr3b_last_deadline(self):
        tasks = gst_gstr3b_deadlines(2024)
        # March 2025 GSTR-3B due 20th April 2025
        assert tasks[-1].due_date == "2025-04-20"


class TestTDSDeadlines:
    def test_quarterly_count(self):
        tasks = tds_quarterly_deadlines(2024)
        assert len(tasks) == 4

    def test_q1_deadline(self):
        tasks = tds_quarterly_deadlines(2024)
        # Q1 (Apr-Jun) due 31st July
        assert tasks[0].due_date == "2024-07-31"
        assert tasks[0].category == "tds"

    def test_q4_deadline(self):
        tasks = tds_quarterly_deadlines(2024)
        # Q4 (Jan-Mar) due 31st May
        assert tasks[3].due_date == "2025-05-31"


class TestITRDeadlines:
    def test_itr_count(self):
        tasks = itr_deadlines(2024)
        assert len(tasks) == 3  # individual, audit, transfer pricing

    def test_individual_deadline(self):
        tasks = itr_deadlines(2024)
        individual = [t for t in tasks if "Individual" in t.title][0]
        assert individual.due_date == "2025-07-31"
        assert individual.category == "it"

    def test_company_deadline(self):
        tasks = itr_deadlines(2024)
        company = [t for t in tasks if "Companies" in t.title][0]
        assert company.due_date == "2025-10-31"


class TestAdvanceTax:
    def test_advance_tax_count(self):
        tasks = advance_tax_deadlines(2024)
        assert len(tasks) == 4

    def test_first_instalment(self):
        tasks = advance_tax_deadlines(2024)
        assert tasks[0].due_date == "2024-06-15"
        assert "15%" in tasks[0].title


class TestFullCalendar:
    def test_generate_all(self):
        tasks = generate_compliance_calendar(2024)
        # GST (12+12+12+2) + TDS (4+12) + ITR (3) + Advance (4) = 61
        assert len(tasks) > 50

    def test_sorted_by_date(self):
        tasks = generate_compliance_calendar(2024)
        dates = [t.due_date for t in tasks]
        assert dates == sorted(dates)

    def test_with_client(self):
        tasks = generate_compliance_calendar(2024, client_id="c1", client_name="Test Client")
        for t in tasks:
            assert t.client_id == "c1"
            assert t.client_name == "Test Client"

    def test_exclude_tds(self):
        tasks = generate_compliance_calendar(2024, include_tds=False)
        tds_tasks = [t for t in tasks if t.category == "tds"]
        assert len(tds_tasks) == 0

    def test_exclude_gst(self):
        tasks = generate_compliance_calendar(2024, include_gst=False)
        gst_tasks = [t for t in tasks if t.category == "gst"]
        assert len(gst_tasks) == 0


class TestTaskFilters:
    def setup_method(self):
        self.tasks = generate_compliance_calendar(2024)

    def test_upcoming(self):
        # Use reference date during FY when many deadlines are upcoming
        upcoming = get_upcoming_tasks(self.tasks, days_ahead=365, reference_date=date(2024, 7, 1))
        assert len(upcoming) > 0

    def test_overdue_with_past_date(self):
        # Set reference date to 2026-01-01 — many tasks will be overdue
        overdue = get_overdue_tasks(self.tasks, reference_date=date(2026, 1, 1))
        assert len(overdue) > 0

    def test_no_overdue_future(self):
        # Reference date in 2023 — nothing is overdue
        overdue = get_overdue_tasks(self.tasks, reference_date=date(2023, 1, 1))
        assert len(overdue) == 0


class TestTaskSummary:
    def test_summary_counts(self):
        tasks = generate_compliance_calendar(2024)
        summary = get_task_summary(tasks)
        assert summary["total"] == len(tasks)
        assert summary["pending"] == len(tasks)  # All start as pending

    def test_summary_by_category(self):
        tasks = generate_compliance_calendar(2024)
        summary = get_task_summary(tasks)
        assert "gst" in summary["by_category"]
        assert "tds" in summary["by_category"]
        assert "it" in summary["by_category"]


class TestSerialization:
    def test_task_to_dict(self):
        tasks = generate_compliance_calendar(2024)
        d = tasks[0].to_dict()
        assert "id" in d
        assert "title" in d
        assert "due_date" in d
        assert "category" in d
        assert "priority" in d
