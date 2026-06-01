# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ChatRuntime security functions (hub/_services/chat/chat_runtime.py)."""

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.chat_runtime import (
    BACH_SYSTEM_DIR,
    BLOCKED_PATTERNS,
    CMD_TIMEOUT,
    SAFE_BASES,
    TOOLS_SAFE,
    _tool,
    exec_tool,
    is_blocked,
    is_safe_command,
    is_safe_write_path,
    run_shell,
)


# ===================================================================
# is_blocked(cmd) — dangerous command detection
# ===================================================================


class TestIsBlocked:
    """Test that dangerous commands are correctly blocked."""

    def test_rm_rf_root(self):
        assert is_blocked("rm -rf /") is True

    def test_rm_rf_root_trailing_space(self):
        assert is_blocked("rm -rf / ") is True

    def test_rm_r_root(self):
        assert is_blocked("rm -r /") is True

    def test_rm_f_root(self):
        assert is_blocked("rm -f /") is True

    def test_rm_rf_home(self):
        assert is_blocked("rm -rf ~") is True

    def test_rm_r_home(self):
        assert is_blocked("rm -r ~") is True

    def test_mkfs(self):
        assert is_blocked("mkfs.ext4 /dev/sda1") is True

    def test_mkfs_alone(self):
        assert is_blocked("mkfs /dev/sda") is True

    def test_dd_if(self):
        assert is_blocked("dd if=/dev/zero of=/dev/sda") is True

    def test_dd_if_urandom(self):
        assert is_blocked("dd if=/dev/urandom of=/dev/sda") is True

    def test_redirect_to_dev_sd(self):
        assert is_blocked("echo x > /dev/sda") is True

    def test_fork_bomb(self):
        assert is_blocked(":() { :; }") is True

    def test_safe_rm_file(self):
        """rm on a specific file (not / or ~) should NOT be blocked."""
        assert is_blocked("rm /tmp/test.txt") is False

    def test_safe_rm_dir(self):
        """rm -r on a user directory should NOT be blocked."""
        assert is_blocked("rm -rf /home/user/trash") is False

    def test_safe_ls(self):
        assert is_blocked("ls /") is False

    def test_safe_cat(self):
        assert is_blocked("cat /etc/passwd") is False

    def test_safe_dd_without_if(self):
        """dd without if= pattern should not match."""
        assert is_blocked("dd of=/tmp/test.img bs=1M count=1") is False

    def test_mkfs_substring_not_blocked(self):
        """A command containing mkfs as substring of another word should still match."""
        # mkfs\b uses word boundary, so 'mkfs_utils' should not match
        assert is_blocked("mkfs_utils --help") is False


# ===================================================================
# is_safe_command(cmd) — whitelist-based safe command detection
# ===================================================================


class TestIsSafeCommand:
    """Test that safe commands pass and unsafe ones are rejected."""

    @pytest.mark.parametrize("cmd", [
        "ls /home",
        "cat /etc/hosts",
        "grep -r pattern .",
        "git status",
        "git log --oneline",
        "find . -name '*.py'",
        "echo hello world",
        "date",
        "whoami",
        "hostname",
        "uname -a",
        "df -h",
        "du -sh /tmp",
        "uptime",
        "ps aux",
        "docker ps",
        "curl https://example.com",
        "ollama list",
        "brew list",
        "pip list",
        "pip3 install requests",
        "bach status",
        "wc -l file.txt",
        "file /tmp/test",
        "stat /tmp/test",
        "head -n 10 file.txt",
        "tail -f logfile",
        "which python",
        "env",
    ])
    def test_safe_commands_pass(self, cmd):
        assert is_safe_command(cmd) is True

    @pytest.mark.parametrize("cmd", [
        "rm -rf /tmp",
        "shutdown -h now",
        "reboot",
        "kill -9 1",
        "chmod 777 /etc/passwd",
        "chown root:root /etc/shadow",
        "python3 -c 'import os; os.system(\"rm -rf /\")'",
        "nano /etc/hosts",
        "vim /etc/passwd",
        "sudo rm -rf /",
        "apt-get remove --purge everything",
        "systemctl stop sshd",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
    ])
    def test_unsafe_commands_rejected(self, cmd):
        assert is_safe_command(cmd) is False

    def test_empty_command(self):
        assert is_safe_command("") is False

    def test_malformed_quotes(self):
        """Commands with unmatched quotes should return False (shlex.split fails)."""
        assert is_safe_command("echo 'unmatched") is False

    def test_full_path_to_safe_command(self):
        """A full path to ls should be recognized as safe (basename extraction)."""
        assert is_safe_command("/usr/bin/ls /home") is True
        assert is_safe_command("/bin/cat /etc/hosts") is True

    def test_full_path_to_unsafe_command(self):
        assert is_safe_command("/usr/bin/rm -rf /tmp") is False


