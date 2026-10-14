"""Versioned v1 result-history and route-level correction contract tests."""
import asyncio
import hashlib
import sqlite3
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from system.tests.test_task_lease_client import _init_db, _insert_task
from hub._services.task_lease_client import TaskLeaseClient


_V1_TEXT = "Früheres Ergebnis mit nachvollziehbaren Belegen."
_V1_SHA = hashlib.sha256(_V1_TEXT.encode("utf-8")).hexdigest()
_V1_TASK_VERSION = "a" * 64
RESULT_HISTORY_V1_FIXTURE = {
    "schema": "bach.task-result-history.v1",
    "task_id": 42001,
    "events": [
        {
            "event_id": 7002,
            "type": "correction_requested",
            "occurred_at": "2026-10-12T11:30:00Z",
            "correction": {
                "correction_id": 8,
                "correction_round": 1,
                "source_result_id": 59,
                "source_result_sha256": _V1_SHA,
                "note": "Quellen und Grenzen ergänzen.",
                "request_id": "a6b7c8d9-e001-4002-8003-a4b5c6d7e8f9",
            },
        },
        {
            "event_id": 7001,
            "type": "result_submitted",
            "occurred_at": "2026-10-12T11:20:00Z",
            "result": {
                "result_id": 59,
                "result_sha256": _V1_SHA,
                "text": _V1_TEXT,
                "generation": "fixture-generation-1",
                "fence": 7,
                "task_version": _V1_TASK_VERSION,
            },
        },
    ],
    "next_before_event_id": None,
    "has_more": False,
}


def _seed_reviewed_task(db_path):
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    task_id = _insert_task(conn, title="API-Korrektur", status="open")
    client = TaskLeaseClient(conn=conn)
    task = client.task_snapshot(task_id)
    binding = client.acquire(
        task_id,
        worker_id="api-fixture@HOST",
        host="HOST",
        task_version=task["task_version"],
        result_generation="api-generation-1",
    )
    submitted = client.submit_result(
        task_id,
        lease_id=binding.lease_id,
        fence=binding.fence,
        task_version=binding.task_version,
        generation="api-generation-1",
        result="API-Ergebnis mit überprüfbaren Quellen",
    )
    return conn, task_id, client, submitted.record


@pytest.fixture
def api_review(tmp_path, monkeypatch):
    import gui.server as server
    from gui.device_auth import create_task_result_operator

    db_path = tmp_path / "task-result-api.sqlite"
    keeper, task_id, client, submitted = _seed_reviewed_task(db_path)

    def connect():
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "get_bach_db", connect)
    read_token = create_task_result_operator("api-read-only", connection=keeper)
    correction_token = create_task_result_operator(
        "api-correction", connection=keeper, can_request_correction=True
    )
    yield server, keeper, task_id, client, submitted, read_token, correction_token
    keeper.close()


def _request(token=None, lease_id=None, *, service_id=None, service_token=None):
    headers = {}
    if token is not None:
        headers["X-BACH-Result-Operator"] = token
    if lease_id is not None:
        headers["X-Lease-Id"] = lease_id
    if service_id is not None:
        headers["X-BACH-Result-Service-ID"] = service_id
    if service_token is not None:
        headers["X-BACH-Result-Service"] = service_token
    return SimpleNamespace(headers=headers)


