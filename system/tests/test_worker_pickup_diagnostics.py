"""Selection explanations preserve the existing authority and filter semantics."""
import copy

import pytest
from gui.api.worker_status_adapter import (
    WorkerStatusUnavailable,
    _project_configuration,
)
from hub._services.chat.slots_config import (
    _worker_configuration,
    match_task_to_pickup_filter,
    pickup_filter_rejection,
)
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.chat.worker_queue_status import (
    project_selection_policy,
    queue_waiting_activity,
    worker_selection_policy,
)


def _slot():
    return {"id": "our-slot", "model": "openrouter/free", "pickup_filter": {
        "enabled": True, "categories": ["WORKER"], "priorities": ["P1", "P2"],
        "tags": ["ready", "safe"], "exclude_tags": ["waiting", "delegated"],
    }}


@pytest.mark.parametrize("categories", [
    {"category": " worker "}, {"project": "WORKER"}, {"categories": "GUI,WORKER"},
    {"categories": ["GUI", "WORKER"]},
])
def test_category_sources_and_positive_tags_are_alternatives(categories):
    task = {**categories, "priority": "p2", "tags": ["SAFE", "other"]}
    assert pickup_filter_rejection(task, _slot()) is None
    assert match_task_to_pickup_filter(task, _slot())
    assert WorkerLeaseBinding._selection_rejection_reason(task, _slot()) is None


@pytest.mark.parametrize("changes,reason", [
    ({"category": "GUI"}, "pickup_category"),
    ({"priority": "P3"}, "pickup_priority"),
    ({"tags": "other"}, "pickup_tags"),
    ({"tags": "safe,waiting"}, "excluded_tag"),
])
def test_one_decision_produces_the_same_boolean_and_reason(changes, reason):
    task = {"category": "WORKER", "priority": "P2", "tags": "safe", **changes}
    assert pickup_filter_rejection(task, _slot()) == reason
    assert not match_task_to_pickup_filter(task, _slot())
    assert WorkerLeaseBinding._selection_rejection_reason(task, _slot()) == reason


def test_explicit_routing_still_obeys_tags_and_model():
    task = {"assigned_slot": "our-slot", "category": "GUI", "priority": "P3", "tags": "safe"}
    assert WorkerLeaseBinding._selection_rejection_reason(task, _slot()) is None
    assert WorkerLeaseBinding._selection_rejection_reason({**task, "tags": "safe,waiting"}, _slot()) == "excluded_tag"
    assert WorkerLeaseBinding._selection_rejection_reason({**task, "tags": ""}, _slot()) == "pickup_tags"
    assert WorkerLeaseBinding._selection_rejection_reason({**task, "required_model": "paid-model"}, _slot()) == "model_binding"


def test_disabled_filter_preserves_ownership_and_never_implies_permission():
    slot = {"id": "our-slot", "pickup_filter": {"enabled": False}}
    assert not match_task_to_pickup_filter({"assigned_to": "user"}, slot)
    assert WorkerLeaseBinding._selection_rejection_reason({"assigned_to": "user"}, slot) == "ownership"
    assert WorkerLeaseBinding._selection_rejection_reason({"assigned_to": "bach"}, slot) is None
    assert worker_selection_policy(slot)["unrouted_ownership"] == "bach_or_own_worker_role"


@pytest.mark.parametrize("assigned_to", ["user", "claude", "gemini", "codex", "other-agent"])
def test_generic_pickup_filter_does_not_override_foreign_ownership(assigned_to):
    task = {"assigned_to": assigned_to, "category": "WORKER", "priority": "P1", "tags": ["ready"]}
    assert pickup_filter_rejection(task, _slot()) is None
    assert WorkerLeaseBinding._selection_rejection_reason(task, _slot()) == "ownership"


def test_only_an_explicit_route_to_this_slot_overrides_personal_owner():
    task = {"assigned_to": "user", "assigned_slot": "our-slot", "category": "GUI",
            "priority": "P3", "tags": ["safe"]}
    assert WorkerLeaseBinding._selection_rejection_reason(task, _slot()) is None
    assert WorkerLeaseBinding._selection_rejection_reason(
        {**task, "assigned_to": "other-agent"}, _slot()) == "ownership"
    assert WorkerLeaseBinding._selection_rejection_reason(
        {**task, "assigned_slot": "another-slot"}, _slot()) == "slot_binding"


