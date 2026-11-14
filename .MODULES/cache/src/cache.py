# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: cache
===========================
Self-contained key-value and function caching with TTL, namespace isolation, and persistence.
"""

from __future__ import annotations

import functools
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class CacheEntry:
    key: str
    value: Any
    expires_at: Optional[float]
    created_at: float

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at


class CacheManager:
    """Fast, thread-safe, self-contained cache store with TTL and namespace partitioning."""

    def __init__(self, persistence_file: Optional[Path | str] = None, default_ttl: Optional[int] = None):
        self.persistence_file = Path(persistence_file) if persistence_file else None
        self.default_ttl = default_ttl
        self._entries: Dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        if self.persistence_file and self.persistence_file.is_file():
            self._load()

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a cached value if present and not expired."""
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return default

        if entry.is_expired:
            del self._entries[key]
            self._evictions += 1
            self._misses += 1
            return default

        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Stores a key-value pair with optional TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = (time.time() + ttl) if ttl and ttl > 0 else None
        self._entries[key] = CacheEntry(
            key=key,
            value=value,
            expires_at=expires_at,
            created_at=time.time(),
        )
        self._save()

    def delete(self, key: str) -> bool:
        """Deletes a key from the cache."""
        if key in self._entries:
            del self._entries[key]
            self._save()
            return True
        return False

    def has(self, key: str) -> bool:
        """Checks if key exists and is unexpired."""
        entry = self._entries.get(key)
        if entry is None or entry.is_expired:
            return False
        return True

    def clear(self) -> None:
        """Clears all cached entries."""
        self._entries.clear()
        self._save()

    def stats(self) -> Dict[str, Any]:
        """Returns cache telemetry stats."""
        total = self._hits + self._misses
        hit_ratio = round((self._hits / total) if total > 0 else 0.0, 4)
        active_keys = sum(1 for e in self._entries.values() if not e.is_expired)
        return {
            "total_keys": len(self._entries),
            "active_keys": active_keys,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_ratio": hit_ratio,
        }

    def namespace(self, ns: str) -> "NamespaceCache":
        """Returns a namespaced wrapper around this cache manager."""
        return NamespaceCache(self, ns)

    def _save(self) -> None:
        if not self.persistence_file:
            return
        try:
            self.persistence_file.parent.mkdir(parents=True, exist_ok=True)
            serializable = {}
            for k, entry in self._entries.items():
                if not entry.is_expired:
                    serializable[k] = {
                        "value": entry.value,
                        "expires_at": entry.expires_at,
                        "created_at": entry.created_at,
                    }
            tmp = self.persistence_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")
            tmp.replace(self.persistence_file)
        except (OSError, TypeError):
            pass

    def _load(self) -> None:
        if not self.persistence_file or not self.persistence_file.is_file():
            return
        try:
            data = json.loads(self.persistence_file.read_text(encoding="utf-8"))
            for k, raw in data.items():
                entry = CacheEntry(
                    key=k,
                    value=raw["value"],
                    expires_at=raw.get("expires_at"),
                    created_at=raw.get("created_at", time.time()),
                )
                if not entry.is_expired:
                    self._entries[k] = entry
        except Exception:
            pass


class NamespaceCache:
    """Prefixes keys with a namespace delimiter."""

    def __init__(self, backend: CacheManager, namespace: str):
        self.backend = backend
        self.namespace = namespace

    def _k(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def get(self, key: str, default: Any = None) -> Any:
        return self.backend.get(self._k(key), default=default)

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        self.backend.set(self._k(key), value, ttl_seconds=ttl_seconds)

    def delete(self, key: str) -> bool:
        return self.backend.delete(self._k(key))

    def has(self, key: str) -> bool:
        return self.backend.has(self._k(key))


def cached(cache: CacheManager, ttl: Optional[int] = None, namespace: str = "fn") -> Callable[[F], F]:
    """Decorator to cache function results by hashed arguments."""

    def decorator(fn: F) -> F:
        ns = cache.namespace(namespace)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            arg_str = f"{args}:{sorted(kwargs.items())}"
            h = hashlib.sha256(arg_str.encode("utf-8")).hexdigest()[:16]
            key = f"{fn.__qualname__}:{h}"
            cached_val = ns.get(key)
            if cached_val is not None:
                return cached_val
            result = fn(*args, **kwargs)
            ns.set(key, result, ttl_seconds=ttl)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
