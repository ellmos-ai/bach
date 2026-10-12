# SPDX-License-Identifier: MIT
"""P05 3b/3c: pinned governance references, global minimum contract and run binding; isolated state only."""
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from hub._services import blueprint_service as service
from hub._services import governance_binding as gb
from hub._services import policy_registry_adapter as adapter
from hub._services.chat import slots_config as slots

P1_SHA = "a" * 64
P2_SHA = "b" * 64


def entry(entry_id="P-001", version="1", sha=P1_SHA, **changes):
    return {"id": entry_id, "kind": "policy", "title": "Norm", "scope": "system-wide", "version": version,
            "privacy": "internal", "status": "active", "adoption": "adopted", "priority": 1, "precedence": 1,
            "source": {"uri": "/private/norm.md"}, "hash": {"algorithm": "sha256", "value": sha}, **changes}


def ref(entry_id="P-001", version="1", sha=P1_SHA, role="agent"):
    return {"registry": "policy-registry", "id": entry_id, "version": version, "sha256": sha, "role": role}


class Registry:
    """Stand-in for the pinned policy-registry package; observe() itself runs for real."""
    def __init__(self, path):
        self.path = path
        self.entries = [entry(), entry("P-002", sha=P2_SHA, kind="rule")]
        self.states = {}

    def search(self, **options):
        return list(self.entries)

    def verify(self):
        return {"checks": [{"id": e["id"], "state": self.states.get(e["id"], "ok")} for e in self.entries]}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text("{}")
    reg = Registry(path)
    monkeypatch.setattr(adapter, "_provider", lambda: reg)
    return reg


@pytest.fixture
def state(tmp_path, monkeypatch):
    from hub._services import skill_source_service

    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    resolved_target = Path(path).resolve()

    def fixture_lock_guard(target):
        if Path(target).resolve() != resolved_target:
            raise PermissionError("test lock guard denies paths outside the isolated config")

    # Only the fixture's exact temporary config is treated as known-unlocked.
    monkeypatch.setattr(skill_source_service, "check_write_locks", fixture_lock_guard)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    monkeypatch.setenv("BACH_GOVERNANCE_GLOBAL_FILE", str(tmp_path / "governance_global.json"))
    conn = sqlite3.connect(tmp_path / "blueprints.db")
    conn.row_factory = sqlite3.Row
    service.ensure_blueprint_schema(conn)
    yield conn
    conn.close()


def write_global(tmp_path, refs=(), forbidden=()):
    (tmp_path / "governance_global.json").write_text(json.dumps(
        {"schema": "bach.governance-global.v1", "policy_refs": list(refs), "forbidden_tools": list(forbidden)}),
        encoding="utf-8")


def save(state, name="githubbot", governance=None, expected_version=0, **changes):
    payload = {"name": name, "kind": "agent", "persona_role": "github-maintainer",
               "persona_prompt": "You are the GitHub maintenance agent.", "modus": "casualis",
               "governance": governance if governance is not None else {"profile": "read_only_research",
                                                                         "tool_whitelist": ["read_files"]},
               "expected_version": expected_version, **changes}
    return service.save_blueprint(state, payload)


def row(state, blueprint_id):
    return dict(state.execute("SELECT * FROM agent_blueprints WHERE id = ?", (blueprint_id,)).fetchone())


def saved_id(configured):
    return int(configured["slot_id"].rsplit("-", 1)[1])


def materialize(state, saved, **changes):
    return service.materialize_blueprint(state, saved["id"], expected_version=saved["version"],
        execution={"backend": "ollama", "model": "test-local", "mode": "full"},
        configuration_version=slots.core_system_agents_snapshot()["configuration_version"], **changes)


def start(state, saved, configured):
    execution = {"schema": "bach.worker-execution.v1", "worker_id": configured["slot_id"],
                 "worker_thread_started": True, "terminal": False, "state": "running"}
    dispatcher = Mock(return_value=execution)
    result = service.start_blueprint_worker(state, saved["id"], expected_version=saved["version"],
        configuration_version=configured["configuration_version"], dispatcher=dispatcher)
    return result, dispatcher


