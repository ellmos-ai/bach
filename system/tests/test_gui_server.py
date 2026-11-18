# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the BACH GUI server — exception handlers, DB helpers, startup."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import server


@pytest.mark.parametrize("path", ["history", "readiness"])
def test_gui_proxy_forwards_history_and_readiness(client, monkeypatch, path):
    import httpx
    payload = {"messages": [{"role": "assistant", "content": "Verlauf", "ok": True}]} if path == "history" else {"available": True}
    seen = []

    class Upstream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            if url.endswith("/auth/check"):
                return httpx.Response(200, json={"authenticated": (headers or {}).get("authorization") == "Bearer control-test"})
            return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})

        async def request(self, method, url, **kwargs):
            seen.append((method, url, dict(kwargs["params"])))
            return httpx.Response(200, json=payload)

    monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://127.0.0.1:8127/api")
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "device-test" else None)
    monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer control-test")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: Upstream())
    response = client.get(f"/api/chat-control/{path}?chat_id=gui-web",
                          headers={"Authorization": "Bearer device-test"})
    assert response.status_code == 200
    assert response.json() == payload
    assert seen == [("GET", f"http://127.0.0.1:8127/api/{path}", {"chat_id": "gui-web"})]


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient for the BACH GUI app."""
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "gui-fixture" else None)
    return TestClient(server.app, raise_server_exceptions=False,
                      headers={"Authorization": "Bearer gui-fixture"})


@pytest.fixture
def fake_dbs(tmp_path, monkeypatch):
    """Create minimal user and bach DBs and point server at them."""
    user_db = tmp_path / "user.db"
    bach_db = tmp_path / "bach.db"

    conn = sqlite3.connect(user_db)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, title TEXT, status TEXT,
            created TEXT, updated TEXT, priority TEXT, tags TEXT
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(bach_db)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, title TEXT, status TEXT DEFAULT 'open',
            created TEXT, updated TEXT, priority TEXT, tags TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(server, "USER_DB", user_db)
    monkeypatch.setattr(server, "BACH_DB", bach_db)
    return user_db, bach_db


# ═══════════════════════════════════════════════════════════════
# DB HELPERS
# ═══════════════════════════════════════════════════════════════


class TestGetUserDb:
    def test_returns_connection_when_db_exists(self, fake_dbs):
        conn = server.get_user_db()
        assert conn is not None
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_raises_when_db_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "USER_DB", tmp_path / "nonexistent.db")
        with pytest.raises(FileNotFoundError):
            server.get_user_db()


class TestGetBachDb:
    def test_returns_connection_when_db_exists(self, fake_dbs):
        conn = server.get_bach_db()
        assert conn is not None
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_raises_when_db_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "BACH_DB", tmp_path / "nonexistent.db")
        with pytest.raises(FileNotFoundError):
            server.get_bach_db()


class TestRowToDict:
    def test_none_returns_none(self):
        assert server.row_to_dict(None) is None

    def test_converts_row(self, fake_dbs):
        conn = server.get_user_db()
        conn.execute("INSERT INTO tasks (title, status) VALUES ('test', 'open')")
        conn.commit()
        row = conn.execute("SELECT * FROM tasks LIMIT 1").fetchone()
        result = server.row_to_dict(row)
        assert isinstance(result, dict)
        assert result["title"] == "test"
        conn.close()


# ═══════════════════════════════════════════════════════════════
# EXCEPTION HANDLER (FileNotFoundError → 503)
# ═══════════════════════════════════════════════════════════════


class TestFileNotFoundHandler:
    def test_missing_user_db_returns_503(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "USER_DB", tmp_path / "nonexistent.db")
        resp = client.get("/api/status")
        assert resp.status_code == 503
        assert "nicht verfügbar" in resp.json()["detail"]

    def test_missing_bach_db_returns_503(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "BACH_DB", tmp_path / "nonexistent.db")
        monkeypatch.setattr(server, "USER_DB", tmp_path / "also_missing.db")
        resp = client.get("/api/status")
        assert resp.status_code == 503

    def test_valid_dbs_return_200(self, client, fake_dbs):
        resp = client.get("/api/status")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# STARTUP URL FORMAT
# ═══════════════════════════════════════════════════════════════


class TestStartupUrlFormat:
    def test_run_server_url_has_double_slash(self):
        """Verify the URL print uses http:// not http:/ (regression for slash bug)."""
        import inspect
        source = inspect.getsource(server)
        assert "http:/{host}" not in source or "http://{host}" in source


# ═══════════════════════════════════════════════════════════════
# CROSS-PLATFORM: creationflags & clipboard
# ═══════════════════════════════════════════════════════════════


class TestCrossPlatformGuards:
    """Verify cross-platform guards on subprocess calls."""

    def test_clipboard_windows_uses_powershell(self):
        import inspect
        source = inspect.getsource(server)
        assert 'sys.platform == "win32"' in source or "sys.platform == 'win32'" in source
        assert "powershell" in source

    def test_clipboard_macos_uses_pbcopy(self):
        import inspect
        source = inspect.getsource(server)
        assert "pbcopy" in source

    def test_clipboard_linux_uses_xclip(self):
        import inspect
        source = inspect.getsource(server)
        assert "xclip" in source

    def test_clipboard_linux_has_wayland_support(self):
        import inspect
        source = inspect.getsource(server)
        assert "wl-copy" in source, "Linux clipboard should support Wayland via wl-copy"

    def test_clipboard_linux_has_xsel_fallback(self):
        import inspect
        source = inspect.getsource(server)
        assert "xsel" in source, "Linux clipboard should support xsel as fallback"

    def test_terminal_launch_has_darwin_branch(self):
        import inspect
        source = inspect.getsource(server)
        assert '"darwin"' in source
        assert "osascript" in source, "macOS terminal launch should use osascript"

    def test_no_unguarded_creationflags(self):
        """Every creationflags=0x08000000 must be inside a win32 branch."""
        import inspect
        source = inspect.getsource(server)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "creationflags=0x08000000" in line:
                context = "\n".join(lines[max(0, i-10):i+1])
                assert 'win32' in context, (
                    f"Unguarded creationflags at approx line {i+1}"
                )


