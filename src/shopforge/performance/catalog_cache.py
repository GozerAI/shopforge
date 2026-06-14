"""Product catalog caching with TTL invalidation.

Provides an in-memory LRU-style cache for product catalog data with
per-entry TTL, tag-based invalidation, and warm-up support.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 300
_DEFAULT_MAX_SIZE = 10_000


@dataclass
class CacheEntry:
    """Single cached value with metadata."""
    key: str
    value: Any
    created_at: float = field(default_factory=time.monotonic)
    ttl: float = _DEFAULT_TTL
    tags: Set[str] = field(default_factory=set)
    hit_count: int = 0

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def remaining_ttl(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())


@dataclass
class CacheStats:
    """Aggregated cache statistics."""
    size: int = 0
    max_size: int = _DEFAULT_MAX_SIZE
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    expired_purges: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "size": self.size, "max_size": self.max_size,
            "hits": self.hits, "misses": self.misses,
            "hit_rate": round(self.hit_rate, 2),
            "evictions": self.evictions,
            "invalidations": self.invalidations,
            "expired_purges": self.expired_purges,
        }


class CatalogCache:
    """Thread-safe product catalog cache with TTL and tag-based invalidation."""

    def __init__(self, default_ttl: float = _DEFAULT_TTL, max_size: int = _DEFAULT_MAX_SIZE):
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._entries: Dict[str, CacheEntry] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        self._access_order: List[str] = []
        self._lock = threading.Lock()
        self._stats = CacheStats(max_size=max_size)

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a cached value. Returns None on miss or expiry."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._stats.misses += 1
                return None
            if entry.is_expired:
                self._remove_entry(key)
                self._stats.misses += 1
                self._stats.expired_purges += 1
                return None
            entry.hit_count += 1
            self._stats.hits += 1
            self._touch(key)
            return entry.value

    def put(self, key: str, value: Any, ttl: Optional[float] = None,
            tags: Optional[Set[str]] = None) -> None:
        """Insert or overwrite a cache entry."""
        with self._lock:
            self._purge_expired()
            while len(self._entries) >= self._max_size:
                self._evict_lru()
            if key in self._entries:
                self._remove_entry(key)
            entry = CacheEntry(
                key=key, value=value,
                ttl=ttl if ttl is not None else self._default_ttl,
                tags=tags or set(),
            )
            self._entries[key] = entry
            self._access_order.append(key)
            self._stats.size = len(self._entries)
            for tag in entry.tags:
                self._tag_index.setdefault(tag, set()).add(key)

    def invalidate(self, key: str) -> bool:
        """Remove a single entry by key."""
        with self._lock:
            if key in self._entries:
                self._remove_entry(key)
                self._stats.invalidations += 1
                return True
            return False

    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all entries sharing a tag."""
        with self._lock:
            keys = self._tag_index.pop(tag, set())
            for k in list(keys):
                if k in self._entries:
                    self._remove_entry(k)
                    self._stats.invalidations += 1
            return len(keys)

    def invalidate_by_prefix(self, prefix: str) -> int:
        """Invalidate all entries whose key starts with prefix."""
        with self._lock:
            to_remove = [k for k in self._entries if k.startswith(prefix)]
            for k in to_remove:
                self._remove_entry(k)
                self._stats.invalidations += 1
            return len(to_remove)

    def clear(self) -> int:
        """Flush the entire cache."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._tag_index.clear()
            self._access_order.clear()
            self._stats.size = 0
            return count

    def get_or_compute(self, key: str, compute_fn: Callable[[], Any],
                       ttl: Optional[float] = None, tags: Optional[Set[str]] = None) -> Any:
        """Return cached value or compute, cache, and return it."""
        val = self.get(key)
        if val is not None:
            return val
        result = compute_fn()
        self.put(key, result, ttl=ttl, tags=tags)
        return result

    def warm(self, items: Dict[str, Any], ttl: Optional[float] = None) -> int:
        """Bulk-load entries. Returns count loaded."""
        count = 0
        for key, value in items.items():
            self.put(key, value, ttl=ttl)
            count += 1
        return count

    def keys(self) -> List[str]:
        """Return list of non-expired keys."""
        with self._lock:
            return [k for k, e in self._entries.items() if not e.is_expired]

    def get_stats(self) -> CacheStats:
        """Return a snapshot of cache statistics."""
        with self._lock:
            self._stats.size = len(self._entries)
            s = self._stats
            return CacheStats(
                size=s.size, max_size=s.max_size, hits=s.hits, misses=s.misses,
                evictions=s.evictions, invalidations=s.invalidations,
                expired_purges=s.expired_purges,
            )

    def _remove_entry(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry:
            for tag in entry.tags:
                tag_set = self._tag_index.get(tag)
                if tag_set:
                    tag_set.discard(key)
                    if not tag_set:
                        del self._tag_index[tag]
            if key in self._access_order:
                self._access_order.remove(key)
            self._stats.size = len(self._entries)

    def _touch(self, key: str) -> None:
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

    def _evict_lru(self) -> None:
        if not self._access_order:
            return
        self._remove_entry(self._access_order[0])
        self._stats.evictions += 1

    def _purge_expired(self) -> None:
        expired = [k for k, e in self._entries.items() if e.is_expired]
        for k in expired:
            self._remove_entry(k)
            self._stats.expired_purges += 1
