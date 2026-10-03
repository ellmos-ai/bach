# -*- coding: utf-8 -*-
"""GUI Task completion contract tests against an isolated SQLite database."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI TestClient not installed")
class TaskCompletionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-completion-")
        self.root = Path(self.temp.name)
        self.db_path = self.root / "data" / "bach.db"
        self.db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT DEFAULT 'P3',
                status TEXT DEFAULT 'open',
                category TEXT,
                project TEXT,
                assigned_to TEXT,
                created_by TEXT,
                depends_on TEXT,
                started_at TEXT,
                completed_at TEXT,
                due_date TEXT,
                claimed_by TEXT,
                claimed_at TEXT,
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
            """
        )
        conn.commit()
        conn.close()

        import gui.server as srv
        import hub.worker_git as worker_git

        self.srv = srv
        self.worker_git = worker_git
        self.original_server_values = {
            name: getattr(srv, name)
            for name in (
                "BACH_DB", "USER_DB", "DATA_DIR", "BACH_DIR", "GUI_DIR",
                "has_active_devices", "validate_token",
            )
        }
        self.original_worktrees_dir = worker_git.get_worktrees_dir

        srv.BACH_DB = self.db_path
        srv.USER_DB = self.db_path
        srv.DATA_DIR = self.db_path.parent
        srv.BACH_DIR = self.root
        srv.GUI_DIR = self.root / "gui"
        srv.has_active_devices = lambda: True
        srv.validate_token = lambda token: {"device_id": "fixture"}

        # Prevent the completion guard from consulting any developer worktree.
        worker_git.get_worktrees_dir = lambda: self.root / "worktrees"
        self.client = TestClient(srv.app, raise_server_exceptions=False,
                                 headers={"Authorization": "Bearer task-fixture"})

    def tearDown(self):
        try:
            self.client.close()
        except Exception:
            pass
        for name, value in self.original_server_values.items():
            setattr(self.srv, name, value)
        self.worker_git.get_worktrees_dir = self.original_worktrees_dir
        self.temp.cleanup()

    def insert_task(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "INSERT INTO tasks (title, status) VALUES (?, 'open')",
            ("Disposable completion fixture",),
        )
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def read_task_and_history(self, task_id):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        history = conn.execute(
            "SELECT action, field_changed, old_value, new_value, changed_by "
            "FROM task_history WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
        conn.close()
        return dict(row) if row else None, [dict(item) for item in history]

    def test_completion_sets_status_timestamp_and_single_audit_entry(self):
        task_id = self.insert_task()

        response = self.client.put(
            "/api/tasks/" + str(task_id),
            json={"status": "completed", "changed_by": "gui"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "updated"})
        completed, history = self.read_task_and_history(task_id)
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["completed_at"])
        self.assertEqual(len(history), 1)
        self.assertEqual(
            history[0],
            {
                "action": "status_change",
                "field_changed": "status",
                "old_value": "open",
                "new_value": "completed",
                "changed_by": "gui",
            },
        )

        first_completed_at = completed["completed_at"]
        repeated = self.client.put(
            "/api/tasks/" + str(task_id),
            json={"status": "completed", "changed_by": "gui"},
        )

        self.assertEqual(repeated.status_code, 200, repeated.text)
        completed_again, history_again = self.read_task_and_history(task_id)
        self.assertEqual(completed_again["completed_at"], first_completed_at)
        self.assertEqual(history_again, history)

    def test_completion_returns_404_for_missing_task(self):
        response = self.client.put(
            "/api/tasks/987654321",
            json={"status": "completed", "changed_by": "gui"},
        )
        self.assertEqual(response.status_code, 404)

    def test_completion_preserves_invalid_token_rejection(self):
        task_id = self.insert_task()
        self.srv.validate_token = lambda token: None

        response = self.client.put(
            "/api/tasks/" + str(task_id),
            json={"status": "completed", "changed_by": "gui"},
            headers={"Authorization": "Bearer invalid-fixture-token"},
        )

        self.assertEqual(response.status_code, 401)
        task, history = self.read_task_and_history(task_id)
        self.assertEqual(task["status"], "open")
        self.assertEqual(history, [])

    def test_missing_pr_guard_returns_conflict_without_mutation(self):
        task_id = self.insert_task()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            INSERT INTO task_history
                (task_id, action, field_changed, old_value, new_value,
                 changed_by, changed_at)
            VALUES (?, 'file_modified', 'file', '', 'fixture.py',
                    'worker', '2026-10-03T12:00:00')
            """,
            (task_id,),
        )
        conn.commit()
        conn.close()

        response = self.client.put(
            "/api/tasks/" + str(task_id),
            json={"status": "completed", "changed_by": "gui"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        task, history = self.read_task_and_history(task_id)
        self.assertEqual(task["status"], "open")
        self.assertIsNone(task["completed_at"])
        self.assertEqual([item["action"] for item in history], ["file_modified"])


if __name__ == "__main__":
    unittest.main()
