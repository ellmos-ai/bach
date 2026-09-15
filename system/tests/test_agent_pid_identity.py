"""Regression: agent stop must never target a reused or unverified PID."""

from __future__ import annotations

import json
import hashlib

import pytest
from filelock import FileLock

from hub.agent_launcher import AgentLauncherHandler
from hub import agent_process_provider as provider


@pytest.fixture
def handler(tmp_path):
    root = tmp_path / "system"
    (root / "data" / "agent_pids").mkdir(parents=True)
    return AgentLauncherHandler(root)


def _pid_file(handler, created=10.0):
    path = handler.pid_dir / "test-boss.pid"
    payload = {"pid": 4242, "name": "test-boss"}
    if created is not None:
        payload["process_create_time"] = created
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_stop_refuses_reused_pid_before_any_kill(handler, monkeypatch):
    pid_file = _pid_file(handler)
    calls = []
    monkeypatch.setattr("hub.agent_launcher.sys.platform", "win32")
    monkeypatch.setattr("hub.agent_launcher.subprocess.run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: _FakeProcess(11.0))

    ok, message = handler._stop_agent("test-boss", dry_run=False)

    assert not ok
    assert "stimmt nicht" in message
    assert calls == []
    assert pid_file.exists()


class _FakeProcess:
    def __init__(self, created=10.0, *, children=()):
        self.created = created
        self.descendants = list(children)
        self.killed = 0
        self.terminated = 0

    def create_time(self):
        return self.created

    def is_running(self):
        return True

    def children(self, recursive=False):
        assert recursive
        return self.descendants

    def kill(self):
        self.killed += 1

    def terminate(self):
        self.terminated += 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_legacy_pid_without_creation_time_fails_closed(handler, monkeypatch, dry_run):
    pid_file = _pid_file(handler, created=None)
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: pytest.fail("legacy PID must not be inspected or killed"))
    ok, message = handler._stop_agent("test-boss", dry_run=dry_run)
    assert not ok
    assert "Alt-PID-Datei" in message
    assert pid_file.exists()


def test_verified_windows_stop_kills_only_bound_process_tree(handler, monkeypatch):
    pid_file = _pid_file(handler)
    child = _FakeProcess()
    parent = _FakeProcess(children=[child])
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: parent)
    monkeypatch.setattr("hub.agent_launcher.sys.platform", "win32")
    monkeypatch.setattr("hub.agent_launcher.subprocess.run", lambda *a, **k: pytest.fail("PID-only taskkill forbidden"))
    ok, _ = handler._stop_agent("test-boss", dry_run=False)
    assert ok
    assert child.killed == parent.killed == 1
    assert not pid_file.exists()


def test_verified_unix_stop_uses_identity_bound_terminate(handler, monkeypatch):
    _pid_file(handler)
    parent = _FakeProcess()
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: parent)
    monkeypatch.setattr("hub.agent_launcher.sys.platform", "linux")
    ok, _ = handler._stop_agent("test-boss", dry_run=False)
    assert ok
    assert parent.terminated == 1


def test_verified_unix_stop_kills_bound_descendants_before_parent(handler, monkeypatch):
    _pid_file(handler)
    child = _FakeProcess()
    parent = _FakeProcess(children=[child])
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: parent)
    monkeypatch.setattr("hub.agent_launcher.sys.platform", "linux")
    ok, _ = handler._stop_agent("test-boss", dry_run=False)
    assert ok
    assert child.killed == 1
    assert parent.terminated == 1


def test_verified_stop_dry_run_checks_identity_but_does_not_kill(handler, monkeypatch):
    pid_file = _pid_file(handler)
    parent = _FakeProcess()
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: parent)
    ok, message = handler._stop_agent("test-boss", dry_run=True)
    assert ok and "DRY-RUN" in message
    assert parent.killed == parent.terminated == 0
    assert pid_file.exists()


