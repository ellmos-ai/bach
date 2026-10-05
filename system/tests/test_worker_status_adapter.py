import asyncio
import json
from urllib.parse import urlsplit

import pytest

from gui.api import worker_status_adapter as adapter


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, calls, responses):
        self.calls = calls
        self.responses = responses

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, *, headers=None, **kwargs):
        endpoint = urlsplit(url).path.rsplit("/api/", 1)[-1]
        self.calls.append(("GET", endpoint, headers, kwargs))
        queue = self.responses.get(("GET", endpoint), [])
        if isinstance(queue, list):
            result = queue.pop(0)
        else:
            result = queue
        return result

    def request(self, method, url, *, params=None, json=None, headers=None, **kwargs):
        endpoint = urlsplit(url).path.rsplit("/api/", 1)[-1]
        self.calls.append((method, endpoint, headers, {"params": params, "json": json, **kwargs}))
        queue = self.responses.get((method, endpoint), [])
        if isinstance(queue, list):
            result = queue.pop(0)
        else:
            result = queue
        return result


def _install_fake_control(monkeypatch, responses):
    calls = []
    monkeypatch.setattr(
        adapter,
        "_control_context",
        lambda device_token: (
            "http://127.0.0.1:18081/api",
            {"Authorization": f"Bearer {device_token}", "Accept": "application/json"},
            lambda payload: isinstance(payload, dict)
            and payload.get("service") == "bach-chat-control"
            and isinstance(payload.get("telegram_verified"), bool),
        ),
    )
    monkeypatch.setattr(
        adapter.httpx,
        "Client",
        lambda **_kwargs: FakeClient(calls, responses),
    )
    responses.setdefault(("GET", "status"), FakeResponse({
        "service": "bach-chat-control", "telegram_verified": False,
    }))
    return calls


def test_control_context_forwards_device_token_only_to_loopback(monkeypatch):
    from gui import server as gui_server

    monkeypatch.setattr(
        gui_server, "_chat_control_base_url", lambda: "http://127.0.0.1:18081/api",
    )
    monkeypatch.setattr(
        gui_server,
        "_chat_control_payload_ready",
        lambda payload: isinstance(payload, dict),
    )

    base, headers, _ready_check = adapter._control_context("device-token-test")

    assert base == "http://127.0.0.1:18081/api"
    assert headers == {
        "Authorization": "Bearer device-token-test",
        "Accept": "application/json",
    }


def test_control_context_rejects_non_loopback_target(monkeypatch):
    from gui import server as gui_server

    monkeypatch.setattr(
        gui_server, "_chat_control_base_url", lambda: "http://100.119.69.90:18081/api",
    )
    monkeypatch.setattr(
        gui_server, "_chat_control_payload_ready", lambda _payload: True,
    )

    with pytest.raises(adapter.WorkerStatusUnavailable, match="Loopback"):
        adapter._control_context("device-token-test")


def test_reads_live_worker_api_with_device_auth_and_projects_safe_fields(monkeypatch):
    calls = _install_fake_control(monkeypatch, {
        ("GET", "workers"): [FakeResponse({
            "ok": True,
            "workers": [{
                "id": "worker-abc123",
                "name": "Buddha Hintergrundworker",
                "backend": "ollama-cloud",
                "model": "kimi-k2.7-code:cloud",
                "status": "running",
                "auto_paused": True,
                "sub_mode": "hintergrund_worker",
                "task_id": 1697,
                "max_tool_rounds": 25,
                "current_activity": "Task läuft",
                "system_prompt": "DON'T EXPOSE",
                "task_prompt": "DON'T EXPOSE",
                "history": [{"content": "DON'T EXPOSE"}],
                "api_key": "DON'T EXPOSE",
            }],
        })],
    })

    result = adapter.read_worker_status(device_token="device-token-test", timeout=2.5)

    assert result["schema"] == "bach.workers.status.v1"
    assert result["source"] == "authenticated_local_control_api"
    assert result["count"] == 1
    assert result["workers"] == [{
        "id": "worker-abc123",
        "name": "Buddha Hintergrundworker",
        "backend": "ollama-cloud",
        "model": "kimi-k2.7-code:cloud",
        "status": "running",
        "auto_paused": True,
        "sub_mode": "hintergrund_worker",
        "current_activity": "Task läuft",
        "max_tool_rounds": 25,
        "task_id": 1697,
    }]
    assert [(method, endpoint) for method, endpoint, *_ in calls] == [
        ("GET", "status"), ("GET", "workers"),
    ]
    assert all(call[2]["Authorization"] == "Bearer device-token-test" for call in calls)
    assert "DON'T EXPOSE" not in json.dumps(result)