def test_public_policy_is_read_only_bounded_and_has_no_private_fields():
    slot = _slot()
    slot["pickup_filter"]["api_key"] = "PRIVATE"
    slot["lease_id"] = "PRIVATE"
    raw = _worker_configuration(slot)
    projected = _project_configuration({"ok": True, **raw}, "our-slot")
    assert projected["selection_policy"] == worker_selection_policy(slot)
    assert "selection_policy" not in projected["configuration"]
    assert "PRIVATE" not in str(projected)
    assert projected["selection_policy"]["pickup_filter"]["categories"] == ["WORKER"]
    slot["pickup_filter"]["categories"].append("NEW")
    assert projected["selection_policy"]["pickup_filter"]["categories"] == ["WORKER"]


def test_selection_changes_invalidate_configuration_version_but_runtime_metadata_does_not():
    slot = _slot()
    before = _worker_configuration(slot)["configuration_version"]
    slot.update(status="running", current_activity="waiting", queue_status={"candidate_count": 153})
    assert _worker_configuration(slot)["configuration_version"] == before
    slot["pickup_filter"]["categories"] = ["BACH"]
    assert _worker_configuration(slot)["configuration_version"] != before
    changed = _worker_configuration(slot)["configuration_version"]
    slot["require_assigned_slot"] = True
    assert _worker_configuration(slot)["configuration_version"] != changed


@pytest.mark.parametrize("key,value", [
    ("enabled", "true"), ("categories", {"api_key": "PRIVATE"}),
    ("priorities", [True]), ("tags", ["x" * 101]), ("exclude_tags", ["x"] * 65),
])
def test_malformed_policy_never_becomes_a_valid_configuration(key, value):
    policy = worker_selection_policy(_slot())
    policy["pickup_filter"][key] = value
    assert project_selection_policy(policy) is None
    raw = _worker_configuration(_slot())
    with pytest.raises(WorkerStatusUnavailable):
        _project_configuration({"ok": True, **raw, "selection_policy": policy}, "our-slot")


def test_live_wait_summary_uses_only_projected_counters_and_utc():
    raw = {"schema": "bach.worker-queue.v1", "state": "waiting", "reason": "selection_excluded",
           "source": "canonical_task_api", "authority_mode": "local", "scan_complete": True,
           "observed_at": "2026-10-10T13:35:00+02:00", "candidate_count": 153, "matched_count": 0,
           "attempted_count": 0, "scanned_pages": 2,
           "rejected_counts": {"pickup_category": 148, "slot_binding": 4, "model_binding": 1},
           "last_candidate_task_id": 1235, "title": "PRIVATE", "lease_id": "PRIVATE"}
    before = copy.deepcopy(raw)
    text = queue_waiting_activity(raw)
    assert "153 Kandidaten, 0 Auswahlmatches" in text
    assert "Kategorie: 148" in text and "Slot: 4" in text and "Modell: 1" in text
    assert "11:35:00 UTC" in text and "Task-API" in text
    assert "PRIVATE" not in text and raw == before
    raw["candidate_count"] = True
    assert queue_waiting_activity(raw) == "Warte auf eine passende übernehmbare Aufgabe"


@pytest.mark.parametrize("authorization,origin,status", [
    ("", "", 401), ("Bearer wrong-fixture-token", "", 401),
    ("Bearer fixture-control-token", "https://foreign.example", 403),
    ("Bearer fixture-control-token", "http://127.0.0.1:8001", 200),
])
def test_control_configuration_requires_actual_token_and_same_origin(monkeypatch, authorization, origin, status):
    from gui import device_auth
    from hub._services.chat import control_auth, telegram_chat

    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "fixture-control-token")
    monkeypatch.setattr(device_auth, "validate_token", lambda _: None)
    reads = []
    monkeypatch.setattr(telegram_chat, "worker_configuration_snapshot",
                        lambda worker_id: reads.append(worker_id) or _worker_configuration(_slot()))
    handler = object.__new__(telegram_chat.ControlHandler)
    handler.path = "/api/workers/configuration?id=our-slot"
    handler.headers = {"Authorization": authorization, "Origin": origin, "Host": "127.0.0.1:8001"}
    replies = []
    monkeypatch.setattr(handler, "_json", lambda payload, code=200: replies.append((payload, code)))
    handler.do_GET()
    payload, code = replies[0]
    assert code == status
    assert reads == (["our-slot"] if status == 200 else [])
    if status == 200:
        assert payload["selection_policy"] == worker_selection_policy(_slot())
    else:
        assert "configuration" not in payload and "selection_policy" not in payload
