# SPDX-License-Identifier: MIT
"""Thin adapter tests with native temporary scheduler state and no executor calls."""

import hashlib
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gui.api import agent_triggers as api


def app_client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


@pytest.fixture
def native(tmp_path, monkeypatch):
    module = pytest.importorskip("ellmos_scheduler")
    if not hasattr(module, "AgentTriggers"):
        pytest.skip("native provider with shared trigger contract required")
    db = tmp_path / "scheduler" / "state.db"
    store = module.SchedulerStore(db)
    store.init()  # explicit deployment preparation, never performed by API
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(db))
    monkeypatch.setattr(
        api.scheduler_provider,
        "probe_scheduler_provider",
        lambda: SimpleNamespace(external=True),
    )
    monkeypatch.setattr(
        api.scheduler_provider, "load_external_scheduler", lambda: module
    )
    monkeypatch.setattr(api, "_authorize", lambda request: None)
    monkeypatch.setattr(
        module.SchedulerStore,
        "init",
        lambda self: pytest.fail("API must not initialize"),
    )
    return module, store, app_client()


def definition(identifier="shared-1", **values):
    return {
        "id": identifier,
        "agent_id": "worker@host",
        "expected_version": 0,
        "schedule": {"kind": "once", "at": "2026-12-01T12:00:00Z"},
        "executor": "noop",
        "payload": {"message": "synthetic"},
        **values,
    }


def test_unavailable_and_old_provider_do_not_construct_state(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_authorize", lambda request: None)
    monkeypatch.setenv(
        "BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "missing" / "state.db")
    )
    monkeypatch.setattr(
        api.scheduler_provider,
        "probe_scheduler_provider",
        lambda: SimpleNamespace(external=False),
    )
    client = app_client()
    assert client.get("/api/agent-triggers").status_code == 503
    monkeypatch.setattr(
        api.scheduler_provider,
        "probe_scheduler_provider",
        lambda: SimpleNamespace(external=True),
    )
    monkeypatch.setattr(
        api.scheduler_provider, "load_external_scheduler", lambda: SimpleNamespace()
    )
    response = client.post("/api/agent-triggers", json=definition())
    assert response.status_code == 503
    assert response.json()["detail"]["state"] == "unavailable"
    assert not (tmp_path / "missing").exists()


def test_native_shared_crud_cas_tombstone_and_configuration_only(native):
    _module, store, client = native
    response = client.post("/api/agent-triggers", json=definition())
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["schema"] == api.SCHEMA and saved["provider"] == "ellmos-scheduler"
    assert saved["trigger"]["enabled"] is False
    assert saved["trigger"]["version"] == 1
    assert saved["ack"] == {
        "configuration_saved": True,
        "readback_verified": True,
        "worker_started": False,
    }
    assert (
        client.get("/api/agent-triggers/shared-1").json()["trigger"] == saved["trigger"]
    )
    assert client.get("/api/agent-triggers?agent_id=worker@host").json()[
        "triggers"
    ] == [saved["trigger"]]
    assert client.get("/api/agent-triggers?agent_id=other").json()["triggers"] == []
    assert (
        client.put(
            "/api/agent-triggers/shared-1",
            json={"expected_version": 2, "changes": {"enabled": True}},
        ).status_code
        == 409
    )
    changed = client.put(
        "/api/agent-triggers/shared-1",
        json={"expected_version": 1, "changes": {"enabled": True}},
    )
    assert changed.json()["trigger"]["version"] == 2
    deleted = client.request(
        "DELETE", "/api/agent-triggers/shared-1", json={"expected_version": 2}
    )
    assert deleted.json()["trigger"]["deleted"] is True
    assert deleted.json()["trigger"]["version"] == 3
    assert client.get("/api/agent-triggers").json()["triggers"] == []
    assert (
        client.get("/api/agent-triggers/shared-1").json()["trigger"]["deleted"] is True
    )
    assert client.post("/api/agent-triggers", json=definition()).status_code == 409
    assert store.recent_runs() == []


@pytest.mark.parametrize(
    "change",
    [
        {"expected_version": True},
        {"expected_version": 1},
        {"token": "private"},
        {"payload": {"nested": [{"api_key": "private"}]}},
        {"executor": "not-registered"},
        {"id": "../path"},
        {"agent_id": "contains space"},
        {"enabled": "true"},
    ],
)
def test_rejects_credentials_unknown_fields_versions_and_ids(native, change):
    _, store, client = native
    assert (
        client.post("/api/agent-triggers", json=definition(**change)).status_code == 400
    )
    assert store.list_jobs() == []


def test_missing_store_get_and_post_never_create_or_migrate(
    native, monkeypatch, tmp_path
):
    _, _, client = native
    path = tmp_path / "missing" / "state.db"
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(path))
    assert client.get("/api/agent-triggers").status_code == 503
    assert client.post("/api/agent-triggers", json=definition()).status_code == 503
    assert not path.parent.exists()
    old = tmp_path / "old.db"
    with sqlite3.connect(old) as conn:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
    before = old.read_bytes()
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(old))
    assert client.get("/api/agent-triggers").status_code == 503
    assert client.post("/api/agent-triggers", json=definition()).status_code == 503
    assert old.read_bytes() == before


