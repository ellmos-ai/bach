"""#2661: resolver tasks go to BACH by default; the owner is a versioned system setting."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub._services import task_resolver_settings as settings
from hub._services.worker_policy_settings import PolicyConflict
from hub.task_audit import apply_task_field_changes
from system.tests.test_task_lease_service import _get, _insert, conn, db_path  # noqa: F401


@pytest.fixture
def config_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL,
        type TEXT DEFAULT 'string', category TEXT, description TEXT, updated_at TEXT,
        dist_type INTEGER DEFAULT 2)""")
    conn.commit()
    return conn


def _block(conn):
    tid = _insert(conn)
    apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "blocked"}, changed_by="cli-task")
    conn.commit()
    return conn.execute("SELECT assigned_to FROM tasks WHERE source=?", (f"resolver:task:{tid}",)).fetchone()[0]


def test_resolver_tasks_go_to_bach_by_default_and_follow_the_setting(config_db, db_path):
    assert _block(config_db) == "BACH"
    current = settings.read_setting(db_path)
    assert (current["assignee"], current["source"]) == ("BACH", "system_default")
    written = settings.write_setting({"configuration_version": current["configuration_version"],
                                      "assignee": "CLAUDE"}, actor="device:test", db_path=db_path)
    assert (written["assignee"], written["source"], written["updated"]) == ("CLAUDE", "user_override", True)
    assert _block(config_db) == "CLAUDE"
    with pytest.raises(PolicyConflict):
        settings.write_setting({"configuration_version": current["configuration_version"],
                                "assignee": "BACH"}, actor="device:test", db_path=db_path)
    for bad in ({"assignee": ""}, {"assignee": "zwei Wörter"}, {"assignee": 7}, {}):
        with pytest.raises(ValueError):
            settings.write_setting({"configuration_version": written["configuration_version"], **bad},
                                   actor="device:test", db_path=db_path)


def test_missing_or_unreadable_setting_means_bach(config_db):
    assert settings.stored_assignee(sqlite3.connect(":memory:")) == "BACH"  # no system_config table
    assert settings.stored_assignee(config_db) == "BACH"  # no key
    config_db.execute("INSERT INTO system_config(key,value) VALUES (?,?)", (settings.KEY, "{broken"))
    assert settings.stored_assignee(config_db) == "BACH"
    config_db.execute("UPDATE system_config SET value=? WHERE key=?",
                      (json.dumps({"revision": 1, "values": {"assignee": "OLLAMA"}}), settings.KEY))
    assert settings.stored_assignee(config_db) == "OLLAMA"

