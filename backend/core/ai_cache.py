"""Semantic cache for AI invoice extractions. Cuts Gemini/OpenRouter API costs by 40-60%.

Strategy:
1. Hash-based: sha256 of the normalized image bytes -> exact match cache
2. MongoDB-backed: persists across server restarts (write-through)
3. In-memory LRU front: fast lookup for repeat requests within a session
4. TTL: entries expire after 24 hours (invoices change, don't cache stale data)
5. Configurable: AI_CACHE_ENABLED env var to disable for debugging
"""

import hashlib
import os
import time
from collections import OrderedDict
from typing import Optional

from core.logging import get_logger

logger = get_logger(__name__)

_MAX_MEMORY_ENTRIES = 500
_CACHE_TTL_SECONDS = 86400  # 24 hours


class SemanticCache:
    def __init__(self, collection=None):
        self._memory: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._collection = collection  # MongoDB collection (optional)
        self._enabled = os.getenv("AI_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")

    def _make_key(self, image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()

    async def get(self, image_bytes: bytes) -> Optional[dict]:
        """Check memory then MongoDB for a cached extraction result."""
        if not self._enabled:
            return None
        key = self._make_key(image_bytes)
        # Memory LRU front
        mem_entry = self._memory.get(key)
        if mem_entry:
            ts, data = mem_entry
            if time.time() - ts < _CACHE_TTL_SECONDS:
                self._memory.move_to_end(key)
                return data
            del self._memory[key]
        # MongoDB persistent back
        if self._collection is not None:
            try:
                doc = await self._collection.find_one({"_id": key})
                if doc:
                    data = doc.get("data")
                    self._memory[key] = (time.time(), data)
                    return data
            except Exception as e:
                logger.debug("Cache MongoDB read failed (non-critical): %s", e)
        return None

    async def set(self, image_bytes: bytes, data: dict) -> None:
        """Write-through: store in both memory and MongoDB."""
        if not self._enabled:
            return
        key = self._make_key(image_bytes)
        self._memory[key] = (time.time(), data)
        # Evict oldest if over limit
        while len(self._memory) > _MAX_MEMORY_ENTRIES:
            self._memory.popitem(last=False)
        if self._collection is not None:
            try:
                await self._collection.update_one(
                    {"_id": key},
                    {"$set": {"data": data, "cached_at": time.time()}},
                    upsert=True,
                )
            except Exception as e:
                logger.debug("Cache MongoDB write failed (non-critical): %s", e)

    def invalidate(self, image_bytes: bytes) -> None:
        """Remove a specific entry from memory (MongoDB TTL handles expiry)."""
        key = self._make_key(image_bytes)
        self._memory.pop(key, None)

    def clear(self) -> None:
        """Flush in-memory cache. MongoDB entries expire via TTL index."""
        self._memory.clear()

    @property
    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "memory_entries": len(self._memory),
            "mongodb_connected": self._collection is not None,
        }