def test_readback_race_is_not_success_and_never_retries(native, monkeypatch):
    module, _, client = native
    original = module.AgentTriggers.get
    calls = []

    def raced(self, identifier):
        calls.append(identifier)
        return {**original(self, identifier), "version": 50}

    monkeypatch.setattr(module.AgentTriggers, "get", raced)
    result = client.post("/api/agent-triggers", json=definition())
    assert result.status_code == 503
    assert result.json()["detail"]["reason_code"] == "readback_unverified"
    assert calls == ["shared-1"]


@pytest.mark.parametrize("lineage", [None, [], ["previous-trigger"]])
def test_event_delivery_reads_materialized_job_and_deduplicates_across_revisions(
    native,
    lineage,
):
    _, store, client = native
    config = definition(schedule={"kind": "event", "event_type": "task.accepted"})
    assert client.post("/api/agent-triggers", json=config).status_code == 200
    event = {
        "expected_version": 1,
        "event_id": "event-1",
        "event_type": "task.accepted",
        "source": "explicit-api",
        "lineage": lineage,
    }
    first = client.post("/api/agent-triggers/shared-1/deliver", json=event)
    assert first.status_code == 200, first.text
    assert first.json()["delivery"]["state"] == "materialized"
    assert first.json()["ack"]["worker_started"] is False
    assert first.json()["trigger"]["version"] == 1
    job_id = first.json()["delivery"]["job_id"]
    update = {
        "expected_version": 1,
        "changes": {"payload": {"message": "new revision"}},
    }
    assert client.put("/api/agent-triggers/shared-1", json=update).status_code == 200
    duplicate = client.post(
        "/api/agent-triggers/shared-1/deliver", json={**event, "expected_version": 2}
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["delivery"] == {
        "job_id": job_id,
        "duplicate": True,
        "state": "materialized",
    }
    assert len(store.list_jobs()) == 1 and store.recent_runs() == []


def test_route_auth_requires_device_or_browser_session_and_never_returns_token(
    tmp_path, monkeypatch
):
    from gui.api import unified_api

    db = tmp_path / "auth.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            "CREATE TABLE devices(id INTEGER,token_hash TEXT,status TEXT);"
            "CREATE TABLE browser_sessions(session_hash TEXT,device_id INTEGER,expires_at TEXT);"
        )
        conn.execute(
            "INSERT INTO devices VALUES(1,?,'active')",
            (hashlib.sha256(b"device-secret").hexdigest(),),
        )
        conn.execute(
            "INSERT INTO browser_sessions VALUES(?,1,'2099-01-01')",
            (hashlib.sha256(b"browser-secret").hexdigest(),),
        )
    monkeypatch.setattr(unified_api, "BACH_DB", db)
    monkeypatch.setattr(
        api, "_execute", lambda *args, **kwargs: api._response(triggers=[])
    )
    client = app_client()
    assert client.get("/api/agent-triggers").status_code == 401
    assert client.get("/api/agent-triggers?token=device-secret").status_code == 401
    assert (
        client.get(
            "/api/agent-triggers", headers={"Authorization": "Bearer revoked"}
        ).status_code
        == 403
    )
    for headers in (
        {"Authorization": "Bearer device-secret"},
        {"Cookie": "bach_device_token=browser-secret"},
    ):
        response = client.get("/api/agent-triggers", headers=headers)
        assert response.status_code == 200
        assert "secret" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/agent-triggers",
        "/api/agent-triggers/shared-1",
        "/api/agent-triggers/shared-1/deliver",
    ],
)
def test_production_middleware_device_prefix_and_cross_origin(path, monkeypatch):
    import asyncio

    from gui import server
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    seen = []

    async def handler(request):
        seen.append(request)
        return PlainTextResponse("authorized")

    def request(headers=()):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "scheme": "http",
                "server": ("127.0.0.1", 8000),
                "client": ("127.0.0.1", 12345),
                "query_string": b"",
                "headers": [(b"host", b"127.0.0.1:8000"), *headers],
            }
        )

    monkeypatch.setattr(
        server, "validate_token", lambda token: {"id": 1} if token == "device" else None
    )
    middleware = server.DeviceAuthMiddleware(server.app)
    assert asyncio.run(middleware.dispatch(request(), handler)).status_code == 401
    assert (
        asyncio.run(
            middleware.dispatch(
                request([(b"authorization", b"Bearer invalid")]), handler
            )
        ).status_code
        == 403
    )
    assert (
        asyncio.run(
            middleware.dispatch(
                request(
                    [
                        (b"authorization", b"Bearer device"),
                        (b"origin", b"https://other.invalid"),
                    ]
                ),
                handler,
            )
        ).status_code
        == 403
    )
    assert seen == []
    assert (
        asyncio.run(
            middleware.dispatch(
                request([(b"authorization", b"Bearer device")]), handler
            )
        ).status_code
        == 200
    )
    assert len(seen) == 1


