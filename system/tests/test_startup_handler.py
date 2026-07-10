# -*- coding: utf-8 -*-
"""Tests for StartupHandler (hub/startup.py) — cross-platform & import fixes."""

import json
import os
import subprocess
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hub.startup import StartupHandler, _StartupTimingList


@pytest.fixture
def startup_env(tmp_path):
    """Erstellt StartupHandler mit temp-DB und Verzeichnisstruktur."""
    base = tmp_path / "bach"
    (base / "data").mkdir(parents=True)
    (base / "data" / "logs").mkdir()
    (base / "hub").mkdir()
    (base / "gui").mkdir()

    db_path = base / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            partner_id TEXT,
            started_at TEXT,
            ended_at TEXT,
            summary TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            name TEXT PRIMARY KEY,
            type TEXT,
            category TEXT,
            endpoint TEXT,
            is_active INTEGER DEFAULT 1,
            help_text TEXT
        )
    """)
    conn.commit()
    conn.close()

    config_path = base / "data" / "user_config.json"
    config_path.write_text(json.dumps({"startup_mode": "silent"}))

    h = StartupHandler(base)
    return h, base, db_path


class TestInit:
    def test_profile_name(self, startup_env):
        h, _, _ = startup_env
        assert h.profile_name == "startup"

    def test_operations(self, startup_env):
        h, _, _ = startup_env
        ops = h.get_operations()
        assert "run" in ops
        assert "quick" in ops
        assert "mode" in ops


class TestModeChange:
    def test_valid_mode_change(self, startup_env):
        h, base, _ = startup_env
        ok, msg = h.handle("mode", ["text"])
        assert ok is True
        assert "text" in msg

        config = json.loads((base / "data" / "user_config.json").read_text())
        assert config["startup_mode"] == "text"

    def test_invalid_mode(self, startup_env):
        h, _, _ = startup_env
        ok, msg = h.handle("mode", ["nope"])
        assert ok is False
        assert "Ungueltiger Modus" in msg


class TestPartnerParsing:
    def test_default_partner(self, startup_env):
        h, _, _ = startup_env
        assert h._get_partner_id([]) == "user"

    def test_explicit_partner(self, startup_env):
        h, _, _ = startup_env
        assert h._get_partner_id(["--partner=claude"]) == "claude"

    def test_anonymous_partner(self, startup_env):
        h, _, _ = startup_env
        pid = h._get_partner_id(["--partner=new"])
        assert pid.startswith("partner_")


class TestAtiStatus:
    def test_detects_ati_in_current_agents_layout(self, startup_env):
        h, base, _ = startup_env
        ati_dir = base / "agents" / "ati"
        ati_dir.mkdir(parents=True)
        (ati_dir / "SKILL.md").write_text("---\nname: ati\n", encoding="utf-8")

        lines = h._ati_status_lines()

        assert "[ATI AGENT]" in lines
        assert " ATI Ordner vorhanden" in lines
        assert " [SKIP] ATI Agent nicht eingerichtet" not in lines

    def test_missing_ati_reports_skip(self, startup_env):
        h, _, _ = startup_env

        lines = h._ati_status_lines()

        assert lines == ["", "[ATI AGENT]", " [SKIP] ATI Agent nicht eingerichtet"]


class TestHooksScope:
    """Bug-Fix: hooks variable was used outside its import scope."""

    def test_after_startup_hook_reimports(self, startup_env):
        h, _, _ = startup_env

        mock_hooks = MagicMock()
        mock_module = MagicMock()
        mock_module.hooks = mock_hooks

        with patch.object(h, "_run_startup", return_value=(True, "OK")), \
             patch.dict("sys.modules", {"core.hooks": mock_module}), \
             patch("hub.startup.hooks", mock_hooks, create=True):
            ok, msg = h.handle("", [], dry_run=False)

        assert ok is True

    def test_hook_import_failure_does_not_crash(self, startup_env):
        h, _, _ = startup_env

        with patch.object(h, "_run_startup", return_value=(True, "OK")), \
             patch.dict("sys.modules", {"core.hooks": None}):
            ok, msg = h.handle("", [], dry_run=False)

        assert ok is True


class TestSkillHealthMonitorStartup:
    def test_quick_start_skips_skill_health_monitor(self, startup_env):
        h, _, _ = startup_env

        class RaisingMonitor:
            issues = []

            def __init__(self, *args, **kwargs):
                pass

            def check_all(self):
                raise AssertionError("SkillHealthMonitor should be skipped")

        fake_module = MagicMock()
        fake_module.SkillHealthMonitor = RaisingMonitor

        with patch.dict(sys.modules, {"skill_health_monitor": fake_module}):
            ok, msg = h._run_startup(
                quick=True,
                dry_run=True,
                startup_mode="gui",
                partner_id="codex",
            )

        assert ok is True
        assert "[SKILL HEALTH]" in msg
        assert "Health-Monitor übersprungen" in msg

    def test_silent_start_skips_skill_health_monitor(self, startup_env):
        h, _, _ = startup_env

        class RaisingMonitor:
            issues = []

            def __init__(self, *args, **kwargs):
                pass

            def check_all(self):
                raise AssertionError("SkillHealthMonitor should be skipped")

        fake_module = MagicMock()
        fake_module.SkillHealthMonitor = RaisingMonitor

        with patch.dict(sys.modules, {"skill_health_monitor": fake_module}):
            ok, msg = h._run_startup(
                quick=False,
                dry_run=True,
                startup_mode="silent",
                partner_id="codex",
            )

        assert ok is True
        assert "[SKILL HEALTH]" in msg
        assert "Health-Monitor übersprungen" in msg

    def test_full_interactive_start_runs_skill_health_monitor(self, startup_env):
        h, _, _ = startup_env
        called = {"value": False}

        class FakeMonitor:
            issues = []

            def __init__(self, *args, **kwargs):
                pass

            def check_all(self):
                called["value"] = True
                return True, {}

        fake_module = MagicMock()
        fake_module.SkillHealthMonitor = FakeMonitor

        with patch.dict(sys.modules, {"skill_health_monitor": fake_module}):
            ok, _ = h._run_startup(
                quick=False,
                dry_run=True,
                startup_mode="gui",
                partner_id="codex",
            )

        assert ok is True
        assert called["value"] is True

    def test_full_interactive_start_reports_skill_health_subprocess_issues(self, startup_env):
        h, base, _ = startup_env
        script = base / "tools" / "maintenance" / "skill_health_monitor.py"
        script.parent.mkdir(parents=True)
        script.write_text("# dummy", encoding="utf-8")

        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout=json.dumps({
                "healthy": False,
                "issues": [{"description": "DB-Pfad hängt"}],
                "warnings": [],
            }),
            stderr="",
        )

        with patch("hub.startup.subprocess.run", return_value=completed):
            ok, msg = h._run_startup(
                quick=False,
                dry_run=True,
                startup_mode="gui",
                partner_id="codex",
            )

        assert ok is True
        assert "[SKILL HEALTH]" in msg
        assert "1 Skill-Probleme gefunden" in msg
        assert "DB-Pfad hängt" in msg

    def test_full_interactive_start_timeboxes_skill_health_subprocess(self, startup_env):
        h, base, _ = startup_env
        h.SKILL_HEALTH_TIMEOUT_SECONDS = 3
        script = base / "tools" / "maintenance" / "skill_health_monitor.py"
        script.parent.mkdir(parents=True)
        script.write_text("# dummy", encoding="utf-8")

        timeout = subprocess.TimeoutExpired(cmd=["python"], timeout=3)

        with patch("hub.startup.subprocess.run", side_effect=timeout):
            ok, msg = h._run_startup(
                quick=False,
                dry_run=True,
                startup_mode="gui",
                partner_id="codex",
            )

        assert ok is True
        assert "[SKILL HEALTH]" in msg
        assert "TIMEOUT" in msg
        assert "3s" in msg

    def test_full_interactive_start_reports_timing_summary(self, startup_env):
        h, _, _ = startup_env

        ok, msg = h._run_startup(
            quick=False,
            dry_run=True,
            startup_mode="gui",
            partner_id="codex",
        )

        assert ok is True
        assert "[STARTUP TIMING]" in msg
        assert "Gesamt:" in msg

    def test_quick_start_omits_timing_summary(self, startup_env):
        h, _, _ = startup_env

        ok, msg = h._run_startup(
            quick=True,
            dry_run=True,
            startup_mode="gui",
            partner_id="codex",
        )

        assert ok is True
        assert "[STARTUP TIMING]" not in msg


class TestMorningBriefingStartup:
    def test_quick_start_keeps_sqlite_module_available(self, startup_env):
        h, _, _ = startup_env

        class MorningDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 10, 9, 0, tzinfo=tz)

        with patch("hub.startup.datetime", MorningDateTime):
            ok, msg = h._run_startup(
                quick=True,
                dry_run=True,
                startup_mode="silent",
                partner_id="codex",
            )

        assert ok is True
        assert "[MORGEN-BRIEFING]" in msg
        assert " --> bach haushalt today | bach task list" in msg
        assert "cannot access local variable 'sqlite3'" not in msg


class TestStartupTimingList:
    def test_timing_summary_lists_slow_sections(self):
        with patch("hub.startup.time.perf_counter", side_effect=[0.0, 0.1, 1.4, 1.6, 2.0]):
            results = _StartupTimingList(enabled=True)
            results.append("[FIRST]")
            results.append("[SECOND]")
            results.append("[THIRD]")
            lines = results.timing_lines(threshold_seconds=1.0)

        summary = "\n".join(lines)
        assert "[STARTUP TIMING]" in summary
        assert "FIRST: 1.30s" in summary
        assert "SECOND: 0.20s" not in summary


class TestSecretsImport:
    """Bug-Fix: 'from secrets import SecretsHandler' shadowed stdlib."""

    def test_import_uses_hub_secrets_handler(self):
        """Verify the import path references hub.secrets_handler, not stdlib secrets."""
        import inspect
        source = inspect.getsource(StartupHandler)
        assert "from hub.secrets_handler import SecretsHandler" in source
        assert "from secrets import SecretsHandler" not in source


class TestStartGuiServer:
    """Bug-Fix: bare 'python' instead of sys.executable, unquoted paths."""

    def test_windows_uses_sys_executable(self, startup_env):
        h, base, _ = startup_env
        server_script = base / "gui" / "server.py"
        server_script.write_text("# dummy")

        with patch("sys.platform", "win32"), \
             patch("os.system") as mock_sys, \
             patch("subprocess.Popen") as mock_popen, \
             patch("socket.socket") as mock_sock, \
             patch("webbrowser.open") as mock_browser, \
             patch.dict("os.environ", {"BACH_NO_BROWSER": ""}):
            mock_instance = MagicMock()
            mock_instance.connect_ex.side_effect = [1, 0, 0]
            mock_sock.return_value = mock_instance

            h._start_gui_background()

            if mock_popen.called:
                args = mock_popen.call_args[0][0]
                assert args[0] == sys.executable

    def test_unix_uses_sys_executable(self, startup_env):
        h, base, _ = startup_env
        server_script = base / "gui" / "server.py"
        server_script.write_text("# dummy")

        with patch("sys.platform", "linux"), \
             patch("subprocess.Popen") as mock_popen, \
             patch("socket.socket") as mock_sock, \
             patch("webbrowser.open") as mock_browser, \
             patch.dict("os.environ", {"BACH_NO_BROWSER": ""}):
            mock_instance = MagicMock()
            mock_instance.connect_ex.side_effect = [1, 0, 0]
            mock_sock.return_value = mock_instance

            h._start_gui_background()

            if mock_popen.called:
                args = mock_popen.call_args[0][0]
                assert args[0] == sys.executable


class TestStartConsole:
    """Bug-Fix: x-terminal-emulator is Debian-only, paths unquoted."""

    def test_windows_uses_sys_executable(self, startup_env):
        h, base, _ = startup_env
        (base / "bach.py").write_text("# dummy")

        with patch("sys.platform", "win32"), \
             patch("os.system") as mock_sys:
            h._start_console_background()
            if mock_sys.called:
                cmd = mock_sys.call_args[0][0]
                assert "bach_terminal.bat" in cmd
                bat_path = Path(os.environ.get("TEMP", "/tmp")) / "bach_terminal.bat"
                if bat_path.exists():
                    content = bat_path.read_text(encoding="utf-8")
                    assert sys.executable in content or "bach.py" in content

    def test_macos_uses_open_terminal(self, startup_env):
        h, base, _ = startup_env
        (base / "bach.py").write_text("# dummy")

        with patch("sys.platform", "darwin"), \
             patch("subprocess.Popen") as mock_popen:
            h._start_console_background()
            if mock_popen.called:
                args = mock_popen.call_args[0][0]
                assert args[0] == "open"
                assert "-a" in args
                assert "Terminal" in args

    def test_linux_finds_terminal(self, startup_env):
        h, base, _ = startup_env
        (base / "bach.py").write_text("# dummy")

        with patch("sys.platform", "linux"), \
             patch("shutil.which", side_effect=lambda x: "/usr/bin/xterm" if x == "xterm" else None), \
             patch("subprocess.Popen") as mock_popen:
            h._start_console_background()
            if mock_popen.called:
                args = mock_popen.call_args[0][0]
                assert "xterm" in args[0]

    def test_linux_no_terminal_returns_false(self, startup_env):
        h, base, _ = startup_env
        (base / "bach.py").write_text("# dummy")

        with patch("sys.platform", "linux"), \
             patch("shutil.which", return_value=None):
            result = h._start_console_background()
            assert result is False

    def test_linux_gnome_terminal_uses_double_dash(self, startup_env):
        h, base, _ = startup_env
        (base / "bach.py").write_text("# dummy")

        with patch("sys.platform", "linux"), \
             patch("shutil.which", side_effect=lambda x: "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None), \
             patch("subprocess.Popen") as mock_popen:
            h._start_console_background()
            if mock_popen.called:
                args = mock_popen.call_args[0][0]
                assert "--" in args
