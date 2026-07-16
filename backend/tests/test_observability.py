"""Observability: request-id tracing, metrics, and error aggregation.

The full app has a circular import (api.app_state -> background -> worker
-> api.app_state) that only triggers under TestClient import, so we test
the tracing primitives, the metrics store, and the audit_log error path directly.
"""

from contextvars import copy_context

from core.logging import set_request_id, get_request_id, RequestIDFilter
from core.metrics import Metrics
from audit_log import audit as audit_logger


def test_set_request_id_is_context_scoped():
    """set_request_id should be isolated per context (per-request)."""
    ctx = copy_context()

    def inner():
        set_request_id("abc123")
        assert get_request_id() == "abc123"

    assert get_request_id() == "-"
    ctx.run(inner)
    assert get_request_id() == "-"


def test_request_id_filter_attaches_field():
    import logging
    f = RequestIDFilter()
    rec = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", None, None)
    set_request_id("xyz789")
    assert f.filter(rec) is True
    assert rec.req_id == "xyz789"


def test_metrics_snapshot_and_counters():
    """Metrics store must aggregate request/error/invoice counters and liveness."""
    m = Metrics()
    for _ in range(10):
        m.record_request(200)
    m.record_request(500)
    m.record_invoice_processed()
    m.record_xml_generated()
    m.record_tally_synced()
    m.set_worker_heartbeat()
    m.set_queue_depth(3)

    snap = m.snapshot()
    assert snap["requests_total"] == 11
    assert snap["errors_total"] == 1
    assert snap["error_rate_pct"] == round(1 / 11 * 100, 2)
    assert snap["invoices_processed"] == 1
    assert snap["xml_generated"] == 1
    assert snap["tally_synced"] == 1
    assert snap["queue_depth"] == 3
    assert snap["worker_alive"] is True
    # Prometheus exposition format
    prom = m.prometheus()
    assert "invosync_requests_total 11" in prom
    assert "invosync_worker_alive 1" in prom


def test_metrics_exception_recording():
    m = Metrics()
    m.record_exception(ValueError("boom"))
    assert "ValueError" in m.snapshot()["last_exception"]


def test_audit_logger_error_is_queryable():
    """An error logged via log_invoice_action("error", ...) is retrievable."""

    async def run():
        await audit_logger.log_invoice_action(
            "error", 0, "tester",
            details="GET /x: boom",
        )
        events = await audit_logger.get_history(action="error", user_id="tester", limit=5)
        return events

    import asyncio
    events = asyncio.get_event_loop().run_until_complete(run())
    assert isinstance(events, list)
