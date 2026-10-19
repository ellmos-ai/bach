"""The task CLI observes completion policy through a genuinely read-only DB."""
import json
import sqlite3
import sys
import types

import pytest

from hub.task import TaskHandler


@pytest.fixture
def completion_cli(tmp_path):
    db = tmp_path / "task space.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY, status TEXT)")
        conn.execute("INSERT INTO tasks VALUES (42, 'review')")
    handler = TaskHandler.__new__(TaskHandler)
    handler.db_path = db
    return handler, db


def _service(monkeypatch, callback):
    module = types.ModuleType("hub._services.worker_completion_policy")
    module.evaluate_current_result = callback
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_cli_reads_decision_without_write_access_or_acceptance(completion_cli, monkeypatch):
    handler, db = completion_cli
    before = db.read_bytes()
    connections = []
    expected = {
        "schema": "bach.worker-completion-evaluation.v1",
        "availability": "available", "task_id": 42,
        "result_id": 7, "result_revision": "a" * 64,
        "decision": {"state": "awaiting_user_review", "reason": "user_review_required",
                     "completion_allowed": False},
        "evidence": {"summary": "Nutzerabnahme bleibt nötig: äöüß"},
    }

    def observe(conn, task_id):
        assert task_id == 42
        assert not conn.in_transaction
        assert conn.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == "review"
        # A bug in the evaluator cannot mutate through this CLI connection.
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE tasks SET status='done' WHERE id=42")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE unwanted(value TEXT)")
        connections.append(conn)
        return expected

    _service(monkeypatch, observe)
    ok, output = handler.handle("result-policy", ["42", "--json", "--dry-run"])
    assert ok and json.loads(output) == expected
    assert "äöüß" in output
    assert db.read_bytes() == before
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute("SELECT 1")


def test_cli_observation_is_not_a_completion_command(completion_cli, monkeypatch):
    handler, db = completion_cli
    _service(monkeypatch, lambda conn, task_id: {
        "schema": "bach.worker-completion-evaluation.v1",
        "availability": "available", "task_id": task_id,
        "decision": {"state": "completed", "reason": "self_check_and_result_evidence_sufficient",
                     "completion_allowed": True},
    })
    ok, output = handler.handle("result-policy", ["42"])
    assert ok and "completed" in output and "Nur gelesen" in output
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == "review"


@pytest.mark.parametrize("args", [[], ["0"], ["-1"], ["x"], ["42", "--apply"],
                                 ["42", "--json", "--json"], ["42", "--db", "other.db"]])
def test_cli_rejects_mutation_and_invalid_options_before_service_use(completion_cli, monkeypatch, args):
    handler, db = completion_cli
    before = db.read_bytes()

    def must_not_run(*args, **kwargs):
        pytest.fail("Invalid CLI arguments reached the completion service")

    _service(monkeypatch, must_not_run)
    ok, output = handler.handle("result-policy", args)
    assert not ok and "Usage:" in output
    assert db.read_bytes() == before


def test_cli_never_creates_missing_database(completion_cli, monkeypatch):
    handler, _ = completion_cli
    missing = handler.db_path.parent / "not-yet-created.db"
    handler.db_path = missing
    _service(monkeypatch, lambda *args: pytest.fail("Missing DB reached evaluator"))
    ok, output = handler.handle("result-policy", ["42", "--json"])
    assert not ok and not missing.exists()
    assert json.loads(output)["availability"] == "unavailable"
    assert json.loads(output)["reason"] == "completion_read_unavailable"


def test_cli_missing_service_is_unavailable_without_raw_error_details(completion_cli, monkeypatch):
    handler, db = completion_cli
    before = db.read_bytes()
    monkeypatch.setitem(sys.modules, "hub._services.worker_completion_policy", None)
    ok, output = handler.handle("result-policy", ["42", "--json"])
    assert not ok and json.loads(output)["decision"] is None
    assert json.loads(output)["reason"] == "completion_service_unavailable"
    assert str(db.parent) not in output
    assert db.read_bytes() == before
