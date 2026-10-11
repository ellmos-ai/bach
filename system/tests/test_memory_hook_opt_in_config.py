"""Trusted configuration CAS for the optional MemoryHook attachment."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hub._services.chat import slots_config as slots


def _initialized_slots(tmp_path: Path) -> str:
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    return path


def _core_agent(snapshot: dict, slot_id: str = "buddha_chat") -> dict:
    return next(agent for agent in snapshot["agents"] if agent["id"] == slot_id)


def _worker(tmp_path: Path) -> tuple[str, str]:
    path = _initialized_slots(tmp_path)
    worker = slots.add_worker(
        {"name": "Memory hook fixture", "sub_mode": "hintergrund_worker"}, path=path
    )
    return path, worker["id"]


def test_core_opt_in_is_default_false_cas_versioned_and_resettable(tmp_path):
    path = _initialized_slots(tmp_path)
    initial = slots.core_system_agents_snapshot(path)
    assert all(agent["memory_hook_opt_in"] is False for agent in initial["agents"])
    for invalid in (1, 1.0, None, "true"):
        config = slots.load_slots_config(path, strict=True)
        config["slots"]["buddha_chat"]["memory_hook_opt_in"] = invalid
        slots.save_slots_config(config, path)
        with pytest.raises(ValueError, match="memory_hook_opt_in"):
            slots.core_system_agents_snapshot(path)
        config = slots.load_slots_config(path, strict=True)
        config["slots"]["buddha_chat"]["memory_hook_opt_in"] = False
        slots.save_slots_config(config, path)
    initial = slots.core_system_agents_snapshot(path)

    configured = slots.change_core_system_agent(
        "buddha_chat", initial["configuration_version"],
        {"allow_tools": False, "max_tool_rounds": 7}, path=path,
    )
    enabled = slots.change_core_system_agent(
        "buddha_chat", configured["configuration_version"],
        {"memory_hook_opt_in": True}, path=path,
    )
    agent = _core_agent(enabled)
    assert agent["memory_hook_opt_in"] is True
    assert agent["allow_tools"] is False
    assert agent["max_tool_rounds"] == 7
    assert enabled["configuration_version"] != configured["configuration_version"]
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_core_system_agent(
            "buddha_chat", initial["configuration_version"], {"name": "Stale"}, path=path
        )

    reset = slots.change_core_system_agent(
        "buddha_chat", enabled["configuration_version"], reset=True, path=path
    )
    assert _core_agent(reset)["memory_hook_opt_in"] is False
    for slot_id in ("buddha_always_on", "buddha_connector"):
        enabled = slots.change_core_system_agent(
            slot_id, reset["configuration_version"], {"memory_hook_opt_in": True}, path=path
        )
        assert _core_agent(enabled, slot_id)["memory_hook_opt_in"] is True
        reset = slots.change_core_system_agent(
            slot_id, enabled["configuration_version"], reset=True, path=path
        )
        assert _core_agent(reset, slot_id)["memory_hook_opt_in"] is False


@pytest.mark.parametrize("value", [1, 1.0, None, "true"])
def test_core_opt_in_rejects_non_boolean_without_writing(tmp_path, value):
    path = _initialized_slots(tmp_path)
    before = Path(path).read_bytes()
    version = slots.core_system_agents_snapshot(path)["configuration_version"]
    with pytest.raises(ValueError, match="memory_hook_opt_in"):
        slots.change_core_system_agent(
            "buddha_chat", version, {"memory_hook_opt_in": value}, path=path
        )
    assert Path(path).read_bytes() == before


def test_core_legacy_missing_opt_in_reads_false_and_generic_update_cannot_bypass_cas(tmp_path):
    path = _initialized_slots(tmp_path)
    config = slots.load_slots_config(path, strict=True)
    config["slots"]["buddha_chat"].pop("memory_hook_opt_in")
    slots.save_slots_config(config, path)
    snapshot = slots.core_system_agents_snapshot(path)
    assert _core_agent(snapshot)["memory_hook_opt_in"] is False
    before = Path(path).read_bytes()
    with pytest.raises(ValueError, match="versioniertes Konfigurations-CAS"):
        slots.update_slot("buddha_chat", {"memory_hook_opt_in": True}, path=path)
    assert Path(path).read_bytes() == before


def test_worker_opt_in_is_default_false_cas_versioned_and_preserves_permissions(tmp_path):
    path, worker_id = _worker(tmp_path)
    initial_worker = slots.get_worker_slot(worker_id, path=path)
    assert initial_worker["memory_hook_opt_in"] is False
    initial = slots.worker_configuration_snapshot(worker_id, path=path)
    assert initial["configuration"]["memory_hook_opt_in"] is False
    for invalid in (1, 1.0, None, "true"):
        config = slots.load_slots_config(path, strict=True)
        config["dynamic_workers"][0]["memory_hook_opt_in"] = invalid
        slots.save_slots_config(config, path)
        with pytest.raises(ValueError, match="memory_hook_opt_in"):
            slots.worker_configuration_snapshot(worker_id, path=path)
        config = slots.load_slots_config(path, strict=True)
        config["dynamic_workers"][0]["memory_hook_opt_in"] = False
        slots.save_slots_config(config, path)
    initial = slots.worker_configuration_snapshot(worker_id, path=path)

    configured = slots.change_worker_configuration(
        worker_id, initial["configuration_version"],
        {"allow_tools": False, "max_tool_rounds": 9}, path=path,
    )
    enabled = slots.change_worker_configuration(
        worker_id, configured["configuration_version"],
        {"memory_hook_opt_in": True}, path=path,
    )
    assert enabled["configuration"]["memory_hook_opt_in"] is True
    assert enabled["configuration"]["allow_tools"] is False
    assert enabled["configuration"]["max_tool_rounds"] == 9
    assert enabled["configuration_version"] != configured["configuration_version"]
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_worker_configuration(
            worker_id, initial["configuration_version"], {"name": "Stale"}, path=path
        )

    disabled = slots.change_worker_configuration(
        worker_id, enabled["configuration_version"],
        {"memory_hook_opt_in": False}, path=path,
    )
    assert disabled["configuration"]["memory_hook_opt_in"] is False
    assert disabled["configuration"]["allow_tools"] is False
    assert disabled["configuration"]["max_tool_rounds"] == 9


@pytest.mark.parametrize("value", [1, 1.0, None, "true"])
def test_worker_opt_in_rejects_non_boolean_without_writing(tmp_path, value):
    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    before = Path(path).read_bytes()
    with pytest.raises(ValueError, match="memory_hook_opt_in"):
        slots.change_worker_configuration(
            worker_id, snapshot["configuration_version"],
            {"memory_hook_opt_in": value}, path=path,
        )
    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("value", [False, True])
def test_worker_creation_cannot_take_opt_in_from_payload(tmp_path, value):
    path = _initialized_slots(tmp_path)
    before = Path(path).read_bytes()
    with pytest.raises(ValueError, match="erst nach Erstellung"):
        slots.add_worker(
            {"name": "Untrusted payload", "sub_mode": "hintergrund_worker",
             "memory_hook_opt_in": value}, path=path,
        )
    assert Path(path).read_bytes() == before


def test_worker_legacy_missing_opt_in_reads_false_and_is_in_cas_hash(tmp_path):
    path, worker_id = _worker(tmp_path)
    config = slots.load_slots_config(path, strict=True)
    config["dynamic_workers"][0].pop("memory_hook_opt_in")
    slots.save_slots_config(config, path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    assert snapshot["configuration"]["memory_hook_opt_in"] is False
    enabled = slots.change_worker_configuration(
        worker_id, snapshot["configuration_version"],
        {"memory_hook_opt_in": True}, path=path,
    )
    assert enabled["configuration"]["memory_hook_opt_in"] is True
    assert enabled["configuration_version"] != snapshot["configuration_version"]


def test_worker_get_and_cas_adapter_project_strict_boolean(tmp_path, monkeypatch):
    from gui.api import worker_status_adapter as adapter

    path, worker_id = _worker(tmp_path)
    calls = []

    def request(method, endpoint, *, body=None, **_kwargs):
        calls.append((method, endpoint))
        assert endpoint == "workers/configuration"
        if method == "GET":
            return {"ok": True, **slots.worker_configuration_snapshot(worker_id, path=path)}
        assert method == "POST" and isinstance(body, dict)
        result = slots.change_worker_configuration(
            body["id"], body["configuration_version"], body["changes"], path=path
        )
        return {"ok": True, **result}

    monkeypatch.setattr(adapter, "_request_control_api", request)
    monkeypatch.setattr(adapter, "read_worker_status", lambda **_kwargs: {
        "workers": [{"id": worker_id, "status": "idle"}]
    })

    initial = adapter.read_worker_configuration(worker_id, device_token="fixture-token")
    assert initial["configuration"]["memory_hook_opt_in"] is False
    enabled = adapter.update_worker_configuration(
        worker_id, initial["configuration_version"], {"memory_hook_opt_in": True},
        device_token="fixture-token",
    )
    assert enabled["configuration"]["memory_hook_opt_in"] is True
    disabled = adapter.update_worker_configuration(
        worker_id, enabled["configuration_version"], {"memory_hook_opt_in": False},
        device_token="fixture-token",
    )
    assert disabled["configuration"]["memory_hook_opt_in"] is False
    assert [method for method, _endpoint in calls].count("POST") == 2


@pytest.mark.parametrize("value", [1, None, "true"])
def test_worker_adapter_get_and_cas_reject_non_boolean_values(tmp_path, monkeypatch, value):
    from gui.api import worker_status_adapter as adapter

    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    malformed = {**snapshot, "configuration": {
        **snapshot["configuration"], "memory_hook_opt_in": value,
    }}
    with pytest.raises(adapter.WorkerStatusUnavailable, match="memory_hook_opt_in"):
        adapter._project_configuration({"ok": True, **malformed}, worker_id)

    monkeypatch.setattr(adapter, "read_worker_status", lambda **_kwargs: pytest.fail("status read before validation"))
    monkeypatch.setattr(adapter, "_request_control_api", lambda *args, **kwargs: pytest.fail("CAS request sent"))
    with pytest.raises(adapter.WorkerActionRejected, match="memory_hook_opt_in"):
        adapter.update_worker_configuration(
            worker_id, snapshot["configuration_version"], {"memory_hook_opt_in": value},
            device_token="fixture-token",
        )


def test_slots_config_save_uses_unique_closed_tempfiles_and_cleans_failed_replace(tmp_path, monkeypatch):
    path = Path(_initialized_slots(tmp_path))
    config = slots.load_slots_config(str(path), strict=True)
    replace_sources = []
    original_replace = Path.replace

    def record_replace(source, target):
        if Path(target) == path:
            assert source.is_file()
            replace_sources.append(source)
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    slots.save_slots_config(config, str(path))
    slots.save_slots_config(config, str(path))

    assert len(replace_sources) == 2
    assert replace_sources[0] != replace_sources[1]
    assert all(not source.exists() for source in replace_sources)
    assert json.loads(path.read_text(encoding="utf-8"))
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []

    previous_bytes = path.read_bytes()
    config["slots"]["buddha_chat"]["name"] = "Nicht veröffentlicht"

    def fail_replace(source, target):
        if Path(target) == path:
            assert source.is_file()
            raise OSError("simulierter atomarer Austauschfehler")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulierter atomarer Austauschfehler"):
        slots.save_slots_config(config, str(path))

    assert path.read_bytes() == previous_bytes
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_parallel_worker_config_cas_keeps_one_complete_winner(tmp_path):
    path, worker_id = _worker(tmp_path)
    version = slots.worker_configuration_snapshot(worker_id, path=path)["configuration_version"]
    barrier = threading.Barrier(2)

    def edit(name):
        barrier.wait(timeout=10)
        try:
            slots.change_worker_configuration(
                worker_id, version, {"name": name}, path=path
            )
            return name
        except RuntimeError as error:
            if str(error) == "configuration_version_conflict":
                return None
            raise

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ("Erster Gewinner", "Zweiter Gewinner")))

    winners = [name for name in results if name is not None]
    assert len(winners) == 1
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    assert snapshot["configuration"]["name"] == winners[0]
    assert snapshot["configuration"]["memory_hook_opt_in"] is False
    persisted = json.loads(Path(path).read_text(encoding="utf-8"))
    stored = [worker for worker in persisted["dynamic_workers"] if worker["id"] == worker_id]
    assert len(stored) == 1
    assert stored[0]["name"] == winners[0]
    assert list(Path(path).parent.glob(f".{Path(path).name}.*.tmp")) == []
