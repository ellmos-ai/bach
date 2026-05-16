# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for LessonHandler (hub/lesson.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.lesson import LessonHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_lessons_table(conn):
    conn.execute("""
        CREATE TABLE memory_lessons (
            id INTEGER PRIMARY KEY,
            category TEXT DEFAULT 'general',
            severity TEXT DEFAULT 'medium',
            title TEXT NOT NULL,
            problem TEXT,
            solution TEXT,
            related_tools TEXT,
            is_active INTEGER DEFAULT 1,
            times_shown INTEGER DEFAULT 0,
            last_shown TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()


@pytest.fixture
def fake_lesson_env(tmp_path):
    """Minimal env with memory_lessons table."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_lessons_table(conn)
    conn.close()
    return tmp_path, db_path


@pytest.fixture
def seeded_env(tmp_path):
    """Env with pre-existing lessons."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_lessons_table(conn)

    conn.execute(
        "INSERT INTO memory_lessons (id, category, severity, title, problem, solution, is_active, times_shown, created_at, updated_at) "
        "VALUES (1, 'bug', 'high', 'DB-Pfad Bug', 'base_path war falsch', 'Immer _canonical_db nutzen', 1, 3, '2026-01-01 10:00', '2026-01-01 10:00')"
    )
    conn.execute(
        "INSERT INTO memory_lessons (id, category, severity, title, problem, solution, is_active, times_shown, created_at, updated_at) "
        "VALUES (2, 'workflow', 'medium', 'Git Workflow', NULL, 'Immer feature-branch nutzen', 1, 0, '2026-01-02 10:00', '2026-01-02 10:00')"
    )
    conn.execute(
        "INSERT INTO memory_lessons (id, category, severity, title, problem, solution, is_active, times_shown, created_at, updated_at) "
        "VALUES (3, 'tool', 'low', 'Alte Lesson', NULL, 'Nicht mehr relevant', 0, 5, '2025-12-01 10:00', '2025-12-01 10:00')"
    )
    conn.execute(
        "INSERT INTO memory_lessons (id, category, severity, title, problem, solution, is_active, times_shown, created_at, updated_at) "
        "VALUES (4, 'bug', 'critical', 'Encoding Bug', 'cp1252 auf Windows', 'PYTHONIOENCODING=utf-8 setzen', 1, 10, '2026-01-03 10:00', '2026-01-03 10:00')"
    )
    conn.commit()
    conn.close()
    return tmp_path, db_path


@pytest.fixture
def handler(fake_lesson_env):
    base, _ = fake_lesson_env
    return LessonHandler(base)


@pytest.fixture
def seeded_handler(seeded_env):
    base, _ = seeded_env
    return LessonHandler(base)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "lesson"

    def test_target_file(self, handler, fake_lesson_env):
        _, db_path = fake_lesson_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "add" in ops
        assert "list" in ops
        assert "search" in ops
        assert "show" in ops
        assert "last" in ops
        assert "edit" in ops
        assert "deactivate" in ops
        assert "categories" in ops

    def test_categories_constant(self, handler):
        assert "bug" in handler.CATEGORIES
        assert "general" in handler.CATEGORIES

    def test_severities_constant(self, handler):
        assert "low" in handler.SEVERITIES
        assert "critical" in handler.SEVERITIES


# ═══════════════════════════════════════════════════════════════
# ADD
# ═══════════════════════════════════════════════════════════════


class TestAdd:
    def test_add_simple(self, handler):
        ok, output = handler.handle("add", ["DB-Pfad: Immer data/bach.db verwenden"])
        assert ok is True
        assert "gespeichert" in output

    def test_add_with_colon_separator(self, handler):
        ok, output = handler.handle("add", ["Titel: Lösung hier"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "Titel" in out2
        assert "Lösung hier" in out2

    def test_add_with_category(self, handler):
        ok, output = handler.handle("add", ["Test Lesson --category bug"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "bug" in out2

    def test_add_with_severity(self, handler):
        ok, output = handler.handle("add", ["Test Lesson --severity critical"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "critical" in out2

    def test_add_with_problem(self, handler):
        ok, output = handler.handle("add", ["Test --problem Etwas ging schief"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "Etwas ging schief" in out2

    def test_add_no_args(self, handler):
        ok, output = handler.handle("add", [])
        assert ok is False
        assert "Usage" in output

    def test_add_dry_run(self, handler):
        ok, output = handler.handle("add", ["Dry Test: Solution"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output
        ok2, out2 = handler.handle("list", [])
        assert "Keine Lessons" in out2

    def test_add_long_title_truncated(self, handler):
        long_text = "A" * 100
        ok, output = handler.handle("add", [long_text])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "..." in out2 or len(long_text) > 50


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_all(self, seeded_handler):
        ok, output = seeded_handler.handle("list", [])
        assert ok is True
        assert "DB-Pfad Bug" in output
        assert "Git Workflow" in output
        assert "Encoding Bug" in output
        assert "Alte Lesson" not in output

    def test_list_by_category(self, seeded_handler):
        ok, output = seeded_handler.handle("list", ["bug"])
        assert ok is True
        assert "DB-Pfad Bug" in output
        assert "Encoding Bug" in output
        assert "Git Workflow" not in output

    def test_list_empty(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "Keine Lessons" in output

    def test_list_shows_count(self, seeded_handler):
        ok, output = seeded_handler.handle("list", [])
        assert "3 Lessons" in output


# ═══════════════════════════════════════════════════════════════
# LAST
# ═══════════════════════════════════════════════════════════════


class TestLast:
    def test_last_default(self, seeded_handler):
        ok, output = seeded_handler.handle("last", [])
        assert ok is True
        assert "LETZTE" in output

    def test_last_n(self, seeded_handler):
        ok, output = seeded_handler.handle("last", ["2"])
        assert ok is True
        assert "Encoding Bug" in output

    def test_last_empty(self, handler):
        ok, output = handler.handle("last", [])
        assert ok is True
        assert "Keine Lessons" in output

    def test_default_op_calls_last(self, seeded_handler):
        ok, output = seeded_handler.handle("unknown_op", [])
        assert ok is True
        assert "LETZTE" in output


# ═══════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════


class TestSearch:
    def test_search_by_title(self, seeded_handler):
        ok, output = seeded_handler.handle("search", ["Encoding"])
        assert ok is True
        assert "Encoding Bug" in output
        assert "1 Treffer" in output

    def test_search_by_solution(self, seeded_handler):
        ok, output = seeded_handler.handle("search", ["PYTHONIOENCODING"])
        assert ok is True
        assert "Encoding Bug" in output

    def test_search_no_results(self, seeded_handler):
        ok, output = seeded_handler.handle("search", ["nonexistent"])
        assert ok is True
        assert "Keine Treffer" in output

    def test_search_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("search", [])
        assert ok is False
        assert "Usage" in output

    def test_search_excludes_inactive(self, seeded_handler):
        ok, output = seeded_handler.handle("search", ["Alte Lesson"])
        assert ok is True
        assert "Keine Treffer" in output


# ═══════════════════════════════════════════════════════════════
# SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_existing(self, seeded_handler):
        ok, output = seeded_handler.handle("show", ["1"])
        assert ok is True
        assert "DB-Pfad Bug" in output
        assert "bug" in output
        assert "high" in output
        assert "base_path war falsch" in output
        assert "_canonical_db" in output

    def test_show_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("show", ["999"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_show_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("show", [])
        assert ok is False
        assert "Usage" in output


# ═══════════════════════════════════════════════════════════════
# EDIT
# ═══════════════════════════════════════════════════════════════


class TestEdit:
    def test_edit_title(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--title", "Neuer Titel"])
        assert ok is True
        assert "bearbeitet" in output
        ok2, out2 = seeded_handler.handle("show", ["1"])
        assert "Neuer Titel" in out2

    def test_edit_solution(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--solution", "Bessere Lösung"])
        assert ok is True
        assert "Solution aktualisiert" in output

    def test_edit_category(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--category", "workflow"])
        assert ok is True
        assert "workflow" in output

    def test_edit_severity(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--severity", "critical"])
        assert ok is True
        assert "critical" in output

    def test_edit_invalid_category(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--category", "invalid"])
        assert ok is False
        assert "Ungueltige Kategorie" in output

    def test_edit_invalid_severity(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--severity", "extreme"])
        assert ok is False
        assert "Ungueltige Severity" in output

    def test_edit_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["999", "--title", "X"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_edit_no_options(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1"])
        assert ok is False
        assert "Mindestens eine Option" in output

    def test_edit_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", [])
        assert ok is False
        assert "Usage" in output

    def test_edit_invalid_id(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["abc", "--title", "X"])
        assert ok is False
        assert "Ungueltige" in output


# ═══════════════════════════════════════════════════════════════
# DEACTIVATE
# ═══════════════════════════════════════════════════════════════


class TestDeactivate:
    def test_deactivate(self, seeded_handler):
        ok, output = seeded_handler.handle("deactivate", ["1"])
        assert ok is True
        assert "deaktiviert" in output
        ok2, out2 = seeded_handler.handle("search", ["DB-Pfad"])
        assert "Keine Treffer" in out2

    def test_deactivate_with_reason(self, seeded_handler):
        ok, output = seeded_handler.handle("deactivate", ["1", "--reason", "Veraltet"])
        assert ok is True
        assert "Veraltet" in output

    def test_deactivate_already_inactive(self, seeded_handler):
        ok, output = seeded_handler.handle("deactivate", ["3"])
        assert ok is False
        assert "bereits deaktiviert" in output

    def test_deactivate_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("deactivate", ["999"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_deactivate_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("deactivate", [])
        assert ok is False
        assert "Usage" in output

    def test_deactivate_invalid_id(self, seeded_handler):
        ok, output = seeded_handler.handle("deactivate", ["abc"])
        assert ok is False
        assert "Ungueltige" in output


# ═══════════════════════════════════════════════════════════════
# CATEGORIES
# ═══════════════════════════════════════════════════════════════


class TestCategories:
    def test_categories(self, handler):
        ok, output = handler.handle("categories", [])
        assert ok is True
        assert "bug" in output
        assert "workflow" in output
        assert "general" in output


# ═══════════════════════════════════════════════════════════════
# DB MISSING
# ═══════════════════════════════════════════════════════════════


class TestDbMissing:
    def test_missing_db(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "nonexistent" / "bach.db"
        monkeypatch.setattr("hub.bach_paths.BACH_DB", fake_db)
        h = LessonHandler(tmp_path)
        ok, output = h.handle("list", [])
        assert ok is False
        assert "nicht gefunden" in output


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import inspect
        source = inspect.getsource(LessonHandler)
        for i, line in enumerate(source.split("\n")):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except: pass":
                pytest.fail(f"Bare except at line {i+1}: {stripped}")
