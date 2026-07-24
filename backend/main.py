"""FastAPI backend — production-grade invoice extraction, validation, and Tally XML generation."""

import asyncio
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from core.logging import set_request_id
from core.metrics import metrics
from core.sentry import init_sentry, capture_exception
from audit_log import audit as audit_logger

from slowapi.errors import RateLimitExceeded
from api.app_state import limiter

import database as db
import validation as val
from core.logging import get_logger
from api.app_state import (
    extraction_pipeline, company_config, learner,
    queue_manager, ai_cache, MAX_CONCURRENT_EXTRACTIONS,
)
from background import run_extraction_worker, run_cleanup_loop
from api.extraction import router as extraction_router
from api.health import router as health_router
from api.clients import router as clients_router
from api.corrections import router as corrections_router
from api.rules_engine import router as rules_engine_router
from auth import router as auth_router
from api.config import router as config_router
from api.banking import router as banking_router
from api.admin import router as admin_router
from api.learning import router as learning_router
from api.invoices import router as invoice_router
from api.tally_sync import router as tally_sync_router
from api.ledgers import router as ledgers_router
from api.reports import router as reports_router
from api.billing import router as billing_router

load_dotenv()

logger = get_logger(__name__)

# Convenience aliases for refactored names
_learner = learner
_extraction_pipeline = extraction_pipeline
_company_config = company_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect DB, load models, launch supervised background workers.

    All background tasks are tracked and monitored:
    - If any worker crashes, it's logged and the task reference is cleaned up
    - On shutdown, all tasks are cancelled in reverse order
    - Extraction worker + cleanup loop are isolated so one crash doesn't cascade
    """
    init_sentry()

    # ── Phase 1: Database ──
    try:
        await db.connect()
    except Exception as e:
        logger.warning("MongoDB connection failed (%s). Running without database.", e)
        logger.warning("Invoice data will NOT be persisted across restarts.")

    # Wire AI cache to MongoDB collection (falls back to memory-only if DB down)
    if db.ai_cache is not None:
        ai_cache._collection = db.ai_cache
        logger.info("AI cache: MongoDB-backed (TTL 7 days)")
    else:
        logger.info("AI cache: memory-only (DB unavailable)")

    has_openrouter = bool(os.getenv("OPENROUTER_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    logger.info("API keys: OpenRouter=%s Gemini=%s (using fallback=%s)",
                "YES" if has_openrouter else "NO",
                "YES" if has_gemini else "NO",
                "NO" if has_gemini else "YES")

    # ── Phase 2: Learner + Config Migration ──
    try:
        await _learner.load("default@local")
        logger.info("LedgerLearner loaded %d corrections", _learner.stats()["corrections_count"])
    except Exception as e:
        logger.warning("LedgerLearner load failed: %s", e)
    try:
        cid = await db.auto_migrate_env_config("default")
        if cid:
            logger.info("Auto-migrated env config to company_id=%d", cid)
    except Exception as e:
        logger.warning("Company auto-migrate failed: %s", e)

    # ── Phase 3: Background Workers (supervised) ──
    _background_tasks: list[asyncio.Task] = []

    async def _run_supervised(coro, name: str):
        """Run a background coroutine and log if it exits unexpectedly.

        If the task finishes (not cancelled), we log at warning level
        so operators know a worker stopped. Cancellation is expected
        during graceful shutdown.
        """
        try:
            await coro
        except asyncio.CancelledError:
            logger.info("Background task '%s' cancelled (shutdown)", name)
        except Exception:
            logger.exception("Background task '%s' crashed — restart needed", name)

    _background_tasks.append(
        asyncio.create_task(
            _run_supervised(run_extraction_worker(queue_manager), "extraction_worker"),
            name="extraction_worker",
        )
    )
    _background_tasks.append(
        asyncio.create_task(
            _run_supervised(run_cleanup_loop(queue_manager), "cleanup_loop"),
            name="cleanup_loop",
        )
    )
    logger.info("Extraction queue worker started (max %s concurrent)", MAX_CONCURRENT_EXTRACTIONS)

    if _APP_URL:
        _background_tasks.append(
            asyncio.create_task(
                _run_supervised(_keepalive_self_ping(), "keepalive"),
                name="keepalive",
            )
        )

    try:
        await db.seed_plans()
    except Exception as e:
        logger.warning("Plan seeding failed: %s", e)

    # ── Yield: app is live ──
    yield

    # ── Shutdown: cancel workers before DB disconnect ──
    logger.info("Shutting down %d background tasks...", len(_background_tasks))
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        done, pending = await asyncio.wait(_background_tasks, timeout=10)
        if pending:
            logger.warning("%d tasks did not finish within 10s timeout", len(pending))
    _background_tasks.clear()

    await db.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(title="Invoice Extractor & XML Generator", lifespan=lifespan)

# -- Max request body: 25MB (prevents OOM from oversized uploads) --
_MAX_BODY_MB = int(os.getenv("MAX_BODY_MB", "25"))


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and int(cl) > _MAX_BODY_MB * 1024 * 1024:
        return JSONResponse(
            status_code=413,
            content={"error": "REQUEST_TOO_LARGE", "message": f"Request body exceeds {_MAX_BODY_MB}MB limit"},
        )
    return await call_next(request)


# -- Compression (reduce API payload size 30-60%) --
app.add_middleware(GZipMiddleware, minimum_size=500)

# -- Rate limiting --
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return 429 as JSON with retry-after seconds so clients can retry gracefully."""
    retry_after = getattr(exc, "retry_after", None) or 60
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": f"Rate limit exceeded. Retry after {retry_after} seconds.",
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

