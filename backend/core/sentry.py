"""Optional Sentry error tracking.

Wire this up by setting SENTRY_DSN in the environment. If the DSN is absent,
every function here is a no-op so the app runs unchanged in dev / on-prem.

This is the "know about errors before users tell you" control. It is fully
optional and never blocks the request path — failures inside Sentry are
swallowed so error tracking can never itself cause an outage.
"""

import os
import traceback

from core.logging import get_logger

logger = get_logger(__name__)

_DSN = os.getenv("SENTRY_DSN", "").strip()
_ENV = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development"))
_ENABLED = bool(_DSN)
_client = None


def init_sentry() -> None:
    """Initialise Sentry once at startup. Safe to call multiple times."""
    global _client, _ENABLED
    if not _DSN:
        logger.info("Sentry disabled (no SENTRY_DSN set).")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.asyncio import AsyncioIntegration

        sentry_sdk.init(
            dsn=_DSN,
            environment=_ENV,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
            send_default_pii=False,  # Never send PII — GSTIN/email/phone are redacted upstream
            attach_stacktrace=True,
            integrations=[FastApiIntegration(), AsyncioIntegration()],
            before_send=_scrub_pii,
        )
        _client = sentry_sdk
        _ENABLED = True
        logger.info("Sentry enabled (env=%s).", _ENV)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Sentry init failed, continuing without it: %s", e)
        _ENABLED = False


def _scrub_pii(event, hint):
    """Defensive second layer: drop any PII-like field before sending."""
    try:
        from core.pii import redact_pii

        if event.get("message"):
            event["message"] = redact_pii(event["message"])
        for exc in event.get("exception", {}).get("values", []) or []:
            if exc.get("value"):
                exc["value"] = redact_pii(exc["value"])
    except Exception:
        pass
    return event


def capture_exception(exc: BaseException) -> None:
    """Capture an exception to Sentry if enabled. Never raises."""
    if not _ENABLED or _client is None:
        return
    try:
        _client.capture_exception(exc)
    except Exception:
        pass


def capture_message(message: str, level: str = "error") -> None:
    """Capture a message to Sentry if enabled. Never raises."""
    if not _ENABLED or _client is None:
        return
    try:
        _client.capture_message(message, level=level)
    except Exception:
        pass


def capture_traceback() -> None:
    """Capture the current exception (must be called inside except)."""
    if not _ENABLED or _client is None:
        return
    try:
        _client.capture_exception()
    except Exception:
        pass


def is_enabled() -> bool:
    return _ENABLED
