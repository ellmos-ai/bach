"""Dynamic destinations use native profile authority and the global CAS."""
import copy
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gui.api import task_assignment as api
from hub._services.chat import slots_config as slots


@pytest.fixture
def configured_profiles(monkeypatch, tmp_path):
    path = tmp_path / "slots.json"
    monkeypatch.setattr(slots, "_resolve_path", lambda unused=None: path)
    config = slots._fresh_slots_config()
    profile = {"id": "worker-free", "name": "Free", "backend": "openrouter",
               "model": "openrouter/free", "status": "running", "allow_tools": True,
               "allowed_tools": ["task_manage"], "task_prompt": "private prompt",
               "expires_at": None}
    config["dynamic_workers"] = [profile]

    def save():
        path.write_text(json.dumps(config), encoding="utf-8")

    save()
    observed = {"id": profile["id"], "backend": "openrouter", "model": "openrouter/free",
                "status": "running", "runtime_verified": True, "running": False}

    def live(**kwargs):
        return {"availability": "available", "source": "authenticated_local_control_api",
                "workers": [copy.deepcopy(observed)]}

    from gui.api import worker_status_adapter, core_system_agents
    monkeypatch.setattr(worker_status_adapter, "read_worker_status", live)
    monkeypatch.setattr(core_system_agents, "_snapshot", slots.core_system_agents_snapshot)
    return config, profile, observed, save, path


def destinations():
    core = slots.core_system_agents_snapshot()
    profiles = api.dynamic_worker_snapshot(core)
    catalog = api.project_targets(core, {"configuration_version": core["configuration_version"]}, profiles)
    return catalog, next(t for t in catalog["targets"] if t["id"] == "worker:worker-free")


def test_profile_catalog_and_assignment_bind_native_identity(configured_profiles):
    _, _, _, _, path = configured_profiles
    before = path.read_bytes()
    catalog, target = destinations()
    assert target["type"] == "worker-profile" and target["assignable"] is True
    assert target["running"] is False and target["living"] is True
    assert target["binding"] == {"assigned_slot": "worker-free", "assigned_to": "OPENROUTER",
                                  "required_model": "openrouter/free"}
    payload = {**target["binding"], "assignment_configuration_version": catalog["configuration_version"]}
    assert api.validate_assignment(payload) == catalog["configuration_version"]
    with api.assignment_write_guard(payload):
        assert path.read_bytes() == before
    assert path.read_bytes() == before  # Routing neither starts a worker nor advances admission.
    assert "private prompt" not in json.dumps(catalog)


@pytest.mark.parametrize("status", ["paused", "error", "expired", "stopping"])
def test_unavailable_lifecycle_is_not_assignable(configured_profiles, status):
    _, profile, observed, save, _ = configured_profiles
    profile["status"] = observed["status"] = status
    save()
    catalog, target = destinations()
    assert target["assignable"] is False
    with pytest.raises(HTTPException) as exc:
        api.validate_assignment({**target["binding"], "assignment_configuration_version": catalog["configuration_version"]})
    assert exc.value.status_code == 422


@pytest.mark.parametrize("changes", [{"allow_tools": False}, {"allowed_tools": []},
    {"expires_at": "2000-01-01T00:00:00+00:00"}, {"expires_at": "invalid"},
    {"expires_at": "2100-01-01T00:00:00"}, {"sequence_run_id": "private-run"}])
def test_tools_expiry_and_private_execution_are_enforced(configured_profiles, changes):
    _, profile, _, save, _ = configured_profiles
    profile.update(changes)
    save()
    core = slots.core_system_agents_snapshot()
    catalog = api.project_targets(core, {"configuration_version": core["configuration_version"]},
                                  api.dynamic_worker_snapshot(core))
    target = next((t for t in catalog["targets"] if t["id"] == "worker:worker-free"), None)
    assert target is None or target["assignable"] is False


@pytest.mark.parametrize("changes", [{"runtime_verified": False}, {"model": "paid-model"},
                                    {"backend": "ollama"}])
def test_unverified_or_mismatched_observation_is_not_authority(configured_profiles, changes):
    _, _, observed, _, _ = configured_profiles
    observed.update(changes)
    assert destinations()[1]["assignable"] is False


def test_control_unavailable_remains_unknown(configured_profiles, monkeypatch):
    from gui.api import worker_status_adapter

    def unavailable(**kwargs):
        raise worker_status_adapter.WorkerStatusUnavailable("not available")

    monkeypatch.setattr(worker_status_adapter, "read_worker_status", unavailable)
    target = destinations()[1]
    assert target["assignable"] is False and target["runtime_verified"] is False
    assert target["reason"] == "runtime_not_verified"


def test_configuration_change_during_probe_rejects_catalog(configured_profiles, monkeypatch):
    _, profile, _, save, _ = configured_profiles
    core = slots.core_system_agents_snapshot()
    from gui.api import worker_status_adapter

    def changed(**kwargs):
        profile["model"] = "changed-model"
        save()
        return {"availability": "available", "source": "authenticated_local_control_api", "workers": []}

    monkeypatch.setattr(worker_status_adapter, "read_worker_status", changed)
    with pytest.raises(HTTPException) as exc:
        api.dynamic_worker_snapshot(core)
    assert exc.value.status_code == 409


def test_configuration_change_before_task_commit_rejects_write(configured_profiles, monkeypatch):
    _, profile, _, save, _ = configured_profiles
    catalog, target = destinations()
    actual_transaction = slots.worker_admission_transaction

    @contextmanager
    def changed_transaction():
        profile["allow_tools"] = False
        save()
        with actual_transaction() as advance:
            yield advance

    monkeypatch.setattr(slots, "worker_admission_transaction", changed_transaction)
    with pytest.raises(HTTPException) as exc:
        with api.assignment_write_guard({**target["binding"],
                                        "assignment_configuration_version": catalog["configuration_version"]}):
            pytest.fail("must not commit task")
    assert exc.value.status_code == 409


