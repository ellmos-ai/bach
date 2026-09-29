# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests fuer core.sandbox (Sandbox Stufe 2, Task 1071) und die
Stufe-2-Integration in hub.sandbox (Memory-Limit, limit-Operation).
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

import subprocess

import core.sandbox as core_sandbox
from core.sandbox import (  # noqa: E402
    DEFAULT_DOCKER_IMAGE,
    IS_POSIX,
    SandboxResult,
    SandboxLimits,
    docker_available,
    docker_run_isolated,
    load_limits_from_db,
    run_isolated,
)
from hub.sandbox import SandboxHandler  # noqa: E402

PY = sys.executable
POSIX_ONLY = pytest.mark.skipif(not IS_POSIX, reason="POSIX-only (rlimit/killpg)")


# ── run_isolated: Baseline ───────────────────────────────────────────

class TestRunIsolated:
    def test_simple_command(self):
        r = run_isolated([PY, "-c", "print('isolated_ok')"],
                         limits=SandboxLimits(timeout_sec=10))
        assert r.returncode == 0
        assert "isolated_ok" in r.stdout
        assert r.timed_out is False
        assert r.memory_exceeded is False
        assert r.duration_sec > 0

    def test_failure_returncode(self):
        r = run_isolated([PY, "-c", "import sys; sys.exit(3)"],
                         limits=SandboxLimits(timeout_sec=10))
        assert r.returncode == 3

    def test_nonzero_but_not_timed_out(self):
        r = run_isolated([PY, "-c", "raise SystemExit(1)"],
                         limits=SandboxLimits(timeout_sec=10))
        assert r.returncode == 1
        assert r.timed_out is False

    def test_stdin_input(self):
        r = run_isolated([PY, "-c", "print(input().upper())"],
                         limits=SandboxLimits(timeout_sec=10),
                         input_text="abc\n")
        assert "ABC" in r.stdout

    def test_result_duck_compatible_with_completed_process(self):
        r = run_isolated([PY, "-c", "print(1)"],
                         limits=SandboxLimits(timeout_sec=10))
        # hub.sandbox._format_result nutzt returncode/stdout/stderr
        assert hasattr(r, "returncode") and hasattr(r, "stdout") and hasattr(r, "stderr")


# ── Timeout / Prozessgruppen-Kill ────────────────────────────────────

@POSIX_ONLY
class TestTimeout:
    def test_timeout_kills_child(self):
        start = time.monotonic()
        r = run_isolated([PY, "-c", "import time; time.sleep(60)"],
                         limits=SandboxLimits(timeout_sec=1))
        assert r.timed_out is True
        assert time.monotonic() - start < 15

    def test_timeout_kills_grandchildren(self, tmp_path):
        marker = tmp_path / "grandchild_alive"
        code = (
            "import subprocess, time, sys\n"
            "subprocess.Popen([sys.executable, '-c', "
            f"\"import time,pathlib; time.sleep(4); pathlib.Path(r'{marker}').write_text('x')\"])\n"
            "time.sleep(60)\n"
        )
        r = run_isolated([PY, "-c", code], limits=SandboxLimits(timeout_sec=1))
        assert r.timed_out is True
        time.sleep(4.5)  # Enkel wuerde jetzt schreiben, wenn er ueberlebt haette
        assert not marker.exists()

    def test_shell_timeout(self):
        start = time.monotonic()
        r = run_isolated("sleep 60", limits=SandboxLimits(timeout_sec=1), shell=True)
        assert r.timed_out is True
        assert time.monotonic() - start < 15


# ── Memory-Limit ─────────────────────────────────────────────────────

