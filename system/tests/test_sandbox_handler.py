# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hub.sandbox import SandboxHandler


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def handler(tmp_path):
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_config "
        "(key TEXT PRIMARY KEY, value TEXT, category TEXT)"
    )
    conn.commit()
    conn.close()
    h = SandboxHandler(tmp_path)
    h._canonical_db = str(db_path)
    h._allowed_commands = h._load_allowed_commands()
    return h


@pytest.fixture
def handler_no_db(tmp_path):
    h = SandboxHandler(tmp_path)
    h._canonical_db = None
    h._allowed_commands = SandboxHandler.DEFAULT_ALLOWED_COMMANDS
    return h


# ── Init / Properties ────────────────────────────────────────────────

class TestInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "sandbox"

    def test_target_file(self, handler, tmp_path):
        assert handler.target_file == tmp_path / "tools"

    def test_timeout_default(self, handler):
        assert handler.TIMEOUT == 30

    def test_allowed_commands_defaults(self, handler):
        assert "echo" in handler._allowed_commands
        assert "python" in handler._allowed_commands
        assert "git" in handler._allowed_commands

    def test_operations_include_policy(self, handler):
        ops = handler.get_operations()
        assert "policy" in ops
        assert "allow" in ops
        assert "deny" in ops
        assert "shell" in ops


# ── Handle Dispatch ──────────────────────────────────────────────────

class TestHandleDispatch:
    def test_dry_run(self, handler):
        ok, msg = handler.handle("run", ["test.py"], dry_run=True)
        assert ok is True
        assert "[DRY-RUN]" in msg

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("unknown", [])
        assert ok is False
        assert "Nutzung:" in msg

    def test_run_no_args(self, handler):
        ok, msg = handler.handle("run", [])
        assert ok is False

    def test_eval_no_args(self, handler):
        ok, msg = handler.handle("eval", [])
        assert ok is False

    def test_test_no_args(self, handler):
        ok, msg = handler.handle("test", [])
        assert ok is False

    def test_shell_no_args(self, handler):
        ok, msg = handler.handle("shell", [])
        assert ok is False


# ── _run_file ────────────────────────────────────────────────────────

