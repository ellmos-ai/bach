from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from gui.api import report_provider, unified_api
from hub._services.document.report_provider_adapter import ReportProviderAdapter
from hub._services.document.report_provider_contract import SCHEMA


ACTIVE_TOKEN = "active-report-device-token-fixture"
SUBJECT_REF = "sub_" + "1" * 48
SOURCE_REF = "src_" + "2" * 48


class _Provider:
    def __init__(self):
        self.calls = []

    async def capabilities(self):
        self.calls.append(("capabilities",))
        return {
            "schema": SCHEMA,
            "available": False,
            "modes": [],
            "watcher_available": True,
            "mode_statuses": {
                mode: {"available": False, "reason_code": "provider_unavailable"}
                for mode in ("local", "cloud", "hybrid")
            },
            "reason_code": "provider_unavailable",
        }

    async def list_sources(self, subject_ref):
        self.calls.append(("sources", subject_ref))
        return {"schema": SCHEMA, "complete": True, "sources": []}

    async def prepare(self, request):
        self.calls.append(("prepare", request))
        return {
            "schema": SCHEMA,
            "run_id": None,
            "status": "blocked",
            "preview_ref": None,
            "expires_at": None,
            "request_digest": request["mode_consent"]["request_digest"],
            "source_revision": None,
            "template_revision": None,
            "source_count": 0,
            "reason_code": "provider_unavailable",
        }

    async def finish(self, run_id, approval):
        self.calls.append(("finish", run_id, approval))
        return {
            "schema": SCHEMA, "run_id": run_id, "status": "blocked", "effect": "none",
            "reason_code": "provider_unavailable", "artifact_refs": [], "review_required": True,
        }

    async def status(self, run_id):
        self.calls.append(("status", run_id))
        return {"schema": SCHEMA, "run_id": run_id, "status": "unknown", "review_required": True}

    async def cleanup(self, run_id, approval):
        self.calls.append(("cleanup", run_id, approval))
        return {"schema": SCHEMA, "run_id": run_id, "status": "cleaned", "sources_retained": True}

    async def watcher_status(self):
        self.calls.append(("watcher_status",))
        return {"schema": SCHEMA, "status": "disabled", "enabled": False}

    async def watcher_configure(self, config):
        self.calls.append(("watcher_configure", config))
        return {"schema": SCHEMA, "status": "disabled", "enabled": False}

    async def watcher_tick(self, now=None):
        self.calls.append(("watcher_tick",))
        return {"schema": SCHEMA, "status": "disabled", "enabled": False}


@pytest.fixture
def api_client(monkeypatch):
    provider = _Provider()
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _request: ACTIVE_TOKEN)
    monkeypatch.setattr(report_provider, "_adapter", lambda token: ReportProviderAdapter(provider))
    app = FastAPI()
    app.include_router(report_provider.router)
    with TestClient(app) as client:
        yield client, provider


def _auth():
    return {"Authorization": f"Bearer {ACTIVE_TOKEN}"}


def _prepare_request():
    from hub._services.document.report_provider_contract import ReportRequest

    stable = {
        "schema": SCHEMA,
        "request_id": "request-test-1",
        "subject_ref": SUBJECT_REF,
        "source_refs": [SOURCE_REF],
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "mode": "local",
        "template_id": "template-test",
    }
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    consent = {
        "mode": "local",
        "consent_ref": "consent-test",
        "request_id": stable["request_id"],
        "request_digest": digest,
        "approved": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }
    request = {**stable, "mode_consent": consent}
    ReportRequest.from_wire(request)
    return request