def test_missing_internal_control_authorization_fails_closed(monkeypatch):
    def no_control_auth(_device_token):
        raise adapter.WorkerStatusUnavailable("missing")

    monkeypatch.setattr(adapter, "_control_context", no_control_auth)
    with pytest.raises(adapter.WorkerStatusUnavailable):
        adapter.read_worker_status(device_token="device-token-test")


def test_worker_create_returns_idle_profile_without_prompt_or_secret(monkeypatch):
    calls = _install_fake_control(monkeypatch, {
        ("GET", "auth/check"): FakeResponse({"authenticated": True}),
        ("POST", "workers"): FakeResponse({
            "ok": True,
            "worker": {
                "id": "worker-created1", "name": "Cloud Worker", "status": "idle",
                "backend": "ollama-cloud", "model": "kimi-k3:cloud",
                "system_prompt": "PRIVATE PROMPT", "api_key": "PRIVATE KEY",
            },
        }),
    })

    result = adapter.worker_action("create", {
        "name": "Cloud Worker", "backend": "ollama-cloud", "model": "kimi-k3:cloud",
    }, device_token="device-token-test")

    assert result["ok"] is True
    assert result["worker"]["status"] == "idle"
    assert "PRIVATE" not in json.dumps(result)
    assert [(method, endpoint) for method, endpoint, *_ in calls] == [
        ("GET", "status"), ("GET", "auth/check"), ("POST", "workers"),
    ]


def test_cloud_worker_start_requires_readiness_and_explicit_authenticated_post(monkeypatch):
    idle = {"ok": True, "workers": [{"id": "worker-cloud1", "status": "idle"}]}
    running = {"ok": True, "workers": [{"id": "worker-cloud1", "status": "running"}]}
    calls = _install_fake_control(monkeypatch, {
        ("GET", "workers"): [FakeResponse(idle), FakeResponse(running)],
        ("GET", "readiness"): FakeResponse({"available": True, "model": "kimi-k3:cloud"}),
        ("GET", "auth/check"): FakeResponse({"authenticated": True}),
        ("POST", "workers/run"): FakeResponse({"ok": True, "message": "started"}),
    })

    result = adapter.start_worker("worker-cloud1", device_token="device-token-test")

    assert result["start_acknowledged"] is True
    assert result["runtime_state"] == "running"
    run_index = next(i for i, item in enumerate(calls) if item[:2] == ("POST", "workers/run"))
    readiness_index = next(i for i, item in enumerate(calls) if item[:2] == ("GET", "readiness"))
    assert readiness_index < run_index
    assert calls[run_index][3]["json"] == {"id": "worker-cloud1"}


def test_worker_start_passes_saved_task_prompt_only_to_control_api(monkeypatch):
    monkeypatch.setattr(
        adapter,
        "_configured_task_prompt",
        lambda _worker_id: "Bearbeite den gespeicherten Auftrag vollständig.",
    )
    calls = _install_fake_control(monkeypatch, {
        ("GET", "workers"): [
            FakeResponse({"ok": True, "workers": [{"id": "worker-cloud1", "status": "idle"}]}),
            FakeResponse({"ok": True, "workers": [{"id": "worker-cloud1", "status": "running"}]}),
        ],
        ("GET", "readiness"): FakeResponse({"available": True, "model": "kimi-k3:cloud"}),
        ("GET", "auth/check"): FakeResponse({"authenticated": True}),
        ("POST", "workers/run"): FakeResponse({"ok": True, "message": "started"}),
    })

    result = adapter.start_worker("worker-cloud1", device_token="device-token-test")

    run_call = next(item for item in calls if item[:2] == ("POST", "workers/run"))
    assert run_call[3]["json"] == {
        "id": "worker-cloud1",
        "prompt": "Bearbeite den gespeicherten Auftrag vollständig.",
    }
    assert "Bearbeite den gespeicherten Auftrag" not in json.dumps(result)


