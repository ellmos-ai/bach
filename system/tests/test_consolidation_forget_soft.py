#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test fuer weiches Vergessen (forget ohne DELETE auf memory_facts).

Entscheidung des Projektleiters (2026-09-26, E4):
- memory_facts wird nicht geloescht; Zeile bleibt unveraendert
- memory_consolidation erhaelt status = 'forgotten' fuer memory_facts
- memory_lessons und memory_working erhalten status = 'deleted' und is_active = 0
- Rueckgabetext unterscheidet zwischen deaktivierten und als vergessen markierten Eintraegen
"""

import sqlite3
import sys
from pathlib import Path
import pytest

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.consolidation import ConsolidationHandler

MINIMAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'text',
    confidence REAL DEFAULT 1.0,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);

CREATE TABLE IF NOT EXISTS memory_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    severity TEXT DEFAULT 'medium',
    title TEXT NOT NULL,
    problem TEXT,
    solution TEXT NOT NULL,
    related_tools TEXT,
    related_files TEXT,
    trigger_words TEXT,
    trigger_events TEXT,
    is_active INTEGER DEFAULT 1,
    times_shown INTEGER DEFAULT 0,
    last_shown TEXT,
    created_at TEXT,
    updated_at TEXT,
    dist_type INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS memory_consolidation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    times_accessed INTEGER DEFAULT 0,
    last_accessed TIMESTAMP,
    weight REAL DEFAULT 0.5,
    decay_rate REAL DEFAULT 0.95,
    threshold REAL DEFAULT 0.2,
    status TEXT DEFAULT 'active',
    consolidated_to INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_table, source_id)
);
"""


