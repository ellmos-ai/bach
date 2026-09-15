"""Contract and rollback tests for the agent-launcher registry seam."""

from __future__ import annotations

import json
import types

import pytest

from hub import agent_launcher as agent_module
from hub.agent_launcher import AgentLauncherHandler
from hub import agent_process_provider as provider


@pytest.fixture
def handler(tmp_path):
    root = tmp_path / "system"
    root.mkdir()
    (root / "data" / "agent_pids").mkdir(parents=True)
    return AgentLauncherHandler(root)


def test_external_registry_reads_same_pid_directory_without_spawning(
    handler, tmp_path, monkeypatch
):
    calls = []

    class Registry:
        def __init__(self, directory):
            calls.append(directory)

        def is_running(self, name):
            calls.append(name)
            return 4242

    monkeypatch.setenv(provider.ROLLBACK_ENV_VAR, "1")
    monkeypatch.setattr(provider.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        provider.importlib, "import_module", lambda name: types.SimpleNamespace(AgentProcessRegistry=Registry)
    )
    assert handler._is_agent_running("test-boss") == 4242
    assert calls == [handler.pid_dir, "test-boss"]
    assert not list(tmp_path.rglob("*.pid"))


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_rollback_uses_legacy_pid_reader(handler, monkeypatch, value):
    monkeypatch.setenv(provider.ROLLBACK_ENV_VAR, value)

    def no_import(_name):
        raise AssertionError("rollback must not import agent-launcher")

    monkeypatch.setattr(provider.importlib, "import_module", no_import)
    pid_file = handler.pid_dir / "test-boss.pid"
    pid_file.write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    monkeypatch.setattr(agent_module.sys, "platform", "win32")
    monkeypatch.setattr(
        agent_module.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(stdout="4242"),
    )
    assert handler._is_agent_running("test-boss") == 4242
    assert pid_file.exists()


def test_missing_module_is_not_an_install_trigger(handler, monkeypatch):
    monkeypatch.setenv(provider.ROLLBACK_ENV_VAR, "1")
    monkeypatch.setattr(provider.importlib.util, "find_spec", lambda name: None)
    assert handler._is_agent_running("unregistered") == 0


def test_default_is_legacy_even_when_external_module_is_installed(handler, monkeypatch):
    monkeypatch.delenv(provider.ROLLBACK_ENV_VAR, raising=False)
    monkeypatch.setattr(provider.importlib.util, "find_spec", lambda name: object())
    assert handler._is_agent_running("unregistered") == 0


def test_broken_external_contract_fails_closed(handler, monkeypatch):
    monkeypatch.setenv(provider.ROLLBACK_ENV_VAR, "1")
    monkeypatch.setattr(provider.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(provider.importlib, "import_module", lambda name: types.SimpleNamespace())
    with pytest.raises(AttributeError, match="AgentProcessRegistry"):
        handler._is_agent_running("test-boss")
