"""Metrics dashboard endpoint."""

from fastapi import APIRouter, Depends

import database as db
from api.deps import get_authenticated_user

router = APIRouter()


def _empty_metrics():
    return {
        "total_invoices": 0,
        "xml_success": 0,
        "xml_success_rate": 0,
        "import_success": 0,
        "import_success_rate": 0,
        "validation_passed": 0,
        "validation_failed": 0,
        "avg_processing_ms": 0,
        "top_errors": [],
    }


@router.get("/api/v3/metrics")
async def metrics_dashboard(current_user: dict = Depends(get_authenticated_user)):
    """Return aggregated invoice processing metrics for the dashboard."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.invoices is None:
        return _empty_metrics()

    pipeline_xml = [
        {"$match": {"user_id": user_id, "xml_generated": True}},
        {"$group": {"_id": None, "count": {"$sum": 1}}},
    ]
    xml_success = 0
    xml_cursor = await db.invoices.aggregate(pipeline_xml).to_list(length=1)
    if xml_cursor:
        xml_success = xml_cursor[0].get("count", 0)

    pipeline_exported = [
        {"$match": {"user_id": user_id, "status": "exported"}},
        {"$group": {"_id": None, "count": {"$sum": 1}}},
    ]
    import_success = 0
    exported_cursor = await db.invoices.aggregate(pipeline_exported).to_list(length=1)
    if exported_cursor:
        import_success = exported_cursor[0].get("count", 0)

    pipeline_errors = [
        {"$match": {"user_id": user_id, "status": "sync_error"}},
        {"$group": {"_id": "$sync_error", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    top_errors = await db.invoices.aggregate(pipeline_errors).to_list(length=10)

    total_invoices = await db.invoices.count_documents({"user_id": user_id})
    validation_passed = 0
    validation_failed = 0
    pipeline_validation = [
        {"$match": {"user_id": user_id}},
        {"$project": {"validation": 1}},
    ]
    async for doc in db.invoices.aggregate(pipeline_validation):
        val = doc.get("validation") or {}
        if val.get("passed") or val.get("decision", {}).get("decision") == "high":
            validation_passed += 1
        else:
            validation_failed += 1

    avg_processing_ms = 0
    pipeline_processing = [
        {"$match": {"user_id": user_id, "processing_duration_ms": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": None, "avg_ms": {"$avg": "$processing_duration_ms"}}},
    ]
    proc_cursor = await db.invoices.aggregate(pipeline_processing).to_list(length=1)
    if proc_cursor:
        avg_processing_ms = round(proc_cursor[0].get("avg_ms", 0), 1)

    import_success_rate = round(import_success / max(total_invoices, 1) * 100, 1)
    xml_success_rate = round(xml_success / max(total_invoices, 1) * 100, 1)

    return {
        "total_invoices": total_invoices,
        "xml_success": xml_success,
        "xml_success_rate": xml_success_rate,
        "import_success": import_success,
        "import_success_rate": import_success_rate,
        "validation_passed": validation_passed,
        "validation_failed": validation_failed,
        "avg_processing_ms": avg_processing_ms,
        "top_errors": [{"error": e.get("_id", ""), "count": e.get("count", 0)} for e in top_errors],
    }
