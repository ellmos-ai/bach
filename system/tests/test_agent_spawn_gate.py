"""Harmless gate checks; no agent CLI or local model is started."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


HUB_GATE = Path(__file__).resolve().parents[1] / "hub" / "agent_spawn_gate.py"


@pytest.mark.skipif(os.name == "nt", reason="Unix execvp keeps the original PID")
def test_unix_gate_never_execs_runner_without_marker(tmp_path):
    marker = tmp_path / "runner-started"
    gate = tmp_path / "gate"
    proc = subprocess.Popen(
        [sys.executable, str(HUB_GATE), "once", str(gate), sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        cwd=tmp_path,
    )
    proc.terminate()
    assert proc.wait(timeout=5) != 0
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Unix execvp keeps the original PID")
def test_unix_gate_execs_runner_only_after_token(tmp_path):
    marker = tmp_path / "runner-started"
    gate = tmp_path / "gate"
    proc = subprocess.Popen(
        [sys.executable, str(HUB_GATE), "once", str(gate), sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        cwd=tmp_path,
    )
    assert not marker.exists()
    gate.write_text("once", encoding="ascii")
    assert proc.wait(timeout=5) == 0
    assert marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe gate")
def test_windows_headless_batch_gate_requires_token(tmp_path):
    marker = tmp_path / "runner-started"
    gate = tmp_path / "gate"
    batch = tmp_path / "gate.bat"
    batch.write_text(
        '@echo off\n'
        'set "BACH_GATE_ATTEMPTS=0"\n'
        ':BACH_SPAWN_WAIT\n'
        f'if exist "{gate}" goto BACH_SPAWN_CHECK\n'
        'set /a BACH_GATE_ATTEMPTS+=1\n'
        'if %BACH_GATE_ATTEMPTS% GEQ 10 exit /b 86\n'
        'timeout /t 1 /nobreak\n'
        'goto BACH_SPAWN_WAIT\n'
        ':BACH_SPAWN_CHECK\n'
        'set "BACH_SPAWN_GATE="\n'
        f'set /p BACH_SPAWN_GATE=<"{gate}"\n'
        'if not "%BACH_SPAWN_GATE%"=="once" exit /b 86\n'
        f'echo ready > "{marker}"\n',
        encoding="utf-8",
    )
    opts = dict(cwd=tmp_path, creationflags=subprocess.CREATE_NO_WINDOW)
    proc = subprocess.Popen(["cmd", "/c", str(batch)], **opts)
    proc.terminate()
    assert proc.wait(timeout=5) != 0
    assert not marker.exists()

    proc = subprocess.Popen(["cmd", "/c", str(batch)], **opts)
    time.sleep(0.3)
    assert proc.poll() is None
    assert not marker.exists()
    gate.write_text("once", encoding="ascii")
    assert proc.wait(timeout=5) == 0
    assert marker.exists()
