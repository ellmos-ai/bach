# SPDX-License-Identifier: MIT
"""Tests for hub/scheduler.py — SchedulerHandler."""
import json
import os
import sqlite3
import sys
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.scheduler import SchedulerHandler, DaemonHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_scheduler_db(db_path: Path, *, jobs=True, runs=True):
    """Create a minimal scheduler DB with optional seed data."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_jobs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            job_type TEXT DEFAULT 'interval',
            schedule TEXT DEFAULT '',
            command TEXT DEFAULT '',
            script_path TEXT DEFAULT '',
            arguments TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            last_result TEXT,
            timeout_seconds INTEGER DEFAULT 60,
            retry_on_fail INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_runs (
            id INTEGER PRIMARY KEY,
            job_id INTEGER,
            result TEXT,
            output TEXT,
            error TEXT,
            started_at TEXT,
            finished_at TEXT,
            duration_seconds REAL DEFAULT 0,
            triggered_by TEXT DEFAULT 'schedule'
        )
    """)
    if jobs:
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active, next_run) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-echo", "interval", "30m", "echo hello", 1,
             (datetime.now() + timedelta(minutes=15)).isoformat()),
        )
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("disabled-job", "cron", "0 * * * *", "echo off", 0),
        )
    if runs:
        conn.execute(
            "INSERT INTO scheduler_runs (job_id, result, finished_at, duration_seconds, triggered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "success", datetime.now().isoformat(), 1.5, "schedule"),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def sched_env(tmp_path):
    """Full scheduler environment with DB, dirs, and seed data."""
    base = tmp_path / "system"
    base.mkdir()
    gui_dir = base / "gui"
    gui_dir.mkdir()
    data_dir = base / "data"
    data_dir.mkdir()
    log_dir = data_dir / "logs"
    log_dir.mkdir()

    (gui_dir / "daemon_service.py").write_text("# stub", encoding="utf-8")

    db_path = data_dir / "bach.db"
    _make_scheduler_db(db_path)

    session_dir = base / "hub" / "_services" / "daemon"
    session_dir.mkdir(parents=True)
    (session_dir / "session_daemon.py").write_text("# stub", encoding="utf-8")
    (session_dir / "auto_session.py").write_text("# stub", encoding="utf-8")
    profiles_dir = session_dir / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "ati.json").write_text(
        json.dumps({"description": "ATI Profil", "task_source": "ati_tasks",
                     "max_tasks": 3, "timeout_minutes": 15}),
        encoding="utf-8",
    )
    control_dir = session_dir / "control"
    control_dir.mkdir()

    config = {
        "enabled": True,
        "quiet_start": "22:00",
        "quiet_end": "08:00",
        "jobs": [
            {"profile": "ati", "interval_minutes": 60, "enabled": True}
        ],
    }
    (session_dir / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )

    handler = SchedulerHandler(base)
    return {
        "handler": handler,
        "base": base,
        "db_path": db_path,
        "data_dir": data_dir,
        "log_dir": log_dir,
        "gui_dir": gui_dir,
        "session_dir": session_dir,
        "profiles_dir": profiles_dir,
        "control_dir": control_dir,
    }


@pytest.fixture
def empty_env(tmp_path):
    """Minimal environment with no DB, no session dirs."""
    base = tmp_path / "system"
    base.mkdir()
    (base / "gui").mkdir()
    (base / "data").mkdir()
    (base / "data" / "logs").mkdir()
    return SchedulerHandler(base)


# ---------------------------------------------------------------------------
# Basic properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_profile_name(self, sched_env):
        assert sched_env["handler"].profile_name == "scheduler"

    def test_target_file(self, sched_env):
        h = sched_env["handler"]
        assert h.target_file == sched_env["gui_dir"] / "daemon_service.py"

    def test_get_operations_keys(self, sched_env):
        ops = sched_env["handler"].get_operations()
        assert "start" in ops
        assert "stop" in ops
        assert "status" in ops
        assert "doctor" in ops
        assert "jobs" in ops
        assert "run" in ops
        assert "logs" in ops
        assert "session" in ops

    def test_daemon_handler_alias(self):
        assert DaemonHandler is SchedulerHandler


# ---------------------------------------------------------------------------
# Utility methods
# ---------------------------------------------------------------------------