# ===================================================================
# is_safe_write_path(path, mode) — path-based write protection
# ===================================================================


class TestIsSafeWritePath:
    """Test write path protection in safe vs full mode.

    Note: The blocked prefixes (/etc, /usr, /bin, etc.) are Unix-style paths.
    On Windows, Path.resolve() converts these to C:\\etc, C:\\usr etc., so the
    prefix check won't match. We mock Path to simulate Unix-like resolution
    for cross-platform test reliability.
    """

    # --- Safe mode: blocked paths (mocked resolution for Unix paths) ---

    @pytest.mark.parametrize("path,expected_resolve", [
        ("/etc/passwd", "/etc/passwd"),
        ("/etc/shadow", "/etc/shadow"),
        ("/usr/bin/python", "/usr/bin/python"),
        ("/usr/local/lib/test", "/usr/local/lib/test"),
        ("/bin/sh", "/bin/sh"),
        ("/sbin/init", "/sbin/init"),
        ("/System/Library/something", "/System/Library/something"),
        ("/Library/Preferences/test", "/Library/Preferences/test"),
        ("/var/root/.bashrc", "/var/root/.bashrc"),
        ("/private/etc/hosts", "/private/etc/hosts"),
    ])
    def test_safe_mode_blocks_system_paths(self, path, expected_resolve):
        """Unix system paths should be blocked in safe mode."""
        with patch("hub._services.chat.chat_runtime.Path") as MockPath:
            mock_resolved = MagicMock()
            mock_resolved.__str__ = lambda self: expected_resolve
            MockPath.return_value.resolve.return_value = mock_resolved
            result = is_safe_write_path(path, "safe")
        assert result is not None
        assert "nicht erlaubt" in result

    def test_safe_mode_blocks_bach_system_dir(self):
        """Writing to BACH system dir (not user subdir) should be blocked."""
        # Use a path that is actually within BACH_SYSTEM_DIR on this platform
        bach_file = str(Path(BACH_SYSTEM_DIR) / "some_handler.py")
        result = is_safe_write_path(bach_file, "safe")
        assert result is not None
        assert "BACH-Systemdateien" in result

    def test_safe_mode_allows_bach_user_dir(self):
        """Paths containing /user/ within BACH system dir should be allowed on Unix."""
        # The /user/ check uses forward slashes — this is a Unix-specific feature.
        # We mock to simulate Unix-like path resolution.
        fake_bach_dir = "/home/lukas/BACH/system/hub"
        fake_user_path = fake_bach_dir + "/data/user/notes.txt"
        with patch("hub._services.chat.chat_runtime.Path") as MockPath, \
             patch("hub._services.chat.chat_runtime.BACH_SYSTEM_DIR", fake_bach_dir):
            mock_resolved = MagicMock()
            mock_resolved.__str__ = lambda self: fake_user_path
            MockPath.return_value.resolve.return_value = mock_resolved
            result = is_safe_write_path(fake_user_path, "safe")
        assert result is None

    def test_safe_mode_allows_tmp(self):
        """Paths outside blocked prefixes should be allowed (e.g. /tmp on Unix)."""
        with patch("hub._services.chat.chat_runtime.Path") as MockPath:
            mock_resolved = MagicMock()
            mock_resolved.__str__ = lambda self: "/tmp/output.txt"
            MockPath.return_value.resolve.return_value = mock_resolved
            result = is_safe_write_path("/tmp/output.txt", "safe")
        assert result is None

    def test_safe_mode_allows_home_dir(self):
        with patch("hub._services.chat.chat_runtime.Path") as MockPath:
            mock_resolved = MagicMock()
            mock_resolved.__str__ = lambda self: "/home/user/documents/test.txt"
            MockPath.return_value.resolve.return_value = mock_resolved
            result = is_safe_write_path("/home/user/documents/test.txt", "safe")
        assert result is None

    # --- Full mode: everything allowed ---

    def test_full_mode_allows_everything(self):
        """Full mode should allow writes to any path (no restriction)."""
        # No mocking needed — mode != "safe" returns None immediately
        paths = [
            "/etc/passwd",
            "/usr/bin/python",
            "/bin/sh",
            "/System/Library/something",
            "/var/root/.bashrc",
            "/private/etc/hosts",
        ]
        for path in paths:
            result = is_safe_write_path(path, "full")
            assert result is None, f"Full mode should allow {path}"

    def test_full_mode_allows_bach_system(self):
        bach_file = str(Path(BACH_SYSTEM_DIR) / "some_handler.py")
        result = is_safe_write_path(bach_file, "full")
        assert result is None

    def test_non_safe_mode_returns_none(self):
        """Any mode other than 'safe' should return None immediately."""
        for mode in ("full", "admin", "unrestricted", ""):
            assert is_safe_write_path("/etc/passwd", mode) is None


