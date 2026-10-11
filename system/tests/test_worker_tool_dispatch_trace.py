"""Normal-loop trace adapter tests use the canonical isolated lease and event store."""
import json
import threading
import uuid

import pytest
from hub._services.chat.worker_tool_dispatch_trace import (
    abandon_normal_tool_result,
    acknowledge_normal_tool_result,
    execute_normal_tool,
)
from hub._services.chat.worker_tool_trace import (
    SCHEMA,
    WorkerToolTraceError,
    digest_json,
    digest_text,
)


@pytest.fixture
def binding(tmp_path, monkeypatch):
    from hub._services import task_lease_client
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    from system.tests.test_task_lease_service import _connect, _create_db, _insert

    database = tmp_path / "canonical.db"
    _create_db(database)
    conn = _connect(database)
    task_id = _insert(conn, title="Normal loop trace task", assigned_to="BACH")
    conn.close()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    client = task_lease_client.TaskLeaseClient(db_path=database)
    worker_binding = WorkerLeaseBinding.acquire(
        client, task_id, worker_id="trace-worker@HOST", host="HOST",
        generation="normal-loop-generation-1", is_current=lambda: True,
        stop_event=threading.Event(),
    )
    yield worker_binding
    if worker_binding._active:
        worker_binding.return_lease()


def _events(binding):
    return binding._client.tool_trace_events(binding.task_id)["events"]


def _phases(binding):
    return [event["phase"] for event in _events(binding)]


def _assert_blocked_and_foreign_claim_denied(binding):
    from hub._services.task_lease_client import LeaseDeniedError

    assert binding._client.read(binding.task_id).status == "blocked"
    snapshot = binding._client.task_snapshot(binding.task_id)
    with pytest.raises(LeaseDeniedError) as denied:
        binding._client.acquire(
            binding.task_id,
            worker_id="foreign-worker@OTHER-HOST",
            host="OTHER-HOST",
            request_id=uuid.uuid4().hex,
            task_version=snapshot["task_version"],
            result_generation=uuid.uuid4().hex,
            intent="isolated quarantine regression",
        )
    assert denied.value.reason == "not_claimable"
    assert binding._client.read(binding.task_id).status == "blocked"


def test_normal_dispatch_records_hash_only_and_ack_after_response_append(binding):
    secret_arg = "synthetic-argument-secret"
    secret_result = "synthetic-result-secret"
    arguments = {"query": secret_arg}
    calls = []

    def execute(name, supplied):
        calls.append((name, supplied))
        assert _phases(binding) == ["started"]
        return secret_result

    outcome = execute_normal_tool(binding, "search_text", arguments, execute)
    assert outcome.status == "returned"
    assert outcome.result == secret_result
    assert _phases(binding) == ["started", "returned"]
    assert calls == [("search_text", arguments)]
    assert secret_result not in repr(outcome)
    assert "completion_token" not in repr(outcome)

    messages = []
    messages.append({"role": "tool", "content": outcome.result})
    assert _phases(binding) == ["started", "returned"]
    assert acknowledge_normal_tool_result(binding, outcome)
    assert outcome.status == "acknowledged"
    assert not acknowledge_normal_tool_result(binding, outcome)

    events = _events(binding)
    assert [event["phase"] for event in events] == ["started", "returned", "acknowledged"]
    assert all(event["schema"] == SCHEMA and event["effect_status"] == "unknown" for event in events)
    assert all(event["source"] == "normal-loop" for event in events)
    assert events[0]["arguments_sha256"] == digest_json(arguments)
    assert events[1]["result_sha256"] == digest_text(secret_result)
    assert events[1]["receipt_id"] == events[2]["receipt_id"]
    serialized = json.dumps(events, ensure_ascii=False)
    assert secret_arg not in serialized
    assert secret_result not in serialized
    assert "synthetic-lease" not in serialized
    assert all("arguments" not in event and "result" not in event and "completion_token" not in event for event in events)
    assert messages == [{"role": "tool", "content": secret_result}]


def test_start_failure_never_calls_dispatcher(binding, monkeypatch):
    calls = []
    monkeypatch.setattr(
        binding, "trace_tool_started",
        lambda **kwargs: (_ for _ in ()).throw(WorkerToolTraceError("synthetic start failure")),
    )
    outcome = execute_normal_tool(binding, "task_manage", {"action": "detail"}, lambda *args: calls.append(args))
    assert outcome.status == "unknown"
    assert outcome.error_code == "trace_start_unavailable"
    assert calls == []
    assert _events(binding) == []


