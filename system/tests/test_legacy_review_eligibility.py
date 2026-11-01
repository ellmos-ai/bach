"""Private SQLite fixtures for the existing legacy-review reopen predicates."""
import ast
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from system.tests.test_task_lease_client import _init_db, _insert_task
from gui.device_auth import create_task_result_operator
from hub._services import legacy_review_reopen as owner
from hub._services.task_lease_client import TaskLeaseClient, LeaseProtocolError
from hub._services.task_result_service import ResultConflict, ResultPermissionDenied


@pytest.fixture
def world():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    for name in ["result", "result_correction_request_id"]:
        if name not in columns:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} TEXT")
    for table, fields in [
        ("worker_task_results", "task_id INTEGER"),
        ("task_result_corrections", "task_id INTEGER"),
        ("worker_result_review_intents", "review_task_id INTEGER,target_task_id INTEGER"),
        ("worker_result_model_reviews", "review_task_id INTEGER,target_task_id INTEGER"),
    ]:
        conn.execute(f"CREATE TABLE {table} ({fields})")
    token = create_task_result_operator("private-eligibility-reviewer", connection=conn,
                                        can_request_correction=True)
    task_id = _insert_task(conn, title="Private Eligibility", status="review")
    yield conn, task_id, token
    conn.close()


def read(world):
    conn, task_id, token = world
    return owner.legacy_review_reopen_eligibility(conn, task_id, operator_token=token)


def reopen(world, snapshot):
    conn, task_id, token = world
    return owner.reopen_legacy_review(conn, task_id, task_version=snapshot["task_version"],
                                     status_revision=snapshot["status_revision"], operator_token=token)


def test_actual_empty_case_readonly_and_existing_reopen(world):
    conn, task_id, token = world
    before = conn.total_changes
    snapshot = TaskLeaseClient(conn=conn).legacy_review_reopen_eligibility(task_id, operator_token=token)
    assert snapshot["eligible"] is True and snapshot["write_rechecks_required"] is True
    assert conn.total_changes == before and conn.in_transaction is False
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    ack = reopen(world, snapshot)
    assert ack["status"] == "pending" and ack["status_revision"] > snapshot["status_revision"]


def test_hidden_intent_2520_class_without_exposing_contents(world):
    conn, task_id, token = world
    conn.execute("INSERT INTO worker_result_review_intents VALUES (?,?)", (999, task_id))
    conn.commit()
    snapshot = read(world)
    assert snapshot["eligible"] is False and snapshot["result_intent_history_blocker"] == "review_intent"
    assert "999" not in json.dumps(snapshot)
    with pytest.raises(ResultConflict):
        reopen(world, snapshot)
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"


@pytest.mark.parametrize("sql,params,reason", [
    ("UPDATE tasks SET result='existing' WHERE id=?", None, "inline_result"),
    ("UPDATE tasks SET result_correction_request_id='prior' WHERE id=?", None, "correction_request_reference"),
    ("UPDATE tasks SET source='worker-result-review:v1:private' WHERE id=?", None, "review_task_source"),
    ("INSERT INTO worker_task_results VALUES (?)", None, "worker_result"),
    ("INSERT INTO task_result_corrections VALUES (?)", None, "result_correction"),
    ("INSERT INTO worker_result_model_reviews VALUES (?,?)", "pair", "model_review"),
    ("INSERT INTO task_history(task_id,action,new_value,changed_at) VALUES (?,'lease_release','bad-json','fixture')", None, "malformed_release_audit"),
    ("INSERT INTO task_history(task_id,action,new_value,changed_at) VALUES (?,'lease_release','[]','fixture')", None, "malformed_release_audit"),
    ("INSERT INTO task_history(task_id,action,new_value,changed_at) VALUES (?,'lease_release','{\"note\":\"prior\"}','fixture')", None, "release_result_or_note"),
    ("INSERT INTO task_history(task_id,action,new_value,changed_at) VALUES (?,'result_previous','{}','fixture')", None, "result_history"),
])
def test_same_guard_matches_native_preimage_and_denies(world, sql, params, reason):
    conn, task_id, token = world
    conn.execute(sql, (task_id, task_id) if params == "pair" else (task_id,))
    conn.commit()
    task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert owner._no_result_or_intent(conn, task_id, task) is False
    snapshot = read(world)
    assert snapshot["eligible"] is False and snapshot["result_intent_history_blocker"] == reason


def test_lease_claim_denies_even_with_no_result(world):
    conn, task_id, token = world
    conn.execute("UPDATE tasks SET claimed_by='private-worker' WHERE id=?", (task_id,))
    conn.commit()
    snapshot = read(world)
    assert snapshot["checks"]["lease_claim_free"] is False and snapshot["eligible"] is False
    with pytest.raises(ResultConflict):
        reopen(world, snapshot)


