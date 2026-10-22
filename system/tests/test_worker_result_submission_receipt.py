"""Behavioral receipt tests for BACH worker result submission.

These tests exercise local temporary SQLite state only. They verify the
submission/release/read/explicit-operator boundary; they do not claim that a
receipt validates project scope, worktree state, reviewer identity, user review,
or GitHub evidence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from hub._services.task_lease import LeaseConfig, ensure_task_lease_schema
from hub._services.task_lease_client import LeaseExpiredError, TaskLeaseClient
from hub._services.task_result_service import (
    ResultConflict,
    accept_result,
    ensure_result_schema,
    read_result,
    request_result_correction,
)

GENERATION = "receipt-generation-1"
RESULT_TEXT = "Ergebnis mit überprüfbaren Belegen und klaren Grenzen."


def _open_db(path, *, with_system_config=True):
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'M',
            category TEXT,
            assigned_to TEXT,
            created_by TEXT,
            depends_on TEXT,
            estimated_minutes INTEGER,
            actual_minutes INTEGER,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT,
            due_date TEXT,
            source TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT,
            changed_at TEXT NOT NULL
        );
    """)
    if with_system_config:
        conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    ensure_task_lease_schema(conn)
    conn.commit()
    return conn


@pytest.fixture
def local_db(tmp_path):
    path = tmp_path / "worker-results.sqlite"
    conn = _open_db(path)
    yield conn, path
    conn.close()


@pytest.fixture
def no_policy_store_db(tmp_path):
    path = tmp_path / "worker-results-no-policy-store.sqlite"
    conn = _open_db(path, with_system_config=False)
    yield conn, path
    conn.close()


def _insert_task(conn, title="Receipt test"):
    cursor = conn.execute(
        "INSERT INTO tasks(title,description,status,priority) VALUES (?,?,?,?)",
        (title, "isolated fixture", "open", "M"),
    )
    conn.commit()
    return cursor.lastrowid


def _submit(conn, task_id, *, generation=GENERATION, result=RESULT_TEXT, config=None, now=None):
    client = TaskLeaseClient(conn=conn)
    task = client.task_snapshot(task_id)
    lease = client.acquire(
        task_id,
        worker_id="fixture-worker@HOST",
        host="HOST",
        intent="submission receipt regression",
        result_generation=generation,
        config=config,
        now=now,
    )
    requests = []
    original_call = client._call

    def capture_release(name, requested_task_id, payload=None, **kwargs):
        if name == "release":
            requests.append(dict(payload or {}))
        return original_call(name, requested_task_id, payload, **kwargs)

    client._call = capture_release
    ack = client.submit_result(
        task_id,
        lease_id=lease.lease_id,
        fence=lease.fence,
        task_version=task["task_version"],
        generation=generation,
        result=result,
        config=config,
        now=now,
    )
    return client, task, lease, ack, requests


def _operator(conn, *, correction=False):
    from gui.device_auth import create_task_result_operator

    return create_task_result_operator(
        "fixture-operator-" + uuid.uuid4().hex,
        connection=conn,
        can_request_correction=correction,
    )


def _accept_current(conn, client, task_id, operator_token):
    observed = client.task_result_snapshot(task_id)
    record = observed["result"]
    return accept_result(
        conn,
        task_id,
        record["result_id"],
        digest=record["result_sha256"],
        task_version=observed["task_version"],
        status_revision=observed["status_revision"],
        operator_token=operator_token,
    )


def _schema_objects(conn):
    return tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    )


def _event_detail(conn, event_id):
    row = conn.execute("SELECT new_value FROM task_history WHERE id=?", (event_id,)).fetchone()
    assert row is not None
    return json.loads(row[0])


