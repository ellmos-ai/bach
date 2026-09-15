"""Harmless gate checks; no agent CLI or local model is started."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


HUB_GATE = Path(__file__).resolve().parents[1] / "hub" / "agent_spawn_gate.py"


@pytest.mark.skipif(os.name == "nt", reason="Unix execvp keeps the original PID")
def test_unix_gate_never_execs_runner_on_eof(tmp_path):
    marker = tmp_path / "runner-started"
    proc = subprocess.Popen(
        [sys.executable, str(HUB_GATE), "once", sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        stdin=subprocess.PIPE,
        cwd=tmp_path,
    )
    proc.stdin.close()
    assert proc.wait(timeout=5) == 86
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Unix execvp keeps the original PID")
def test_unix_gate_execs_runner_only_after_token(tmp_path):
    marker = tmp_path / "runner-started"
    proc = subprocess.Popen(
        [sys.executable, str(HUB_GATE), "once", sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
        stdin=subprocess.PIPE,
        cwd=tmp_path,
    )
    assert not marker.exists()
    proc.stdin.write(b"once\n")
    proc.stdin.close()
    assert proc.wait(timeout=5) == 0
    assert marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe gate")
def test_windows_headless_batch_gate_requires_token(tmp_path):
    marker = tmp_path / "runner-started"
    batch = tmp_path / "gate.bat"
    batch.write_text(
        '@echo off\nset "BACH_SPAWN_GATE="\nset /p BACH_SPAWN_GATE=\n'
        'if not "%BACH_SPAWN_GATE%"=="once" exit /b 86\n'
        f'echo ready > "{marker}"\n',
        encoding="utf-8",
    )
    opts = dict(stdin=subprocess.PIPE, cwd=tmp_path, creationflags=subprocess.CREATE_NO_WINDOW)
    proc = subprocess.Popen(["cmd", "/c", str(batch)], **opts)
    proc.stdin.close()
    assert proc.wait(timeout=5) == 86
    assert not marker.exists()

    proc = subprocess.Popen(["cmd", "/c", str(batch)], **opts)
    proc.stdin.write(b"once\n")
    proc.stdin.close()
    assert proc.wait(timeout=5) == 0
    assert marker.exists()
