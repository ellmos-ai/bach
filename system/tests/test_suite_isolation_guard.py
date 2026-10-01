"""Regression tests for the suite-wide isolation guard."""

import json
import os
import subprocess
import sys
from pathlib import Path

from system.tests import conftest


def test_session_bootstraps_slots_config_on_private_disk():
    slots_path = Path(os.environ["BACH_SLOTS_CONFIG_PATH"]).resolve()
    assert slots_path == (conftest._TEST_DB_DIR / "slots_config.json").resolve()
    assert conftest._source_runtime_path(slots_path) is None
    assert slots_path.is_file()
    config = json.loads(slots_path.read_text(encoding="utf-8"))
    assert "buddha_chat" in config["slots"]


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


def test_destructive_process_reason_allows_script_arguments_with_options():
    assert conftest._destructive_process_reason(["python", "system/bach.py", "--status"]) is None
    assert conftest._destructive_process_reason(["python", "system/bach.py", "--memory", "status"]) is None
    assert conftest._destructive_process_reason(["python", "system/bach.py", "scheduler", "status", "--json"]) is None
    assert conftest._destructive_process_reason("python system/bach.py --status") is None
    assert conftest._destructive_process_reason("python system/bach.py --memory status") is None


def test_python_child_distinguishes_interpreter_and_program_options():
    commands = [
        [sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1"],
        [sys.executable, "system/bach.py", "--status"],
        [sys.executable, "-c", "pass", "-I"],
        "python -m http.server 0 --bind 127.0.0.1",
        [sys.executable, "-I", "-m", "http.server", "0"],
        [sys.executable, "-E", "-c", "pass"],
        [sys.executable, "-S", "-c", "pass"],
        [sys.executable, "-uI", "-c", "pass"],
        "python -S -c pass",
        ["cmd.exe", "/c", "taskkill /PID 999999 /F"],
        [sys.executable, "-X", "dev", "-I", "-c", "pass"],
        [sys.executable, "-W", "ignore", "-S", "-c", "pass"],
        [sys.executable, "--check-hash-based-pycs", "default", "-E", "-c", "pass"],
        "python -X dev -I -c pass",
        "python -W ignore -S -c pass",
        [sys.executable, "-Ximporttime", "-c", "pass"],
        [sys.executable, "-W", "ignore", "-c", "pass"],
        [sys.executable, "-X", "importtime", "-m", "http.server", "0", "--bind", "127.0.0.1"],
        "python -X importtime -m http.server 0 --bind 127.0.0.1",
        [sys.executable, "--check-hash-based-pycs", "default", "-m", "http.server", "0"],
        'python -c "import time; time.sleep(30)"',
    ]
    code = (
        "import json, sitecustomize; "
        f"commands = {commands!r}; "
        "print(json.dumps([sitecustomize._dangerous_command(c) for c in commands]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = [False] * 4 + [True] * 11 + [False] * 6
    assert json.loads(result.stdout) == expected
    assert [conftest._destructive_process_reason(c) is not None for c in commands] == expected
