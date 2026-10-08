"""Typed task routing: honest liveness, source revisions, no implicit starts."""
import pytest
from fastapi import HTTPException
from gui.api import task_assignment as api


def slot(**changes):
    return {"id": "buddha_research", "name": "Recherche", "execution_kind": "worker",
            "model": "test-model", "backend": "ollama", "enabled": True, "living": True,
            "running": False, "runtime_verified": True, "allow_tools": True,
            "allowed_tools": ["task_manage"], **changes}


def snapshot(*items):
    return {"configuration_version": "a" * 64, "agents": list(items)}


def blueprints(**changes):
    return {"configuration_version": "a" * 64, "templates": [], "blueprints": [], **changes}


def test_ready_native_slot_has_canonical_binding():
    result = api.project_targets(snapshot(slot()), blueprints())
    assert result["schema"] == "bach.task-assignees.v1"
    target = result["targets"][0]
    assert target["assignable"] is True and target["running"] is False
    assert target["binding"] == {"assigned_slot": "buddha_research", "assigned_to": "OLLAMA", "required_model": "test-model"}


@pytest.mark.parametrize("change,reason", [({"runtime_verified": False}, "runtime_not_verified"),
    ({"enabled": False}, "disabled"), ({"living": False}, "worker_not_ready"),
    ({"execution_kind": "chat"}, "not_task_worker"), ({"allowed_tools": []}, "task_tool_unavailable")])
def test_unavailable_destinations_are_not_ready(change, reason):
    item = api.project_targets(snapshot(slot(**change)), blueprints())["targets"][0]
    assert item["assignable"] is False and item["reason"] == reason


def test_private_sequence_slots_and_empty_catalog_do_not_claim_availability():
    result = api.project_targets(snapshot(slot(sequence_run_id="private-run")), blueprints())
    assert result["targets"] == [] and result["runtime_verified"] is False


def test_blueprint_requires_current_instance_and_does_not_materialize():
    bp = {"id": 7, "name": "expert", "title": "Experte", "kind": "agent", "version": 2}
    result = api.project_targets(snapshot(slot(blueprint_id=7, blueprint_version=1)),
        blueprints(blueprints=[{**bp, "instance": {"id": "buddha_research"}}]))
    assert result["targets"][-1]["assignable"] is False
    assert result["targets"][-1]["reason"] == "blueprint_requires_instance"
    result = api.project_targets(snapshot(slot(blueprint_id=7, blueprint_version=2)),
        blueprints(blueprints=[{**bp, "instance": {"id": "buddha_research"}}]))
    assert result["targets"][-1]["assignable"] is True


def test_mixed_configuration_snapshots_are_rejected():
    with pytest.raises(HTTPException) as exc:
        api.project_targets(snapshot(slot()), blueprints(configuration_version="b" * 64))
    assert exc.value.status_code == 409


@pytest.fixture
def configured(monkeypatch):
    from gui.api import core_system_agents
    monkeypatch.setattr(core_system_agents, "_snapshot", lambda: snapshot(slot()))


def test_assignment_validates_revision_model_backend_and_slot(configured):
    valid = {"assigned_slot": "buddha_research", "assigned_to": "OLLAMA", "required_model": "test-model",
             "assignment_configuration_version": "a" * 64}
    api.validate_assignment(valid)
    for change in ({"assignment_configuration_version": "b" * 64}, {"required_model": "other"},
                   {"assigned_to": "openrouter"}, {"assigned_slot": "unknown"}):
        with pytest.raises(HTTPException): api.validate_assignment({**valid, **change})


def test_existing_assignment_is_retained_on_unrelated_edits(configured):
    api.validate_assignment({"title": "Neuer Titel"}, {"assigned_slot": "unavailable-legacy"})
    api.validate_assignment({"assigned_slot": "unavailable-legacy", "title": "Neuer Titel"}, {"assigned_slot": "unavailable-legacy"})
    api.validate_assignment({"assigned_slot": None, "assignment_configuration_version": "a" * 64}, {"assigned_slot": "unavailable-legacy"})


@pytest.mark.parametrize("payload,existing", [({"assigned_slot": "buddha_research"}, {}),
    ({"assigned_slot": None}, {"assigned_slot": "unavailable-legacy"}),
    ({"required_model": "other"}, {"assigned_slot": "buddha_research"})])
def test_native_binding_change_requires_cas(payload, existing):
    with pytest.raises(HTTPException) as denied: api.validate_assignment(payload, existing)
    assert denied.value.status_code == 400


def test_configuration_change_between_probe_and_commit_is_rejected(configured, monkeypatch):
    from contextlib import contextmanager
    from hub._services.chat import slots_config
    @contextmanager
    def transaction(): yield lambda: pytest.fail("must not advance configuration")
    monkeypatch.setattr(slots_config, "worker_admission_transaction", transaction)
    monkeypatch.setattr(slots_config, "core_system_agents_snapshot", lambda: {"configuration_version": "b" * 64})
    with pytest.raises(HTTPException) as denied:
        with api.assignment_write_guard({"assigned_slot": "buddha_research", "assignment_configuration_version": "a" * 64}):
            pytest.fail("must not write task")
    assert denied.value.status_code == 409


def test_stopped_runtime_is_rejected_even_when_configuration_is_current(monkeypatch):
    from gui.api import core_system_agents
    monkeypatch.setattr(core_system_agents, "_snapshot", lambda: snapshot(slot(living=False)))
    with pytest.raises(HTTPException) as denied:
        api.validate_assignment({"assigned_slot": "buddha_research", "assignment_configuration_version": "a" * 64})
    assert denied.value.status_code == 422
