"""Simple in-memory async cache with TTL. No Redis dependency."""

import hashlib
import json
import time
from typing import Any, Optional


class TTLCache:
    """Dict-based cache with time-to-live expiry. Thread-safe for asyncio.

    Usage:
        cache = TTLCache(ttl=60)
        data = await cache.get_or_set("my_key", fetch_from_db)
    """

    def __init__(self, ttl: int = 60, max_items: int = 500):
        self._ttl = ttl
        self._max_items = max_items
        self._store: dict[str, tuple[float, Any]] = {}

    def _key(self, *args, **kwargs) -> str:
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self._max_items:
            oldest = min(self._store.keys(), key=lambda k: self._store[k][0])
            del self._store[oldest]
        self._store[key] = (time.monotonic(), value)

    async def get_or_set(self, key: str, factory, ttl: Optional[int] = None) -> Any:
        """Get cached value or call async factory to produce it."""
        entry = self._store.get(key)
        if entry is not None:
            ts, value = entry
            if time.monotonic() - ts <= (ttl or self._ttl):
                return value
        value = await factory()
        self.set(key, value)
        return value

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def make_key(self, *args, **kwargs) -> str:
        return self._key(*args, **kwargs)


# Shared report cache: 60-second TTL means reports eventually consistent
# with newly generated XML, but avoid hitting MongoDB on every page load.
report_cache = TTLCache(ttl=60, max_items=200)
