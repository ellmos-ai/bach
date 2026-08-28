# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Verhaltensprüfungen für die gemeinsame BACH-Startspine."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

STARTSPINE_PATH = Path(__file__).parents[2] / "start" / "startspine.py"
SPEC = importlib.util.spec_from_file_location("bach_startspine", STARTSPINE_PATH)
startspine = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(startspine)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_resolve_port_preserves_foreign_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        desired = int(listener.getsockname()[1])
        actual, owner = startspine._resolve_port("127.0.0.1", desired)
        assert actual != desired
        assert owner and owner["pid"] == os.getpid()
        assert listener.fileno() >= 0


def test_supervisor_records_child_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    paths = startspine._paths()
    spec_path = tmp_path / "probe-spec.json"
    spec_path.write_text(json.dumps({
        "launch_id": "probe-7",
        "command": [sys.executable, "-c", "raise SystemExit(7)"],
        "cwd": str(tmp_path),
        "env_overrides": {"PYTHONIOENCODING": "utf-8"},
        "log": str(tmp_path / "probe.log"),
    }), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(STARTSPINE_PATH),
            "_run-child",
            "--service",
            "probe",
            "--spec",
            str(spec_path),
        ],
        env={**os.environ, "BACH_RUNTIME_DIR": str(paths["runtime"])},
        check=False,
    )
    receipt = json.loads((paths["receipts"] / "probe.json").read_text(encoding="utf-8"))
    assert result.returncode == 7
    assert receipt["exit_code"] == 7
    assert receipt["pid"] > 0
    assert receipt["supervisor_pid"] > 0


def test_exit_receipt_wait_does_not_read_while_supervisor_is_writing(monkeypatch):
    record = {"exit_code": None}
    supervisor_states = iter((True, True, False))
    events = []

    def fake_supervisor_alive(_record):
        events.append("supervisor-check")
        return next(supervisor_states)

    def fake_sync(_name, target_record):
        events.append("receipt-read")
        target_record["exit_code"] = 15
        return target_record

    monkeypatch.setattr(startspine, "_supervisor_identity_alive", fake_supervisor_alive)
    monkeypatch.setattr(startspine, "_sync_receipt", fake_sync)
    monkeypatch.setattr(startspine.time, "sleep", lambda _seconds: None)

    assert startspine._wait_for_exit_receipt("gui", record)
    assert events == ["supervisor-check", "supervisor-check", "supervisor-check", "receipt-read"]