# --- positive paths -------------------------------------------------------------------------

def test_legacy_blueprint_runs_without_registry_and_is_marked_legacy(state, monkeypatch):
    monkeypatch.delenv("BACH_POLICY_REGISTRY_ENABLED", raising=False)  # no provider needed for legacy
    saved = save(state)
    configured = materialize(state, saved)
    binding = slots.get_system_slot(configured["slot_id"])["governance_binding"]
    assert binding["legacy"] is True and binding["refs"] == [] and binding["inherits"] == []
    assert configured["governance_binding"] == {"effective_sha256": binding["effective_sha256"],
                                                "refs": [], "legacy": True}
    result, dispatcher = start(state, saved, configured)
    assert result["is_running"] is True and dispatcher.call_count == 1


def test_pinned_refs_bind_with_recomputable_effective_sha256(state, registry):
    saved = save(state, governance={"profile": "read_only_research", "tool_whitelist": ["read_files"],
                                    "policy_refs": [ref(), ref("P-002", sha=P2_SHA, role="role")]})
    configured = materialize(state, saved)
    binding = slots.get_system_slot(configured["slot_id"])["governance_binding"]
    assert binding["legacy"] is False
    assert [(r["id"], r["role"]) for r in binding["refs"]] == [("P-002", "role"), ("P-001", "agent")]
    material = {key: binding[key] for key in binding if key != "effective_sha256"}
    expected = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    assert binding["effective_sha256"] == expected == configured["governance_binding"]["effective_sha256"]
    assert start(state, saved, configured)[0]["is_running"] is True


def test_hash_rule_is_canonical_utf8_json():
    value = {"b": "Ä", "a": [1, {"z": None}]}
    assert gb.canonical_sha256(value) == hashlib.sha256(
        '{"a":[1,{"z":null}],"b":"Ä"}'.encode("utf-8")).hexdigest()


# --- closed rejection at save -------------------------------------------------------------

@pytest.mark.parametrize("bad, code", [
    (ref("P-404"), "policy_ref_unknown"),
    (ref(sha="c" * 64), "policy_ref_hash_mismatch"),
    (ref(version="0"), "policy_ref_stale"),
    (ref(role="global"), "policy_ref_role_invalid"),
    (ref(role="boss"), "policy_ref_role_invalid"),
    ({**ref(), "registry": "other-registry"}, "policy_ref_invalid"),
    ({**ref(), "note": "x"}, "policy_ref_invalid"),
    ({**ref(), "sha256": "A" * 64}, "policy_ref_invalid"),
], ids=["unknown", "hash", "stale", "role-global", "role-unknown", "registry", "extra-field", "sha-format"])
def test_invalid_reference_is_rejected_and_nothing_is_saved(state, registry, bad, code):
    with pytest.raises(gb.GovernanceRejected, match=f"^{code}$"):
        save(state, governance={"policy_refs": [bad]})
    assert state.execute("SELECT count(*) FROM agent_blueprints").fetchone()[0] == 0


@pytest.mark.parametrize("state_name, code", [("hash-mismatch", "policy_ref_unverified"),
    ("remote-unchecked", "policy_ref_unverified"), ("missing", "policy_ref_unverified")])
def test_reference_whose_source_does_not_verify_is_rejected(state, registry, state_name, code):
    registry.states["P-001"] = state_name
    with pytest.raises(gb.GovernanceRejected, match=f"^{code}$"):
        save(state, governance={"policy_refs": [ref()]})


@pytest.mark.parametrize("changes", [{"adoption": "pending"}, {"status": "revoked"}, {"kind": "evidence"}])
def test_reference_to_a_non_binding_entry_is_rejected(state, registry, changes):
    registry.entries[0] = entry(**changes)
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_not_binding$"):
        save(state, governance={"policy_refs": [ref()]})


def test_references_without_configured_provider_fail_closed(state, monkeypatch):
    monkeypatch.delenv("BACH_POLICY_REGISTRY_ENABLED", raising=False)
    with pytest.raises(gb.GovernanceRejected, match="^policy_provider_unavailable$"):
        save(state, governance={"policy_refs": [ref()]})


