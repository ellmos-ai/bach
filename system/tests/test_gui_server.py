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

        async def get(self, url, **kwargs):
            return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})

        async def request(self, method, url, **kwargs):
            seen.append((method, url, dict(kwargs["params"])))
            return httpx.Response(200, json=payload)

    monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://127.0.0.1:8127/api")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: Upstream())
    response = client.get(f"/api/chat-control/{path}?chat_id=gui-web")
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
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN", "test-control-token")
    return TestClient(server.app, raise_server_exceptions=False, headers={"Authorization": "Bearer test-control-token"})


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
    monkeypatch.setattr("gui.task_db.BACH_DB", bach_db)
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
# API ROUTES - AGENTS / AVATAR / ANIMUS MATRIX
# ═══════════════════════════════════════════════════════════════


class TestAvatarAnimusMatrix:
    """Tests fuer die Avatar-Agenten DB-Migration und Animuns-Matrix Endpunkte."""

    def test_avatar_agents_migrated_to_bach_agents(self, client, fake_dbs, monkeypatch):
        """Lifespan soll die DEFAULT_AVATAR_AGENTS in bach_agents anlegen."""
        from gui.task_db import DEFAULT_AVATAR_AGENTS, _init_bach_agents, get_bach_db

        # Direkte Initialisierung, damit Schema vorhanden ist
        conn = get_bach_db()
        _init_bach_agents(conn)
        for avatar in DEFAULT_AVATAR_AGENTS:
            row = conn.execute(
                "SELECT * FROM bach_agents WHERE name = ?", (avatar["name"],)
            ).fetchone()
            assert row is not None, f"Avatar {avatar['name']} fehlt in bach_agents"
            assert row["animus"] == avatar["animus"]
            assert row["session_hook"] == avatar["session_hook"]
            assert row["taskboard_id"] == avatar["taskboard_id"]
            assert row["taskboard_default"] == avatar["taskboard_default"]
        conn.close()

    def test_api_agents_contains_animus_fields(self, client, fake_dbs):
        from gui.task_db import DEFAULT_AVATAR_AGENTS, _init_bach_agents, get_bach_db, upsert_bach_agent
        conn = get_bach_db()
        _init_bach_agents(conn)
        for avatar in DEFAULT_AVATAR_AGENTS:
            upsert_bach_agent(conn, avatar)
        conn.close()

        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        names = {a["name"] for a in data["agents"]}
        for avatar in DEFAULT_AVATAR_AGENTS:
            assert avatar["name"] in names
        claude = next(a for a in data["agents"] if a["name"] == "claude")
        assert claude.get("animus") == "subscription"
        assert claude.get("session_hook") == "claude://session"
        assert claude.get("taskboard_id") == "claude-board"
        assert claude.get("taskboard_default") in (1, True)

    def test_api_assignees_loads_avatars_from_db(self, client, fake_dbs):
        from gui.task_db import DEFAULT_AVATAR_AGENTS, _init_bach_agents, get_bach_db, upsert_bach_agent
        conn = get_bach_db()
        _init_bach_agents(conn)
        for avatar in DEFAULT_AVATAR_AGENTS:
            upsert_bach_agent(conn, avatar)
        conn.close()

        resp = client.get("/api/assignees")
        assert resp.status_code == 200
        data = resp.json()
        avatar_entries = [a for a in data["assignees"] if a["type"] == "avatar"]
        names = {a["name"] for a in avatar_entries}
        for avatar in DEFAULT_AVATAR_AGENTS:
            assert avatar["name"] in names
        claude = next(a for a in avatar_entries if a["name"] == "claude")
        assert claude.get("session_hook") == "claude://session"
        assert claude.get("taskboard_id") == "claude-board"

    def test_api_presence_returns_session_hook_and_taskboard(self, client, fake_dbs):
        from gui.task_db import DEFAULT_AVATAR_AGENTS, _init_bach_agents, get_bach_db, upsert_bach_agent
        conn = get_bach_db()
        _init_bach_agents(conn)
        for avatar in DEFAULT_AVATAR_AGENTS:
            upsert_bach_agent(conn, avatar)
        conn.close()

        resp = client.post("/api/presence", json={
            "partner_name": "claude",
            "status": "online",
            "session_id": "sess-123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "online"
        assert data["session_hook"] == "claude://session"
        assert data["taskboard_id"] == "claude-board"
        assert data["taskboard_default"] in (1, True)

    def test_api_taskboards_and_assignment_endpoints(self, client, fake_dbs):
        from gui.task_db import DEFAULT_AVATAR_AGENTS, _init_bach_agents, get_bach_db, upsert_bach_agent
        conn = get_bach_db()
        _init_bach_agents(conn)
        for avatar in DEFAULT_AVATAR_AGENTS:
            upsert_bach_agent(conn, avatar)
        conn.close()

        # Alle Taskboards auflisten
        resp = client.get("/api/taskboards")
        assert resp.status_code == 200
        boards = resp.json()["taskboards"]
        board_ids = {b["id"] for b in boards}
        assert "claude-board" in board_ids

        # Agent-ID ermitteln
        agents = client.get("/api/agents").json()["agents"]
        gemini = next(a for a in agents if a["name"] == "gemini")

        # Session-Hook aendern
        resp = client.post(f"/api/agents/{gemini['id']}/session-hook", json={
            "session_hook": "gemini://session-v2",
        })
        assert resp.status_code == 200
        assert resp.json()["agent"]["session_hook"] == "gemini://session-v2"

        # Taskboard zuweisen
        resp = client.post(f"/api/agents/{gemini['id']}/taskboard", json={
            "taskboard_id": "gemini-board-v2",
            "taskboard_default": True,
        })
        assert resp.status_code == 200
        agent = resp.json()["agent"]
        assert agent["taskboard_id"] == "gemini-board-v2"
        assert agent["taskboard_default"] in (1, True)


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
        assert "if (!text || sending || !backendAvailable) return;" in template
