# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone cache module."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cache import CacheManager, cached


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "cache"
    assert data["selfcontained"] is True


def test_cache_basic_and_ttl():
    cache = CacheManager()
    cache.set("foo", "bar", ttl_seconds=1)
    assert cache.get("foo") == "bar"
    assert cache.has("foo") is True

    # Stats check
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 0

    time.sleep(1.05)
    assert cache.get("foo") is None
    assert cache.has("foo") is False
    assert cache.stats()["evictions"] == 1


def test_cache_namespace_and_decorator():
    cache = CacheManager()
    ns1 = cache.namespace("alpha")
    ns2 = cache.namespace("beta")

    ns1.set("key", 100)
    ns2.set("key", 200)

    assert ns1.get("key") == 100
    assert ns2.get("key") == 200

    calls = 0

    @cached(cache, ttl=60, namespace="test_fn")
    def compute(a: int, b: int) -> int:
        nonlocal calls
        calls += 1
        return a + b

    assert compute(2, 3) == 5
    assert calls == 1
    # Second call should hit cache
    assert compute(2, 3) == 5
    assert calls == 1


def test_cache_persistence(tmp_path: Path):
    f = tmp_path / "cache.json"
    c1 = CacheManager(persistence_file=f)
    c1.set("item1", {"name": "test"}, ttl_seconds=60)

    c2 = CacheManager(persistence_file=f)
    assert c2.get("item1") == {"name": "test"}
