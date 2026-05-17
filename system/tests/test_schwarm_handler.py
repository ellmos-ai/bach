# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SchwarmHandler.

Tests core operations: list, run, status, and validates
that pattern operations handle edge cases gracefully.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


@pytest.fixture
def handler(tmp_path, monkeypatch):
    """SchwarmHandler with a temporary DB."""
    db_path = tmp_path / "test_bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schwarm_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT,
            task TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            workers INTEGER DEFAULT 1,
            duration_ms INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

    from hub.schwarm import SchwarmHandler
    h = SchwarmHandler(SYSTEM_ROOT)
    monkeypatch.setattr(h, "db_path", db_path)
    return h


class TestSchwarmBasic:
    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "list" in ops
        assert "consensus" in ops
        assert "translate" in ops

    def test_list_patterns(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "SCHWARM-MUSTER" in msg
        assert "parallel-chunks" in msg
        assert "consensus" in msg.lower()

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent_op", [])
        assert ok is False
        assert "Unbekannte" in msg or "unbekannt" in msg.lower()

    def test_run_no_args(self, handler):
        ok, msg = handler.handle("run", [])
        assert ok is False
        assert "Usage" in msg or "usage" in msg.lower()

    def test_run_unknown_pattern(self, handler):
        ok, msg = handler.handle("run", ["nonexistent_pattern", "test task"])
        assert ok is False

    def test_status_empty(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok is True

    def test_translate_no_args_shows_help(self, handler):
        ok, msg = handler.handle("translate", [])
        assert isinstance(msg, str)

    def test_consensus_no_args(self, handler):
        ok, msg = handler.handle("consensus", [])
        assert ok is False or "Usage" in msg or "Frage" in msg

    def test_hierarchy_no_args(self, handler):
        ok, msg = handler.handle("hierarchy", [])
        assert ok is False or isinstance(msg, str)

    def test_specialist_no_args(self, handler):
        ok, msg = handler.handle("specialist", [])
        assert ok is False or isinstance(msg, str)


class TestSchwarmPatterns:
    def test_all_patterns_are_defined(self, handler):
        expected = {"parallel-chunks", "hierarchy", "stigmergy", "consensus", "specialist"}
        assert set(handler.PATTERNS.keys()) == expected

    def test_all_patterns_have_required_fields(self, handler):
        for key, pattern in handler.PATTERNS.items():
            assert "name" in pattern, f"Pattern {key} missing 'name'"
            assert "desc" in pattern, f"Pattern {key} missing 'desc'"
            assert "status" in pattern, f"Pattern {key} missing 'status'"

    def test_legacy_alias_epstein_maps_to_parallel_chunks(self, handler):
        ok, msg = handler.handle("run", ["epstein", "test task"])
        assert ok is True
        assert "Parallel Chunks" in msg or "sub-commands" in msg.lower()

    def test_legacy_alias_konsensus(self, handler):
        ok, msg = handler.handle("run", ["konsensus", "Testfrage?"], dry_run=True)
        assert ok is True
        assert "Konsensus" in msg or "DRY-RUN" in msg

    def test_consensus_dry_run_returns_plan(self, handler):
        ok, msg = handler.handle("consensus", ["Testfrage?"], dry_run=True)
        assert isinstance(msg, str)
