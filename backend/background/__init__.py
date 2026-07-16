"""Background processing — extraction queue, worker loop, and stale-task cleanup.

Usage
-----
Routers submit work without touching the underlying ``asyncio.Queue``::

    from api.app_state import queue_manager
    from background.models import ExtractionJob

    job = ExtractionJob(invoice_id=..., tmp_path=..., ...)
    job_id = await queue_manager.submit(job)

``main.py`` starts the worker + cleanup loops during startup::

    from background import run_extraction_worker, run_cleanup_loop

    asyncio.create_task(run_extraction_worker(queue_manager))
    asyncio.create_task(run_cleanup_loop(queue_manager))
"""

from .queue_manager import ExtractionQueueManager
from .worker import run_extraction_worker
from .cleanup import run_cleanup_loop
from .models import ExtractionJob, TaskStatus
from .tally_queue_manager import TallySyncManager, TallySyncJob

__all__ = [
    "ExtractionQueueManager",
    "run_extraction_worker",
    "run_cleanup_loop",
    "ExtractionJob",
    "TaskStatus",
    "TallySyncManager",
    "TallySyncJob",
]