# ═══════════════════════════════════════════════════════════════
# SMOKE TESTS — real endpoint hits via TestClient
# ═══════════════════════════════════════════════════════════════


class TestSmokeEndpoints:
    """Hit actual endpoints — catches import errors, routing bugs, template crashes."""

    def test_chat_page_restores_history_from_runtime(self, client):
        """Leaving /chat must not lose the conversation: the page loads it back (1.1.7)."""
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "/history?chat_id=" in resp.text
        assert "loadHistory()" in resp.text

    def test_root_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert len(resp.text) > 1000

    def test_api_endpoints_page(self, client, fake_dbs):
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_static_css_or_js(self, client):
        resp = client.get("/static/style.css")
        assert resp.status_code in (200, 404)


class TestChatControlResolution:
    def test_chat_proxy_timeout_is_bounded_and_configurable(self, monkeypatch):
        monkeypatch.delenv("BACH_CHAT_PROXY_TIMEOUT_SECONDS", raising=False)
        assert server._chat_proxy_timeout() == 960.0

        monkeypatch.setenv("BACH_CHAT_PROXY_TIMEOUT_SECONDS", "45.5")
        assert server._chat_proxy_timeout() == 45.5

        monkeypatch.setenv("BACH_CHAT_PROXY_TIMEOUT_SECONDS", "ungültig")
        assert server._chat_proxy_timeout() == 960.0

        monkeypatch.setenv("BACH_CHAT_PROXY_TIMEOUT_SECONDS", "1")
        assert server._chat_proxy_timeout() == 10.0

    def test_uses_startspine_actual_control_port(self, tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        (runtime / "discovery.json").write_text(
            json.dumps({
                "root": str(server.BACH_DIR.parent),
                "services": {
                    "chat": {"host": "127.0.0.1", "actual_port": 8127},
                },
            }),
            encoding="utf-8",
        )
        monkeypatch.setenv("BACH_RUNTIME_DIR", str(runtime))

        assert server._chat_control_base_url() == "http://127.0.0.1:8127/api"

    def test_rejects_discovery_from_other_checkout(self, tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        (runtime / "discovery.json").write_text(
            json.dumps({
                "root": str(tmp_path / "other-checkout"),
                "services": {
                    "chat": {"host": "127.0.0.1", "actual_port": 8127},
                },
            }),
            encoding="utf-8",
        )
        monkeypatch.setenv("BACH_RUNTIME_DIR", str(runtime))

        assert server._chat_control_base_url() is None

    def test_chat_template_has_no_fixed_control_host_or_port(self):
        template = (server.TEMPLATES_DIR / "chat.html").read_text(encoding="utf-8")
        nav = (server.STATIC_DIR / "js" / "nav.js").read_text(encoding="utf-8")
        assert "const CHAT_API = '/api/chat-control'" in template
        assert "CHAT_HOST" not in template
        assert "CHAT_HOST" not in nav
        assert "macstudvonlukas" not in nav

    def test_chat_template_fails_closed_until_backend_is_available(self):
        template = (server.TEMPLATES_DIR / "chat.html").read_text(encoding="utf-8")

        assert 'id="send-btn" title="Backend wird geprüft" disabled' in template
        assert "let backendAvailable = false;" in template
        assert "readiness.available === true" in template
        assert "/readiness?chat_id=" in template
        assert "readiness.available !== true" in template
        assert "if (!text || sending || !backendAvailable || profileSelectionError) return;" in template


# Foreground HTTP cancellation across GUI, Control, runtime and private transport.
import asyncio
import importlib
import shutil
import threading
import types
from unittest.mock import AsyncMock
import httpx
from hub._services.llm.model_backend import OllamaBackend

@pytest.fixture
def http_disconnect_control_module(monkeypatch, tmp_path):
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

    from hub._services import chat as chat_package
    previous_attribute = vars(chat_package).get("telegram_chat")
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
    token = "test-control-token"
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN", token)
    original_post = httpx.post

    def _authorized_post(*args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        if "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        return original_post(*args, headers=headers, **kwargs)

    monkeypatch.setattr(httpx, "post", _authorized_post)

    module = importlib.import_module(module_name)
    try:
        yield module
    finally:
        sys.modules.pop(module_name, None)
        if previous_module is not None:
            sys.modules[module_name] = previous_module
        if previous_attribute is not None:
            chat_package.telegram_chat = previous_attribute
        elif hasattr(chat_package, "telegram_chat"):
            del chat_package.telegram_chat



@pytest.fixture
def disconnect_control_server(http_disconnect_control_module):
    """Real authenticated Control transport; no model or production service."""
    server = http_disconnect_control_module.QuietHTTPServer(("127.0.0.1", 0), http_disconnect_control_module.ControlHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def _prepare_http_request(base, module, *, device="7", chat_id="gui-web"):
    response = httpx.post(base + "/chat/request", json={
        "action": "prepare", "device_id": device, "chat_id": chat_id,
        "service_instance": module._WORKER_SERVICE_INSTANCE,
    }, timeout=3)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    binding = payload["binding"]
    assert binding["device_id"] == device
    assert binding["chat_id"] == chat_id
    assert binding["service_instance"] == module._WORKER_SERVICE_INSTANCE
    assert len(binding["request_id"]) >= 32
    assert len(binding["cancel_token"]) >= 32
    assert len(binding["slot_binding"]) == 64
    return binding


def test_http_disconnect_before_dispatch_prevents_late_prompt(
    disconnect_control_server, http_disconnect_control_module, monkeypatch,
):
    base = disconnect_control_server
    binding = _prepare_http_request(base, http_disconnect_control_module)
    called = []
    async def forbidden(*args, **kwargs):
        called.append(args)
        return "must not run"
    monkeypatch.setattr(http_disconnect_control_module.runtime, "process", forbidden)
    cancelled = httpx.post(base + "/chat/request",
        json={"action": "cancel", "binding": binding}, timeout=3)
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "aborted"
    assert cancelled.json()["cleanup_complete"] is True
    late = httpx.post(base + "/chat",
        json={"prompt": "must not be accepted", "chat_id": "gui-web", "_http_request": binding}, timeout=3)
    assert late.status_code == 409, late.text
    assert late.json()["reason_code"] == "http_disconnect"
    assert called == []


@pytest.mark.parametrize("field,value", [
    ("device_id", "8"), ("chat_id", "other"), ("service_instance", "previous-service"),
    ("request_id", "0" * 32), ("cancel_token", "not-the-private-token"),
    ("slot_binding", "0" * 64), ("chat_id", "fremd-ä"),
])
def test_http_disconnect_rejects_foreign_cancel_authority(
    disconnect_control_server, http_disconnect_control_module, field, value,
):
    base = disconnect_control_server
    binding = _prepare_http_request(base, http_disconnect_control_module)
    forged = dict(binding, **{field: value})
    response = httpx.post(base + "/chat/request",
        json={"action": "cancel", "binding": forged}, timeout=3)
    assert response.status_code == 409, response.text
    own = httpx.post(base + "/chat/request",
        json={"action": "status", "binding": binding}, timeout=3)
    assert own.json()["state"] == "prepared"
    assert own.json()["cancel_requested"] is False
    # Exact duplicate cancellation is idempotent only for this binding.
    first = httpx.post(base + "/chat/request", json={"action": "cancel", "binding": binding}, timeout=3)
    second = httpx.post(base + "/chat/request", json={"action": "cancel", "binding": binding}, timeout=3)
    assert first.json() == second.json()
    assert first.json()["state"] == "aborted"


def test_http_disconnect_rejects_stale_prepare_before_binding(disconnect_control_server):
    response = httpx.post(disconnect_control_server + "/chat/request", json={
        "action": "prepare", "device_id": "7", "chat_id": "gui-web",
        "service_instance": "previous-service",
    }, timeout=3)
    assert response.status_code == 409
    assert response.json()["reason_code"] == "http_request_binding_invalid"


def test_http_disconnect_binding_is_one_shot_and_late_cancel_is_harmless(
    disconnect_control_server, http_disconnect_control_module, monkeypatch,
):
    base = disconnect_control_server
    backend = OllamaBackend(default_model="m")
    monkeypatch.setattr(http_disconnect_control_module, "_snapshot_chat_backend", lambda *a, **kw: (backend, "m"))
    monkeypatch.setattr(http_disconnect_control_module, "_checked_backend_availability", lambda *a, **kw: (True, "ready"))
    monkeypatch.setattr(http_disconnect_control_module, "_chat_resource_readiness", lambda *a, **kw: None)
    calls = []
    async def process(prompt, chat_id, **kwargs):
        calls.append((prompt, chat_id))
        return "Confirmed result"
    monkeypatch.setattr(http_disconnect_control_module.runtime, "process", process)
    binding = _prepare_http_request(base, http_disconnect_control_module)
    payload = {"prompt": "once", "chat_id": "gui-web", "_http_request": binding}
    first = httpx.post(base + "/chat", json=payload, timeout=3)
    assert first.status_code == 200 and first.json()["ok"] is True
    duplicate = httpx.post(base + "/chat", json=payload, timeout=3)
    assert duplicate.status_code == 409
    assert calls == [("once", "gui-web")]
    late = httpx.post(base + "/chat/request", json={"action": "cancel", "binding": binding}, timeout=3)
    assert late.status_code == 200
    assert late.json()["state"] == "finished"
    assert late.json()["cancel_requested"] is False


def test_http_disconnect_slot_changed_before_dispatch_blocks_effect(
    disconnect_control_server, http_disconnect_control_module, monkeypatch,
):
    base = disconnect_control_server
    slot = {"id": "buddha_chat", "backend": "ollama", "model": "before"}
    monkeypatch.setattr(http_disconnect_control_module, "_resolve_slot_for_chat", lambda _chat: dict(slot))
    binding = _prepare_http_request(base, http_disconnect_control_module)
    slot["model"] = "after"
    effect = AsyncMock(return_value="must not run")
    monkeypatch.setattr(http_disconnect_control_module.runtime, "process", effect)
    response = httpx.post(base + "/chat",
        json={"prompt": "stale slot", "chat_id": "gui-web", "_http_request": binding}, timeout=3)
    assert response.status_code == 409
    assert response.json()["reason_code"] == "http_request_binding_invalid"
    effect.assert_not_awaited()


def _http_disconnect_runtime(http_disconnect_control_module, monkeypatch, tmp_path, backend):
    import sqlite3
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.chat.session_store import SQLiteChatSessionStore
    from hub import compute_lock
    database = tmp_path / "http-transcript.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE session_snapshots (id INTEGER PRIMARY KEY, "
            "session_id TEXT NOT NULL, snapshot_type TEXT NOT NULL, snapshot_data TEXT, "
            "name TEXT, created_at TEXT)")
    runtime = ChatRuntime(backend, session_store=SQLiteChatSessionStore(database))
    runtime.max_tool_rounds = 0
    monkeypatch.setattr(runtime, "_uses_local_compute", lambda _backend: False)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *a, **kw: None)
    monkeypatch.setattr(compute_lock, "get_effective_keep_alive", lambda **kw: "5m")
    monkeypatch.setattr(http_disconnect_control_module, "runtime", runtime)
    monkeypatch.setattr(http_disconnect_control_module, "_snapshot_chat_backend", lambda *a, **kw: (backend, "m"))
    monkeypatch.setattr(http_disconnect_control_module, "_checked_backend_availability", lambda *a, **kw: (True, "ready"))
    monkeypatch.setattr(http_disconnect_control_module, "_chat_resource_readiness", lambda *a, **kw: None)
    return runtime


@pytest.mark.parametrize("stalled_phase", ["before_headers", "empty_stream", "partial"])
def test_http_disconnect_control_closes_tcp_and_persists_once(
    disconnect_control_server, http_disconnect_control_module, monkeypatch, tmp_path, stalled_phase,
):
    """Real Control, runtime, SQLite store and stalled loopback Ollama socket."""
    async def scenario():
        sent, disconnected = asyncio.Event(), asyncio.Event()
        consumed = threading.Event()
        release = asyncio.Event()
        handlers = set()
        original_lines = httpx.Response.aiter_lines

        async def observed_lines(response):
            async for line in original_lines(response):
                yield line
                consumed.set()
        monkeypatch.setattr(httpx.Response, "aiter_lines", observed_lines)

        async def serve(reader, writer):
            task = asyncio.current_task()
            handlers.add(task)
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                              if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                if stalled_phase != "before_headers":
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
                                 b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                    if stalled_phase == "partial":
                        body = (json.dumps({"model": "m", "message": {"role": "assistant",
                                "content": "Persistierte Teilantwort"}, "done": False}) + "\n").encode()
                        writer.write(("%x\r\n" % len(body)).encode() + body + b"\r\n")
                    await writer.drain()
                sent.set()
                eof = asyncio.create_task(reader.read())
                finish = asyncio.create_task(release.wait())
                try:
                    done, _ = await asyncio.wait({eof, finish}, return_when=asyncio.FIRST_COMPLETED)
                    if eof in done and eof.result() == b"":
                        disconnected.set()
                finally:
                    for child in (eof, finish):
                        if not child.done():
                            child.cancel()
                    await asyncio.gather(eof, finish, return_exceptions=True)
            finally:
                writer.close()
                await writer.wait_closed()
                handlers.discard(task)

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        backend = OllamaBackend(base_url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                                default_model="m")
        runtime = _http_disconnect_runtime(http_disconnect_control_module, monkeypatch, tmp_path, backend)
        binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module, chat_id="http-fixture")
        request = None
        try:
            async with httpx.AsyncClient(headers={"Authorization": "Bearer test-control-token"}) as client:
                request = asyncio.create_task(client.post(disconnect_control_server + "/chat",
                    json={"prompt": "Keep this prompt", "chat_id": "http-fixture",
                          "_http_request": binding}, timeout=10))
                await asyncio.wait_for(sent.wait(), 3)
                if stalled_phase == "partial":
                    assert await asyncio.to_thread(consumed.wait, 2)
                cancel = await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "cancel", "binding": binding}, timeout=1)
                assert cancel.status_code == 200
                done, _ = await asyncio.wait({request}, timeout=1)
                assert request in done, "Control cancel did not end its own runtime/provider"
                response = request.result()
                assert response.status_code == 502
                assert response.json()["reason_code"] == "http_disconnect"
                assert response.json()["ok"] is False
                await asyncio.wait_for(disconnected.wait(), 1)
                state = (await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "status", "binding": binding})).json()
                assert state["state"] == "aborted" and state["cleanup_complete"] is True
                assert state["persisted"] is True
                messages = runtime.session_store.load("http-fixture")
                assert len(messages) == 2
                assert messages[0] == {"role": "user", "content": "Keep this prompt"}
                assert messages[1]["answer_status"] == "failed"
                assert messages[1]["reason_code"] == "http_disconnect"
                if stalled_phase == "partial":
                    assert "Persistierte Teilantwort" in messages[1]["content"]
                duplicate = await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "cancel", "binding": binding})
                assert duplicate.json() == state
                assert runtime.session_store.load("http-fixture") == messages
        finally:
            release.set()
            if request is not None:
                await asyncio.gather(request, return_exceptions=True)
            server.close()
            await server.wait_closed()
            if handlers:
                await asyncio.wait_for(asyncio.gather(*tuple(handlers), return_exceptions=True), 2)

    asyncio.run(scenario())