def test_dispatcher_exception_records_failed_and_never_replays_possible_effect(binding):
    secret = "synthetic-exception-secret"
    effects = []

    def fail_after_possible_effect(*args):
        effects.append("possible-effect")
        raise RuntimeError(secret)

    outcome = execute_normal_tool(binding, "search_text", {"query": "x"}, fail_after_possible_effect)
    assert outcome.status == "failed"
    assert outcome.error_code == "tool_failed"
    assert secret not in repr(outcome)
    retry = execute_normal_tool(
        binding, "search_text", {"query": "x"},
        lambda *args: effects.append("replayed-effect"),
    )
    assert retry.status == "unknown"
    assert effects == ["possible-effect"]
    _assert_blocked_and_foreign_claim_denied(binding)
    events = _events(binding)
    assert [event["phase"] for event in events] == ["started", "failed"]
    assert secret not in json.dumps(events)
    assert all(event["effect_status"] == "unknown" for event in events)


def test_return_sink_failure_does_not_replay_dispatch(binding, monkeypatch):
    calls = []
    original = binding.trace_tool_phase

    def phase(identity, name, **kwargs):
        if name == "returned":
            raise WorkerToolTraceError("synthetic return sink failure")
        return original(identity, name, **kwargs)

    monkeypatch.setattr(binding, "trace_tool_phase", phase)
    def execute(*args):
        calls.append(args)
        return "private result"

    outcome = execute_normal_tool(binding, "search_text", {"query": "x"}, execute)
    assert outcome.status == "unknown"
    assert outcome.result is None
    assert calls == [("search_text", {"query": "x"})]
    retry = execute_normal_tool(binding, "search_text", {"query": "x"}, execute)
    assert retry.status == "unknown"
    assert len(calls) == 1
    _assert_blocked_and_foreign_claim_denied(binding)
    assert _phases(binding) == ["started"]


def test_no_ack_event_exists_until_caller_appends_response(binding):
    outcome = execute_normal_tool(binding, "search_text", {"query": "x"}, lambda *_: "result")
    assert _phases(binding) == ["started", "returned"]
    # A caller that cannot append must stop without calling the ACK helper.
    assert outcome.status == "returned"
    assert _phases(binding) == ["started", "returned"]


def test_abandoned_response_quarantines_and_blocks_foreign_claim(binding):
    calls = []
    outcome = execute_normal_tool(
        binding, "search_text", {"query": "x"},
        lambda *args: calls.append(args) or "private result",
    )
    assert outcome.status == "returned"
    assert _phases(binding) == ["started", "returned"]

    # Simulate the response append failing after the tool and returned event.
    with pytest.raises(RuntimeError, match="synthetic response append failure"):
        try:
            raise RuntimeError("synthetic response append failure")
        except RuntimeError:
            assert abandon_normal_tool_result(binding, outcome)
            raise

    assert outcome.status == "unknown"
    assert outcome.error_code == "response_abandoned"
    assert outcome.result is None
    assert not acknowledge_normal_tool_result(binding, outcome)
    assert calls == [("search_text", {"query": "x"})]
    assert _phases(binding) == ["started", "returned"]
    _assert_blocked_and_foreign_claim_denied(binding)


def test_abandon_rejects_mismatched_binding_without_consuming_outcome(binding):
    outcome = execute_normal_tool(binding, "search_text", {"query": "x"}, lambda *_: "result")
    assert not abandon_normal_tool_result(None, outcome)
    assert outcome.status == "returned"
    assert outcome.result == "result"
    assert abandon_normal_tool_result(binding, outcome)


def test_abandon_does_not_requarantine_review_closed_binding(binding, monkeypatch):
    quarantine_calls = []
    original_quarantine = binding.quarantine_lease

    def quarantine():
        quarantine_calls.append(True)
        return original_quarantine()

    monkeypatch.setattr(binding, "quarantine_lease", quarantine)

    def terminal_tool(_name, _arguments):
        assert binding.record_worktree_result(
            binding.task_id,
            "synthetic isolated review result",
            review=True,
            result_ref="https://github.com/example/repo/pull/1",
        )
        return "review result"

    outcome = execute_normal_tool(binding, "task_manage", {"action": "review"}, terminal_tool)
    assert outcome.status == "returned"
    assert binding._client.read(binding.task_id).status == "review"
    assert abandon_normal_tool_result(binding, outcome)
    assert outcome.status == "unknown"
    assert outcome.result is None
    assert quarantine_calls == []
    assert binding.closed is True
    assert binding._client.read(binding.task_id).status == "review"
    assert _phases(binding) == ["started", "returned"]