class TestRunFile:
    def test_file_not_found(self, handler, tmp_path):
        ok, msg = handler._run_file("nonexistent.py", [])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_run_valid_script(self, handler, tmp_path):
        script = tmp_path / "hello.py"
        script.write_text("print('hello sandbox')", encoding="utf-8")
        ok, msg = handler._run_file(str(script), [])
        assert ok is True
        assert "hello sandbox" in msg

    def test_run_relative_path(self, handler, tmp_path):
        script = tmp_path / "rel_test.py"
        script.write_text("print('relative')", encoding="utf-8")
        ok, msg = handler._run_file("rel_test.py", [])
        assert ok is True
        assert "relative" in msg

    def test_run_with_args(self, handler, tmp_path):
        script = tmp_path / "argtest.py"
        script.write_text("import sys; print(sys.argv[1])", encoding="utf-8")
        ok, msg = handler._run_file(str(script), ["hello_arg"])
        assert ok is True
        assert "hello_arg" in msg

    def test_run_failing_script(self, handler, tmp_path):
        script = tmp_path / "fail.py"
        script.write_text("raise ValueError('boom')", encoding="utf-8")
        ok, msg = handler._run_file(str(script), [])
        assert ok is False
        assert "boom" in msg

    def test_run_timeout(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(handler, "TIMEOUT", 1)
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(10)", encoding="utf-8")
        ok, msg = handler._run_file(str(script), [])
        assert ok is False
        assert "TIMEOUT" in msg


# ── _eval ────────────────────────────────────────────────────────────

class TestEval:
    def test_eval_expression(self, handler):
        ok, msg = handler._eval("2 + 3")
        assert ok is True
        assert "5" in msg

    def test_eval_string(self, handler):
        ok, msg = handler._eval("'hello'")
        assert ok is True
        assert "hello" in msg

    def test_eval_statement(self, handler):
        ok, msg = handler._eval("print('statement_test')")
        assert ok is True
        assert "statement_test" in msg

    def test_eval_multiline_statement_fails(self, handler):
        # for-loops can't be wrapped in _result=... — compile-time SyntaxError
        ok, msg = handler._eval("for i in range(3): print(i)")
        assert ok is False
        assert "SyntaxError" in msg

    def test_eval_runtime_error(self, handler):
        ok, msg = handler._eval("1/0")
        assert ok is False
        assert "ZeroDivisionError" in msg

    def test_eval_timeout(self, handler, monkeypatch):
        monkeypatch.setattr(handler, "TIMEOUT", 1)
        ok, msg = handler._eval("__import__('time').sleep(10)")
        assert ok is False
        assert "TIMEOUT" in msg


# ── _test ────────────────────────────────────────────────────────────

class TestTestOperation:
    def test_file_not_found(self, handler):
        ok, msg = handler._test("nonexistent_test.py")
        assert ok is False
        assert "nicht gefunden" in msg

    def test_passing_test(self, handler, tmp_path):
        test_file = tmp_path / "test_ok.py"
        test_file.write_text("def test_pass(): assert True", encoding="utf-8")
        ok, msg = handler._test(str(test_file))
        assert ok is True
        assert "SANDBOX" in msg

    def test_failing_test(self, handler, tmp_path):
        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_fail(): assert False", encoding="utf-8")
        ok, msg = handler._test(str(test_file))
        assert ok is False


# ── _shell + Capability System ───────────────────────────────────────

class TestShell:
    def test_allowed_echo(self, handler):
        ok, msg = handler._shell("echo hello")
        assert ok is True
        assert "hello" in msg

    def test_blocked_command(self, handler):
        ok, msg = handler._shell("curl http://example.com")
        assert ok is False
        assert "BLOCKIERT" in msg
        assert "curl" in msg

    def test_blocked_pattern(self, handler):
        ok, msg = handler._shell("rm -rf /")
        assert ok is False
        assert "BLOCKIERT" in msg
        assert "verbotenes Muster" in msg

    def test_empty_command(self, handler):
        ok, msg = handler._shell("   ")
        assert ok is False
        assert "Leerer Befehl" in msg

    def test_shell_timeout(self, handler, monkeypatch):
        monkeypatch.setattr(handler, "TIMEOUT", 1)
        with patch("hub.sandbox.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
            ok, msg = handler._shell("echo slow")
            assert ok is False
            assert "TIMEOUT" in msg


class TestExtractBaseCommand:
    def test_simple(self, handler):
        assert handler._extract_base_command("echo hello") == "echo"

    def test_with_path(self, handler):
        assert handler._extract_base_command("/usr/bin/git status") == "git"

    def test_windows_path(self, handler):
        assert handler._extract_base_command("C:\\Windows\\System32\\cmd.exe /c dir") == "cmd"

    def test_quoted(self, handler):
        assert handler._extract_base_command('"git" log') == "git"

    def test_empty(self, handler):
        assert handler._extract_base_command("") == ""

    def test_with_extension(self, handler):
        assert handler._extract_base_command("python3.exe script.py") == "python3"


class TestCheckShellAllowed:
    def test_allowed(self, handler):
        ok, _ = handler._check_shell_allowed("echo test")
        assert ok is True

    def test_denied(self, handler):
        ok, msg = handler._check_shell_allowed("wget http://bad.com")
        assert ok is False
        assert "BLOCKIERT" in msg
        assert "Allowlist" in msg

    def test_blocked_pattern_rm_rf(self, handler):
        ok, msg = handler._check_shell_allowed("rm -rf /")
        assert ok is False
        assert "verbotenes Muster" in msg

    def test_blocked_pattern_shutdown(self, handler):
        ok, msg = handler._check_shell_allowed("shutdown -h now")
        assert ok is False

    def test_empty(self, handler):
        ok, _ = handler._check_shell_allowed("")
        assert ok is False

    def test_no_false_positive_halt_in_filename(self, handler):
        ok, _ = handler._check_shell_allowed("cat halted.log")
        assert ok is True

    def test_no_false_positive_fork_in_filename(self, handler):
        ok, _ = handler._check_shell_allowed("python forklift.py")
        assert ok is True

    def test_no_false_positive_reboot_in_grep(self, handler):
        ok, _ = handler._check_shell_allowed("grep reboot_time syslog.txt")
        assert ok is True

    def test_no_false_positive_shutdown_in_echo(self, handler):
        ok, _ = handler._check_shell_allowed("echo shutdown_timer_started")
        assert ok is True

    def test_actual_shutdown_still_blocked(self, handler):
        ok, msg = handler._check_shell_allowed("shutdown -h now")
        assert ok is False
        assert "verbotenes Muster" in msg

    def test_actual_reboot_still_blocked(self, handler):
        ok, msg = handler._check_shell_allowed("reboot")
        assert ok is False

    def test_actual_halt_still_blocked(self, handler):
        ok, msg = handler._check_shell_allowed("halt")
        assert ok is False

    def test_actual_rm_rf_still_blocked(self, handler):
        ok, msg = handler._check_shell_allowed("rm -rf /")
        assert ok is False
        assert "verbotenes Muster" in msg

    def test_actual_fork_bomb_still_blocked(self, handler):
        ok, msg = handler._check_shell_allowed(":(){ :|:& };:")
        assert ok is False


# ── Policy / Allow / Deny ────────────────────────────────────────────

class TestPolicy:
    def test_policy_output(self, handler):
        ok, msg = handler._policy()
        assert ok is True
        assert "SANDBOX-002" in msg
        assert "fail-closed" in msg
        assert "echo" in msg

    def test_policy_shows_blocked(self, handler):
        ok, msg = handler._policy()
        assert "Blockierte Muster" in msg


class TestAllowDeny:
    def test_allow_new_command(self, handler):
        assert "curl" not in handler._allowed_commands
        ok, msg = handler._allow_command("curl")
        assert ok is True
        assert "curl" in handler._allowed_commands

    def test_allow_persists_to_db(self, handler):
        handler._allow_command("wget")
        reloaded = handler._load_allowed_commands()
        assert "wget" in reloaded

    def test_deny_existing(self, handler):
        handler._allow_command("curl")
        ok, msg = handler._deny_command("curl")
        assert ok is True
        assert "curl" not in handler._allowed_commands

    def test_deny_nonexistent(self, handler):
        ok, msg = handler._deny_command("nonexistent_tool")
        assert ok is False
        assert "nicht in der Allowlist" in msg

    def test_allow_empty(self, handler):
        ok, _ = handler._allow_command("")
        assert ok is False

    def test_deny_empty(self, handler):
        ok, _ = handler._deny_command("")
        assert ok is False

    def test_allow_without_db(self, handler_no_db):
        ok, msg = handler_no_db._allow_command("custom_tool")
        assert ok is True
        assert "nur Session" in msg
        assert "custom_tool" in handler_no_db._allowed_commands

    def test_deny_persists_to_db(self, handler):
        handler._allow_command("temp_cmd")
        handler._deny_command("temp_cmd")
        reloaded = handler._load_allowed_commands()
        assert "temp_cmd" not in reloaded


class TestLoadFromDB:
    def test_loads_custom_config(self, handler, tmp_path):
        db_path = tmp_path / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value, category) "
            "VALUES ('sandbox.allowed_commands', ?, 'sandbox')",
            (json.dumps(["custom1", "custom2"]),)
        )
        conn.commit()
        conn.close()
        loaded = handler._load_allowed_commands()
        assert loaded == frozenset({"custom1", "custom2"})

    def test_falls_back_to_defaults_on_missing_key(self, handler):
        loaded = handler._load_allowed_commands()
        assert loaded == SandboxHandler.DEFAULT_ALLOWED_COMMANDS


