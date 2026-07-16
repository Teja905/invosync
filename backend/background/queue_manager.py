"""ExtractionQueueManager — single public API for submitting and tracking extraction jobs.

Routers call `await queue_manager.submit(job)` instead of pushing onto a raw
``asyncio.Queue`` or touching ``processing_tasks`` directly.
"""

import asyncio
import time
from typing import Optional

from .models import ExtractionJob, TaskStatus


class ExtractionQueueManager:
    """Owns the extraction queue, task-status registry, and concurrency limits."""

    def __init__(self, max_concurrent: int = 3, task_ttl: int = 3600):
        self._queue: asyncio.Queue[ExtractionJob] = asyncio.Queue()
        self._tasks: dict[str, TaskStatus] = {}
        self.max_concurrent = max_concurrent
        self.task_ttl = task_ttl

    # ── Public API (used by routers) ──────────────────────────────────────

    async def submit(self, job: ExtractionJob) -> str:
        """Enqueue an extraction job and record its initial ``queued`` state.

        Returns the job ID (same as ``str(job.invoice_id)``).
        """
        job_id = str(job.invoice_id)
        self._tasks[job_id] = TaskStatus(state="queued", timestamp=time.monotonic())
        await self._queue.put(job)
        return job_id

    def get_status(self, job_id: str) -> Optional[str]:
        """Return the current state string for *job_id*, or ``None``."""
        entry = self._tasks.get(job_id)
        if entry is None:
            return None
        return entry.state

    # ── Internal API (used by worker / cleanup) ───────────────────────────

    async def get(self) -> ExtractionJob:
        """Block until a job is available (used by the background worker)."""
        return await self._queue.get()

    def task_done(self):
        """Mark the last fetched job as processed (called by the worker)."""
        self._queue.task_done()

    def pending_count(self) -> int:
        """Number of jobs not yet dequeued (queue depth)."""
        return self._queue.qsize()

    def set_status(self, job_id: str, state: str):
        """Update the status for *job_id* and refresh its timestamp."""
        self._tasks[job_id] = TaskStatus(state=state, timestamp=time.monotonic())

    def evict_stale(self) -> list[str]:
        """Remove entries older than ``task_ttl`` seconds.

        Returns the list of evicted job IDs for logging.
        """
        cutoff = time.monotonic() - self.task_ttl
        stale = [k for k, v in self._tasks.items() if v.timestamp < cutoff]
        for k in stale:
            self._tasks.pop(k, None)
        return stale

    @property
    def stats(self) -> dict:
        """Return a snapshot of queue depth and task-state counts."""
        state_counts = {}
        for s in self._tasks.values():
            state_counts[s.state] = state_counts.get(s.state, 0) + 1
        return {
            "queue_size": self._queue.qsize(),
            "tasks": state_counts,
        }
