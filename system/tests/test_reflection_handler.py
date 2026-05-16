# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ReflectionHandler (hub/reflection.py)."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.reflection import ReflectionHandler


@pytest.fixture
def handler(tmp_path):
    db = tmp_path / "data" / "bach.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memory_working (
            id INTEGER PRIMARY KEY,
            type TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    return ReflectionHandler(tmp_path)


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "reflection"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "status" in ops
        assert "review" in ops
        assert "gaps" in ops
        assert "log" in ops


class TestHandle:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    @patch.object(ReflectionHandler, '_get_analyzer')
    def test_status(self, mock_analyzer, handler):
        analyzer = MagicMock()
        analyzer.format_report.return_value = "Performance OK"
        mock_analyzer.return_value = analyzer
        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "Performance OK" in msg

    @patch.object(ReflectionHandler, '_get_analyzer')
    def test_review_default_days(self, mock_analyzer, handler):
        analyzer = MagicMock()
        analyzer.review_performance.return_value = {"tasks_completed": 10, "avg_time": "2h"}
        mock_analyzer.return_value = analyzer
        ok, msg = handler.handle("review", [])
        assert ok is True
        assert "7 Tage" in msg
        analyzer.review_performance.assert_called_once_with(days=7)

    @patch.object(ReflectionHandler, '_get_analyzer')
    def test_review_custom_days(self, mock_analyzer, handler):
        analyzer = MagicMock()
        analyzer.review_performance.return_value = {"done": 5}
        mock_analyzer.return_value = analyzer
        ok, msg = handler.handle("review", ["14"])
        assert ok is True
        assert "14 Tage" in msg

    @patch.object(ReflectionHandler, '_get_analyzer')
    def test_gaps(self, mock_analyzer, handler):
        analyzer = MagicMock()
        analyzer.identify_gaps.return_value = ["Memory underused", "Tasks overdue"]
        mock_analyzer.return_value = analyzer
        ok, msg = handler.handle("gaps", [])
        assert ok is True
        assert "Memory underused" in msg
        assert "Tasks overdue" in msg

    def test_log_empty(self, handler):
        ok, msg = handler.handle("log", [])
        assert ok is True
        assert "Keine Reflection-Metriken" in msg

    def test_log_with_entries(self, handler):
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute(
            "INSERT INTO memory_working (type, content) VALUES (?, ?)",
            ("note", "REFLECTION: Score 4.2/5.0")
        )
        conn.commit()
        conn.close()
        ok, msg = handler.handle("log", [])
        assert ok is True
        assert "Score 4.2" in msg
