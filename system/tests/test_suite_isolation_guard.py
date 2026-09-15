"""Regression tests for the suite-wide isolation guard."""

import subprocess
import sys
from pathlib import Path

from system.tests import conftest


def test_source_runtime_path_detects_runtime_data():
    source_data = conftest._SOURCE_SYSTEM_ROOT / "data" / "bach.db"
    assert conftest._source_runtime_path(source_data) == source_data


def test_source_runtime_path_allows_temporary_data(tmp_path: Path):
    assert conftest._source_runtime_path(tmp_path / "bach.db") is None


def test_destructive_process_reason_detects_onedrive_shutdown():
    command = [r"C:\Program Files\Microsoft OneDrive\OneDrive.exe", "/shutdown"]
    assert conftest._destructive_process_reason(command) == "OneDrive shutdown"


def test_destructive_process_reason_allows_normal_subprocess():
    assert conftest._destructive_process_reason(["python", "-V"]) is None


def test_destructive_process_reason_detects_shell_wrapper():
    command = ["cmd.exe", "/c", "taskkill /PID 999999 /F"]
    assert conftest._destructive_process_reason(command) == (
        "shell-mediated process termination"
    )


def test_destructive_process_reason_rejects_python_without_site_guard():
    assert conftest._destructive_process_reason([sys.executable, "-I", "-c", "pass"]) == (
        "Python child without inherited safety guard"
    )


def test_destructive_process_reason_rejects_shell_python_without_site_guard():
    command = 'python -S -c "import os; os.kill(123, 9)"'
    assert conftest._destructive_process_reason(command) == (
        "Python child without inherited safety guard"
    )


def test_daemon_kill_all_is_blocked_in_test_mode():
    from gui.daemon_service import DaemonService

    result = DaemonService.kill_all_daemons()

    assert result["killed"] == []
    assert result["errors"] == [
        "Host-Prozesssteuerung ist im BACH-Testmodus deaktiviert"
    ]


def test_python_child_blocks_nested_process_termination():
    code = (
        "import subprocess; "
        "subprocess.run(['taskkill', '/PID', '999999', '/F'], check=True)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "host process control blocked in test child" in result.stderr


def test_python_child_forces_guard_into_grandchild_environment():
    code = (
        "import os, subprocess, sys; "
        "env=dict(os.environ, BACH_TEST_MODE='0', PYTHONPATH=''); "
        "child=\"import subprocess; subprocess.run(['taskkill','/PID','999999','/F'])\"; "
        "raise SystemExit(subprocess.run([sys.executable, '-c', child], env=env).returncode)"
    )

    result = subprocess.run(
        args=[sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "host process control blocked in test child" in result.stderr
