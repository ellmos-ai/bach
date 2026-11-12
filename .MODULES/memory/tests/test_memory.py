# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone memory module."""
import time
from pathlib import Path
import pytest
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from memory import MemoryStore


def test_memory_notes_and_working_decay():
    store = MemoryStore()

    # Write permanent note
    nid1 = store.write_note("Permanent note", namespace="tasks", tags=["todo"])
    assert nid1 == 1

    # Write short-lived note (1 second TTL)
    nid2 = store.write_note("Short lived", namespace="working", ttl_seconds=1)
    assert nid2 == 2

    notes = store.read_notes(namespace="working")
    assert len(notes) == 1
    assert notes[0]["content"] == "Short lived"

    # Wait for TTL expiration
    time.sleep(1.1)
    cleaned = store.cleanup_expired()
    assert cleaned == 1

    # Now working note is decayed
    notes_after = store.read_notes(namespace="working")
    assert len(notes_after) == 0

    # Permanent note still exists
    perm = store.read_notes(namespace="tasks")
    assert len(perm) == 1


def test_memory_facts_and_search():
    store = MemoryStore()

    store.store_fact("user_name", "Lukas", confidence=1.0, tags=["identity"])
    store.store_fact("model_tier", "worker", confidence=0.9, tags=["system"])

    fact = store.get_fact("user_name")
    assert fact is not None
    assert fact["value"] == "Lukas"

    facts = store.list_facts()
    assert len(facts) == 2

    # Search
    results = store.search("Lukas")
    assert len(results) == 1
    assert results[0]["type"] == "fact"


def test_memory_sessions_and_export_import():
    store = MemoryStore()

    ok = store.store_session("sess-123", "Session completed successfully", duration_sec=42.5, partner="gemini")
    assert ok is True

    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess-123"

    status = store.status()
    assert status["sessions_count"] == 1

    # Export
    exported = store.export_data()
    assert "schema" in exported
    assert len(exported["sessions"]) == 1

    # Import into fresh store
    fresh = MemoryStore()
    imported_count = fresh.import_data(exported)
    assert imported_count >= 1
    assert fresh.status()["sessions_count"] == 1