def test_http_disconnect_removes_own_waiter_without_accepting_prompt(
    disconnect_control_server, http_disconnect_control_module, monkeypatch, tmp_path,
):
    backend = OllamaBackend(default_model="m")
    runtime = _http_disconnect_runtime(http_disconnect_control_module, monkeypatch, tmp_path, backend)
    gate = runtime._chat_turn_gate("http-fixture")
    gate.clearing = True
    binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module, chat_id="http-fixture")

    async def scenario():
        request = None
        async with httpx.AsyncClient(headers={"Authorization": "Bearer test-control-token"}) as client:
            try:
                request = asyncio.create_task(client.post(disconnect_control_server + "/chat",
                    json={"prompt": "not accepted", "chat_id": "http-fixture",
                          "_http_request": binding}, timeout=10))
                for _ in range(100):
                    if http_disconnect_control_module._HTTP_REQUESTS.get(binding).owner is not None:
                        break
                    await asyncio.sleep(0.01)
                assert http_disconnect_control_module._HTTP_REQUESTS.get(binding).owner is not None
                await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "cancel", "binding": binding})
                done, _ = await asyncio.wait({request}, timeout=1)
                assert request in done, "Own foreground waiter survived a verified cancel"
                assert request.result().status_code == 409
                assert runtime.session_store.load("http-fixture") == []
                assert gate.clearing is True and gate.active_turns == 0
            finally:
                gate.clearing = False
                if request is not None:
                    await asyncio.gather(request, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("route", ["chat", "talk"])
def test_http_disconnect_real_gui_control_tcp_and_reconnect(
    disconnect_control_server, http_disconnect_control_module, monkeypatch, tmp_path, route,
):
    import socket
    import uvicorn
    from gui import server as gui

    async def scenario():
        consumed = threading.Event()
        stopped, second_started, resume, release = (
            asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event())
        handlers = set()
        calls = []
        original_lines = httpx.Response.aiter_lines

        async def observed_lines(response):
            async for line in original_lines(response):
                yield line
                consumed.set()
        monkeypatch.setattr(httpx.Response, "aiter_lines", observed_lines)

        async def model(reader, writer):
            task = asyncio.current_task()
            handlers.add(task)
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                              if line.lower().startswith(b"content-length:"))
                calls.append(json.loads(await reader.readexactly(length)))
                second = len(calls) > 1
                if second:
                    second_started.set()
                    await resume.wait()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
                             b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                content = "New request survived." if second else "Saved before browser left."
                body = (json.dumps({"model": "m", "message": {"role": "assistant",
                            "content": content}, "done": second}) + "\n").encode()
                writer.write(("%x\r\n" % len(body)).encode() + body + b"\r\n")
                if second:
                    writer.write(b"0\r\n\r\n")
                await writer.drain()
                if not second:
                    eof = asyncio.create_task(reader.read())
                    finish = asyncio.create_task(release.wait())
                    try:
                        done, _ = await asyncio.wait({eof, finish}, return_when=asyncio.FIRST_COMPLETED)
                        if eof in done and eof.result() == b"":
                            stopped.set()
                    finally:
                        for child in (eof, finish):
                            if not child.done():
                                child.cancel()
                        await asyncio.gather(eof, finish, return_exceptions=True)
            finally:
                writer.close()
                await writer.wait_closed()
                handlers.discard(task)

        provider = await asyncio.start_server(model, "127.0.0.1", 0)
        backend = OllamaBackend(base_url=f"http://127.0.0.1:{provider.sockets[0].getsockname()[1]}",
                                default_model="m")
        runtime = _http_disconnect_runtime(http_disconnect_control_module, monkeypatch, tmp_path, backend)
        monkeypatch.setattr(gui, "_chat_control_base_url", lambda: disconnect_control_server)
        monkeypatch.setattr(gui, "get_control_api_auth_header", lambda: "Bearer test-control-token")
        monkeypatch.setattr(gui, "validate_token",
                            lambda token: {"id": 7} if token == "browser-device-token" else None)
        monkeypatch.setattr(gui, "has_active_devices", lambda: True)
        monkeypatch.setattr(gui, "_TALK_CONFIG_FILE", tmp_path / "talk-config.json")
        monkeypatch.setattr(gui, "_TALK_SESSION_SINGLETON", None)
        if route == "talk":
            from dataclasses import dataclass
            from types import SimpleNamespace
            from hub._services import ocean_stack_bridge
            @dataclass
            class Reflex:
                backchannel_text: str = ""
                latency_budget_ms: int = 20
            class Engine:
                def __init__(self, initial_state, reflex, cortex):
                    self.state, self.reflex, self.cortex = initial_state, reflex, cortex
                def update_visual_state(self, changes):
                    for key, value in changes.items():
                        setattr(self.state, key, value)
                def process_turn(self, user_utterance):
                    answer = self.cortex.responder(user_utterance)
                    return SimpleNamespace(reflex=Reflex(), spoken_text=answer,
                        sentence_chunks=[answer], visual_state=vars(self.state),
                        applied_directives={})
            state = SimpleNamespace(persona="buddha", language="de", mode="listening",
                bound_slot="buddha_chat", fast_relay_model="fixture")
            shared = SimpleNamespace(state=state)
            module = SimpleNamespace(TalkEngine=Engine,
                FastReflexLoop=lambda model_name: SimpleNamespace(model_name=model_name),
                DeepCortexLoop=lambda responder: SimpleNamespace(responder=responder))
            monkeypatch.setattr(gui, "_get_talk_session", lambda: shared)
            monkeypatch.setattr(ocean_stack_bridge, "load_talk_module", lambda: module)
        original_get = http_disconnect_control_module.ControlHandler.do_GET
        def metadata(handler):
            if handler.path == "/api/status":
                handler._json({"service": "bach-chat-control", "telegram_verified": False})
            else:
                original_get(handler)
        monkeypatch.setattr(http_disconnect_control_module.ControlHandler, "do_GET", metadata)

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        application = uvicorn.Server(uvicorn.Config(
            gui.app, host="127.0.0.1", port=port, lifespan="off",
            log_level="error", access_log=False, timeout_graceful_shutdown=3))
        serving = asyncio.create_task(application.serve(sockets=[listener]))
        writer = None
        second_request = None
        try:
            for _ in range(100):
                if application.started:
                    break
                await asyncio.sleep(0.01)
            assert application.started
            path = "/api/chat-control/chat" if route == "chat" else "/api/talk/turn"
            payload = ({"prompt": "First request", "chat_id": "http-fixture"} if route == "chat"
                       else {"text": "Please answer this question."})
            body = json.dumps(payload).encode()
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write((f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                "Authorization: Bearer browser-device-token\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
            await writer.drain()
            assert await asyncio.to_thread(consumed.wait, 3), "GUI did not reach the real provider"
            first = next(iter(http_disconnect_control_module._HTTP_REQUESTS.entries.values()))
            old_binding = dict(first.binding)
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(stopped.wait(), 3)
            for _ in range(100):
                if first.snapshot()["state"] == "aborted":
                    break
                await asyncio.sleep(0.01)
            state = first.snapshot()
            assert state["state"] == "aborted" and state["cleanup_complete"] is True
            assert state["persisted"] is True
            history = runtime.session_store.load(old_binding["chat_id"])
            assert len(history) == 2 and history[-1]["reason_code"] == "http_disconnect"
            assert "Saved before browser left." in history[-1]["content"]

            async with httpx.AsyncClient() as client:
                second_request = asyncio.create_task(client.post(
                    f"http://127.0.0.1:{port}{path}", json=payload,
                    headers={"Authorization": "Bearer browser-device-token"}, timeout=5))
                await asyncio.wait_for(second_started.wait(), 3)
                late = await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "cancel", "binding": old_binding},
                    headers={"Authorization": "Bearer test-control-token"})
                assert late.status_code == 200
                assert not second_request.done()
                resume.set()
                response = await asyncio.wait_for(second_request, 3)
                assert response.status_code == 200, response.text
                assert "New request survived." in response.text
            history = runtime.session_store.load(old_binding["chat_id"])
            assert len(history) == 4
            assert history[-1]["answer_status"] == "success"
            assert sum(message.get("reason_code") == "http_disconnect" for message in history) == 1
        finally:
            release.set()
            resume.set()
            if writer is not None:
                writer.close()
            if second_request is not None:
                await asyncio.gather(second_request, return_exceptions=True)
            application.should_exit = True
            await asyncio.wait_for(serving, 5)
            listener.close()
            provider.close()
            await provider.wait_closed()
            if handlers:
                await asyncio.wait_for(asyncio.gather(*tuple(handlers), return_exceptions=True), 3)
    asyncio.run(scenario())


