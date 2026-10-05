# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer exec_tool("task_manage", ..., action="done") in chat_runtime.py.

T-20260906-833218904 (Folgefund aus T-20260906-985973908/PR #21, gemeldet beim Merge-
Review von PR #21): chat_runtime.py setzte Task-Status direkt per SQL, ohne
task_history-Zeile. Nutzt jetzt wie server.py/headless.py/task.py
hub.task_audit.apply_task_field_changes.
"""

import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat import chat_runtime
from hub._services.chat.chat_runtime import exec_tool


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "bach.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            category TEXT,
            depends_on TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            assigned_to TEXT DEFAULT 'bach',
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        INSERT INTO tasks (title, status, priority) VALUES ('Test task', 'pending', 'P2');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(chat_runtime, "RUNTIME_BACH_DB", str(p))
    return p


def _history_rows(db_path, task_id=1):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _task_row(db_path, task_id=1):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


class TestTaskManageDone:
    def test_done_sets_completed_at_and_returns_confirmation(self, db_path):
        result = exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")
        assert result == "Task #1 erledigt."
        row = _task_row(db_path)
        assert row["status"] == "done"
        assert row["completed_at"] not in (None, "")
        assert row["updated_at"] not in (None, "")

    def test_done_writes_history_row_with_default_changed_by(self, db_path):
        exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")
        rows = _history_rows(db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "status_change"
        assert row["field_changed"] == "status"
        assert row["old_value"] == "pending"
        assert row["new_value"] == "done"
        assert row["changed_by"] == "chat-runtime"

    def test_done_missing_task_returns_not_found(self, db_path):
        result = exec_tool("task_manage", {"action": "done", "task_id": 999}, mode="safe")
        assert result == "Task #999 nicht gefunden"
        assert _history_rows(db_path, task_id=999) == []

    def test_done_missing_task_id_returns_hint(self, db_path):
        result = exec_tool("task_manage", {"action": "done"}, mode="safe")
        assert result == "Keine Task-ID angegeben"

    @pytest.mark.parametrize("status", ["done", "completed"])
    def test_done_on_already_completed_task_does_not_emit_new_success_receipt(
        self, db_path, status
    ):
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE tasks SET status = ?, completed_at = '2026-01-01 00:00:00' WHERE id = 1",
            (status,),
        )
        conn.commit()
        conn.close()

        result = exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")

        assert result == "Task #1 war bereits erledigt."
        row = _task_row(db_path)
        assert row["status"] == status
        assert row["completed_at"] == "2026-01-01 00:00:00"
        assert _history_rows(db_path) == []

    def test_done_is_atomic_for_parallel_workers(self, db_path, monkeypatch):
        start = threading.Barrier(3)
        audit_lock = threading.Lock()
        audit_calls = 0
        apply_changes = chat_runtime.apply_task_field_changes

        def delayed_apply_changes(*args, **kwargs):
            nonlocal audit_calls
            with audit_lock:
                audit_calls += 1
            time.sleep(0.1)
            return apply_changes(*args, **kwargs)

        monkeypatch.setattr(chat_runtime, "apply_task_field_changes", delayed_apply_changes)

        def complete_task():
            start.wait(timeout=5)
            return exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(complete_task)
            second = pool.submit(complete_task)
            start.wait(timeout=5)
            results = [first.result(timeout=10), second.result(timeout=10)]

        assert results.count("Task #1 erledigt.") == 1
        assert results.count("Task #1 war bereits erledigt.") == 1
        assert audit_calls == 1
        assert _task_row(db_path)["status"] == "done"
        assert len(_history_rows(db_path)) == 1

    def test_done_fallback_without_task_audit(self, db_path, monkeypatch):
        """Wenn hub.task_audit nicht importierbar ist (identischer sys.path-Vorbehalt
        wie RUNTIME_BACH_DB), soll die Aktion trotzdem funktionieren -- nur ohne
        Audit-Trail, statt hart zu brechen."""
        monkeypatch.setattr(chat_runtime, "apply_task_field_changes", None)
        result = exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")
        assert result == "Task #1 erledigt."
        row = _task_row(db_path)
        assert row["status"] == "done"
        assert row["completed_at"] not in (None, "")
        assert _history_rows(db_path) == []  # kein Fallback-Audit-Trail, aber kein Crash


class TestTaskManageUpdate:
    def test_update_fields(self, db_path):
        result = exec_tool(
            "task_manage",
            {"action": "update", "task_id": 1, "description": "Neuer Umfang", "priority": "P1"},
            mode="safe",
        )
        assert "aktualisiert" in result
        row = _task_row(db_path, task_id=1)
        assert row["priority"] == "P1"


class TestTaskManageDecompose:
    @pytest.mark.parametrize("subtasks", [
        [], [{}], [{"title": "   "}], ["kein Objekt"], {"title": "keine Liste"},
        [{"title": "Gültiger Schritt"}, {"title": ""}],
        [{"title": "Schritt", "description": ["ungültig"]}],
    ])
    def test_invalid_subtasks_preserve_parent_and_create_nothing(self, db_path, subtasks):
        before = _task_row(db_path)
        result = exec_tool("task_manage", {
            "action": "decompose", "task_id": 1, "subtasks": subtasks,
        }, mode="safe")

        assert "Teilaufgaben zerlegt" not in result
        assert _task_row(db_path) == before
        assert _history_rows(db_path) == []
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    @pytest.mark.parametrize("already_closed", ["done", "completed", "cancelled"])
    def test_closed_parent_cannot_be_decomposed_again(self, db_path, already_closed):
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE tasks SET status=? WHERE id=1", (already_closed,))
        result = exec_tool("task_manage", {
            "action": "decompose", "task_id": 1, "subtasks": [{"title": "Schritt"}],
        }, mode="safe")

        assert "Teilaufgaben zerlegt" not in result
        assert _task_row(db_path)["status"] == already_closed
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    def test_parallel_decomposition_closes_parent_and_creates_subtasks_once(self, db_path, monkeypatch):
        start = threading.Barrier(3)
        apply_changes = chat_runtime.apply_task_field_changes

        def delayed_apply(*args, **kwargs):
            time.sleep(0.1)
            return apply_changes(*args, **kwargs)

        monkeypatch.setattr(chat_runtime, "apply_task_field_changes", delayed_apply)

        def decompose():
            start.wait(timeout=5)
            return exec_tool("task_manage", {
                "action": "decompose", "task_id": 1,
                "subtasks": [{"title": "Analyse"}, {"title": "Umsetzung"}],
                "sequential": True,
            }, mode="safe")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(decompose) for _ in range(2)]
            start.wait(timeout=5)
            results = [f.result(timeout=10) for f in futures]

        assert sum("in 2 Teilaufgaben zerlegt" in r for r in results) == 1
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3
            assert conn.execute("SELECT depends_on FROM tasks WHERE id=3").fetchone()[0] == "2"
        assert _task_row(db_path)["status"] == "completed"
        assert len([r for r in _history_rows(db_path) if r["field_changed"] == "status"]) == 1

    @pytest.mark.parametrize("close_parent", [False, True])
    def test_real_decomposition_receipt_requires_closed_parent_and_is_consumed_once(self, db_path, close_parent):
        runtime = chat_runtime.ChatRuntime(object())
        chat_id = "worker-decompose-test"
        args = {"action": "decompose", "task_id": 1,
                "subtasks": [{"title": "Schritt"}], "close_parent": close_parent}
        result = exec_tool("task_manage", args, mode="safe")
        token = runtime._compute_turn_context.set((chat_id, "background"))
        try:
            assert runtime._record_task_completion_receipt(chat_id, "task_manage", args, result) is close_parent
            assert runtime._record_task_completion_receipt(chat_id, "task_manage", args, result) is False
            expected = (1,) if close_parent else ()
            assert runtime.consume_task_completion_receipts(chat_id) == expected
            assert runtime.consume_task_completion_receipts(chat_id) == ()
        finally:
            runtime._compute_turn_context.reset(token)
        assert _task_row(db_path)["status"] == ("completed" if close_parent else "pending")
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2

    def test_decompose_into_subtasks(self, db_path):
        subtasks = [
            {"title": "Teilschritt 1: Analyse", "description": "Lies Datei X"},
            {"title": "Teilschritt 2: Edit", "description": "Patsche Zeile Y"},
        ]
        result = exec_tool(
            "task_manage",
            {"action": "decompose", "task_id": 1, "subtasks": subtasks, "sequential": True},
            mode="safe",
        )
        assert "in 2 Teilaufgaben zerlegt" in result
        parent = _task_row(db_path, task_id=1)
        assert parent["status"] == "completed"

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tasks WHERE id > 1 ORDER BY id").fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0]["title"] == "Teilschritt 1: Analyse"
        assert rows[1]["title"] == "Teilschritt 2: Edit"
        assert rows[1]["depends_on"] == str(rows[0]["id"])

    def test_decompose_fallback_preserves_note_and_completion_time(self, db_path, monkeypatch):
        monkeypatch.setattr(chat_runtime, "apply_task_field_changes", None)
        result = exec_tool("task_manage", {
            "action": "decompose", "task_id": 1, "subtasks": [{"title": "Schritt"}],
        }, mode="safe")
        assert "in 1 Teilaufgaben zerlegt" in result
        parent = _task_row(db_path)
        assert parent["status"] == "completed"
        assert parent["completed_at"]
        assert "Teilaufgaben zerlegt: [2]" in parent["description"]

    def test_background_process_receives_real_decomposition_completion(self, db_path):
        import asyncio

        args = {"action": "decompose", "task_id": 1,
                "subtasks": [{"title": "Prüfung", "description": "Konkreter nächster Schritt"}]}

        class Backend:
            calls = 0

            def get_default_model(self):
                return "test-model"

            async def chat(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    tc = [{"function": {"name": "task_manage", "arguments": args}}]
                    return {"content": "", "tool_calls": tc,
                            "raw_message": {"role": "assistant", "content": "", "tool_calls": tc}}
                return {"content": "FERTIG", "tool_calls": None}

            def tool_response_message(self, content, tool_call_id=""):
                return {"role": "tool", "content": content}

        runtime = chat_runtime.ChatRuntime(Backend())
        runtime.max_tool_rounds = 3
        runtime.hook_every = 999
        answer = asyncio.run(runtime.process("Task #1 bearbeiten", "worker-real-decompose"))
        assert answer == "FERTIG"
        assert runtime.consume_task_completion_receipts("worker-real-decompose") == (1,)
        assert _task_row(db_path)["status"] == "completed"
        assert _task_row(db_path, 2)["title"] == "Prüfung"


class TestTaskManageAdd:
    def test_add_defaults_assigned_to_bach(self, db_path):
        result = exec_tool("task_manage", {"action": "add", "title": "Neuer Test", "category": "Test"}, mode="safe")
        assert "erstellt" in result
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE title = 'Neuer Test'").fetchone()
        conn.close()
        assert row is not None
        assert row["assigned_to"] == "bach"