@POSIX_ONLY
class TestMemoryLimit:
    def test_watchdog_kills_memory_hog(self):
        # 30 x 30MB = 900MB Allokation bei 300MB Limit
        code = (
            "import time\n"
            "x=[]\n"
            "for i in range(30):\n"
            "    x.append(bytearray(30*1024*1024))\n"
            "    time.sleep(0.05)\n"
            "print('SURVIVED')\n"
        )
        r = run_isolated([PY, "-c", code],
                         limits=SandboxLimits(timeout_sec=60, memory_mb=300))
        assert r.memory_exceeded is True
        assert "SURVIVED" not in r.stdout

    def test_process_within_limit_survives(self):
        r = run_isolated([PY, "-c", "x=bytearray(5*1024*1024); print('within_limit')"],
                         limits=SandboxLimits(timeout_sec=15, memory_mb=512))
        assert r.returncode == 0
        assert "within_limit" in r.stdout
        assert r.memory_exceeded is False

    def test_watchdog_flag_active(self):
        r = run_isolated([PY, "-c", "pass"],
                         limits=SandboxLimits(timeout_sec=10, memory_mb=512))
        assert r.watchdog_active is True
        assert r.rlimits_applied is True

    def test_no_limit_no_watchdog(self):
        r = run_isolated([PY, "-c", "pass"],
                         limits=SandboxLimits(timeout_sec=10, memory_mb=None))
        assert r.rlimits_applied is True   # rlimit gesetzt (nur RLIMIT_CORE)
        # Watchdog ohne Memory-Limit nicht aktiv
        assert r.watchdog_active is False


# ── SandboxLimits / load_limits_from_db ──────────────────────────────

class TestLimitsConfig:
    def test_defaults(self):
        lim = SandboxLimits()
        assert lim.timeout_sec == 30
        assert lim.memory_mb == 512

    def test_load_missing_db(self, tmp_path):
        lim = load_limits_from_db(tmp_path / "nix.db")
        assert lim.timeout_sec == 30
        assert lim.memory_mb == 512

    def test_load_from_db(self, tmp_path):
        db = tmp_path / "bach.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT, category TEXT)")
        conn.execute("INSERT INTO system_config VALUES ('sandbox.timeout_sec', '99', 'sandbox')")
        conn.execute("INSERT INTO system_config VALUES ('sandbox.memory_limit_mb', '256', 'sandbox')")
        conn.commit()
        conn.close()
        lim = load_limits_from_db(str(db))
        assert lim.timeout_sec == 99
        assert lim.memory_mb == 256

    def test_load_ignores_invalid_values(self, tmp_path):
        db = tmp_path / "bach.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT, category TEXT)")
        conn.execute("INSERT INTO system_config VALUES ('sandbox.memory_limit_mb', 'abc', 'sandbox')")
        conn.commit()
        conn.close()
        lim = load_limits_from_db(str(db))
        assert lim.memory_mb == 512


# ── Handler-Integration (Stufe 2) ────────────────────────────────────

@pytest.fixture
def handler(tmp_path):
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, category TEXT)")
    conn.commit()
    conn.close()
    h = SandboxHandler(tmp_path)
    h._canonical_db = str(db_path)
    return h


class TestHandlerStufe2:
    def test_default_memory_limit(self, handler):
        assert handler._memory_limit_mb == SandboxHandler.DEFAULT_MEMORY_LIMIT_MB

    def test_limit_show(self, handler):
        ok, msg = handler.handle("limit", [])
        assert ok is True
        assert "512" in msg

    def test_limit_set_persists(self, handler):
        ok, msg = handler.handle("limit", ["256"])
        assert ok is True
        assert handler._memory_limit_mb == 256
        # Persistierung: frisch laden
        assert handler._load_memory_limit() == 256

    def test_limit_invalid(self, handler):
        ok, msg = handler.handle("limit", ["abc"])
        assert ok is False

    def test_limit_too_small(self, handler):
        ok, msg = handler.handle("limit", ["8"])
        assert ok is False
        assert handler._memory_limit_mb != 8

    def test_operations_include_limit(self, handler):
        assert "limit" in handler.get_operations()

    def test_policy_shows_memory_limit(self, handler):
        ok, msg = handler._policy()
        assert ok is True
        assert "Memory-Limit" in msg
        assert "Resource-Bounds" in msg

    @POSIX_ONLY
    def test_run_memory_hog_blocked(self, handler):
        script = Path(tempfile.mkdtemp()) / "hog.py"
        script.write_text(
            "import time\nx=[]\n"
            "for i in range(40):\n"
            "    x.append(bytearray(30*1024*1024))\n    time.sleep(0.05)\n"
            "print('SURVIVED')\n", encoding="utf-8")
        handler.handle("limit", ["256"])
        ok, msg = handler._run_file(str(script), [])
        assert ok is False
        assert "MEMORY-LIMIT" in msg

    @POSIX_ONLY
    def test_shell_memory_limit_respected(self, handler):
        handler.handle("limit", ["256"])
        code = "import time" + chr(10) + "x=[bytearray(30*1024*1024) for _ in range(40)]; time.sleep(3)"
        ok, msg = handler._shell(f'python3 -c "{code}"')
        assert ok is False
        assert "MEMORY-LIMIT" in msg


