# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for GuiHandler (hub/gui.py)."""

import sys
import socket
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def gui_env(tmp_path):
    """Create minimal BACH directory with gui structure."""
    (tmp_path / "data").mkdir()
    gui_dir = tmp_path / "gui"
    gui_dir.mkdir()
    (gui_dir / "templates").mkdir()
    (gui_dir / "static" / "css").mkdir(parents=True)
    (gui_dir / "static" / "js").mkdir(parents=True)
    (gui_dir / "server.py").write_text("# mock server", encoding="utf-8")
    # Create some template/static files
    (gui_dir / "templates" / "index.html").write_text("<html>", encoding="utf-8")
    (gui_dir / "templates" / "tasks.html").write_text("<html>", encoding="utf-8")
    (gui_dir / "static" / "css" / "style.css").write_text("body{}", encoding="utf-8")
    (gui_dir / "static" / "js" / "nav.js").write_text("//nav", encoding="utf-8")
    (gui_dir / "static" / "js" / "api.js").write_text("//api", encoding="utf-8")
    return tmp_path


@pytest.fixture
def handler(gui_env):
    from hub.gui import GuiHandler
    return GuiHandler(gui_env)


class TestGuiHandlerInit:
    def test_init(self, handler, gui_env):
        assert handler.gui_dir == gui_env / "gui"
        assert handler.server_script == gui_env / "gui" / "server.py"

    def test_profile_name(self, handler):
        assert handler.profile_name == "gui"

    def test_target_file(self, handler, gui_env):
        assert handler.target_file == gui_env / "gui"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "start" in ops
        assert "start-bg" in ops
        assert "status" in ops
        assert "info" in ops


class TestHandleRouting:
    def test_start_dry_run(self, handler):
        ok, msg = handler.handle("start", [], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg
        assert "8000" in msg

    def test_start_custom_port_dry_run(self, handler):
        ok, msg = handler.handle("start", ["--port", "9000"], dry_run=True)
        assert ok
        assert "9000" in msg

    def test_start_bg_dry_run(self, handler):
        ok, msg = handler.handle("start-bg", [], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_start_bg_custom_port_dry_run(self, handler):
        ok, msg = handler.handle("start-bg", ["--port", "9999"], dry_run=True)
        assert ok
        assert "9999" in msg

    def test_unknown_operation_shows_info(self, handler):
        ok, msg = handler.handle("foobar", [])
        assert ok
        assert "GUI INFO" in msg

    def test_empty_operation_shows_info(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "GUI INFO" in msg


class TestStartServer:
    def test_missing_script(self, gui_env):
        from hub.gui import GuiHandler
        handler = GuiHandler(gui_env)
        handler.server_script = gui_env / "gui" / "nonexistent.py"
        ok, msg = handler._start_server(8000, dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg

    def test_missing_uvicorn(self, handler):
        with patch.dict(sys.modules, {"uvicorn": None}):
            ok, msg = handler._start_server(8000, dry_run=False)
            assert not ok
            assert "uvicorn" in msg


class TestStartBackground:
    def test_missing_script(self, gui_env):
        from hub.gui import GuiHandler
        handler = GuiHandler(gui_env)
        handler.server_script = gui_env / "gui" / "nonexistent.py"
        ok, msg = handler._start_background(8000, dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg

    def test_already_running(self, handler):
        with patch("socket.socket") as mock_sock:
            instance = MagicMock()
            instance.connect_ex.return_value = 0
            mock_sock.return_value = instance
            ok, msg = handler._start_background(8000, dry_run=False)
            assert ok
            assert "laeuft bereits" in msg

    def test_waits_for_delayed_port_readiness(self, handler):
        with patch.object(handler, "_is_port_open", side_effect=[False, False, True]):
            with patch("subprocess.Popen") as mock_popen:
                with patch("hub.gui.time.sleep", return_value=None):
                    ok, msg = handler._start_background(8000, dry_run=False)

        assert ok
        assert "GUI Server gestartet" in msg
        mock_popen.assert_called_once()


class TestPortPidLookup:
    def test_find_pid_on_port_windows_localized_netstat(self, handler):
        localized_netstat = (
            "  TCP    127.0.0.1:8000         0.0.0.0:0              ABHÖREN         169292\n"
            "  TCP    127.0.0.1:58397        127.0.0.1:8000         WARTEND         0\n"
        )
        mock_result = MagicMock(stdout=localized_netstat)

        with patch("hub.gui.sys.platform", "win32"):
            with patch("subprocess.run", return_value=mock_result):
                pid = handler._find_pid_on_port(8000)

        assert pid == 169292


class TestShowStatus:
    def test_status_online(self, handler):
        with patch("socket.socket") as mock_sock:
            instance = MagicMock()
            instance.connect_ex.return_value = 0
            mock_sock.return_value = instance
            ok, msg = handler._show_status()
            assert ok
            assert "ONLINE" in msg

    def test_status_offline(self, handler):
        with patch("socket.socket") as mock_sock:
            instance = MagicMock()
            instance.connect_ex.return_value = 1
            mock_sock.return_value = instance
            ok, msg = handler._show_status()
            assert ok
            assert "OFFLINE" in msg


class TestShowInfo:
    def test_info_content(self, handler):
        ok, msg = handler._show_info()
        assert ok
        assert "GUI INFO" in msg
        assert "Templates: 2" in msg
        assert "CSS:       1" in msg
        assert "JS:        2" in msg

    def test_info_missing_dirs(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "gui").mkdir()
        (tmp_path / "gui" / "server.py").write_text("", encoding="utf-8")
        from hub.gui import GuiHandler
        handler = GuiHandler(tmp_path)
        ok, msg = handler._show_info()
        assert ok
        assert "Templates: 0" in msg
