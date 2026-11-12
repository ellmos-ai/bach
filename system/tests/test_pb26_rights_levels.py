"""Tests for PB-26 background worker rights levels (Stufe I/II/III) and execute_command env hardening."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

for _mod in ("pystray", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"):
    sys.modules.setdefault(_mod, MagicMock())

from hub._services.chat import bach_tools, chat_tray, slots_config, worker_write_guard


def test_background_worker_default_tools_three_levels():
    # Default ("full") and ("full", "execute") -> Level III (read + write + execute_command)
    full_default = slots_config.background_worker_default_tools("full")
    full_execute = slots_config.background_worker_default_tools("full", "execute")
    assert full_default == full_execute
    assert "execute_command" in full_default
    assert "write_file" in full_default
    assert "edit_file" in full_default
    assert "start_task_worktree" in full_default
    assert "finish_task" in full_default
    assert "safe_shell" in full_default

    # ("full", "write") -> Level II (read + write_only, NO execute_command)
    full_write = slots_config.background_worker_default_tools("full", "write")
    for tool in ("safe_shell", "start_task_worktree", "write_file", "edit_file", "finish_task"):
        assert tool in full_write
    assert "execute_command" not in full_write
    for tool in slots_config.BACKGROUND_WORKER_READ_TOOLS:
        assert tool in full_write

    # ("safe"), ("safe", "write"), ("full", "read") -> Level I (read only)
    for args in (("safe",), ("safe", "write"), ("safe", "execute"), ("full", "read")):
        read_only = slots_config.background_worker_default_tools(*args)
        assert read_only == list(slots_config.BACKGROUND_WORKER_READ_TOOLS)
        assert "write_file" not in read_only
        assert "edit_file" not in read_only
        assert "start_task_worktree" not in read_only
        assert "finish_task" not in read_only
        assert "execute_command" not in read_only


def test_always_on_projection_respects_rights_and_explicit_allowed_tools(tmp_path):
    cfg_path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(cfg_path)

    # Default config: mode="full", rights unset -> Level III (includes execute_command)
    projected = slots_config.get_always_on_execution_slot(cfg_path)
    assert "execute_command" in projected["allowed_tools"]
    assert "write_file" in projected["allowed_tools"]

    # Level II: mode="full", rights="write" -> write tools without execute_command
    slots_config.update_slot("buddha_always_on", {"mode": "full", "rights": "write"}, cfg_path)
    projected_write = slots_config.get_always_on_execution_slot(cfg_path)
    assert "write_file" in projected_write["allowed_tools"]
    assert "execute_command" not in projected_write["allowed_tools"]

    # Level I: mode="safe", rights="read" -> read tools only
    slots_config.update_slot("buddha_always_on", {"mode": "safe", "rights": "read"}, cfg_path)
    projected_read = slots_config.get_always_on_execution_slot(cfg_path)
    assert projected_read["allowed_tools"] == list(slots_config.BACKGROUND_WORKER_READ_TOOLS)

    # Explicit allowed_tools list is never overridden by rights/mode projection
    slots_config.update_slot(
        "buddha_always_on",
        {"mode": "full", "rights": "execute", "allowed_tools": ["read_file", "task_manage"]},
        cfg_path,
    )
    projected_explicit = slots_config.get_always_on_execution_slot(cfg_path)
    assert projected_explicit["allowed_tools"] == ["read_file", "task_manage"]


def test_update_slot_rights_roundtrip_and_validation(tmp_path):
    cfg_path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(cfg_path)

    for mode, rights in (("full", "write"), ("safe", "read"), ("full", "execute")):
        updated = slots_config.update_slot("buddha_always_on", {"mode": mode, "rights": rights}, cfg_path)
        assert updated["mode"] == mode
        assert updated["rights"] == rights
        reloaded = slots_config.get_slot("buddha_always_on", cfg_path)
        assert reloaded["mode"] == mode
        assert reloaded["rights"] == rights

    for invalid in ("sudo", "", 123, None, ["read"]):
        with pytest.raises(ValueError):
            slots_config.update_slot("buddha_always_on", {"rights": invalid}, cfg_path)


def test_dynamic_worker_rights_default_and_configuration_update(tmp_path):
    cfg_path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(cfg_path)

    worker = slots_config.add_worker({"name": "Rights Worker", "task_prompt": "Test task"}, cfg_path)
    assert worker["rights"] == "write"
    wid = worker["id"]

    snap = slots_config.worker_configuration_snapshot(wid, path=cfg_path)
    assert snap["configuration"]["rights"] == "write"

    for new_rights in ("read", "execute", "write"):
        snap = slots_config.change_worker_configuration(
            wid, snap["configuration_version"], {"rights": new_rights}, path=cfg_path
        )
        assert snap["configuration"]["rights"] == new_rights
        assert slots_config.get_worker_slot(wid, path=cfg_path)["rights"] == new_rights

    for bad_rights in ("sudo", "", 123):
        with pytest.raises(ValueError):
            slots_config.change_worker_configuration(
                wid, snap["configuration_version"], {"rights": bad_rights}, path=cfg_path
            )

    with pytest.raises(ValueError):
        slots_config.add_worker({"name": "Bad Worker", "rights": "sudo", "task_prompt": "x"}, cfg_path)


def test_tray_menu_exposes_three_german_rights_levels_and_dispatches_updates(monkeypatch):
    class FakeMenu(list):
        SEPARATOR = object()

        def __init__(self, *items):
            super().__init__(items)

    class FakeMenuItem:
        SEPARATOR = object()

        def __init__(self, text, action=None, checked=None, radio=False, enabled=True, default=False):
            self.text = text
            self.action = action
            self._checked = checked
            self.radio = radio
            self.enabled = enabled
            self.default = default

        @property
        def checked(self):
            return bool(self._checked(self)) if callable(self._checked) else bool(self._checked)

    fake_pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem)
    monkeypatch.setattr(chat_tray, "pystray", fake_pystray, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "pystray", fake_pystray)

    tray = chat_tray.BACHTray.__new__(chat_tray.BACHTray)
    tray.remote = False
    tray.idle_enabled = True
    tray.state = {"connected": True, "mode": "safe", "think": True, "fackel_preference": "ollama"}
    tray.models = ["qwen3.8:27b-mlx"]
    tray.backends = {"ollama": {"available": True}}
    tray.prompts = {}
    tray.favorite_prompts = {}
    tray.permissions = {}
    tray.modular_status = {}
    tray.modular_standalone_count = 0
    tray.module_updates = {"has_updates": False, "count": 0, "updates": []}
    tray.services = {}
    tray.dynamic_workers = []
    tray.idle_task_name = None
    tray.icon = None
    tray._always_on_runtime_label = lambda slot: "Bereit"
    tray._fackel_runtime_label = lambda: "Fackel: Ollama"
    tray._build_modular_status_menu_items = lambda: []
    tray._promptboard_app_path = lambda: None
    calls = []
    tray._api = lambda method, endpoint, data=None, **kw: (calls.append((method, endpoint, data)) or {"ok": True})
    tray._refresh = lambda: None
    tray._update_icon = lambda: None
    tray._notify_error = lambda msg: None

    expected_labels = [
        "Stufe I: nur lesen",
        "Stufe II: lesen + schreiben",
        "Stufe III: schreiben + Befehle ausführen",
    ]
    expected_updates = {
        "Stufe I: nur lesen": {"mode": "safe", "rights": "read"},
        "Stufe II: lesen + schreiben": {"mode": "full", "rights": "write"},
        "Stufe III: schreiben + Befehle ausführen": {"mode": "full", "rights": "execute"},
    }

    for slot_state, active_label in (
        ({"mode": "safe", "rights": "read"}, "Stufe I: nur lesen"),
        ({"mode": "full", "rights": "write"}, "Stufe II: lesen + schreiben"),
        ({"mode": "full", "rights": "execute"}, "Stufe III: schreiben + Befehle ausführen"),
        ({"mode": "full"}, "Stufe III: schreiben + Befehle ausführen"),
    ):
        tray.slots = {
            "buddha_chat": {"mode": "safe"},
            "buddha_always_on": {"id": "buddha_always_on", "enabled": True, "status": "idle", **slot_state},
            "buddha_connector": {"mode": "safe"},
        }
        menu = tray._build_menu()
        always_menu_item = next(
            item for item in menu
            if isinstance(item, FakeMenuItem) and "Buddha Always-On" in str(item.text)
        )
        level_items = {
            item.text: item
            for item in always_menu_item.action
            if isinstance(item, FakeMenuItem) and item.text in expected_labels
        }
        assert list(level_items.keys()) == expected_labels
        for label, item in level_items.items():
            assert item.radio is True
            assert item.checked is (label == active_label)

    # Clicking each level item sends the exact mode+rights update to /api/slots
    for label, item in level_items.items():
        calls.clear()
        item.action(item)
        assert calls == [("POST", "/api/slots", {"slot_id": "buddha_always_on", "updates": expected_updates[label]})]


def test_execute_command_environment_hardening(tmp_path, monkeypatch):
    synthetic_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "LANG": "de_DE.UTF-8",
        "VIRTUAL_ENV": str(tmp_path / "venv"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(tmp_path / "py"),
        "GITHUB_TOKEN": "test-only-dummy",
        "GH_TOKEN": "test-only-dummy",
        "OPENAI_API_KEY": "test-only-dummy",
        "ANTHROPIC_API_KEY": "test-only-dummy",
        "OPENROUTER_API_KEY": "test-only-dummy",
        "BACH_CONTROL_TOKEN": "test-only-dummy",
        "AWS_SECRET_ACCESS_KEY": "test-only-dummy",
        "MY_CUSTOM_PASSWORD": "test-only-dummy",
        "DB_PASSWD": "test-only-dummy",
        "SERVICE_SECRET": "test-only-dummy",
        "EXTERNAL_APIKEY": "test-only-dummy",
        "TLS_PRIVATE_KEY": "test-only-dummy",
        "CLOUD_CREDENTIAL_FILE": "test-only-dummy",
        "GIT_ASKPASS": "/bin/echo",
        "SSH_ASKPASS": "/bin/echo",
        "SSH_AUTH_SOCK": "/tmp/ssh-agent.sock",
    }
    hardened = worker_write_guard.build_execute_command_env(synthetic_env)

    for removed in (
        "GITHUB_TOKEN", "GH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY", "BACH_CONTROL_TOKEN", "AWS_SECRET_ACCESS_KEY",
        "MY_CUSTOM_PASSWORD", "DB_PASSWD", "SERVICE_SECRET", "EXTERNAL_APIKEY",
        "TLS_PRIVATE_KEY", "CLOUD_CREDENTIAL_FILE", "GIT_ASKPASS",
        "SSH_ASKPASS", "SSH_AUTH_SOCK",
    ):
        assert removed not in hardened

    assert hardened["PATH"] == "/usr/bin:/bin"
    assert hardened["HOME"] == str(tmp_path / "home")
    assert hardened["LANG"] == "de_DE.UTF-8"
    assert hardened["VIRTUAL_ENV"] == str(tmp_path / "venv")
    assert hardened["PYTHONIOENCODING"] == "utf-8"
    assert hardened["PYTHONPATH"] == str(tmp_path / "py")
    assert hardened["GIT_TERMINAL_PROMPT"] == "0"
    assert hardened["GIT_CONFIG_COUNT"] == "1"
    assert hardened["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert hardened["GIT_CONFIG_VALUE_0"] == ""

    # _worker_check_environment also strips secrets and sets git non-interactive config
    check_env, _, _ = worker_write_guard._worker_check_environment(tmp_path, environ=synthetic_env)
    assert "GITHUB_TOKEN" not in check_env
    assert "OPENAI_API_KEY" not in check_env
    assert check_env["GIT_TERMINAL_PROMPT"] == "0"
    assert check_env["GIT_CONFIG_KEY_0"] == "credential.helper"

    # run_shell_restricted with allowed=None (execute_command path) passes hardened env
    captured_env = {}

    def fake_run(argv, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setenv("GITHUB_TOKEN", "test-only-dummy")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-dummy")
    monkeypatch.setattr(bach_tools.safe_exec, "resolve_executable", lambda cmd, allowed: ["python", "-V"])
    monkeypatch.setattr(bach_tools.subprocess, "run", fake_run)

    out = bach_tools.run_shell_restricted("python -V", allowed=None)
    assert out == "ok"
    assert "GITHUB_TOKEN" not in captured_env
    assert "OPENAI_API_KEY" not in captured_env
    assert captured_env["GIT_TERMINAL_PROMPT"] == "0"
    assert captured_env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert captured_env["PYTHONIOENCODING"] == "utf-8"
