"""HTTP contract tests using isolated device/blueprint SQLite data and the real composer."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from gui.api import gui_capabilities, subscription_agents_transport, unified_api
from hub import bach_paths, subscription_agents
from hub._services.subscription_agents_composer import (
    MAX_REQUEST_BYTES,
    PREVIEW_SCHEMA,
    REQUEST_SCHEMA,
)


API_PATH = "/api/agent-studio/subscription-agents/compose"
ACTIVE_TOKEN = "active-device-token-fixture-only"
REVOKED_TOKEN = "revoked-device-token-fixture-only"


def _create_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE devices (id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL, status TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO devices (id, token_hash, status) VALUES (?, ?, ?)",
            [
                (1, hashlib.sha256(ACTIVE_TOKEN.encode("utf-8")).hexdigest(), "active"),
                (2, hashlib.sha256(REVOKED_TOKEN.encode("utf-8")).hexdigest(), "revoked"),
            ],
        )
        conn.execute(
            """CREATE TABLE agent_blueprints (
                id INTEGER PRIMARY KEY, name TEXT, title TEXT, persona_role TEXT,
                persona_prompt TEXT, skills_json TEXT, contractus_json TEXT,
                animus_type TEXT, modus TEXT, governance_json TEXT,
                kind TEXT, version INTEGER
            )"""
        )
        conn.execute(
            """INSERT INTO agent_blueprints (
                id, name, title, persona_role, persona_prompt, skills_json,
                contractus_json, animus_type, modus, governance_json, kind, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                7,
                "research_helper",
                "Recherchehilfe",
                "Recherche",
                "Prüfe Quellen sorgfältig und benenne Unsicherheiten.",
                "[]",
                '{"turns":12,"cooldown_seconds":20}',
                "subscription",
                "casualis",
                '{"profile":"fail_closed_standard","tool_whitelist":["read_file"]}',
                "agent",
                3,
            ),
        )
        conn.commit()


def _request(**changes) -> dict:
    value = {
        "schema": REQUEST_SCHEMA,
        "target_client": {
            "client_id": "unregistered-demo-client",
            "host": "test-host",
            "name": "Vorschauziel",
        },
        "blueprint": {"id": 7, "version": 3},
        "selected_skill_ids": ["task-notes"],
        "user_task": "Erstelle eine begrenzte Vorschau mit echten Umlauten.",
        "task_refs": [],
        "task_selection_rule": "",
        "governance": {"scope": "BACH", "policy_query": "", "decision_query": ""},
    }
    value.update(changes)
    return value