# --- pin semantics: no silent change, explicit logged migration ---------------------------

def test_newer_policy_version_rejects_run_until_explicit_logged_migration(state, registry):
    saved = save(state, governance={"policy_refs": [ref()]})
    configured = materialize(state, saved)
    registry.entries[0] = entry(version="2", sha="d" * 64)  # registry moved on
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_stale$"):
        start(state, saved, configured)
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_stale$"):
        materialize(state, saved, terminal_verified=True)
    # Same version, different content: integrity break, also closed.
    registry.entries[0] = entry(sha="e" * 64)
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_hash_mismatch$"):
        start(state, saved, configured)
    # Explicit migration: save with the new pin (CAS) and re-materialize; the server logs it.
    registry.entries[0] = entry(version="2", sha="d" * 64)
    migrated = save(state, governance={"policy_refs": [ref(version="2", sha="d" * 64)],
                                       "pin_log": [{"forged": True}]}, expected_version=saved["version"])
    governance = json.loads(row(state, saved["id"])["governance_json"])
    assert [item["changed"] for item in governance["pin_log"]] == [["P-001"], ["P-001"]]
    assert governance["pin_log"][-1]["blueprint_version"] == migrated["version"]
    assert {"forged": True} not in governance["pin_log"]
    reconfigured = materialize(state, migrated, terminal_verified=True)
    assert reconfigured["governance_binding"]["refs"][0]["version"] == "2"
    assert start(state, migrated, reconfigured)[0]["is_running"] is True


# --- global minimum contract over all layers ----------------------------------------------

def test_global_prohibition_cannot_be_relaxed_by_role_or_agent_layer(state, registry, tmp_path):
    write_global(tmp_path, refs=[ref(role="global")], forbidden=["web_fetch"])
    with pytest.raises(gb.GovernanceRejected, match="^governance_global_violation$"):
        save(state, governance={"profile": "full_dev_guarded", "tool_whitelist": ["read_files", "web_fetch"],
                                "policy_refs": [ref("P-002", sha=P2_SHA)]})
    with pytest.raises(gb.GovernanceRejected, match="^governance_global_violation$"):
        save(state, governance={"policy_refs": [ref(version="0", sha="f" * 64, role="role")]})
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_role_invalid$"):
        save(state, governance={"policy_refs": [ref(role="global")]})
    saved = save(state, governance={"tool_whitelist": ["read_files"], "policy_refs": [ref()]})
    configured = materialize(state, saved)
    binding = slots.get_system_slot(configured["slot_id"])["governance_binding"]
    assert [(r["id"], r["role"]) for r in binding["refs"]] == [("P-001", "global")]
    # A later slot edit (agent override) that grants the forbidden tool is refused at run.
    slots.change_core_system_agent(configured["slot_id"], configured["configuration_version"],
                                   {"allowed_tools": ["read_file", "web_fetch"]})
    edited = {**configured, "configuration_version": slots.core_system_agents_snapshot()["configuration_version"]}
    with pytest.raises(gb.GovernanceRejected, match="^governance_global_violation$"):
        start(state, saved, edited)


def test_changed_global_contract_rejects_bound_agents_until_rematerialized(state, registry, tmp_path):
    saved = save(state)
    configured = materialize(state, saved)
    write_global(tmp_path, refs=[ref(role="global")])
    with pytest.raises(gb.GovernanceRejected, match="^governance_global_changed$"):
        start(state, saved, configured)
    reconfigured = materialize(state, saved, terminal_verified=True)
    assert reconfigured["governance_binding"]["refs"][0]["role"] == "global"
    assert reconfigured["governance_binding"]["legacy"] is True
    assert start(state, saved, reconfigured)[0]["is_running"] is True


def test_invalid_global_contract_fails_closed(state, tmp_path):
    (tmp_path / "governance_global.json").write_text('{"schema": "bach.governance-global.v1"}')
    with pytest.raises(gb.GovernanceRejected, match="^governance_global_invalid$"):
        save(state)


