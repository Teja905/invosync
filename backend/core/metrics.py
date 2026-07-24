"""In-process metrics collectors.

Lightweight, dependency-free counters that aggregate what matters for an
on-call engineer at 3 AM: request throughput, error rate, queue depth, and
worker liveness. Exposed via /api/v3/admin/metrics/live and a Prometheus
text format at /metrics.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _Window:
    capacity: int
    samples: Deque = field(default_factory=deque)

    def push(self, value: float) -> None:
        self.samples.append(value)
        while len(self.samples) > self.capacity:
            self.samples.popleft()

    def count(self) -> int:
        return len(self.samples)

    def sum(self) -> float:
        return sum(self.samples)

    def rate_per_min(self) -> float:
        if not self.samples:
            return 0.0
        span = (self.samples[-1] - self.samples[0]) / 60.0
        if span <= 0:
            return float(len(self.samples))
        return len(self.samples) / span


class Metrics:
    """Singleton metrics store."""

    # Approximate cost per 1K tokens (USD) — update as pricing changes
    COST_PER_1K = {
        "openrouter": 0.000125,   # Gemini Flash via OpenRouter ~$0.075/1M tokens
        "gemini": 0.000075,       # Gemini Flash direct ~$0.075/1M tokens
    }

    def __init__(self) -> None:
        self._start_time = time.time()
        self._requests_total = 0
        self._errors_total = 0
        self._request_timestamps: Deque[float] = deque()
        self._error_timestamps: Deque[float] = deque()
        self._invoices_processed = 0
        self._xml_generated = 0
        self._tally_synced = 0
        self._worker_heartbeat = 0.0
        self._queue_depth = 0
        self._last_exception: str | None = None
        self._total_tokens = 0
        self._total_cost_usd = 0.0
        self._tokens_by_provider: dict[str, int] = {}
        self._cost_by_provider: dict[str, float] = {}

    # -- Mutators --
    def record_request(self, status_code: int) -> None:
        now = time.time()
        self._requests_total += 1
        self._request_timestamps.append(now)
        while self._request_timestamps and now - self._request_timestamps[0] > 600:
            self._request_timestamps.popleft()
        if status_code >= 500:
            self._errors_total += 1
            self._error_timestamps.append(now)
            while self._error_timestamps and now - self._error_timestamps[0] > 600:
                self._error_timestamps.popleft()

    def record_invoice_processed(self) -> None:
        self._invoices_processed += 1

    def record_xml_generated(self) -> None:
        self._xml_generated += 1

    def record_tally_synced(self) -> None:
        self._tally_synced += 1

    def set_worker_heartbeat(self) -> None:
        self._worker_heartbeat = time.time()

    def set_queue_depth(self, depth: int) -> None:
        self._queue_depth = depth

    def record_exception(self, exc: Exception) -> None:
        self._last_exception = f"{type(exc).__name__}: {exc}"

    def record_ai_usage(self, provider: str, usage: dict) -> None:
        """Record token usage and estimated cost for an AI extraction call."""
        tokens = usage.get("total_tokens", 0) or usage.get("completion_tokens", 0) or 0
        if tokens <= 0:
            return
        self._total_tokens += tokens
        cost_per_1k = self.COST_PER_1K.get(provider, 0.0001)
        cost = (tokens / 1000.0) * cost_per_1k
        self._total_cost_usd += cost
        self._tokens_by_provider[provider] = self._tokens_by_provider.get(provider, 0) + tokens
        self._cost_by_provider[provider] = self._cost_by_provider.get(provider, 0.0) + cost

    # -- Snapshot --
    def snapshot(self) -> dict:
        uptime = time.time() - self._start_time
        heartbeat_age = time.time() - self._worker_heartbeat if self._worker_heartbeat else None
        return {
            "uptime_seconds": round(uptime, 1),
            "requests_total": self._requests_total,
            "requests_per_min": round(self._rate(self._request_timestamps), 2),
            "errors_total": self._errors_total,
            "errors_per_min": round(self._rate(self._error_timestamps), 2),
            "error_rate_pct": round(self._errors_total / max(self._requests_total, 1) * 100, 2),
            "invoices_processed": self._invoices_processed,
            "xml_generated": self._xml_generated,
            "tally_synced": self._tally_synced,
            "queue_depth": self._queue_depth,
            "worker_heartbeat_age_seconds": (
                round(heartbeat_age, 1) if heartbeat_age is not None else None
            ),
            "worker_alive": heartbeat_age is None or heartbeat_age < 120,
            "last_exception": self._last_exception,
            "total_tokens": self._total_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
            "tokens_by_provider": dict(self._tokens_by_provider),
            "cost_by_provider": {k: round(v, 6) for k, v in self._cost_by_provider.items()},
        }

    def _rate(self, timestamps: Deque[float]) -> float:
        if len(timestamps) < 2:
            return float(len(timestamps))
        span = (timestamps[-1] - timestamps[0]) / 60.0
        if span <= 0:
            return float(len(timestamps))
        return len(timestamps) / span

    def prometheus(self) -> str:
        s = self.snapshot()
        lines = [
            "# HELP invosync_uptime_seconds Process uptime.",
            "# TYPE invosync_uptime_seconds gauge",
            f"invosync_uptime_seconds {s['uptime_seconds']}",
            "# HELP invosync_requests_total Total HTTP requests.",
            "# TYPE invosync_requests_total counter",
            f"invosync_requests_total {s['requests_total']}",
            "# HELP invosync_requests_per_min Requests per minute (rolling 10m).",
            "# TYPE invosync_requests_per_min gauge",
            f"invosync_requests_per_min {s['requests_per_min']}",
            "# HELP invosync_errors_total Total 5xx responses.",
            "# TYPE invosync_errors_total counter",
            f"invosync_errors_total {s['errors_total']}",
            "# HELP invosync_error_rate_pct 5xx rate percentage.",
            "# TYPE invosync_error_rate_pct gauge",
            f"invosync_error_rate_pct {s['error_rate_pct']}",
            "# HELP invosync_invoices_processed_total Invoices extracted.",
            "# TYPE invosync_invoices_processed_total counter",
            f"invosync_invoices_processed_total {s['invoices_processed']}",
            "# HELP invosync_xml_generated_total XML files generated.",
            "# TYPE invosync_xml_generated_total counter",
            f"invosync_xml_generated_total {s['xml_generated']}",
            "# HELP invosync_tally_synced_total Vouchers pushed to Tally.",
            "# TYPE invosync_tally_synced_total counter",
            f"invosync_tally_synced_total {s['tally_synced']}",
            "# HELP invosync_queue_depth Pending extraction jobs.",
            "# TYPE invosync_queue_depth gauge",
            f"invosync_queue_depth {s['queue_depth']}",
            "# HELP invosync_worker_alive Background worker liveness.",
            "# TYPE invosync_worker_alive gauge",
            f"invosync_worker_alive {1 if s['worker_alive'] else 0}",
            "# HELP invosync_total_tokens Total AI tokens consumed.",
            "# TYPE invosync_total_tokens counter",
            f"invosync_total_tokens {s['total_tokens']}",
            "# HELP invosync_total_cost_usd Estimated AI cost in USD.",
            "# TYPE invosync_total_cost_usd counter",
            f"invosync_total_cost_usd {s['total_cost_usd']}",
        ]
        return "\n".join(lines) + "\n"


metrics = Metrics()
