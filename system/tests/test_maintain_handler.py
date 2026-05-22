# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for MaintainHandler (hub/maintain.py)."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.maintain import MaintainHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def maintain_env(tmp_path):
    """Minimal environment for MaintainHandler."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "maintenance").mkdir()

    # Create dummy scripts for testing
    for script in [
        "doc_update_checker.py",
        "duplicate_detector.py",
        "skill_generator.py",
        "exporter.py",
        "pattern_tool.py",
        "tool_scanner.py",
        "file_cleaner.py",
        "json_fixer.py",
        "skill_header_gen.py",
    ]:
        (tools_dir / script).write_text("# dummy", encoding="utf-8")

    for script in [
        "doc_path_updater.py",
        "registry_watcher.py",
        "skill_health_monitor.py",
        "sync_skills.py",
    ]:
        (tools_dir / "maintenance" / script).write_text("# dummy", encoding="utf-8")

    return tmp_path


@pytest.fixture
def handler(maintain_env):
    """MaintainHandler with mocked base_path."""
    h = MaintainHandler(maintain_env)
    return h


# ═══════════════════════════════════════════════════════════════
# BASIC PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "maintain"

    def test_target_file(self, handler, maintain_env):
        assert handler.target_file == maintain_env / "tools"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "docs" in ops
        assert "clean" in ops
        assert "nul" in ops
        assert "list" in ops
        assert len(ops) >= 15


# ═══════════════════════════════════════════════════════════════
# HANDLE ROUTING
# ═══════════════════════════════════════════════════════════════


class TestRouting:
    def test_list_is_default(self, handler):
        ok, msg = handler.handle("", [], dry_run=False)
        assert ok is True
        assert "WARTUNGS-TOOLS" in msg

    def test_list_explicit(self, handler):
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok is True
        assert "WARTUNGS-TOOLS" in msg

    def test_help(self, handler):
        ok, msg = handler.handle("help", [], dry_run=False)
        assert ok is True
        assert "BACH Maintain" in msg

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent_op", [], dry_run=False)
        assert ok is False
        assert "Unbekannter Befehl" in msg

    def test_heal_returns_deprecation_notice(self, handler):
        ok, msg = handler.handle("heal", [], dry_run=False)
        assert ok is True
        assert "nicht mehr noetig" in msg or "bach_paths.py" in msg

    def test_health_routes_to_status_handler(self, handler):
        with patch("hub.maintain.StatusHandler.handle", return_value=(True, "STATUS")) as mocked:
            ok, msg = handler.handle("health", [], dry_run=False)

        assert ok is True
        assert msg == "STATUS"
        mocked.assert_called_once_with("show", [], False)


# ═══════════════════════════════════════════════════════════════
# SCRIPT-NOT-FOUND HANDLING
# ═══════════════════════════════════════════════════════════════


class TestScriptNotFound:
    def test_docs_missing_script(self, handler):
        (handler.tools_dir / "doc_update_checker.py").unlink()
        ok, msg = handler.handle("docs", ["check"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_generate_missing_script(self, handler):
        (handler.tools_dir / "skill_generator.py").unlink()
        ok, msg = handler.handle("generate", ["test"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_export_missing_script(self, handler):
        (handler.tools_dir / "exporter.py").unlink()
        ok, msg = handler.handle("export", ["skill"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_pattern_missing_script(self, handler):
        (handler.tools_dir / "pattern_tool.py").unlink()
        ok, msg = handler.handle("pattern", ["./docs"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_scan_missing_script(self, handler):
        (handler.tools_dir / "tool_scanner.py").unlink()
        ok, msg = handler.handle("scan", [], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_clean_missing_script(self, handler):
        (handler.tools_dir / "file_cleaner.py").unlink()
        ok, msg = handler.handle("clean", ["./logs"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_json_missing_script(self, handler):
        (handler.tools_dir / "json_fixer.py").unlink()
        ok, msg = handler.handle("json", ["test.json"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_docs_paths_missing_script(self, handler):
        (handler.tools_dir / "maintenance" / "doc_path_updater.py").unlink()
        ok, msg = handler.handle("docs-paths", ["--apply"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_registry_missing_script(self, handler):
        (handler.tools_dir / "maintenance" / "registry_watcher.py").unlink()
        ok, msg = handler.handle("registry", [], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_skills_missing_script(self, handler):
        (handler.tools_dir / "maintenance" / "skill_health_monitor.py").unlink()
        ok, msg = handler.handle("skills", [], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_sync_missing_script(self, handler):
        (handler.tools_dir / "maintenance" / "sync_skills.py").unlink()
        ok, msg = handler.handle("sync", [], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_headers_missing_script(self, handler):
        (handler.tools_dir / "skill_header_gen.py").unlink()
        ok, msg = handler.handle("headers", ["--fix"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg


# ═══════════════════════════════════════════════════════════════
# HELP TEXT FOR EMPTY ARGS
# ═══════════════════════════════════════════════════════════════


class TestHelpTexts:
    def test_generate_no_args(self, handler):
        ok, msg = handler.handle("generate", [], dry_run=False)
        assert ok is True
        assert "Skill Generator" in msg

    def test_export_no_args(self, handler):
        ok, msg = handler.handle("export", [], dry_run=False)
        assert ok is True
        assert "Exporter" in msg

    def test_pattern_no_args(self, handler):
        ok, msg = handler.handle("pattern", [], dry_run=False)
        assert ok is True
        assert "Pattern Tool" in msg

    def test_clean_no_args(self, handler):
        ok, msg = handler.handle("clean", [], dry_run=False)
        assert ok is True
        assert "File Cleaner" in msg

    def test_json_no_args(self, handler):
        ok, msg = handler.handle("json", [], dry_run=False)
        assert ok is True
        assert "JSON Fixer" in msg

    def test_docs_paths_no_args(self, handler):
        ok, msg = handler.handle("docs-paths", [], dry_run=False)
        assert ok is True
        assert "Doc Path Updater" in msg

    def test_nul_no_args(self, handler):
        ok, msg = handler.handle("nul", [], dry_run=False)
        assert ok is True
        assert "NUL Cleaner" in msg

    def test_headers_no_args(self, handler):
        ok, msg = handler.handle("headers", [], dry_run=False)
        assert ok is True
        assert "Skill Header Generator" in msg

    def test_skill_help_no_args(self, handler):
        ok, msg = handler.handle("skill-help", [], dry_run=False)
        assert ok is True
        assert "Skill Help Generator" in msg


# ═══════════════════════════════════════════════════════════════
# SUBPROCESS CALLS
# ═══════════════════════════════════════════════════════════════


class TestSubprocessCalls:
    @patch("subprocess.run")
    def test_docs_check_calls_subprocess(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        ok, msg = handler.handle("docs", ["check"], dry_run=False)
        assert ok is True
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "doc_update_checker.py" in str(cmd[-1]) or "doc_update_checker" in str(cmd)

    @patch("subprocess.run")
    def test_docs_dry_run_adds_flag(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        handler.handle("docs", ["check"], dry_run=True)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--dry-run" in cmd

    @patch("subprocess.run")
    def test_scan_default_subcommand(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("scan", [], dry_run=False)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "scan" in cmd

    @patch("subprocess.run")
    def test_pattern_dry_run(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("pattern", ["./docs"], dry_run=True)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--dry-run" in cmd

    @patch("subprocess.run")
    def test_json_dry_run(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="fixed", stderr="")
        handler.handle("json", ["test.json"], dry_run=True)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--dry-run" in cmd

    @patch("subprocess.run")
    def test_subprocess_failure_returns_false(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error!")
        ok, msg = handler.handle("docs", ["check"], dry_run=False)
        assert ok is False

    @patch("subprocess.run")
    def test_subprocess_exception_returns_false(self, mock_run, handler):
        mock_run.side_effect = OSError("exec failed")
        ok, msg = handler.handle("docs", ["check"], dry_run=False)
        assert ok is False
        assert "Fehler" in msg

    @patch("subprocess.run")
    def test_subprocess_env_has_utf8(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("docs", ["check"], dry_run=False)
        env = mock_run.call_args[1].get("env") or mock_run.call_args.kwargs.get("env")
        assert env is not None
        assert env.get("PYTHONIOENCODING") == "utf-8"

    @patch("subprocess.run")
    def test_sync_dry_run(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="synced", stderr="")
        handler.handle("sync", [], dry_run=True)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--dry-run" in cmd

    @patch("subprocess.run")
    def test_docs_with_subcommand_report(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="report", stderr="")
        handler.handle("docs", ["report"], dry_run=False)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "report" in cmd
        assert "check" not in cmd


# ═══════════════════════════════════════════════════════════════
# NUL CLEANER
# ═══════════════════════════════════════════════════════════════


class TestNulCleaner:
    def test_nul_help_text_shown_without_args(self, handler):
        ok, msg = handler.handle("nul", [], dry_run=False)
        assert ok is True
        assert "NUL Cleaner" in msg


# ═══════════════════════════════════════════════════════════════
# LIST TOOLS OUTPUT
# ═══════════════════════════════════════════════════════════════


class TestListTools:
    def test_list_contains_all_operations(self, handler):
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok is True
        for keyword in ["docs", "duplicates", "generate", "export",
                         "pattern", "scan", "clean", "json",
                         "registry", "skills", "headers", "nul"]:
            assert keyword in msg

    def test_show_help_contains_examples(self, handler):
        ok, msg = handler.handle("help", [], dry_run=False)
        assert ok is True
        assert "Beispiele" in msg


# ═══════════════════════════════════════════════════════════════
# HEADERS ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════


class TestHeadersParsing:
    @patch("subprocess.run")
    def test_headers_fix_passes_flag(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("headers", ["--fix"], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "--fix" in cmd

    @patch("subprocess.run")
    def test_headers_path_arg(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("headers", ["--path", "agents"], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "--path" in cmd
        assert "agents" in cmd

    @patch("subprocess.run")
    def test_headers_default_is_dry_run(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("headers", ["--all"], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "--dry-run" in cmd

    @patch("subprocess.run")
    def test_headers_update_db(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("headers", ["--update-db"], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "--update-db" in cmd


# ═══════════════════════════════════════════════════════════════
# DOCS ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════


class TestDocsArgParsing:
    @patch("subprocess.run")
    def test_docs_default_is_check(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("docs", [], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "check" in cmd

    @patch("subprocess.run")
    def test_docs_auto_update(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("docs", ["auto-update"], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "auto-update" in cmd

    @patch("subprocess.run")
    def test_docs_flags_appended(self, mock_run, handler):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        handler.handle("docs", ["--verbose"], dry_run=False)
        cmd = mock_run.call_args[0][0]
        assert "check" in cmd
        assert "--verbose" in cmd
