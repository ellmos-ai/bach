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
        assert "pause" in ops
        assert "resume" in ops
        assert "clear-steer" in ops
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

    def test_clear_steer_too_few_args(self, handler):
        ok, msg = handler.handle("clear-steer", [])
        assert ok is False
        assert "clear-steer" in msg

    def test_pause_too_few_args(self, handler):
        ok, msg = handler.handle("pause", [])
        assert ok is False
        assert "pause" in msg.lower()

    def test_resume_too_few_args(self, handler):
        ok, msg = handler.handle("resume", [])
        assert ok is False
        assert "resume" in msg.lower()

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

    def test_parse_max_turns(self, handler):
        assert handler._parse_max_turns("7") == 7
        assert handler._parse_max_turns("") is None

    def test_parse_max_turns_rejects_invalid(self, handler):
        with pytest.raises(ValueError):
            handler._parse_max_turns("0")

    def test_load_agent_runtime_defaults(self, handler):
        skill_file = handler.agents_dir / "test-boss" / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: test-boss\n"
            "agent_runtime:\n"
            "  permission_mode: full\n"
            "  allowed_tools:\n"
            "    - Read\n"
            "    - Bash\n"
            "  max_turns: 9\n"
            "---\n"
            "# Test Boss\n",
            encoding="utf-8",
        )
        defaults = handler._load_agent_runtime_defaults(skill_file)
        assert defaults["permission_mode"] == "full"
        assert defaults["allowed_tools"] is None
        assert defaults["max_turns"] == 9


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

    def test_pause_request_updates_markdown(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Test-Hinweis", "requested_at": "2026-05-16T10:00:00"}],
            temp_dir=temp_dir,
        )
        handler._write_pause_request(
            "test-boss",
            {"reason": "Kurz warten", "requested_at": "2026-05-16T10:05:00"},
            temp_dir=temp_dir,
        )
        md_path = handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir, markdown=True)
        content = md_path.read_text(encoding="utf-8")
        assert "Pause Request" in content
        assert "Kurz warten" in content
        assert "naechsten Start in die initiale CLAUDE.md" in content

    def test_clear_operator_notes_keeps_pause_markdown(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Test-Hinweis", "requested_at": "2026-05-16T10:00:00"}],
            temp_dir=temp_dir,
        )
        handler._write_pause_request(
            "test-boss",
            {"reason": "Kurz warten", "requested_at": "2026-05-16T10:05:00"},
            temp_dir=temp_dir,
        )
        removed = handler._clear_operator_notes("test-boss", temp_dir=temp_dir)
        assert removed == 1
        md_path = handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir, markdown=True)
        assert md_path.exists()
        assert "Pause Request" in md_path.read_text(encoding="utf-8")

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

    def test_clear_operator_notes_removes_json_and_markdown(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Bitte löschen", "requested_at": "2026-05-16T11:00:00"}],
            temp_dir=temp_dir,
        )
        removed = handler._clear_operator_notes("test-boss", temp_dir=temp_dir)
        assert removed == 1
        assert not handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir).exists()
        assert not handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir, markdown=True).exists()


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
        assert "operator_control" in agent
        assert "available_actions" in agent["operator_control"]


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

    def test_start_dry_run_uses_runtime_defaults(self, handler):
        skill_file = handler.agents_dir / "test-boss" / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: test-boss\n"
            "agent_runtime:\n"
            "  permission_mode: restricted\n"
            "  allowed_tools: Read,Grep\n"
            "  max_turns: 5\n"
            "---\n"
            "# Test Boss\n",
            encoding="utf-8",
        )
        ok, msg = handler.handle("start", ["test-boss", "--json"], dry_run=True)
        assert ok is True
        data = json.loads(msg)
        assert data["agent"]["permission_mode"] == "restricted"
        assert data["agent"]["allowed_tools"] == "Read,Grep"
        assert data["agent"]["max_turns"] == 5
        assert data["agent"]["runtime_defaults"]["max_turns"] == 5

    def test_start_invalid_permission_mode(self, handler):
        ok, msg = handler.handle(
            "start",
            ["test-boss", "--permission-mode", "unsafe", "--json"],
        )
        assert ok is False
        assert "Permission-Modus" in msg

    def test_start_invalid_max_turns(self, handler):
        ok, msg = handler.handle(
            "start",
            ["test-boss", "--max-turns", "0", "--json"],
        )
        assert ok is False
        assert "Max-Turns" in msg


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
        ok, msg = handler.handle("steer", ["test-boss", "Bitte pruefen", "--json"])
        assert ok is True
        payload = json.loads(msg)
        assert payload["agent"]["status"] == "queued"
        assert payload["agent"]["pending_operator_notes"] == 1
        assert payload["agent"]["queued_for_next_start"] is True
        assert "start" in payload["agent"]["available_actions"]
        assert "clear-steer" in payload["agent"]["available_actions"]

    def test_steer_marks_checkpoint_ack_as_pending(self, handler, monkeypatch):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        (handler.temp_dir / "agent_test-boss").mkdir(parents=True, exist_ok=True)
        pid_file = handler.pid_dir / "test-boss.pid"
        pid_file.write_text(
            json.dumps(
                {
                    "pid": 4242,
                    "name": "test-boss",
                    "display_name": "Test Boss",
                    "type": "boss",
                    "model": "sonnet",
                    "mode": "default",
                    "started": "2026-05-16T12:00:00",
                    "temp_dir": temp_dir,
                    "window_title": "BACH: Test Boss",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

        ok, msg = handler.handle("steer", ["test-boss", "Bitte pruefen", "--json"])

        assert ok is True
        payload = json.loads(msg)
        assert payload["agent"]["operator_control"]["awaiting_checkpoint_ack"] is True
        assert "checkpoint" in payload["agent"]["operator_control"]["available_actions"]

    def test_steer_syntax(self, handler):
        ok, msg = handler.handle("steer", [])
        assert ok is False
        assert "Syntax" in msg

    def test_steer_unknown_agent(self, handler):
        ok, msg = handler.handle("steer", ["unknown-agent", "Bitte pruefen"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_clear_steer_empty_queue(self, handler):
        ok, msg = handler.handle("clear-steer", ["test-boss"])
        assert ok is True
        assert "Keine Operator-Hinweise" in msg

    def test_clear_steer_removes_pending_queue(self, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Bitte löschen", "requested_at": "2026-05-16T11:00:00"}],
            temp_dir=temp_dir,
        )

        ok, msg = handler.handle("clear-steer", ["test-boss"])

        assert ok is True
        assert "gelöscht" in msg
        assert handler._read_operator_notes("test-boss", temp_dir=temp_dir) == []
        assert not handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir).exists()
        assert not handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir, markdown=True).exists()

    @patch("subprocess.Popen")
    def test_start_preserves_prelaunch_operator_notes(self, mock_popen, handler):
        temp_dir = str(handler.temp_dir / "agent_test-boss")
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Vor dem Start pruefen", "requested_at": "2026-05-20T12:00:00"}],
            temp_dir=temp_dir,
        )
        mock_popen.return_value = MagicMock(pid=4321)

        ok, msg = handler.handle("start", ["test-boss", "--json"])

        assert ok is True
        payload = json.loads(msg)
        assert payload["agent"]["pending_operator_notes"] == 1
        assert payload["agent"]["latest_operator_note"] == "Vor dem Start pruefen"
        notes = handler._read_operator_notes("test-boss", temp_dir=temp_dir)
        assert len(notes) == 1
        assert notes[0]["message"] == "Vor dem Start pruefen"
        claude_md = Path(temp_dir) / "CLAUDE.md"
        assert claude_md.exists()
        claude_content = claude_md.read_text(encoding="utf-8")
        assert "Diese Hinweise waren bereits vor diesem Start vorgemerkt und gelten sofort" in claude_content
        assert "Vor dem Start pruefen" in claude_content
        assert "sicheren Checkpoints" in claude_content


class TestPauseResume:
    def _running_pid_fixture(self, handler):
        temp_dir = handler.temp_dir / "agent_test-boss"
        temp_dir.mkdir(parents=True, exist_ok=True)
        pid_file = handler.pid_dir / "test-boss.pid"
        pid_file.write_text(
            json.dumps(
                {
                    "pid": 4242,
                    "name": "test-boss",
                    "display_name": "Test Boss",
                    "type": "boss",
                    "model": "sonnet",
                    "mode": "default",
                    "started": "2026-05-16T12:00:00",
                    "temp_dir": str(temp_dir),
                    "window_title": "BACH: Test Boss",
                }
            ),
            encoding="utf-8",
        )
        return str(temp_dir)

    def test_pause_not_running(self, handler):
        ok, msg = handler.handle("pause", ["test-boss", "--json"])
        assert ok is False
        payload = json.loads(msg)
        assert payload["action"] == "pause"
        assert payload["agent"]["operator_control"]["pause_requested"] is False

    def test_pause_running_sets_control_snapshot(self, handler, monkeypatch):
        temp_dir = self._running_pid_fixture(handler)
        monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

        ok, msg = handler.handle("pause", ["test-boss", "Kurz warten", "--json"])

        assert ok is True
        payload = json.loads(msg)
        assert payload["agent"]["status"] == "pause-requested"
        assert payload["agent"]["operator_control"]["pause_requested"] is True
        assert payload["agent"]["operator_control"]["pause_reason"] == "Kurz warten"
        assert payload["agent"]["operator_control"]["available_actions"][0] == "resume"
        pause_path = handler._agent_pause_request_path("test-boss", temp_dir=temp_dir)
        assert pause_path.exists()

    def test_resume_clears_pause_request(self, handler, monkeypatch):
        temp_dir = self._running_pid_fixture(handler)
        handler._write_pause_request(
            "test-boss",
            {"reason": "Kurz warten", "requested_at": "2026-05-16T12:05:00"},
            temp_dir=temp_dir,
        )
        monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

        ok, msg = handler.handle("resume", ["test-boss", "--json"])

        assert ok is True
        payload = json.loads(msg)
        assert payload["agent"]["status"] == "running"
        assert payload["agent"]["operator_control"]["pause_requested"] is False
        assert not handler._agent_pause_request_path("test-boss", temp_dir=temp_dir).exists()

    def test_checkpoint_not_running(self, handler):
        ok, msg = handler.handle("checkpoint", ["test-boss", "--json"])
        assert ok is False
        payload = json.loads(msg)
        assert payload["action"] == "checkpoint"
        assert payload["agent"]["operator_control"]["last_checkpoint_at"] is None

    def test_checkpoint_running_records_acknowledgement(self, handler, monkeypatch):
        temp_dir = self._running_pid_fixture(handler)
        handler._write_operator_notes(
            "test-boss",
            [{"message": "Bitte pruefen", "requested_at": "2026-05-16T12:05:00"}],
            temp_dir=temp_dir,
        )
        monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

        ok, msg = handler.handle("checkpoint", ["test-boss", "Am sicheren Punkt", "--json"])

        assert ok is True
        payload = json.loads(msg)
        assert payload["agent"]["operator_control"]["last_checkpoint_message"] == "Am sicheren Punkt"
        assert payload["agent"]["operator_control"]["awaiting_checkpoint_ack"] is False
        checkpoint_path = handler._agent_checkpoint_path("test-boss", temp_dir=temp_dir)
        assert checkpoint_path.exists()
        markdown = handler._agent_operator_notes_path("test-boss", temp_dir=temp_dir, markdown=True).read_text(encoding="utf-8")
        assert "## Last Checkpoint" in markdown
        assert "Am sicheren Punkt" in markdown

    def test_status_json_shows_pause_requested_for_running_agent(self, handler, monkeypatch):
        temp_dir = self._running_pid_fixture(handler)
        handler._write_pause_request(
            "test-boss",
            {"reason": "Kurz warten", "requested_at": "2026-05-16T12:05:00"},
            temp_dir=temp_dir,
        )
        monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

        ok, msg = handler.handle("status", ["--json"])

        assert ok is True
        payload = json.loads(msg)
        assert payload["agents"][0]["status"] == "pause-requested"
        assert payload["agents"][0]["operator_control"]["pause_requested"] is True


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
