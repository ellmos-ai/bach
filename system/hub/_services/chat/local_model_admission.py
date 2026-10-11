# SPDX-License-Identifier: MIT
"""Join the existing local reserve receipt with the configured model-socket identity.

A reserve budget pass is an admission input, never a model-capacity certificate.
This module adds no second resource formula or provider/model router.
"""
from __future__ import annotations

SCHEMA = "bach.local-model-admission.v1"
_WAITING = frozenset({"waiting_memory_reserve", "waiting_disk_reserve"})
_BINDING_FIELDS = (
    "socket_id", "binding_id", "agent_id", "backend", "model",
    "configuration_version",
)


def _binding_projection(binding):
    if not isinstance(binding, dict):
        return {"status": "unknown"}
    if any(not isinstance(binding.get(key), str) or not binding[key]
           for key in _BINDING_FIELDS):
        return {"status": "unknown"}
    return {
        "schema": "bach.model-sockets.v1",
        "status": "bound",
        **{key: binding[key] for key in _BINDING_FIELDS},
    }


def compose_admission_receipt(receipt, *, binding=None, require_model_socket=False):
    """Preserve source evidence while composing strict local dispatch admission.

    The reserve service remains the authority for memory/disk budgets. The
    model-socket registry remains the authority for stable local target identity.
    Unknown reserve state never becomes capacity certification.
    """
    if not isinstance(receipt, dict):
        raise TypeError("local reserve receipt must be an object")
    if receipt.get("state") == "external_target":
        return receipt

    source_state = receipt.get("state")
    if not isinstance(source_state, str):
        source_state = "unknown"
    configured = (
        False if source_state == "not_configured"
        else None if source_state in {"invalid_policy", "unknown"}
        else True
    )
    enforced = receipt.get("enforced")
    if type(enforced) is not bool:
        enforced = None

    if binding is None:
        model_socket = {"status": "unknown" if require_model_socket else "not_required"}
    else:
        model_socket = _binding_projection(binding)

    capacity_status = (
        "budget_gate_passed"
        if source_state == "ready" and configured is True and enforced is True
        else "unknown"
    )
    result = dict(receipt)
    blocked_state = None
    if require_model_socket:
        if (source_state in {"not_configured", "disabled"}
                or (source_state in _WAITING | {"ready"}
                    and (configured is not True or enforced is not True))):
            blocked_state = "unknown_capacity"
        elif source_state in _WAITING | {"ready"} and model_socket["status"] != "bound":
            blocked_state = "unknown_model_socket_binding"

    if blocked_state is not None:
        result.update(state=blocked_state, admitted=False, retryable=False)

    result["local_admission"] = {
        "schema": SCHEMA,
        "decision": blocked_state or source_state,
        "reserve": {
            "schema": receipt.get("schema"),
            "state": source_state,
            "configured": configured,
            "enforced": enforced,
            "policy_version": receipt.get("policy_version"),
        },
        "model_socket": model_socket,
        "capacity": {
            "status": capacity_status,
            "certification": "not_provided",
        },
    }
    return result
