"""Legacy session daemons must leave model/slot-bound tasks to their owners."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.daemon import auto_session, session_daemon


@pytest.mark.parametrize("columns", [(), ("required_model",), ("assigned_slot",),
                                     ("required_model", "assigned_slot")])
def test_legacy_daemons_only_see_unbound_tasks(tmp_path, monkeypatch, columns):
    db = tmp_path / "tasks.db"
    with sqlite3.connect(db) as conn:
        extras = "".join(f", {name} TEXT" for name in columns)
        conn.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, category TEXT, title TEXT, "
            f"priority TEXT, status TEXT{extras})"
        )
        rows = [
            (1, "free", None, None),
            (2, "model-bound", "model-x", None),
            (3, "slot-bound", None, "worker-x"),
            (4, "empty-bindings", "", ""),
        ]
        for task_id, title, model, slot in rows:
            fields = {"id": task_id, "category": "INBOX", "title": title,
                      "priority": "P1", "status": "open"}
            if "required_model" in columns:
                fields["required_model"] = model
            if "assigned_slot" in columns:
                fields["assigned_slot"] = slot
            names = ", ".join(fields)
            values = ", ".join("?" for _ in fields)
            conn.execute(f"INSERT INTO tasks ({names}) VALUES ({values})", tuple(fields.values()))

    monkeypatch.setattr(auto_session, "BACH_DB", db)
    monkeypatch.setattr(session_daemon, "BACH_DB", db)
    profile = {"task_source": "tasks"}
    expected = {1, 4}
    if "required_model" not in columns:
        expected.add(2)
    if "assigned_slot" not in columns:
        expected.add(3)
    assert {row[3] for row in auto_session.get_tasks(profile, limit=10)} == expected
    assert auto_session.count_tasks(profile) == len(expected)
    assert session_daemon.count_tasks(profile) == len(expected)
