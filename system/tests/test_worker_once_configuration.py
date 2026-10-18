"""An explicitly saved once mode ends after its bound task."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from hub._services.chat import slots_config as slots


def profile(tmp_path, worker_type="continuous"):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    worker = slots.add_worker({"name": "Cloud", "backend": "ollama-cloud",
        "model": "glm-5.3:cloud", "type": worker_type,
        "sub_mode": "hintergrund_worker"}, path=path)
    return path, worker["id"]


@pytest.mark.parametrize("worker_type", ["continuous", "persistent"])
def test_once_mode_is_persisted_read_back_and_versioned(tmp_path, worker_type):
    path, wid = profile(tmp_path, worker_type)
    before = slots.worker_configuration_snapshot(wid, path=path)
    assert before["configuration"]["type"] == "continuous"
    after = slots.change_worker_configuration(wid, before["configuration_version"],
        {"type": "once", "sub_mode": "task_worker", "task_id": 2111}, path=path)
    assert after["configuration"]["type"] == "once"
    assert after["configuration_version"] != before["configuration_version"]
    saved = slots.get_worker_slot(wid, path=path)
    assert saved["type"] == "once" and saved["task_id"] == 2111 and saved["status"] == "idle"
    assert after == slots.worker_configuration_snapshot(wid, path=path)
    raw = Path(path).read_bytes()
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_worker_configuration(wid, before["configuration_version"], {"type": "continuous"}, path=path)
    assert Path(path).read_bytes() == raw


@pytest.mark.parametrize("bad", [None, True, "persistent", "bad", [], {}])
def test_invalid_mode_does_not_change_saved_profile(tmp_path, bad):
    path, wid = profile(tmp_path)
    before = slots.worker_configuration_snapshot(wid, path=path)
    raw = Path(path).read_bytes()
    with pytest.raises(ValueError, match="Arbeitsmodus"):
        slots.change_worker_configuration(wid, before["configuration_version"], {"type": bad}, path=path)
    assert Path(path).read_bytes() == raw


@pytest.mark.parametrize("status", ["running", "stopping"])
def test_live_profile_mode_cannot_change(tmp_path, status):
    path, wid = profile(tmp_path)
    slots.update_slot(wid, {"status": status}, path=path)
    before = slots.worker_configuration_snapshot(wid, path=path)
    with pytest.raises(RuntimeError, match="worker_not_editable"):
        slots.change_worker_configuration(wid, before["configuration_version"], {"type": "once"}, path=path)
    assert slots.get_worker_slot(wid, path=path)["type"] == "continuous"


def test_legacy_mode_round_trip_remains_equivalent_without_rewriting_on_read(tmp_path):
    path, wid = profile(tmp_path, "persistent")
    raw = Path(path).read_bytes()
    before = slots.worker_configuration_snapshot(wid, path=path)
    assert before["configuration"]["type"] == "continuous"
    assert Path(path).read_bytes() == raw
    after = slots.change_worker_configuration(wid, before["configuration_version"], {"name": "Renamed"}, path=path)
    assert after["configuration"]["type"] == "continuous"
    assert slots.get_worker_slot(wid, path=path)["type"] == "persistent"


def test_existing_persistent_consent_digest_is_preserved_and_once_edit_revokes_it(tmp_path):
    from hub._services.chat.worker_queue_status import worker_selection_policy
    path, wid = profile(tmp_path, "persistent")
    worker = slots.get_worker_slot(wid, path=path)
    fields = slots.WORKER_EDITABLE_FIELDS - {"persistent_opt_in", "type", "max_model_requests"}
    legacy = {field: worker.get(field) for field in sorted(fields)}
    raw = json.dumps({"id": wid, **legacy, "selection_policy": worker_selection_policy(worker)},
        sort_keys=True, ensure_ascii=False).encode()
    assert slots._worker_profile_version(worker) == hashlib.sha256(raw).hexdigest()
    before = slots.worker_configuration_snapshot(wid, path=path)
    granted = slots.change_worker_configuration(wid, before["configuration_version"],
        {"persistent_opt_in": True}, path=path)
    assert granted["persistent_opt_in"] is True
    after = slots.change_worker_configuration(wid, granted["configuration_version"], {"type": "once"}, path=path)
    assert after["configuration"]["type"] == "once" and after["persistent_opt_in"] is False


@pytest.mark.parametrize("requested", ["once", "continuous", None])
def test_gui_route_passes_explicit_mode_and_preserves_omitted_mode(monkeypatch, requested):
    from gui.api import unified_api, worker_status_adapter as adapter
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _: "fixture-token")
    monkeypatch.setattr(adapter, "worker_model_catalog", lambda *a, **k: {"models": ["glm-5.3:cloud"]})
    seen = []
    monkeypatch.setattr(adapter, "update_worker_configuration", lambda wid, version, changes, **kw:
        seen.append(changes) or {"ok": True, "id": wid, "configuration": changes})
    config = {"name": "Cloud", "backend": "ollama-cloud", "model": "glm-5.3:cloud",
        "sub_mode": "task_worker", "task_id": 2111, "mode": "safe"}
    if requested is not None:
        config["type"] = requested
    result = asyncio.run(unified_api.update_system_worker_configuration("worker-1", None,
        {"configuration_version": "a" * 64, "configuration": config}))
    assert result["ok"] is True
    if requested is None:
        assert "type" not in seen[0]
    else:
        assert seen[0]["type"] == requested
