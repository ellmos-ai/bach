# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
TOOLS_ROOT = SYSTEM_ROOT / "tools"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import memory_working_cleanup as cleanup_module


def _create_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memory_working (
            id INTEGER PRIMARY KEY,
            type TEXT,
            content TEXT,
            priority INTEGER,
            created_at TEXT,
            expires_at TEXT,
            is_active INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_note(db_path: Path, days_old: int, content: str) -> None:
    created_at = (datetime.now() - timedelta(days=days_old)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO memory_working (type, content, priority, created_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("note", content, 1, created_at, None, 1),
    )
    conn.commit()
    conn.close()


def test_analyze_stats_classifies_entries(tmp_path):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _insert_note(db_path, 1, "recent")
    _insert_note(db_path, 10, "review")
    _insert_note(db_path, 20, "archive")

    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    stats = cleanup.analyze_stats()

    assert stats["total"] == 3
    assert stats["keep"] == 1
    assert stats["review"] == 1
    assert stats["archive"] == 1


def test_main_analyze_prints_stats(monkeypatch, capsys):
    monkeypatch.setattr(
        cleanup_module.WorkingMemoryCleanup,
        "analyze_stats",
        lambda self: {
            "total": 2,
            "keep": 1,
            "review": 1,
            "archive": 0,
            "by_age": {"< 7d": 1, "7-14d": 1, "> 14d": 0},
            "entries": [
                {"age_days": 10.0, "action": "REVIEW", "content": "older note"},
                {"age_days": 1.0, "action": "KEEP", "content": "recent note"},
            ],
        },
    )
    monkeypatch.setattr(sys, "argv", ["memory_working_cleanup.py", "analyze"])

    cleanup_module.main()

    out = capsys.readouterr().out
    assert "WORKING MEMORY ANALYSE" in out
    assert "Total Eintraege:  2" in out
    assert "older note" in out


def test_cleanup_alias_delegates_to_cleanup_soft(monkeypatch, tmp_path):
    db_path = tmp_path / "working.db"
    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    calls = []

    def fake_cleanup_soft(self, dry_run=True):
        calls.append(dry_run)
        return True, "ok"

    monkeypatch.setattr(cleanup_module.WorkingMemoryCleanup, "cleanup_soft", fake_cleanup_soft)

    success, message = cleanup.cleanup(dry_run=False)

    assert success is True
    assert message == "ok"
    assert calls == [False]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
