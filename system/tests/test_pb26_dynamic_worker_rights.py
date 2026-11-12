"""PB-26 (G13/G14): runtime-only projection of default write rights for dynamic background workers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import pytest

from hub._services.chat import (
    chat_runtime,
    slots_config,
    telegram_chat,
    worker_selection_preview,
    worker_write_guard,
)


def _write_minimal_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> str:
    cfg_path = tmp_path / "slots_config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "slots": {
                    key: dict(value)
                    for key, value in slots_config.DEFAULT_CORE_SLOTS.items()
                },
                "dynamic_workers": [],
                "activity_history": [],
            }
        ),
        encoding="utf-8",
    )
    if monkeypatch is not None:
        monkeypatch.setattr(slots_config, "DEFAULT_SLOTS_FILE", str(cfg_path))
    return str(cfg_path)


def test_dynamic_worker_default_write_rights_projected_at_runtime(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Write Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "write",
        },
        path=cfg_path,
    )
    assert created["rights"] == "write"
    assert created["allowed_tools"] is None

    # Stored config on disk and config-layer readers keep allowed_tools as None (raw).
    stored_raw = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    assert stored_raw["dynamic_workers"][0]["allowed_tools"] is None
    raw_slot = slots_config.get_worker_slot(created["id"], path=cfg_path)
    assert raw_slot["allowed_tools"] is None

    # Runtime execution slot projects the Level-II tools.
    exec_slot = telegram_chat._execution_worker_slot(created["id"])
    tools = set(exec_slot["allowed_tools"])
    assert {"write_file", "edit_file", "finish_task", "safe_shell", "start_task_worktree"} <= tools
    assert "execute_command" not in tools

    chat_slot = telegram_chat._resolve_slot_for_chat(created["id"])
    assert set(chat_slot["allowed_tools"]) == tools

    # Runtime session refresh and write guard honour the projected level II tools.
    session = chat_runtime.ChatSession()
    session.chat_id = created["id"]
    session.mode = "full"
    session.worker_slot_reader = lambda: telegram_chat._execution_worker_slot(created["id"])
    assert chat_runtime.ChatRuntime._refresh_worker_tools(session) is None
    assert "write_file" in session.allowed_tools
    assert "execute_command" not in session.allowed_tools
    worker_write_guard.require_write_grant("write_file", session.allowed_tools)
    with pytest.raises(worker_write_guard.WorkerWriteGuardError):
        worker_write_guard.require_write_grant("execute_command", session.allowed_tools)

    grants = chat_runtime._effective_tool_grants(session)
    granted_names = {
        tool["function"]["name"]
        for tool in chat_runtime.tools_for_mode(session.mode, bound_worker=True)
        if tool["function"]["name"] in grants
    }
    assert {"write_file", "edit_file", "finish_task", "safe_shell", "start_task_worktree"} <= granted_names
    assert "execute_command" not in granted_names

    # Config/version helpers keep raw allowed_tools=None so rights stay adjustable.
    snap = slots_config.worker_configuration_snapshot(created["id"], path=cfg_path)
    assert snap["configuration"]["allowed_tools"] is None
    at_ver = slots_config.system_worker_at_version(
        created["id"],
        snap["configuration_version"],
        version_scope="worker_profile",
        path=cfg_path,
    )
    assert at_ver is not None
    assert at_ver["allowed_tools"] is None


def test_dynamic_worker_rights_execute_read_and_safe_mode(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)

    exec_worker = slots_config.add_worker(
        {
            "name": "Execute Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "execute",
        },
        path=cfg_path,
    )
    assert slots_config.get_worker_slot(exec_worker["id"], path=cfg_path)["allowed_tools"] is None
    exec_slot = telegram_chat._execution_worker_slot(exec_worker["id"])
    exec_tools = set(exec_slot["allowed_tools"])
    assert {"write_file", "edit_file", "finish_task", "safe_shell", "start_task_worktree", "execute_command"} <= exec_tools

    read_worker = slots_config.add_worker(
        {
            "name": "Read Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "read",
        },
        path=cfg_path,
    )
    assert slots_config.get_worker_slot(read_worker["id"], path=cfg_path)["allowed_tools"] is None
    read_slot = telegram_chat._execution_worker_slot(read_worker["id"])
    assert read_slot["allowed_tools"] == list(slots_config.BACKGROUND_WORKER_READ_TOOLS)
    assert "write_file" not in read_slot["allowed_tools"]
    assert "execute_command" not in read_slot["allowed_tools"]

    safe_worker = slots_config.add_worker(
        {
            "name": "Safe Mode Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "safe",
            "rights": "execute",
        },
        path=cfg_path,
    )
    assert slots_config.get_worker_slot(safe_worker["id"], path=cfg_path)["allowed_tools"] is None
    safe_slot = telegram_chat._execution_worker_slot(safe_worker["id"])
    assert safe_slot["allowed_tools"] == list(slots_config.BACKGROUND_WORKER_READ_TOOLS)
    assert "write_file" not in safe_slot["allowed_tools"]
    assert "execute_command" not in safe_slot["allowed_tools"]


def test_dynamic_worker_without_rights_field_keeps_allowed_tools_none(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Legacy Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
        },
        path=cfg_path,
    )
    # Simulate a pre-#690 persisted worker entry without a "rights" field.
    raw = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    raw["dynamic_workers"][0].pop("rights", None)
    raw["dynamic_workers"][0]["allowed_tools"] = None
    Path(cfg_path).write_text(json.dumps(raw), encoding="utf-8")

    legacy_slot = slots_config.get_worker_slot(created["id"], path=cfg_path)
    assert "rights" not in legacy_slot
    assert legacy_slot["allowed_tools"] is None

    runtime_slot = telegram_chat._execution_worker_slot(created["id"])
    assert "rights" not in runtime_slot
    assert runtime_slot["allowed_tools"] is None


def test_dynamic_worker_explicit_allowed_tools_list_wins(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Explicit Tools Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "execute",
            "allowed_tools": ["read_file"],
        },
        path=cfg_path,
    )
    slot = slots_config.get_worker_slot(created["id"], path=cfg_path)
    assert slot["allowed_tools"] == ["read_file"]
    runtime_slot = telegram_chat._execution_worker_slot(created["id"])
    assert runtime_slot["allowed_tools"] == ["read_file"]


def test_get_worker_slot_and_worker_configuration_return_raw_allowed_tools_none(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Raw Config Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "write",
            "sub_mode": "hintergrund_worker",
        },
        path=cfg_path,
    )
    slot = slots_config.get_worker_slot(created["id"], path=cfg_path)
    assert slot["rights"] == "write"
    assert slot["allowed_tools"] is None

    cfg = slots_config._worker_configuration(slot)
    assert cfg["configuration"]["rights"] == "write"
    assert cfg["configuration"]["allowed_tools"] is None

    snap = slots_config.worker_configuration_snapshot(created["id"], path=cfg_path)
    assert snap["configuration"]["allowed_tools"] is None

    # Editing another field via change_worker_configuration preserves allowed_tools=None
    # so switching rights later continues to adjust runtime tools.
    updated_snap = slots_config.change_worker_configuration(
        created["id"],
        snap["configuration_version"],
        {"rights": "execute"},
        path=cfg_path,
    )
    assert updated_snap["configuration"]["rights"] == "execute"
    assert updated_snap["configuration"]["allowed_tools"] is None
    runtime_slot = telegram_chat._execution_worker_slot(created["id"])
    assert "execute_command" in runtime_slot["allowed_tools"]


def test_worker_profile_version_identical_before_and_after_projection(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Version Stability Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "write",
        },
        path=cfg_path,
    )
    stored_raw = json.loads(Path(cfg_path).read_text(encoding="utf-8"))["dynamic_workers"][0]
    version_before = slots_config._worker_profile_version(stored_raw)

    # Trigger runtime projections.
    exec_slot = telegram_chat._execution_worker_slot(created["id"])
    chat_slot = telegram_chat._resolve_slot_for_chat(created["id"])
    assert exec_slot["allowed_tools"] is not None
    assert chat_slot["allowed_tools"] is not None

    slot_after = slots_config.get_worker_slot(created["id"], path=cfg_path)
    version_after = slots_config._worker_profile_version(slot_after)
    assert version_before == version_after

    # Verify that _worker_profile_version does not secretly project allowed_tools:
    # an explicitly populated allowed_tools list produces a different profile version.
    explicitly_projected = slots_config._project_dynamic_worker_slot(stored_raw)
    assert explicitly_projected["allowed_tools"] is not None
    assert slots_config._worker_profile_version(explicitly_projected) != version_before


def test_runtime_execution_slot_gets_level_ii_tools(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Runtime Level II Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "write",
        },
        path=cfg_path,
    )
    expected_tools = slots_config.background_worker_default_tools("full", "write")

    exec_slot = telegram_chat._execution_worker_slot(created["id"])
    assert exec_slot["allowed_tools"] == expected_tools
    assert {"write_file", "edit_file", "finish_task", "safe_shell", "start_task_worktree"} <= set(exec_slot["allowed_tools"])
    assert "execute_command" not in exec_slot["allowed_tools"]

    chat_slot = telegram_chat._resolve_slot_for_chat(created["id"])
    assert chat_slot["allowed_tools"] == expected_tools


def test_preview_and_display_surfaces_show_effective_rights_and_tools(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Preview Write Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "write",
        },
        path=cfg_path,
    )
    worker_id = created["id"]
    expected_tools = slots_config.background_worker_default_tools("full", "write")

    # 1. _execution_worker_configuration projects raw dynamic worker slots and exposes rights_effective
    raw_slot = slots_config.get_worker_slot(worker_id, path=cfg_path)
    assert raw_slot["allowed_tools"] is None
    assert "rights_effective" not in raw_slot

    exec_cfg_from_raw = telegram_chat._execution_worker_configuration(raw_slot)
    exec_cfg_from_exec = telegram_chat._execution_worker_configuration(
        telegram_chat._execution_worker_slot(worker_id)
    )
    assert exec_cfg_from_raw == exec_cfg_from_exec
    assert exec_cfg_from_raw["configuration"]["allowed_tools"] == expected_tools
    assert exec_cfg_from_raw["configuration"]["rights"] == "write"
    assert exec_cfg_from_raw["rights_effective"] == "write"

    # 2. _preview_worker_selection / preview_worker_selection / project_selection_preview
    class _StubAuthority:
        mode = "local"

        def task_candidates(self, **kwargs):
            return {"tasks": [], "total": 0, "offset": 0, "has_more": False}

    monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: _StubAuthority())
    preview_res = telegram_chat._preview_worker_selection(worker_id)
    snap = slots_config.worker_configuration_snapshot(worker_id, path=cfg_path)
    assert preview_res["configuration_version"] == snap["configuration_version"]
    assert preview_res["rights"] == "write"
    assert preview_res["rights_effective"] == "write"
    assert preview_res["allowed_tools"] == expected_tools
    assert {"write_file", "edit_file", "finish_task", "safe_shell", "start_task_worktree"} <= set(
        preview_res["allowed_tools"]
    )
    assert "execute_command" not in preview_res["allowed_tools"]
    assert worker_selection_preview.project_selection_preview(preview_res, worker_id) == preview_res

    # Direct preview_worker_selection with raw slot also projects runtime tools/rights
    direct_preview = worker_selection_preview.preview_worker_selection(
        _StubAuthority(),
        raw_slot,
        configuration_version=snap["configuration_version"],
        execution_profile_version=preview_res["execution_profile_version"],
    )
    assert direct_preview["rights"] == "write"
    assert direct_preview["rights_effective"] == "write"
    assert direct_preview["allowed_tools"] == expected_tools

    # 3. _worker_handoff_snapshot / _worker_execution_snapshots / _registered_worker_slot
    handoff_snap = telegram_chat._worker_handoff_snapshot(raw_slot)
    assert handoff_snap["allowed_tools"] == expected_tools
    assert handoff_snap["rights"] == "write"
    assert handoff_snap["rights_effective"] == "write"

    exec_snaps = telegram_chat._worker_execution_snapshots()
    our_snap = next(w for w in exec_snaps if w["id"] == worker_id)
    assert our_snap["allowed_tools"] == expected_tools
    assert our_snap["rights_effective"] == "write"

    reg_slot = telegram_chat._registered_worker_slot(worker_id)
    assert reg_slot is not None
    assert reg_slot["allowed_tools"] == expected_tools
    assert reg_slot["rights_effective"] == "write"

    # 4. Safe mode caps rights="execute" to rights_effective="read" and read-only tools
    safe_worker = slots_config.add_worker(
        {
            "name": "Preview Safe Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "safe",
            "rights": "execute",
        },
        path=cfg_path,
    )
    safe_preview = telegram_chat._preview_worker_selection(safe_worker["id"])
    assert safe_preview["rights"] == "execute"
    assert safe_preview["rights_effective"] == "read"
    assert safe_preview["allowed_tools"] == list(slots_config.BACKGROUND_WORKER_READ_TOOLS)

    # Stored config remains raw (allowed_tools is None) across all preview/display calls
    stored_raw = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    for w in stored_raw["dynamic_workers"]:
        assert w["allowed_tools"] is None
        assert "rights_effective" not in w


def test_start_worker_execution_with_expected_version_projects_runtime_slot(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path, monkeypatch)
    created = slots_config.add_worker(
        {
            "name": "Versioned Start Worker",
            "model": "qwen3.8:27b-mlx",
            "backend": "ollama",
            "mode": "full",
            "rights": "write",
        },
        path=cfg_path,
    )
    worker_id = created["id"]
    core_snap = slots_config.core_system_agents_snapshot(cfg_path)
    expected_version = core_snap["configuration_version"]
    expected_tools = slots_config.background_worker_default_tools("full", "write")

    captured: dict = {}

    def _fake_start_reserved(control, slot, custom_prompt=None):
        captured["control"] = control
        captured["slot"] = dict(slot)
        captured["custom_prompt"] = custom_prompt
        control.launch_attempted = True
        control.done_event.set()
        return {"ok": True, "started": True, "id": slot["id"], "allowed_tools": slot.get("allowed_tools")}, 200

    monkeypatch.setattr(telegram_chat, "_assert_worker_profile_inactive", lambda *a, **kw: None)
    monkeypatch.setattr(telegram_chat, "_start_reserved_worker_execution", _fake_start_reserved)
    try:
        res, status = telegram_chat._start_worker_execution(
            worker_id,
            expected_configuration_version=expected_version,
        )
        assert status == 200
        assert res["started"] is True
        started_slot = captured["slot"]
        assert started_slot["allowed_tools"] == expected_tools
        assert started_slot["rights"] == "write"
        assert started_slot["rights_effective"] == "write"
        assert telegram_chat._execution_worker_configuration(
            started_slot
        ) == telegram_chat._execution_worker_configuration(
            telegram_chat._execution_worker_slot(worker_id)
        )
        # Stored config stays raw
        assert slots_config.get_worker_slot(worker_id, path=cfg_path)["allowed_tools"] is None
    finally:
        telegram_chat._WORKER_CONTROLS.pop(worker_id, None)
        telegram_chat._ACTIVE_WORKER_THREADS.pop(worker_id, None)
        telegram_chat._WORKER_EXECUTIONS.pop(worker_id, None)


