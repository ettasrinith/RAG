"""LRU cache with TTL expiration for expensive operations (embeddings, search).

Thread-safe, with hit/miss statistics for observability.
"""
from __future__ import annotations

import hashlib
import time
import threading
from collections import OrderedDict
from typing import Any

from core.logging import get_logger

log = get_logger("cache")


class TTLCache:
    """Thread-safe LRU cache with TTL expiration."""

    def __init__(self, maxsize: int = 256, ttl_seconds: float = 300.0):
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._cache:
                ts, value = self._cache[key]
                if time.time() - ts < self._ttl:
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = (time.time(), value)

    def invalidate(self, prefix: str = "") -> int:
        """Invalidate entries matching prefix. Returns count removed."""
        with self._lock:
            if not prefix:
                count = len(self._cache)
                self._cache.clear()
                return count
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]
            return len(keys)

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
            "size": len(self._cache),
        }


def cache_key(*parts: str) -> str:
    """Create a stable cache key from parts."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Global caches
embedding_cache = TTLCache(maxsize=1024, ttl_seconds=3600)  # Embeddings are stable
search_cache = TTLCache(maxsize=256, ttl_seconds=60)        # Search results expire fast
