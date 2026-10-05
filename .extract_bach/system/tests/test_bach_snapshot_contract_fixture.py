"""Optional, isolated behavior probe for the fixed BACH snapshot source.

This is deliberately not an Ocean adapter test.  It imports the explicitly
provided BACH source against an anonymized temporary SQLite database, never
starts the BACH CLI, and asserts the source semantics recorded by the K9
contract.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPECTED_BACH_COMMIT = "8392ed8cecd9ac598d1b3b711b8e3df1b7c1dc4d"


def _snapshot_handler(bach_root: Path, base_path: Path):
    for name in tuple(sys.modules):
        if name == "system" or name.startswith("system."):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(bach_root))
    try:
        module = importlib.import_module("system.hub.snapshot")
        module_path = Path(module.__file__).resolve()
        if not module_path.is_relative_to(bach_root.resolve()):
            raise AssertionError(f"snapshot import escaped requested BACH root: {module_path}")
        return module.SnapshotHandler(base_path), module_path
    finally:
        sys.path.pop(0)


class BachSnapshotContractFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("BACH_SNAPSHOT_ROOT")
        if not root:
            if os.environ.get("REQUIRE_BACH_SNAPSHOT_FIXTURE") == "1":
                raise AssertionError("BACH_SNAPSHOT_ROOT is required for the requested 8392 fixture")
            raise unittest.SkipTest("set BACH_SNAPSHOT_ROOT to run the isolated BACH fixture")
        cls.bach_root = Path(root).resolve()
        actual = subprocess.run(
            ["git", "-C", str(cls.bach_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual != EXPECTED_BACH_COMMIT:
            raise AssertionError(f"expected BACH {EXPECTED_BACH_COMMIT}, got {actual}")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "synthetic-bach"
        db_path = self.base / "data" / "bach.db"
        db_path.parent.mkdir(parents=True)
        self._create_database(db_path)
        self.db_path = db_path
        self.handler, self.handler_module_path = _snapshot_handler(self.bach_root, self.base)
        self.assertTrue(self.handler_module_path.is_relative_to(self.bach_root))
        self.assertEqual(self.db_path.resolve(), self.handler.db_path.resolve())

    def tearDown(self):
        self.temp.cleanup()
        for name in tuple(sys.modules):
            if name == "system" or name.startswith("system."):
                sys.modules.pop(name, None)

    def _create_database(self, path: Path) -> None:
        snapshot_data = {
            "session_id": "source-session",
            "open_tasks": [{"id": 999, "title": "payload fallback must not win"}],
            "recent_memory": ["payload fallback must not win"],
            "active_files": ["synthetic/active.txt"],
            "token_usage": 4242,
            "created_at": "2026-09-21T09:00:00",
        }
        separate_tasks = [
            {"id": 101, "title": "reactivate closed synthetic task"},
            {"id": 102, "title": "create missing synthetic task"},
            {"id": 103, "title": "retain active synthetic task"},
        ]
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE session_snapshots (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT,
                    name TEXT,
                    snapshot_data TEXT,
                    working_memory TEXT,
                    open_tasks TEXT,
                    created_at TEXT
                );
                CREATE TABLE memory_working (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT,
                    content TEXT,
                    priority INTEGER,
                    is_active INTEGER,
                    created_by_session_id TEXT,
                    created_at TEXT
                );
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    status TEXT,
                    priority TEXT,
                    source TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO system_config VALUES (?, ?)", ("current_session", "active-now")
            )
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (101, "reactivate closed synthetic task", "done", "P3", "synthetic", "old", "old"),
            )
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (103, "retain active synthetic task", "in_progress", "P3", "synthetic", "old", "old"),
            )
            connection.execute(
                "INSERT INTO memory_working (type, content, priority, is_active, created_by_session_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("note", "already active synthetic note", 3, 1, "active-now", "old"),
            )
            connection.execute(
                "INSERT INTO session_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    1,
                    "source-session",
                    "synthetic-checkpoint",
                    json.dumps(snapshot_data),
                    json.dumps(["restored only from separate column"]),
                    json.dumps(separate_tasks),
                    "2026-09-21T09:00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _state(self):
        connection = sqlite3.connect(self.db_path)
        try:
            return {
                "session": connection.execute(
                    "SELECT value FROM system_config WHERE key = 'current_session'"
                ).fetchone()[0],
                "tasks": connection.execute(
                    "SELECT title, status, source FROM tasks ORDER BY id"
                ).fetchall(),
                "memory": connection.execute(
                    "SELECT content, is_active FROM memory_working ORDER BY id"
                ).fetchall(),
            }
        finally:
            connection.close()

    def test_display_is_a_load_argument_and_never_mutates(self):
        before = self._state()

        ok, output = self.handler.handle("load", ["1", "display"])

        self.assertTrue(ok)
        self.assertIn("Display-Modus", output)
        self.assertEqual(before, self._state())
        self.assertTrue(self.handler.handle("display", [])[1].startswith("[SNAPSHOTS]"))

    def test_default_load_uses_separate_columns_and_restores_only_documented_state(self):
        ok, output = self.handler.handle("load", ["1"])

        self.assertTrue(ok)
        self.assertIn("RESTORIERT", output)
        state = self._state()
        self.assertEqual("active-now", state["session"])
        self.assertIn(("reactivate closed synthetic task", "pending", "synthetic"), state["tasks"])
        self.assertIn(("retain active synthetic task", "in_progress", "synthetic"), state["tasks"])
        self.assertIn(("create missing synthetic task", "pending", "snapshot-restore"), state["tasks"])
        self.assertIn(("restored only from separate column", 1), state["memory"])
        self.assertNotIn(("payload fallback must not win", 1), state["memory"])


if __name__ == "__main__":
    unittest.main()
