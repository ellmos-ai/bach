# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Regression test for health.py _log_check() dedup fix.

Bug (2026-05-12): _log_check() created a new memory_working entry on every
call instead of updating the existing one.  On a system with 30-min health
check intervals this produced ~48 rows/day and bloated the DB.

Fix: SELECT existing entry for today before INSERT; UPDATE if found.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
HUB_ROOT = SYSTEM_ROOT / "hub"

if str(HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(HUB_ROOT))
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def _create_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE memory_working (
            id INTEGER PRIMARY KEY,
            type TEXT,
            content TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    conn.commit()
    conn.close()


def _count_health_entries(db_path: Path, *, active_only: bool = True) -> int:
    conn = sqlite3.connect(str(db_path))
    query = "SELECT COUNT(*) FROM memory_working WHERE content LIKE 'Health-Check:%'"
    if active_only:
        query += " AND is_active = 1"
    count = conn.execute(query).fetchone()[0]
    conn.close()
    return count


def _get_health_entries(db_path: Path) -> list:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, content, created_at, is_active FROM memory_working "
        "WHERE content LIKE 'Health-Check:%' ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def _make_handler(db_path: Path):
    """Create a minimal HealthCheckHandler with db_path pointed at temp DB."""
    try:
        from health import HealthCheckHandler
    except ImportError:
        pytest.skip("health module not importable")

    handler = object.__new__(HealthCheckHandler)
    handler.db_path = db_path
    return handler


class TestLogCheckDedup:
    """_log_check() must produce at most 1 active entry per day."""

    def test_single_call_creates_one_entry(self, tmp_path):
        db = tmp_path / "test.db"
        _create_db(db)
        handler = _make_handler(db)

        handler._log_check(True)

        assert _count_health_entries(db) == 1
        entries = _get_health_entries(db)
        assert entries[0][1] == "Health-Check: OK"

    def test_multiple_calls_same_day_stay_at_one(self, tmp_path):
        """Core regression: 10 calls must NOT produce 10 entries."""
        db = tmp_path / "test.db"
        _create_db(db)
        handler = _make_handler(db)

        for _ in range(10):
            handler._log_check(True)

        assert _count_health_entries(db) == 1

    def test_status_change_updates_existing(self, tmp_path):
        db = tmp_path / "test.db"
        _create_db(db)
        handler = _make_handler(db)

        handler._log_check(True)
        handler._log_check(False)

        assert _count_health_entries(db) == 1
        entries = _get_health_entries(db)
        assert entries[0][1] == "Health-Check: WARNUNGEN"

    def test_timestamp_updates_on_repeat(self, tmp_path):
        db = tmp_path / "test.db"
        _create_db(db)
        handler = _make_handler(db)

        handler._log_check(True)
        first = _get_health_entries(db)[0][2]

        import time
        time.sleep(0.05)

        handler._log_check(True)
        second = _get_health_entries(db)[0][2]

        assert second >= first

    def test_inactive_entry_not_reused(self, tmp_path):
        """An old inactive entry should not prevent new insert."""
        db = tmp_path / "test.db"
        _create_db(db)

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO memory_working (type, content, created_at, is_active) "
            "VALUES ('note', 'Health-Check: OK', ?, 0)",
            (f"{today} 08:00:00",),
        )
        conn.commit()
        conn.close()

        handler = _make_handler(db)
        handler._log_check(True)

        active = _count_health_entries(db, active_only=True)
        total = _count_health_entries(db, active_only=False)
        assert active == 1
        assert total == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