_RAW_ORIGINS = os.getenv("ALLOWED_ORIGINS",
    "https://invosync-wheat.vercel.app,http://localhost:3000,http://localhost:5173,https://invosync.vercel.app,https://invosync.in"
)

# Handle both JSON-array format ["url1","url2"] and comma-separated url1,url2
_RAW_ORIGINS = _RAW_ORIGINS.strip().strip("[]").replace('"', "").replace("'", "")
_ALLOWED_ORIGINS = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]

# If wildcard is in the list, allow all origins (disables credentials-based restriction)
_ALLOW_ALL = "*" in [o.lower() for o in _ALLOWED_ORIGINS]

logger.info("CORS allowed origins: %s (wildcard=%s)", _ALLOWED_ORIGINS, _ALLOW_ALL)

if _ALLOW_ALL:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=3600,
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=3600,
    )


@app.middleware("http")
async def http_exception_and_timing_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    set_request_id(rid)
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        logger.info("%s %s \u2192 %s (%.0fms)",
                    request.method, request.url.path, response.status_code, process_time * 1000)
        metrics.record_request(response.status_code)
        response.headers["X-Request-ID"] = rid
        return response
    except RequestValidationError as val_err:
        process_time = time.perf_counter() - start_time
        logger.error("Schema validation error on %s (%dms): %s",
                     request.url.path, process_time * 1000, val_err.errors())
        return JSONResponse(
            status_code=422,
            content={
                "error": "DATA_SCHEMA_MISMATCH",
                "message": "The invoice structure does not conform to compliance models.",
                "request_id": rid,
                "details": val_err.errors(),
            },
        )
    except ValueError as val_err:
        logger.error("Compliance validation error on %s: %s", request.url.path, val_err)
        return JSONResponse(
            status_code=400,
            content={
                "error": "ACCOUNTING_VALIDATION_FAILED",
                "message": str(val_err),
                "request_id": rid,
            },
        )
    except Exception as exc:
        process_time = time.perf_counter() - start_time
        logger.critical("Unhandled exception on %s %s (%dms): %s\n%s",
                        request.method, request.url.path, process_time * 1000, exc,
                        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        metrics.record_exception(exc)
        capture_exception(exc)
        try:
            await audit_logger.log_invoice_action(
                "error", 0, request.headers.get("X-User-ID", "unknown"),
                details=f"{request.method} {request.url.path}: {exc}",
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SYSTEM_CRASH",
                "message": "An unexpected critical exception occurred.",
                "request_id": rid,
            },
        )


val.COMPANY_STATE_CODE = company_config.state_code

# Domain routers
app.include_router(extraction_router)
app.include_router(health_router)
app.include_router(clients_router)
app.include_router(corrections_router)
app.include_router(rules_engine_router)
app.include_router(auth_router)
app.include_router(config_router)
app.include_router(banking_router)
app.include_router(admin_router)
app.include_router(learning_router)
app.include_router(invoice_router)
app.include_router(tally_sync_router)
app.include_router(ledgers_router)
app.include_router(reports_router)
app.include_router(billing_router)

from api.compliance import router as compliance_router
app.include_router(compliance_router)

# Seed default plans on startup (idempotent)
# (moved to lifespan below)


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


_APP_URL = os.getenv("APP_URL", "").rstrip("/")


async def _keepalive_self_ping():
    """Self-ping every 14 minutes to prevent Render/Railway from sleeping."""
    if not _APP_URL:
        return
    import httpx
    while True:
        await asyncio.sleep(14 * 60)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{_APP_URL}/health")
                logger.debug("Keepalive ping → %s", resp.status_code)
        except Exception as e:
            logger.debug("Keepalive ping failed: %s", e)





## ---------------------------------------------------------------------------
## All route endpoints extracted to api/ routers.
## Background queue worker extracted to background/ module.
## Remaining code in main.py is only:
##   - app creation
##   - middleware / exception handlers
##   - startup / shutdown lifecycle
## ---------------------------------------------------------------------------