# ── _format_result ───────────────────────────────────────────────────

class TestFormatResult:
    def test_with_stdout(self, handler):
        result = MagicMock(returncode=0, stdout="output text", stderr="")
        msg = handler._format_result(result, "test")
        assert "[SANDBOX] test" in msg
        assert "Exit: 0" in msg
        assert "output text" in msg

    def test_with_stderr(self, handler):
        result = MagicMock(returncode=1, stdout="", stderr="error text")
        msg = handler._format_result(result, "test")
        assert "error text" in msg
        assert "STDERR:" in msg

    def test_no_output(self, handler):
        result = MagicMock(returncode=0, stdout="", stderr="")
        msg = handler._format_result(result, "test")
        assert "(keine Ausgabe)" in msg

    def test_truncates_long_stdout(self, handler):
        result = MagicMock(returncode=0, stdout="x" * 5000, stderr="")
        msg = handler._format_result(result, "test")
        assert len(msg) < 4000


# ── Handle integration for new operations ────────────────────────────

class TestHandleNewOps:
    def test_handle_policy(self, handler):
        ok, msg = handler.handle("policy", [])
        assert ok is True
        assert "SANDBOX-002" in msg

    def test_handle_allow(self, handler):
        ok, msg = handler.handle("allow", ["curl"])
        assert ok is True
        assert "curl" in handler._allowed_commands

    def test_handle_deny(self, handler):
        handler._allow_command("curl")
        ok, msg = handler.handle("deny", ["curl"])
        assert ok is True
        assert "curl" not in handler._allowed_commands

    def test_handle_allow_no_args(self, handler):
        ok, msg = handler.handle("allow", [])
        assert ok is False

    def test_handle_deny_no_args(self, handler):
        ok, msg = handler.handle("deny", [])
        assert ok is False