DOCKER = pytest.mark.skipif(not docker_available(), reason="Docker/Image nicht verfuegbar")


class _FakeDocker:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, limits=None, cwd=None, env=None, shell=False,
                 input_text=None, image=DEFAULT_DOCKER_IMAGE):
        self.calls.append({
            "cmd": cmd, "limits": limits, "cwd": cwd, "env": env,
            "shell": shell, "input_text": input_text, "image": image,
        })
        return SandboxResult(returncode=0, stdout="FAKE-DOCKER", stderr="",
                             args=cmd, backend="docker")


def test_sandbox_result_default_backend_local():
    r = SandboxResult(returncode=0, stdout="", stderr="")
    assert r.backend == "local"


def test_run_isolated_docker_fallback_local(monkeypatch):
    monkeypatch.setattr(core_sandbox, "docker_available", lambda *a, **k: False)
    r = run_isolated(["echo", "hi"], backend="docker")
    assert r.backend == "local"
    assert "hi" in r.stdout


def test_run_isolated_auto_fallback_local(monkeypatch):
    monkeypatch.setattr(core_sandbox, "docker_available", lambda *a, **k: False)
    r = run_isolated(["echo", "hi"], backend="auto")
    assert r.backend == "local"
    assert "hi" in r.stdout


def test_run_isolated_docker_dispatch(monkeypatch):
    fake = _FakeDocker()
    monkeypatch.setattr(core_sandbox, "docker_available", lambda *a, **k: True)
    monkeypatch.setattr(core_sandbox, "docker_run_isolated", fake)
    lim = SandboxLimits(timeout_sec=5)
    r = run_isolated(["echo", "hi"], limits=lim, backend="docker")
    assert r.stdout == "FAKE-DOCKER"
    assert r.backend == "docker"
    assert len(fake.calls) == 1
    assert fake.calls[0]["limits"] is lim


def test_run_isolated_auto_dispatch(monkeypatch):
    fake = _FakeDocker()
    monkeypatch.setattr(core_sandbox, "docker_available", lambda *a, **k: True)
    monkeypatch.setattr(core_sandbox, "docker_run_isolated", fake)
    r = run_isolated(["echo", "hi"], backend="auto")
    assert r.backend == "docker"
    assert r.stdout == "FAKE-DOCKER"


def test_run_isolated_local_ignores_docker(monkeypatch):
    fake = _FakeDocker()
    monkeypatch.setattr(core_sandbox, "docker_available", lambda *a, **k: True)
    monkeypatch.setattr(core_sandbox, "docker_run_isolated", fake)
    r = run_isolated(["echo", "hi"], backend="local")
    assert fake.calls == []
    assert "hi" in r.stdout
    assert r.backend == "local"


def test_run_isolated_default_backend_local(monkeypatch):
    fake = _FakeDocker()
    monkeypatch.setattr(core_sandbox, "docker_available", lambda *a, **k: True)
    monkeypatch.setattr(core_sandbox, "docker_run_isolated", fake)
    r = run_isolated(["echo", "hi"])
    assert r.backend == "local"
    assert fake.calls == []


def test_docker_available_false_without_cli(monkeypatch):
    monkeypatch.setattr(core_sandbox.shutil, "which", lambda name: None)
    assert docker_available(force=True) is False


