"""System configuration endpoint."""

from fastapi import APIRouter

from api.app_state import MAX_CONCURRENT_EXTRACTIONS

router = APIRouter()

_PRODUCTION_MODE = __import__('os').getenv("PRODUCTION_MODE", "").lower() in ("true", "1", "yes")


@router.get("/api/v3/system/config")
async def system_config():
    return {
        "production_mode": _PRODUCTION_MODE,
        "version": "3.3",
        "features": {
            "dry_run": True,
            "idempotency": True,
            "replay": True,
            "monitoring": True,
            "learning_engine": True,
            "south_indian_invoices": True,
        },
        "max_concurrent_extractions": MAX_CONCURRENT_EXTRACTIONS,
    }