def test_http_disconnect_unmarked_control_tcp_half_close_is_not_cancel(
    disconnect_control_server, http_disconnect_control_module, monkeypatch,
):
    import socket
    backend = OllamaBackend(default_model="m")
    monkeypatch.setattr(http_disconnect_control_module, "_snapshot_chat_backend", lambda *a, **kw: (backend, "m"))
    monkeypatch.setattr(http_disconnect_control_module, "_checked_backend_availability", lambda *a, **kw: (True, "ready"))
    monkeypatch.setattr(http_disconnect_control_module, "_chat_resource_readiness", lambda *a, **kw: None)
    async def process(*args, **kwargs):
        await asyncio.sleep(0.05)
        return "Half-close kept the response readable."
    monkeypatch.setattr(http_disconnect_control_module.runtime, "process", process)
    from urllib.parse import urlsplit
    target = urlsplit(disconnect_control_server)
    body = json.dumps({"prompt": "complete body", "chat_id": "gui-web"}).encode()
    with socket.create_connection(("127.0.0.1", target.port), timeout=2) as client:
        client.sendall((f"POST /api/chat HTTP/1.1\r\nHost: localhost\r\n"
            "Authorization: Bearer test-control-token\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
        client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while chunk := client.recv(4096):
            response.extend(chunk)
    assert b"200 OK" in response
    assert b"Half-close kept the response readable." in response
    assert http_disconnect_control_module._HTTP_REQUESTS.entries == {}


def test_http_disconnect_unicode_binding_roundtrip(disconnect_control_server, http_disconnect_control_module):
    binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module,
                                    device="Gerät-7", chat_id="échange")
    response = httpx.post(disconnect_control_server + "/chat/request",
        json={"action": "cancel", "binding": binding}, timeout=2)
    assert response.status_code == 200
    assert response.json()["state"] == "aborted"


@pytest.mark.parametrize("receipt", [
    {"state": "stopped", "cleanup_verified": False},
    {"state": "resource_recovery_hold"},
    {"state": "loaded", "cleanup_verified": False},
])
def test_http_disconnect_warmup_never_promotes_missing_cleanup(
    disconnect_control_server, http_disconnect_control_module, monkeypatch, receipt,
):
    backend = OllamaBackend(default_model="m")
    monkeypatch.setattr(http_disconnect_control_module, "_snapshot_chat_backend", lambda *a, **kw: (backend, "m"))
    monkeypatch.setattr(http_disconnect_control_module, "_checked_backend_availability", lambda *a, **kw: (True, "ready"))
    monkeypatch.setattr(http_disconnect_control_module, "_chat_resource_readiness",
                        lambda *a, **kw: {"load_required": True, "status": "cold"})
    entered = threading.Event()
    async def warmup(*args, stop_event, **kwargs):
        entered.set()
        while not stop_event.is_set():
            await asyncio.sleep(0.01)
        return dict(receipt)
    monkeypatch.setattr(http_disconnect_control_module.runtime, "warm_chat_ollama_model", warmup)
    process = AsyncMock()
    monkeypatch.setattr(http_disconnect_control_module.runtime, "process", process)
    binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module)

    async def scenario():
        async with httpx.AsyncClient(headers={"Authorization": "Bearer test-control-token"}) as client:
            call = asyncio.create_task(client.post(disconnect_control_server + "/chat",
                json={"prompt": "must not be accepted", "chat_id": "gui-web", "_http_request": binding}))
            assert await asyncio.to_thread(entered.wait, 2)
            await client.post(disconnect_control_server + "/chat/request",
                              json={"action": "cancel", "binding": binding})
            result = await asyncio.wait_for(call, 1)
            assert result.status_code == 409
            state = (await client.post(disconnect_control_server + "/chat/request",
                json={"action": "status", "binding": binding})).json()
            assert state["state"] == "aborted"
            assert state["cleanup_complete"] is False, "Unverified native warmup cleanup was promoted to done"
            assert state["persisted"] is False
            process.assert_not_awaited()
    asyncio.run(scenario())