def _auth(token: str = ACTIVE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def http_client(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "bach.db"
    _create_db(db_path)
    skills_root = tmp_path / "skills"
    skill_path = skills_root / "task-notes" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: Task Notes\nversion: 1.4.2\ndescription: Geprüfte Testquelle\n---\n"
        "Prüfe Belege und verwende echte Umlaute.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(bach_paths, "BACH_DB", db_path)
    monkeypatch.setattr(unified_api, "BACH_DB", db_path)
    monkeypatch.setenv("BACH_USER_SKILLS_ROOT", str(skills_root))
    monkeypatch.setenv("BACH_SKILLS_ROOTS", json.dumps([str(skills_root)]))
    monkeypatch.setenv("BACH_POLICY_REGISTRY_ENABLED", "0")

    app = FastAPI()
    app.include_router(subscription_agents_transport.router)
    with TestClient(app) as client:
        yield client, db_path, skill_path


def test_http_and_existing_cli_use_the_same_real_composer_and_sources(http_client, tmp_path):
    client, db_path, skill_path = http_client
    request = _request()
    request_path = tmp_path / "compose-request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    handler = subscription_agents.SubscriptionAgentsHandler(tmp_path)
    ok, cli_output = handler.handle("compose", [str(request_path)])
    assert ok is True

    response = client.post(API_PATH, json=request, headers=_auth())
    assert response.status_code == 200
    result = response.json()
    assert result == json.loads(cli_output)
    assert result["schema"] == PREVIEW_SCHEMA
    assert result["status"] == "needs_sources"  # Policy source is deliberately disabled in this test.
    assert result["blueprint"]["version"] == 3
    assert "Erstelle eine begrenzte Vorschau mit echten Umlauten." in result["prompt"]
    assert "Prüfe Belege und verwende echte Umlaute." in result["prompt"]
    assert any(
        item["id"] == "skill:task-notes"
        and item["state"] == "included"
        and item["sha256"] == hashlib.sha256(skill_path.read_bytes()).hexdigest()
        for item in result["sources"]
    )
    assert result["actions"] == {
        "agent_started": False,
        "task_claimed": False,
        "queue_scanned": False,
        "clipboard_written": False,
    }
    assert result["limits"]["governance_enforcement_verified"] is False
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_missing_or_revoked_device_fails_before_body_read_and_capability_labels_do_not_grant_access(
    http_client, monkeypatch
):
    client, _, _ = http_client
    stream_calls = []
    original_stream = StarletteRequest.stream

    async def tracked_stream(request):
        stream_calls.append(True)
        async for chunk in original_stream(request):
            yield chunk

    monkeypatch.setattr(StarletteRequest, "stream", tracked_stream)
    large_invalid_body = b"{" + b"x" * (MAX_REQUEST_BYTES + 1)
    missing_responses = [
        client.post(
            API_PATH,
            content=large_invalid_body,
            headers={"Content-Type": "application/json", "X-BACH-Capability": "subscription_agents.compose"},
        ),
        client.post(
            f"{API_PATH}?token={ACTIVE_TOKEN}",
            content=large_invalid_body,
            headers={"Content-Type": "application/json"},
        ),
        client.post(
            API_PATH,
            content=large_invalid_body,
            headers={"Content-Type": "application/json", "X-Forwarded-For": "127.0.0.1"},
        ),
        client.post(
            API_PATH,
            content=large_invalid_body,
            headers={
                "Content-Type": "application/json",
                "X-Forwarded-For": "127.0.0.1",
                "X-BACH-Capability": "subscription_agents.compose",
            },
        ),
    ]
    assert [response.status_code for response in missing_responses] == [401] * 4
    assert stream_calls == []

    revoked = client.post(
        API_PATH,
        content=large_invalid_body,
        headers={**_auth(REVOKED_TOKEN), "Content-Type": "application/json"},
    )
    assert revoked.status_code == 403
    assert stream_calls == []
    assert all(ACTIVE_TOKEN not in response.text for response in [*missing_responses, revoked])
    assert all(REVOKED_TOKEN not in response.text for response in [*missing_responses, revoked])

    declaration = gui_capabilities.declaration(
        subscription_agents_transport.router.routes,
        kit={}, brand={}, modules={},
    )
    endpoint = next(item for item in declaration["endpoints"] if item["path"] == API_PATH)
    assert endpoint["auth"] == "device-token"
    assert endpoint["runtime_verified"] is False


def test_unreadable_device_database_fails_before_body_or_composer(http_client, tmp_path, monkeypatch):
    client, _, _ = http_client
    unreadable_db = tmp_path / "missing-parent" / "unreadable.db"
    monkeypatch.setattr(unified_api, "BACH_DB", unreadable_db)
    stream_calls = []
    composer_calls = []
    original_stream = StarletteRequest.stream

    async def tracked_stream(request):
        stream_calls.append(True)
        async for chunk in original_stream(request):
            yield chunk

    def tracked_composer():
        composer_calls.append(True)
        raise AssertionError("Composer must not be constructed before device authorization")

    monkeypatch.setattr(StarletteRequest, "stream", tracked_stream)
    monkeypatch.setattr(subscription_agents_transport, "SubscriptionAgentsComposer", tracked_composer)
    response = client.post(
        API_PATH,
        content=b"{}",
        headers={**_auth(), "Content-Type": "application/json"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "device_auth_unavailable"
    assert str(unreadable_db) not in response.text
    assert stream_calls == []
    assert composer_calls == []


def test_authorized_body_limits_and_json_shape_are_checked(http_client, monkeypatch):
    client, _, _ = http_client
    headers = {**_auth(), "Content-Type": "application/json"}

    oversized = client.post(API_PATH, content=b"x" * (MAX_REQUEST_BYTES + 1), headers=headers)
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "request_too_large"

    wrong_media_type = client.post(API_PATH, content=b"{}", headers={**_auth(), "Content-Type": "text/plain"})
    assert wrong_media_type.status_code == 415

    invalid_json = client.post(API_PATH, content=b"{invalid", headers=headers)
    assert invalid_json.status_code == 400

    duplicate_fields = (
        b'{"schema":"bach.subscription-agent-onboarding.request.v1",'
        b'"schema":"bach.subscription-agent-onboarding.request.v1"}'
    )
    duplicate = client.post(API_PATH, content=duplicate_fields, headers=headers)
    assert duplicate.status_code == 400

    non_object = client.post(API_PATH, content=b"[]", headers=headers)
    assert non_object.status_code == 422

    async def broken_stream(_request):
        raise RuntimeError("raw body error with private details")
        yield b""

    monkeypatch.setattr(StarletteRequest, "stream", broken_stream)
    body_error = client.post(API_PATH, content=b"{}", headers=headers)
    assert body_error.status_code == 400
    assert body_error.json()["detail"]["code"] == "body_unavailable"
    assert "private details" not in body_error.text


@pytest.mark.parametrize(
    "changes,secret_marker",
    [
        ({"schema": "wrong.schema.v9"}, None),
        ({"target_client": {"client_id": "bad/client", "host": "test-host"}}, None),
        ({"blueprint": {"id": 7, "version": 2}}, None),
        ({"user_task": 'api_key: "fixture-secret-value-not-for-response"'}, "fixture-secret-value-not-for-response"),
    ],
)
def test_composer_rejections_are_generic_and_never_return_a_prompt(http_client, changes, secret_marker, caplog):
    client, _, _ = http_client
    response = client.post(API_PATH, json=_request(**changes), headers=_auth())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "compose_rejected"
    assert "prompt" not in response.json()
    if secret_marker:
        assert secret_marker not in response.text
        assert secret_marker not in caplog.text


def test_missing_skill_is_reported_without_inserting_its_id_into_prompt(http_client):
    client, _, _ = http_client
    response = client.post(
        API_PATH,
        json=_request(selected_skill_ids=["missing-skill"]),
        headers=_auth(),
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "needs_sources"
    assert {item["reason"] for item in result["missing"] if item["kind"] == "skill"} == {"source_missing"}
    assert "missing-skill" not in result["prompt"]
    assert result["actions"]["agent_started"] is False
    assert result["actions"]["task_claimed"] is False


@pytest.fixture
def mounted_server(http_client, tmp_path, monkeypatch):
    """Exercise the actual consumer app, its mounted route and perimeter."""
    _, db_path, _ = http_client
    with sqlite3.connect(db_path) as conn:
        for name in ("name", "created_at", "revoked_at", "last_seen_at"):
            conn.execute(f"ALTER TABLE devices ADD COLUMN {name} TEXT")
        conn.execute("UPDATE devices SET name = 'synthetic-device-' || id")
    from gui import device_auth, server

    def connection():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(device_auth, "GET_CONNECTION", connection)
    monkeypatch.setattr(server, "BACH_DB", db_path)
    dist = tmp_path / "shared-dist"
    dist.mkdir()
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", dist)
    monkeypatch.setenv("ELLMOS_SYSTEM_GUI_DIST", str(dist))
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    try:
        yield client, db_path, dist, server
    finally:
        client.close()


def test_actual_consumer_mount_accepts_header_and_cookie_with_same_origin(mounted_server):
    client, db_path, _, server = mounted_server
    registered = [(route.path, getattr(route, "methods", set()))
                  for route in server.app.routes if getattr(route, "path", "") == API_PATH]
    assert len(registered) == 1 and "POST" in registered[0][1]
    request = _request(target_client={
        "client_id": "codex-cli", "host": "client-host",
        "workspace": "/tmp/Arbeitsfläche",
    })
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT * FROM agent_blueprints").fetchall()
    header = client.post(API_PATH, json=request, headers={
        **_auth(), "Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin",
    })
    assert header.status_code == 200
    client.cookies.set("bach_device_token", ACTIVE_TOKEN)
    cookie = client.post(API_PATH, json=request, headers={"Origin": "http://127.0.0.1:8000"})
    assert cookie.status_code == 200 and cookie.json() == header.json()
    assert cookie.json()["target_client"]["workspace"] == "/tmp/Arbeitsfläche"
    assert all(value is False for value in cookie.json()["actions"].values())
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT * FROM agent_blueprints").fetchall() == before


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer " + REVOKED_TOKEN},
    {**_auth(), "Origin": "https://foreign.example"},
    {**_auth(), "Sec-Fetch-Site": "cross-site"},
    {**_auth(), "Host": "foreign.example"},
])
def test_actual_consumer_denies_before_stream_or_composer(mounted_server, monkeypatch, headers):
    client, _, _, _ = mounted_server
    calls = []
    original = StarletteRequest.stream

    async def observed(request):
        calls.append("body")
        async for chunk in original(request):
            yield chunk

    def composer():
        calls.append("composer")
        raise AssertionError("Rejected request reached composer")

    monkeypatch.setattr(StarletteRequest, "stream", observed)
    monkeypatch.setattr(subscription_agents_transport, "SubscriptionAgentsComposer", composer)
    response = client.post(API_PATH, content=b"{", headers={
        "Content-Type": "application/json", **headers,
    })
    assert response.status_code in {401, 403}
    assert calls == []


def test_subscription_shell_is_static_public_and_has_no_legacy_fallback(mounted_server):
    client, _, dist, server = mounted_server
    page = "/agenten/subscription-agents"
    assert page in server.DeviceAuthMiddleware.PUBLIC_PAGE_PATHS
    missing = client.get(page)
    assert missing.status_code == 503
    target = dist / "agenten" / "subscription-agents.html"
    target.parent.mkdir()
    target.write_text("<!doctype html><title>Subscription-Agents</title>", encoding="utf-8")
    shown = client.get(page)
    assert shown.status_code == 200 and "Subscription-Agents" in shown.text
    target.unlink()
    outside = dist.parent / "foreign.html"
    outside.write_text("must-not-render", encoding="utf-8")
    target.symlink_to(outside)
    denied = client.get(page)
    assert denied.status_code == 503 and "must-not-render" not in denied.text


def test_subscription_page_requires_post_compose_and_never_claims_runtime_readiness(mounted_server):
    _, _, _, server = mounted_server
    declaration = gui_capabilities.declaration(
        server.app.routes, kit={}, brand={}, modules={},
    )
    page = next(item for item in declaration["pages"]
                if item["path"] == "/agenten/subscription-agents")
    assert "POST " + API_PATH in page["requires"]
    assert "GET " + API_PATH not in page["requires"]
    compose = next(item for item in declaration["endpoints"]
                   if item["path"] == API_PATH and item["method"] == "POST")
    assert compose["auth"] == "device-token"
    assert compose["runtime_verified"] is False
    without = [route for route in server.app.routes if getattr(route, "path", "") != API_PATH]
    absent = gui_capabilities.declaration(without, kit={}, brand={}, modules={})
    projection = next(item for item in absent["pages"]
                      if item["path"] == "/agenten/subscription-agents")
    assert projection["status"] == "unavailable"
    assert "POST " + API_PATH in projection["missing"]