def test_slot_materialized_before_3b_stays_legacy_but_global_ban_applies(state, tmp_path):
    saved = save(state, governance={"tool_whitelist": ["read_files", "web_fetch"]})
    configured = materialize(state, saved)
    raw = json.loads(open(slots.DEFAULT_SLOTS_FILE, encoding="utf-8").read())
    raw["slots"][configured["slot_id"]].pop("governance_binding")
    slots.save_slots_config(raw, slots.DEFAULT_SLOTS_FILE)
    current = {**configured, "configuration_version": slots.core_system_agents_snapshot()["configuration_version"]}
    assert start(state, saved, current)[0]["is_running"] is True
    write_global(tmp_path, forbidden=["web_fetch"])
    with pytest.raises(gb.GovernanceRejected, match="^governance_global_violation$"):
        start(state, saved, current)


def test_client_cannot_write_the_pin_log(state):
    saved = save(state, governance={"tool_whitelist": ["read_files"], "pin_log": [{"forged": True}]})
    assert "pin_log" not in json.loads(row(state, saved["id"])["governance_json"])


@pytest.mark.parametrize("field, value", [("governance_binding", {"legacy": True}),
    ("governance_binding", None), ("blueprint_id", None), ("blueprint_version", 99)])
def test_binding_is_owned_by_materialize_and_survives_slot_edits(state, registry, field, value):
    configured = materialize(state, save(state, governance={"policy_refs": [ref()]}))
    slot_id = configured["slot_id"]
    before = slots.get_system_slot(slot_id)["governance_binding"]
    with pytest.raises(ValueError):  # core editor (GUI)
        slots.change_core_system_agent(slot_id, configured["configuration_version"], {field: value})
    with pytest.raises(ValueError):  # generic POST /api/slots
        slots.update_slot(slot_id, {field: value, "model": "other"})
    # Regular edits through every slot editor keep the binding byte-identical.
    slots.update_slot(slot_id, {"model": "other-model", "status": "idle"})
    version = slots.core_system_agents_snapshot()["configuration_version"]
    slots.change_core_system_agent(slot_id, version, {"description": "edited", "max_tool_rounds": 7})
    version = slots.core_system_agents_snapshot()["configuration_version"]
    slots.change_core_system_agent(slot_id, version, reset=True)
    after = slots.get_system_slot(slot_id)
    assert after["governance_binding"] == before and after["blueprint_id"] == saved_id(configured)


# Herkunft: Review R14 (Sonnet 5.5) zu #347; ein abgewiesenes Update lässt den Slot vollständig unverändert.
@pytest.mark.parametrize("field,value", [("governance_binding", None), ("governance_binding", {"legacy": True}),
                                         ("blueprint_id", None), ("blueprint_version", 99)])
def test_generic_slot_update_cannot_touch_binding_or_blueprint_link(state, registry, field, value):
    configured = materialize(state, save(state, governance={"policy_refs": [ref()]}))
    before = slots.get_system_slot(configured["slot_id"])
    with pytest.raises(ValueError):
        slots.update_slot(configured["slot_id"], {field: value})
    assert slots.get_system_slot(configured["slot_id"]) == before
    slots.update_slot(configured["slot_id"], {"current_activity": "x"})  # normal updates still work
    assert slots.get_system_slot(configured["slot_id"])["governance_binding"] == before["governance_binding"]


# --- inheritance ---------------------------------------------------------------------------

def test_inherits_from_narrows_tools_carries_refs_and_pins_the_parent(state, registry):
    parent = save(state, name="maintainer-base", governance={
        "profile": "read_only_research", "tool_whitelist": ["read_files"], "policy_refs": [ref(role="role")]})
    pin = {"blueprint_id": parent["id"], "version": parent["version"],
           "sha256": gb.blueprint_sha256(row(state, parent["id"]))}
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_override$"):
        save(state, name="child", governance={"inherits_from": pin, "policy_refs": [ref(version="0", sha="9" * 64)]})
    child = save(state, name="child", governance={
        "profile": "full_dev_guarded", "tool_whitelist": ["read_files", "write_files"], "inherits_from": pin,
        "policy_refs": [ref("P-002", sha=P2_SHA)]})
    configured = materialize(state, child)
    slot = slots.get_system_slot(configured["slot_id"])
    assert slot["allowed_tools"] == ["list_directory", "read_file"] and slot["mode"] == "safe"
    assert slot["governance_binding"]["inherits"] == [pin]
    assert [r["id"] for r in slot["governance_binding"]["refs"]] == ["P-001", "P-002"]
    save(state, name="maintainer-base", governance={"profile": "read_only_research"},
         expected_version=parent["version"])
    with pytest.raises(gb.GovernanceRejected, match="^inherits_from_stale$"):
        start(state, child, configured)