def test_http_disconnect_between_tools_prevents_the_next_effect(
    disconnect_control_server, http_disconnect_control_module, monkeypatch, tmp_path,
):
    from hub._services.chat import chat_runtime as runtime_module
    backend = OllamaBackend(default_model="m")
    effects = []
    model_calls = []
    async def chat(*args, **kwargs):
        model_calls.append(True)
        return {"content": "Planned tools", "tool_calls": [
            {"function": {"name": "first", "arguments": {}}},
            {"function": {"name": "second", "arguments": {}}},
        ]}
    monkeypatch.setattr(backend, "chat", chat)
    runtime = _http_disconnect_runtime(http_disconnect_control_module, monkeypatch, tmp_path, backend)
    runtime.max_tool_rounds = 2
    session = runtime.get_session("http-fixture")
    session.allow_tools, session.max_tool_rounds = True, 2
    definitions = [{"type": "function", "function": {
        "name": name, "description": "isolated fixture effect",
        "parameters": {"type": "object", "properties": {}}}} for name in ("first", "second")]
    monkeypatch.setattr(runtime_module, "tools_for_mode", lambda *a, **kw: definitions)
    binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module, chat_id="http-fixture")
    def execute(name, *args, **kwargs):
        effects.append(name)
        if name == "first":
            http_disconnect_control_module._HTTP_REQUESTS.get(binding).cancel()
        return "tool returned"
    monkeypatch.setattr(runtime_module, "exec_tool", execute)
    response = httpx.post(disconnect_control_server + "/chat",
        json={"prompt": "tools", "chat_id": "http-fixture", "_http_request": binding}, timeout=3)
    assert response.status_code == 502
    assert response.json()["reason_code"] == "http_disconnect"
    assert effects == ["first"], "A later synchronous tool effect escaped the request's stop boundary"
    assert len(model_calls) == 1
    assert runtime.session_store.load("http-fixture")[-1]["reason_code"] == "http_disconnect"


