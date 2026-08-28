# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Control-API contract for fail-closed chat backend availability."""

import importlib
import json
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm.model_backend import OllamaBackend  # noqa: E402


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
