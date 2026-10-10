"""Private candidate reads and streamed learning request limits, isolated from runtime."""
import asyncio
import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gui.api import unified_api
from hub.learning import LearningHandler
from hub._services.learning_source_service import MAX_REQUEST_BYTES


@pytest.fixture
def api(tmp_path, monkeypatch):
    db = tmp_path / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')", (hashlib.sha256(b"test-device").hexdigest(),))
        conn.execute("INSERT INTO devices VALUES (8,?,'revoked')", (hashlib.sha256(b"revoked-device").hexdigest(),))
    monkeypatch.setattr(unified_api, "BACH_DB", db)
    calls = []
    def run(payload, **kwargs):
        calls.append((payload, kwargs))
        return {"persisted": kwargs["persist"], "targets_published": False}
    monkeypatch.setattr(LearningHandler, "analyze_payload", staticmethod(run))
    app = FastAPI()
    app.include_router(unified_api.router)
    return TestClient(app), calls, app


@pytest.mark.parametrize("endpoint", ["analyze", "store"])
def test_source_auth_precedes_json_and_size_checks(api, endpoint):
    client, calls, _ = api
    url = "/api/learning/sources/" + endpoint
    for body in (b"invalid JSON", b"x" * (MAX_REQUEST_BYTES + 1)):
        assert client.post(url, content=body).status_code == 401
        assert client.post(url, content=body, headers={"Authorization": "Bearer revoked-device"}).status_code == 403
    assert calls == []


@pytest.mark.parametrize("endpoint", ["analyze", "store"])
def test_source_wire_byte_limit_precedes_parsing(api, monkeypatch, endpoint):
    client, calls, _ = api
    # Valid JSON whose insignificant whitespace crosses the wire limit.
    body = b"{}" + b" " * (MAX_REQUEST_BYTES - 1)
    def forbidden_parser(*args, **kwargs):
        raise AssertionError("Oversize body reached the JSON parser")
    monkeypatch.setattr(unified_api, "json", SimpleNamespace(loads=forbidden_parser))
    response = client.post("/api/learning/sources/" + endpoint, content=body,
                           headers={"Authorization": "Bearer test-device"})
    assert response.status_code == 413
    assert calls == []


@pytest.mark.parametrize("body", [b"", b"{", b"[]", b"null", b"\xff"])
def test_invalid_source_json_is_422(api, body):
    client, calls, _ = api
    response = client.post("/api/learning/sources/analyze", content=body,
                           headers={"Authorization": "Bearer test-device"})
    assert response.status_code == 422
    assert calls == []


def test_source_json_recursion_error_is_422_before_service_call(api, monkeypatch):
    client, calls, _ = api

    # Exercise error normalization without guessing the C decoder's depth limit.
    def recursive_parser(*args, **kwargs):
        raise RecursionError("source JSON exceeds the parser's recursion budget")

    monkeypatch.setattr(unified_api, "json", SimpleNamespace(loads=recursive_parser))
    response = client.post("/api/learning/sources/analyze", content=b"{}",
                           headers={"Authorization": "Bearer test-device"})
    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("endpoint", ["analyze", "store"])
def test_exact_wire_limit_and_device_cookie_are_supported(api, endpoint):
    client, calls, _ = api
    client.cookies.set("bach_device_token", "test-device")
    body = b"{}" + b" " * (MAX_REQUEST_BYTES - 2)
    response = client.post("/api/learning/sources/" + endpoint, content=body)
    assert response.status_code == 200
    assert calls == [({}, {"db_path": unified_api.BACH_DB, "actor": "device:7", "persist": endpoint == "store"})]


@pytest.mark.parametrize("provider", ["hermes", "nemofold"])
@pytest.mark.parametrize("suffix", ["", "/1"])
def test_candidate_reads_require_device_before_loading_private_contract(api, monkeypatch, provider, suffix):
    client, _, _ = api
    reads = []
    candidate = {"id": 1, "common_contract": {"events": [{"locator": {"session_id": "private-source"}}]}}
    class Store:
        def list_candidates(self, **kwargs):
            reads.append("list")
            return [candidate]
        def get_candidate(self, candidate_id):
            reads.append(candidate_id)
            return candidate
    monkeypatch.setattr(unified_api, "_get_" + provider + "_service_instance", lambda: Store())
    url = "/api/learning/" + provider + "/candidates" + suffix
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer revoked-device"}).status_code == 403
    assert reads == []
    result = client.get(url, headers={"Authorization": "Bearer test-device"})
    assert result.status_code == 200
    assert reads == ([1] if suffix else ["list"])
    assert "private-source" in result.text


def test_stream_stops_at_limit_without_reading_later_chunks(api):
    consumed = []
    class ChunkedRequest:
        headers = {"Authorization": "Bearer test-device"}
        cookies = {}
        async def stream(self):
            for chunk in (b" " * MAX_REQUEST_BYTES, b"x", b"unread"):
                consumed.append(len(chunk))
                yield chunk
    with pytest.raises(unified_api.HTTPException) as err:
        asyncio.run(unified_api._bounded_learning_source_payload(ChunkedRequest()))
    assert err.value.status_code == 413
    assert consumed == [MAX_REQUEST_BYTES, 1]


def test_source_openapi_keeps_json_object_request_body(api):
    _, _, app = api
    paths = app.openapi()["paths"]
    for endpoint in ("analyze", "store"):
        body = paths["/api/learning/sources/" + endpoint]["post"]["requestBody"]
        assert body["required"]
        assert body["content"]["application/json"]["schema"]["type"] == "object"