def test_ack_sink_failure_does_not_retry_dispatch_or_ack(binding, monkeypatch):
    calls = []
    original = binding.trace_tool_phase

    def phase(identity, name, **kwargs):
        if name == "acknowledged":
            raise WorkerToolTraceError("synthetic ack sink failure")
        return original(identity, name, **kwargs)

    monkeypatch.setattr(binding, "trace_tool_phase", phase)
    outcome = execute_normal_tool(
        binding, "search_text", {"query": "x"},
        lambda *args: calls.append(args) or "result",
    )
    messages = [{"role": "tool", "content": outcome.result}]
    assert not acknowledge_normal_tool_result(binding, outcome)
    assert not acknowledge_normal_tool_result(binding, outcome)
    assert outcome.status == "unknown"
    assert calls == [("search_text", {"query": "x"})]
    assert len(messages) == 1
    _assert_blocked_and_foreign_claim_denied(binding)
    assert _phases(binding) == ["started", "returned"]


def test_quarantine_without_ack_does_not_claim_blocked(binding, monkeypatch):
    monkeypatch.setattr(binding, "quarantine_lease", lambda: False)
    effects = []

    def fail_after_possible_effect(*args):
        effects.append("possible-effect")
        raise RuntimeError("synthetic failure")

    outcome = execute_normal_tool(binding, "search_text", {"query": "x"}, fail_after_possible_effect)
    assert outcome.status == "failed"
    assert binding._active is False
    assert binding._client.read(binding.task_id).status == "in_progress"
    retry = execute_normal_tool(binding, "search_text", {"query": "x"}, lambda *_: effects.append("replay"))
    assert retry.status == "unknown"
    assert effects == ["possible-effect"]


def test_review_closed_terminal_binding_is_not_requarantined(binding, monkeypatch):
    quarantine_calls = []
    original_quarantine = binding.quarantine_lease
    original_phase = binding.trace_tool_phase

    def quarantine():
        quarantine_calls.append(True)
        return original_quarantine()

    def phase(identity, name, **kwargs):
        if name == "acknowledged":
            raise WorkerToolTraceError("synthetic ack sink failure")
        return original_phase(identity, name, **kwargs)

    monkeypatch.setattr(binding, "quarantine_lease", quarantine)
    monkeypatch.setattr(binding, "trace_tool_phase", phase)

    def terminal_tool(_name, _arguments):
        assert binding.record_worktree_result(
            binding.task_id,
            "synthetic isolated review result",
            review=True,
            result_ref="https://github.com/example/repo/pull/1",
        )
        return "review result"

    outcome = execute_normal_tool(binding, "task_manage", {"action": "review"}, terminal_tool)
    assert outcome.status == "returned"
    messages = [{"role": "tool", "content": outcome.result}]
    assert not acknowledge_normal_tool_result(binding, outcome)
    assert outcome.status == "unknown"
    assert binding.closed is True
    assert quarantine_calls == []
    assert messages == [{"role": "tool", "content": "review result"}]
    assert binding._client.read(binding.task_id).status == "review"


def test_started_identity_closes_after_native_task_version_update(binding):
    def update_task(_name, _arguments):
        return binding.execute_task_manage(
            {"action": "update", "task_id": binding.task_id, "title": "Updated trace task"},
            _dispatch_marked=True,
        )

    first = execute_normal_tool(binding, "task_manage", {"action": "update"}, update_task)
    old_version = _events(binding)[0]["task_version"]
    assert first.status == "returned"
    messages = [{"role": "tool", "content": first.result}]
    assert acknowledge_normal_tool_result(binding, first)

    second = execute_normal_tool(
        binding, "task_manage", {"action": "detail", "task_id": binding.task_id},
        lambda _name, _arguments: "current task detail",
    )
    assert second.status == "returned"
    messages.append({"role": "tool", "content": second.result})
    assert acknowledge_normal_tool_result(binding, second)

    events = _events(binding)
    starts = [event for event in events if event["phase"] == "started"]
    returns = [event for event in events if event["phase"] == "returned"]
    assert len(starts) == 2 and len(returns) == 2
    assert starts[0]["task_version"] == returns[0]["task_version"] == old_version
    assert starts[1]["task_version"] == returns[1]["task_version"]
    assert starts[1]["task_version"] != old_version
    assert _phases(binding) == [
        "started", "returned", "acknowledged",
        "started", "returned", "acknowledged",
    ]
    assert len(messages) == 2


def test_unbound_compatibility_has_no_trace_ack():
    calls = []
    outcome = execute_normal_tool(
        None, "search_text", {"query": "x"},
        lambda *args: calls.append(args) or "unbound result",
    )
    assert outcome.status == "untraced"
    assert calls == [("search_text", {"query": "x"})]
    assert acknowledge_normal_tool_result(None, outcome)
    assert not acknowledge_normal_tool_result(None, outcome)


def test_invalid_argument_shape_never_starts_or_dispatches(binding):
    calls = []
    outcome = execute_normal_tool(binding, "search_text", ["not", "a", "mapping"], lambda *args: calls.append(args))
    assert outcome.status == "unknown"
    assert outcome.error_code == "invalid_tool_call"
    assert calls == []
    assert _events(binding) == []
