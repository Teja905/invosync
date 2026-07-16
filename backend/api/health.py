"""Health check endpoint."""

import os
import time

from fastapi import APIRouter

import database as db
from api.app_state import queue_manager, tally_sync_manager
from core.logging import get_logger
from core.metrics import metrics

router = APIRouter()
logger = get_logger(__name__)

_start_time = time.monotonic()


@router.get("/health")
async def health():
    status = "healthy"
    checks = {}

    # Database
    try:
        if db.invoices is not None:
            t0 = time.monotonic()
            await db.invoices.find_one({}, {"_id": 1})
            latency = round((time.monotonic() - t0) * 1000, 1)
            checks["database"] = {"status": "ok", "latency_ms": latency}
        else:
            checks["database"] = {"status": "disconnected", "latency_ms": None}
            status = "degraded"
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        status = "degraded"

    # Extraction queue
    qs = queue_manager.stats
    checks["extraction_queue"] = {
        "queue_size": qs["queue_size"],
        "active_tasks": qs["tasks"],
    }

    # Tally sync manager
    ts = tally_sync_manager.stats
    checks["tally_sync"] = {"active_jobs": ts["jobs"]}

    # Background worker liveness (from the metrics heartbeat)
    ms = metrics.snapshot()
    checks["worker"] = {
        "alive": ms["worker_alive"],
        "heartbeat_age_seconds": ms["worker_heartbeat_age_seconds"],
        "queue_depth": ms["queue_depth"],
    }
    if not ms["worker_alive"]:
        status = "degraded"

    # AI providers
    checks["openrouter"] = {"configured": bool(os.getenv("OPENROUTER_API_KEY"))}
    checks["gemini"] = {"configured": bool(os.getenv("GEMINI_API_KEY"))}
    if not checks["openrouter"]["configured"] and not checks["gemini"]["configured"]:
        status = "degraded"

    return {
        "status": status,
        "version": "3.2",
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
        "checks": checks,
    }