def test_service_identity_headers_are_forwarded_and_required_by_middleware(api_review, monkeypatch):
    server, _keeper, task_id, _client, _submitted, _read_token, _correction_token = api_review
    service_id = "service-api-fixture"
    service_token = "S" * 43
    seen = []

    def fake_read(conn, actual_task_id, **kwargs):
        seen.append(("read", actual_task_id, kwargs))
        return {"schema": "read-fixture"}

    def fake_history(conn, actual_task_id, **kwargs):
        seen.append(("history", actual_task_id, kwargs))
        return {"schema": "history-fixture", "events": []}

    from hub._services import task_result_service

    monkeypatch.setattr(task_result_service, "read_result", fake_read)
    monkeypatch.setattr(task_result_service, "read_result_history", fake_history)
    request = _request(service_id=service_id, service_token=service_token)
    assert asyncio.run(server.read_task_result(task_id, request)) == {"schema": "read-fixture"}
    assert asyncio.run(server.read_task_result_history(task_id, request)) == {
        "schema": "history-fixture", "events": []
    }
    assert seen[0][2]["service_id"] == service_id
    assert seen[0][2]["service_token"] == service_token
    assert seen[1][2]["service_id"] == service_id
    assert seen[1][2]["service_token"] == service_token

    middleware = server.DeviceAuthMiddleware(app=object())

    def request_for(path, headers, method="GET"):
        return SimpleNamespace(
            url=SimpleNamespace(path=path, scheme="http", netloc="example.test"),
            method=method,
            headers=headers,
            cookies={},
            state=SimpleNamespace(),
        )

    async def call_next(_request):
        return "passed"

    incomplete = asyncio.run(middleware.dispatch(
        request_for("/api/tasks/42/result", {"X-BACH-Result-Service": service_token}),
        call_next,
    ))
    assert incomplete.status_code == 403
    unrelated = asyncio.run(middleware.dispatch(
        request_for("/api/tasks/42/lease", {
            "X-BACH-Result-Service-ID": service_id,
            "X-BACH-Result-Service": service_token,
        }),
        call_next,
    ))
    assert unrelated.status_code == 403
    allowed = asyncio.run(middleware.dispatch(
        request_for("/api/tasks/42/result", {
            "X-BACH-Result-Service-ID": service_id,
            "X-BACH-Result-Service": service_token,
        }),
        call_next,
    ))
    assert allowed == "passed"


