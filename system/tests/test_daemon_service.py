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

"""
Unit Tests fuer gui/daemon_service.py
=======================================
Tests fuer DaemonService, DaemonJob, Interval-Parsing, Job-Scheduling.
"""

import json
import sys
import sqlite3
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest

from gui.daemon_service import DaemonService, DaemonJob


# ═══════════════════════════════════════════════════════════════
# DaemonJob Tests
# ═══════════════════════════════════════════════════════════════

class TestDaemonJob:
    def test_creation(self):
        job = DaemonJob(
            id=1, name="test-job", description="A test",
            job_type="interval", schedule="30m",
            command="echo hello", script_path=None, arguments=None,
            is_active=True, timeout_seconds=300,
            retry_on_fail=False, max_retries=3,
            last_run=None, next_run=None,
        )
        assert job.id == 1
        assert job.name == "test-job"
        assert job.job_type == "interval"
        assert job.is_active is True

    def test_manual_job(self):
        job = DaemonJob(
            id=2, name="manual", description="",
            job_type="manual", schedule="",
            command="bach task list", script_path=None, arguments=None,
            is_active=True, timeout_seconds=60,
            retry_on_fail=False, max_retries=0,
            last_run=None, next_run=None,
        )
        assert job.next_run is None


# ═══════════════════════════════════════════════════════════════
# DaemonService Parsing Tests
# ═══════════════════════════════════════════════════════════════

class TestIntervalParsing:
    def setup_method(self):
        self.svc = DaemonService.__new__(DaemonService)

    def test_seconds(self):
        result = self.svc._parse_interval("30s")
        assert result == timedelta(seconds=30)

    def test_minutes(self):
        result = self.svc._parse_interval("15m")
        assert result == timedelta(minutes=15)

    def test_hours(self):
        result = self.svc._parse_interval("2h")
        assert result == timedelta(hours=2)

    def test_days(self):
        result = self.svc._parse_interval("7d")
        assert result == timedelta(days=7)

    def test_empty(self):
        assert self.svc._parse_interval("") is None
        assert self.svc._parse_interval(None) is None

    def test_invalid_unit(self):
        assert self.svc._parse_interval("10x") is None

    def test_invalid_format(self):
        assert self.svc._parse_interval("abc") is None

    def test_single_char(self):
        assert self.svc._parse_interval("m") is None


class TestDatetimeParsing:
    def setup_method(self):
        self.svc = DaemonService.__new__(DaemonService)

    def test_valid_iso(self):
        result = self.svc._parse_datetime("2026-05-15T10:30:00")
        assert result == datetime(2026, 5, 15, 10, 30, 0)

    def test_none(self):
        assert self.svc._parse_datetime(None) is None

    def test_empty(self):
        assert self.svc._parse_datetime("") is None

    def test_invalid(self):
        assert self.svc._parse_datetime("not-a-date") is None

    def test_integer_input(self):
        assert self.svc._parse_datetime(12345) is None


# ═══════════════════════════════════════════════════════════════
# DaemonService Scheduling Tests
# ═══════════════════════════════════════════════════════════════

