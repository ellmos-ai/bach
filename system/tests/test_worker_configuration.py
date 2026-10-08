import pytest
from hub._services.chat import slots_config as slots


def _worker(tmp_path):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    worker = slots.add_worker({"name": "Worker", "backend": "ollama", "model": "test",
                               "sub_mode": "hintergrund_worker"}, path=path)
    return path, worker["id"]


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
