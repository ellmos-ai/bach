# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for TaskHandler (hub/task.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.task import TaskHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_tasks_table(conn):
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            description TEXT DEFAULT '',
            assigned_to TEXT,
            delegated_to TEXT,
            depends_on TEXT,
            created_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()


@pytest.fixture
def fake_task_env(tmp_path, monkeypatch):
    """Minimal env with tasks table."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tasks_table(conn)
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def seeded_env(tmp_path, monkeypatch):
    """Env with pre-existing tasks."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tasks_table(conn)

    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, category, created_at) "
        "VALUES (1, 'Fix critical bug', 'pending', 'P1', 'bugfix', '2026-01-01 10:00')"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, category, created_at) "
        "VALUES (2, 'Write docs', 'pending', 'P3', 'docs', '2026-01-02 10:00')"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, category, created_at) "
        "VALUES (3, 'Old task', 'done', 'P4', 'general', '2025-12-01 10:00')"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, category, created_at) "
        "VALUES (4, 'Blocked work', 'blocked', 'P2', 'infra', '2026-01-03 10:00')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def handler(fake_task_env):
    base, _ = fake_task_env
    return TaskHandler(base)


@pytest.fixture
def seeded_handler(seeded_env):
    base, _ = seeded_env
    return TaskHandler(base)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "task"

    def test_target_file(self, handler, fake_task_env):
        _, db_path = fake_task_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "add" in ops
        assert "list" in ops
        assert "done" in ops
        assert "show" in ops
        assert "delete" in ops
        assert "priority" in ops
        assert "depends" in ops


# ═══════════════════════════════════════════════════════════════
# ADD
# ═══════════════════════════════════════════════════════════════