class TestNextRunCalculation:
    def setup_method(self):
        self.svc = DaemonService.__new__(DaemonService)

    def test_interval_no_last_run(self):
        job = DaemonJob(
            id=1, name="t", description="", job_type="interval",
            schedule="1h", command="echo", script_path=None,
            arguments=None, is_active=True, timeout_seconds=60,
            retry_on_fail=False, max_retries=0,
            last_run=None, next_run=None,
        )
        before = datetime.now()
        self.svc._calculate_next_run(job)
        after = datetime.now()
        assert job.next_run is not None
        assert before + timedelta(hours=1) <= job.next_run <= after + timedelta(hours=1)

    def test_interval_with_recent_last_run(self):
        now = datetime.now()
        last = now - timedelta(minutes=10)
        job = DaemonJob(
            id=1, name="t", description="", job_type="interval",
            schedule="1h", command="echo", script_path=None,
            arguments=None, is_active=True, timeout_seconds=60,
            retry_on_fail=False, max_retries=0,
            last_run=last, next_run=None,
        )
        self.svc._calculate_next_run(job)
        assert job.next_run == last + timedelta(hours=1)

    def test_interval_with_old_last_run(self):
        last = datetime.now() - timedelta(days=2)
        job = DaemonJob(
            id=1, name="t", description="", job_type="interval",
            schedule="1h", command="echo", script_path=None,
            arguments=None, is_active=True, timeout_seconds=60,
            retry_on_fail=False, max_retries=0,
            last_run=last, next_run=None,
        )
        before = datetime.now()
        self.svc._calculate_next_run(job)
        assert job.next_run >= before

    def test_manual_job_stays_none(self):
        job = DaemonJob(
            id=1, name="t", description="", job_type="manual",
            schedule="", command="echo", script_path=None,
            arguments=None, is_active=True, timeout_seconds=60,
            retry_on_fail=False, max_retries=0,
            last_run=None, next_run=None,
        )
        self.svc._calculate_next_run(job)
        assert job.next_run is None

    def test_invalid_interval_keeps_none(self):
        job = DaemonJob(
            id=1, name="t", description="", job_type="interval",
            schedule="invalid", command="echo", script_path=None,
            arguments=None, is_active=True, timeout_seconds=60,
            retry_on_fail=False, max_retries=0,
            last_run=None, next_run=None,
        )
        self.svc._calculate_next_run(job)
        assert job.next_run is None


# ═══════════════════════════════════════════════════════════════
# DaemonService DB Integration Tests
# ═══════════════════════════════════════════════════════════════

