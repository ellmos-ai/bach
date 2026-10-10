import pytest
from hub._services.chat import slots_config as slots


def _worker(tmp_path):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    worker = slots.add_worker({"name": "Worker", "backend": "ollama", "model": "test",
                               "sub_mode": "hintergrund_worker"}, path=path)
    return path, worker["id"]


def _valid_pickup_filter():
    return {
        "enabled": True,
        "categories": ["BACH"],
        "priorities": ["P1", "P2"],
        "tags": [],
        "exclude_tags": ["delegated", "waiting"],
    }


def test_pickup_filter_edit_uses_cas_and_returns_only_projected_policy(tmp_path):
    from pathlib import Path

    path, worker_id = _worker(tmp_path)
    before = slots.worker_configuration_snapshot(worker_id, path=path)
    pickup_filter = _valid_pickup_filter()

    result = slots.change_worker_configuration(
        worker_id,
        before["configuration_version"],
        {"pickup_filter": pickup_filter},
        path=path,
    )

    assert result["configuration_version"] != before["configuration_version"]
    assert "pickup_filter" not in result["configuration"]
    assert result["selection_policy"]["pickup_filter"] == pickup_filter
    saved = slots.get_worker_slot(worker_id, path=path)
    assert saved["pickup_filter"] == pickup_filter
    saved_bytes = Path(path).read_bytes()
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_worker_configuration(
            worker_id,
            before["configuration_version"],
            {"pickup_filter": _valid_pickup_filter()},
            path=path,
        )
    assert Path(path).read_bytes() == saved_bytes


def test_pickup_filter_update_adapter_reads_back_selection_policy(tmp_path, monkeypatch):
    from gui.api import worker_status_adapter as adapter

    path, worker_id = _worker(tmp_path)
    before = slots.worker_configuration_snapshot(worker_id, path=path)
    pickup_filter = _valid_pickup_filter()

    monkeypatch.setattr(adapter, "read_worker_status", lambda **kwargs: {
        "workers": [{"id": worker_id, "status": "idle"}],
    })

    def apply_change(method, endpoint, *, body, **kwargs):
        assert method == "POST"
        assert endpoint == "workers/configuration"
        return {"ok": True, **slots.change_worker_configuration(
            body["id"], body["configuration_version"], body["changes"], path=path,
        )}

    def read_configuration(requested_worker_id, **kwargs):
        assert requested_worker_id == worker_id
        snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
        return adapter._project_configuration({"ok": True, **snapshot}, worker_id)

    monkeypatch.setattr(adapter, "_request_control_api", apply_change)
    monkeypatch.setattr(adapter, "read_worker_configuration", read_configuration)

    result = adapter.update_worker_configuration(
        worker_id,
        before["configuration_version"],
        {"pickup_filter": pickup_filter},
        device_token="fixture-token",
    )

    assert "pickup_filter" not in result["configuration"]
    assert result["selection_policy"]["pickup_filter"] == pickup_filter
    assert slots.get_worker_slot(worker_id, path=path)["pickup_filter"] == pickup_filter


def test_edited_pickup_filter_preserves_owner_gate_and_explicit_user_route(tmp_path):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.change_worker_configuration(
        worker_id,
        snapshot["configuration_version"],
        {"pickup_filter": _valid_pickup_filter()},
        path=path,
    )
    slot = slots.get_worker_slot(worker_id, path=path)

    foreign_owner = {"category": "BACH", "priority": "P1", "assigned_to": "other-agent"}
    assert WorkerLeaseBinding._selection_rejection_reason(foreign_owner, slot) == "ownership"
    personal_unrouted = {"category": "BACH", "priority": "P1", "assigned_to": "user"}
    assert WorkerLeaseBinding._selection_rejection_reason(personal_unrouted, slot) == "ownership"
    explicit_user_route = {
        "category": "GUI", "priority": "P3", "assigned_to": "user", "assigned_slot": worker_id,
    }
    assert WorkerLeaseBinding._selection_rejection_reason(explicit_user_route, slot) is None


@pytest.mark.parametrize("pickup_filter", [
    None,
    [],
    {**_valid_pickup_filter(), "enabled": 1},
    {**_valid_pickup_filter(), "enabled": "true"},
    {"enabled": True},
    {**_valid_pickup_filter(), "categories": "BACH"},
    {**_valid_pickup_filter(), "categories": ("BACH",)},
    {**_valid_pickup_filter(), "priorities": [True]},
    {**_valid_pickup_filter(), "tags": ["x" * 101]},
    {**_valid_pickup_filter(), "exclude_tags": ["tag"] * 65},
    {**_valid_pickup_filter(), "categories": ["bad\x00value"]},
    {**_valid_pickup_filter(), "owner": "user"},
])
def test_invalid_pickup_filter_edit_leaves_file_unchanged(tmp_path, pickup_filter):
    from pathlib import Path

    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    before = Path(path).read_bytes()

    with pytest.raises(ValueError):
        slots.change_worker_configuration(
            worker_id,
            snapshot["configuration_version"],
            {"pickup_filter": pickup_filter},
            path=path,
        )

    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("authority_field,value", [
    ("assigned_to", "other-agent"),
    ("assigned_slot", "other-slot"),
    ("required_model", "remote-model"),
    ("require_assigned_slot", True),
])
def test_worker_configuration_cannot_edit_task_authority_fields(tmp_path, authority_field, value):
    from pathlib import Path

    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    before = Path(path).read_bytes()
    changes = {"pickup_filter": _valid_pickup_filter(), authority_field: value}

    with pytest.raises(ValueError):
        slots.change_worker_configuration(
            worker_id,
            snapshot["configuration_version"],
            changes,
            path=path,
        )

    assert Path(path).read_bytes() == before