@pytest.fixture
def soft_forget_env(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()
    (system_dir / "help" / "wiki").mkdir()

    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(MINIMAL_SCHEMA_SQL)
    conn.close()

    handler = ConsolidationHandler(system_dir)
    handler.db_path = db_path
    return handler, db_path


class TestConsolidationForgetSoft:
    """Tests fuer weiches Vergessen gemaess Auftrag E4."""

    def test_forget_soft_facts_preserved_lessons_working_deactivated(self, soft_forget_env):
        handler, db_path = soft_forget_env

        conn = sqlite3.connect(str(db_path))
        # 1 Fakt, 1 Lesson, 1 Working
        conn.execute(
            "INSERT INTO memory_facts (category, key, value) VALUES (?, ?, ?)",
            ("system", "platform", "linux-arm64")
        )
        fact_id = 1

        conn.execute(
            "INSERT INTO memory_lessons (category, title, solution, is_active) VALUES (?, ?, ?, ?)",
            ("practice", "Test Lesson Title", "Use soft delete pattern", 1)
        )
        lesson_id = 1

        conn.execute(
            "INSERT INTO memory_working (type, content, is_active) VALUES (?, ?, ?)",
            ("scratchpad", "Temporary scratchpad content", 1)
        )
        working_id = 1

        # Tracking-Eintraege mit weight < 0.05
        conn.execute(
            """INSERT INTO memory_consolidation (source_table, source_id, weight, status)
               VALUES (?, ?, ?, ?)""",
            ("memory_facts", fact_id, 0.02, "active")
        )
        conn.execute(
            """INSERT INTO memory_consolidation (source_table, source_id, weight, status)
               VALUES (?, ?, ?, ?)""",
            ("memory_lessons", lesson_id, 0.01, "active")
        )
        conn.execute(
            """INSERT INTO memory_consolidation (source_table, source_id, weight, status)
               VALUES (?, ?, ?, ?)""",
            ("memory_working", working_id, 0.03, "active")
        )
        conn.commit()

        # Vorher-Zustand erfassen
        facts_before = conn.execute("SELECT id, category, key, value FROM memory_facts").fetchall()
        assert len(facts_before) == 1
        conn.close()

        # forget ausfuehren
        ok, msg = handler.handle("forget", [])
        assert ok is True
        assert "2 Einträge deaktiviert" in msg
        assert "1 als vergessen markiert" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # 1. Zeilenzahl von memory_facts vorher == nachher
        facts_after = conn.execute("SELECT id, category, key, value FROM memory_facts").fetchall()
        assert len(facts_after) == len(facts_before)
        # Fakt-Zeile existiert noch unveraendert
        assert facts_after[0]["id"] == facts_before[0][0]
        assert facts_after[0]["category"] == facts_before[0][1]
        assert facts_after[0]["key"] == facts_before[0][2]
        assert facts_after[0]["value"] == facts_before[0][3]

        # 2. consolidation-Status fuer Fakt ist 'forgotten'
        fact_cons = conn.execute(
            "SELECT status FROM memory_consolidation WHERE source_table = 'memory_facts' AND source_id = ?",
            (fact_id,)
        ).fetchone()
        assert fact_cons["status"] == "forgotten"

        # 3. Lesson/Working is_active = 0, Status 'deleted'
        lesson_row = conn.execute("SELECT is_active FROM memory_lessons WHERE id = ?", (lesson_id,)).fetchone()
        assert lesson_row["is_active"] == 0

        lesson_cons = conn.execute(
            "SELECT status FROM memory_consolidation WHERE source_table = 'memory_lessons' AND source_id = ?",
            (lesson_id,)
        ).fetchone()
        assert lesson_cons["status"] == "deleted"

        working_row = conn.execute("SELECT is_active FROM memory_working WHERE id = ?", (working_id,)).fetchone()
        assert working_row["is_active"] == 0

        working_cons = conn.execute(
            "SELECT status FROM memory_consolidation WHERE source_table = 'memory_working' AND source_id = ?",
            (working_id,)
        ).fetchone()
        assert working_cons["status"] == "deleted"

        conn.close()

    def test_forget_soft_dry_run(self, soft_forget_env):
        handler, db_path = soft_forget_env

        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO memory_facts (category, key, value) VALUES ('domain', 'k', 'v')")
        conn.execute("INSERT INTO memory_lessons (category, title, solution, is_active) VALUES ('dev', 'T', 'S', 1)")
        conn.execute("INSERT INTO memory_working (type, content, is_active) VALUES ('note', 'N', 1)")
        conn.execute("INSERT INTO memory_consolidation (source_table, source_id, weight, status) VALUES ('memory_facts', 1, 0.01, 'active')")
        conn.execute("INSERT INTO memory_consolidation (source_table, source_id, weight, status) VALUES ('memory_lessons', 1, 0.01, 'active')")
        conn.execute("INSERT INTO memory_consolidation (source_table, source_id, weight, status) VALUES ('memory_working', 1, 0.01, 'active')")
        conn.commit()
        conn.close()

        ok, msg = handler.handle("forget", [], dry_run=True)
        assert ok is True
        assert "[DRY-RUN]" in msg
        assert "2 Einträge deaktiviert, 1 als vergessen markiert" in msg

        conn = sqlite3.connect(str(db_path))
        # Nichts geaendert
        active_cons = conn.execute("SELECT COUNT(*) FROM memory_consolidation WHERE status = 'active'").fetchone()[0]
        assert active_cons == 3

        lesson_active = conn.execute("SELECT is_active FROM memory_lessons WHERE id = 1").fetchone()[0]
        assert lesson_active == 1

        working_active = conn.execute("SELECT is_active FROM memory_working WHERE id = 1").fetchone()[0]
        assert working_active == 1

        facts_count = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        assert facts_count == 1
        conn.close()

    def test_status_output_includes_forgotten(self, soft_forget_env):
        handler, db_path = soft_forget_env

        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO memory_facts (category, key, value) VALUES ('domain', 'k', 'v')")
        conn.execute("INSERT INTO memory_consolidation (source_table, source_id, weight, status) VALUES ('memory_facts', 1, 0.01, 'forgotten')")
        conn.commit()
        conn.close()

        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "- forgotten:" in msg
        assert "1" in msg
