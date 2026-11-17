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

def test_inflight_talk_keeps_event_loop_free_and_its_own_state(client, monkeypatch):
    import asyncio
    import threading
    from starlette.requests import Request

    started, release = threading.Event(), threading.Event()
    observed_scope = []
    def responder(*args):
        observed_scope.append(server._TALK_CALLER_SCOPE.get())
        started.set()
        assert release.wait(2), "synthetic turn was not released"
        return "Snapshot-Antwort."

    monkeypatch.setattr(server, "_talk_cortex_responder", responder)
    request = Request({"type": "http", "headers": []})
    request.state.device = {"id": 7}
    shared = server._get_talk_session()
    initial_state = shared.state
    initial_reflex = shared.reflex

    async def scenario():
        task = asyncio.create_task(server.api_talk_turn(request, {"text": "Langer Auftrag."}))
        timer = threading.Timer(1, release.set)
        timer.start()
        try:
            assert await asyncio.to_thread(started.wait, 1)
            assert not task.done(), "Talk blocked the event loop until inference completed"
            status = await server.api_talk_status()
            assert status["persona"] == "buddha"
            await server.api_update_talk_config({
                "persona": "claude", "bound_slot": "buddha_talk",
                "fast_relay_model": "changed-reflex",
            })
            release.set()
            result = await task
            assert result["visual_state"]["persona"] == initial_state.persona
            assert result["visual_state"]["bound_slot"] == initial_state.bound_slot
            assert result["visual_state"]["fast_relay_model"] == initial_state.fast_relay_model
            assert shared.state.persona == "claude"
            assert shared.state.bound_slot == "buddha_talk"
            assert shared.reflex is initial_reflex
            assert observed_scope == [server._talk_chat_scope({"id": 7}, initial_state.bound_slot)]
        finally:
            release.set()
            timer.cancel()
            await task

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 409, 503, "network"])
def test_companion_client_keeps_input_and_shows_failure(status):
    import asyncio
    import json
    import re
    import shutil
    import subprocess

    html = asyncio.run(server.talk_visualizer_companion_page()).body.decode("utf-8")
    start = html.index("    async function sendTurn() {")
    end = html.index(chr(10) * 2 + "    document.getElementById('sendBtn')", start)
    source = html[start:end]
    node = shutil.which("node")
    assert node, "Node is required to exercise the delivered companion client"
    script = """
const vm = require('node:vm');
const assert = require('node:assert/strict');
const status = STATUS;
const elements = {
  utteranceInput: { value: 'Behalte meinen Auftrag' },
  personaSelect: { value: 'buddha' },
  langSelect: { value: 'de' },
  transcriptBox: { textContent: '' },
  reflexStatus: { textContent: '' },
  sendBtn: { disabled: false },
};
let fetchCount = 0, spoken = 0, rendered = 0;
const scope = {
  document: { getElementById: id => elements[id] },
  fetch: async () => {
    fetchCount++;
    if (status === 'network') throw new Error('Scoped network failure');
    return {ok: false, status, json: async () => ({detail: 'Scoped failure ' + status})};
  },
  applyVisualState: () => { rendered++; },
  window: { speechSynthesis: { cancel() {}, speak() { spoken++; } } },
  SpeechSynthesisUtterance: function() {},
};
vm.runInNewContext(SOURCE + ';sendTurn()', scope).then(() => {
  assert.equal(elements.utteranceInput.value, 'Behalte meinen Auftrag');
  assert.match(elements.transcriptBox.textContent, /Scoped (?:network )?failure/);
  assert.equal(fetchCount, 1);
  assert.equal(spoken, 0);
  assert.equal(rendered, 0);
  assert.equal(elements.sendBtn.disabled, false);
}).catch(error => { console.error(error); process.exitCode = 1; });
""".replace("STATUS", json.dumps(status)).replace("SOURCE", json.dumps(source))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_talk_config_labels_legacy_model_as_non_executing(client):
    result = client.get("/api/talk/config")
    assert result.status_code == 200
    assert result.json()["execution_binding"] == {
        "source": "system_slot", "slot_id": "buddha_chat", "primary_model_override": False,
    }

def test_companion_audio_failure_keeps_the_received_answer():
    import asyncio
    import json
    import shutil
    import subprocess

    html = asyncio.run(server.talk_visualizer_companion_page()).body.decode("utf-8")
    start = html.index("    async function sendTurn() {")
    end = html.index(chr(10) * 2 + "    document.getElementById('sendBtn')", start)
    script = """
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = {
  utteranceInput: { value: 'Mein Auftrag' }, personaSelect: {value: 'buddha'},
  langSelect: {value: 'de'}, transcriptBox: {textContent: ''},
  reflexStatus: {textContent: ''}, sendBtn: {disabled: false},
};
const scope = {
  document: {getElementById: id => elements[id]},
  fetch: async url => url === '/api/talk/turn'
    ? {ok: true, json: async () => ({spoken_text: 'Empfangene Antwort.'})}
    : {ok: false},
  applyVisualState() {},
  window: {speechSynthesis: {cancel() {}, speak() {throw new Error('synthetic audio error');}}},
  SpeechSynthesisUtterance: function() {},
};
vm.runInNewContext(SOURCE + ';sendTurn()', scope).then(() => {
  assert.equal(elements.utteranceInput.value, '');
  assert.equal(elements.transcriptBox.textContent, 'Empfangene Antwort.');
  assert.match(elements.reflexStatus.textContent, /Sprachausgabe/);
  assert.equal(elements.sendBtn.disabled, false);
}).catch(error => {console.error(error); process.exitCode = 1;});
""".replace("SOURCE", json.dumps(html[start:end]))
    node = shutil.which("node")
    assert node
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