# ===================================================================
# run_shell(cmd) — shell command execution with timeout clamping
# ===================================================================


class TestRunShell:
    """Test run_shell timeout clamping, subprocess handling, error handling."""

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="hello world\n",
            stderr="",
        )
        result = run_shell("echo hello world")
        assert "hello world" in result
        mock_run.assert_called_once()

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_stderr_included(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="output\n",
            stderr="warning: something\n",
        )
        result = run_shell("some command")
        assert "output" in result
        assert "[stderr]" in result
        assert "warning: something" in result

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="",
        )
        result = run_shell("true")
        assert result == "(keine Ausgabe)"

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_timeout_expired(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=30)
        result = run_shell("sleep 999", timeout=30)
        assert "Timeout" in result
        assert "30s" in result

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = OSError("No such file or directory")
        result = run_shell("nonexistent_cmd")
        assert "Fehler" in result
        assert "No such file or directory" in result

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_timeout_clamped_minimum(self, mock_run):
        """Timeout below 5 should be clamped to 5."""
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_shell("ls", timeout=1)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 5

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_timeout_clamped_maximum(self, mock_run):
        """Timeout above 120 should be clamped to 120."""
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_shell("ls", timeout=999)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 120

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_timeout_within_range(self, mock_run):
        """Timeout within 5-120 should be passed as-is."""
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_shell("ls", timeout=60)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 60

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_output_truncated_at_4000(self, mock_run):
        """Output longer than 4000 chars should be truncated."""
        long_output = "x" * 5000
        mock_run.return_value = MagicMock(stdout=long_output, stderr="")
        result = run_shell("generate_long_output")
        assert len(result) == 4000

    @patch("hub._services.chat.chat_runtime.subprocess.run")
    def test_default_timeout_is_cmd_timeout(self, mock_run):
        """Default timeout should be CMD_TIMEOUT (30)."""
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_shell("ls")
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == CMD_TIMEOUT


# ===================================================================
# _tool() helper — OpenAI-format tool definitions
# ===================================================================