@pytest.mark.parametrize("mutate, code", [
    (lambda pin: {**pin, "blueprint_id": 999}, "inherits_from_unknown"),
    (lambda pin: {**pin, "sha256": "0" * 64}, "inherits_from_hash_mismatch"),
    (lambda pin: {**pin, "version": 7}, "inherits_from_stale"),
    (lambda pin: {**pin, "version": "1"}, "inherits_from_invalid"),
])
def test_unresolvable_parent_pin_is_rejected(state, mutate, code):
    parent = save(state, name="base")
    pin = {"blueprint_id": parent["id"], "version": 1, "sha256": gb.blueprint_sha256(row(state, parent["id"]))}
    with pytest.raises(gb.GovernanceRejected, match=f"^{code}$"):
        save(state, name="child", governance={"inherits_from": mutate(pin)})


def test_inheritance_cycle_is_rejected(state):
    first = save(state, name="first")
    pin = {"blueprint_id": first["id"], "version": 1, "sha256": gb.blueprint_sha256(row(state, first["id"]))}
    second = save(state, name="second", governance={"inherits_from": pin})
    back = {"blueprint_id": second["id"], "version": 1, "sha256": gb.blueprint_sha256(row(state, second["id"]))}
    with pytest.raises(gb.GovernanceRejected, match="^inherits_from_cycle$"):
        save(state, name="first", governance={"inherits_from": back}, expected_version=1)


def test_list_exposes_content_sha256_for_pinning(state):
    saved = save(state)
    listed = service.list_blueprints(state)
    item = next(b for b in listed["blueprints"] if b["id"] == saved["id"])
    assert item["content_sha256"] == gb.blueprint_sha256(row(state, saved["id"]))


# --- 3c: controller run receipt (bach.worker-execution.v1, additive fields) ---------------

@pytest.fixture
def controller(state, monkeypatch):
    import importlib
    from hub._services.chat.chat_runtime import ChatSession
    control = importlib.import_module("hub._services.chat.telegram_chat")
    for name in ("_WORKER_CONTROLS", "_ACTIVE_WORKER_THREADS", "_WORKER_EXECUTIONS"):
        monkeypatch.setattr(control, name, {}, raising=False)
    monkeypatch.setattr(control, "record_activity", lambda *args, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *args, **kw: (object(), "test-local"))
    monkeypatch.setattr(control, "_acquire_worker_task", lambda *args: None)
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: ChatSession())
    monkeypatch.setattr(control, "finish_assignment", lambda *args, **kw: None)
    assignments = []
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: assignments.append(kw) or kw)
    monkeypatch.setattr(control, "assignments", assignments, raising=False)
    return control


def run(control, slot_id, request_id):
    response, status = control.start_worker_execution(slot_id, start_request_id=request_id)
    execution = control._WORKER_EXECUTIONS.get(slot_id)
    if execution is not None and hasattr(execution.thread, "join"):
        execution.thread.join(5)
    return response, status


def test_controller_receipt_carries_governance_and_model_binding(state, registry, controller):
    saved = save(state, governance={"policy_refs": [ref()]})
    configured = materialize(state, saved)
    binding = slots.get_system_slot(configured["slot_id"])["governance_binding"]
    response, status = run(controller, configured["slot_id"], "1" * 32)
    assert status == 200, response
    receipt = controller.worker_execution_receipt(configured["slot_id"], "1" * 32)
    assert receipt["schema"] == "bach.worker-execution.v1"
    assert receipt["governance_binding"] == {"effective_sha256": binding["effective_sha256"],
                                             "refs": binding["refs"], "legacy": False}
    assert receipt["model_binding"] == {"chain_index": 0, "backend": "ollama", "model": "test-local",
                                        "switch_reason": None}