def test_docker_run_isolated_error_no_silent_fallback(monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("boom")
    monkeypatch.setattr(core_sandbox.subprocess, "Popen", _boom)
    r = docker_run_isolated(["echo", "hi"])
    assert r.returncode == -1
    assert "Docker-Fehler" in r.stderr
    assert r.backend == "docker"


def test_docker_run_isolated_timeout_cleanup_sequence(monkeypatch):
    """Bei Timeout muss stop/kill/rm -f aufgerufen werden (nicht nur Popen.kill)."""

    class _StubbornPopen:
        def __init__(self, *args, **kwargs):
            self.returncode = None
            self._done = threading.Event()
            self._killed = False

        def poll(self):
            return 137 if self._killed else None

        def communicate(self, input=None):
            assert self._done.wait(timeout=5)
            self.returncode = 137
            return ("", "")

        def wait(self, timeout=None):
            self._done.wait(timeout=timeout)

        def kill_container(self):
            self._killed = True
            self._done.set()

    popen = _StubbornPopen()
    calls = []

    def _fake_popen(*args, **kwargs):
        return popen

    def _fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["docker", "kill"]:
            popen.kill_container()
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(core_sandbox.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(core_sandbox.subprocess, "run", _fake_run)

    r = docker_run_isolated(["sleep", "60"], limits=SandboxLimits(timeout_sec=0.05))
    assert r.timed_out is True
    assert r.returncode == -1
    assert r.backend == "docker"

    # Cleanup-Sequenz muss enthalten sein (stop -> kill -> rm -f)
    cmds = [c[:2] for c in calls]
    assert ["docker", "stop"] in cmds
    assert ["docker", "kill"] in cmds
    assert ["docker", "rm"] in cmds or ["docker", "rm", "-f"] in [c[:3] for c in calls]


def test_docker_run_isolated_oom_detection(monkeypatch):
    """OOMKilled=true aus docker inspect muss memory_exceeded setzen."""

    class _OOMExitPopen:
        def __init__(self, *args, **kwargs):
            self.returncode = 1

        def poll(self):
            return self.returncode

        def communicate(self, input=None):
            return ("", "")

        def wait(self, timeout=None):
            pass

    def _fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(core_sandbox.subprocess, "Popen", _OOMExitPopen)
    monkeypatch.setattr(core_sandbox.subprocess, "run", _fake_run)

    r = docker_run_isolated(["python3", "-c", "x=bytearray(300*1024*1024)"])
    assert r.returncode == 1
    assert r.memory_exceeded is True
    assert r.backend == "docker"


@DOCKER
def test_docker_run_isolated_echo():
    r = docker_run_isolated(["echo", "docker-ok"])
    assert r.returncode == 0
    assert "docker-ok" in r.stdout
    assert r.backend == "docker"


@DOCKER
def test_docker_run_isolated_timeout_rollback():
    unique_name = "bach-sbx-test-" + uuid.uuid4().hex[:12]
    r = docker_run_isolated(["sleep", "60"], limits=SandboxLimits(timeout_sec=2),
                            name=unique_name)
    assert r.timed_out is True
    ps = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"],
                        capture_output=True, text=True, timeout=15)
    assert unique_name not in ps.stdout


@DOCKER
def test_docker_run_isolated_memory_limit():
    r = docker_run_isolated(["python3", "-c", "x = bytearray(300*1024*1024)"],
                            limits=SandboxLimits(timeout_sec=30, memory_mb=32))
    assert r.memory_exceeded is True


@DOCKER
def test_docker_run_isolated_read_only_rootfs():
    r = docker_run_isolated(["sh", "-c", "echo x > /probe.txt"])
    assert r.returncode != 0


@DOCKER
def test_docker_run_isolated_network_blocked():
    code = chr(10).join([
        "import socket",
        "try:",
        "    socket.create_connection(('127.0.0.1', 80), timeout=3)",
        "    print('OPEN')",
        "except Exception:",
        "    print('BLOCKED')",
    ])
    r = docker_run_isolated(["python3", "-c", code])
    assert "BLOCKED" in r.stdout