class TestAdd:
    def test_add_simple(self, handler):
        ok, output = handler.handle("add", ["New task"])
        assert ok is True
        assert "erstellt" in output
        assert "New task" in output

    def test_add_with_priority(self, handler):
        ok, output = handler.handle("add", ["Urgent", "--priority", "P1"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "P1" in out2

    def test_add_with_description(self, handler):
        ok, output = handler.handle("add", ["Task", "-d", "Details here"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "Details here" in out2

    def test_add_with_category(self, handler):
        ok, output = handler.handle("add", ["Task", "-c", "bugfix"])
        assert ok is True
        ok2, out2 = handler.handle("show", ["1"])
        assert "bugfix" in out2

    def test_add_no_args(self, handler):
        ok, output = handler.handle("add", [])
        assert ok is False
        assert "Usage" in output

    def test_add_sanitizes_title(self, handler):
        ok, output = handler.handle("add", ['Unbalanced "quote'])
        assert ok is True
        assert '"' not in output.split("erstellt:")[1]


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_default_pending(self, seeded_handler):
        ok, output = seeded_handler.handle("list", [])
        assert ok is True
        assert "Fix critical bug" in output
        assert "Write docs" in output
        assert "Old task" not in output

    def test_list_all(self, seeded_handler):
        ok, output = seeded_handler.handle("list", ["all"])
        assert ok is True
        assert "Fix critical bug" in output
        assert "Old task" in output
        assert "Blocked work" in output

    def test_list_done(self, seeded_handler):
        ok, output = seeded_handler.handle("list", ["done"])
        assert ok is True
        assert "Old task" in output
        assert "Fix critical bug" not in output

    def test_list_blocked(self, seeded_handler):
        ok, output = seeded_handler.handle("list", ["blocked"])
        assert ok is True
        assert "Blocked work" in output

    def test_list_filter(self, seeded_handler):
        ok, output = seeded_handler.handle("list", ["all", "--filter=bug"])
        assert ok is True
        assert "Fix critical bug" in output
        assert "Write docs" not in output

    def test_list_empty_result(self, seeded_handler):
        ok, output = seeded_handler.handle("list", ["all", "--filter=nonexistent_xyz"])
        assert ok is True
        assert "Keine Tasks" in output


# ═══════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════


class TestDone:
    def test_done_single(self, seeded_handler):
        ok, output = seeded_handler.handle("done", ["1"])
        assert ok is True
        assert "erledigt" in output
        ok2, out2 = seeded_handler.handle("show", ["1"])
        assert "done" in out2

    def test_done_multi(self, seeded_handler):
        ok, output = seeded_handler.handle("done", ["1", "2"])
        assert ok is True
        assert output.count("erledigt") == 2

    def test_done_with_note(self, seeded_handler):
        ok, output = seeded_handler.handle("done", ["1", "--note", "Fixed via PR"])
        assert ok is True
        ok2, out2 = seeded_handler.handle("show", ["1"])
        assert "Fixed via PR" in out2

    def test_done_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("done", ["999"])
        assert ok is True
        assert "WARN" in output

    def test_done_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("done", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# BLOCK / UNBLOCK
# ═══════════════════════════════════════════════════════════════


class TestBlockUnblock:
    def test_block(self, seeded_handler):
        ok, output = seeded_handler.handle("block", ["1"])
        assert ok is True
        assert "blockiert" in output
        ok2, out2 = seeded_handler.handle("show", ["1"])
        assert "blocked" in out2

    def test_block_with_reason(self, seeded_handler):
        ok, output = seeded_handler.handle("block", ["1", "--reason", "Waiting for API"])
        assert ok is True
        assert "Waiting for API" in output

    def test_unblock(self, seeded_handler):
        ok, output = seeded_handler.handle("unblock", ["4"])
        assert ok is True
        assert "entblockt" in output
        ok2, out2 = seeded_handler.handle("show", ["4"])
        assert "pending" in out2

    def test_unblock_not_blocked(self, seeded_handler):
        ok, output = seeded_handler.handle("unblock", ["1"])
        assert ok is True
        assert "nicht blockiert" in output

    def test_block_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("block", [])
        assert ok is False

    def test_unblock_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("unblock", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# REOPEN
# ═══════════════════════════════════════════════════════════════


class TestReopen:
    def test_reopen_done(self, seeded_handler):
        ok, output = seeded_handler.handle("reopen", ["3"])
        assert ok is True
        assert "wieder geoeffnet" in output
        ok2, out2 = seeded_handler.handle("show", ["3"])
        assert "pending" in out2

    def test_reopen_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("reopen", ["999"])
        assert ok is True
        assert "WARN" in output

    def test_reopen_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("reopen", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_existing(self, seeded_handler):
        ok, output = seeded_handler.handle("show", ["1"])
        assert ok is True
        assert "Fix critical bug" in output
        assert "P1" in output
        assert "pending" in output
        assert "bugfix" in output

    def test_show_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("show", ["999"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_show_invalid_id(self, seeded_handler):
        ok, output = seeded_handler.handle("show", ["abc"])
        assert ok is False
        assert "Ungueltige" in output

    def test_show_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("show", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════════


class TestDelete:
    def test_delete_single(self, seeded_handler):
        ok, output = seeded_handler.handle("delete", ["2"])
        assert ok is True
        assert "geloescht" in output
        ok2, out2 = seeded_handler.handle("show", ["2"])
        assert ok2 is False

    def test_delete_multi(self, seeded_handler):
        ok, output = seeded_handler.handle("delete", ["1", "2"])
        assert ok is True
        assert output.count("geloescht") == 2

    def test_delete_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("delete", ["999"])
        assert ok is True
        assert "WARN" in output

    def test_delete_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("delete", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# PRIORITY
# ═══════════════════════════════════════════════════════════════


class TestPriority:
    def test_change_priority(self, seeded_handler):
        ok, output = seeded_handler.handle("priority", ["2", "P1"])
        assert ok is True
        assert "P1" in output
        ok2, out2 = seeded_handler.handle("show", ["2"])
        assert "P1" in out2

    def test_priority_case_insensitive(self, seeded_handler):
        ok, output = seeded_handler.handle("priority", ["2", "p2"])
        assert ok is True
        assert "P2" in output

    def test_priority_invalid(self, seeded_handler):
        ok, output = seeded_handler.handle("priority", ["2", "P5"])
        assert ok is False
        assert "P1, P2, P3 oder P4" in output

    def test_priority_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("priority", ["999", "P1"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_priority_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("priority", ["1"])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# EDIT
# ═══════════════════════════════════════════════════════════════


class TestEdit:
    def test_edit_title(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--title", "New title"])
        assert ok is True
        assert "bearbeitet" in output
        ok2, out2 = seeded_handler.handle("show", ["1"])
        assert "New title" in out2

    def test_edit_category(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1", "--category", "feature"])
        assert ok is True
        ok2, out2 = seeded_handler.handle("show", ["1"])
        assert "feature" in out2

    def test_edit_no_options(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["1"])
        assert ok is False
        assert "Mindestens eine Option" in output

    def test_edit_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["999", "--title", "X"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_edit_invalid_id(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", ["abc"])
        assert ok is False

    def test_edit_no_args(self, seeded_handler):
        ok, output = seeded_handler.handle("edit", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# ASSIGN
# ═══════════════════════════════════════════════════════════════


class TestAssign:
    def test_assign_to_partner(self, seeded_handler):
        ok, output = seeded_handler.handle("assign", ["1", "--to", "GEMINI"])
        assert ok is True
        assert "GEMINI" in output

    def test_assign_unknown_partner(self, seeded_handler):
        ok, output = seeded_handler.handle("assign", ["1", "--to", "UNKNOWN_AI"])
        assert ok is True
        assert "nicht in bekannter Liste" in output

    def test_assign_no_partner(self, seeded_handler):
        ok, output = seeded_handler.handle("assign", ["1"])
        assert ok is False
        assert "--to PARTNER" in output

    def test_assign_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("assign", ["999", "--to", "CLAUDE"])
        assert ok is True
        assert "WARN" in output


# ═══════════════════════════════════════════════════════════════
# DEPENDS
# ═══════════════════════════════════════════════════════════════


class TestDepends:
    def test_add_dependency(self, seeded_handler):
        ok, output = seeded_handler.handle("depends", ["2", "--on", "1"])
        assert ok is True
        assert "haengt jetzt von Task 1 ab" in output

    def test_show_dependencies(self, seeded_handler):
        seeded_handler.handle("depends", ["2", "--on", "1"])
        ok, output = seeded_handler.handle("depends", ["2"])
        assert ok is True
        assert "Fix critical bug" in output

    def test_circular_dependency(self, seeded_handler):
        ok, output = seeded_handler.handle("depends", ["1", "--on", "1"])
        assert ok is False
        assert "Zirkulaere" in output

    def test_remove_dependency(self, seeded_handler):
        seeded_handler.handle("depends", ["2", "--on", "1"])
        ok, output = seeded_handler.handle("depends", ["2", "--remove", "1"])
        assert ok is True
        assert "entfernt" in output

    def test_clear_dependencies(self, seeded_handler):
        seeded_handler.handle("depends", ["2", "--on", "1"])
        ok, output = seeded_handler.handle("depends", ["2", "--clear"])
        assert ok is True
        assert "Alle Abhaengigkeiten entfernt" in output

    def test_no_dependencies(self, seeded_handler):
        ok, output = seeded_handler.handle("depends", ["1"])
        assert ok is True
        assert "Keine Abhaengigkeiten" in output

    def test_depends_not_found(self, seeded_handler):
        ok, output = seeded_handler.handle("depends", ["999"])
        assert ok is False
        assert "nicht gefunden" in output


# ═══════════════════════════════════════════════════════════════
# HELP & UNKNOWN
# ═══════════════════════════════════════════════════════════════


class TestHelpUnknown:
    def test_help(self, handler):
        ok, output = handler.handle("help", [])
        assert ok is True
        assert "TASK-VERWALTUNG" in output

    def test_empty_op(self, handler):
        ok, output = handler.handle("", [])
        assert ok is True
        assert "TASK-VERWALTUNG" in output

    def test_unknown_op(self, handler):
        ok, output = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in output


# ═══════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════


class TestHelpers:
    def test_parse_ids(self, handler):
        ids, rest = handler._parse_ids(["1", "2", "--note", "text", "3"])
        assert ids == [1, 2, 3]
        assert "--note" in rest
        assert "text" in rest

    def test_get_note(self, handler):
        assert handler._get_note(["--note", "my note"]) == "my note"
        assert handler._get_note(["--note=inline"]) == "inline"
        assert handler._get_note(["--other"]) is None

    def test_get_reason(self, handler):
        assert handler._get_reason(["--reason", "blocked"]) == "blocked"
        assert handler._get_reason(["--reason=inline"]) == "inline"
        assert handler._get_reason([]) is None

    def test_sanitize_title_balanced_quotes(self, handler):
        assert handler._sanitize_title('"ok"') == '"ok"'

    def test_sanitize_title_unbalanced_quotes(self, handler):
        assert '"' not in handler._sanitize_title('broken"title')

    def test_sanitize_title_whitespace(self, handler):
        assert handler._sanitize_title("  too   many   spaces  ") == "too many spaces"
