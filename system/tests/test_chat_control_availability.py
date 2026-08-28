# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Control-API contract for fail-closed chat backend availability."""

import importlib
import json
import shutil
import subprocess
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm.model_backend import CLIBackend, OllamaBackend  # noqa: E402


@pytest.fixture
def control_module(monkeypatch, tmp_path):
    class _Injector:
        def set_mode(self, _mode):
            pass

    fake_bach_api = types.ModuleType("bach_api")
    fake_bach_api.memory = None
    fake_bach_api.injector = _Injector()
    fake_bach_api.get_app = lambda: None

    fake_telegram = types.ModuleType("telegram")
    fake_telegram.Update = type("Update", (), {})
    fake_telegram_ext = types.ModuleType("telegram.ext")
    fake_telegram_ext.Application = type("Application", (), {})
    fake_telegram_ext.CommandHandler = type("CommandHandler", (), {})
    fake_telegram_ext.MessageHandler = type("MessageHandler", (), {})
    fake_telegram_ext.filters = types.SimpleNamespace()
    fake_telegram_ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)

    module_name = "hub._services.chat.telegram_chat"
    previous_module = sys.modules.pop(module_name, None)
    monkeypatch.setitem(sys.modules, "bach_api", fake_bach_api)
    monkeypatch.setitem(sys.modules, "telegram", fake_telegram)
    monkeypatch.setitem(sys.modules, "telegram.ext", fake_telegram_ext)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_OWNER_ID", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    module = importlib.import_module(module_name)
    try:
        yield module
    finally:
        sys.modules.pop(module_name, None)
        if previous_module is not None:
            sys.modules[module_name] = previous_module


def test_backend_inventory_marks_selected_unreachable_backend(control_module, monkeypatch):
    backend = OllamaBackend(default_model="qwen3:4b")
    monkeypatch.setattr(
        backend,
        "availability",
        lambda **_kwargs: (False, "nicht erreichbar"),
    )
    control_module.runtime.backend = backend
    control_module.runtime.sessions.clear()

    inventory = control_module._backend_inventory()

    assert inventory["ollama"]["selected"] is True
    assert inventory["ollama"]["available"] is False
    assert inventory["ollama"]["status"] == "nicht erreichbar"


def test_control_api_rejects_chat_before_runtime_when_backend_is_unavailable(
    control_module,
    monkeypatch,
):
    backend = OllamaBackend(default_model="qwen3:4b")
    monkeypatch.setattr(
        backend,
        "availability",
        lambda **_kwargs: (False, "nicht erreichbar"),
    )
    control_module.runtime.backend = backend
    control_module.runtime.sessions.clear()
    control_module.runtime.process = MagicMock()

    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}/api/chat",
            json={"prompt": "Nicht ausführen", "chat_id": "test"},
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Backend nicht verfügbar: nicht erreichbar",
    }
    control_module.runtime.process.assert_not_called()
    assert not thread.is_alive()


def test_control_api_checks_model_for_requested_chat(control_module, monkeypatch):
    backend = OllamaBackend(default_model="standard:latest")
    availability = MagicMock(
        side_effect=lambda *, model, **_kwargs: (
            (False, f"Modell fehlt: {model}")
            if model == "ziel:latest"
            else (True, "bereit")
        )
    )
    monkeypatch.setattr(backend, "availability", availability)
    control_module.runtime.backend = backend
    control_module.runtime.sessions.clear()
    control_module.runtime.get_session("anderer-chat").model = "vorhanden:latest"
    control_module.runtime.get_session("ziel-chat").model = "ziel:latest"
    control_module.runtime.process = MagicMock()

    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}/api/chat",
            json={"prompt": "Zielmodell prüfen", "chat_id": "ziel-chat"},
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Backend nicht verfügbar: Modell fehlt: ziel:latest",
    }
    availability.assert_called_once_with(model="ziel:latest", timeout=1.5)
    control_module.runtime.process.assert_not_called()
    assert not thread.is_alive()


def test_api_key_status_requires_nonempty_readable_configuration(
    control_module,
    monkeypatch,
    tmp_path,
):
    credentials = tmp_path / ".credentials"
    credentials.mkdir()
    key_file = credentials / "openai_api_key"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    key_file.write_text("  \n", encoding="utf-8")
    assert control_module._check_api_key("openai") == "Key fehlt"

    key_file.write_text("konfiguriert\n", encoding="utf-8")
    assert control_module._check_api_key("openai") == "Key vorhanden"

    original_read_text = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == key_file:
            raise OSError("nicht lesbar")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    assert control_module._check_api_key("openai") == "Key fehlt"


def test_backend_inventory_does_not_treat_configuration_as_readiness(
    control_module,
    monkeypatch,
    tmp_path,
):
    selected = OllamaBackend(default_model="qwen3:4b")
    monkeypatch.setattr(
        selected,
        "availability",
        lambda **_kwargs: (True, "bereit"),
    )
    control_module.runtime.backend = selected
    control_module.runtime.sessions.clear()

    fake_cli = tmp_path / "cli.exe"
    fake_cli.write_text("test executable placeholder", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: str(fake_cli))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "configured-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "configured-anthropic-key")
    request = httpx.Request("GET", "https://provider.invalid/v1/models")
    monkeypatch.setattr(
        httpx,
        "get",
        MagicMock(side_effect=httpx.ConnectError("offline", request=request)),
    )

    inventory = control_module._backend_inventory()

    assert inventory["ollama"]["available"] is True
    for name in ("claude", "codex", "claude-api", "openai"):
        assert inventory[name]["available"] is False
        assert "configured" not in inventory[name]["status"].lower()


