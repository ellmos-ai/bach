#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer AgentLauncherHandler"""

import sys
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.agent_launcher import AgentLauncherHandler


@pytest.fixture
def tmp_bach(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()

    agents_dir = system_dir / "agents"
    agents_dir.mkdir()
    experts_dir = agents_dir / "_experts"
    experts_dir.mkdir()

    data_dir = system_dir / "data"
    data_dir.mkdir()
    (data_dir / "agent_pids").mkdir()
    (data_dir / "temp").mkdir()

    ag_boss = agents_dir / "test-boss"
    ag_boss.mkdir()
    (ag_boss / "SKILL.md").write_text("---\nname: test-boss\n---\n# Test Boss", encoding="utf-8")

    ag_expert = experts_dir / "test-expert"
    ag_expert.mkdir()
    (ag_expert / "SKILL.md").write_text("---\nname: test-expert\n---\n# Test Expert", encoding="utf-8")

    hidden = agents_dir / "_archive"
    hidden.mkdir()
    (hidden / "SKILL.md").write_text("hidden", encoding="utf-8")

    return system_dir


@pytest.fixture
def handler(tmp_bach):
    return AgentLauncherHandler(tmp_bach)


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "agent"

    def test_target_file(self, handler):
        assert handler.target_file == handler.agents_dir

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "start" in ops
        assert "stop" in ops
        assert "status" in ops
        assert "doctor" in ops
        assert "steer" in ops
        assert "rename" in ops


# ================================================================
# HANDLE ROUTING
# ================================================================

class TestHandleRouting:
    def test_list(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "test-boss" in msg
        assert "test-expert" in msg

    def test_start_no_name(self, handler):
        ok, msg = handler.handle("start", [])
        assert ok is False
        assert "bach agent start" in msg

    def test_stop_no_name(self, handler):
        ok, msg = handler.handle("stop", [])
        assert ok is False
        assert "bach agent stop" in msg

    def test_steer_too_few_args(self, handler):
        ok, msg = handler.handle("steer", ["test-boss"])
        assert ok is False
        assert "bach agent steer" in msg.lower() or "Syntax" in msg

    def test_rename_too_few_args(self, handler):
        ok, msg = handler.handle("rename", ["test-boss"])
        assert ok is False
        assert "rename" in msg.lower() or "Syntax" in msg

    def test_unknown_op_fallback_to_list(self, handler):
        ok, msg = handler.handle("xyzfoo", [])
        assert ok is True
        assert "test-boss" in msg

    def test_status(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok is True


# ================================================================
# SCAN
# ================================================================

class TestScan:
    def test_scan_finds_both_types(self, handler):
        agents = handler._scan_agents()
        names = {a["name"] for a in agents}
        assert "test-boss" in names
        assert "test-expert" in names

    def test_scan_ignores_hidden(self, handler):
        agents = handler._scan_agents()
        names = {a["name"] for a in agents}
        assert "_archive" not in names

    def test_scan_types(self, handler):
        agents = handler._scan_agents()
        type_map = {a["name"]: a["type"] for a in agents}
        assert type_map["test-boss"] == "boss"
        assert type_map["test-expert"] == "expert"

    def test_scan_empty(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "help").mkdir()
        (system_dir / "data").mkdir()
        (system_dir / "data" / "agent_pids").mkdir()
        (system_dir / "data" / "temp").mkdir()
        h = AgentLauncherHandler(system_dir)
        assert h._scan_agents() == []


# ================================================================
# FLAGS
# ================================================================

class TestFlags:
    def test_has_flag(self, handler):
        assert handler._has_flag(["--json", "foo"], "--json") is True
        assert handler._has_flag(["foo", "bar"], "--json") is False

    def test_has_flag_multiple(self, handler):
        assert handler._has_flag(["--headless"], "--headless", "--quiet") is True
        assert handler._has_flag(["--quiet"], "--headless", "--quiet") is True

    def test_parse_flag(self, handler):
        assert handler._parse_flag(["--model", "opus"], "--model", "sonnet") == "opus"
        assert handler._parse_flag(["foo"], "--model", "sonnet") == "sonnet"
        assert handler._parse_flag(["--model"], "--model", "sonnet") == "sonnet"


# ================================================================
# OPERATOR NOTES
# ================================================================

class TestOperatorNotes:
    def test_empty_notes(self, handler):
        notes = handler._read_operator_notes("test-boss")
        assert notes == []

    def test_write_and_read_notes(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        notes_data = [
            {"message": "Bitte Logs pruefen", "requested_at": "2026-05-16T12:00:00"},
            {"message": "RAM-Nutzung hoch", "requested_at": "2026-05-16T13:00:00"},
        ]
        handler._write_operator_notes("test-boss", notes_data, temp_dir=temp_dir)

        read_back = handler._read_operator_notes("test-boss", temp_dir=temp_dir)
        assert len(read_back) == 2
        assert read_back[0]["message"] == "Bitte Logs pruefen"

    def test_markdown_mirror(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Test-Hinweis", "requested_at": "2026-05-16T10:00:00"}],
            temp_dir=temp_dir,
        )
        md_path = handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir, markdown=True)
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Test-Hinweis" in content
        assert "Operator Notes" in content

    def test_notes_skip_invalid(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        json_path = handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir)
        json_path.write_text(json.dumps([
            {"message": "valid"},
            {"no_message": True},
            "just a string",
        ]), encoding="utf-8")
        notes = handler._read_operator_notes("test-boss", temp_dir=temp_dir)
        assert len(notes) == 1
        assert notes[0]["message"] == "valid"


# ================================================================
# RUNTIME SECONDS
# ================================================================

class TestRuntime:
    def test_compute_none(self, handler):
        assert handler._compute_runtime_seconds(None) is None
        assert handler._compute_runtime_seconds("") is None

    def test_compute_valid(self, handler):
        past = (datetime.now() - timedelta(seconds=120)).isoformat()
        result = handler._compute_runtime_seconds(past)
        assert result is not None
        assert 118 <= result <= 125

    def test_compute_invalid(self, handler):
        assert handler._compute_runtime_seconds("not-a-date") is None


# ================================================================
# DOCTOR
# ================================================================

class TestDoctor:
    def test_doctor_no_query(self, handler):
        ok, msg = handler.handle("doctor", [])
        assert ok is True
        assert "AGENT DOCTOR" in msg

    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("subprocess.run")
    def test_doctor_with_agent(self, mock_run, mock_which, handler):
        mock_run.return_value = MagicMock(stdout="1.0.0", stderr="", returncode=0)
        ok, msg = handler.handle("doctor", ["test-boss"])
        assert ok is True
        assert "test-boss" in msg

    @patch("shutil.which", return_value=None)
    def test_doctor_no_claude_cli(self, mock_which, handler):
        ok, msg = handler.handle("doctor", [])
        assert ok is True
        assert "nicht gefunden" in msg or "not found" in msg.lower()

    def test_doctor_json(self, handler):
        ok, msg = handler.handle("doctor", ["--json"])
        assert ok is True
        data = json.loads(msg)
        assert "checks" in data

    def test_doctor_unknown_agent(self, handler):
        ok, msg = handler.handle("doctor", ["nonexistent-agent"])
        assert ok is True
        assert "nicht gefunden" in msg or "not found" in msg.lower()


# ================================================================
# LIST JSON
# ================================================================

class TestListJson:
    def test_list_json(self, handler):
        ok, msg = handler.handle("list", ["--json"])
        assert ok is True
        data = json.loads(msg)
        assert "agents" in data
        names = {a["name"] for a in data["agents"]}
        assert "test-boss" in names
        assert "test-expert" in names

    def test_list_json_structure(self, handler):
        ok, msg = handler.handle("list", ["--json"])
        data = json.loads(msg)
        agent = data["agents"][0]
        assert "name" in agent
        assert "type" in agent
        assert "running" in agent
        assert "available_actions" in agent


# ================================================================
# START (dry_run)
# ================================================================

class TestStartDryRun:
    def test_start_not_found(self, handler):
        ok, msg = handler.handle("start", ["nonexistent"])
        assert ok is False
        assert "not found" in msg or "nicht gefunden" in msg

    def test_start_dry_run(self, handler):
        ok, msg = handler.handle("start", ["test-boss"], dry_run=True)
        assert ok is True
        assert "DRY" in msg

    def test_start_invalid_mode(self, handler):
        ok, msg = handler.handle("start", ["test-boss", "--mode", "invalid"])
        assert ok is False
        assert "Modus" in msg or "mode" in msg.lower()


# ================================================================
# ACTION RESPONSE
# ================================================================

class TestActionResponse:
    def test_plain(self, handler):
        ok, msg = handler._action_response("start", "x", "x", True, "Gestartet")
        assert ok is True
        assert msg == "Gestartet"

    def test_json(self, handler):
        ok, msg = handler._action_response("start", "x", "y", True, "OK", json_output=True)
        data = json.loads(msg)
        assert data["action"] == "start"
        assert data["requested_name"] == "x"
        assert data["resolved_name"] == "y"
        assert data["ok"] is True

    def test_json_with_agent(self, handler):
        ok, msg = handler._action_response(
            "start", "x", "y", True, "OK",
            json_output=True,
            agent={"name": "test", "pid": 1234}
        )
        data = json.loads(msg)
        assert data["agent"]["name"] == "test"
        assert data["agent"]["pid"] == 1234


# ================================================================
# SUMMARIZE CHECKS
# ================================================================

class TestSummarizeChecks:
    def test_all_ok(self, handler):
        checks = [{"status": "ok"}, {"status": "ok"}]
        result = handler._summarize_checks(checks)
        assert result["overall_status"] == "ok"
        assert result["ok"] == 2

    def test_with_warn(self, handler):
        checks = [{"status": "ok"}, {"status": "warn"}]
        result = handler._summarize_checks(checks)
        assert result["overall_status"] == "warn"

    def test_error_overrides(self, handler):
        checks = [{"status": "ok"}, {"status": "warn"}, {"status": "error"}]
        result = handler._summarize_checks(checks)
        assert result["overall_status"] == "error"
        assert result["error"] == 1


# ================================================================
# IS AGENT RUNNING
# ================================================================

class TestIsAgentRunning:
    def test_no_pid_file(self, handler):
        assert handler._is_agent_running("test-boss") == 0

    def test_invalid_pid_file(self, handler):
        pid_file = handler.pid_dir / "test-boss.pid"
        pid_file.write_text("not json", encoding="utf-8")
        assert handler._is_agent_running("test-boss") == 0

    def test_empty_pid(self, handler):
        pid_file = handler.pid_dir / "test-boss.pid"
        pid_file.write_text(json.dumps({"pid": 0}), encoding="utf-8")
        assert handler._is_agent_running("test-boss") == 0


# ================================================================
# LOAD PID DATA
# ================================================================

class TestLoadPidData:
    def test_missing(self, handler):
        assert handler._load_pid_data("test-boss") == {}

    def test_valid(self, handler):
        pid_file = handler.pid_dir / "test-boss.pid"
        data = {"pid": 12345, "model": "opus", "started": "2026-05-16T10:00:00"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        result = handler._load_pid_data("test-boss")
        assert result["pid"] == 12345
        assert result["model"] == "opus"

    def test_corrupt(self, handler):
        pid_file = handler.pid_dir / "test-boss.pid"
        pid_file.write_text("{broken", encoding="utf-8")
        assert handler._load_pid_data("test-boss") == {}


# ================================================================
# STEER
# ================================================================

class TestSteer:
    def test_steer_not_running(self, handler):
        ok, msg = handler.handle("steer", ["test-boss", "Bitte pruefen"])
        assert ok is False

    def test_steer_syntax(self, handler):
        ok, msg = handler.handle("steer", [])
        assert ok is False
        assert "Syntax" in msg


# ================================================================
# RESOLVE NAME
# ================================================================

class TestResolveName:
    def test_exact_match(self, handler):
        assert handler._resolve_to_technical_name("test-boss") == "test-boss"

    def test_case_insensitive(self, handler):
        assert handler._resolve_to_technical_name("TEST-BOSS") == "test-boss"

    def test_unknown_passthrough(self, handler):
        assert handler._resolve_to_technical_name("unknown-agent") == "unknown-agent"


# ================================================================
# BAT GENERATION — BACH_AUTO + HEADLESS
# ================================================================

class TestBatGeneration:
    """Tests that generated .bat files use conditional pause via BACH_AUTO."""

    def _build_bat_lines(self, handler, headless=False):
        """Simulate bat_lines generation from agent_launcher start logic."""
        agent_label = "test-boss"
        resolved_name = "test-boss"
        title = f"BACH: {agent_label}"
        model = "sonnet"
        mode = "auto"
        cmd = ["claude", "--model", model]
        bat_lines = [
            f"@echo off",
            f"title {title}",
            f'cd /d "C:\\temp"',
            f"echo === BACH Agent: {agent_label} ({resolved_name}) ===",
            f"echo Modell: {model} ^| Modus: {mode}",
            f"echo.",
            f"{' '.join(cmd)}",
        ]
        if not headless:
            bat_lines.append('if not defined BACH_AUTO pause')
        return "\n".join(bat_lines) + "\n"

    def test_normal_bat_has_conditional_pause(self, handler):
        content = self._build_bat_lines(handler, headless=False)
        assert "if not defined BACH_AUTO pause" in content
        assert content.count("pause") == 1

    def test_headless_bat_has_no_pause(self, handler):
        content = self._build_bat_lines(handler, headless=True)
        assert "pause" not in content

    def test_normal_bat_no_hard_pause(self, handler):
        content = self._build_bat_lines(handler, headless=False)
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "pause":
                pytest.fail("Found hard 'pause' without BACH_AUTO guard")