def test_worker_is_not_started_when_model_is_not_ready(monkeypatch):
    calls = _install_fake_control(monkeypatch, {
        ("GET", "workers"): [FakeResponse({
            "ok": True, "workers": [{"id": "worker-cloud1", "status": "idle"}],
        })],
        ("GET", "readiness"): FakeResponse({"available": False, "status": "Key fehlt"}),
    })

    with pytest.raises(adapter.WorkerActionRejected, match="Modell ist derzeit nicht bereit"):
        adapter.start_worker("worker-cloud1", device_token="device-token-test")
    assert all(endpoint != "workers/run" for _method, endpoint, *_ in calls)


def test_invalid_worker_snapshot_is_not_reported_as_empty(monkeypatch):
    _install_fake_control(monkeypatch, {
        ("GET", "workers"): [FakeResponse({"ok": True, "workers": [{}]})],
    })
    with pytest.raises(adapter.WorkerStatusUnavailable):
        adapter.read_worker_status(device_token="device-token-test")


def test_projects_observed_tool_round_from_live_running_activity():
    worker = adapter._project_worker({
        "id": "worker-rounds",
        "status": "running",
        "current_activity": "Tool [7]: task_manage",
        "max_tool_rounds": 9,
    })

    assert worker["tool_round"] == 7
    assert worker["max_tool_rounds"] == 9


@pytest.mark.parametrize("status", ["idle", "paused", "completed"])
def test_does_not_report_stale_or_non_running_tool_round(status):
    worker = adapter._project_worker({
        "id": "worker-rounds",
        "status": status,
        "current_activity": "Tool [7]: task_manage",
        "max_tool_rounds": 9,
    })

    assert "tool_round" not in worker


def test_does_not_infer_tool_round_from_unstructured_activity():
    worker = adapter._project_worker({
        "id": "worker-rounds",
        "status": "running",
        "current_activity": "Warte auf Ergebnis aus Tool [7]: task_manage",
        "max_tool_rounds": 9,
    })

    assert "tool_round" not in worker


def test_worker_catalog_is_provider_scoped_and_does_not_forward_secrets(monkeypatch):
    calls = _install_fake_control(monkeypatch, {
        ("GET", "models"): [FakeResponse({
            "provider": "ollama-cloud",
            "models": ["kimi-k3:cloud", "glm-5.3:cloud"],
            "credential_configured": True,
        })],
    })

    result = adapter.worker_model_catalog("ollama-cloud", device_token="device-token-test")

    assert result["models"] == ["kimi-k3:cloud", "glm-5.3:cloud"]
    model_call = next(item for item in calls if item[:2] == ("GET", "models"))
    assert model_call[3]["params"] == {"provider": "ollama-cloud"}
    assert "server-only-control-token" not in json.dumps(result)


def test_invalid_control_provider_is_rejected():
    with pytest.raises(adapter.WorkerActionRejected, match="Provider"):
        adapter.worker_model_catalog("arbitrary-provider")


def test_worker_creation_options_reflect_registered_bach_modes_and_roles():
    options = adapter.worker_creation_options()

    assert {item["id"] for item in options["sub_modes"]} == {
        "hintergrund_worker", "task_worker", "boss_routing", "expert_role",
    }
    roles = {item["id"]: item["label"] for item in options["expert_roles"]}
    assert roles["task-divider"] == "Task-Divider · Aufgabenzerlegung"
    assert roles["ticket-master"] == "Ticket-Master · Triage"
    assert "hintergrund_worker" not in roles
    assert all(set(item) == {"id", "label"} for item in options["expert_roles"])