class TestUtilities:
    def test_has_flag_present(self, sched_env):
        h = sched_env["handler"]
        assert h._has_flag(["--json", "--bg"], "--json") is True

    def test_has_flag_absent(self, sched_env):
        h = sched_env["handler"]
        assert h._has_flag(["--bg"], "--json") is False

    def test_has_flag_multiple(self, sched_env):
        h = sched_env["handler"]
        assert h._has_flag(["--bg"], "--json", "--bg") is True

    def test_json_dump(self, sched_env):
        h = sched_env["handler"]
        result = h._json_dump({"key": "wert"})
        data = json.loads(result)
        assert data["key"] == "wert"

    def test_parse_datetime_value_valid(self, sched_env):
        h = sched_env["handler"]
        dt = h._parse_datetime_value("2026-05-16T12:00:00")
        assert dt.year == 2026

    def test_parse_datetime_value_none(self, sched_env):
        h = sched_env["handler"]
        assert h._parse_datetime_value(None) is None

    def test_parse_datetime_value_invalid(self, sched_env):
        h = sched_env["handler"]
        assert h._parse_datetime_value("not-a-date") is None

    def test_get_profile_from_args_default(self, sched_env):
        h = sched_env["handler"]
        assert h._get_profile_from_args([]) == "ati"

    def test_get_profile_from_args_custom(self, sched_env):
        h = sched_env["handler"]
        assert h._get_profile_from_args(["--profile", "research"]) == "research"

    def test_get_profile_from_args_custom_default(self, sched_env):
        h = sched_env["handler"]
        assert h._get_profile_from_args([], default="dev") == "dev"

    def test_strip_profile_and_flags(self, sched_env):
        h = sched_env["handler"]
        result = h._strip_profile_and_flags(["--profile", "ati", "some", "text", "--dry-run"])
        assert result == ["some", "text"]

    def test_strip_profile_and_flags_no_flags(self, sched_env):
        h = sched_env["handler"]
        result = h._strip_profile_and_flags(["hello", "world"])
        assert result == ["hello", "world"]

    def test_session_profile_slug_normal(self, sched_env):
        h = sched_env["handler"]
        assert h._session_profile_slug("ati") == "ati"

    def test_session_profile_slug_special_chars(self, sched_env):
        h = sched_env["handler"]
        assert h._session_profile_slug("my profile!") == "my_profile_"

    def test_session_profile_slug_empty(self, sched_env):
        h = sched_env["handler"]
        assert h._session_profile_slug("") == "ati"


# ---------------------------------------------------------------------------
# Doctor / Diagnostic checks
# ---------------------------------------------------------------------------

