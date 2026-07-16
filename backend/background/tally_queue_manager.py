"""TallySyncManager — tracks sync jobs submitted to the C# connector.

The extraction queue manager owns background work *inside* the backend.
The Tally sync manager owns the *handoff* to the C# connector — it records
job creation, then the connector polls, pushes to Tally, and reports back.
The manager provides a ``job_id`` so the frontend can poll status.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TallySyncJob:
    """A single Tally sync job — created by the backend, fulfilled by the connector."""

    job_id: str
    invoice_display_id: int
    status: str = "queued"  # queued → processing → success | failed
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class TallySyncManager:
    """Tracks sync jobs so frontends can poll ``/api/v3/sync/job/{id}``.

    Not a full queue — the actual Tally XML push is done by the C# connector
    (which polls ``/api/v3/sync/pending``).  This manager just records intent
    and final result.
    """

    def __init__(self):
        self._jobs: dict[str, TallySyncJob] = {}

    def create_job(self, invoice_display_id: int) -> str:
        """Register a new sync job and return its ID."""
        ts = int(time.time())
        job_id = f"tally_{invoice_display_id}_{ts}"
        self._jobs[job_id] = TallySyncJob(
            job_id=job_id,
            invoice_display_id=invoice_display_id,
            status="queued",
        )
        return job_id

    def get_job(self, job_id: str) -> Optional[TallySyncJob]:
        return self._jobs.get(job_id)

    def update_status(
        self, job_id: str, status: str, error: Optional[str] = None
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = status
        if error is not None:
            job.error = error
        if status in ("success", "failed"):
            job.completed_at = datetime.now(timezone.utc)

    @property
    def stats(self) -> dict:
        state_counts = {}
        for j in self._jobs.values():
            state_counts[j.status] = state_counts.get(j.status, 0) + 1
        return {"jobs": state_counts}
