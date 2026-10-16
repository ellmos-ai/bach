# SPDX-License-Identifier: MIT
"""Behavioral regressions for the targeted historical review reopen."""

import asyncio
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException

from system.tests.test_task_lease_client import _init_db
from gui.device_auth import create_task_result_operator, revoke_device
from hub._services.task_lease import release_lease, task_content_version
from hub._services.task_result_service import _status_revision, ensure_result_schema
from hub.task_audit import apply_task_field_changes


@pytest.fixture
def review_world(tmp_path, monkeypatch):
    from gui import server

    path = tmp_path / "legacy-review.sqlite"
    keeper = sqlite3.connect(path)
    keeper.row_factory = sqlite3.Row
    _init_db(keeper)
    cursor = keeper.execute(
        "INSERT INTO tasks (title,description,status,priority,source,assigned_to,"
        "created_by,category) VALUES (?,?,?,?,?,?,?,?)",
        ("Quellen prüfen", "Prüfe zwei Belege.", "open", "H",
         "manual-review", "researcher", "user", "Forschung"),
    )
    task_id = cursor.lastrowid
    keeper.commit()
    row = dict(keeper.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert apply_task_field_changes(
        keeper, task_id, row, {"status": "review"}, changed_by="historical-operator")
    keeper.commit()
    correction_token = create_task_result_operator(
        "legacy-reopen-operator", connection=keeper, can_request_correction=True)
    accept_only_token = create_task_result_operator(
        "accept-only", connection=keeper, can_request_correction=False)

    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(server, "get_bach_db", connect)
    yield server, keeper, task_id, correction_token, accept_only_token
    keeper.close()


def _request(token):
    return SimpleNamespace(headers={"X-BACH-Result-Operator": token})


def _cas(conn, task_id):
    row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    return {"task_version": task_content_version(row),
            "status_revision": _status_revision(conn, task_id)}


def _post(world, cas, token=None):
    server, _, task_id, correction_token, _ = world
    return asyncio.run(server.reopen_legacy_review_task(
        task_id, server.LegacyReviewReopenRequest(**cas),
        _request(correction_token if token is None else token)))


def _unchanged(conn, task_id, before):
    assert dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()) == before


def test_single_review_reopen_uses_existing_operator_and_preserves_task(review_world):
    server, conn, task_id, token, _ = review_world
    observed = asyncio.run(server.read_task_result(task_id, _request(token)))
    assert observed["status"] == "review" and observed["result"] is None
    before = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    ack = _post(review_world, {key: observed[key] for key in ("task_version", "status_revision")})
    after = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert ack["schema"] == "bach.legacy-review-reopen.v1"
    assert ack["status"] == after["status"] == "pending"
    assert ack["previous_task_version"] == ack["task_version"] == observed["task_version"]
    assert ack["status_revision"] > observed["status_revision"]
    assert {k: v for k, v in after.items() if k not in {"status", "updated_at"}} == {
        k: v for k, v in before.items() if k not in {"status", "updated_at"}}
    event = conn.execute(
        "SELECT action,field_changed,old_value,new_value,changed_by "
        "FROM task_history WHERE id=?", (ack["status_event_id"],)).fetchone()
    assert tuple(event[:4]) == ("status_change", "status", "review", "pending")
    assert event["changed_by"].startswith("operator-device:")
    assert len(tuple(conn.execute(
        "SELECT id FROM task_history WHERE task_id=? AND action='status_change'",
        (task_id,)))) == 2
    with pytest.raises(HTTPException) as replay:
        _post(review_world, {key: observed[key] for key in ("task_version", "status_revision")})
    assert replay.value.status_code == 409


@pytest.mark.parametrize("mode", ["accept_only", "revoked", "missing"])
def test_operator_scope_cannot_be_supplied_by_body_or_revoked_token(review_world, mode):
    _, conn, task_id, token, accept_only = review_world
    before = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    history = conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0]
    if mode == "revoked":
        assert revoke_device("legacy-reopen-operator", connection=conn)
        candidate = token
    else:
        candidate = accept_only if mode == "accept_only" else ""
    with pytest.raises(HTTPException) as denial:
        _post(review_world, _cas(conn, task_id), candidate)
    assert denial.value.status_code == 403
    _unchanged(conn, task_id, before)
    assert conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0] == history


def test_status_aba_and_content_cas_reject_old_readback(review_world):
    _, conn, task_id, _, _ = review_world
    expected = _cas(conn, task_id)
    row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert apply_task_field_changes(conn, task_id, row, {"status": "pending"},
                                    changed_by="other-operator", allow_reopen=True)
    row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert apply_task_field_changes(conn, task_id, row, {"status": "review"},
                                    changed_by="other-operator")
    conn.commit()
    assert _cas(conn, task_id)["task_version"] == expected["task_version"]
    with pytest.raises(HTTPException) as stale:
        _post(review_world, expected)
    assert stale.value.status_code == 409
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    current = _cas(conn, task_id)
    conn.execute("UPDATE tasks SET description='Neuer fachlicher Auftrag' WHERE id=?", (task_id,))
    conn.commit()
    with pytest.raises(HTTPException) as changed:
        _post(review_world, current)
    assert changed.value.status_code == 409