def _watcher_config():
    return {
        "schema": SCHEMA,
        "enabled": True,
        "auto_finish": False,
        "subject_refs": [SUBJECT_REF],
        "mode": "local",
        "template_id": "template-test",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "consent_ref": "consent-test",
        "consent_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }


def test_device_authorization_happens_before_body_or_query_read(monkeypatch):
    stream_calls = []
    original_stream = StarletteRequest.stream

    async def tracked_stream(request):
        stream_calls.append(True)
        async for chunk in original_stream(request):
            yield chunk

    def deny(_request):
        raise HTTPException(status_code=401, detail="private auth detail")

    monkeypatch.setattr(unified_api, "_require_memory_device_token", deny)
    monkeypatch.setattr(StarletteRequest, "stream", tracked_stream)
    app = FastAPI()
    app.include_router(report_provider.router)
    with TestClient(app) as client:
        response = client.post(
            "/api/reports/prepare?token=not-authority",
            content=b"{" + b"x" * (report_provider.MAX_REPORT_REQUEST_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
        get_response = client.get("/api/reports/sources?token=not-authority")

    assert response.status_code == 401 and get_response.status_code == 401
    assert response.json()["detail"]["code"] == "device_auth_required"
    assert stream_calls == []
    assert "private auth detail" not in response.text


def test_strict_v1_routes_return_provider_dtos_and_forward_only_fixed_fields(api_client):
    client, provider = api_client
    headers = {**_auth(), "Content-Type": "application/json"}
    request = _prepare_request()

    capabilities = client.get("/api/reports/capabilities", headers=_auth())
    sources = client.get(f"/api/reports/sources?subject_ref={SUBJECT_REF}", headers=_auth())
    prepared = client.post("/api/reports/prepare", json=request, headers=headers)
    finished = client.post(
        "/api/reports/finish",
        json={"run_id": "run-test", "approval": {
            "approved": True, "preview_ref": "preview-test", "consent_ref": "consent-test",
        }},
        headers=headers,
    )
    cleanup = client.post(
        "/api/reports/cleanup",
        json={"run_id": "run-test", "approval": {
            "run_id": "run-test", "consent_ref": "consent-test", "approved": True,
            "delete_sources": False,
        }},
        headers=headers,
    )
    status = client.get("/api/reports/status?run_id=run-test", headers=_auth())
    watcher_status = client.get("/api/reports/watcher/status", headers=_auth())
    watcher_config = client.post(
        "/api/reports/watcher/configure", json=_watcher_config(), headers=headers,
    )
    watcher_tick = client.post("/api/reports/watcher/tick", json={}, headers=headers)

    assert capabilities.status_code == 200 and capabilities.json()["schema"] == SCHEMA
    assert sources.status_code == 200 and sources.json() == {
        "schema": SCHEMA, "complete": True, "sources": [],
    }
    assert prepared.status_code == 200 and prepared.json()["status"] == "blocked"
    assert finished.status_code == 200 and finished.json()["status"] == "blocked"
    assert cleanup.status_code == 200 and cleanup.json()["sources_retained"] is True
    assert status.status_code == 200 and status.json()["run_id"] == "run-test"
    assert watcher_status.status_code == 200 and watcher_status.json()["enabled"] is False
    assert watcher_config.status_code == 200 and watcher_config.json()["enabled"] is False
    assert watcher_tick.status_code == 200 and watcher_tick.json()["enabled"] is False
    assert capabilities.json()["watcher_available"] is True
    assert [call[0] for call in provider.calls] == [
        "capabilities", "sources", "prepare", "finish", "cleanup", "status",
        "watcher_status", "watcher_configure", "watcher_tick",
    ]
    assert provider.calls[2][1] == request
    assert provider.calls[-2][1]["schema"] == SCHEMA
    assert provider.calls[-2][1]["subject_refs"] == [SUBJECT_REF]


@pytest.mark.parametrize("number", ["1e999", "-1e999"])
def test_json_float_overflow_is_rejected_before_provider_dispatch(api_client, number):
    client, provider = api_client
    response = client.post(
        "/api/reports/watcher/tick",
        content=("{\"x\":" + number + "}").encode("ascii"),
        headers={**_auth(), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_json"}}
    assert provider.calls == []


def test_json_container_depth_is_bounded_before_provider_dispatch(api_client):
    client, provider = api_client
    headers = {**_auth(), "Content-Type": "application/json"}
    within_limit = "{\"x\":" + "[" * 31 + "0" + "]" * 31 + "}"
    beyond_limit = "{\"x\":" + "[" * 32 + "0" + "]" * 32 + "}"

    accepted = client.post("/api/reports/watcher/tick", content=within_limit, headers=headers)
    rejected = client.post("/api/reports/watcher/tick", content=beyond_limit, headers=headers)

    assert accepted.status_code == 422
    assert rejected.status_code == 400
    assert rejected.json() == {"detail": {"code": "invalid_json"}}
    assert provider.calls == []


def test_extra_query_fields_duplicate_json_and_invalid_watcher_body_are_rejected(api_client):
    client, provider = api_client
    headers = {**_auth(), "Content-Type": "application/json"}

    extra_query = client.get(
        f"/api/reports/sources?subject_ref={SUBJECT_REF}&extra=x", headers=_auth(),
    )
    capabilities_query = client.get("/api/reports/capabilities?extra=x", headers=_auth())
    duplicate = client.post(
        "/api/reports/watcher/tick", content=b'{"x":1,"x":2}', headers=headers,
    )
    tick_extra = client.post("/api/reports/watcher/tick", json={"now": "2026-10-11"}, headers=headers)
    finish_extra = client.post(
        "/api/reports/finish", json={"run_id": "r", "approval": {}, "provider": "x"},
        headers=headers,
    )

    assert extra_query.status_code == 422
    assert capabilities_query.status_code == 422
    assert duplicate.status_code == 400
    assert tick_extra.status_code == 422
    assert finish_extra.status_code == 422
    assert provider.calls == []


@pytest.mark.asyncio
async def test_control_client_uses_only_the_confirmed_rpc_routes(monkeypatch):
    client = report_provider._ControlReportProvider(ACTIVE_TOKEN)
    calls = []

    async def capture(method, endpoint, *, params=None, body=None):
        calls.append((method, endpoint, params, body))
        return {"schema": SCHEMA}

    monkeypatch.setattr(client, "_request", capture)
    await client.capabilities()
    await client.list_sources(SUBJECT_REF)
    await client.status("run-test")
    await client.watcher_status()
    await client.prepare({"schema": SCHEMA})
    await client.finish("run-test", {"approved": True})
    await client.cleanup("run-test", {"approved": True})
    await client.watcher_configure({"schema": SCHEMA})
    await client.watcher_tick()

    assert calls == [
        ("GET", "reports/capabilities", None, None),
        ("GET", "reports/sources", {"subject_ref": SUBJECT_REF}, None),
        ("GET", "reports/status", {"run_id": "run-test"}, None),
        ("GET", "reports/watcher/status", None, None),
        ("POST", "reports/prepare", None, {"schema": SCHEMA}),
        ("POST", "reports/finish", None, {"run_id": "run-test", "approval": {"approved": True}}),
        ("POST", "reports/cleanup", None, {"run_id": "run-test", "approval": {"approved": True}}),
        ("POST", "reports/watcher/configure", None, {"schema": SCHEMA}),
        ("POST", "reports/watcher/tick", None, {}),
    ]