def test_duplicate_profile_identity_fails_closed(configured_profiles):
    config, profile, _, save, _ = configured_profiles
    config["dynamic_workers"].append(dict(profile))
    save()
    with pytest.raises(HTTPException) as exc:
        api.dynamic_worker_snapshot(slots.core_system_agents_snapshot())
    assert exc.value.status_code == 503


@pytest.mark.parametrize("with_profile", [False, True])
def test_valid_legacy_defaults_are_not_normalized_before_cas(configured_profiles, with_profile):
    config, _, _, save, path = configured_profiles
    config["version"] = 1
    config["slots"] = {ident: value for ident, value in config["slots"].items()
                       if ident in slots.REQUIRED_CORE_SYSTEM_AGENT_IDS}
    for slot in config["slots"].values():
        for field in ("pause_after", "pause_minutes", "pause_basis", "pause_counter",
                      "pause_started_at", "pickup_filter"):
            slot.pop(field, None)
    if not with_profile:
        config.pop("dynamic_workers")
    save()
    before = path.read_bytes()
    core = slots.core_system_agents_snapshot()
    profiles = api.dynamic_worker_snapshot(core)
    assert profiles["configuration_version"] == core["configuration_version"]
    if with_profile:
        catalog, target = destinations()
        with api.assignment_write_guard({**target["binding"],
                                        "assignment_configuration_version": catalog["configuration_version"]}):
            pass
    else:
        assert profiles["agents"] == []
    assert path.read_bytes() == before


def test_expiry_crossing_commit_boundary_is_rejected_without_config_change(configured_profiles, monkeypatch):
    _, profile, _, save, path = configured_profiles
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    clock = {"now": now}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(api, "datetime", Clock)
    profile["expires_at"] = (now + timedelta(seconds=1)).isoformat()
    save()
    catalog, target = destinations()
    before = path.read_bytes()
    actual_transaction = slots.worker_admission_transaction

    @contextmanager
    def clock_advanced():
        clock["now"] = now + timedelta(seconds=2)
        with actual_transaction() as advance:
            yield advance

    monkeypatch.setattr(slots, "worker_admission_transaction", clock_advanced)
    with pytest.raises(HTTPException) as exc:
        with api.assignment_write_guard({**target["binding"],
                                        "assignment_configuration_version": catalog["configuration_version"]}):
            pytest.fail("must not commit expired profile")
    assert exc.value.status_code == 422 and path.read_bytes() == before


@pytest.fixture
def task_http(configured_profiles, tmp_path, monkeypatch):
    """Real HTTP handlers and transactions, isolated DB and runtime observation."""
    from gui import server
    from gui.api import unified_api

    path = tmp_path / "tasks.db"
    schema = Path(__file__).resolve().parents[1] / "data/schema/schema.sql"
    with sqlite3.connect(path) as conn:
        conn.executescript(schema.read_text(encoding="utf-8"))

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    async def blueprints():
        return {"configuration_version": slots.core_system_agents_snapshot()["configuration_version"],
                "templates": [], "blueprints": []}

    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "has_active_devices", lambda: True)
    monkeypatch.setattr(server, "validate_token", lambda token: {"device_id": "fixture"})
    monkeypatch.setattr(unified_api, "list_agent_blueprints", blueprints)
    # Do not run the full application's service startup/lifespan in a fixture.
    client = TestClient(server.app, headers={"Authorization": "Bearer test-fixture"})
    try:
        yield client, path
    finally:
        client.close()


def test_http_catalog_create_update_and_lease_boundary(task_http, configured_profiles):
    client, _ = task_http
    _, profile, _, save, config_path = configured_profiles
    config_before = config_path.read_bytes()
    response = client.get("/api/task-assignees")
    assert response.status_code == 200
    catalog = response.json()
    target = next(t for t in catalog["targets"] if t["type"] == "worker-profile")
    binding = {**target["binding"], "assignment_configuration_version": catalog["configuration_version"]}
    created = client.post("/api/tasks", json={"title": "Fixture task", **binding})
    assert created.status_code == 200 and created.json()["success"] is True, created.text
    ident = created.json()["id"]
    row = client.get(f"/api/tasks/{ident}").json()
    assert {k: row[k] for k in target["binding"]} == target["binding"]
    assert client.get(f"/api/tasks/{ident}/lease").json()["leased"] is False
    assert config_path.read_bytes() == config_before

    # An actual config edit invalidates a previously selected write.
    profile["name"] = "Renamed"
    save()
    stale = client.put(f"/api/tasks/{ident}", json={"assigned_slot": None,
                                                "assignment_configuration_version": catalog["configuration_version"]})
    assert stale.status_code == 409
    assert client.get(f"/api/tasks/{ident}").json()["assigned_slot"] == "worker-free"

    fresh = client.get("/api/task-assignees").json()
    changed = client.put(f"/api/tasks/{ident}", json={"assigned_slot": None,
                        "assignment_configuration_version": fresh["configuration_version"]})
    assert changed.status_code == 200 and changed.json().get("status") == "updated", changed.text
    assert client.get(f"/api/tasks/{ident}").json()["assigned_slot"] is None


def test_http_stale_catalog_cannot_create_task(task_http, configured_profiles):
    client, path = task_http
    _, profile, _, save, _ = configured_profiles
    catalog, target = destinations()
    profile["status"] = "paused"
    save()
    response = client.post("/api/tasks", json={"title": "Must not exist", **target["binding"],
                            "assignment_configuration_version": catalog["configuration_version"]})
    assert response.status_code == 409
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