def test_http_disconnect_malformed_unicode_is_controlled_rejection(
    disconnect_control_server, http_disconnect_control_module,
):
    binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module)
    binding["chat_id"] = chr(0xD800)
    response = httpx.post(disconnect_control_server + "/chat/request",
        content=json.dumps({"action": "cancel", "binding": binding}).encode("ascii"),
        headers={"Content-Type": "application/json"}, timeout=2)
    assert response.status_code == 409
    assert response.json()["reason_code"] == "http_request_binding_invalid"

@pytest.mark.parametrize("cancel_ack", [True, False])
def test_http_disconnect_gui_uses_private_control_cancel(monkeypatch, cancel_ack):
    import asyncio
    from starlette.requests import Request

    async def scenario():
        seen, posted = [], asyncio.Event()
        release = asyncio.Event()
        receive_queue = asyncio.Queue()
        binding = {"device_id": "7", "chat_id": "gui-web", "service_instance": "epoch",
                   "request_id": "a" * 48, "cancel_token": "private", "slot_binding": "b" * 64}

        async def upstream(request):
            if request.url.path == "/api/status":
                return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})
            body = json.loads(request.content)
            seen.append((request.url.path, body, request.headers.get("authorization")))
            if request.url.path == "/api/chat/request":
                if body["action"] == "inspect":
                    return httpx.Response(200, json={"ok": True, "version": 1, "service_instance": "epoch"})
                if body["action"] == "prepare":
                    assert body["device_id"] == "7"
                    return httpx.Response(200, json={"ok": True, "binding": binding})
                if body["action"] == "cancel":
                    assert body["binding"] == binding
                    if cancel_ack:
                        release.set()
                        return httpx.Response(200, json={"ok": True, "state": "aborted", "cleanup_complete": True})
                    return httpx.Response(503, json={"ok": False})
            posted.set()
            await release.wait()
            return httpx.Response(502, json={"ok": False, "reason_code": "http_disconnect"})

        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
            transport=httpx.MockTransport(upstream), **kw))
        monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://control.invalid/api")
        monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer server-only")
        body = json.dumps({"prompt": "test", "chat_id": "gui-web"}).encode()
        await receive_queue.put({"type": "http.request", "body": body, "more_body": False})
        request = Request({"type": "http", "method": "POST", "path": "/api/chat-control/chat",
            "query_string": b"", "headers": [(b"content-type", b"application/json")],
            "state": {"device": {"id": 7}}}, receive=receive_queue.get)
        call = asyncio.create_task(server.chat_control_proxy("chat", request))
        try:
            await asyncio.wait_for(posted.wait(), 1)
            await receive_queue.put({"type": "http.disconnect"})
            done, _ = await asyncio.wait({call}, timeout=1)
            assert call in done, "ASGI disconnect did not send the private Control cancel"
            try:
                result = call.result()
                assert result.status_code == 499
            except server.HTTPException as exc:
                assert exc.status_code == 499
                assert exc.detail["cleanup_complete"] is cancel_ack
            chat_posts = [payload for path, payload, _ in seen if path == "/api/chat"]
            assert chat_posts[0]["_http_request"] == binding
            assert sum(payload.get("action") == "cancel" for _, payload, _ in seen) == 1
            assert all(auth == "Bearer server-only" for _, _, auth in seen)
        finally:
            release.set()
            await asyncio.gather(call, return_exceptions=True)
    asyncio.run(scenario())


