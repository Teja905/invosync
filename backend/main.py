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

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api.app_state import limiter

import database as db
import validation as val
from core.logging import get_logger
from config.settings import (
    config_overrides, user_config_from_current,
    make_xml_generator, run_validation_pipeline,
)
from api.app_state import (
    extraction_pipeline, company_config, learner,
    queue_manager, MAX_CONCURRENT_EXTRACTIONS,
)
from background import run_extraction_worker, run_cleanup_loop
from api.extraction import router as extraction_router
from api.health import router as health_router
from api.gst import router as gst_router
from api.system import router as system_router
from api.clients import router as clients_router
from api.corrections import router as corrections_router
from api.rules_engine import router as rules_engine_router
from api.companies import router as companies_router
from api.auth import router as auth_router
from api.gstr import router as gstr_router
from api.preflight import router as preflight_router
from api.voucher import router as voucher_router
from api.config import router as config_router
from api.banking import router as banking_router
from api.admin import router as admin_router
from api.metrics import router as metrics_router
from api.learning import router as learning_router
from api.invoices import router as invoice_router
from api.tally_sync import router as tally_sync_router
from api.ledgers import router as ledgers_router
from api.reports import router as reports_router
from api.billing import router as billing_router
_AUTH_ENABLED = False


load_dotenv()

logger = get_logger(__name__)

# Convenience aliases for refactored names
_learner = learner
_extraction_pipeline = extraction_pipeline
_company_config = company_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect DB, load models, launch background workers."""
    init_sentry()
    try:
        await db.connect()
    except Exception as e:
        logger.warning("MongoDB connection failed (%s). Running without database.", e)
        logger.warning("Invoice data will NOT be persisted across restarts.")
    has_openrouter = bool(os.getenv("OPENROUTER_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    logger.info("API keys: OpenRouter=%s Gemini=%s (using fallback=%s)",
                "YES" if has_openrouter else "NO",
                "YES" if has_gemini else "NO",
                "NO" if has_gemini else "YES")
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
    asyncio.create_task(run_extraction_worker(queue_manager))
    asyncio.create_task(run_cleanup_loop(queue_manager))
    logger.info("Extraction queue worker started (max %s concurrent)", MAX_CONCURRENT_EXTRACTIONS)
    asyncio.create_task(_keepalive_self_ping())
    yield
    await db.disconnect()


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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(gst_router)
app.include_router(system_router)
app.include_router(clients_router)
app.include_router(corrections_router)
app.include_router(rules_engine_router)
app.include_router(companies_router)
app.include_router(auth_router)
app.include_router(gstr_router)
app.include_router(preflight_router)
app.include_router(voucher_router)
app.include_router(config_router)
app.include_router(banking_router)
app.include_router(admin_router)
app.include_router(metrics_router)
app.include_router(learning_router)
app.include_router(invoice_router)
app.include_router(tally_sync_router)
app.include_router(ledgers_router)
    app.include_router(reports_router)
    app.include_router(billing_router)

    # Seed default plans on startup (idempotent)
    await db.seed_plans()


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