def test_production_prefix_does_not_match_lookalikes(monkeypatch):
    import asyncio

    from gui import server
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    monkeypatch.setattr(server, "validate_token", lambda token: None)

    async def handler(request):
        return PlainTextResponse("should not pass")

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/agent-triggers-other",
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"authorization", b"Bearer invalid"),
        ],
    }
    # The generic device branch returns 401, the exact trigger branch returns 403.
    assert (
        asyncio.run(
            server.DeviceAuthMiddleware(server.app).dispatch(Request(scope), handler)
        ).status_code
        == 401
    )
    assert any(
        getattr(route, "path", "") == "/api/agent-triggers"
        for route in server.app.routes
    )


@pytest.mark.parametrize("authorization", ["Bearer transported-secret", None])
def test_transport_token_never_persisted_inside_arbitrary_payload(
    native, authorization
):
    _, store, client = native
    headers = (
        {"Authorization": authorization}
        if authorization
        else {"Cookie": "bach_device_token=transported-secret"}
    )
    result = client.post(
        "/api/agent-triggers",
        headers=headers,
        json=definition(payload={"message": "prefix transported-secret suffix"}),
    )
    assert result.status_code == 400
    assert "transported-secret" not in result.text
    assert store.list_jobs() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": True},
        {"expected_version": True},
        {"changes": {"unknown": True}},
        {"changes": {"enabled": "yes"}},
    ],
)
def test_update_rejects_unknown_or_invalid_fields_without_mutation(native, changes):
    _, _, client = native
    original = client.post("/api/agent-triggers", json=definition()).json()["trigger"]
    body = {"expected_version": 1, "changes": {"enabled": True}, **changes}
    assert client.put("/api/agent-triggers/shared-1", json=body).status_code == 400
    assert client.get("/api/agent-triggers/shared-1").json()["trigger"] == original


def test_provider_snapshot_credentials_are_not_exposed(native, monkeypatch):
    module, _, client = native
    saved = client.post("/api/agent-triggers", json=definition()).json()["trigger"]
    monkeypatch.setattr(
        module.AgentTriggers,
        "get",
        lambda *args: {**saved, "payload": {"token": "private-value"}},
    )
    response = client.get("/api/agent-triggers/shared-1")
    assert response.status_code == 503
    assert "private-value" not in response.text