def test_edit_uses_config_version_and_recomposes_role_prompt(tmp_path):
    path, worker_id = _worker(tmp_path)
    before = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.record_activity(worker_id, "Statusabfrage", path=path)
    assert slots.worker_configuration_snapshot(worker_id, path=path)["configuration_version"] == before["configuration_version"]
    result = slots.change_worker_configuration(worker_id, before["configuration_version"], {
        "sub_mode": "expert_role", "role_id": "entwickler", "max_tool_rounds": 0,
        "pause_basis": "tasks", "pause_after": 3, "pause_minutes": 2,
    }, path=path)
    assert result["configuration"]["role_id"] == "entwickler"
    assert result["configuration"]["max_tool_rounds"] == 0
    assert result["configuration_version"] != before["configuration_version"]
    assert slots.get_worker_slot(worker_id, path=path)["status"] == "idle"
    assert "Entwickler" in slots.get_worker_slot(worker_id, path=path)["system_prompt"]
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_worker_configuration(worker_id, before["configuration_version"], {"name": "Stale"}, path=path)


def test_worker_portrait_is_saved_and_projected_without_truncation(tmp_path):
    from gui.api.worker_status_adapter import _project_configuration, _project_worker
    path, worker_id = _worker(tmp_path)
    before = slots.worker_configuration_snapshot(worker_id, path=path)
    result = slots.change_worker_configuration(worker_id, before['configuration_version'],
        {'avatar': 'preset:guardian', 'symbol': 'server', 'allowed_tools': ['read_file'], 'skill_refs': []}, path=path)
    result['ok'] = True
    projected = _project_configuration(result, worker_id)
    assert projected['configuration']['avatar'] == 'preset:guardian'
    assert projected['configuration']['symbol'] == 'server'
    assert projected['configuration']['allowed_tools'] == ['read_file']
    public = _project_worker(slots.get_worker_slot(worker_id, path=path))
    assert public['avatar'] == 'preset:guardian' and public['symbol'] == 'server'


def test_uploaded_worker_image_survives_configuration_projection(tmp_path):
    import base64
    from gui.api.worker_status_adapter import _project_configuration
    path, worker_id = _worker(tmp_path)
    image = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'x' * 1000).decode()
    version = slots.worker_configuration_snapshot(worker_id, path=path)['configuration_version']
    result = slots.change_worker_configuration(worker_id, version, {'avatar': image}, path=path)
    assert _project_configuration({'ok': True, **result}, worker_id)['configuration']['avatar'] == image


def test_changed_skill_does_not_block_configuration_readback_but_still_blocks_execution(tmp_path, monkeypatch):
    from gui.api.worker_status_adapter import _project_configuration
    from hub._services import skill_source_service as source
    root = tmp_path / 'skills'
    target = root / 'example' / 'SKILL.md'
    target.parent.mkdir(parents=True)
    target.write_text('# Aktuelle Anleitung\n', encoding='utf-8')
    monkeypatch.setattr(source, 'skill_roots', lambda: [root])
    path, worker_id = _worker(tmp_path)
    pins = source.pin_skills(['example'])
    version = slots.worker_configuration_snapshot(worker_id, path=path)['configuration_version']
    slots.change_worker_configuration(worker_id, version, {'skill_refs': pins}, path=path)
    target.write_text('# Geänderte Anleitung\n', encoding='utf-8')
    saved = slots.worker_configuration_snapshot(worker_id, path=path)
    projected = _project_configuration({'ok': True, **saved}, worker_id)
    assert projected['configuration']['skill_refs'] == pins
    assert projected['skill_bindings'][0]['state'] == 'source_changed'
    with pytest.raises(RuntimeError, match='geändert'):
        slots.compose_worker_prompt(slots.get_worker_slot(worker_id, path=path))
    target.unlink()
    assert _project_configuration({'ok': True, **saved}, worker_id)['skill_bindings'][0]['state'] == 'missing'


@pytest.mark.parametrize("changes", [{"status": "running"}, {"allow_tools": "false"},
                                    {"max_tool_rounds": True}, {"sub_mode": "unknown"},
                                    {"role_id": "unknown", "sub_mode": "expert_role"}])
def test_invalid_edit_leaves_file_unchanged(tmp_path, changes):
    from pathlib import Path
    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    before = Path(path).read_bytes()
    with pytest.raises(ValueError):
        slots.change_worker_configuration(worker_id, snapshot["configuration_version"], changes, path=path)
    assert Path(path).read_bytes() == before


def test_running_worker_cannot_be_reconfigured(tmp_path):
    path, worker_id = _worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.update_slot(worker_id, {"status": "running"}, path=path)
    with pytest.raises(RuntimeError, match="worker_not_editable"):
        slots.change_worker_configuration(worker_id, snapshot["configuration_version"], {"model": "other"}, path=path)


def test_parallel_edits_have_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path, worker_id = _worker(tmp_path)
    version = slots.worker_configuration_snapshot(worker_id, path=path)["configuration_version"]
    def edit(name):
        try:
            slots.change_worker_configuration(worker_id, version, {"name": name}, path=path)
            return True
        except RuntimeError as error:
            assert str(error) == "configuration_version_conflict"
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(edit, ["Erster", "Zweiter"])) == 1


def test_expired_worker_edit_is_rejected(tmp_path):
    path, worker_id = _worker(tmp_path)
    slots.update_slot(worker_id, {"expires_at": "2020-01-01T00:00:00+00:00"}, path=path)
    version = slots.worker_configuration_snapshot(worker_id, path=path)["configuration_version"]
    with pytest.raises(RuntimeError, match="worker_not_editable"):
        slots.change_worker_configuration(worker_id, version, {"name": "Edited"}, path=path)