def _store_event_detail(conn, event_id, detail):
    encoded = json.dumps(detail, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    conn.execute("UPDATE task_history SET new_value=? WHERE id=?", (encoded, event_id))


def _seed_preexisting_v0_result(conn, task_id, *, corrupt_release=False):
    """Build a row using the result schema that existed before receipt v1."""
    task = TaskLeaseClient(conn=conn).task_snapshot(task_id)
    worker = "fixture-worker@HOST"
    generation = "legacy-generation"
    result = "Historischer Reviewbeleg aus dem V0-Schema."
    digest = hashlib.sha256(result.encode("utf-8")).hexdigest()
    submitted_at = "2026-10-15 10:20:30.000000"
    conn.execute("""CREATE TABLE worker_task_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        fence INTEGER NOT NULL,
        generation TEXT NOT NULL,
        task_version TEXT NOT NULL,
        result TEXT NOT NULL,
        result_sha256 TEXT NOT NULL,
        submitted_by TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        submission_event_id INTEGER,
        accepted_by TEXT,
        accepted_at TEXT,
        accepted_status_event_id INTEGER,
        acceptance_event_id INTEGER,
        UNIQUE(task_id, fence)
    )""")

    # Persist the pre-receipt lifecycle before running the migration below.
    conn.execute(
        "UPDATE tasks SET status='review',claim_fence=1,claim_id=NULL WHERE id=?",
        (task_id,),
    )
    conn.execute(
        "INSERT INTO task_history(task_id,action,field_changed,old_value,new_value,changed_by,changed_at) "
        "VALUES (?,'status_change','status','open','in_progress',?,?)",
        (task_id, worker, "2026-10-15 10:19:00.000000"),
    )
    conn.execute(
        "INSERT INTO task_history(task_id,action,field_changed,old_value,new_value,changed_by,changed_at) "
        "VALUES (?,'status_change','status','in_progress','review',?,?)",
        (task_id, worker, submitted_at),
    )
    cursor = conn.execute(
        "INSERT INTO worker_task_results "
        "(task_id,fence,generation,task_version,result,result_sha256,submitted_by,submitted_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (task_id, 1, generation, task["task_version"], result, digest, worker, submitted_at),
    )
    result_id = cursor.lastrowid
    release = {
        "fence": 1,
        "outcome": "review",
        "result_ref": f"bach-task-result:{result_id}:{digest}",
        "note": "",
    }
    encoded_release = json.dumps(release, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    cursor = conn.execute(
        "INSERT INTO task_history(task_id,action,field_changed,old_value,new_value,changed_by,changed_at) "
        "VALUES (?,'lease_release','lease','in_progress',?,?,?)",
        (task_id, encoded_release, worker, submitted_at),
    )
    conn.execute(
        "UPDATE worker_task_results SET submission_event_id=? WHERE id=?",
        (cursor.lastrowid, result_id),
    )
    if corrupt_release:
        conn.execute(
            "UPDATE task_history SET changed_by=? WHERE id=?",
            ("other-worker@HOST", cursor.lastrowid),
        )
    conn.commit()
    return result_id


def test_submission_release_read_and_legacy_operator_request_cannot_accept_v1(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client, task, lease, ack, requests = _submit(conn, task_id)

    assert len(requests) == 1
    assert set(requests[0]["worker_result"]) == {"generation", "result"}
    assert requests[0]["worker_result"] == {"generation": GENERATION, "result": RESULT_TEXT}
    assert ack.release.released is True
    assert ack.release.outcome == ack.release.status == "review"

    record = ack.record
    assert record["schema"] == "bach.worker-result.v1"
    assert record["accepted"] is False
    assert record["generation"] == GENERATION
    assert record["task_version"] == task["task_version"]
    assert record["submission"]["schema"] == "bach.worker-submission-readback.v1"
    assert record["submission"]["availability"] == "available"
    assert record["submission_revision"].startswith("sha256:")
    assert len(record["submission_revision"]) == 71
    assert "result_revision" not in record
    assert lease.lease_id not in json.dumps(record, ensure_ascii=False)

    event_id = record["submission_event_id"]
    detail = _event_detail(conn, event_id)
    receipt = detail["submission_receipt"]
    assert receipt["schema"] == "bach.worker-submission-receipt.v1"
    assert receipt["task_id"] == task_id
    assert receipt["result_id"] == record["result_id"]
    assert receipt["fence"] == lease.fence
    assert receipt["generation"] == GENERATION
    assert receipt["task_version"] == task["task_version"]
    assert receipt["result_sha256"] == record["result_sha256"]
    assert receipt["submitted_by"] == record["submitted_by"]
    assert receipt["submitted_status_event_id"] == record["status_revision"]
    assert receipt["submitted_status_changed_at"]
    assert detail["outcome"] == "review"
    assert detail["result_ref"] == (
        f"bach-task-result:{record['result_id']}:{record['result_sha256']}"
    )
    assert lease.lease_id not in json.dumps(detail, ensure_ascii=False)

    task_row = conn.execute(
        "SELECT status,claim_id,claim_fence FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    assert tuple(task_row) == ("review", None, lease.fence)
    assert conn.execute(
        "SELECT COUNT(*) FROM worker_task_results WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='result_acceptance'",
        (task_id,),
    ).fetchone()[0] == 0

    first = client.task_result_snapshot(task_id)
    second = client.task_result_snapshot(task_id)
    assert first["status"] == "review"
    assert first["result"]["accepted"] is False
    assert first["result"]["submission"] == record["submission"]
    assert first["result"]["submission_revision"] == record["submission_revision"]
    assert second["result"]["submission_revision"] == first["result"]["submission_revision"]
    assert lease.lease_id not in json.dumps(first, ensure_ascii=False)

    operator_token = _operator(conn)
    with pytest.raises(ResultConflict):
        _accept_current(conn, client, task_id, operator_token)
    still_review = client.task_result_snapshot(task_id)
    assert still_review["status"] == "review"
    assert still_review["result"]["accepted"] is False
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='result_acceptance'",
        (task_id,),
    ).fetchone()[0] == 0


def test_submit_restores_plain_sqlite_row_factory(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    conn.row_factory = None

    _, _, _, ack, _ = _submit(conn, task_id)

    assert conn.row_factory is None
    assert ack.record["submission"]["availability"] == "available"
    assert read_result(conn, task_id)["result"]["submission"]["availability"] == "available"


@pytest.mark.parametrize(
    "tamper",
    [
        "actor",
        "action",
        "task",
        "fence",
        "outcome",
        "result_ref",
        "missing_receipt",
        "status_join",
        "status_reference",
        "receipt_digest",
    ],
)
def test_changed_or_unjoined_receipt_blocks_operator_acceptance(local_db, tamper):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client, _, _, ack, _ = _submit(conn, task_id)
    record = ack.record
    event_id = record["submission_event_id"]

    if tamper in {"actor", "action", "task"}:
        if tamper == "actor":
            conn.execute(
                "UPDATE task_history SET changed_by=? WHERE id=?",
                ("different-worker@HOST", event_id),
            )
        elif tamper == "action":
            conn.execute(
                "UPDATE task_history SET action=? WHERE id=?",
                ("other_history_action", event_id),
            )
        else:
            conn.execute(
                "UPDATE task_history SET task_id=? WHERE id=?",
                (task_id + 1000, event_id),
            )
    elif tamper == "status_join":
        conn.execute(
            "UPDATE task_history SET changed_at=? WHERE id=?",
            ("2099-01-01 00:00:00", record["status_revision"]),
        )
    elif tamper == "status_reference":
        conn.execute(
            "UPDATE worker_task_results SET submitted_status_event_id=? WHERE id=?",
            (event_id, record["result_id"]),
        )
    elif tamper == "receipt_digest":
        conn.execute(
            "UPDATE worker_task_results SET submission_receipt_sha256=? WHERE id=?",
            ("0" * 64, record["result_id"]),
        )
    else:
        detail = _event_detail(conn, event_id)
        if tamper == "fence":
            detail["fence"] += 1
        elif tamper == "outcome":
            detail["outcome"] = "done"
        elif tamper == "result_ref":
            detail["result_ref"] = "bach-task-result:wrong:reference"
        else:
            detail.pop("submission_receipt", None)
        _store_event_detail(conn, event_id, detail)
    conn.commit()

    observed = client.task_result_snapshot(task_id)
    assert observed["status"] == "review"
    assert observed["result"]["accepted"] is False
    assert observed["result"]["submission"]["availability"] == "unavailable"
    assert observed["result"]["submission"]["reason"] == "submission_receipt_invalid"
    assert observed["result"]["reason"] == "submission_receipt_invalid"

    operator_token = _operator(conn)
    with pytest.raises(ResultConflict):
        _accept_current(conn, client, task_id, operator_token)
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='result_acceptance'",
        (task_id,),
    ).fetchone()[0] == 0


def test_boolean_receipt_id_is_not_an_integer_even_with_matching_digest(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    assert task_id == 1
    _, _, _, ack, _ = _submit(conn, task_id)
    record = ack.record
    event_id = record["submission_event_id"]
    detail = _event_detail(conn, event_id)
    detail["submission_receipt"]["task_id"] = True
    _store_event_detail(conn, event_id, detail)
    canonical = json.dumps(
        detail["submission_receipt"],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    matching_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    conn.execute(
        "UPDATE worker_task_results SET submission_receipt_sha256=? WHERE id=?",
        (matching_digest, record["result_id"]),
    )
    conn.commit()

    observed = read_result(conn, task_id)
    assert observed["result"]["submission"]["availability"] == "unavailable"
    assert observed["result"]["submission"]["reason"] == "submission_receipt_invalid"
    assert observed["result"]["accepted"] is False


def test_v1_receipt_marker_loss_cannot_be_laundered_into_legacy(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client, _, _, ack, _ = _submit(conn, task_id)
    record = ack.record
    event_id = record["submission_event_id"]
    detail = _event_detail(conn, event_id)
    detail.pop("submission_receipt")
    _store_event_detail(conn, event_id, detail)
    conn.execute(
        "UPDATE worker_task_results SET submitted_status_event_id=NULL,"
        "submission_receipt_sha256=NULL WHERE id=?",
        (record["result_id"],),
    )
    conn.commit()

    observed = client.task_result_snapshot(task_id)
    assert observed["result"]["accepted"] is False
    assert observed["result"]["submission_receipt_version"] == 1
    assert observed["result"]["submission"]["availability"] == "unavailable"
    assert observed["result"]["submission"]["reason"] == "submission_receipt_invalid"
    with pytest.raises(ResultConflict):
        _accept_current(conn, client, task_id, _operator(conn))
    assert observed["status"] == "review"
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"


@pytest.mark.parametrize("bad_version", [-1, 2])
def test_unknown_or_negative_receipt_version_cannot_be_accepted(local_db, bad_version):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client, _, _, ack, _ = _submit(conn, task_id)
    conn.execute(
        "UPDATE worker_task_results SET submission_receipt_version=? WHERE id=?",
        (bad_version, ack.record["result_id"]),
    )
    conn.commit()

    observed = client.task_result_snapshot(task_id)
    assert observed["result"]["accepted"] is False
    assert observed["result"]["submission"]["availability"] == "unavailable"
    assert observed["result"]["submission"]["reason"] == "submission_receipt_invalid"
    with pytest.raises(ResultConflict):
        _accept_current(conn, client, task_id, _operator(conn))
    assert observed["status"] == "review"


@pytest.mark.parametrize("corrupt_release", [False, True])
def test_preexisting_v0_rows_migrate_to_legacy_only_projection(local_db, corrupt_release):
    conn, _ = local_db
    task_id = _insert_task(conn)
    result_id = _seed_preexisting_v0_result(conn, task_id, corrupt_release=corrupt_release)
    old_columns = {row[1] for row in conn.execute("PRAGMA table_info(worker_task_results)")}
    assert "submission_receipt_version" not in old_columns
    assert "submission_receipt_sha256" not in old_columns
    old_row = conn.execute(
        "SELECT submission_event_id FROM worker_task_results WHERE id=?", (result_id,)
    ).fetchone()
    assert old_row[0] is not None

    # This is the real old-table migration path: version 0 is assigned only to
    # the persisted V0 row, rather than by editing a newly-created V1 result.
    ensure_result_schema(conn)
    conn.commit()
    migrated = conn.execute(
        "SELECT submission_receipt_version,submission_receipt_sha256,submitted_status_event_id "
        "FROM worker_task_results WHERE id=?",
        (result_id,),
    ).fetchone()
    assert tuple(migrated) == (0, None, None)

    client = TaskLeaseClient(conn=conn)
    observed = client.task_result_snapshot(task_id)
    assert observed["status"] == "review"
    assert observed["result"]["accepted"] is False
    if corrupt_release:
        assert observed["result"]["submission"]["availability"] == "unavailable"
        assert observed["result"]["submission"]["reason"] == "submission_receipt_invalid"
        with pytest.raises(ResultConflict):
            _accept_current(conn, client, task_id, _operator(conn))
        assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    else:
        assert observed["result"]["submission"]["availability"] == "legacy_release_only"
        assert observed["result"]["submission"]["reason"] == "legacy_release_only"
        assert observed["result"]["submission_revision"] is None
        accepted = _accept_current(conn, client, task_id, _operator(conn))
        assert accepted["result"]["accepted"] is True
        assert accepted["status"] == "done"


def test_policy_snapshot_is_frozen_and_readback_does_not_create_schema(local_db):
    conn, path = local_db
    task_id = _insert_task(conn)

    from hub._services.worker_policy_settings import (
        read_global_policy,
        read_task_policy,
        write_global_policy,
        write_task_policy,
    )

    global_view = read_global_policy(db_path=path)
    simple_policy = dict(global_view["policy"])
    simple_policy.update(policy_version="receipt-simple-policy", default_mode="simple_task")
    write_global_policy(
        {
            "configuration_version": global_view["configuration_version"],
            "policy": simple_policy,
            "selection": global_view["selection"],
        },
        actor="fixture-policy-admin",
        db_path=path,
    )
    task_view = read_task_policy(task_id, db_path=path)
    explicit_default = {
        "mode": None,
        "require_user_review": False,
        "github_external_review": None,
        "allow_review_task_pickup": None,
    }
    write_task_policy(
        task_id,
        {
            "task_id": task_id,
            "task_version": task_view["task_version"],
            "configuration_version": task_view["configuration_version"],
            "override": explicit_default,
        },
        actor="fixture-policy-admin",
        db_path=path,
    )

    complete = json.dumps({"schema": "bach.worker-self-check.v1", "complete": True,
        "completed_work": "Versionierten Ergebnisbeleg für die Policyprüfung erstellt.",
        "checks": ["Policy-Snapshot und Ergebnisrevision geprüft."],
        "remaining_required_work": []}, ensure_ascii=False)
    client, _, _, ack, _ = _submit(conn, task_id, result=complete)
    record = ack.record
    frozen = record["submission"]["policy"]
    assert frozen["availability"] == "available"
    assert frozen["policy"]["default_mode"] == "simple_task"
    assert frozen["policy_source"] == "task_override"
    assert frozen["override_present"] is True
    assert frozen["override"] == {
        **explicit_default,
        "require_assigned_slot": None,
        "enforce_model_binding": None,
    }
    assert frozen["user_review_required"] is False
    assert record["accepted"] is False
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"

    before_version = frozen["global_configuration_version"]
    changed_global = read_global_policy(db_path=path)
    balanced_policy = dict(changed_global["policy"])
    balanced_policy.update(policy_version="receipt-balanced-policy", default_mode="balanced")
    write_global_policy(
        {
            "configuration_version": changed_global["configuration_version"],
            "policy": balanced_policy,
            "selection": changed_global["selection"],
        },
        actor="fixture-policy-admin",
        db_path=path,
    )
    after = client.task_result_snapshot(task_id)
    assert after["result"]["submission"]["policy"] == frozen
    assert after["result"]["submission"]["policy"]["global_configuration_version"] == before_version
    assert after["result"]["submission_revision"] == record["submission_revision"]

    schema_before = _schema_objects(conn)
    conn.execute("PRAGMA query_only=ON")
    first = read_result(conn, task_id)
    second = read_result(conn, task_id)
    assert first == second
    assert first["result"]["submission"]["availability"] == "available"
    assert _schema_objects(conn) == schema_before
    conn.execute("PRAGMA query_only=OFF")


def test_missing_policy_store_keeps_new_result_in_review(no_policy_store_db):
    conn, _ = no_policy_store_db
    task_id = _insert_task(conn)
    client, _, _, ack, _ = _submit(conn, task_id)
    record = ack.record

    assert record["submission"]["availability"] == "available"
    assert record["submission"]["policy"] == {
        "availability": "unavailable",
        "reason": "policy_store_unavailable",
    }
    assert record["accepted"] is False
    assert record["submission_revision"].startswith("sha256:")
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"

    with pytest.raises(ResultConflict):
        _accept_current(conn, client, task_id, _operator(conn))
    assert client.task_result_snapshot(task_id)["status"] == "review"


def test_missing_optional_policy_contract_keeps_new_result_in_review(monkeypatch, local_db):
    from hub._services import worker_policy_settings as settings

    def unavailable_kernel():
        raise settings.PolicyUnavailable("fixture simulates an unavailable shared contract")

    monkeypatch.setattr(settings, "_kernel", unavailable_kernel)
    conn, _ = local_db
    task_id = _insert_task(conn)
    client, _, _, ack, _ = _submit(conn, task_id)

    assert ack.record["submission"]["availability"] == "available"
    assert ack.record["submission"]["policy"] == {
        "availability": "unavailable",
        "reason": "policy_contract_unavailable",
    }
    assert ack.record["accepted"] is False
    first = client.task_result_snapshot(task_id)
    second = client.task_result_snapshot(task_id)
    assert first["result"]["submission"] == second["result"]["submission"]
    assert first["result"]["reason"] == "awaiting_review"
    assert first["status"] == "review"

    with pytest.raises(ResultConflict):
        _accept_current(conn, client, task_id, _operator(conn))
    still_review = client.task_result_snapshot(task_id)
    assert still_review["status"] == "review"
    assert still_review["result"]["submission"]["policy"]["reason"] == "policy_contract_unavailable"


def test_correction_and_new_fence_make_old_submission_unacceptable(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client, _, first_lease, first_ack, _ = _submit(conn, task_id)
    first_view = client.task_result_snapshot(task_id)
    first_record = first_view["result"]
    operator_token = _operator(conn, correction=True)
    correction = request_result_correction(
        conn,
        task_id,
        {
            "result_id": first_record["result_id"],
            "result_sha256": first_record["result_sha256"],
            "generation": first_record["generation"],
            "fence": first_record["fence"],
            "task_version": first_record["task_version"],
            "status_revision": first_view["status_revision"],
            "request_id": str(uuid.uuid4()),
            "correction_note": "Bitte Belege und Einschränkungen ergänzen.",
        },
        operator_token=operator_token,
    )
    assert correction["status"] == "pending"
    pending = client.task_snapshot(task_id)
    assert pending["status"] == "pending"
    assert pending["task_version"] != first_view["task_version"]

    with pytest.raises(ResultConflict):
        accept_result(
            conn,
            task_id,
            first_record["result_id"],
            digest=first_record["result_sha256"],
            task_version=first_view["task_version"],
            status_revision=first_view["status_revision"],
            operator_token=operator_token,
        )
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "pending"

    second_generation = "receipt-generation-2"
    second_version = pending["task_version"]
    second_lease = client.acquire(
        task_id,
        worker_id="fixture-worker@HOST",
        host="HOST",
        intent="corrected submission",
        task_version=second_version,
        result_generation=second_generation,
    )
    second_ack = client.submit_result(
        task_id,
        lease_id=second_lease.lease_id,
        fence=second_lease.fence,
        task_version=second_version,
        generation=second_generation,
        result="Korrigiertes Ergebnis mit ergänzten Belegen.",
    )
    assert second_lease.fence == first_lease.fence + 1
    assert second_ack.record["generation"] == second_generation
    assert second_ack.record["submission"]["availability"] == "available"
    assert second_ack.record["submission_revision"] != first_ack.record["submission_revision"]
    latest = client.task_result_snapshot(task_id)
    assert latest["result"]["result_id"] == second_ack.record["result_id"]
    assert latest["result"]["accepted"] is False
    with pytest.raises(ResultConflict):
        accept_result(
            conn,
            task_id,
            first_record["result_id"],
            digest=first_record["result_sha256"],
            task_version=first_view["task_version"],
            status_revision=first_view["status_revision"],
            operator_token=operator_token,
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM worker_task_results WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='result_correction_request'",
        (task_id,),
    ).fetchone()[0] == 1
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"


def test_expired_submission_is_late_history_without_receipt_or_result_row(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client = TaskLeaseClient(conn=conn)
    task = client.task_snapshot(task_id)
    started = datetime.now(timezone.utc)
    config = LeaseConfig(creator_window_seconds=0)
    lease = client.acquire(
        task_id,
        worker_id="fixture-worker@HOST",
        host="HOST",
        result_generation=GENERATION,
        config=config,
        now=started,
    )

    with pytest.raises(LeaseExpiredError):
        client.submit_result(
            task_id,
            lease_id=lease.lease_id,
            fence=lease.fence,
            task_version=task["task_version"],
            generation=GENERATION,
            result=RESULT_TEXT,
            config=config,
            now=started + timedelta(minutes=31),
        )

    state = conn.execute(
        "SELECT status,claim_id,claim_fence FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    assert tuple(state) == ("in_progress", lease.lease_id, lease.fence)
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='late_result'",
        (task_id,),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='lease_release'",
        (task_id,),
    ).fetchone()[0] == 0
    has_results = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_task_results'"
    ).fetchone()
    if has_results:
        assert conn.execute(
            "SELECT COUNT(*) FROM worker_task_results WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 0


def test_receipt_write_failure_rolls_back_submit_release_atomically(local_db):
    conn, _ = local_db
    task_id = _insert_task(conn)
    client = TaskLeaseClient(conn=conn)
    task = client.task_snapshot(task_id)
    lease = client.acquire(
        task_id,
        worker_id="fixture-worker@HOST",
        host="HOST",
        result_generation=GENERATION,
    )
    ensure_result_schema(conn)
    conn.execute("""
        CREATE TRIGGER reject_receipt_update
        BEFORE UPDATE OF submission_receipt_sha256 ON worker_task_results
        BEGIN
            SELECT RAISE(ABORT, 'forced receipt write failure');
        END
    """)
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced receipt write failure"):
        client.submit_result(
            task_id,
            lease_id=lease.lease_id,
            fence=lease.fence,
            task_version=task["task_version"],
            generation=GENERATION,
            result=RESULT_TEXT,
        )

    task_row = conn.execute(
        "SELECT status,claim_id,claim_fence FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    assert tuple(task_row) == ("in_progress", lease.lease_id, lease.fence)
    assert conn.execute(
        "SELECT COUNT(*) FROM worker_task_results WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='lease_release'",
        (task_id,),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='status_change' "
        "AND new_value='review'",
        (task_id,),
    ).fetchone()[0] == 0
