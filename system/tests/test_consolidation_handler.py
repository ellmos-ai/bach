#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer ConsolidationHandler"""

import sys
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.consolidation import ConsolidationHandler


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('scratchpad', 'context', 'loop', 'note')),
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
    category TEXT NOT NULL CHECK(category IN ('user', 'project', 'system', 'domain')),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'text',
    confidence REAL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);

CREATE TABLE IF NOT EXISTS memory_lessons (
    id INTEGER PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS memory_sessions (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    tasks_completed INTEGER DEFAULT 0,
    tasks_created INTEGER DEFAULT 0,
    tokens_used INTEGER,
    delegation_count INTEGER DEFAULT 0,
    continuation_context TEXT,
    dist_type INTEGER DEFAULT 0,
    is_compressed INTEGER DEFAULT 0,
    partner_id TEXT DEFAULT 'user'
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

CREATE TABLE IF NOT EXISTS memory_context (
    id INTEGER PRIMARY KEY,
    source_name TEXT UNIQUE NOT NULL,
    source_path TEXT,
    weight INTEGER DEFAULT 5,
    trigger_events TEXT,
    trigger_words TEXT,
    inject_on_match INTEGER DEFAULT 1,
    injection_template TEXT,
    is_active INTEGER DEFAULT 1,
    updated_at TEXT
);
"""


@pytest.fixture
def cons_env(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()
    (system_dir / "help" / "wiki").mkdir()

    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.close()

    handler = ConsolidationHandler(system_dir)
    handler.db_path = db_path
    return handler, db_path


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, cons_env):
        h, _ = cons_env
        assert h.profile_name == "consolidation"

    def test_target_file(self, cons_env):
        h, db = cons_env
        assert h.target_file == db

    def test_operations(self, cons_env):
        h, _ = cons_env
        ops = h.get_operations()
        assert "status" in ops
        assert "run" in ops
        assert "weight" in ops
        assert "archive" in ops
        assert "index" in ops
        assert "forget" in ops


# ================================================================
# ROUTING
# ================================================================

class TestRouting:
    def test_unknown_operation(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_db_not_found(self, cons_env):
        h, _ = cons_env
        h.db_path = Path("/nonexistent/bach.db")
        ok, msg = h.handle("status", [])
        assert ok is False
        assert "nicht gefunden" in msg


# ================================================================
# STATUS
# ================================================================

class TestStatus:
    def test_status_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("status", [])
        assert ok is True
        assert "CONSOLIDATION" in msg
        assert "MEMORY-TABELLEN" in msg

    def test_status_with_data(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO memory_facts (category, key, value) VALUES (?, ?, ?)",
                     ("system", "test_key", "test_value"))
        conn.execute("""INSERT INTO memory_consolidation
                        (source_table, source_id, weight, status, last_accessed)
                        VALUES (?, ?, ?, ?, ?)""",
                     ("memory_facts", 1, 0.8, "active", datetime.now().isoformat()))
        conn.commit()
        conn.close()

        ok, msg = h.handle("status", [])
        assert ok is True
        assert "Facts" in msg
        assert "KONSOLIDIERUNG" in msg


# ================================================================
# WEIGHT UPDATE
# ================================================================

class TestWeight:
    def test_weight_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("weight", [])
        assert ok is True
        assert "0 Gewichtungen" in msg

    def test_weight_dry_run(self, cons_env):
        h, db = cons_env
        past = (datetime.now() - timedelta(days=10)).isoformat()
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_consolidation
                        (source_table, source_id, weight, decay_rate, last_accessed, status)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     ("memory_facts", 1, 0.8, 0.95, past, "active"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("weight", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert "1 Gewichtungen" in msg

        conn = sqlite3.connect(str(db))
        weight = conn.execute("SELECT weight FROM memory_consolidation WHERE id = 1").fetchone()[0]
        conn.close()
        assert weight == 0.8

    def test_weight_applies_decay(self, cons_env):
        h, db = cons_env
        past = (datetime.now() - timedelta(days=5)).isoformat()
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_consolidation
                        (source_table, source_id, weight, decay_rate, last_accessed, status)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     ("memory_facts", 1, 1.0, 0.9, past, "active"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("weight", [])
        assert ok is True

        conn = sqlite3.connect(str(db))
        weight = conn.execute("SELECT weight FROM memory_consolidation WHERE id = 1").fetchone()[0]
        conn.close()
        expected = 1.0 * (0.9 ** 5)
        assert abs(weight - expected) < 0.001


# ================================================================
# ARCHIVE
# ================================================================

class TestArchive:
    def test_archive_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("archive", [])
        assert ok is True
        assert "0 Eintraege archiviert" in msg

    def test_archive_below_threshold(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_consolidation
                        (source_table, source_id, weight, status)
                        VALUES (?, ?, ?, ?)""",
                     ("memory_facts", 1, 0.1, "active"))
        conn.execute("""INSERT INTO memory_consolidation
                        (source_table, source_id, weight, status)
                        VALUES (?, ?, ?, ?)""",
                     ("memory_facts", 2, 0.8, "active"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("archive", [])
        assert ok is True
        assert "1 Eintraege archiviert" in msg

        conn = sqlite3.connect(str(db))
        status = conn.execute("SELECT status FROM memory_consolidation WHERE source_id = 1").fetchone()[0]
        conn.close()
        assert status == "archived"

    def test_archive_dry_run(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_consolidation
                        (source_table, source_id, weight, status)
                        VALUES (?, ?, ?, ?)""",
                     ("memory_facts", 1, 0.05, "active"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("archive", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db))
        status = conn.execute("SELECT status FROM memory_consolidation WHERE source_id = 1").fetchone()[0]
        conn.close()
        assert status == "active"


# ================================================================
# INDEX FACTS
# ================================================================

class TestIndex:
    def test_index_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("index", [])
        assert ok is True

    def test_index_with_help_files(self, cons_env):
        h, _ = cons_env
        help_dir = h.base_path / "help"
        (help_dir / "test_topic.txt").write_text("Test help content", encoding="utf-8")

        ok, msg = h.handle("index", [])
        assert ok is True


# ================================================================
# RUN ALL
# ================================================================

class TestRunAll:
    def test_run_all_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("run", [])
        assert ok is True
        assert "WEIGHT" in msg
        assert "ARCHIVE" in msg
        assert "INDEX" in msg

    def test_run_all_dry_run(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("run", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg


# ================================================================
# COMPRESS
# ================================================================

class TestCompress:
    def test_compress_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("compress", [])
        assert ok is True

    def test_compress_cleanup_marks_empty(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s1", "2026-01-01T10:00:00", "", 0))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s2", "2026-01-02T10:00:00", "AUTO-CLOSED: timeout", 0))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s3", "2026-01-03T10:00:00", "This is a real session summary with enough length to not be empty", 0))
        conn.commit()
        conn.close()

        ok, msg = h.handle("compress", ["--cleanup"])
        assert ok is True
        assert "2 leere Sessions" in msg

        conn = sqlite3.connect(str(db))
        s1 = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's1'").fetchone()[0]
        s2 = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's2'").fetchone()[0]
        s3 = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's3'").fetchone()[0]
        conn.close()
        assert s1 == 1
        assert s2 == 1
        assert s3 == 0

    def test_compress_cleanup_dry_run(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s1", "2026-01-01T10:00:00", None, 0))
        conn.commit()
        conn.close()

        ok, msg = h.handle("compress", ["--cleanup"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert "1 leere Sessions" in msg

        conn = sqlite3.connect(str(db))
        compressed = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's1'").fetchone()[0]
        conn.close()
        assert compressed == 0

    def test_compress_cleanup_none_found(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("compress", ["--cleanup"])
        assert ok is True
        assert "Keine leeren Sessions" in msg

    def test_compress_batch_groups_by_day(self, cons_env):
        h, db = cons_env
        long_summary = "A" * 60
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s1", "2026-03-01T10:00:00", long_summary, 0))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s2", "2026-03-01T14:00:00", long_summary, 0))
        conn.execute("""INSERT INTO memory_sessions
            (session_id, started_at, summary, is_compressed) VALUES (?, ?, ?, ?)""",
            ("s3", "2026-03-02T10:00:00", long_summary, 0))
        conn.commit()
        conn.close()

        ok, msg = h.handle("compress", ["--batch"])
        assert ok is True
        assert "2 Sessions komprimiert" in msg

        conn = sqlite3.connect(str(db))
        s1 = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's1'").fetchone()[0]
        s2 = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's2'").fetchone()[0]
        s3 = conn.execute("SELECT is_compressed FROM memory_sessions WHERE session_id = 's3'").fetchone()[0]
        conn.close()
        assert s1 == 1
        assert s2 == 1
        assert s3 == 0

    def test_compress_batch_none_found(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("compress", ["--batch"])
        assert ok is True
        assert "Keine zusammenfassbaren" in msg


# ================================================================
# RECLASSIFY
# ================================================================

class TestReclassify:
    def test_reclassify_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("reclassify", [])
        assert ok is True
        assert "Keine Reklassifizierungs-Vorschlaege" in msg

    def test_reclassify_manual_invalid_id(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("reclassify", ["lesson", "abc", "context"])
        assert ok is False
        assert "Ungueltige ID" in msg

    def test_reclassify_manual_unsupported(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("reclassify", ["fact", "1", "lesson"])
        assert ok is False
        assert "nicht unterstuetzt" in msg

    def test_reclassify_manual_dry_run(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("reclassify", ["lesson", "1", "context"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_reclassify_manual_working_to_fact(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_working (type, content, is_active)
            VALUES ('note', 'API-Key: sk-abc123', 1)""")
        conn.commit()
        wid = conn.execute("SELECT id FROM memory_working WHERE content LIKE '%API-Key%'").fetchone()[0]
        conn.close()

        ok, msg = h.handle("reclassify", ["working", str(wid), "fact"])
        assert ok is True
        assert "Konvertiert" in msg

        conn = sqlite3.connect(str(db))
        fact = conn.execute("SELECT key, value FROM memory_facts WHERE key = 'API-Key'").fetchone()
        active = conn.execute("SELECT is_active FROM memory_working WHERE id = ?", (wid,)).fetchone()[0]
        conn.close()
        assert fact is not None
        assert "sk-abc123" in fact[1]
        assert active == 0

    def test_reclassify_manual_lesson_to_context(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_lessons
            (category, title, solution, is_active, created_at, updated_at)
            VALUES ('bug', 'Test Lesson', 'Fix: restart service', 1, datetime('now'), datetime('now'))""")
        lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        ok, msg = h.handle("reclassify", ["lesson", str(lid), "context"])
        assert ok is True
        assert "Konvertiert" in msg

        conn = sqlite3.connect(str(db))
        ctx = conn.execute("SELECT source_name, injection_template FROM memory_context WHERE source_name = ?",
                           (f"LESSON_{lid}",)).fetchone()
        lesson_active = conn.execute("SELECT is_active FROM memory_lessons WHERE id = ?", (lid,)).fetchone()[0]
        conn.close()
        assert ctx is not None
        assert "Test Lesson" in ctx[1]
        assert lesson_active == 0

    def test_reclassify_manual_working_to_lesson(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("""INSERT INTO memory_working (type, content, is_active)
            VALUES ('note', 'Gelernt: Immer UTF-8 setzen bei Windows-Aufrufen', 1)""")
        wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        ok, msg = h.handle("reclassify", ["working", str(wid), "lesson"])
        assert ok is True
        assert "Konvertiert" in msg

        conn = sqlite3.connect(str(db))
        lesson = conn.execute("SELECT title, solution FROM memory_lessons WHERE category = 'workflow'").fetchone()
        active = conn.execute("SELECT is_active FROM memory_working WHERE id = ?", (wid,)).fetchone()[0]
        conn.close()
        assert lesson is not None
        assert "UTF-8" in lesson[1]
        assert active == 0

    def test_reclassify_manual_not_found(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("reclassify", ["working", "9999", "fact"])
        assert ok is False
        assert "fehlgeschlagen" in msg


# ================================================================
# FORGET
# ================================================================

class TestForget:
    def test_forget_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("forget", [])
        assert ok is True

    def test_forget_dry_run(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("forget", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg


# ================================================================
# INIT TRACKING
# ================================================================

class TestInit:
    def test_init_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("init", [])
        assert ok is True

    def test_init_with_facts(self, cons_env):
        h, db = cons_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO memory_facts (category, key, value) VALUES (?, ?, ?)",
                     ("system", "k1", "v1"))
        conn.execute("INSERT INTO memory_facts (category, key, value) VALUES (?, ?, ?)",
                     ("project", "k2", "v2"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("init", [])
        assert ok is True


# ================================================================
# REVIEW
# ================================================================

class TestReview:
    def test_review_empty(self, cons_env):
        h, _ = cons_env
        ok, msg = h.handle("review", [])
        assert ok is True
