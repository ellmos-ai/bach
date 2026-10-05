"""Tests fuer gui/shell.py (GUI-Schale; Quelle QUEUED 652455601, Task #1410).

Deckt ab: parse_gui_url, check_health, connect_or_start (laufender Server und
Kind-Prozess-Start), run()-Ablauf inkl. Assignment-Aktivitaetshistorie,
AssignmentDenied fuer unbekannte Rolle / ungueltigen Modus, Server-Start-Fehler
(error), window_open_failed (released) sowie from_env/main-Smoketests
(--check-only up/down).
"""

import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui.shell import GUIShell, main, parse_gui_url  # noqa: E402
from hub._services.chat.slots_config import (  # noqa: E402
    get_activity_history,
    initialize_slots_config,
)

BODY_OK = b'{"status":"ok"}'

# Inline-HTTP-Server-Skript fuer den Kind-Prozess-Test (200 auf jedem GET;
# python -m http.server unbrauchbar, da /api/status dort 404 liefert).
INLINE_SERVER_SCRIPT = r'''
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status": "ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


port = int(sys.argv[1])
HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY_OK)))
        self.end_headers()
        self.wfile.write(BODY_OK)

    def log_message(self, fmt, *args):
        pass


@pytest.fixture
def live_server_port():
    """Thread-HTTP-Server auf ephemerem Port; liefert die Portnummer."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("BACH_GUI_URL", "BACH_GUI_HOST", "BACH_GUI_PORT"):
        monkeypatch.delenv(name, raising=False)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stop(shell):
    process = getattr(shell, "process", None)
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _init_cfg(tmp_path):
    cfg_file = tmp_path / "slots.json"
    initialize_slots_config(str(cfg_file))
    return str(cfg_file)


# ---------------------------------------------------------------- parse_gui_url


def test_parse_gui_url_variants():
    assert parse_gui_url("http://127.0.0.1:8123") == ("127.0.0.1", 8123)
    assert parse_gui_url("http://127.0.0.1:8123/") == ("127.0.0.1", 8123)
    assert parse_gui_url("http://localhost:8080/api/status") == ("localhost", 8080)
    assert parse_gui_url("localhost:9/") == ("localhost", 9)
    assert parse_gui_url("localhost") == ("localhost", 80)


# ------------------------------------------------------- check_health / connect


def test_check_health_up(live_server_port):
    shell = GUIShell(host="127.0.0.1", port=live_server_port)
    assert shell.check_health() is True


def test_check_health_down():
    shell = GUIShell(host="127.0.0.1", port=_free_port())
    assert shell.check_health(timeout=1.0) is False


def test_connect_or_start_running_server(live_server_port):
    shell = GUIShell(host="127.0.0.1", port=live_server_port)
    result = shell.connect_or_start()
    assert result["connected"] is True
    assert result["started"] is False
    assert result["url"] == shell.base_url
    assert result["error"] == ""


def test_connect_or_start_starts_child_process(tmp_path):
    port = _free_port()
    command = [sys.executable, "-c", INLINE_SERVER_SCRIPT, str(port)]
    shell = GUIShell(
        host="127.0.0.1",
        port=port,
        server_command=command,
        log_dir=tmp_path / "logs",
        start_timeout=15.0,
        poll_interval=0.2,
    )
    try:
        result = shell.connect_or_start()
        assert result["connected"] is True
        assert result["started"] is True
        assert result["error"] == ""
    finally:
        _stop(shell)
    assert shell.process is not None
    assert shell.process.poll() is not None
    assert (tmp_path / "logs" / "gui_shell.log").exists()


# ------------------------------------------------------------------- run()-flow


def test_run_full_flow(tmp_path, live_server_port):
    cfg_path = _init_cfg(tmp_path)
    shell = GUIShell(
        host="127.0.0.1",
        port=live_server_port,
        opener=lambda url: True,
        slots_config_path=cfg_path,
    )
    result = shell.run(task_id="1410", open_window=True)
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["connected"] is True
    assert result["started"] is False
    assert result["window_opened"] is True
    assert result["assignment_id"]
    assert result["error"] == ""
    assert result["url"] == shell.base_url

    history = get_activity_history(limit=10, path=cfg_path)
    assert len(history) == 2
    end = history[0]
    start = history[1]
    assert start["event"] == "assignment_started"
    assert end["event"] == "assignment_ended"
    assert end["assignment_id"] == start["assignment_id"]
    assert end["assignment_id"] == result["assignment_id"]
    assert end["result"] == "gui_ready"
    assert end["ended_at"]
    assert start["slot_id"] == "gui_shell"
    assert start["role_id"] == "expert_role"
    assert start["status"] == "running"


def test_run_completed_without_window(tmp_path, live_server_port):
    cfg_path = _init_cfg(tmp_path)
    shell = GUIShell(
        host="127.0.0.1",
        port=live_server_port,
        slots_config_path=cfg_path,
    )
    result = shell.run(task_id="1410", open_window=False)
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["connected"] is True
    assert result["window_opened"] is False


def test_run_window_open_failed(tmp_path, live_server_port):
    cfg_path = _init_cfg(tmp_path)
    shell = GUIShell(
        host="127.0.0.1",
        port=live_server_port,
        opener=lambda url: False,
        slots_config_path=cfg_path,
    )
    result = shell.run(task_id="1410", open_window=True)
    assert result["ok"] is False
    assert result["status"] == "released"
    assert result["connected"] is True
    assert result["window_opened"] is False
    assert result["assignment_id"]
    history = get_activity_history(limit=10, path=cfg_path)
    assert history[0]["result"] == "window_open_failed"
    assert history[0]["assignment_id"] == result["assignment_id"]


def test_run_denied_unknown_role(tmp_path):
    cfg_path = _init_cfg(tmp_path)
    shell = GUIShell(
        role_id="not-registered",
        slots_config_path=cfg_path,
        start_timeout=1.0,
    )
    result = shell.run(task_id="1410", open_window=False)
    assert result["ok"] is False
    assert result["status"] == "denied"
    assert result["connected"] is False
    assert result["assignment_id"] == ""
    assert "AssignmentDenied" in result["error"]
    history = get_activity_history(limit=10, path=cfg_path)
    assert not [e for e in history if e.get("event") == "assignment_started"]


def test_run_denied_invalid_mode(tmp_path):
    cfg_path = _init_cfg(tmp_path)
    shell = GUIShell(
        mode="turbo",
        slots_config_path=cfg_path,
        start_timeout=1.0,
    )
    result = shell.run(task_id="1410", open_window=False)
    assert result["ok"] is False
    assert result["status"] == "denied"
    assert result["assignment_id"] == ""


def test_run_server_start_fails(tmp_path):
    cfg_path = _init_cfg(tmp_path)
    shell = GUIShell(
        host="127.0.0.1",
        port=_free_port(),
        server_command=[sys.executable, "-c", "import sys; sys.exit(3)"],
        slots_config_path=cfg_path,
        log_dir=tmp_path / "logs",
        start_timeout=2.0,
    )
    result = shell.run(task_id="1410", open_window=False)
    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["connected"] is False
    assert result["window_opened"] is False
    assert "exit" in result["error"]
    assert result["assignment_id"]
    history = get_activity_history(limit=10, path=cfg_path)
    end = history[0]
    assert end["event"] == "assignment_ended"
    assert end["result"] == "gui_connect_failed"
    assert end["assignment_id"] == result["assignment_id"]


# ------------------------------------------------------------------ from_env/main


def test_from_env_url(clean_env, monkeypatch):
    monkeypatch.setenv("BACH_GUI_URL", "http://127.0.0.1:8123")
    shell = GUIShell.from_env()
    assert shell.host == "127.0.0.1"
    assert shell.port == 8123


def test_from_env_host_port(clean_env, monkeypatch):
    monkeypatch.setenv("BACH_GUI_HOST", "127.0.0.1")
    monkeypatch.setenv("BACH_GUI_PORT", "8124")
    shell = GUIShell.from_env()
    assert shell.host == "127.0.0.1"
    assert shell.port == 8124


def test_from_env_defaults(clean_env):
    shell = GUIShell.from_env()
    assert shell.host == "127.0.0.1"
    assert shell.port == 8000


def test_main_check_only_up(clean_env, live_server_port, capsys):
    rc = main(["--check-only", "--host", "127.0.0.1", "--port", str(live_server_port)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["url"] == f"http://127.0.0.1:{live_server_port}"


def test_main_check_only_down(clean_env, capsys):
    port = _free_port()
    rc = main(["--check-only", "--host", "127.0.0.1", "--port", str(port)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["status"] == "down"


def test_main_url_default_from_env(clean_env, monkeypatch, live_server_port, capsys):
    monkeypatch.setenv("BACH_GUI_URL", f"http://127.0.0.1:{live_server_port}")
    rc = main(["--check-only"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["ok"] is True