class TestDoctorChecks:
    def test_check_runtime_dir_exists(self, sched_env):
        h = sched_env["handler"]
        result = h._check_runtime_dir("data", sched_env["data_dir"], "Datenverzeichnis")
        assert result["status"] == "ok"
        assert result["name"] == "data"

    def test_check_runtime_dir_creates(self, sched_env):
        h = sched_env["handler"]
        new_dir = sched_env["base"] / "new_dir"
        result = h._check_runtime_dir("new", new_dir, "Neues Verzeichnis")
        assert result["status"] == "ok"
        assert new_dir.exists()

    def test_check_file_exists_ok(self, sched_env):
        h = sched_env["handler"]
        result = h._check_file_exists("script", sched_env["gui_dir"] / "daemon_service.py", "Script")
        assert result["status"] == "ok"

    def test_check_file_exists_missing_required(self, sched_env):
        h = sched_env["handler"]
        result = h._check_file_exists("script", sched_env["base"] / "nope.py", "Script", required=True)
        assert result["status"] == "error"

    def test_check_file_exists_missing_optional(self, sched_env):
        h = sched_env["handler"]
        result = h._check_file_exists("script", sched_env["base"] / "nope.py", "Script", required=False)
        assert result["status"] == "warn"

    def test_check_pid_state_running(self, sched_env):
        h = sched_env["handler"]
        result = h._check_pid_state("runtime", h.pid_file, 12345, "Service")
        assert result["status"] == "ok"
        assert "12345" in result["message"]

    def test_check_pid_state_no_pid_no_file(self, sched_env):
        h = sched_env["handler"]
        result = h._check_pid_state("runtime", h.pid_file, 0, "Service")
        assert result["status"] == "ok"
        assert "Keine laufende" in result["message"]

    def test_check_pid_state_stale_file(self, sched_env):
        h = sched_env["handler"]
        h.pid_file.write_text("99999", encoding="utf-8")
        result = h._check_pid_state("runtime", h.pid_file, 0, "Service")
        assert result["status"] == "warn"
        assert not h.pid_file.exists()

    def test_check_pid_state_invalid_file(self, sched_env):
        h = sched_env["handler"]
        h.pid_file.write_text("not-a-pid", encoding="utf-8")
        result = h._check_pid_state("runtime", h.pid_file, 0, "Service")
        assert result["status"] == "warn"
        assert "Ungültige" in result["message"]

    def test_summarize_checks_all_ok(self, sched_env):
        h = sched_env["handler"]
        checks = [{"status": "ok"}, {"status": "ok"}]
        summary = h._summarize_checks(checks)
        assert summary["overall_status"] == "ok"
        assert summary["ok"] == 2

    def test_summarize_checks_with_warn(self, sched_env):
        h = sched_env["handler"]
        checks = [{"status": "ok"}, {"status": "warn"}]
        summary = h._summarize_checks(checks)
        assert summary["overall_status"] == "warn"

    def test_summarize_checks_with_error(self, sched_env):
        h = sched_env["handler"]
        checks = [{"status": "ok"}, {"status": "warn"}, {"status": "error"}]
        summary = h._summarize_checks(checks)
        assert summary["overall_status"] == "error"

    def test_check_scheduler_db_ok(self, sched_env):
        h = sched_env["handler"]
        result = h._check_scheduler_db()
        assert result["status"] == "ok"
        assert "2" in result["message"] or "aktiv" in result["message"]

    def test_check_scheduler_db_missing(self, empty_env):
        h = empty_env
        result = h._check_scheduler_db()
        assert result["status"] == "error"

    def test_check_scheduler_db_no_jobs(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        db_path = data_dir / "bach.db"
        _make_scheduler_db(db_path, jobs=False, runs=False)
        h = SchedulerHandler(base)
        result = h._check_scheduler_db()
        assert result["status"] == "warn"
        assert "keine Jobs" in result["message"]

    def test_check_scheduler_db_failed_last_run(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        db_path = data_dir / "bach.db"
        _make_scheduler_db(db_path, runs=False)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_runs (job_id, result, finished_at, triggered_by) VALUES (?, ?, ?, ?)",
            (1, "failed", datetime.now().isoformat(), "schedule"),
        )
        conn.commit()
        conn.close()
        h = SchedulerHandler(base)
        result = h._check_scheduler_db()
        assert result["status"] == "warn"
        assert "failed" in result["message"]


class TestDoctorPayloads:
    def test_scheduler_doctor_payload_structure(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            payload = h._scheduler_doctor_payload()
        assert "generated_at" in payload
        assert "service" in payload
        assert "checks" in payload
        assert "summary" in payload
        assert "next_steps" in payload
        assert payload["service"]["kind"] == "scheduler"

    def test_scheduler_doctor_text(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h._doctor_scheduler()
        assert ok is True
        assert "SCHEDULER DOCTOR" in text

    def test_scheduler_doctor_json(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h._doctor_scheduler(json_output=True)
        assert ok is True
        data = json.loads(text)
        assert data["service"]["kind"] == "scheduler"

    def test_session_doctor_payload_structure(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            payload = h._session_doctor_payload()
        assert payload["service"]["kind"] == "session_scheduler"
        assert "checks" in payload
        assert "summary" in payload

    def test_session_doctor_text(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            ok, text = h._session_doctor(json_output=False)
        assert ok is True
        assert "SESSION SCHEDULER DOCTOR" in text

    def test_session_doctor_json(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            ok, text = h._session_doctor(json_output=True)
        assert ok is True
        data = json.loads(text)
        assert data["service"]["kind"] == "session_scheduler"

    def test_session_doctor_warns_when_legacy_runtime_is_deprecated(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        session_dir = base / "hub" / "_services" / "daemon"
        profiles_dir = session_dir / "profiles"
        profiles_dir.mkdir(parents=True)

        (session_dir / "session_daemon.py").write_text('"""DEPRECATED legacy daemon"""', encoding="utf-8")
        (session_dir / "auto_session.py").write_text('"""DEPRECATED legacy trigger"""', encoding="utf-8")
        (session_dir / "config.json").write_text(
            json.dumps(
                {
                    "enabled": False,
                    "quiet_start": "22:00",
                    "quiet_end": "08:00",
                    "jobs": [{"profile": "ati", "interval_minutes": 30, "enabled": False}],
                }
            ),
            encoding="utf-8",
        )
        (profiles_dir / "ati.json").write_text("{}", encoding="utf-8")

        h = SchedulerHandler(base)
        payload = h._session_doctor_payload()
        checks = {check["name"]: check for check in payload["checks"]}

        assert payload["summary"]["overall_status"] == "warn"
        assert payload["summary"]["ready"] is True
        assert payload["summary"]["can_start"] is False
        assert checks["policy"]["status"] == "warn"
        assert checks["policy"]["details"]["deprecated"] is True
        assert any("Buddha Control API" in step for step in payload["next_steps"])

    def test_format_doctor_text_structure(self, sched_env):
        h = sched_env["handler"]
        payload = {
            "generated_at": "2026-05-16T12:00:00",
            "service": {"label": "Test-Service"},
            "checks": [
                {"status": "ok", "message": "Alles gut", "details": {"path": "/tmp"}},
                {"status": "warn", "message": "Achtung", "details": {"pid_file": "/tmp/pid"}},
            ],
            "summary": {
                "overall_status": "warn",
                "ready": True,
                "running": False,
                "can_start": True,
            },
            "next_steps": ["Schritt 1", "Schritt 2"],
        }
        text = h._format_doctor_text(payload, "TEST")
        assert "=== TEST DOCTOR ===" in text
        assert "Test-Service" in text
        assert "[OK] Alles gut" in text
        assert "[WARN] Achtung" in text
        assert "Schritt 1" in text


# ---------------------------------------------------------------------------
# Session config checks
# ---------------------------------------------------------------------------

class TestSessionConfigChecks:
    def test_check_session_config_ok(self, sched_env):
        h = sched_env["handler"]
        config_file = sched_env["session_dir"] / "config.json"
        result = h._check_session_config(config_file)
        assert result["status"] == "ok"
        assert "1 Job" in result["message"]

    def test_check_session_config_missing(self, sched_env):
        h = sched_env["handler"]
        result = h._check_session_config(sched_env["base"] / "missing.json")
        assert result["status"] == "warn"

    def test_check_session_config_invalid_json(self, sched_env):
        h = sched_env["handler"]
        bad = sched_env["session_dir"] / "bad.json"
        bad.write_text("{invalid json", encoding="utf-8")
        result = h._check_session_config(bad)
        assert result["status"] == "error"

    def test_check_session_config_no_jobs(self, sched_env):
        h = sched_env["handler"]
        empty_cfg = sched_env["session_dir"] / "empty_config.json"
        empty_cfg.write_text('{"enabled": true, "jobs": []}', encoding="utf-8")
        result = h._check_session_config(empty_cfg)
        assert result["status"] == "warn"
        assert "keine Jobs" in result["message"]

    def test_check_session_profiles_ok(self, sched_env):
        h = sched_env["handler"]
        result = h._check_session_profiles()
        assert result["status"] == "ok"
        assert "1 Session-Profil" in result["message"]

    def test_check_session_profiles_missing_dir(self, empty_env):
        h = empty_env
        result = h._check_session_profiles()
        assert result["status"] == "error"

    def test_check_session_profiles_empty_dir(self, sched_env):
        h = sched_env["handler"]
        for f in sched_env["profiles_dir"].glob("*.json"):
            f.unlink()
        result = h._check_session_profiles()
        assert result["status"] == "warn"


# ---------------------------------------------------------------------------
# Job status computation
# ---------------------------------------------------------------------------

class TestJobStatus:
    def _make_row(self, **overrides):
        defaults = {
            "is_active": 1,
            "next_run": (datetime.now() + timedelta(hours=1)).isoformat(),
            "last_result": "success",
        }
        defaults.update(overrides)
        return defaults

    def test_disabled(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(is_active=0)
        assert h._compute_job_status(row, datetime.now()) == "disabled"

    def test_error_status(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(last_result="failed")
        assert h._compute_job_status(row, datetime.now()) == "error"

    def test_timeout_status(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(last_result="timeout")
        assert h._compute_job_status(row, datetime.now()) == "error"

    def test_due_status(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(
            next_run=(datetime.now() - timedelta(minutes=5)).isoformat(),
            last_result="success",
        )
        assert h._compute_job_status(row, datetime.now()) == "due"

    def test_scheduled_status(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(last_result="success")
        assert h._compute_job_status(row, datetime.now()) == "scheduled"

    def test_ok_status(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(next_run=None, last_result="success")
        assert h._compute_job_status(row, datetime.now()) == "ok"

    def test_idle_status(self, sched_env):
        h = sched_env["handler"]
        row = self._make_row(next_run=None, last_result="")
        assert h._compute_job_status(row, datetime.now()) == "idle"

    def test_serialize_job_row(self, sched_env):
        h = sched_env["handler"]
        now = datetime.now()
        future = (now + timedelta(minutes=30)).isoformat()
        row = {
            "id": 1, "name": "test", "description": "desc", "job_type": "interval",
            "schedule": "30m", "command": "echo hi", "script_path": "", "arguments": "",
            "is_active": 1, "last_run": now.isoformat(), "next_run": future,
            "last_result": "success", "run_count": 5, "success_count": 4,
            "fail_count": 1, "timeout_seconds": 60, "retry_on_fail": 0, "max_retries": 0,
        }
        serialized = h._serialize_job_row(row, now)
        assert serialized["id"] == 1
        assert serialized["name"] == "test"
        assert serialized["status"] == "scheduled"
        assert serialized["due_in_seconds"] is not None
        assert serialized["due_in_seconds"] > 0

    def test_serialize_job_row_overdue(self, sched_env):
        h = sched_env["handler"]
        now = datetime.now()
        past = (now - timedelta(minutes=10)).isoformat()
        row = {
            "id": 2, "name": "overdue", "description": "", "job_type": "cron",
            "schedule": "*/5 * * * *", "command": "echo", "script_path": "",
            "arguments": "", "is_active": 1, "last_run": None, "next_run": past,
            "last_result": "success", "run_count": 0, "success_count": 0,
            "fail_count": 0, "timeout_seconds": 30, "retry_on_fail": 0, "max_retries": 0,
        }
        serialized = h._serialize_job_row(row, now)
        assert serialized["overdue_seconds"] is not None
        assert serialized["overdue_seconds"] > 0
        assert serialized["due_in_seconds"] is None


# ---------------------------------------------------------------------------
# DB-based operations: _list_jobs, _show_status
# ---------------------------------------------------------------------------

class TestDBOperations:
    def test_list_jobs_text(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._list_jobs()
        assert ok is True
        assert "test-echo" in text
        assert "disabled-job" in text

    def test_list_jobs_json(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._list_jobs(json_output=True)
        assert ok is True
        data = json.loads(text)
        assert len(data["jobs"]) == 2

    def test_list_jobs_no_db(self, empty_env):
        h = empty_env
        ok, text = h._list_jobs()
        assert ok is False
        assert "nicht gefunden" in text

    def test_show_status_text(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h._show_status()
        assert ok is True
        assert "SCHEDULER STATUS" in text
        assert "STOPPED" in text

    def test_show_status_running(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=42):
            ok, text = h._show_status()
        assert ok is True
        assert "RUNNING" in text

    def test_show_status_json(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h._show_status(json_output=True)
        assert ok is True
        data = json.loads(text)
        assert data["service"]["running"] is False
        assert data["jobs"]["total"] == 2
        assert data["jobs"]["active"] == 1

    def test_show_status_json_recent_runs(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h._show_status(json_output=True)
        data = json.loads(text)
        assert len(data["recent_runs"]) == 1
        assert data["recent_runs"][0]["result"] == "success"


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

class TestLogs:
    def test_show_logs(self, sched_env):
        log_file = sched_env["log_dir"] / "daemon.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(30)), encoding="utf-8")
        h = sched_env["handler"]
        ok, text = h._show_logs(5)
        assert ok is True
        assert "line 29" in text
        assert "line 25" in text
        assert "line 24" not in text

    def test_show_logs_missing(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._show_logs()
        assert ok is False
        assert "nicht gefunden" in text


# ---------------------------------------------------------------------------
# Session control: pause, resume, steer, clear-steer
# ---------------------------------------------------------------------------

class TestSessionControl:
    def test_session_pause(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_pause(["--profile", "ati", "Wartung"], dry_run=False)
        assert ok is True
        assert "pausiert" in text
        pause_file = h._session_pause_file("ati")
        assert pause_file.exists()
        data = json.loads(pause_file.read_text(encoding="utf-8"))
        assert data["reason"] == "Wartung"

    def test_session_pause_dry_run(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_pause(["--profile", "ati"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text
        assert not h._session_pause_file("ati").exists()

    def test_session_pause_default_reason(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_pause([], dry_run=False)
        assert ok is True
        data = json.loads(h._session_pause_file("ati").read_text(encoding="utf-8"))
        assert data["reason"] == "Manuell pausiert"

    def test_session_resume(self, sched_env):
        h = sched_env["handler"]
        h._session_pause([], dry_run=False)
        assert h._session_pause_file("ati").exists()
        ok, text = h._session_resume([], dry_run=False)
        assert ok is True
        assert "aufgehoben" in text
        assert not h._session_pause_file("ati").exists()

    def test_session_resume_no_pause(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_resume([], dry_run=False)
        assert ok is True
        assert "Keine Pause" in text

    def test_session_resume_dry_run(self, sched_env):
        h = sched_env["handler"]
        h._session_pause([], dry_run=False)
        ok, text = h._session_resume([], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text
        assert h._session_pause_file("ati").exists()

    def test_session_steer(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_steer(["--profile", "ati", "Fix", "Bug"], dry_run=False)
        assert ok is True
        assert "vorgemerkt" in text
        steer_file = h._session_steer_file("ati")
        data = json.loads(steer_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["message"] == "Fix Bug"

    def test_session_steer_accumulates(self, sched_env):
        h = sched_env["handler"]
        h._session_steer(["Hinweis 1"], dry_run=False)
        h._session_steer(["Hinweis 2"], dry_run=False)
        steer_file = h._session_steer_file("ati")
        data = json.loads(steer_file.read_text(encoding="utf-8"))
        assert len(data) == 2

    def test_session_steer_empty_message(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_steer([], dry_run=False)
        assert ok is False
        assert "ERROR" in text

    def test_session_steer_dry_run(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_steer(["Test"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text

    def test_session_clear_steer(self, sched_env):
        h = sched_env["handler"]
        h._session_steer(["Hinweis"], dry_run=False)
        ok, text = h._session_clear_steer([], dry_run=False)
        assert ok is True
        assert "gelöscht" in text
        assert not h._session_steer_file("ati").exists()

    def test_session_clear_steer_empty(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_clear_steer([], dry_run=False)
        assert ok is True
        assert "Keine" in text

    def test_session_clear_steer_dry_run(self, sched_env):
        h = sched_env["handler"]
        h._session_steer(["Hinweis"], dry_run=False)
        ok, text = h._session_clear_steer([], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text
        assert h._session_steer_file("ati").exists()


# ---------------------------------------------------------------------------
# Session control read helpers
# ---------------------------------------------------------------------------

class TestSessionReadHelpers:
    def test_session_read_json_missing(self, sched_env):
        h = sched_env["handler"]
        result = h._session_read_json(sched_env["base"] / "nope.json", {"default": True})
        assert result == {"default": True}

    def test_session_read_json_valid(self, sched_env):
        h = sched_env["handler"]
        path = sched_env["control_dir"] / "test.json"
        path.write_text('{"key": 42}', encoding="utf-8")
        result = h._session_read_json(path, {})
        assert result["key"] == 42

    def test_session_read_json_corrupt(self, sched_env):
        h = sched_env["handler"]
        path = sched_env["control_dir"] / "bad.json"
        path.write_text("not json!", encoding="utf-8")
        result = h._session_read_json(path, [])
        assert result == []

    def test_get_pause_request_none(self, sched_env):
        h = sched_env["handler"]
        assert h._session_get_pause_request("ati") is None

    def test_get_pause_request_valid(self, sched_env):
        h = sched_env["handler"]
        h._session_pause(["--profile", "ati", "Test"], dry_run=False)
        result = h._session_get_pause_request("ati")
        assert result is not None
        assert result["reason"] == "Test"

    def test_peek_steer_requests_empty(self, sched_env):
        h = sched_env["handler"]
        result = h._session_peek_steer_requests("ati")
        assert result == []

    def test_peek_steer_requests_populated(self, sched_env):
        h = sched_env["handler"]
        h._session_steer(["Message 1"], dry_run=False)
        h._session_steer(["Message 2"], dry_run=False)
        result = h._session_peek_steer_requests("ati")
        assert len(result) == 2
        assert result[0]["message"] == "Message 1"

    def test_control_snapshot(self, sched_env):
        h = sched_env["handler"]
        snap = h._session_control_snapshot("ati")
        assert snap["profile"] == "ati"
        assert snap["pause_requested"] is False
        assert snap["pending_steer_count"] == 0

    def test_control_snapshot_with_pause_and_steer(self, sched_env):
        h = sched_env["handler"]
        h._session_pause(["Grund"], dry_run=False)
        h._session_steer(["Tipp"], dry_run=False)
        snap = h._session_control_snapshot("ati")
        assert snap["pause_requested"] is True
        assert snap["pause_reason"] == "Grund"
        assert snap["pending_steer_count"] == 1
        assert snap["latest_steer_message"] == "Tipp"


# ---------------------------------------------------------------------------
# Session status and profiles
# ---------------------------------------------------------------------------

class TestSessionStatus:
    def test_session_status_text(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            ok, text = h._session_status()
        assert ok is True
        assert "SESSION SCHEDULER STATUS" in text
        assert "STOPPED" in text

    def test_session_status_running(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=99):
            ok, text = h._session_status()
        assert ok is True
        assert "RUNNING" in text

    def test_session_status_json(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            ok, text = h._session_status(json_output=True)
        assert ok is True
        data = json.loads(text)
        assert data["service"]["running"] is False
        assert "ati" in data["profiles"]

    def test_session_status_json_marks_deprecated_runtime(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        session_dir = base / "hub" / "_services" / "daemon"
        profiles_dir = session_dir / "profiles"
        profiles_dir.mkdir(parents=True)

        (session_dir / "session_daemon.py").write_text('"""DEPRECATED legacy daemon"""', encoding="utf-8")
        (session_dir / "auto_session.py").write_text('"""DEPRECATED legacy trigger"""', encoding="utf-8")
        (session_dir / "config.json").write_text(
            json.dumps({"enabled": False, "jobs": [{"profile": "ati", "interval_minutes": 30, "enabled": False}]}),
            encoding="utf-8",
        )
        (profiles_dir / "ati.json").write_text("{}", encoding="utf-8")

        h = SchedulerHandler(base)
        ok, text = h._session_status(json_output=True)
        assert ok is True
        data = json.loads(text)
        assert data["service"]["deprecated"] is True
        assert data["service"]["available_actions"] == []
        assert "Buddha Control API (:8081/api/chat)" in data["service"]["recommended_replacements"]

    def test_session_profiles(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_profiles()
        assert ok is True
        assert "ati" in text
        assert "ATI Profil" in text
        assert text.count("--- Verwendung ---") == 1

    def test_session_start_requires_force_when_runtime_is_deprecated(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        session_dir = base / "hub" / "_services" / "daemon"
        profiles_dir = session_dir / "profiles"
        profiles_dir.mkdir(parents=True)

        (session_dir / "session_daemon.py").write_text('"""DEPRECATED legacy daemon"""', encoding="utf-8")
        (session_dir / "auto_session.py").write_text('"""DEPRECATED legacy trigger"""', encoding="utf-8")
        (session_dir / "config.json").write_text(json.dumps({"enabled": False, "jobs": []}), encoding="utf-8")
        (profiles_dir / "ati.json").write_text("{}", encoding="utf-8")

        h = SchedulerHandler(base)
        ok, text = h._session_start(["--profile", "ati"], dry_run=False)
        assert ok is False
        assert "--force" in text
        assert "deprecated" in text.lower()

    def test_session_profiles_missing_dir(self, empty_env):
        h = empty_env
        ok, text = h._session_profiles()
        assert ok is False
        assert "nicht gefunden" in text

    def test_session_help(self, sched_env):
        h = sched_env["handler"]
        ok, text = h._session_help()
        assert ok is True
        assert "SESSION SYSTEM" in text
        assert "bach scheduler session" in text


# ---------------------------------------------------------------------------
# Handle dispatch
# ---------------------------------------------------------------------------

class TestHandleDispatch:
    def test_handle_status(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h.handle("status", [])
        assert ok is True
        assert "SCHEDULER STATUS" in text

    def test_handle_status_json(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h.handle("status", ["--json"])
        assert ok is True
        data = json.loads(text)
        assert "service" in data

    def test_handle_doctor(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h.handle("doctor", [])
        assert ok is True
        assert "DOCTOR" in text

    def test_handle_jobs(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("jobs", [])
        assert ok is True
        assert "test-echo" in text

    def test_handle_jobs_json(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("jobs", ["--json"])
        assert ok is True
        data = json.loads(text)
        assert len(data["jobs"]) == 2

    def test_handle_logs_missing(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("logs", [])
        assert ok is False

    def test_handle_run_no_id(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("run", [])
        assert ok is False
        assert "Job-ID erforderlich" in text

    def test_handle_run_invalid_id(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("run", ["abc"])
        assert ok is False
        assert "Ungueltige" in text

    def test_handle_run_dry_run(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("run", ["1"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text

    def test_handle_start_dry_run(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("start", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text

    def test_handle_start_missing_script(self, empty_env):
        h = empty_env
        ok, text = h.handle("start", [])
        assert ok is False
        assert "nicht gefunden" in text

    def test_handle_start_already_running(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_is_running", return_value=True):
            ok, text = h.handle("start", [])
        assert ok is False
        assert "bereits" in text

    def test_handle_stop_not_running(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_is_running", return_value=False):
            ok, text = h.handle("stop", [])
        assert ok is False
        assert "nicht" in text.lower()

    def test_handle_stop_dry_run(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_is_running", return_value=True):
            ok, text = h.handle("stop", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text

    def test_handle_session_dispatch(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            ok, text = h.handle("session", ["status"])
        assert ok is True
        assert "SESSION SCHEDULER STATUS" in text

    def test_handle_session_profiles(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("session", ["profiles"])
        assert ok is True
        assert "ati" in text

    def test_handle_session_help(self, sched_env):
        h = sched_env["handler"]
        ok, text = h.handle("session", ["unknown_cmd"])
        assert ok is True
        assert "SESSION SYSTEM" in text

    def test_handle_session_empty(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_session_is_running", return_value=0):
            ok, text = h.handle("session", [])
        assert ok is True
        assert "SESSION SCHEDULER STATUS" in text

    def test_handle_unknown_falls_to_status(self, sched_env):
        h = sched_env["handler"]
        with patch.object(h, "_get_daemon_pid", return_value=0):
            ok, text = h.handle("unknown_op", [])
        assert ok is True
        assert "SCHEDULER STATUS" in text


# ---------------------------------------------------------------------------
# Connection leak check (DB operations close connections)
# ---------------------------------------------------------------------------

class TestConnectionLeaks:
    def test_check_scheduler_db_closes_conn(self, sched_env):
        h = sched_env["handler"]
        original_connect = sqlite3.connect
        connections = []

        def tracking_connect(*args, **kwargs):
            conn = original_connect(*args, **kwargs)
            connections.append(conn)
            return conn

        with patch("sqlite3.connect", side_effect=tracking_connect):
            h._check_scheduler_db()
        for conn in connections:
            try:
                conn.execute("SELECT 1")
                closed = False
            except Exception:
                closed = True
            assert closed, "Connection not closed after _check_scheduler_db"

    def test_list_jobs_closes_conn(self, sched_env):
        h = sched_env["handler"]
        original_connect = sqlite3.connect
        connections = []

        def tracking_connect(*args, **kwargs):
            conn = original_connect(*args, **kwargs)
            connections.append(conn)
            return conn

        with patch("sqlite3.connect", side_effect=tracking_connect):
            h._list_jobs()
        for conn in connections:
            try:
                conn.execute("SELECT 1")
                closed = False
            except Exception:
                closed = True
            assert closed, "Connection not closed after _list_jobs"