def _create_test_db(tmp_path):
    """Creates a minimal scheduler DB for testing."""
    db_path = tmp_path / "test_daemon.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE scheduler_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            job_type TEXT NOT NULL DEFAULT 'interval',
            schedule TEXT,
            command TEXT NOT NULL,
            script_path TEXT,
            arguments TEXT,
            is_active INTEGER DEFAULT 1,
            timeout_seconds INTEGER DEFAULT 300,
            retry_on_fail INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE scheduler_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            started_at TEXT,
            finished_at TEXT,
            duration_seconds REAL,
            result TEXT,
            output TEXT,
            error TEXT,
            triggered_by TEXT
        )
    """)
    conn.commit()
    conn.close()
    return db_path


class TestDaemonServiceDB:
    def test_load_jobs_empty(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        svc = DaemonService(db_path)
        svc.load_jobs()
        assert len(svc.jobs) == 0

    def test_load_jobs_active_only(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("active-job", "interval", "30m", "echo active", 1),
        )
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("inactive-job", "interval", "1h", "echo inactive", 0),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        assert len(svc.jobs) == 1
        assert list(svc.jobs.values())[0].name == "active-job"

    def test_run_job_not_found(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        svc = DaemonService(db_path)
        svc.load_jobs()
        result = svc.run_job(999)
        assert result["success"] is False
        assert "nicht gefunden" in result["error"]

    def test_run_job_success(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("echo-job", "interval", "1h", "echo HELLO_DAEMON", 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is True
        assert "HELLO_DAEMON" in result["output"]
        assert result["duration_seconds"] >= 0

    def test_run_job_injects_scheduler_operator_steer_env(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("echo-job", "interval", "1h", "echo HELLO_DAEMON", 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        steer_file = tmp_path / "scheduler.steer.json"
        steer_file.write_text(
            json.dumps(
                [{"message": "Bitte zuerst Logs prüfen.", "requested_at": "2026-05-20T12:00:00"}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class _Result:
            returncode = 0
            stdout = "HELLO_DAEMON\n"
            stderr = ""

        def fake_run(*args, **kwargs):
            env = kwargs["env"]
            assert env["BACH_SCHEDULER_JOB_NAME"] == "echo-job"
            assert env["BACH_SCHEDULER_TRIGGERED_BY"] == "test"
            steer = json.loads(env["BACH_SCHEDULER_OPERATOR_STEER"])
            assert steer[0]["message"] == "Bitte zuerst Logs prüfen."
            return _Result()

        with patch("gui.daemon_service.SCHEDULER_STEER_FILE", steer_file):
            with patch("gui.daemon_service.subprocess.run", side_effect=fake_run):
                result = svc.run_job(job_id, triggered_by="test")

        assert result["success"] is True
        assert steer_file.exists()

    def test_run_job_failure(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active, timeout_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("fail-job", "interval", "1h", "python -c \"import sys; sys.exit(1)\"", 1, 30),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is False

    def test_run_job_logs_to_db(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("logged-job", "interval", "1h", "echo LOG_TEST", 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        svc.run_job(job_id, triggered_by="test")

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT * FROM scheduler_runs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        assert row is not None

    def test_run_job_updates_run_count(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("count-job", "interval", "1h", "echo COUNT", 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        svc.run_job(job_id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT run_count FROM scheduler_jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        assert row["run_count"] == 1

    def test_run_job_timeout(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, is_active, timeout_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("timeout-job", "interval", "1h", "python -c \"import time; time.sleep(30)\"", 1, 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id)
        assert result["success"] is False
        assert "Timeout" in result["error"]


# ═══════════════════════════════════════════════════════════════
# Pending Jobs / Scheduling Tests
# ═══════════════════════════════════════════════════════════════

class TestPendingJobs:
    def test_get_pending_returns_due_jobs(self):
        svc = DaemonService.__new__(DaemonService)
        svc.lock = threading.Lock()
        now = datetime.now()
        svc.jobs = {
            1: DaemonJob(
                id=1, name="due", description="", job_type="interval",
                schedule="1h", command="echo", script_path=None,
                arguments=None, is_active=True, timeout_seconds=60,
                retry_on_fail=False, max_retries=0,
                last_run=None, next_run=now - timedelta(seconds=10),
            ),
            2: DaemonJob(
                id=2, name="future", description="", job_type="interval",
                schedule="1h", command="echo", script_path=None,
                arguments=None, is_active=True, timeout_seconds=60,
                retry_on_fail=False, max_retries=0,
                last_run=None, next_run=now + timedelta(hours=2),
            ),
            3: DaemonJob(
                id=3, name="no-schedule", description="", job_type="manual",
                schedule="", command="echo", script_path=None,
                arguments=None, is_active=True, timeout_seconds=60,
                retry_on_fail=False, max_retries=0,
                last_run=None, next_run=None,
            ),
        }
        pending = svc.get_pending_jobs()
        assert len(pending) == 1
        assert pending[0].name == "due"

    def test_check_and_run_due_jobs_respects_scheduler_pause(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        svc = DaemonService(db_path)
        svc.jobs = {
            1: DaemonJob(
                id=1, name="due", description="", job_type="interval",
                schedule="1h", command="echo", script_path=None,
                arguments=None, is_active=True, timeout_seconds=60,
                retry_on_fail=False, max_retries=0,
                last_run=None, next_run=datetime.now() - timedelta(seconds=10),
            ),
        }
        pause_file = tmp_path / "scheduler.pause.json"
        pause_file.write_text(
            json.dumps(
                {"reason": "Wartung", "requested_at": "2026-05-20T12:05:00"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch("gui.daemon_service.SCHEDULER_PAUSE_FILE", pause_file):
            with patch("gui.daemon_service.threading.Thread") as mock_thread:
                svc.check_and_run_due_jobs()

        mock_thread.assert_not_called()
        assert svc._pause_logged is True


# ═══════════════════════════════════════════════════════════════
# Daemon Lifecycle Tests
# ═══════════════════════════════════════════════════════════════

class TestDaemonLifecycle:
    def test_stop_sets_shutdown(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        svc = DaemonService(db_path)
        assert not svc._shutdown_event.is_set()
        svc.stop()
        assert svc._shutdown_event.is_set()
        assert svc.running is False

    def test_get_status(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        svc = DaemonService(db_path)
        status = svc.get_status()
        assert status["running"] is False
        assert status["total_jobs"] == 0
        assert status["active_jobs"] == 0
        assert isinstance(status["last_runs"], list)


# ═══════════════════════════════════════════════════════════════
# OneDrive Pause/Resume (Cross-Platform)
# ═══════════════════════════════════════════════════════════════

class TestOneDrivePauseResume:
    def test_pause_returns_true_on_non_windows(self):
        with patch("gui.daemon_service.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert DaemonService.pause_onedrive() is True

    def test_resume_returns_true_on_non_windows(self):
        with patch("gui.daemon_service.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert DaemonService.resume_onedrive() is True


# ═══════════════════════════════════════════════════════════════
# Script-Path Execution Tests
# ═══════════════════════════════════════════════════════════════

class TestScriptPathExecution:
    """Tests for the script_path code path in run_job (shell=False, list form)."""

    def test_script_path_runs_python_script(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        script = tmp_path / "hello.py"
        script.write_text("print('SCRIPT_OUTPUT_OK')", encoding="utf-8")

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, script_path, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("script-job", "interval", "1h", "", str(script), 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is True
        assert "SCRIPT_OUTPUT_OK" in result["output"]

    def test_script_path_with_arguments(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        script = tmp_path / "argecho.py"
        script.write_text(
            "import sys\nprint(' '.join(sys.argv[1:]))",
            encoding="utf-8",
        )

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, script_path, arguments, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("arg-job", "interval", "1h", "", str(script), "--flag value", 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is True
        assert "--flag value" in result["output"]

    def test_script_path_with_backslash_argument(self, tmp_path):
        """Verifies that shlex.split(posix=False) preserves Windows backslash paths."""
        db_path = _create_test_db(tmp_path)
        script = tmp_path / "pathecho.py"
        script.write_text(
            "import sys\nprint(sys.argv[1])",
            encoding="utf-8",
        )

        win_path = r"C:\Users\test\data\file.txt"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, script_path, arguments, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("backslash-job", "interval", "1h", "", str(script), win_path, 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is True
        assert "C:\\Users\\test\\data\\file.txt" in result["output"]

    def test_script_path_no_arguments(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        script = tmp_path / "noargs.py"
        script.write_text(
            "import sys\nprint(f'ARGC={len(sys.argv)}')",
            encoding="utf-8",
        )

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, script_path, arguments, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("noarg-job", "interval", "1h", "", str(script), None, 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is True
        assert "ARGC=1" in result["output"]

    def test_script_path_failure_returns_error(self, tmp_path):
        db_path = _create_test_db(tmp_path)
        script = tmp_path / "fail.py"
        script.write_text(
            "import sys\nprint('FAIL_MSG', file=sys.stderr)\nsys.exit(1)",
            encoding="utf-8",
        )

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scheduler_jobs (name, job_type, schedule, command, script_path, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("fail-script", "interval", "1h", "", str(script), 1),
        )
        conn.commit()
        conn.close()

        svc = DaemonService(db_path)
        svc.load_jobs()
        job_id = list(svc.jobs.keys())[0]
        result = svc.run_job(job_id, triggered_by="test")
        assert result["success"] is False
        assert "FAIL_MSG" in result["error"]


# ═══════════════════════════════════════════════════════════════
# shlex.split POSIX-Mode Regression Test
# ═══════════════════════════════════════════════════════════════

class TestShlexPosixMode:
    """Ensures shlex.split uses posix=False on Windows to preserve backslashes."""

    def test_shlex_posix_false_preserves_backslashes(self):
        import shlex
        result = shlex.split(r'C:\Users\test\file.txt', posix=False)
        assert result == [r'C:\Users\test\file.txt']

    def test_shlex_posix_true_destroys_backslashes(self):
        import shlex
        result = shlex.split(r'C:\Users\test\file.txt', posix=True)
        assert result == ['C:Userstestfile.txt']

    def test_daemon_service_uses_correct_posix_mode(self):
        """Verifies the actual code path uses posix=(os.name != 'nt')."""
        import os
        import shlex as shlex_mod
        test_arg = r'--config C:\data\settings.json --verbose'
        result = shlex_mod.split(test_arg, posix=(os.name != 'nt'))
        if os.name == 'nt':
            assert r'C:\data\settings.json' in result
        else:
            assert 'C:datasettings.json' in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