@pytest.mark.parametrize("created,state", [(None, "unverified"), (10.0, "mismatch")])
def test_unowned_pid_is_preserved_and_blocks_status_actions_and_start(handler, monkeypatch, created, state):
    pid_file = _pid_file(handler, created=created)
    skill_dir = handler.agents_dir / "test-boss"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: test-boss\n---\n", encoding="utf-8")
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: _FakeProcess(11.0))
    monkeypatch.setattr("hub.agent_launcher.subprocess.Popen", lambda *a, **k: pytest.fail("unsafe start"))

    ok, response = handler.handle("status", ["--json"])
    assert ok
    agent = json.loads(response)["agents"][0]
    assert agent["status"] == state
    assert agent["running"] is False
    assert "start" not in agent["available_actions"]
    assert "stop" not in agent["available_actions"]
    assert "start" not in agent["operator_control"]["available_actions"]
    assert "stop" not in agent["operator_control"]["available_actions"]
    assert pid_file.exists()

    ok, response = handler.handle("status", [])
    assert ok and f"[{state.upper()}]" in response
    assert pid_file.exists()
    ok, response = handler.handle("list", [])
    assert ok and f"[{state.upper()}]" in response
    assert pid_file.exists()
    ok, response = handler.handle("start", ["test-boss"], dry_run=True)
    assert not ok and "Start verweigert" in response
    assert pid_file.exists()


def test_psutil_unavailable_preserves_record_and_refuses_stop(handler, monkeypatch):
    pid_file = _pid_file(handler)
    monkeypatch.setattr(provider, "psutil", None)
    ok, response = handler.handle("stop", ["test-boss"], dry_run=False)
    assert not ok and "nicht lesbar" in response
    assert pid_file.exists()


def test_termination_failure_preserves_record_for_recertification(handler, monkeypatch):
    pid_file = _pid_file(handler)
    parent = _FakeProcess()
    def refuse_termination():
        raise PermissionError("protected")
    parent.terminate = refuse_termination
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: parent)
    monkeypatch.setattr("hub.agent_launcher.sys.platform", "linux")
    ok, response = handler.handle("stop", ["test-boss"], dry_run=False)
    assert not ok and "protected" in response
    assert pid_file.exists()


@pytest.mark.parametrize("content", ["not json", "{}", "[]"])
def test_invalid_pid_evidence_survives_status_and_stop_dry_run(handler, content):
    pid_file = handler.pid_dir / "test-boss.pid"
    pid_file.write_text(content, encoding="utf-8")
    for args in ([], ["--json"]):
        ok, response = handler.handle("status", args)
        assert ok
        assert pid_file.read_text(encoding="utf-8") == content
        if args:
            agent = json.loads(response)["agents"][0]
            assert agent["status"] in {"invalid", "unverified"}
            assert "start" not in agent["available_actions"]
    ok, _response = handler.handle("stop", ["test-boss"], dry_run=True)
    assert not ok
    assert pid_file.read_text(encoding="utf-8") == content


def test_start_dry_run_refuses_when_named_lifecycle_claim_is_held(handler):
    skill_dir = handler.agents_dir / "test-boss"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: test-boss\n---\n", encoding="utf-8")
    digest = hashlib.sha256(b"test-boss").hexdigest()
    claim_path = handler.pid_dir / f".agent-claim-{digest}.lock"
    with FileLock(str(claim_path)):
        ok, response = handler.handle("start", ["test-boss"], dry_run=True)
    assert not ok
    assert "Claim" in response


def test_json_status_does_not_bind_a_file_to_another_agent_name(handler, monkeypatch):
    a_file = handler.pid_dir / "a.pid"
    b_file = handler.pid_dir / "b.pid"
    a_file.write_text(json.dumps({"pid": 4242, "name": "b", "process_create_time": 10.0}), encoding="utf-8")
    b_file.write_text(json.dumps({"pid": 4242, "name": "b", "process_create_time": 10.0}), encoding="utf-8")
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: _FakeProcess())
    ok, response = handler.handle("status", ["--json"])
    assert ok
    agents = json.loads(response)["agents"]
    a_entry = next(agent for agent in agents if agent["pid_file"] == str(a_file))
    assert a_entry["running"] is False
    assert a_entry["status"] == "invalid"
    assert a_file.exists()


def test_stop_refuses_pid_record_named_for_another_agent(handler, monkeypatch):
    a_file = handler.pid_dir / "a.pid"
    a_file.write_text(json.dumps({"pid": 4242, "name": "b", "process_create_time": 10.0}), encoding="utf-8")
    candidate = _FakeProcess()
    monkeypatch.setattr(provider.psutil, "Process", lambda pid: candidate)
    ok, response = handler.handle("stop", ["a"])
    assert not ok and "anderen Agenten" in response
    assert candidate.killed == candidate.terminated == 0
    assert a_file.exists()