def test_cli_readiness_gets_enough_time_for_local_auth_startup(
    control_module,
    monkeypatch,
    tmp_path,
):
    cli_path = tmp_path / "claude.exe"
    cli_path.write_text("test executable placeholder", encoding="utf-8")
    backend = CLIBackend(cli_name="claude", cli_path=str(cli_path))
    observed = {}

    def availability(*, model, timeout):
        observed.update(model=model, timeout=timeout)
        return True, "bereit"

    monkeypatch.setattr(backend, "availability", availability)

    assert control_module._checked_backend_availability(backend, "sonnet") == (
        True,
        "bereit",
    )
    assert observed["model"] == "sonnet"
    assert observed["timeout"] >= 4.0


def test_backend_inventory_reuses_recent_probe_result(control_module, monkeypatch):
    selected = OllamaBackend(default_model="qwen3:4b")
    calls = 0

    def availability(**_kwargs):
        nonlocal calls
        calls += 1
        return True, "bereit"

    monkeypatch.setattr(selected, "availability", availability)
    monkeypatch.setattr(
        control_module,
        "BACKEND_PRESETS",
        {
            "ollama": {
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "default_model": "qwen3:4b",
                "method": "api",
                "description": "Lokales Ollama",
            }
        },
    )
    control_module.runtime.backend = selected
    control_module.runtime.sessions.clear()
    control_module._invalidate_backend_inventory_cache()

    first = control_module._backend_inventory()
    second = control_module._backend_inventory()

    assert first == second
    assert calls == 1


@pytest.mark.parametrize(
    "answer",
    [
        "Fehler: CLI exit 1",
        "  Fehler: Anmeldung erforderlich  ",
    ],
)
def test_control_chat_response_treats_cli_error_text_as_http_error(
    control_module,
    answer,
):
    payload, status = control_module._control_chat_response(answer)

    assert status == 502
    assert payload == {"ok": False, "error": answer.strip()}


def test_control_status_exposes_stable_backend_id(control_module, monkeypatch):
    backend = OllamaBackend(default_model="qwen3:4b")
    monkeypatch.setattr(
        backend,
        "availability",
        lambda **_kwargs: (True, "bereit"),
    )
    control_module.runtime.backend = backend
    control_module.runtime.sessions.clear()

    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status_response = httpx.get(
            f"http://127.0.0.1:{server.server_port}/api/status",
            timeout=3,
        )
        inventory_response = httpx.get(
            f"http://127.0.0.1:{server.server_port}/api/backends",
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status_response.status_code == 200
    assert status_response.json()["backend_id"] == "ollama"
    assert inventory_response.status_code == 200
    inventory = json.loads(inventory_response.content)
    assert inventory["ollama"]["available"] is True
    assert inventory["ollama"]["selected"] is True
    assert not thread.is_alive()


def test_control_api_defaults_to_loopback(control_module, monkeypatch):
    monkeypatch.delenv("BACH_CONTROL_HOST", raising=False)
    monkeypatch.setattr(control_module, "CONTROL_PORT", 0)

    server = control_module.start_control_api()
    assert server is not None
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.shutdown()
        server.server_close()


def test_control_api_rejects_unauthenticated_non_loopback_bind(
    control_module,
    monkeypatch,
):
    monkeypatch.setenv("BACH_CONTROL_HOST", "0.0.0.0")
    monkeypatch.setattr(control_module, "CONTROL_PORT", 0)

    server = control_module.start_control_api()
    try:
        assert server is None
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


def test_control_api_does_not_grant_cors_to_public_origin(control_module):
    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = httpx.get(
            f"http://127.0.0.1:{server.server_port}/api/status",
            headers={"Origin": "https://example.invalid"},
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert not thread.is_alive()


def test_control_api_rejects_cross_site_post_before_state_change(control_module):
    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    control_module._global_defaults["mode"] = "safe"
    try:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}/api/mode",
            headers={"Origin": "https://example.invalid"},
            json={"mode": "full"},
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 403
    assert control_module._global_defaults["mode"] == "safe"
    assert "access-control-allow-origin" not in response.headers
    assert not thread.is_alive()


def test_control_api_rejects_non_json_post(control_module):
    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    control_module._global_defaults["mode"] = "safe"
    try:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}/api/mode",
            headers={"Content-Type": "text/plain"},
            content='{"mode":"full"}',
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 415
    assert control_module._global_defaults["mode"] == "safe"
    assert not thread.is_alive()


def test_control_api_rejects_json_that_is_not_an_object(control_module):
    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}/api/mode",
            json=[],
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 400
    assert response.json() == {"error": "JSON-Objekt erforderlich"}
    assert not thread.is_alive()


def test_control_api_allows_loopback_json_post(control_module):
    server = control_module.QuietHTTPServer(
        ("127.0.0.1", 0),
        control_module.ControlHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://localhost:{server.server_port}"
    try:
        response = httpx.post(
            f"http://127.0.0.1:{server.server_port}/api/mode",
            headers={"Origin": origin},
            json={"mode": "safe"},
            timeout=3,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "mode": "safe"}
    assert response.headers["access-control-allow-origin"] == origin
    assert not thread.is_alive()