def test_controller_marks_legacy_run_in_receipt(state, controller):
    configured = materialize(state, save(state))
    response, status = run(controller, configured["slot_id"], "2" * 32)
    assert status == 200, response
    receipt = controller.worker_execution_receipt(configured["slot_id"], "2" * 32)
    assert receipt["governance_binding"]["legacy"] is True
    assert len(receipt["governance_binding"]["effective_sha256"]) == 64


def test_controller_refuses_stale_pin_on_direct_worker_start(state, registry, controller):
    configured = materialize(state, save(state, governance={"policy_refs": [ref()]}))
    registry.entries[0] = entry(version="2", sha="d" * 64)
    response, status = run(controller, configured["slot_id"], "3" * 32)
    # Same rejection path as changed skill_refs: the admission is not confirmed, nothing runs.
    assert status == 503 and response["execution"]["error_code"] == "admission_unconfirmed"
    assert controller.assignments == []  # no assignment, no worker thread
    assert response["execution"]["worker_thread_started"] is not True


def test_controller_refuses_manipulated_binding_on_direct_worker_start(state, registry, controller):
    configured = materialize(state, save(state, governance={"policy_refs": [ref()]}))
    raw = json.loads(open(slots.DEFAULT_SLOTS_FILE, encoding="utf-8").read())
    raw["slots"][configured["slot_id"]]["governance_binding"]["refs"][0]["version"] = "0"  # hash not updated
    slots.save_slots_config(raw, slots.DEFAULT_SLOTS_FILE)
    response, status = run(controller, configured["slot_id"], "4" * 32)
    assert status == 503 and controller.assignments == []
    with pytest.raises(gb.GovernanceRejected, match="^governance_binding_invalid$"):
        gb.verify_run(raw["slots"][configured["slot_id"]]["governance_binding"], [])


def test_policy_reader_rechecks_during_a_run(state, registry, controller, monkeypatch):
    configured = materialize(state, save(state, governance={"policy_refs": [ref()]}))
    reader = controller._execution_slot_reader(slots.get_system_slot(configured["slot_id"]))
    assert reader()["id"] == configured["slot_id"]  # admission read verifies
    registry.entries[0] = entry(version="2", sha="d" * 64)
    assert reader()["id"] == configured["slot_id"]  # inside the window: no new registry read
    monkeypatch.setattr(gb, "RUN_RECHECK_SECONDS", 0.0)
    with pytest.raises(gb.GovernanceRejected, match="^policy_ref_stale$"):
        reader()


def test_adapter_projection_keeps_the_binding_fields(monkeypatch):
    from gui.api import worker_status_adapter as status_adapter
    worker_id, version, request, instance = "system-blueprint-17", "a" * 64, "b" * 32, "c" * 32
    receipt = {"schema": "bach.worker-execution.v1", "worker_id": worker_id, "start_request_id": request,
               "service_instance": instance, "generation": "d" * 32, "state": "running", "terminal": False,
               "worker_thread_started": True, "governance_binding": {"effective_sha256": "e" * 64, "refs": [],
               "legacy": True}, "model_binding": {"chain_index": 0, "backend": "ollama", "model": "m",
               "switch_reason": None}}
    responses = iter([{"configuration_version": version, "service_instance": instance,
        "agents": [{"id": worker_id, "enabled": True, "execution_kind": "worker"}]}, {"available": True},
        {"ok": True}, {"ok": True, "execution": receipt}])
    monkeypatch.setattr(status_adapter, "_request_control_api", lambda *a, **kw: next(responses))
    projected = status_adapter.dispatch_blueprint_worker(worker_id, version, device_token="t",
                                                         start_request_id=request)
    assert projected["governance_binding"] == receipt["governance_binding"]
    assert projected["model_binding"] == receipt["model_binding"]
