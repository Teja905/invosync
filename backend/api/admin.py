"""Admin alerts and monitoring endpoints."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import database as db
from api.deps import get_authenticated_user
from core.logging import get_logger
from core.metrics import metrics

router = APIRouter()
logger = get_logger(__name__)

_PRODUCTION_MODE = os.getenv("PRODUCTION_MODE", "").lower() in ("true", "1", "yes")


class AlertPayload(BaseModel):
    level: str = "info"
    category: str = "general"
    message: str
    details: dict = {}


@router.post("/api/v3/admin/alerts")
async def receive_alert(
    payload: AlertPayload,
    current_user: dict = Depends(get_authenticated_user),
):
    """Receive and store an alert from the connector or frontend."""
    if not _PRODUCTION_MODE:
        return {"status": "accepted", "mode": "development"}

    user_id = current_user.get("user_id", current_user.get("email", ""))
    alert_doc = {
        "user_id": user_id,
        "level": payload.level,
        "category": payload.category,
        "message": payload.message,
        "details": payload.details,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$push": {"alerts": {"$each": [alert_doc], "$slice": -100}}},
            upsert=True,
        )

    logger.warning("ALERT [%s] %s: %s", payload.level, payload.category, payload.message)
    return {"status": "accepted", "mode": "production"}


@router.get("/api/v3/admin/alerts")
async def list_alerts(
    limit: int = Query(50, le=200),
    current_user: dict = Depends(get_authenticated_user),
):
    """List stored alerts for the authenticated user's organization."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        org = await db.organizations.find_one({"org_id": user_id})
        if org:
            alerts = org.get("alerts", [])
            return {"alerts": alerts[-limit:], "count": len(alerts)}
    return {"alerts": [], "count": 0}


@router.get("/api/v3/admin/errors")
async def list_errors(
    limit: int = Query(50, le=500),
    current_user: dict = Depends(get_authenticated_user),
):
    """List recent server-side errors (from the audit_logs collection)."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.audit_logs is None:
        return {"errors": [], "count": 0, "note": "audit_logs not available"}
    # Errors are logged as action="error" via the global exception handler
    events = await db.list_audit_logs(
        resource_type="invoice", action="error",
        user_id=user_id, limit=limit,
    )
    # Also surface any auth/admin/system errors tagged with the user
    if not events:
        events = await db.list_audit_logs(
            action="error", user_id=user_id, limit=limit,
        )
    return {
        "errors": [
            {
                "created_at": e.get("created_at"),
                "details": e.get("details"),
                "action": e.get("action"),
            }
            for e in events
        ],
        "count": len(events),
    }


@router.get("/api/v3/admin/metrics/live")
async def live_metrics(
    current_user: dict = Depends(get_authenticated_user),
):
    """Live in-process metrics: request rate, error rate, queue depth, worker liveness."""
    return metrics.snapshot()


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint (text exposition format)."""
    return PlainTextResponse(metrics.prometheus(), media_type="text/plain")