def test_unknown_id_and_request_shape_are_safe(native):
    _, _, client = native
    assert client.get("/api/agent-triggers/missing").status_code == 404
    assert (
        client.post(
            "/api/agent-triggers/shared-1/deliver", json={"expected_version": 1}
        ).status_code
        == 400
    )
    assert (
        client.request(
            "DELETE",
            "/api/agent-triggers/shared-1",
            json={"expected_version": 1, "unknown": True},
        ).status_code
        == 400
    )


@pytest.mark.parametrize("body", ["sensitive-input", ["sensitive-input"], False, 42])
def test_nonobject_bodies_fail_without_echoing_content(native, body):
    _, store, client = native
    for method, path in [
        ("POST", "/api/agent-triggers"),
        ("PUT", "/api/agent-triggers/shared-1"),
        ("DELETE", "/api/agent-triggers/shared-1"),
        ("POST", "/api/agent-triggers/shared-1/deliver"),
    ]:
        response = client.request(method, path, json=body)
        assert response.status_code == 400
        assert "sensitive-input" not in response.text
    assert store.list_jobs() == []


@pytest.mark.parametrize("identifier", ["a/b", "a/deliver", "a/b/deliver"])
def test_native_slash_ids_share_exact_crud_and_delivery_identity(native, identifier):
    from urllib.parse import quote

    _, store, client = native
    agent = "agents/worker@host"
    body = definition(
        identifier=identifier,
        agent_id=agent,
        schedule={"kind": "event", "event_type": "task.accepted"},
    )
    created = client.post("/api/agent-triggers", json=body)
    assert created.status_code == 200, created.text
    assert created.json()["trigger"]["id"] == identifier
    path = "/api/agent-triggers/" + quote(identifier, safe="")
    assert client.get(path).json()["trigger"]["id"] == identifier
    listed = client.get("/api/agent-triggers", params={"agent_id": agent}).json()[
        "triggers"
    ]
    assert len(listed) == 1 and listed[0]["id"] == identifier
    changed = client.put(
        path, json={"expected_version": 1, "changes": {"enabled": True}}
    )
    assert changed.status_code == 200 and changed.json()["trigger"]["id"] == identifier
    delivered = client.post(
        path + "/deliver",
        json={
            "expected_version": 2,
            "event_id": "event/slash",
            "event_type": "task.accepted",
            "source": "explicit/api",
        },
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["trigger"]["id"] == identifier
    assert len(store.list_jobs()) == 1
    deleted = client.request("DELETE", path, json={"expected_version": 2})
    assert deleted.status_code == 200
    assert (
        deleted.json()["trigger"]["id"] == identifier
        and deleted.json()["trigger"]["deleted"]
    )
    assert client.get(path).json()["trigger"]["deleted"] is True
    assert store.recent_runs() == []


@pytest.fixture
def authenticated_native(tmp_path, monkeypatch):
    """Native store and real device/session authorization; synthetic credentials only."""
    from gui.api import unified_api

    module = pytest.importorskip("ellmos_scheduler")
    store = module.SchedulerStore(tmp_path / "scheduler.db")
    store.init()
    auth_db = tmp_path / "auth.db"
    with closing(sqlite3.connect(auth_db)) as conn:
        conn.executescript(
            "CREATE TABLE devices(id INTEGER,token_hash TEXT,status TEXT);"
            "CREATE TABLE browser_sessions(session_hash TEXT,device_id INTEGER,expires_at TEXT);"
        )
        conn.execute(
            "INSERT INTO devices VALUES(1,?,'active')",
            (hashlib.sha256(b"synthetic-device-secret").hexdigest(),),
        )
        conn.execute(
            "INSERT INTO browser_sessions VALUES(?,1,'2099-01-01')",
            (hashlib.sha256(b"synthetic-browser-secret").hexdigest(),),
        )
        conn.commit()
    monkeypatch.setattr(unified_api, "BACH_DB", auth_db)
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(store.path))
    monkeypatch.setattr(api.scheduler_provider, "probe_scheduler_provider", lambda: SimpleNamespace(external=True))
    monkeypatch.setattr(api.scheduler_provider, "load_external_scheduler", lambda: module)
    monkeypatch.setattr(module.SchedulerStore, "init", lambda self: pytest.fail("API must not initialize"))
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        yield module, store, client


