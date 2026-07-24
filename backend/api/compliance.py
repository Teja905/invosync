"""Compliance Calendar and Task Automation API.

Provides:
  - Compliance calendar generation (GST, TDS, ITR, ROC deadlines)
  - Task management (create, update, complete tasks)
  - Upcoming/overdue task queries
  - Firm-wide compliance health dashboard
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import database as db
from api.deps import get_authenticated_user
from compliance_calendar import (
    generate_compliance_calendar,
    get_upcoming_tasks,
    get_overdue_tasks,
    get_task_summary,
    ComplianceTask,
)

router = APIRouter()


class CalendarRequest(BaseModel):
    fy_start: int = 2024  # FY 2024-25
    client_id: Optional[str] = None
    client_name: str = ""
    include_gst: bool = True
    include_tds: bool = True
    include_itr: bool = True
    include_roc: bool = False
    include_advance_tax: bool = True


class TaskUpdateRequest(BaseModel):
    task_id: str
    status: str = ""  # pending, in_progress, completed
    notes: str = ""
    assigned_to: str = ""


@router.post("/compliance/calendar")
async def compliance_calendar(req: CalendarRequest, current_user: dict = Depends(get_authenticated_user)):
    """Generate compliance calendar for a financial year.

    Returns all deadlines for GST, TDS, ITR, ROC, and advance tax
    for the specified financial year.
    """
    user_id = current_user.get("user_id", current_user.get("email", ""))

    tasks = generate_compliance_calendar(
        fy_start=req.fy_start,
        client_id=req.client_id,
        client_name=req.client_name,
        include_gst=req.include_gst,
        include_tds=req.include_tds,
        include_itr=req.include_itr,
        include_roc=req.include_roc,
        include_advance_tax=req.include_advance_tax,
    )

    # Load any user overrides from DB
    if db.compliance_tasks is not None:
        try:
            cursor = db.compliance_tasks.find({
                "user_id": user_id,
                "fy_start": req.fy_start,
                "client_id": req.client_id or {"$exists": False},
            })
            overrides = await cursor.to_list(length=1000)
            override_map = {o["task_id"]: o for o in overrides}
            for task in tasks:
                if task.id in override_map:
                    ov = override_map[task.id]
                    task.status = ov.get("status", task.status)
                    task.notes = ov.get("notes", task.notes)
                    task.assigned_to = ov.get("assigned_to", task.assigned_to)
        except Exception:
            pass

    return {
        "fy_start": req.fy_start,
        "fy_label": f"FY {req.fy_start}-{str(req.fy_start + 1)[-2:]}",
        "tasks": [t.to_dict() for t in tasks],
        "summary": get_task_summary(tasks),
    }


@router.post("/compliance/upcoming")
async def upcoming_tasks(
    days: int = 30,
    current_user: dict = Depends(get_authenticated_user),
):
    """Get tasks due within the next N days."""
    user_id = current_user.get("user_id", current_user.get("email", ""))

    # Load all tasks for this user
    tasks = []
    if db.compliance_tasks is not None:
        try:
            cursor = db.compliance_tasks.find({"user_id": user_id})
            docs = await cursor.to_list(length=10000)
            for doc in docs:
                tasks.append(ComplianceTask(
                    id=doc.get("task_id", ""),
                    title=doc.get("title", ""),
                    description=doc.get("description", ""),
                    due_date=doc.get("due_date", ""),
                    category=doc.get("category", ""),
                    priority=doc.get("priority", "medium"),
                    frequency=doc.get("frequency", "monthly"),
                    client_id=doc.get("client_id"),
                    client_name=doc.get("client_name", ""),
                    status=doc.get("status", "pending"),
                    assigned_to=doc.get("assigned_to", ""),
                ))
        except Exception:
            pass

    upcoming = get_upcoming_tasks(tasks, days_ahead=days)
    overdue = get_overdue_tasks(tasks)

    return {
        "upcoming": [t.to_dict() for t in upcoming],
        "overdue": [t.to_dict() for t in overdue],
        "summary": get_task_summary(tasks),
    }


@router.post("/compliance/task/update")
async def update_task(req: TaskUpdateRequest, current_user: dict = Depends(get_authenticated_user)):
    """Update a compliance task (status, notes, assignment)."""
    user_id = current_user.get("user_id", current_user.get("email", ""))

    if db.compliance_tasks is None:
        return {"error": "Database not available"}

    update_fields = {}
    if req.status:
        update_fields["status"] = req.status
    if req.notes:
        update_fields["notes"] = req.notes
    if req.assigned_to:
        update_fields["assigned_to"] = req.assigned_to

    if not update_fields:
        return {"error": "No fields to update"}

    await db.compliance_tasks.update_one(
        {"user_id": user_id, "task_id": req.task_id},
        {"$set": update_fields},
        upsert=True,
    )

    return {"ok": True, "task_id": req.task_id, "updated": list(update_fields.keys())}


@router.post("/compliance/generate-all")
async def generate_all_client_calendars(
    fy_start: int = 2024,
    current_user: dict = Depends(get_authenticated_user),
):
    """Generate compliance calendars for all active clients at once.

    This is the "one-click" feature: CA clicks once, and all client
    deadlines are generated and stored for tracking.
    """
    user_id = current_user.get("user_id", current_user.get("email", ""))

    # Load clients
    clients = []
    if db.clients is not None:
        try:
            cursor = db.clients.find({"user_id": user_id})
            clients = await cursor.to_list(length=500)
        except Exception:
            pass

    total_tasks = 0
    for client in clients:
        client_id = str(client.get("_id", ""))
        client_name = client.get("company_name", "") or client.get("client_name", "")

        # Determine which sections to include
        client_type = client.get("client_type", "individual")  # individual, partnership, company, llp
        is_company = client_type in ("company", "llp")

        tasks = generate_compliance_calendar(
            fy_start=fy_start,
            client_id=client_id,
            client_name=client_name,
            include_gst=True,
            include_tds=True,
            include_itr=True,
            include_roc=is_company,
            include_advance_tax=True,
        )

        # Store in DB
        if db.compliance_tasks is not None:
            for task in tasks:
                try:
                    await db.compliance_tasks.update_one(
                        {
                            "user_id": user_id,
                            "task_id": task.id,
                            "client_id": client_id,
                        },
                        {"$set": {
                            "user_id": user_id,
                            "task_id": task.id,
                            "client_id": client_id,
                            "client_name": client_name,
                            "title": task.title,
                            "description": task.description,
                            "due_date": task.due_date,
                            "category": task.category,
                            "priority": task.priority,
                            "frequency": task.frequency,
                            "status": "pending",
                            "fy_start": fy_start,
                        }},
                        upsert=True,
                    )
                except Exception:
                    pass
                total_tasks += 1

    return {
        "ok": True,
        "clients_processed": len(clients),
        "total_tasks_generated": total_tasks,
        "fy_start": fy_start,
    }