def test_version_race_denies_without_status_write(world):
    conn, task_id, token = world
    snapshot = read(world)
    conn.execute("UPDATE tasks SET title='Changed after read' WHERE id=?", (task_id,))
    conn.commit()
    with pytest.raises(ResultConflict):
        reopen(world, snapshot)
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"


def test_intent_race_is_rechecked_by_existing_writer(world):
    conn, task_id, token = world
    snapshot = read(world)
    conn.execute("INSERT INTO worker_result_review_intents VALUES (?,?)", (task_id, 999))
    conn.commit()
    with pytest.raises(ResultConflict):
        reopen(world, snapshot)


def test_revoked_or_wrong_operator_denied_without_writes(world):
    conn, task_id, token = world
    before = conn.total_changes
    with pytest.raises(ResultPermissionDenied):
        owner.legacy_review_reopen_eligibility(conn, task_id, operator_token="private-invalid")
    assert conn.total_changes == before
    conn.execute("UPDATE task_result_operators SET can_request_correction=0")
    conn.commit()
    before = conn.total_changes
    with pytest.raises(ResultPermissionDenied):
        read(world)
    assert conn.total_changes == before


def test_malformed_store_never_reports_eligible(world):
    conn, task_id, token = world
    conn.execute("DROP TABLE task_history")
    conn.commit()
    with pytest.raises(ResultConflict):
        read(world)


def test_existing_transaction_not_committed_or_rolled_back(world):
    conn, task_id, token = world
    conn.execute("BEGIN")
    with pytest.raises(ResultConflict):
        read(world)
    assert conn.in_transaction is True
    conn.rollback()


@pytest.mark.parametrize("authorized,task_id_value,expected_status", [
    (True, "actual", 200), (False, "actual", 403), (True, 0, 422),
])
def test_endpoint_exact_handler_auth_readonly(world, authorized, task_id_value, expected_status):
    """Actual route body and actual owner; DB factory seam only, no GUI lifespan."""
    import asyncio
    from fastapi import Request, HTTPException

    conn, task_id, token = world
    source_path = Path(__file__).resolve().parents[1] / "gui/server.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == "legacy_review_reopen_eligibility_read")
    assert len(handler.decorator_list) == 1
    assert ast.literal_eval(handler.decorator_list[0].args[0]) == "/api/tasks/{task_id}/legacy-review/eligibility"
    handler.decorator_list = []
    dump = "\n".join(conn.iterdump())
    statements, opened = [], []

    def private_connection():
        private = sqlite3.connect(":memory:")
        private.row_factory = sqlite3.Row
        private.executescript(dump)
        private.set_trace_callback(lambda statement: statements.append(statement.split()[0].upper()))
        opened.append(private)
        return private

    namespace = {"Request": Request, "HTTPException": HTTPException,
                 "get_bach_db": private_connection}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source_path), "exec"), namespace)
    headers = [(b"x-bach-result-operator", token.encode())] if authorized else []
    request = Request({"type": "http", "headers": headers})
    action = namespace[handler.name](task_id if task_id_value == "actual" else task_id_value, request)
    if expected_status == 200:
        result = asyncio.run(action)
        assert result["eligible"] is True and result["task_id"] == task_id
    else:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(action)
        assert caught.value.status_code == expected_status
    assert set(statements) <= {"SELECT", "PRAGMA", "BEGIN", "ROLLBACK"}
    assert opened
    for private in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            private.execute("SELECT 1")


@pytest.mark.parametrize("tamper", [None, "boolean_revision", "missing_check", "missing_blocker", "unknown_blocker", "false_eligible", "dict_blocker", "list_blocker"])
def test_remote_client_read_contract_without_network(world, tamper):
    conn, task_id, token = world
    response = read(world)
    if tamper == "boolean_revision":
        response["lease_fence"] = False
    elif tamper == "missing_check":
        response["checks"].pop("lease_claim_free")
    elif tamper == "missing_blocker":
        response.pop("result_intent_history_blocker")
    elif tamper == "unknown_blocker":
        response.update(eligible=False, result_intent_history_blocker="future-unknown")
        response["checks"]["result_intent_history_clear"] = False
    elif tamper in {"dict_blocker", "list_blocker"}:
        response.update(eligible=False, result_intent_history_blocker={} if tamper == "dict_blocker" else [])
        response["checks"]["result_intent_history_clear"] = False
    elif tamper == "false_eligible":
        response["eligible"] = False
    client = TaskLeaseClient.__new__(TaskLeaseClient)
    client._mode = "remote"
    calls = []

    def transport(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return 200, copy.deepcopy(response)

    client._http_request = transport
    if tamper is None:
        assert client.legacy_review_reopen_eligibility(task_id, operator_token=token)["eligible"] is True
    else:
        with pytest.raises(LeaseProtocolError):
            client.legacy_review_reopen_eligibility(task_id, operator_token=token)
    assert calls == [("GET", f"/api/tasks/{task_id}/legacy-review/eligibility",
                      {"headers": {"X-BACH-Result-Operator": token}})]
