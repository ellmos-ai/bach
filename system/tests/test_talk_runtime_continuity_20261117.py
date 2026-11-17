"""Talk uses the existing authenticated runtime, with owner-separated durable scope."""

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gui import server


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "validate_token",
                        lambda token: {"id": 7, "name": "owner"} if token == "owner-token" else
                        {"id": 8, "name": "second"} if token == "second-token" else None)
    monkeypatch.setattr(server, "_TALK_CONFIG_FILE", tmp_path / "talk_config.json")
    monkeypatch.setattr(server, "_TALK_SESSION_SINGLETON", None)
    monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://control.invalid/api")
    monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer internal-control")
    return TestClient(server.app)


@pytest.mark.parametrize("path", ["/api/talk/turn", "/api/talk/config", "/api/talk/directive",
                                  "/api/talk/summon", "/api/talk/summon/ack"])
def test_talk_mutations_require_active_device(client, path):
    assert client.post(path, json={"text": "private turn"}).status_code == 401
    assert client.post(path, json={}, headers={"Authorization": "Bearer revoked"}).status_code == 403


def install_control(monkeypatch, response=None, status=200):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer internal-control"
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"ready": True})
        return httpx.Response(status, json=response or {"ok": True, "answer": "Kanonische Antwort."})
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(server.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(server, "_chat_control_payload_ready", lambda payload: payload == {"ready": True})
    return calls


def test_talk_uses_control_with_durable_device_slot_scope(client, monkeypatch):
    import json
    calls = install_control(monkeypatch)
    headers = {"Authorization": "Bearer owner-token"}
    first = client.post("/api/talk/turn", json={"text": "Merke meinen Kontext."}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["spoken_text"] == "Kanonische Antwort."
    body = json.loads(calls[-1].content)
    assert calls[-1].url.path == "/api/chat"
    assert body["prompt"] == "Merke meinen Kontext."
    assert body["chat_id"].startswith("slot:buddha_chat:")
    assert len(body["chat_id"].rsplit(":", 1)[1]) == 32
    assert set(body) == {"prompt", "chat_id"}
    # A restarted visual engine and another valid credential for the same device
    # must address the same runtime transcript; another device must not.
    monkeypatch.setattr(server, "_TALK_SESSION_SINGLETON", None)
    client.post("/api/talk/turn", json={"text": "Weiter."}, headers=headers)
    assert json.loads(calls[-1].content)["chat_id"] == body["chat_id"]
    client.post("/api/talk/turn", json={"text": "Anderes Gerät."},
                headers={"Authorization": "Bearer second-token"})
    assert json.loads(calls[-1].content)["chat_id"] != body["chat_id"]
    assert all(r.url.host == "control.invalid" for r in calls)


def test_talk_respects_bound_slot_without_accepting_foreign_chat_id(client, monkeypatch):
    import json
    calls = install_control(monkeypatch)
    headers = {"Authorization": "Bearer owner-token"}
    configured = client.post("/api/talk/config", json={"bound_slot": "buddha_talk"}, headers=headers)
    assert configured.status_code == 200
    result = client.post("/api/talk/turn", json={"text": "Hallo.", "chat_id": "gui-web"}, headers=headers)
    assert result.status_code == 400
    result = client.post("/api/talk/turn", json={"text": "Hallo."}, headers=headers)
    assert result.status_code == 200
    assert json.loads(calls[-1].content)["chat_id"].startswith("slot:buddha_talk:")


@pytest.mark.parametrize("payload", [{"model_response": "gefälscht"}, {"agent_id": 1}, {"chat_id": "gui-web"}])
def test_talk_rejects_client_authority_or_model_answer(client, payload):
    result = client.post("/api/talk/turn", json={"text": "Hallo.", **payload},
                         headers={"Authorization": "Bearer owner-token"})
    assert result.status_code == 400


def test_talk_control_failure_is_not_spoken_as_success(client, monkeypatch):
    calls = install_control(monkeypatch, {"ok": False, "error": "Systemsteckplatz ist ausgeschaltet"}, 503)
    result = client.post("/api/talk/turn", json={"text": "Hallo."},
                         headers={"Authorization": "Bearer owner-token"})
    assert result.status_code == 503
    assert "Systemsteckplatz" in result.json()["detail"]
    assert len(calls) == 2


def test_unbound_responder_cannot_infer(monkeypatch):
    with pytest.raises(HTTPException) as error:
        server._talk_cortex_responder("Hallo.", "claude", "de")
    assert error.value.status_code == 401

@pytest.mark.parametrize("persona", ["claude", "gemini", "codex"])
def test_unverified_persona_cannot_claim_another_model_identity(client, monkeypatch, persona):
    calls = install_control(monkeypatch)
    result = client.post("/api/talk/turn", json={"text": "Hallo.", "persona": persona},
                         headers={"Authorization": "Bearer owner-token"})
    assert result.status_code == 409
    assert "Steckplatz" in result.json()["detail"]
    assert calls == []


def test_browser_cookie_authenticates_talk_and_preserves_scope(client, monkeypatch):
    import json
    calls = install_control(monkeypatch)
    client.cookies.set("bach_device_token", "owner-token")
    assert client.post("/api/talk/turn", json={"text": "Cookie."}).status_code == 200
    cookie_id = json.loads(calls[-1].content)["chat_id"]
    client.cookies.clear()
    assert client.post("/api/talk/turn", json={"text": "Bearer."},
                       headers={"Authorization": "Bearer owner-token"}).status_code == 200
    assert json.loads(calls[-1].content)["chat_id"] == cookie_id


def test_compute_lock_is_failure_and_resets_request_scope(client, monkeypatch):
    install_control(monkeypatch, {"compute_locked": True, "answer": "Compute-Lock aktiv"})
    result = client.post("/api/talk/turn", json={"text": "Hallo."},
                         headers={"Authorization": "Bearer owner-token"})
    assert result.status_code == 503
    assert server._TALK_CALLER_SCOPE.get() is None
