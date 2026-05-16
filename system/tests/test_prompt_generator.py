# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for PromptGenerator clipboard cascade and cross-platform support."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.prompt_generator.prompt_generator import PromptGenerator


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def pg(tmp_path):
    """PromptGenerator with minimal config."""
    p = PromptGenerator.__new__(PromptGenerator)
    p.config = {}
    p.templates_dir = tmp_path / "templates"
    p.templates_dir.mkdir()
    return p


# ═══════════════════════════════════════════════════════════════
# CLIPBOARD — PYPERCLIP AVAILABLE
# ═══════════════════════════════════════════════════════════════


class TestClipboardPyperclip:
    def test_pyperclip_success(self, pg):
        mock_pyperclip = MagicMock()
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = pg.copy_to_clipboard("hello")
        assert result["status"] == "copied"
        assert result["length"] == 5
        mock_pyperclip.copy.assert_called_once_with("hello")


# ═══════════════════════════════════════════════════════════════
# CLIPBOARD — TKINTER FALLBACK
# ═══════════════════════════════════════════════════════════════


class TestClipboardTkinter:
    def test_tkinter_fallback(self, pg):
        mock_root = MagicMock()
        mock_tk = MagicMock()
        mock_tk.Tk.return_value = mock_root

        with patch.dict("sys.modules", {"pyperclip": None}):
            with patch.dict("sys.modules", {"tkinter": mock_tk}):
                with patch("builtins.__import__", side_effect=_import_skip_pyperclip(mock_tk)):
                    result = pg.copy_to_clipboard("test")

        assert result["status"] == "copied"


# ═══════════════════════════════════════════════════════════════
# CLIPBOARD — LINUX CASCADE (wl-copy > xsel > xclip)
# ═══════════════════════════════════════════════════════════════


class TestClipboardLinuxCascade:
    def _run_with_which(self, pg, which_map):
        """Run copy_to_clipboard with pyperclip+tkinter unavailable, mocking shutil.which."""
        def fake_which(cmd):
            return which_map.get(cmd)

        with patch.dict("sys.modules", {"pyperclip": None}), \
             patch("builtins.__import__", side_effect=_import_block_pyperclip_tkinter()), \
             patch("sys.platform", "linux"), \
             patch("shutil.which", side_effect=fake_which) as mock_w, \
             patch("subprocess.run") as mock_run:
            result = pg.copy_to_clipboard("cascade test")
        return result, mock_run

    def test_prefers_wl_copy(self, pg):
        result, mock_run = self._run_with_which(pg, {
            "wl-copy": "/usr/bin/wl-copy",
            "xsel": "/usr/bin/xsel",
            "xclip": "/usr/bin/xclip",
        })
        assert result["status"] == "copied"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["wl-copy"]

    def test_falls_back_to_xsel(self, pg):
        result, mock_run = self._run_with_which(pg, {
            "wl-copy": None,
            "xsel": "/usr/bin/xsel",
            "xclip": "/usr/bin/xclip",
        })
        assert result["status"] == "copied"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["xsel", "-b", "-i"]

    def test_falls_back_to_xclip(self, pg):
        result, mock_run = self._run_with_which(pg, {
            "wl-copy": None,
            "xsel": None,
            "xclip": "/usr/bin/xclip",
        })
        assert result["status"] == "copied"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["xclip", "-selection", "clipboard"]

    def test_no_tool_returns_error(self, pg):
        result, mock_run = self._run_with_which(pg, {
            "wl-copy": None,
            "xsel": None,
            "xclip": None,
        })
        assert result["status"] == "error"
        mock_run.assert_not_called()

    def test_windows_uses_powershell(self, pg):
        with patch.dict("sys.modules", {"pyperclip": None}), \
             patch("builtins.__import__", side_effect=_import_block_pyperclip_tkinter()), \
             patch("sys.platform", "win32"), \
             patch("subprocess.run") as mock_run:
            result = pg.copy_to_clipboard("win test")
        assert result["status"] == "copied"
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "powershell"

    def test_macos_uses_pbcopy(self, pg):
        with patch.dict("sys.modules", {"pyperclip": None}), \
             patch("builtins.__import__", side_effect=_import_block_pyperclip_tkinter()), \
             patch("sys.platform", "darwin"), \
             patch("subprocess.run") as mock_run:
            result = pg.copy_to_clipboard("mac test")
        assert result["status"] == "copied"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pbcopy"]


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except_in_prompt_generator(self):
        import ast
        source_file = SYSTEM_ROOT / "hub" / "_services" / "prompt_generator" / "prompt_generator.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                pytest.fail(f"Bare except at line {node.lineno} in prompt_generator.py")

    def test_clipboard_source_has_wayland(self):
        import inspect
        source = inspect.getsource(PromptGenerator.copy_to_clipboard)
        assert "wl-copy" in source
        assert "xsel" in source
        assert "xclip" in source


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


def _import_skip_pyperclip(mock_tk):
    """Import hook that blocks pyperclip but allows tkinter via mock."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def _imp(name, *args, **kwargs):
        if name == "pyperclip":
            raise ImportError("no pyperclip")
        if name == "tkinter":
            return mock_tk
        return real_import(name, *args, **kwargs)
    return _imp


def _import_block_pyperclip_tkinter():
    """Import hook that blocks both pyperclip and tkinter."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def _imp(name, *args, **kwargs):
        if name == "pyperclip":
            raise ImportError("no pyperclip")
        if name == "tkinter":
            raise ImportError("no tkinter")
        return real_import(name, *args, **kwargs)
    return _imp