def test_api_capabilities_history_cas_correction_and_context(api_review):
    server, conn, task_id, client, submitted, read_token, correction_token = api_review
    read_only = asyncio.run(server.read_task_result(task_id, _request(read_token)))
    assert read_only["operator_capabilities"] == {
        "accept_result": True,
        "request_correction": False,
    }
    writable = asyncio.run(server.read_task_result(task_id, _request(correction_token)))
    assert writable["operator_capabilities"]["request_correction"] is True
    assert writable["result"]["result_id"] == submitted["result_id"]

    payload = {
        "result_id": submitted["result_id"],
        "result_sha256": submitted["result_sha256"],
        "generation": submitted["generation"],
        "fence": submitted["fence"],
        "task_version": submitted["task_version"],
        "status_revision": writable["status_revision"],
        "request_id": str(uuid.uuid4()),
        "correction_note": "Bitte Quellen und Grenzen ergänzen.",
    }
    stale = {**payload, "status_revision": payload["status_revision"] + 1}
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(server.request_task_result_correction(task_id, stale, _request(correction_token)))
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "result_changed_reload"
    assert client.task_snapshot(task_id)["status"] == "review"

    denied = {**payload, "request_id": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as permission:
        asyncio.run(server.request_task_result_correction(task_id, denied, _request(read_token)))
    assert permission.value.status_code == 403
    assert permission.value.detail["code"] == "result_operator_correction_scope_required"

    correction = asyncio.run(
        server.request_task_result_correction(task_id, payload, _request(correction_token))
    )
    assert correction["schema"] == "bach.task-result-correction-request.v1"
    assert correction["status"] == "pending" and correction["replayed"] is False
    history = asyncio.run(server.read_task_result_history(task_id, _request(), limit=50))
    assert history["schema"] == "bach.task-result-history.v1"
    assert any(
        event["type"] == "result_submitted"
        and event["result"]["result_id"] == submitted["result_id"]
        and event["result"]["text"] == "API-Ergebnis mit überprüfbaren Quellen"
        for event in history["events"]
    )
    assert any(event["type"] == "correction_requested" for event in history["events"])

    snapshot = client.task_snapshot(task_id)
    lease = client.acquire(
        task_id,
        worker_id="api-retry@HOST",
        host="HOST",
        task_version=snapshot["task_version"],
        result_generation="api-generation-2",
    )
    context = asyncio.run(server.read_task_correction_context(
        task_id,
        _request(lease_id=lease.lease_id),
        fence=lease.fence,
        task_version=lease.task_version,
        generation="api-generation-2",
    ))
    assert context["correction"]["source_result"]["result_id"] == submitted["result_id"]
    assert context["correction"]["source_result"]["result_sha256"] == submitted["result_sha256"]
    with pytest.raises(HTTPException) as wrong_generation:
        asyncio.run(server.read_task_correction_context(
            task_id, _request(lease_id=lease.lease_id), fence=lease.fence,
            task_version=lease.task_version, generation="wrong-generation",
        ))
    assert wrong_generation.value.status_code == 409
    assert wrong_generation.value.detail["code"] == "task_correction_context_unavailable"


def test_missing_correction_operator_table_is_403_without_schema_mutation(api_review):
    server, keeper, task_id, client, submitted, _read_token, correction_token = api_review
    readback = asyncio.run(server.read_task_result(task_id, _request(correction_token)))
    payload = {
        "result_id": submitted["result_id"],
        "result_sha256": submitted["result_sha256"],
        "generation": submitted["generation"],
        "fence": submitted["fence"],
        "task_version": submitted["task_version"],
        "status_revision": readback["status_revision"],
        "request_id": str(uuid.uuid4()),
        "correction_note": "Bitte Belege und Grenzen ergänzen.",
    }
    keeper.execute("DROP TABLE task_result_operators")
    keeper.commit()
    before_schema = tuple(keeper.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ))
    before_task = tuple(keeper.execute(
        "SELECT id,status,title,description,claim_id,claim_fence FROM tasks WHERE id=?", (task_id,)
    ).fetchone())
    before_result = tuple(keeper.execute(
        "SELECT id,task_id,fence,generation,task_version,result_sha256,submission_event_id "
        "FROM worker_task_results WHERE task_id=?", (task_id,)
    ).fetchone())

    with pytest.raises(HTTPException) as denied:
        asyncio.run(server.request_task_result_correction(task_id, payload, _request(correction_token)))

    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "result_operator_correction_scope_required"
    assert tuple(keeper.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    )) == before_schema
    assert tuple(keeper.execute(
        "SELECT id,status,title,description,claim_id,claim_fence FROM tasks WHERE id=?", (task_id,)
    ).fetchone()) == before_task
    assert tuple(keeper.execute(
        "SELECT id,task_id,fence,generation,task_version,result_sha256,submission_event_id "
        "FROM worker_task_results WHERE task_id=?", (task_id,)
    ).fetchone()) == before_result
    assert not any(row[1] == "task_result_corrections" for row in before_schema)


def test_correction_context_get_does_not_migrate_missing_lease_columns(api_review):
    server, keeper, _review_task_id, client, _submitted, _read_token, _correction_token = api_review
    from system.tests.test_task_lease_client import _insert_task

    task_id = _insert_task(keeper, title="Context ohne vollständige Lease-Spalten", status="open")
    snapshot = client.task_snapshot(task_id)
    lease = client.acquire(
        task_id, worker_id="api-context@HOST", host="HOST",
        task_version=snapshot["task_version"], result_generation="context-no-ddl",
    )
    keeper.execute("ALTER TABLE tasks DROP COLUMN claim_task_version")
    keeper.commit()
    before_schema = tuple(keeper.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ))
    before_columns = tuple(row[1] for row in keeper.execute("PRAGMA table_info(tasks)"))

    with pytest.raises(HTTPException) as denied:
        asyncio.run(server.read_task_correction_context(
            task_id, _request(lease_id=lease.lease_id), fence=lease.fence,
            task_version=lease.task_version, generation="context-no-ddl",
        ))

    assert denied.value.status_code == 409
    assert denied.value.detail["code"] == "task_correction_context_unavailable"
    assert tuple(keeper.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    )) == before_schema
    assert tuple(row[1] for row in keeper.execute("PRAGMA table_info(tasks)")) == before_columns
    assert "claim_task_version" not in before_columns