def test_background_worker_blueprint_defaults_to_continuous_explicit_start(monkeypatch):
    from hub._services.chat import slots_config

    monkeypatch.setattr(slots_config, "core_system_agents_snapshot", lambda: {
        "agents": [{
            "id": "buddha_always_on", "max_tool_rounds": 25, "mode": "full",
            "think": True, "pause_after": 5, "pause_minutes": 1, "pause_basis": "tasks",
        }],
    })

    blueprint = adapter.background_worker_blueprint()

    assert blueprint["defaults"]["type"] == "continuous"
    assert blueprint["defaults"]["ttl_minutes"] == 0
    assert blueprint["creation_state"] == "idle"
    assert blueprint["requires_explicit_start"] is True
    assert blueprint["defaults"]["pause_basis"] == "tasks"


def test_system_worker_creation_persists_selected_mode_and_task(monkeypatch):
    from gui.api import unified_api

    captured = {}
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _request: "device-token-test")
    monkeypatch.setattr(adapter, "worker_model_catalog", lambda _backend, **_kwargs: {
        "models": ["kimi-k3:cloud"],
    })

    def create_worker(action, config, *, device_token):
        captured.update(action=action, config=config)
        captured["device_token"] = device_token
        return {
            "ok": True,
            "worker": {
                "id": "worker-created1",
                "name": config["name"],
                "status": "idle",
                "sub_mode": config["sub_mode"],
                "role_id": config["role_id"],
                "task_id": config["task_id"],
            },
        }

    monkeypatch.setattr(adapter, "worker_action", create_worker)
    result = asyncio.run(unified_api.create_system_worker(None, {
        "name": "Aufgabenzerleger",
        "backend": "ollama-cloud",
        "model": "kimi-k3:cloud",
        "sub_mode": "expert_role",
        "role_id": "task-divider",
        "task_id": 42,
        "max_tool_rounds": 12,
        "mode": "full",
        "think": True,
        "pause_after": 5,
        "pause_minutes": 1,
        "pause_basis": "tasks",
        "type": "once",
        "ttl_minutes": 0,
        "task_prompt": "",
        "include_system_prompt": True,
        "allow_tools": True,
    }))

    assert captured["action"] == "create"
    assert captured["device_token"] == "device-token-test"
    assert captured["config"]["sub_mode"] == "expert_role"
    assert captured["config"]["role_id"] == "task-divider"
    assert captured["config"]["task_id"] == 42
    assert captured["config"]["max_tool_rounds"] == 12
    assert captured["config"]["pause_basis"] == "tasks"
    assert result["worker"]["status"] == "idle"


def test_system_worker_creation_rejects_unregistered_expert_before_catalog(monkeypatch):
    from fastapi import HTTPException
    from gui.api import unified_api

    monkeypatch.setattr(
        unified_api,
        "_require_memory_device_token",
        lambda _request: "device-token-test",
    )
    monkeypatch.setattr(adapter, "worker_model_catalog", lambda _backend: pytest.fail("catalog must not load"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(unified_api.create_system_worker(None, {
            "name": "Unknown expert",
            "backend": "ollama-cloud",
            "model": "kimi-k3:cloud",
            "sub_mode": "expert_role",
            "role_id": "arbitrary-prompt",
        }))
    assert error.value.status_code == 400


def test_continuous_worker_can_run_without_a_time_limit(monkeypatch):
    from gui.api import unified_api

    captured = {}
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _request: "device-token-test")
    monkeypatch.setattr(adapter, "worker_model_catalog", lambda _backend, **_kwargs: {
        "models": ["kimi-k3:cloud"],
    })

    def create_worker(action, config, *, device_token):
        captured.update(action=action, config=config, device_token=device_token)
        return {"ok": True, "worker": {"id": "worker-always1", "name": config["name"], "status": "idle"}}

    monkeypatch.setattr(adapter, "worker_action", create_worker)
    result = asyncio.run(unified_api.create_system_worker(None, {
        "name": "Always-On Hintergrundworker",
        "backend": "ollama-cloud",
        "model": "kimi-k3:cloud",
        "sub_mode": "hintergrund_worker",
        "type": "continuous",
        "ttl_minutes": 0,
        "pause_after": 5,
        "pause_minutes": 1,
    }))

    assert captured["config"]["type"] == "continuous"
    assert "ttl_seconds" not in captured["config"]
    assert captured["config"]["pause_after"] == 5
    assert captured["config"]["pause_basis"] == "runs"
    assert result["worker"]["status"] == "idle"
