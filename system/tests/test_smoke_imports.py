# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke tests: verify critical modules import without error.

These tests catch real bugs — missing dependencies, broken relative imports,
misconfigured configs — that unit tests can't find because they mock everything.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


# ═══════════════════════════════════════════════════════════════
# SUBPROCESS SMOKE — catches sys.path issues invisible to in-process tests
# ═══════════════════════════════════════════════════════════════


class TestSubprocessSmoke:
    """Run critical imports in a clean subprocess."""

    @staticmethod
    def _import_check(module_path: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{SYSTEM_ROOT}'); "
             f"import {module_path}; print('OK')"],
            capture_output=True, text=True, timeout=30, env=env,
        )

    def test_bach_cli_help(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, str(SYSTEM_ROOT / "bach.py"), "--help"],
            capture_output=True, text=True, timeout=30, env=env,
            cwd=str(SYSTEM_ROOT),
        )
        assert result.returncode == 0, f"bach.py --help failed: {result.stderr[:300]}"
        assert "BACH" in result.stdout

    def test_gui_server_import(self):
        r = self._import_check("gui.server")
        assert r.returncode == 0, f"gui.server import failed: {r.stderr[:300]}"

    def test_chat_tray_import(self):
        r = self._import_check("hub._services.chat.chat_tray")
        assert r.returncode == 0, f"chat_tray import failed: {r.stderr[:300]}"

    def test_bridge_tray_import(self):
        r = self._import_check("hub._services.claude_bridge.bridge_tray")
        assert r.returncode == 0, f"bridge_tray import failed: {r.stderr[:300]}"

    def test_bridge_daemon_import(self):
        r = self._import_check("hub._services.claude_bridge.bridge_daemon")
        assert r.returncode == 0, f"bridge_daemon import failed: {r.stderr[:300]}"

    def test_bridge_fackel_wrapper_import(self):
        r = self._import_check("hub._services.claude_bridge.bridge_fackel_wrapper")
        assert r.returncode == 0, f"bridge_fackel_wrapper import failed: {r.stderr[:300]}"


# ═══════════════════════════════════════════════════════════════
# IN-PROCESS — all 112 hub handlers must import cleanly
# ═══════════════════════════════════════════════════════════════


class TestHubHandlerImports:
    """Every hub/*.py module must import without error."""

    @staticmethod
    def _hub_modules():
        for f in sorted((SYSTEM_ROOT / "hub").glob("*.py")):
            if f.name.startswith("__"):
                continue
            yield f.stem

    @pytest.mark.parametrize("module", list(_hub_modules.__func__()))
    def test_hub_import(self, module):
        mod = importlib.import_module(f"hub.{module}")
        assert mod is not None


# ═══════════════════════════════════════════════════════════════
# CONNECTOR IMPORTS
# ═══════════════════════════════════════════════════════════════


class TestConnectorImports:
    """All connectors/*.py must import cleanly."""

    @staticmethod
    def _connector_modules():
        for f in sorted((SYSTEM_ROOT / "connectors").glob("*.py")):
            if f.name.startswith("__"):
                continue
            yield f.stem

    @pytest.mark.parametrize("module", list(_connector_modules.__func__()))
    def test_connector_import(self, module):
        mod = importlib.import_module(f"connectors.{module}")
        assert mod is not None


# ═══════════════════════════════════════════════════════════════
# TOOL IMPORTS — all tools/*.py must import cleanly
# ═══════════════════════════════════════════════════════════════


class TestToolImports:
    """Every tools/*.py module must import without error."""

    @staticmethod
    def _tool_modules():
        for f in sorted((SYSTEM_ROOT / "tools").glob("*.py")):
            if f.name.startswith("__"):
                continue
            yield f.stem

    @pytest.mark.parametrize("module", list(_tool_modules.__func__()))
    def test_tool_import(self, module):
        mod = importlib.import_module(f"tools.{module}")
        assert mod is not None


# ═══════════════════════════════════════════════════════════════
# TOOL SUBPACKAGE SUBPROCESS SMOKE — heavy tools tested in isolation
# ═══════════════════════════════════════════════════════════════


class TestToolSubpackageSmoke:
    """Tool subdirectories with __init__.py must import as packages."""

    @staticmethod
    def _importable_subpackages():
        tools_dir = SYSTEM_ROOT / "tools"
        for d in sorted(tools_dir.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".")):
                continue
            if (d / "__init__.py").exists():
                yield f"tools.{d.name}"

    @pytest.mark.parametrize("pkg", list(_importable_subpackages.__func__()))
    def test_subpackage_import(self, pkg):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{SYSTEM_ROOT}'); "
             f"import {pkg}; print('OK')"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert r.returncode == 0, f"{pkg} import failed: {r.stderr[:300]}"


# ═══════════════════════════════════════════════════════════════
# TOOL SCRIPT SYNTAX — every .py in tool subdirs must compile
# ═══════════════════════════════════════════════════════════════


class TestToolScriptSyntax:
    """All .py files in tools/ subdirectories must at least compile."""

    @staticmethod
    def _tool_scripts():
        tools_dir = SYSTEM_ROOT / "tools"
        for d in sorted(tools_dir.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".")):
                continue
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("__"):
                    continue
                yield str(f.relative_to(SYSTEM_ROOT))

    @pytest.mark.parametrize("script", list(_tool_scripts.__func__()))
    def test_script_compiles(self, script):
        full_path = SYSTEM_ROOT / script
        source = full_path.read_text(encoding="utf-8")
        compile(source, str(full_path), "exec")


# ═══════════════════════════════════════════════════════════════
# AGENT IMPORTS
# ═══════════════════════════════════════════════════════════════


class TestAgentImports:
    """Agent modules that exist as .py files must import."""

    def test_agents_init(self):
        mod = importlib.import_module("agents")
        assert mod is not None

    def test_reflection_analyzer(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{SYSTEM_ROOT}'); "
             f"from agents.reflection import reflection_analyzer; print('OK')"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert r.returncode == 0, f"reflection_analyzer import failed: {r.stderr[:300]}"