def test_history_index_gap_returns_unavailable_without_read_side_schema_write(api_review):
    server, keeper, task_id, _client, _submitted, _read_token, _correction_token = api_review
    keeper.execute("DROP INDEX idx_task_history_task_action_id")
    keeper.commit()

    with pytest.raises(HTTPException) as unavailable:
        asyncio.run(server.read_task_result_history(task_id, _request(), limit=20))
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail["code"] == "result_history_unavailable"
    assert keeper.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_task_history_task_action_id'"
    ).fetchone() is None


def test_existing_v1_history_fixture_is_canonical_and_retains_original_bytes(monkeypatch):
    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device-token")
    calls = []

    def fake_request(method, path, payload=None, headers=None):
        calls.append((method, path, payload, headers))
        return 200, RESULT_HISTORY_V1_FIXTURE

    monkeypatch.setattr(client, "_http_request", fake_request)
    result = client.task_result_history(42001, limit=2)
    assert result == RESULT_HISTORY_V1_FIXTURE
    assert calls == [("GET", "/api/tasks/42001/result/history?limit=2", None, None)]
    historical = result["events"][1]["result"]
    assert historical["result_id"] == 59
    assert historical["text"] == _V1_TEXT
    assert historical["result_sha256"] == _V1_SHA



def test_native_naive_v1_timestamp_is_normalized_with_lease_parser(api_review):
    server, keeper, task_id, _client, submitted, _read_token, _correction_token = api_review
    from hub._services.task_lease import _fmt, parse_ts

    raw_timestamp = "2026-10-12T14:44:25.607630"
    keeper.execute("UPDATE worker_task_results SET submitted_at=? WHERE id=?",
                   (raw_timestamp, submitted["result_id"]))
    keeper.commit()

    history = asyncio.run(server.read_task_result_history(task_id, _request(), limit=20))
    event = next(item for item in history["events"]
                 if item["type"] == "result_submitted")
    assert event["occurred_at"] == _fmt(parse_ts(raw_timestamp))
    assert event["occurred_at"].endswith("Z")
    assert event["result"]["text"] == submitted["result"]


def test_task_capabilities_are_explicit_before_create_and_nullable_detail_is_stable():
    import gui.server as server
    from hub._services.task_lease import task_content_version

    expected = {
        "schema": "bach.task-capabilities.v1",
        "result_max_chars": {
            "supported": True,
            "min": 1,
            "max": 3000,
            "nullable": True,
        },
    }
    assert asyncio.run(server.get_task_capabilities()) == expected

    route_paths = [route.path for route in server.app.router.routes if hasattr(route, "path")]
    assert "/api/task-capabilities" in route_paths

    from gui.api import headless
    assert asyncio.run(headless.get_task_capabilities()) == expected
    headless_paths = [route.path for route in headless.app.router.routes if hasattr(route, "path")]
    assert "/api/v1/task-capabilities" in headless_paths

    legacy_row = {
        "id": 42002,
        "title": "Unbegrenzter Alt-Task",
        "description": "Vorhandener Auftrag",
        "status": "pending",
        "priority": "P2",
        "category": "SYSTEM",
    }
    legacy_version = task_content_version(legacy_row)
    nullable_version = task_content_version({**legacy_row, "result_max_chars": None})
    projected = server._public_task_snapshot(legacy_row)
    assert legacy_version == nullable_version
    assert projected["task_version"] == legacy_version
    assert "result_max_chars" in projected
    assert projected["result_max_chars"] is None


def test_task_capabilities_reject_noncanonical_contract():
    from hub._services.task_lease_client import LeaseProtocolError

    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device-token")
    calls = []
    expected = {
        "schema": "bach.task-capabilities.v1",
        "result_max_chars": {
            "supported": True,
            "min": 1,
            "max": 3000,
            "nullable": True,
        },
    }

    def fake_request(method, path, payload=None, headers=None):
        calls.append((method, path, payload, headers))
        return 200, expected

    client._http_request = fake_request
    assert client.task_capabilities() == expected
    assert calls == [("GET", "/api/task-capabilities", None, None)]

    expected["result_max_chars"]["max"] = 3001
    with pytest.raises(LeaseProtocolError):
        client.task_capabilities()

