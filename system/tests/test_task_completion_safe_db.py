"""The public generic DB facade cannot bypass the canonical task state writers."""
import sqlite3

import pytest

from core.safe_db import SafeDB, SafeDBError
from hub._services.task_lease_client import TaskLeaseClient
from hub._services.task_result_service import read_result
from system.tests.test_task_lease_client import _init_db, _insert_task


@pytest.fixture
def managed_database(tmp_path):
    path = tmp_path / "authority.db"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        _init_db(conn)
        task_id = _insert_task(conn, "Current managed result")
        client = TaskLeaseClient(conn=conn)
        current = client.task_snapshot(task_id)
        lease = client.acquire(task_id, worker_id="safe-db-test@HOST", host="HOST",
            task_version=current["task_version"], result_generation="safe-db-generation")
        client.submit_result(task_id, lease_id=lease.lease_id, fence=lease.fence,
            task_version=lease.task_version, generation="safe-db-generation",
            result="Submitted evidence remains subject to completion policy.")
        observed = read_result(conn, task_id)
        assert observed["status"] == "review"
        assert observed["result"]["completion_policy_version"] == 1
        assert observed["result"]["submission"]["availability"] == "available"
    return path, task_id


@pytest.mark.parametrize("table", ["tasks", "TASKS", "Tasks"])
@pytest.mark.parametrize("status", ["done", "completed", " DONE "])
def test_generic_update_cannot_finish_an_actual_v1_submission(managed_database, table, status):
    path, task_id = managed_database
    before = path.read_bytes()
    with pytest.raises(SafeDBError, match="Task-API"):
        SafeDB(path).update(table, {"status": status}, {"id": task_id})
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        current = read_result(conn, task_id)
        assert current["status"] == "review"
        assert current["result"]["accepted"] is False
        assert conn.execute("SELECT COUNT(*) FROM task_history WHERE action='result_acceptance'").fetchone()[0] == 0


@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.parametrize("field", ["require_user_review", "github_pr_review_required",
    "completion_contract_json", "github_review_contract_json"])
def test_generic_task_rules_are_rejected_before_any_database_access(tmp_path, operation, field):
    path = tmp_path / "must-not-be-created.db"
    db = SafeDB(path)
    with pytest.raises(SafeDBError, match="Task-API"):
        if operation == "insert":
            db.insert("Tasks", {"title": "Bypass", field: None})
        else:
            db.update("Tasks", {field: None}, {"id": 1})
    assert not path.exists()


@pytest.mark.parametrize("status", ["done", "completed", " DONE "])
def test_generic_insert_cannot_create_a_terminal_task(tmp_path, status):
    path = tmp_path / "must-not-be-created.db"
    with pytest.raises(SafeDBError, match="Task-API"):
        SafeDB(path).insert("TASKS", {"title": "Bypass", "status": status})
    assert not path.exists()


def test_generic_non_state_task_writes_and_other_tables_keep_working(tmp_path):
    path = tmp_path / "ordinary.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE tasks(id INTEGER PRIMARY KEY,title TEXT,status TEXT DEFAULT 'open');"
            "CREATE TABLE memory_note(id INTEGER PRIMARY KEY,status TEXT);")
    db = SafeDB(path)
    db._fire_hook = lambda *args: None  # The fixture has no native hook consumers.
    task_id = db.insert("tasks", {"title": "Original", "status": "pending"})
    assert db.update("tasks", {"title": "Überarbeitet"}, {"id": task_id}) == 1
    note_id = db.insert("memory_note", {"status": "open"})
    assert db.update("memory_note", {"status": "done"}, {"id": note_id}) == 1
    assert db.select("tasks", where={"id": task_id})[0]["title"] == "Überarbeitet"
    assert db.select("memory_note", where={"id": note_id})[0]["status"] == "done"