@pytest.mark.parametrize("new_evidence", [
    "claim", "result_row", "release_result_ref", "correction_pointer",
    "correction_ledger", "review_intent", "review_receipt", "inline_result",
    "late_result_ref", "late_result_note",
])
def test_new_claim_result_or_intent_between_read_and_write_denies(
        review_world, new_evidence):
    _, conn, task_id, _, _ = review_world
    expected = _cas(conn, task_id)
    if new_evidence == "claim":
        conn.execute("UPDATE tasks SET claim_id='other-lease',claimed_by='other@HOST' "
                     "WHERE id=?", (task_id,))
    elif new_evidence == "result_row":
        ensure_result_schema(conn)
        conn.execute("INSERT INTO worker_task_results "
                     "(task_id,fence,generation,task_version,result,result_sha256,"
                     "submitted_by,submitted_at) VALUES (?,?,?,?,?,?,?,?)",
                     (task_id, 1, "old", expected["task_version"], "Result", "0"*64,
                      "other@HOST", "2026-10-16T00:00:00"))
    elif new_evidence == "release_result_ref":
        conn.execute("INSERT INTO task_history "
                     "(task_id,action,field_changed,new_value,changed_at) "
                     "VALUES (?,'lease_release','lease',?,?)",
                     (task_id, '{"result_ref":"https://github.com/example/repo/pull/1"}',
                      "2026-10-16T00:00:00"))
    elif new_evidence == "correction_pointer":
        if "result_correction_request_id" not in {
                row[1] for row in conn.execute("PRAGMA table_info(tasks)")}:
            conn.execute("ALTER TABLE tasks ADD COLUMN result_correction_request_id INTEGER")
        conn.execute("UPDATE tasks SET result_correction_request_id=5 WHERE id=?", (task_id,))
    elif new_evidence == "correction_ledger":
        conn.execute("CREATE TABLE task_result_corrections (task_id INTEGER)")
        conn.execute("INSERT INTO task_result_corrections VALUES (?)", (task_id,))
    elif new_evidence == "review_intent":
        conn.execute("CREATE TABLE worker_result_review_intents "
                     "(review_task_id INTEGER,target_task_id INTEGER)")
        conn.execute("INSERT INTO worker_result_review_intents VALUES (?,?)", (99, task_id))
    elif new_evidence == "review_receipt":
        conn.execute("CREATE TABLE worker_result_model_reviews "
                     "(review_task_id INTEGER,target_task_id INTEGER)")
        conn.execute("INSERT INTO worker_result_model_reviews VALUES (?,?)", (99, task_id))
    elif new_evidence in {"late_result_ref", "late_result_note"}:
        # Exercise the canonical release writer with a former holder. It
        # records the evidence but does not change task/status CAS values.
        late = release_lease(
            conn, task_id, lease_id=str(uuid.uuid4()), fence=7,
            task_version=expected["task_version"],
            outcome="review" if new_evidence == "late_result_ref" else "return",
            result_ref="https://github.com/example/repo/pull/1"
            if new_evidence == "late_result_ref" else "",
            note="Später eingereichter Ergebnistext"
            if new_evidence == "late_result_note" else "",
            now=datetime(2026, 10, 16, tzinfo=timezone.utc),
        )
        assert late.http_status == 409 and late.payload["late_result_recorded"] is True
        assert _cas(conn, task_id) == expected
    else:
        if "result" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}:
            conn.execute("ALTER TABLE tasks ADD COLUMN result TEXT")
        conn.execute("UPDATE tasks SET result='Früheres Inline-Ergebnis' WHERE id=?", (task_id,))
    conn.commit()
    before = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    history = conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0]
    with pytest.raises(HTTPException) as conflict:
        _post(review_world, expected)
    assert conflict.value.status_code == 409
    # Even a fresh CAS view must not convert existing evidence into a
    # result-free legacy review. This isolates the evidence guard from the
    # version guard for added nullable task columns.
    with pytest.raises(HTTPException) as still_blocked:
        _post(review_world, _cas(conn, task_id))
    assert still_blocked.value.status_code == 409
    _unchanged(conn, task_id, before)
    assert conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0] == history


def test_audit_writer_error_rolls_back_status_and_history(review_world, monkeypatch):
    from hub._services import legacy_review_reopen as service

    _, conn, task_id, _, _ = review_world
    before = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    history = conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0]
    original = service.apply_task_field_changes

    def fail_after_audit(*args, **kwargs):
        assert original(*args, **kwargs)
        raise RuntimeError("simulierter Fehler nach Auditwriter")

    monkeypatch.setattr(service, "apply_task_field_changes", fail_after_audit)
    with pytest.raises(RuntimeError):
        _post(review_world, _cas(conn, task_id))
    _unchanged(conn, task_id, before)
    assert conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0] == history
