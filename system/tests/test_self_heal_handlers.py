# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for small BACH self-heal handler fixes."""

import sqlite3
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def _init_base(tmp_path):
    base = tmp_path / "system"
    (base / "data").mkdir(parents=True)
    return base


def test_task_add_returns_created_id(tmp_path):
    from hub.task import TaskHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                priority TEXT,
                category TEXT,
                description TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                assigned_to TEXT,
                delegated_to TEXT,
                depends_on TEXT
            )
            """
        )

    success, message = TaskHandler(base).handle("add", ["Self-Heal Test"])

    assert success is True
    assert message == "[OK] Task 1 erstellt: Self-Heal Test"


def test_wiki_read_alias_shows_article(tmp_path):
    from hub.wiki import WikiHandler

    base = _init_base(tmp_path)
    wiki_dir = base / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "bach.txt").write_text("BACH Wiki Body", encoding="utf-8")

    success, message = WikiHandler(base).handle("read", ["bach"])

    assert success is True
    assert "WIKI: BACH" in message
    assert "BACH Wiki Body" in message


def test_mem_write_alias_uses_memory_handler(tmp_path):
    from hub.mem import MemHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_working (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                content TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_active INTEGER DEFAULT 1
            )
            """
        )

    success, message = MemHandler(base).handle("write", ["Kompatible", "Notiz"])

    assert success is True
    assert "Notiz gespeichert" in message

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT type, content FROM memory_working").fetchone()

    assert row == ("note", "Kompatible Notiz")