def test_http_disconnect_gui_rejects_browser_supplied_authority(monkeypatch):
    from starlette.requests import Request
    import asyncio

    async def scenario():
        body = json.dumps({"prompt": "forged", "_http_request": {"cancel_token": "forged"}}).encode()
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/api/chat-control/chat",
            "query_string": b"", "headers": [], "state": {"device": {"id": 7}}}, receive=receive)
        monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://control.invalid/api")
        monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer server-only")
        calls = []
        async def upstream(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
            transport=httpx.MockTransport(upstream), **kw))
        try:
            await server.chat_control_proxy("chat", request)
        except server.HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Browser supplied Control authority was forwarded")
        assert "/api/chat" not in calls
    asyncio.run(scenario())


def test_http_disconnect_slot_change_during_preflight_is_rejected(
    disconnect_control_server, http_disconnect_control_module, monkeypatch,
):
    control = http_disconnect_control_module
    slot = {"id": "buddha_chat", "backend": "ollama", "model": "before"}
    monkeypatch.setattr(control, "_resolve_slot_for_chat", lambda _chat: dict(slot))
    backend = OllamaBackend(default_model="before")
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, "before"))
    def available(*args, **kwargs):
        slot["model"] = "after"
        return True, "ready"
    monkeypatch.setattr(control, "_checked_backend_availability", available)
    monkeypatch.setattr(control, "_chat_resource_readiness", lambda *a, **kw: None)
    process = AsyncMock(return_value="must not dispatch")
    monkeypatch.setattr(control.runtime, "process", process)
    binding = _prepare_http_request(disconnect_control_server, control)
    result = httpx.post(disconnect_control_server + "/chat",
        json={"prompt": "changed slot", "chat_id": "gui-web", "_http_request": binding}, timeout=2)
    assert result.status_code == 409
    assert result.json()["reason_code"] == "http_request_binding_invalid"
    process.assert_not_awaited()


@pytest.mark.parametrize("stalled_setup", ["status", "prepare"])
def test_http_disconnect_during_gui_setup_never_starts_model(monkeypatch, stalled_setup):
    from starlette.requests import Request

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        queue = asyncio.Queue()
        calls = []
        async def upstream(request):
            calls.append(request.url.path)
            action = json.loads(request.content).get("action") if request.content else None
            if ((stalled_setup == "status" and request.url.path == "/api/status")
                    or (stalled_setup == "prepare" and action == "prepare")):
                entered.set()
                await release.wait()
            if request.url.path == "/api/status":
                return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})
            if action == "inspect":
                return httpx.Response(200, json={"ok": True, "version": 1, "service_instance": "epoch"})
            if action == "prepare":
                return httpx.Response(200, json={"ok": True, "binding": {
                    "device_id": "7", "chat_id": "api-delegate", "service_instance": "epoch",
                    "request_id": "a" * 48, "cancel_token": "b" * 48, "slot_binding": "c" * 64}})
            return httpx.Response(200, json={"ok": True})
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
            transport=httpx.MockTransport(upstream), **kw))
        monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://control.invalid/api")
        monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer internal-only")
        await queue.put({"type": "http.request", "body": b'{"prompt":"test"}', "more_body": False})
        request = Request({"type": "http", "method": "POST", "path": "/api/chat-control/chat",
            "query_string": b"", "headers": [], "state": {"device": {"id": 7}}}, receive=queue.get)
        task = asyncio.create_task(server.chat_control_proxy("chat", request))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await queue.put({"type": "http.disconnect"})
            done, _ = await asyncio.wait({task}, timeout=1)
            assert task in done, "Disconnected GUI request remained stuck in Control preparation"
            with pytest.raises(server.HTTPException) as error:
                task.result()
            assert error.value.status_code == 499
            assert "/api/chat" not in calls
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_http_disconnect_preserves_positive_native_worker_trace_contract(http_disconnect_control_module):
    contract = http_disconnect_control_module._persistent_worker_trace_contract()
    assert isinstance(contract, dict)
    assert contract["schema"] == "bach.worker-tool-trace.v1"
    assert len(contract["source_sha256"]) == 64
    int(contract["source_sha256"], 16)