@pytest.mark.parametrize("transport", ["device-cookie", "browser-cookie", "bearer"])
@pytest.mark.parametrize("padding", ["", " ", "  "])
@pytest.mark.parametrize("as_key", [False, True])
def test_canonical_auth_credentials_cannot_be_persisted_as_keys_or_values(
    authenticated_native, transport, padding, as_key
):
    _, store, client = authenticated_native
    secret = "synthetic-browser-secret" if transport == "browser-cookie" else "synthetic-device-secret"
    headers = (
        {"Authorization": f"Bearer {padding}{secret}{padding}"}
        if transport == "bearer" else
        {"Cookie": f'bach_device_token="{padding}{secret}{padding}"'}
    )
    # Demonstrate that this exact padded credential really authenticates.
    assert client.get("/api/agent-triggers", headers=headers).status_code == 200
    payload = {secret: "note"} if as_key else {"note": f"prefix {secret} suffix"}
    response = client.post("/api/agent-triggers", headers=headers, json=definition(payload={"nested": [payload]}))
    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "credential_in_payload"
    assert secret not in response.text
    assert store.list_jobs() == []
    assert client.get("/api/agent-triggers", headers=headers).json()["triggers"] == []


def test_all_mutation_bodies_reject_auth_secret_before_native_state_changes(authenticated_native):
    _, store, client = authenticated_native
    secret = "synthetic-device-secret"
    headers = {"Cookie": f'bach_device_token=" {secret} "'}
    created = client.post(
        "/api/agent-triggers", headers=headers,
        json=definition(schedule={"kind": "event", "event_type": "task.accepted"}),
    ).json()["trigger"]
    attempts = [
        ("PUT", "/api/agent-triggers/shared-1", {"expected_version": 1, "changes": {"payload": {secret: "note"}}}),
        ("DELETE", "/api/agent-triggers/shared-1", {"expected_version": 1, "note": secret}),
        ("POST", "/api/agent-triggers/shared-1/deliver", {
            "expected_version": 1, "event_id": "event-1", "event_type": "task.accepted", "source": secret,
        }),
    ]
    for method, path, body in attempts:
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code == 400
        assert response.json()["detail"]["reason_code"] == "credential_in_payload"
        assert secret not in response.text
        assert client.get("/api/agent-triggers/shared-1", headers=headers).json()["trigger"] == created
    assert store.list_jobs() == [] and store.recent_runs() == []


@pytest.mark.parametrize("as_key", [False, True])
def test_preexisting_native_snapshot_cannot_echo_auth_secret_or_success_ack(authenticated_native, as_key):
    module, store, client = authenticated_native
    secret = "synthetic-device-secret"
    leaked = {secret: "note"} if as_key else {"note": secret}
    # Model already-persisted provider data, without bypassing route authentication.
    module.AgentTriggers(store).create(
        "existing", agent_id="worker", schedule={"kind": "once", "at": "2026-12-01T12:00:00Z"},
        executor="noop", payload={"nested": [leaked]},
    )
    headers = {"Authorization": f"Bearer  {secret} "}
    for method, path, body in [
        ("GET", "/api/agent-triggers", None),
        ("GET", "/api/agent-triggers/existing", None),
        ("PUT", "/api/agent-triggers/existing", {"expected_version": 1, "changes": {"enabled": True}}),
        ("DELETE", "/api/agent-triggers/existing", {"expected_version": 2}),
    ]:
        response = client.request(method, path, headers=headers, **({"json": body} if body is not None else {}))
        assert response.status_code == 503
        assert response.json()["detail"]["reason_code"] == "credential_in_response"
        assert secret not in response.text
        assert "ack" not in response.json()
    assert store.recent_runs() == []