def test_cli_is_independent_of_current_directory(tmp_path):
    runtime = tmp_path / "runtime"
    result = subprocess.run(
        [sys.executable, str(STARTSPINE_PATH), "status", "--json"],
        cwd=tmp_path,
        env={**os.environ, "BACH_RUNTIME_DIR": str(runtime)},
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["root"] == str(STARTSPINE_PATH.parents[1])
    assert not (runtime / "discovery.json").exists()


def test_windows_autostart_uses_absolute_task_command(monkeypatch):
    if os.name != "nt":
        return
    captured = []

    def fake_run(command, **kwargs):
        captured.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(startspine.subprocess, "run", fake_run)
    assert startspine.command_autostart_install(argparse.Namespace()) == 0
    command = captured[0]
    action = command[command.index("/tr") + 1]
    assert str(Path(sys.executable)) in action
    assert str(STARTSPINE_PATH) in action
    assert " start --tray" in action
    assert captured[1][:3] == ["schtasks", "/query", "/tn"]


def test_start_readback_and_stop_only_owned_process(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("BACH_STARTSPINE_TEST_SECRET", "do-not-persist")
    port = _free_port()
    state = startspine._base_state()
    ready = startspine._start_service(
        state,
        "gui",
        command=[sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
        env=startspine._child_environment(),
        required=True,
        host="127.0.0.1",
        desired_port=port,
        actual_port=port,
        readiness_timeout=15,
    )
    record = state["services"]["gui"]
    try:
        assert ready is True
        assert startspine._service_health("gui", record)
        assert startspine._service_ready_owned("gui", record)
        assert startspine._listener_owner(port)["pid"] == record["pid"]
        spec_files = list(startspine._paths()["specs"].glob("gui-*.json"))
        assert len(spec_files) == 1
        assert "do-not-persist" not in spec_files[0].read_text(encoding="utf-8")
    finally:
        assert startspine._stop_record("gui", record)
        receipt = json.loads(startspine._receipt_path("gui").read_text(encoding="utf-8"))
        assert record["exit_code"] is not None
        assert receipt["exit_code"] == record["exit_code"]
        assert not startspine._child_identity_alive(record)
        assert not startspine._supervisor_identity_alive(record)
        assert not list(startspine._receipt_path("gui").parent.glob(".gui.json.*.tmp"))


def test_stop_refuses_reused_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    state = startspine._base_state()
    state["services"]["gui"] = {
        "root": str(startspine.ROOT_DIR),
        "pid": os.getpid(),
        "create_time": 1.0,
        "supervisor_pid": os.getpid(),
        "supervisor_create_time": 1.0,
        "status": "online",
    }
    startspine._save_state(state)
    args = argparse.Namespace(services="gui")
    assert startspine.command_stop(args) == 1
    assert os.getpid() > 0


def test_stop_refuses_live_state_from_other_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    identity = startspine._process_identity(os.getpid())
    state = startspine._base_state()
    state["root"] = str(tmp_path / "other-checkout")
    state["services"]["gui"] = {
        "pid": os.getpid(),
        "create_time": identity["create_time"],
        "status": "online",
    }
    startspine._save_state(state)
    assert startspine.main(["stop", "--services", "gui"]) == 2
    assert os.getpid() > 0


def test_stop_refuses_mixed_state_record_from_other_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    identity = startspine._process_identity(os.getpid())
    state = startspine._base_state()
    state["services"]["gui"] = {
        "root": str(tmp_path / "other-checkout"),
        "pid": os.getpid(),
        "create_time": identity["create_time"],
        "status": "online",
    }
    startspine._save_state(state)
    assert startspine.main(["stop", "--services", "gui"]) == 2
    assert os.getpid() > 0


def test_readiness_fails_closed_without_port_owner(monkeypatch):
    monkeypatch.setattr(startspine, "_record_is_owned", lambda record: True)
    monkeypatch.setattr(startspine, "_service_health", lambda name, record: True)
    monkeypatch.setattr(startspine, "_listener_owner", lambda port: None)
    assert not startspine._service_ready_owned(
        "gui",
        {"pid": 123, "actual_port": 8123},
    )


def test_chat_health_requires_identified_bach_control(monkeypatch):
    record = {"host": "127.0.0.1", "actual_port": 8081}
    monkeypatch.setattr(
        startspine,
        "_json_url",
        lambda url: {
            "service": "bach-chat-control",
            "telegram_verified": False,
        },
    )
    assert startspine._service_health("chat", record)
    monkeypatch.setattr(
        startspine,
        "_json_url",
        lambda url: {
            "service": "foreign-control",
            "telegram_verified": True,
        },
    )
    assert not startspine._service_health("chat", record)


def test_ollama_readiness_requires_models_schema():
    assert startspine._ollama_payload_ready({"models": []})
    assert not startspine._ollama_payload_ready({"status": "ok"})
    assert not startspine._ollama_payload_ready(None)


def test_telegram_direct_mode_resolves_system_root():
    text = (
        Path(__file__).parents[1]
        / "hub"
        / "_services"
        / "chat"
        / "telegram_chat.py"
    ).read_text(encoding="utf-8")
    assert "Path(__file__).resolve().parents[3]" in text
    assert 'command=[sys.executable, "-m", "hub._services.chat.telegram_chat"]' in STARTSPINE_PATH.read_text(encoding="utf-8")


def test_dashboard_optional_stats_are_null_safe():
    script = (
        Path(__file__).parents[1]
        / "gui"
        / "static"
        / "js"
        / "app.js"
    ).read_text(encoding="utf-8")
    assert "const setStat = (id, value)" in script
    assert "document.getElementById('stat-scanned').textContent" not in script
    assert "document.getElementById('stat-daemon').textContent" not in script


def test_tray_start_is_required_and_uses_local_ollama(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    captured = {}

    def fake_start_service(state, name, **kwargs):
        captured[name] = kwargs
        return True

    monkeypatch.setattr(startspine, "_start_service", fake_start_service)
    monkeypatch.setattr(startspine, "_load_mutable_state", startspine._base_state)
    monkeypatch.setattr(startspine, "_save_state", lambda state: None)
    monkeypatch.setattr(
        startspine,
        "_discovery",
        lambda state, gui_port, control_port: {"services": {}, "ollama": {}},
    )
    monkeypatch.setattr(startspine, "_print_status", lambda payload: None)
    args = argparse.Namespace(
        host="remote-control",
        gui_port=None,
        control_port=None,
        gui=False,
        chat=False,
        tray=True,
        readiness_timeout=1.0,
        open_browser=False,
    )

    assert startspine.command_start(args) == 0
    tray = captured["tray"]
    assert tray["required"] is True
    command = tray["command"]
    assert command[command.index("--ollama-host") + 1] == "127.0.0.1"
    assert command[command.index("--host") + 1] == "remote-control"


def test_remote_status_keeps_ollama_local(monkeypatch, capsys):
    checked_urls = []
    checked_ollama = []

    def fake_url_ready(url, timeout=1.0):
        checked_urls.append(url)
        return False

    monkeypatch.setattr(startspine, "_url_ready", fake_url_ready)
    monkeypatch.setattr(
        startspine,
        "_ollama_ready",
        lambda host="127.0.0.1": checked_ollama.append(host) or False,
    )
    monkeypatch.setattr(startspine, "_json_url", lambda url: None)
    args = argparse.Namespace(
        host="remote-control",
        gui_port=None,
        control_port=None,
        json=True,
    )

    assert startspine.command_status(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ollama"]["host"] == "127.0.0.1"
    assert checked_ollama == ["127.0.0.1"]
    assert "http://remote-control:11434/api/tags" not in checked_urls


def test_tray_health_requires_launch_bound_ready_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    identity = startspine._process_identity(os.getpid())
    record = {
        "root": str(startspine.ROOT_DIR),
        "launch_id": "launch-1",
        "pid": os.getpid(),
        "create_time": identity["create_time"],
    }
    assert not startspine._service_health("tray", record)
    startspine._atomic_json(
        startspine._ready_receipt_path("tray"),
        {"launch_id": "other", "pid": os.getpid()},
    )
    assert not startspine._service_health("tray", record)
    startspine._atomic_json(
        startspine._ready_receipt_path("tray"),
        {"launch_id": "launch-1", "pid": os.getpid()},
    )
    assert startspine._service_health("tray", record)


def test_short_lived_tray_never_reports_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    state = startspine._base_state()
    ready = startspine._start_service(
        state,
        "tray",
        command=[sys.executable, "-c", "import time; time.sleep(.75); raise SystemExit(7)"],
        cwd=tmp_path,
        env=startspine._child_environment(),
        required=True,
        host="127.0.0.1",
        desired_port=8081,
        actual_port=8081,
        readiness_timeout=2.0,
    )
    record = state["services"]["tray"]
    assert ready is False
    assert record["status"] == "failed"
    assert isinstance(record["exit_code"], int)
    assert record["exit_code"] != 0
    assert not startspine._child_identity_alive(record)
    assert not startspine._supervisor_identity_alive(record)


def test_failed_replacement_stop_blocks_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    state = startspine._base_state()
    state["services"]["tray"] = {
        "host": "old-host",
        "desired_port": 8081,
        "actual_port": 8081,
    }
    monkeypatch.setattr(startspine, "_sync_receipt", lambda name, record: record)
    monkeypatch.setattr(startspine, "_record_has_live_identity", lambda record: True)
    monkeypatch.setattr(startspine, "_stop_record", lambda name, record: False)
    monkeypatch.setattr(
        startspine,
        "_spawn_supervisor",
        lambda name, spec: pytest.fail("unsafe replacement spawn"),
    )

    assert not startspine._start_service(
        state,
        "tray",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
        env=startspine._child_environment(),
        required=True,
        host="127.0.0.1",
        desired_port=8081,
        actual_port=8081,
    )


def test_failed_start_cleans_owned_supervisor(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    state = startspine._base_state()
    stopped = []
    monkeypatch.setattr(
        startspine,
        "_spawn_supervisor",
        lambda name, spec: ({
            "launch_id": "launch-2",
            "supervisor_pid": 123,
            "supervisor_create_time": 1.0,
        }, "launch-2"),
    )
    monkeypatch.setattr(startspine, "_wait_for_receipt", lambda *args: {})
    monkeypatch.setattr(startspine, "_wait_ready", lambda *args: False)
    monkeypatch.setattr(startspine, "_record_is_owned", lambda record: False)
    monkeypatch.setattr(startspine, "_supervisor_is_owned", lambda record: True)
    monkeypatch.setattr(
        startspine,
        "_stop_record",
        lambda name, record: stopped.append(name) or True,
    )

    assert not startspine._start_service(
        state,
        "tray",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
        env=startspine._child_environment(),
        required=True,
        host="127.0.0.1",
        desired_port=8081,
        actual_port=8081,
        readiness_timeout=0.1,
    )
    assert stopped == ["tray"]
