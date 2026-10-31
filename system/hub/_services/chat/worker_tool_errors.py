"""Versioned, bounded error metadata for the private worker-tool relay.

The display value remains a ``str`` for existing callers. Only values created
as :class:`ToolErrorText` carry trusted error metadata; message prefixes never
establish an effect state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCHEMA = "bach.worker-tool-error.v1"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_GENERATION = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CORRELATION_KEYS = frozenset({"request_id", "generation", "task_id", "receipt_id"})

# Each code has one producer, one public reason, and only effects that
# producer can prove. Unknown vendor details use reason_unavailable.
_ERRORS = {
    "tool_not_authorized": ("bach_tools.provider", "tool_not_authorized", frozenset({"not_applied"})),
    "tool_dispatch_denied": ("bach_tools.exec_tool", "tool_not_authorized", frozenset({"not_applied"})),
    "worker_context_denied": ("bach_tools.provider", "worker_context_denied", frozenset({"not_applied"})),
    "worker_binding_inactive": ("bach_tools.exec_tool", "worker_context_denied", frozenset({"not_applied"})),
    "worker_write_grant_denied": ("bach_tools.exec_tool", "write_grant_denied", frozenset({"not_applied"})),
    "provider_mode_unavailable": ("bach_tools.provider", "mode_unavailable", frozenset({"not_applied"})),
    "task_binding_required": ("bach_tools.exec_tool", "task_binding_required", frozenset({"not_started"})),
    "invalid_task_arguments": ("bach_tools.task_manage", "invalid_arguments", frozenset({"not_applied"})),
    "invalid_task_result": ("bach_tools.task_manage", "result_validation_failed", frozenset({"not_applied"})),
    "task_preflight_unavailable": ("bach_tools.task_manage", "reason_unavailable", frozenset({"not_applied"})),
    "task_result_limit_locked": ("bach_tools.task_manage", "result_limit_locked", frozenset({"not_applied"})),
    "task_operation_unconfirmed": ("bach_tools.task_manage", "reason_unavailable", frozenset({"unknown"})),
    "invalid_tool_arguments": ("bach_tools.write_file", "invalid_arguments", frozenset({"not_applied"})),
    "write_tool_denied": ("bach_tools.write_file", "mode_not_authorized", frozenset({"not_applied"})),
    "write_path_denied": ("bach_tools.write_file", "write_path_denied", frozenset({"not_applied"})),
    "write_effect_unconfirmed": ("bach_tools.write_file", "reason_unavailable", frozenset({"unknown"})),
    "trace_unavailable": ("worker_tool_bridge", "reason_unavailable", frozenset({"not_started"})),
    "tool_execution_unconfirmed": ("worker_tool_bridge", "reason_unavailable", frozenset({"unknown"})),
    "returned_trace_unconfirmed": ("worker_tool_bridge", "reason_unavailable", frozenset({"unknown"})),
    "transport_response_unconfirmed": ("worker_tool_client", "reason_unavailable", frozenset({"unknown"})),
    "transport_ack_unconfirmed": ("worker_tool_client", "reason_unavailable", frozenset({"unknown"})),
    "transport_response_invalid": ("worker_tool_client", "protocol_invalid", frozenset({"unknown"})),
    "bach_tool_effect_unconfirmed": ("bach_tools", "reason_unavailable", frozenset({"unknown"})),
}

# These reasons are selected only at the concrete guard site in bach_tools.
# Text returned by a tool is never inspected to choose a reason or effect.
_POLICY_REASONS = {
    "tool_not_authorized": frozenset({"not_applied"}),
    "task_binding_required": frozenset({"not_started"}),
    "worker_context_denied": frozenset({"not_applied"}),
    "write_grant_denied": frozenset({"not_applied"}),
    "bound_check_denied": frozenset({"not_applied"}),
    "mode_not_authorized": frozenset({"not_applied"}),
    "mode_unavailable": frozenset({"not_applied"}),
    "provider_unavailable": frozenset({"not_applied"}),
    "invalid_arguments": frozenset({"not_applied"}),
    "task_target_mismatch": frozenset({"not_applied"}),
    "task_read_scope_denied": frozenset({"not_applied"}),
    "directory_expected": frozenset({"not_applied"}),
    "path_not_authorized": frozenset({"not_applied"}),
    "secret_path_denied": frozenset({"not_applied"}),
    "search_pattern_invalid": frozenset({"not_applied"}),
    "resource_limit_exceeded": frozenset({"unknown"}),
    "handler_not_allowed": frozenset({"not_applied"}),
    "command_not_authorized": frozenset({"not_applied"}),
    "write_path_denied": frozenset({"not_applied"}),
    "resource_not_found": frozenset({"not_applied"}),
    "state_conflict": frozenset({"not_applied"}),
    "no_updates": frozenset({"not_applied"}),
    "unsupported_action": frozenset({"not_applied"}),
}

def _error_spec(code, reason=None):
    if not isinstance(code, str):
        raise ToolErrorContractError("Unbekannter Werkzeugfehlercode")
    if code == "tool_policy_denied":
        if not isinstance(reason, str) or reason not in _POLICY_REASONS:
            raise ToolErrorContractError("Unbekannter Werkzeugablehnungsgrund")
        return "bach_tools", reason, _POLICY_REASONS[reason]
    spec = _ERRORS.get(code)
    if spec is None or reason is not None:
        raise ToolErrorContractError("Unbekannter Werkzeugfehlercode")
    return spec


class ToolErrorContractError(ValueError):
    """An error envelope is not a canonical v1 value."""


@dataclass(frozen=True)
class WorkerToolCallResult:
    """Detailed client result; ``WorkerToolClient.call`` remains tuple-compatible."""

    result: str
    is_error: bool
    error: dict | None = None
    quarantined: bool = False


class ToolErrorText(str):
    """A legacy display string with explicit, producer-created error metadata."""

    def __new__(cls, text, *, code, reason=None, effect_state=None):
        if not isinstance(text, str) or len(text) > 4096:
            raise ToolErrorContractError("Ungültiger Werkzeugfehlertext")
        source, public_reason, effects = _error_spec(code, reason)
        state = effect_state if effect_state is not None else min(effects)
        if not isinstance(state, str) or state not in effects:
            raise ToolErrorContractError("Nicht belegter Werkzeugwirkungsstatus")
        value = super().__new__(cls, text)
        object.__setattr__(value, "_code", code)
        object.__setattr__(value, "_source", source)
        object.__setattr__(value, "_reason", public_reason)
        object.__setattr__(value, "_effect_state", state)
        return value

    def __setattr__(self, _name, _value):
        raise AttributeError("Werkzeugfehler-Metadaten sind unveränderlich")


def _validate_correlation(value):
    if not isinstance(value, dict) or set(value) != _CORRELATION_KEYS:
        raise ToolErrorContractError("Werkzeugfehler-Korrelation ist ungültig")
    request_id = value.get("request_id")
    generation = value.get("generation")
    task_id = value.get("task_id")
    receipt_id = value.get("receipt_id")
    if (not isinstance(request_id, str) or not _ID.fullmatch(request_id)
            or not isinstance(generation, str) or not _GENERATION.fullmatch(generation)
            or type(task_id) is not int or task_id <= 0
            or (receipt_id is not None and (not isinstance(receipt_id, str) or not _ID.fullmatch(receipt_id)))):
        raise ToolErrorContractError("Werkzeugfehler-Korrelation ist ungültig")
    return {"request_id": request_id, "generation": generation,
            "task_id": task_id, "receipt_id": receipt_id}


def envelope_for(error, correlation):
    """Serialize only the trusted concrete type with an exact call binding."""
    if type(error) is not ToolErrorText:
        return None
    bound = _validate_correlation(correlation)
    return {"schema": SCHEMA, "code": error._code, "source": error._source,
            "reason": error._reason, "effect_state": error._effect_state,
            "correlation": bound}


def validate_envelope(value, *, expected_correlation=None):
    """Validate a received envelope, including every correlation field."""
    if not isinstance(value, dict) or set(value) != {
        "schema", "code", "source", "reason", "effect_state", "correlation"
    } or value.get("schema") != SCHEMA:
        raise ToolErrorContractError("Werkzeugfehlervertrag ist ungültig")
    code = value.get("code")
    supplied_reason = value.get("reason")
    try:
        if code == "tool_policy_denied":
            source, reason, effects = _error_spec(code, supplied_reason)
        else:
            source, reason, effects = _error_spec(code)
    except ToolErrorContractError:
        raise ToolErrorContractError("Unbekannter oder ungültiger Werkzeugfehlercode") from None
    effect_state = value.get("effect_state")
    if (value.get("source") != source or supplied_reason != reason
            or not isinstance(effect_state, str) or effect_state not in effects):
        raise ToolErrorContractError("Werkzeugfehlervertrag ist inkonsistent")
    correlation = _validate_correlation(value.get("correlation"))
    if expected_correlation is not None and correlation != _validate_correlation(expected_correlation):
        raise ToolErrorContractError("Werkzeugfehler passt nicht zum aktuellen Aufruf")
    return {"schema": SCHEMA, "code": value["code"], "source": source,
            "reason": reason, "effect_state": value["effect_state"],
            "correlation": correlation}


def transport_error(code, correlation):
    """Create a bounded local transport error without exposing exception text."""
    source, reason, effects = _error_spec(code)
    return validate_envelope({"schema": SCHEMA, "code": code, "source": source,
                              "reason": reason, "effect_state": min(effects),
                              "correlation": correlation})
