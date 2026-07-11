import asyncio
import functools
import time

from core.logging import get_logger

logger = get_logger(__name__)


def time_it(func):
    """Log how long a function takes. Works for sync and async."""
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        elapsed = (time.time() - start) * 1000
        logger.debug("%s took %.0fms", func.__name__, elapsed)
        return result

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = (time.time() - start) * 1000
        logger.debug("%s took %.0fms", func.__name__, elapsed)
        return result

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
