"""Periodic cleanup loop that evicts stale task-status entries."""

import asyncio

from core.logging import get_logger
from .queue_manager import ExtractionQueueManager

logger = get_logger(__name__)


async def run_cleanup_loop(manager: ExtractionQueueManager, interval: int = 600):
    """Evict stale ``processing_tasks`` entries every *interval* seconds.

    Crash-proof: loop restart on any error so stale-task eviction never stops.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            stale = manager.evict_stale()
            if stale:
                logger.info("Evicted %d stale processing_tasks entries", len(stale))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("CLEANUP loop error, retrying in %ss: %s", interval, e)
            await asyncio.sleep(interval)
