from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import socket
import sqlite3
from types import SimpleNamespace
import uuid

import pytest


GLOBAL_PATH = "/api/system/worker-policy"
TASK_PATH = "/api/tasks/{task_id}/worker-policy"
ACTOR = "test-device"
TASK_ID = 1
NOW = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


def _connect(path):
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _create_database(path):
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                require_user_review INTEGER NOT NULL DEFAULT 0, claimed_by TEXT,
                claimed_at TEXT, claim_id TEXT, claim_host TEXT, claim_issued_at TEXT,
                claim_expires_at TEXT, claim_heartbeat_at TEXT,
                claim_fence INTEGER NOT NULL DEFAULT 0, claim_ttl_profile TEXT,
                claim_salt_ref TEXT, claim_intent TEXT, claim_request_id TEXT,
                claim_task_version TEXT, claim_result_generation TEXT
            );
            INSERT INTO tasks(id,title,status,require_user_review)
            VALUES (1,'Seed task','pending',0);
            """
        )


def _insert_task(path, task_id, *, required=False, status="pending", title=None):
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks(id,title,status,require_user_review) VALUES (?,?,?,?)",
            (task_id, title or f"Task {task_id}", status, int(required)),
        )


def _task_row(path, task_id=TASK_ID):
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None


def _config_rows(path):
    with _connect(path) as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT key,value FROM system_config ORDER BY key"
        )]


def _schema_objects(path):
    with _connect(path) as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )]


def _global_payload(snapshot):
    return {
        "configuration_version": snapshot["configuration_version"],
        "policy": json.loads(json.dumps(snapshot["policy"])),
        "selection": json.loads(json.dumps(snapshot["selection"])),
    }


def _override(*, require_review=False, github_external_review=None,
              allow_review_task_pickup=None, mode=None,
              require_assigned_slot=None, enforce_model_binding=None):
    return {
        "mode": mode, "require_user_review": require_review,
        "github_external_review": github_external_review,
        "allow_review_task_pickup": allow_review_task_pickup,
        "require_assigned_slot": require_assigned_slot,
        "enforce_model_binding": enforce_model_binding,
    }


def _task_write_payload(snapshot, task_id=TASK_ID, *, override=None):
    return {
        "task_id": task_id, "task_version": snapshot["task_version"],
        "configuration_version": snapshot["configuration_version"],
        "override": override or _override(),
    }


def _schema_version(row):
    from hub._services.task_lease import task_content_version
    return task_content_version(row)


def _seed_claim(path, *, task_id=TASK_ID, now=NOW, generation=None,
                claimed_by=None, claim_id=None, expires_at=None,
                issued_at=None, heartbeat_at=None, fence=17):
    generation = generation or uuid.uuid4().hex
    physical_id = "worker-" + uuid.uuid4().hex
    holder = claimed_by or f"{physical_id}@{socket.gethostname()}"
    claim_id = claim_id or "native-private-capability-" + uuid.uuid4().hex
    issued_at = issued_at or (now - timedelta(seconds=30)).isoformat()
    heartbeat_at = heartbeat_at or (now - timedelta(seconds=2)).isoformat()
    expires_at = expires_at or (now + timedelta(minutes=10)).isoformat()
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return generation, holder, claim_id
        version = _schema_version(dict(row))
        conn.execute(
            """UPDATE tasks SET status='in_progress', claimed_by=?, claimed_at=?,
               claim_id=?, claim_host=?, claim_issued_at=?, claim_expires_at=?,
               claim_heartbeat_at=?, claim_fence=?, claim_ttl_profile='M',
               claim_request_id=?, claim_task_version=?, claim_result_generation=?
               WHERE id=?""",
            (holder, issued_at, claim_id, socket.gethostname(), issued_at, expires_at,
             heartbeat_at, fence, uuid.uuid4().hex, version, generation, task_id),
        )
    return generation, holder, claim_id


def _lease_item(task_id, generation, holder, *, now=NOW):
    slot_id = "task-slot-1"
    return {
        "id": slot_id, "runtime_verified": True, "running": True,
        "active_task_id": task_id, "generation": generation,
        "execution": {
            "schema": "bach.worker-execution.v1", "worker_id": slot_id,
            "state": "running", "terminal": False, "generation": generation,
            "active_task_id": task_id, "lease_worker_id": holder,
            "heartbeat_at": (now - timedelta(seconds=1)).isoformat(),
        },
    }


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "worker-policy-test.db"
    _create_database(path)
    return path


@pytest.fixture
def api(db_path, monkeypatch):
    from fastapi.testclient import TestClient
    from hub import bach_paths
    from gui import device_auth, server
    from gui.api import unified_api

    monkeypatch.setattr(bach_paths, "BACH_DB", db_path)
    monkeypatch.setattr(unified_api, "BACH_DB", db_path)
    monkeypatch.setattr(device_auth, "GET_CONNECTION", lambda: _connect(db_path))
    with _connect(db_path) as conn:
        token = device_auth.create_device(ACTOR, connection=conn)
    client = TestClient(server.app)
    yield SimpleNamespace(client=client, token=token, path=db_path, auth=device_auth)
    client.close()


def _auth(api):
    return {"Authorization": f"Bearer {api.token}"}


def test_global_get_is_read_only_and_does_not_initialize_schema(api):
    before_rows, before_schema = _config_rows(api.path), _schema_objects(api.path)
    response = api.client.get(GLOBAL_PATH, headers=_auth(api))
    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "available"
    assert body["policy_source"] == "system_default"
    assert body["configuration_version"]
    assert _config_rows(api.path) == before_rows
    assert _schema_objects(api.path) == before_schema


def test_global_get_returns_503_without_schema_and_does_not_recreate_it(api):
    with _connect(api.path) as conn:
        conn.execute("DROP TABLE system_config")
    before_schema = _schema_objects(api.path)
    response = api.client.get(GLOBAL_PATH, headers=_auth(api))
    assert response.status_code == 503
    assert _schema_objects(api.path) == before_schema
    with _connect(api.path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_config'"
        ).fetchone() is None


def test_global_put_is_observed_by_an_independent_get(api):
    before = api.client.get(GLOBAL_PATH, headers=_auth(api)).json()
    payload = _global_payload(before)
    payload["policy"]["github_external_review"] = False
    payload["selection"]["normal_task_order"] = "oldest_first"
    written = api.client.put(GLOBAL_PATH, headers=_auth(api), json=payload)
    assert written.status_code == 200
    assert written.json()["updated"] is True
    assert written.json()["worker_started"] is False
    after = api.client.get(GLOBAL_PATH, headers=_auth(api))
    assert after.status_code == 200
    assert after.json()["policy"]["github_external_review"] is False
    assert after.json()["selection"]["normal_task_order"] == "oldest_first"
    assert after.json()["configuration_version"] == written.json()["configuration_version"]
    assert _config_rows(api.path)


def test_global_compare_and_swap_rejects_stale_version_and_reset_prevents_aba(api):
    initial = api.client.get(GLOBAL_PATH, headers=_auth(api)).json()
    stale_payload = _global_payload(initial)
    first = _global_payload(initial)
    first["selection"]["normal_task_order"] = "oldest_first"
    first_write = api.client.put(GLOBAL_PATH, headers=_auth(api), json=first)
    assert first_write.status_code == 200
    reset = api.client.put(
        GLOBAL_PATH, headers=_auth(api),
        json={"configuration_version": first_write.json()["configuration_version"],
              "reset_to_default": True},
    )
    assert reset.status_code == 200
    reread = api.client.get(GLOBAL_PATH, headers=_auth(api)).json()
    assert reread["policy_source"] == "system_default"
    assert reread["selection"]["normal_task_order"] == "priority_then_created"
    assert reread["configuration_version"] != initial["configuration_version"]
    assert api.client.put(
        GLOBAL_PATH, headers=_auth(api), json=stale_payload
    ).status_code == 409


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body["policy"].update(allow_review_task_pickup=None),
        lambda body: body["policy"].update(allow_review_task_pickup=1),
        lambda body: body["policy"].update(github_external_review=None),
        lambda body: body["policy"].update(github_external_review=1),
        lambda body: body["selection"].update(resume_bound_task_first=None),
        lambda body: body["selection"].update(resume_bound_task_first=1),
        lambda body: body["selection"].update(decompose_when_idle=None),
        lambda body: body["selection"].update(decompose_when_idle=1),
        lambda body: body["policy"].update(unrecognized=True),
        lambda body: body["selection"].update(unrecognized=True),
        lambda body: body.update(unrecognized=True),
    ],
)
def test_global_put_rejects_non_boolean_and_unknown_fields(api, mutation):
    snapshot = api.client.get(GLOBAL_PATH, headers=_auth(api)).json()
    before = _config_rows(api.path)
    payload = _global_payload(snapshot)
    mutation(payload)
    response = api.client.put(GLOBAL_PATH, headers=_auth(api), json=payload)
    assert response.status_code == 400
    assert _config_rows(api.path) == before


def test_global_write_error_rolls_back_config_and_audit_rows(api):
    before = api.client.get(GLOBAL_PATH, headers=_auth(api)).json()
    rows_before = _config_rows(api.path)
    with _connect(api.path) as conn:
        conn.execute(
            """CREATE TRIGGER reject_worker_policy_audit
               BEFORE INSERT ON system_config
               WHEN NEW.key LIKE 'worker_review_audit.v1:%'
               BEGIN SELECT RAISE(ABORT, 'forced audit failure'); END"""
        )
    payload = _global_payload(before)
    payload["selection"]["normal_task_order"] = "oldest_first"
    response = api.client.put(GLOBAL_PATH, headers=_auth(api), json=payload)
    assert response.status_code == 503
    assert _config_rows(api.path) == rows_before
    assert api.client.get(
        GLOBAL_PATH, headers=_auth(api)
    ).json()["configuration_version"] == before["configuration_version"]


def test_task_settings_cas_checks_both_task_content_and_configuration_versions(api):
    path = TASK_PATH.format(task_id=TASK_ID)
    first = api.client.get(path, headers=_auth(api)).json()
    accepted = api.client.put(
        path, headers=_auth(api),
        json=_task_write_payload(first, override=_override(github_external_review=False)),
    )
    assert accepted.status_code == 200
    assert accepted.json()["worker_started"] is False
    after_policy_change = api.client.get(path, headers=_auth(api)).json()
    stale_config = _task_write_payload(
        after_policy_change, override=_override(allow_review_task_pickup=True)
    )
    stale_config["configuration_version"] = first["configuration_version"]
    assert api.client.put(path, headers=_auth(api), json=stale_config).status_code == 409
    with _connect(api.path) as conn:
        conn.execute("UPDATE tasks SET title='Changed task content' WHERE id=?", (TASK_ID,))
    changed_task = api.client.get(path, headers=_auth(api)).json()
    stale_task = _task_write_payload(
        changed_task, override=_override(allow_review_task_pickup=True)
    )
    stale_task["task_version"] = first["task_version"]
    assert api.client.put(path, headers=_auth(api), json=stale_task).status_code == 409


def test_task_override_reset_is_cas_bound_and_changes_version_without_aba(api):
    path = TASK_PATH.format(task_id=TASK_ID)
    initial = api.client.get(path, headers=_auth(api)).json()
    configured = api.client.put(
        path, headers=_auth(api),
        json=_task_write_payload(initial, override=_override(github_external_review=False)),
    )
    assert configured.status_code == 200
    current = api.client.get(path, headers=_auth(api)).json()
    reset = api.client.put(
        path, headers=_auth(api),
        json={"task_id": TASK_ID, "task_version": current["task_version"],
              "configuration_version": current["configuration_version"],
              "reset_to_default": True},
    )
    assert reset.status_code == 200
    assert reset.json()["worker_started"] is False
    reread = api.client.get(path, headers=_auth(api)).json()
    assert reread["override"] == {
        "mode": None, "require_user_review": False,
        "github_external_review": None, "allow_review_task_pickup": None,
    }
    assert reread["configuration_version"] != initial["configuration_version"]
    stale = _task_write_payload(
        reread, override=_override(allow_review_task_pickup=True)
    )
    stale["configuration_version"] = initial["configuration_version"]
    assert api.client.put(path, headers=_auth(api), json=stale).status_code == 409


def test_user_review_can_be_added_or_inherited_but_not_removed_or_reset(api):
    path = TASK_PATH.format(task_id=TASK_ID)
    with _connect(api.path) as conn:
        conn.execute(
            """UPDATE tasks SET status='in_progress', claimed_by='worker-agent@HOST',
               claimed_at=?, claim_id='private-claim-marker', claim_fence=9 WHERE id=?""",
            (NOW.isoformat(), TASK_ID),
        )
    before_row = _task_row(api.path)
    initial = api.client.get(path, headers=_auth(api)).json()
    assert initial["effective"]["user_review_required"] is False
    add_review = api.client.put(
        path, headers=_auth(api),
        json=_task_write_payload(initial, override=_override(require_review=True)),
    )
    assert add_review.status_code == 200
    assert add_review.json()["worker_started"] is False
    added = api.client.get(path, headers=_auth(api)).json()
    assert added["effective"]["user_review_required"] is True
    assert _task_row(api.path) == before_row
    attempt_clear = api.client.put(
        path, headers=_auth(api),
        json=_task_write_payload(added, override=_override(require_review=False)),
    )
    attempt_reset = api.client.put(
        path, headers=_auth(api),
        json={"task_id": TASK_ID, "task_version": added["task_version"],
              "configuration_version": added["configuration_version"],
              "reset_to_default": True},
    )
    assert attempt_clear.status_code == 400
    assert attempt_reset.status_code == 400
    assert _task_row(api.path) == before_row
    _insert_task(api.path, 2, required=True)
    inherited = api.client.get(TASK_PATH.format(task_id=2), headers=_auth(api)).json()
    assert inherited["effective"]["user_review_required"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body["override"].update(require_user_review=None),
        lambda body: body["override"].update(require_user_review=1),
        lambda body: body["override"].update(github_external_review=1),
        lambda body: body["override"].update(allow_review_task_pickup=1),
        lambda body: body["override"].update(unrecognized=True),
        lambda body: body.update(unrecognized=True),
        lambda body: body.update(reset_to_default=1),
    ],
)
def test_task_put_rejects_non_boolean_and_unknown_fields(api, mutation):
    path = TASK_PATH.format(task_id=TASK_ID)
    snapshot = api.client.get(path, headers=_auth(api)).json()
    before_config = _config_rows(api.path)
    payload = _task_write_payload(snapshot)
    mutation(payload)
    response = api.client.put(path, headers=_auth(api), json=payload)
    assert response.status_code == 400
    assert _config_rows(api.path) == before_config


def test_unknown_task_get_and_put_return_404(api):
    path = TASK_PATH.format(task_id=999)
    assert api.client.get(path, headers=_auth(api)).status_code == 404
    payload = {
        "task_id": 999, "task_version": "a" * 64,
        "configuration_version": "b" * 64, "override": _override(),
    }
    assert api.client.put(path, headers=_auth(api), json=payload).status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", GLOBAL_PATH), ("PUT", GLOBAL_PATH),
        ("GET", TASK_PATH.format(task_id=TASK_ID)),
        ("PUT", TASK_PATH.format(task_id=TASK_ID)),
    ],
)
@pytest.mark.parametrize("revoked", [False, True], ids=["missing-token", "revoked-token"])
def test_real_device_auth_protects_get_and_put(api, method, path, revoked):
    headers = _auth(api) if revoked else {}
    if revoked:
        with _connect(api.path) as conn:
            assert api.auth.revoke_device(ACTOR, connection=conn)
    response = api.client.request(
        method, path, headers=headers, json={} if method == "PUT" else None
    )
    assert response.status_code == (403 if revoked else 401)


def test_controller_tray_and_worker_projection_preserve_only_verified_holder(monkeypatch):
    from hub._services.chat import telegram_chat
    from hub._services.chat.chat_tray import BACHTray
    from gui.api.worker_status_adapter import _project_worker

    task_id, generation, slot_id = TASK_ID, uuid.uuid4().hex, "task-slot-1"
    physical_id = "worker-" + uuid.uuid4().hex
    holder = f"{physical_id}@{socket.gethostname()}"
    control = telegram_chat._WorkerControl(
        worker_id=slot_id, generation=generation, physical_worker_id=physical_id,
        lease_worker_id=holder, thread=SimpleNamespace(is_alive=lambda: True),
        worker_thread_started=True, last_heartbeat_at=(NOW - timedelta(seconds=1)).isoformat(),
        task_binding=SimpleNamespace(task_id=task_id, closed=False, generation=generation),
    )
    unbound = telegram_chat._control_execution_receipt(control, verify_results=False)
    assert "lease_worker_id" not in unbound
    monkeypatch.setitem(telegram_chat._WORKER_CONTROLS, slot_id, control)
    receipt = telegram_chat._control_execution_receipt(control, verify_results=False)
    assert receipt["active_task_id"] == task_id
    assert receipt["lease_worker_id"] == holder
    tray_projection = BACHTray._safe_worker_execution(slot_id, receipt)
    assert tray_projection["lease_worker_id"] == holder
    worker_projection = _project_worker({
        "id": slot_id, "runtime_verified": True, "running": True,
        "active_task_id": task_id, "generation": generation,
        "execution": tray_projection,
    })
    assert worker_projection["execution"]["active_task_id"] == task_id
    assert worker_projection["execution"]["lease_worker_id"] == holder
    assert receipt["worker_thread_started"] is True


def test_verified_native_lease_projects_stable_hash_without_private_capability(db_path, monkeypatch):
    from hub._services.chat import telegram_chat
    from hub._services.chat.chat_tray import BACHTray
    from hub._services.worker_policy_settings import attach_active_task_leases
    from gui.api.worker_status_adapter import _project_worker

    generation, holder, native_id = _seed_claim(db_path)
    slot_id = "task-slot-1"
    control = telegram_chat._WorkerControl(
        worker_id=slot_id, generation=generation,
        physical_worker_id=holder.split("@", 1)[0], lease_worker_id=holder,
        thread=SimpleNamespace(is_alive=lambda: True), worker_thread_started=True,
        last_heartbeat_at=(NOW - timedelta(seconds=1)).isoformat(),
        task_binding=SimpleNamespace(task_id=TASK_ID, closed=False, generation=generation),
    )
    monkeypatch.setitem(telegram_chat._WORKER_CONTROLS, slot_id, control)
    receipt = telegram_chat._control_execution_receipt(control, verify_results=False)
    tray_projection = BACHTray._safe_worker_execution(slot_id, receipt)
    projected = _project_worker({
        "id": slot_id, "runtime_verified": True, "running": True,
        "active_task_id": TASK_ID, "generation": generation,
        "execution": tray_projection,
    })
    projected["active_task_lease"] = {"lease_id": "caller-supplied-raw-dummy"}
    schema_before, task_before = _schema_objects(db_path), _task_row(db_path)
    result = attach_active_task_leases([projected], db_path=db_path, now=NOW)
    lease = result[0]["active_task_lease"]
    expected = "sha256:" + hashlib.sha256(native_id.encode("utf-8")).hexdigest()
    assert lease["lease_id"] == expected
    assert lease["lease_id_kind"] == "observation_sha256"
    assert lease["source"] == "native_task_db"
    assert lease["fence"] == 17
    assert lease["task_id"] == TASK_ID
    serialized = json.dumps(result, sort_keys=True)
    assert native_id not in serialized
    assert "caller-supplied-raw-dummy" not in serialized
    assert result == attach_active_task_leases([projected], db_path=db_path, now=NOW)
    assert _task_row(db_path) == task_before
    assert _schema_objects(db_path) == schema_before


@pytest.mark.parametrize(
    "case",
    [
        "expired", "unknown_task", "legacy", "foreign_holder",
        "generation_mismatch", "content_version_mismatch", "zero_fence",
        "missing_heartbeat", "future_controller_heartbeat", "missing_execution",
        "terminal_execution", "runtime_unverified", "not_running",
    ],
)
def test_lease_projection_excludes_unverified_or_stale_claims(db_path, case):
    from hub._services.worker_policy_settings import attach_active_task_leases

    generation, holder, native_id = _seed_claim(db_path)
    item = _lease_item(TASK_ID, generation, holder)
    with _connect(db_path) as conn:
        if case == "expired":
            conn.execute("UPDATE tasks SET claim_expires_at=? WHERE id=?",
                         ((NOW - timedelta(seconds=1)).isoformat(), TASK_ID))
        elif case == "legacy":
            conn.execute("UPDATE tasks SET claim_id=NULL WHERE id=?", (TASK_ID,))
        elif case == "generation_mismatch":
            conn.execute("UPDATE tasks SET claim_result_generation=? WHERE id=?",
                         (uuid.uuid4().hex, TASK_ID))
        elif case == "content_version_mismatch":
            conn.execute("UPDATE tasks SET title='changed after claim' WHERE id=?", (TASK_ID,))
        elif case == "zero_fence":
            conn.execute("UPDATE tasks SET claim_fence=0 WHERE id=?", (TASK_ID,))
        elif case == "missing_heartbeat":
            conn.execute("UPDATE tasks SET claim_heartbeat_at=NULL WHERE id=?", (TASK_ID,))
    if case == "unknown_task":
        item["active_task_id"] = 999
        item["execution"]["active_task_id"] = 999
    elif case == "foreign_holder":
        item["execution"]["lease_worker_id"] = "worker-" + uuid.uuid4().hex + "@OTHER"
    elif case == "future_controller_heartbeat":
        item["execution"]["heartbeat_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif case == "missing_execution":
        item.pop("execution")
    elif case == "terminal_execution":
        item["execution"]["terminal"] = True
    elif case == "runtime_unverified":
        item["runtime_verified"] = False
    elif case == "not_running":
        item["running"] = False
    item["active_task_lease"] = {"lease_id": "untrusted-raw-dummy"}
    schema_before = _schema_objects(db_path)
    result = attach_active_task_leases([item], db_path=db_path, now=NOW)
    assert "active_task_lease" not in result[0]
    serialized = json.dumps(result, sort_keys=True)
    assert native_id not in serialized
    assert "untrusted-raw-dummy" not in serialized
    assert _schema_objects(db_path) == schema_before



def test_task_policy_supports_current_tasks_schema_without_user_review_column(tmp_path):
    from hub._services.worker_policy_settings import read_task_policy, write_task_policy

    path = tmp_path / "tasks-without-review-column.db"
    task_id = 214
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                claimed_by TEXT, claimed_at TEXT, claim_id TEXT, claim_host TEXT,
                claim_issued_at TEXT, claim_expires_at TEXT, claim_heartbeat_at TEXT,
                claim_fence INTEGER NOT NULL DEFAULT 0, claim_ttl_profile TEXT,
                claim_salt_ref TEXT, claim_intent TEXT, claim_request_id TEXT,
                claim_task_version TEXT, claim_result_generation TEXT
            );
            """
        )
        conn.execute(
            """INSERT INTO tasks(
                   id,title,status,claimed_by,claimed_at,claim_id,claim_host,
                   claim_issued_at,claim_expires_at,claim_heartbeat_at,claim_fence,
                   claim_ttl_profile,claim_request_id,claim_task_version,claim_result_generation
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, "Existing-schema task", "in_progress", "worker-existing@HOST",
             NOW.isoformat(), "private-claim-214", "HOST", NOW.isoformat(),
             (NOW + timedelta(minutes=5)).isoformat(), NOW.isoformat(), 23, "M",
             uuid.uuid4().hex, "f" * 64, uuid.uuid4().hex),
        )

    original_task = _task_row(path, task_id)
    before_schema = _schema_objects(path)
    with _connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    assert "require_user_review" not in columns

    initial = read_task_policy(task_id, db_path=path)
    assert initial["effective"]["state"] == "not_evaluated"
    assert initial["effective"]["user_review_required"] is False

    written = write_task_policy(
        task_id,
        _task_write_payload(
            initial, task_id=task_id, override=_override(require_review=True)
        ),
        actor="device:legacy-schema-test",
        db_path=path,
    )
    assert written["worker_started"] is False
    confirmed = read_task_policy(task_id, db_path=path)
    assert confirmed["effective"]["state"] == "not_evaluated"
    assert confirmed["effective"]["user_review_required"] is True

    with pytest.raises(ValueError):
        write_task_policy(
            task_id,
            _task_write_payload(
                confirmed, task_id=task_id, override=_override(require_review=False)
            ),
            actor="device:legacy-schema-test",
            db_path=path,
        )
    sticky = read_task_policy(task_id, db_path=path)
    assert sticky["effective"]["state"] == "not_evaluated"
    assert sticky["effective"]["user_review_required"] is True
    assert _task_row(path, task_id) == original_task
    assert _schema_objects(path) == before_schema