class TestToolHelper:
    """Test that _tool produces valid OpenAI-format tool definitions."""

    def test_basic_tool_structure(self):
        result = _tool("test_tool", "A test tool", {"arg1": {"type": "string"}})
        assert result["type"] == "function"
        assert "function" in result
        func = result["function"]
        assert func["name"] == "test_tool"
        assert func["description"] == "A test tool"
        assert func["parameters"]["type"] == "object"
        assert "arg1" in func["parameters"]["properties"]
        assert func["parameters"]["required"] == []

    def test_tool_with_required_params(self):
        result = _tool(
            "write_file",
            "Write a file",
            {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Content"},
            },
            required=["path", "content"],
        )
        func = result["function"]
        assert func["parameters"]["required"] == ["path", "content"]

    def test_tool_with_empty_props(self):
        result = _tool("no_args", "Tool with no arguments", {})
        func = result["function"]
        assert func["parameters"]["properties"] == {}
        assert func["parameters"]["required"] == []

    def test_tool_with_complex_properties(self):
        result = _tool(
            "complex_tool",
            "Complex tool",
            {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove"],
                    "description": "Action to perform",
                },
                "count": {
                    "type": "integer",
                    "description": "Item count",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recurse into subdirs",
                },
            },
            required=["action"],
        )
        func = result["function"]
        props = func["parameters"]["properties"]
        assert props["action"]["enum"] == ["list", "add", "remove"]
        assert props["count"]["type"] == "integer"
        assert props["recursive"]["type"] == "boolean"
        assert func["parameters"]["required"] == ["action"]

    def test_tool_name_preserved(self):
        """Name with special characters should be preserved exactly."""
        result = _tool("my_tool_v2", "Version 2", {})
        assert result["function"]["name"] == "my_tool_v2"

    def test_tool_description_preserved(self):
        """Description with German characters should be preserved."""
        desc = "Dateien und Ordner auflisten"
        result = _tool("list_dir", desc, {})
        assert result["function"]["description"] == desc

    def test_bach_command_lists_mediplaner_handler(self):
        bach_tool = next(tool for tool in TOOLS_SAFE if tool["function"]["name"] == "bach_command")
        handler_desc = bach_tool["function"]["parameters"]["properties"]["handler"]["description"]
        assert "mediplaner" in handler_desc


class TestFoerderberichtToolPrivacy:
    def test_status_hides_paths_and_client_names(self, tmp_path):
        base_path = tmp_path / "Berichte"
        (base_path / "data_roh" / "Max Mustermann").mkdir(parents=True)
        (base_path / "data_bundled").mkdir(parents=True)
        (base_path / "data_bundled" / "prompt.txt").write_text("prompt", encoding="utf-8")

        class DummyPipeline:
            def __init__(self):
                self.base_path = base_path

        dummy_module = types.SimpleNamespace(FoerderberichtPipeline=DummyPipeline)
        with patch.dict(sys.modules, {
            "hub._services.document.foerderbericht_pipeline": dummy_module,
        }):
            result = exec_tool("foerderbericht", {"action": "status"}, "safe")

        assert "Pipeline bereit." in result
        assert "Akte erkannt: ja (1 Ordner)" in result
        assert "Anonymisierter Prompt vorhanden: ja" in result
        assert "Max Mustermann" not in result
        assert str(base_path) not in result

    def test_prepare_hides_prompt_path(self, tmp_path):
        base_path = tmp_path / "Berichte"

        class DummyResult:
            success = True
            tarnname = "Tarn Person"
            duration_s = 2.5
            steps_completed = ["profil: Tarnname=Tarn Person", "prompt: 1200 Zeichen"]

        class DummyPipeline:
            def __init__(self):
                self.base_path = base_path

            def prepare_prompt(self, **kwargs):
                return DummyResult()

        dummy_module = types.SimpleNamespace(FoerderberichtPipeline=DummyPipeline)
        with patch.dict(sys.modules, {
            "hub._services.document.foerderbericht_pipeline": dummy_module,
        }):
            result = exec_tool("foerderbericht", {"action": "prepare"}, "safe")

        assert "Phase 1 abgeschlossen." in result
        assert "Tarnname: Tarn Person" in result
        assert "Anonymisierter Prompt bereit." in result
        assert "prompt.txt" not in result
        assert str(base_path) not in result
