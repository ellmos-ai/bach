from __future__ import annotations

from hub._services.chat import execution_target, model_sockets


def _snapshot():
    return {
        "schema": model_sockets.SCHEMA,
        "configuration_version": "a" * 64,
        "migration_required": False,
        "host_id": "test-host",
        "source": "canonical_slots_config",
        "runtime_verified": False,
        "sockets": [{
            "id": "socket-a",
            "backend": "ollama",
            "model": "qwen:4b",
            "host_id": "test-host",
            "enabled": True,
            "max_active_slots": 1,
            "residency_policy": "exclusive",
            "slots": [{
                "id": "binding-a",
                "agent_id": "buddha_chat",
                "socket_id": "socket-a",
                "enabled": True,
                "priority": "foreground",
                "context_tokens": None,
                "name": "Buddha Chat",
                "orphaned": False,
                "running": None,
                "resource_share": None,
            }],
            "residency": "unknown",
            "weight_bytes": None,
            "resource_share": None,
            "effective_max_active_slots": 1,
            "capacity_verified": False,
        }],
        "unbound_agent_ids": [],
        "host_inference_limit": 1,
    }


def _local_target():
    return execution_target.local_execution_target(
        "ollama", "qwen:4b", host="test-host",
        binding={"socket_id": "socket-a", "binding_id": "binding-a", "agent_id": "buddha_chat"},
        source="host_inference_gate",
    )


def test_execution_target_is_allowlisted_and_rejects_untrusted_fields():
    target = _local_target()
    assert target["schema"] == execution_target.SCHEMA
    assert target["locality"] == "local"
    assert target["binding_id"] == "binding-a"
    assert execution_target.project_execution_target({**target, "secret": "drop"}) is not None
    assert execution_target.project_execution_target({**target, "model": "qwen model"}) is None
    assert execution_target.project_execution_target({**target, "locality": "unknown"}) is None


def test_measured_host_owner_gets_full_socket_and_relative_slot_share(monkeypatch):
    monkeypatch.setattr(model_sockets, "_live_runtime_evidence", lambda: {
        "gate_available": True,
        "gate_active": True,
        "gate_target": _local_target(),
        "control_available": True,
        "targets": [_local_target()],
        "agent_states": {"buddha_chat": {"running": True, "target_seen": True}},
    })
    view = model_sockets._with_runtime(_snapshot())
    socket = view["sockets"][0]
    binding = socket["slots"][0]
    assert view["runtime_verified"] is True
    assert view["runtime_reason_code"] == "host_owner"
    assert socket["resource_share"] == 1.0
    assert socket["resource_share_state"] == "measured_owner"
    assert binding["running"] is True
    assert binding["resource_share"] == 1.0
    assert binding["relative_slot_share"] == 1.0


def test_local_target_without_host_owner_keeps_resource_share_unknown(monkeypatch):
    monkeypatch.setattr(model_sockets, "_live_runtime_evidence", lambda: {
        "gate_available": True,
        "gate_active": False,
        "gate_target": None,
        "control_available": True,
        "targets": [_local_target()],
        "agent_states": {"buddha_chat": {"running": True, "target_seen": True}},
    })
    view = model_sockets._with_runtime(_snapshot())
    socket = view["sockets"][0]
    binding = socket["slots"][0]
    assert view["runtime_reason_code"] == "local_target_resource_unmeasured"
    assert socket["resource_share"] is None
    assert binding["running"] is True
    assert binding["resource_share"] is None


def test_unavailable_runtime_source_does_not_project_zero_percent(monkeypatch):
    monkeypatch.setattr(model_sockets, "_live_runtime_evidence", lambda: {
        "gate_available": False,
        "gate_active": False,
        "gate_target": None,
        "control_available": False,
        "targets": [],
        "agent_states": {},
    })
    view = model_sockets._with_runtime(_snapshot())
    socket = view["sockets"][0]
    binding = socket["slots"][0]
    assert view["runtime_verified"] is False
    assert socket["resource_share"] is None
    assert binding["running"] is None
    assert binding["resource_share"] is None


def test_active_owner_without_configured_socket_remains_unclassified(monkeypatch):
    target = execution_target.local_execution_target(
        "ollama", "other:4b", host="test-host",
        binding={"socket_id": "socket-other", "binding_id": "binding-other", "agent_id": "other"},
        source="host_inference_gate",
    )
    monkeypatch.setattr(model_sockets, "_live_runtime_evidence", lambda: {
        "gate_available": True,
        "gate_active": True,
        "gate_target": target,
        "control_available": False,
        "targets": [],
        "agent_states": {},
    })
    view = model_sockets._with_runtime(_snapshot())
    socket = view["sockets"][0]
    binding = socket["slots"][0]
    assert socket["resource_share"] is None
    assert socket["resource_share_state"] == "active_target_unavailable"
    assert binding["running"] is None
    assert binding["resource_share"] is None
