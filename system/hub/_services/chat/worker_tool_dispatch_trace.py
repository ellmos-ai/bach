"""Normal-loop adapter for the canonical worker tool trace."""
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .worker_tool_trace import TraceIdentity, digest_json, digest_text


class _TraceAckRejected(Exception):
    pass


@dataclass
class TracedToolOutcome:
    """Internal dispatch result; raw result and native identity are omitted from repr."""
    status: str
    result: Any = field(default=None, repr=False, compare=False)
    error_code: str | None = None
    _binding: Any = field(default=None, repr=False, compare=False)
    _identity: TraceIdentity | None = field(default=None, repr=False, compare=False)
    _receipt_id: str | None = field(default=None, repr=False, compare=False)
    _ack_lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)
    _ack_attempted: bool = field(default=False, init=False, repr=False, compare=False)


def _invalidate(binding: Any, reason: str) -> None:
    # Cleanup exceptions can carry private tool data; invalidate silently.
    try:
        binding.invalidate(reason)
    except Exception:  # noqa: BLE001,S110 - redacted best-effort revocation
        pass


def _quarantine_then_invalidate(binding: Any, reason: str) -> None:
    """Quarantine uncertain effects before local revocation; never infer ACK."""
    # Do not log arbitrary quarantine details or claim a blocked ACK without one.
    try:
        if getattr(binding, "closed", False) is not True:
            binding.quarantine_lease()
    except Exception:  # noqa: BLE001,S110 - redacted quarantine failure; no blocked claim
        # The caller receives only the original failed/unknown outcome. A missing
        # quarantine ACK is not evidence that the canonical task is blocked.
        pass
    finally:
        _invalidate(binding, reason)


def _require_accepted(ack: Any) -> None:
    if not isinstance(ack, dict) or ack.get("accepted") is not True:
        raise _TraceAckRejected()


def _result_digest(result: Any) -> str:
    if isinstance(result, str):
        return digest_text(result)
    return digest_json(result)


def execute_normal_tool(
    binding: Any,
    name: str,
    args: dict,
    execute: Callable[[str, dict], Any],
) -> TracedToolOutcome:
    """Persist started/returned around one tool execution; never retry the tool."""
    if not isinstance(name, str) or not name or not isinstance(args, dict) or not callable(execute):
        return TracedToolOutcome(status="unknown", error_code="invalid_tool_call")

    if binding is None:
        return TracedToolOutcome(status="untraced", result=execute(name, args))

    try:
        arguments_sha256 = digest_json(args)
        identity = binding.trace_tool_started(
            source="normal-loop",
            request_id=uuid.uuid4().hex,
            tool_name=name,
            arguments_sha256=arguments_sha256,
        )
        if not isinstance(identity, TraceIdentity):
            raise _TraceAckRejected()
    except Exception:  # noqa: BLE001 - trace sink details stay private; dispatch is denied
        _invalidate(binding, "trace_start_unavailable")
        return TracedToolOutcome(status="unknown", error_code="trace_start_unavailable")

    try:
        result = execute(name, args)
    except Exception:  # noqa: BLE001 - tool exception text may contain private arguments/results
        try:
            _require_accepted(binding.trace_tool_phase(identity, "failed"))
        except Exception:  # noqa: BLE001 - trace sink exception details stay private
            _quarantine_then_invalidate(binding, "trace_sink_unavailable")
            return TracedToolOutcome(status="unknown", error_code="trace_sink_unavailable")
        _quarantine_then_invalidate(binding, "tool_failed")
        return TracedToolOutcome(status="failed", error_code="tool_failed")

    try:
        result_sha256 = _result_digest(result)
        receipt_id = uuid.uuid4().hex
        _require_accepted(binding.trace_tool_phase(
            identity,
            "returned",
            receipt_id=receipt_id,
            result_sha256=result_sha256,
        ))
    except Exception:  # noqa: BLE001 - serializer/sink details stay private; outcome is unknown
        _quarantine_then_invalidate(binding, "trace_sink_unavailable")
        return TracedToolOutcome(status="unknown", error_code="trace_sink_unavailable")

    return TracedToolOutcome(
        status="returned",
        result=result,
        _binding=binding,
        _identity=identity,
        _receipt_id=receipt_id,
    )


def acknowledge_normal_tool_result(binding: Any, outcome: TracedToolOutcome) -> bool:
    """Acknowledge once, after the caller has accepted/appended the tool response."""
    if not isinstance(outcome, TracedToolOutcome):
        return False

    with outcome._ack_lock:
        if outcome._ack_attempted:
            return False
        outcome._ack_attempted = True

    if outcome.status == "untraced":
        return binding is None
    if outcome.status != "returned" or binding is None or binding is not outcome._binding:
        return False

    try:
        _require_accepted(binding.trace_tool_phase(
            outcome._identity,
            "acknowledged",
            receipt_id=outcome._receipt_id,
        ))
    except Exception:  # noqa: BLE001 - ACK sink details stay private; outcome is unknown
        outcome.status = "unknown"
        outcome.result = None
        _quarantine_then_invalidate(binding, "tool_ack_unconfirmed")
        return False

    outcome.status = "acknowledged"
    return True


def abandon_normal_tool_result(binding: Any, outcome: TracedToolOutcome) -> bool:
    """Consume a returned result when the caller cannot append its response.

    True means the local outcome was consumed and quarantine was attempted
    before invalidation. It does not confirm a native blocked ACK.
    """
    if not isinstance(outcome, TracedToolOutcome) or binding is None:
        return False

    with outcome._ack_lock:
        if (
            outcome._ack_attempted
            or outcome.status != "returned"
            or binding is not outcome._binding
            or not isinstance(outcome._identity, TraceIdentity)
            or not isinstance(outcome._receipt_id, str)
            or not outcome._receipt_id
        ):
            return False
        outcome._ack_attempted = True
        outcome.status = "unknown"
        outcome.error_code = "response_abandoned"
        outcome.result = None
        _quarantine_then_invalidate(binding, "response_abandoned")
    return True
