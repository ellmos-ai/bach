# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for TokensHandler (hub/tokens.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.tokens import TokensHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_tables(conn):
    """Create monitor_tokens and monitor_pricing tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_tokens (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            model TEXT NOT NULL,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            tokens_total INTEGER DEFAULT 0,
            cost_eur REAL DEFAULT 0.0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_pricing (
            model TEXT PRIMARY KEY,
            input_price REAL DEFAULT 0.0,
            output_price REAL DEFAULT 0.0
        )
    """)
    conn.commit()


def _seed_data(conn):
    """Insert sample token usage data."""
    conn.executemany(
        "INSERT INTO monitor_tokens (timestamp, model, tokens_input, tokens_output, tokens_total, cost_eur) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2026-05-16T10:00:00", "claude-opus-4", 1000, 500, 1500, 0.05),
            ("2026-05-16T11:00:00", "claude-sonnet-4", 800, 400, 1200, 0.03),
            ("2026-05-15T09:00:00", "claude-opus-4", 2000, 1000, 3000, 0.10),
            ("2026-04-20T09:00:00", "claude-opus-4", 5000, 2000, 7000, 0.25),
        ],
    )
    conn.executemany(
        "INSERT INTO monitor_pricing (model, input_price, output_price) VALUES (?, ?, ?)",
        [
            ("claude-opus-4", 0.015, 0.075),
            ("claude-sonnet-4", 0.003, 0.015),
        ],
    )
    conn.commit()


@pytest.fixture
def tokens_env(tmp_path, monkeypatch):
    """Minimal env with monitor_tokens and monitor_pricing tables."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tables(conn)
    _seed_data(conn)
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def handler(tokens_env):
    base, _ = tokens_env
    return TokensHandler(base)


@pytest.fixture
def empty_handler(tmp_path, monkeypatch):
    """Handler with tables but no data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tables(conn)
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return TokensHandler(tmp_path)


# ═══════════════════════════════════════════════════════════════
# TESTS: PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "tokens"

    def test_target_file(self, handler):
        assert handler.target_file.name == "bach.db"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "status" in ops
        assert "today" in ops
        assert "week" in ops
        assert "report" in ops


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_with_data(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "TOKEN STATUS" in msg
        assert "Tokens" in msg

    def test_status_empty_db(self, empty_handler):
        ok, msg = empty_handler.handle("status", [])
        assert ok is True
        assert "TOKEN STATUS" in msg
        assert "0" in msg

    def test_default_operation_is_status(self, handler):
        """Empty/unknown op falls through to _status."""
        ok, msg = handler.handle("", [])
        assert ok is True
        assert "TOKEN STATUS" in msg

    def test_db_not_found(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "data" / "nonexistent.db"
        monkeypatch.setattr("hub.bach_paths.BACH_DB", fake_db)
        h = TokensHandler(tmp_path)
        ok, msg = h.handle("status", [])
        assert ok is False
        assert "nicht gefunden" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — TODAY
# ═══════════════════════════════════════════════════════════════


class TestToday:
    def test_today_with_data(self, handler):
        ok, msg = handler.handle("today", [])
        assert ok is True
        assert "HEUTE" in msg

    def test_today_empty(self, empty_handler):
        ok, msg = empty_handler.handle("today", [])
        assert ok is True
        assert "Keine Eintraege" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — WEEK
# ═══════════════════════════════════════════════════════════════


class TestWeek:
    def test_week_with_data(self, handler):
        ok, msg = handler.handle("week", [])
        assert ok is True
        assert "LETZTE 7 TAGE" in msg

    def test_week_empty(self, empty_handler):
        ok, msg = empty_handler.handle("week", [])
        assert ok is True
        assert "Keine Eintraege" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — REPORT
# ═══════════════════════════════════════════════════════════════


class TestReport:
    def test_report_with_data(self, handler):
        ok, msg = handler.handle("report", [])
        assert ok is True
        assert "TOKEN REPORT" in msg
        assert "Nach Model" in msg
        assert "Aktuelle Preise" in msg

    def test_report_has_pricing(self, handler):
        ok, msg = handler.handle("report", [])
        assert ok is True
        assert "claude-opus-4" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — UNKNOWN
# ═══════════════════════════════════════════════════════════════


class TestUnknown:
    def test_usage_falls_to_status(self, handler):
        """'usage' is not a valid operation -- falls through to _status."""
        ok, msg = handler.handle("usage", [])
        assert ok is True
        assert "TOKEN STATUS" in msg

    def test_unknown_operation_falls_to_status(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok is True
        assert "TOKEN STATUS" in msg