@pytest.mark.parametrize("confirmed_disconnect", [True, False])
def test_simultaneous_http_disconnect_and_control_transport_error(monkeypatch, confirmed_disconnect):
    """A failed completed I/O task is not a successful Control completion."""
    from starlette.requests import Request

    async def scenario():
        cancels = []
        binding = {"device_id": "7", "chat_id": "gui-web", "service_instance": "epoch",
                   "request_id": "a" * 48, "cancel_token": "b" * 48, "slot_binding": "c" * 64}
        async def receive():
            assert confirmed_disconnect
            return {"type": "http.disconnect"}
        request = Request({"type": "http", "method": "POST", "headers": [],
                           "state": {"device": {"id": 7}}}, receive=receive)
        bridge = server._GuiHttpChatRequest(request)
        async def upstream(request):
            if request.url.path == "/api/status":
                return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})
            payload = json.loads(request.content)
            if request.url.path == "/api/chat/request":
                if payload["action"] == "inspect":
                    return httpx.Response(200, json={"ok": True, "version": 1, "service_instance": "epoch"})
                if payload["action"] == "prepare":
                    return httpx.Response(200, json={"ok": True, "binding": binding})
                cancels.append(payload)
                return httpx.Response(200, json={"ok": True, "state": "aborting", "cleanup_complete": False})
            if confirmed_disconnect:
                # Consume the actual ASGI message before finishing the same
                # transport task with an error; both waiters are now ready.
                await bridge.watch()
            raise httpx.ReadError("isolated Control transport failure", request=request)
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
            transport=httpx.MockTransport(upstream), **kw))
        monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://control.invalid/api")
        monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer internal-only")
        with pytest.raises(server.HTTPException) as error:
            await bridge.post({"prompt": "test", "chat_id": "gui-web"})
        assert error.value.status_code == (499 if confirmed_disconnect else 503)
        assert cancels == ([{"action": "cancel", "binding": binding}] if confirmed_disconnect else [])
        if confirmed_disconnect:
            assert error.value.detail["cleanup_complete"] is False
    asyncio.run(scenario())


@pytest.mark.parametrize("stop_result", ["exception", "partial_result"])
def test_http_disconnect_during_summary_preserves_history_and_hides_internal_partial(
    disconnect_control_server, http_disconnect_control_module, monkeypatch, tmp_path, stop_result,
):
    """A cancelled internal call cannot become a user answer or discard old turns."""
    from hub._services.chat.http_request_control import HttpRequestDisconnected

    chat_id = "http-summary-fixture"
    backend = OllamaBackend(default_model="m")
    runtime = _http_disconnect_runtime(http_disconnect_control_module, monkeypatch, tmp_path, backend)
    runtime.MAX_MESSAGES = 1
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"Prior turn {index}"}
        for index in range(6)
    ]
    session = runtime.get_session(chat_id)
    session.messages = list(history)
    runtime._persist_session(chat_id, session)
    history = runtime.session_store.load(chat_id)
    session.messages = list(history)
    started = threading.Event()
    calls = []

    async def summary(messages, **kwargs):
        assert "_http_capture_partial" not in kwargs
        calls.append(messages)
        assert messages[0]["content"] == "Fasse den Gesprächsverlauf in 2-3 Sätzen zusammen."
        started.set()
        await kwargs["cancel_event"].wait()
        if stop_result == "exception":
            raise HttpRequestDisconnected()
        return {"content": "INTERNAL SUMMARY FRAGMENT", "error": "request stopped",
                "reason_code": "http_disconnect", "tool_calls": None}

    monkeypatch.setattr(backend, "chat", summary)
    binding = _prepare_http_request(disconnect_control_server, http_disconnect_control_module,
                                    chat_id=chat_id)

    async def scenario():
        async with httpx.AsyncClient(headers={"Authorization": "Bearer test-control-token"}) as client:
            pending = asyncio.create_task(client.post(disconnect_control_server + "/chat", json={
                "prompt": "Keep the accepted new prompt", "chat_id": chat_id,
                "_http_request": binding}, timeout=5))
            try:
                assert await asyncio.to_thread(started.wait, 2), "internal summary did not start"
                cancelled = await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "cancel", "binding": binding}, timeout=2)
                assert cancelled.status_code == 200
                response = await asyncio.wait_for(pending, 2)
                assert response.status_code == 502, response.text
                assert response.json()["reason_code"] == "http_disconnect"
                state = (await client.post(disconnect_control_server + "/chat/request",
                    json={"action": "status", "binding": binding})).json()
                assert state["state"] == "aborted" and state["persisted"] is True
                assert state["cleanup_complete"] is False  # This fake provider supplies no close proof.
                stored = runtime.session_store.load(chat_id)
                assert all("INTERNAL SUMMARY FRAGMENT" not in item["content"] for item in stored)
                assert stored[:len(history)] == history
                assert len(stored) == len(history) + 2
                assert stored[-2] == {"role": "user", "content": "Keep the accepted new prompt"}
                assert stored[-1]["answer_status"] == "failed"
                assert stored[-1]["reason_code"] == "http_disconnect"
                assert session.messages[:len(history)] == history
                assert len(session.messages) == len(stored)
                assert str(session.messages[-1]["content"]) == stored[-1]["content"]
                assert len(calls) == 1, "the user-answer dispatch must not start after the summary stop"
            finally:
                await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())