def test_correction_dto_is_optional_but_strict_on_create_and_edit():
    from pydantic import ValidationError
    from gui.server import TaskCreate as GuiTaskCreate, TaskUpdate as GuiTaskUpdate
    from gui.api.headless import TaskCreate as HeadlessTaskCreate, TaskUpdate as HeadlessTaskUpdate

    for create_model in (GuiTaskCreate, HeadlessTaskCreate):
        assert create_model(title="Task ohne Limit").result_max_chars is None
        assert create_model(title="Task mit Limit", result_max_chars=120).result_max_chars == 120
        with pytest.raises(ValidationError):
            create_model(title="Ungültig", result_max_chars=True)
    for update_model in (GuiTaskUpdate, HeadlessTaskUpdate):
        assert update_model().result_max_chars is None
        assert update_model(result_max_chars=80).result_max_chars == 80
        with pytest.raises(ValidationError):
            update_model(result_max_chars="80")

def test_capability_discovery_routes_keep_device_and_headless_auth(monkeypatch):
    import gui.server as server
    from gui.api import headless
    from starlette.requests import Request
    from starlette.responses import Response

    def request(path, headers=()):
        encoded = [(name.lower().encode("latin-1"), value.encode("latin-1"))
                   for name, value in headers]
        return Request({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": path,
            "raw_path": path.encode("ascii"), "query_string": b"",
            "headers": encoded, "client": ("192.0.2.42", 50000),
            "server": ("bach.example", 80),
        })

    async def next_handler(_request):
        return Response(status_code=204)

    assert "/api/task-capabilities" not in server.DeviceAuthMiddleware.EXEMPT_API_PATHS
    middleware = server.DeviceAuthMiddleware(app=lambda _scope, _receive, _send: None)
    missing = asyncio.run(middleware.dispatch(request("/api/task-capabilities"), next_handler))
    assert missing.status_code == 401

    monkeypatch.setattr(server, "validate_token", lambda _token: None)
    invalid = asyncio.run(middleware.dispatch(
        request("/api/task-capabilities", (("Authorization", "Bearer invalid"),)),
        next_handler,
    ))
    assert invalid.status_code == 401

    device = {"device_id": "fixture-device"}
    monkeypatch.setattr(server, "validate_token", lambda _token: device)
    authorized = asyncio.run(middleware.dispatch(
        request("/api/task-capabilities", (("Authorization", "Bearer valid"),)),
        next_handler,
    ))
    assert authorized.status_code == 204

    monkeypatch.setattr(headless, "_verify_api_key", lambda _key: False)
    monkeypatch.setattr(headless, "_verify_api_key", lambda _key: False)
    headless_route = next(
        route for route in headless.app.routes
        if getattr(route, "path", None) == "/api/v1/task-capabilities"
    )
    assert any(dependency.call is headless.verify_auth
               for dependency in headless_route.dependant.dependencies)
    remote = request("/api/v1/task-capabilities")
    with pytest.raises(HTTPException) as missing_headless:
        asyncio.run(headless.verify_auth(remote, api_key=None))
    assert missing_headless.value.status_code == 401

    monkeypatch.setattr(headless, "_verify_api_key", lambda _key: False)
    bad_key = request("/api/v1/task-capabilities", (("X-BACH-Key", "invalid"),))
    with pytest.raises(HTTPException) as invalid_headless:
        asyncio.run(headless.verify_auth(bad_key, api_key=None))
    assert invalid_headless.value.status_code == 401

    monkeypatch.setattr(headless, "_verify_api_key", lambda _key: True)
    valid_key = request("/api/v1/task-capabilities", (("X-BACH-Key", "valid"),))
    assert asyncio.run(headless.verify_auth(valid_key, api_key=None)) is True
