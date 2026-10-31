"""Behavioral tests for private model-call evidence bound to a worker lease.

Every test uses the existing TaskLeaseClient and WorkerLeaseBinding against an
isolated in-memory SQLite database. The response values below are local
fixtures passed to the confirmation API; they are not provider or task-review
acceptance evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading

import pytest

from hub._services.task_lease_client import LeaseProtocolError, TaskLeaseClient
from system.tests.test_task_lease_client import _insert_task, mem_db
from system.tests.test_task_lease_client_review import T0


BACKEND = "ollama"
REQUESTED_MODEL = "requested-model"
OBSERVED_MODEL = "observed-model"
SLOT_ID = "worker-slot-2210"
GENERATION = "execution-generation-1"
SUBMISSION = "Konkretes Ergebnis, das getrennt im Review bleibt."
RAW_REQUEST = "private prompt fixture; not persisted in the execution projection"
RAW_RESPONSE = "private response fixture; only its digest should be projected"


def _response(*, content=RAW_RESPONSE, model=OBSERVED_MODEL, tool_calls=None, error=None):
    # Adapter-provided response metadata is separate from the display model;
    # the OpenAI choices/message transport envelope is not this API contract.
    response = {"model": model, "provider_reported_model": model,
                "content": content, "tool_calls": tool_calls}
    if error is not None:
        response["error"] = error
    return response


def _request_sha(text=RAW_REQUEST):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_binding(client, task_id, *, generation=GENERATION, current=None, stop=None):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    current = current if current is not None else {"value": True}
    stop = stop if stop is not None else threading.Event()
    binding = WorkerLeaseBinding.acquire(
        client,
        task_id,
        worker_id="physical-worker@HOST",
        host="HOST",
        generation=generation,
        is_current=lambda: current["value"],
        stop_event=stop,
        clock=lambda: T0,
    )
    return binding, current, stop


@pytest.fixture
def worker_context(mem_db):
    conn = mem_db
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "created_at" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
        conn.commit()
    task_id = _insert_task(conn, "Execution evidence task")
    client = TaskLeaseClient(conn=conn)
    binding, current, stop = _new_binding(client, task_id)
    context = {"conn": conn, "client": client, "task_id": task_id,
               "binding": binding, "current": current, "stop": stop}
    yield context
    if not binding.closed and current["value"]:
        binding.return_lease()


def _begin(binding, *, request_text=RAW_REQUEST):
    return binding.begin_model_execution(
        backend_id=BACKEND,
        requested_model=REQUESTED_MODEL,
        slot_id=SLOT_ID,
        request_sha256=_request_sha(request_text),
    )


def _read(context):
    snapshot = context["client"].task_result_snapshot(context["task_id"])
    return snapshot, snapshot.get("result")


def _assert_execution_available(execution, record, binding, *, request_text=RAW_REQUEST,
                                input_version=None, response_model=OBSERVED_MODEL):
    assert isinstance(execution, dict)
    assert execution["schema"] == "bach.worker-execution-evidence.v2"
    assert execution["availability"] == "available"
    assert execution["backend_id"] == BACKEND
    assert execution["requested_model"] == REQUESTED_MODEL
    assert execution["observed_model"] == response_model
    assert execution["model_provenance"] == ("unknown" if response_model is None else "provider_reported")
    assert execution["slot_id"] == SLOT_ID
    assert execution["generation"] == GENERATION
    assert execution["fence"] == binding._ack.fence
    assert execution["submission_task_version"] == record["task_version"]
    assert execution["input_task_version"] == (input_version or record["task_version"])
    assert execution["request_sha256"] == _request_sha(request_text)
    assert re.fullmatch(r"[a-f0-9]{64}", execution["response_sha256"])
    assert execution["execution_id"]
    assert execution["execution_revision"]
    for field in ("started_at", "returned_at", "linked_at"):
        assert isinstance(execution[field], str) and execution[field]
    rendered = json.dumps(execution, ensure_ascii=False, sort_keys=True)
    assert RAW_REQUEST not in rendered
    assert RAW_RESPONSE not in rendered
    assert binding._ack.lease_id not in rendered


def _submit(binding, task_id, result=SUBMISSION):
    return binding.execute_task_manage({
        "action": "submit_result",
        "task_id": task_id,
        "result": result,
    })


def _schema_objects(conn):
    return tuple(tuple(row) for row in conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ))


@pytest.mark.parametrize(
    "response",
    [
        _response(),
        _response(content=None, tool_calls=[{
            "id": "call-fixture-1",
            "type": "function",
            "function": {"name": "local_fixture_tool", "arguments": "{\"private\":true}"},
        }]),
    ],
    ids=["content-response", "tool-call-response"],
)
def test_confirmed_model_call_links_after_native_result_submission(worker_context, response):
    context = worker_context
    binding = context["binding"]
    task_id = context["task_id"]
    input_version = binding.task_snapshot()["task_version"]

    handle = _begin(binding)
    assert handle is not None
    with pytest.raises(TypeError):
        json.dumps(handle)
    assert binding.finish_model_execution(handle, result=response) is True

    _submit(binding, task_id)
    snapshot, record = _read(context)

    assert snapshot["status"] == "review"
    assert record["accepted"] is False
    assert record["submitted_by"] == "physical-worker@HOST"
    assert record.get("accepted_by") is None
    _assert_execution_available(record.get("execution"), record, binding,
                                input_version=input_version)
    assert record["execution"]["observed_model"] == response["model"]

    # Linking the same confirmed handle is idempotent: it returns the existing
    # link event rather than appending another one.
    before = context["conn"].execute(
        "SELECT id,link_event_id,linked_at FROM worker_model_executions WHERE result_id=?",
        (record["result_id"],),
    ).fetchone()
    assert before is not None and before[1] is not None
    assert binding._link_confirmed_model_execution() is True
    after = context["conn"].execute(
        "SELECT id,link_event_id,linked_at FROM worker_model_executions WHERE result_id=?",
        (record["result_id"],),
    ).fetchone()
    assert tuple(after) == tuple(before)
    assert context["conn"].execute(
        "SELECT status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()[0] == "review"


def test_cli_order_links_only_after_submit_then_valid_return(worker_context):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None

    _submit(binding, context["task_id"])
    snapshot, record = _read(context)
    assert snapshot["status"] == "review"
    assert record["accepted"] is False
    assert record["execution"]["schema"] == "bach.worker-execution-evidence.v2"
    assert record["execution"]["availability"] == "unavailable"

    assert binding.finish_model_execution(handle, result=_response()) is True
    snapshot, record = _read(context)
    assert snapshot["status"] == "review"
    _assert_execution_available(record["execution"], record, binding)
    task = context["client"].task_snapshot(context["task_id"])
    assert task.get("claim_id") is None


def test_lost_submit_ack_links_only_after_canonical_result_reconciliation(
    worker_context, monkeypatch
):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None
    assert binding.finish_model_execution(handle, result=_response()) is True

    original_submit = context["client"].submit_result
    calls = []

    def commit_then_lose_ack(*args, **kwargs):
        calls.append((args, kwargs))
        original_submit(*args, **kwargs)
        raise RuntimeError("simulated lost response after the canonical commit")

    monkeypatch.setattr(context["client"], "submit_result", commit_then_lose_ack)
    with pytest.raises(LeaseProtocolError):
        _submit(binding, context["task_id"])

    _, before_reconcile = _read(context)
    assert before_reconcile["reason"] == "awaiting_review"
    assert before_reconcile["execution"]["availability"] == "unavailable"
    row = context["conn"].execute(
        "SELECT result_id,link_event_id FROM worker_model_executions WHERE task_id=?",
        (context["task_id"],),
    ).fetchone()
    assert row is not None and row[0] is None and row[1] is None

    state = binding.result_state()
    assert state["reviewed_task_ids"] == (context["task_id"],)
    _, recovered = _read(context)
    assert recovered["accepted"] is False
    _assert_execution_available(recovered["execution"], recovered, binding)
    assert len(calls) == 1


def test_cli_return_after_lost_submit_ack_waits_for_result_reconciliation(
    worker_context, monkeypatch
):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None

    original_submit = context["client"].submit_result
    calls = []

    def commit_then_lose_ack(*args, **kwargs):
        calls.append((args, kwargs))
        original_submit(*args, **kwargs)
        raise RuntimeError("simulated lost response after the canonical commit")

    monkeypatch.setattr(context["client"], "submit_result", commit_then_lose_ack)
    with pytest.raises(LeaseProtocolError):
        _submit(binding, context["task_id"])

    assert binding.finish_model_execution(handle, result=_response()) is True
    _, before_reconcile = _read(context)
    assert before_reconcile["execution"]["availability"] == "unavailable"
    row = context["conn"].execute(
        "SELECT result_id,link_event_id FROM worker_model_executions WHERE task_id=?",
        (context["task_id"],),
    ).fetchone()
    assert row is not None and row[0] is None and row[1] is None

    state = binding.result_state()
    assert state["reviewed_task_ids"] == (context["task_id"],)
    _, recovered = _read(context)
    assert recovered["accepted"] is False
    _assert_execution_available(recovered["execution"], recovered, binding)
    assert len(calls) == 1


def test_fenced_task_edit_keeps_input_and_submission_versions_distinct(worker_context):
    context = worker_context
    binding = context["binding"]
    input_version = binding.task_snapshot()["task_version"]
    handle = _begin(binding)
    assert handle is not None

    binding.execute_task_manage({
        "action": "update",
        "task_id": context["task_id"],
        "description": "Fenced edit between model input and result submission.",
    })
    submission_version = binding.task_snapshot()["task_version"]
    assert submission_version != input_version
    assert binding.finish_model_execution(handle, result=_response()) is True
    _submit(binding, context["task_id"])

    snapshot, record = _read(context)
    assert snapshot["status"] == "review"
    _assert_execution_available(record["execution"], record, binding,
                                input_version=input_version)
    assert record["execution"]["submission_task_version"] == submission_version
    assert record["execution"]["input_task_version"] != record["execution"]["submission_task_version"]


@pytest.mark.parametrize(
    "response,failed",
    [
        (_response(error="upstream error"), False),
        (_response(content="", tool_calls=[]), False),
        (_response(content=None, tool_calls=[None]), False),
        (_response(content=None, tool_calls=[{
            "type": "function", "function": {"name": "  ", "arguments": "{}"},
        }]), False),
        (_response(content=None, tool_calls=[{
            "type": "function", "function": {"name": "tool", "arguments": "[]"},
        }]), False),
        (_response(content=[]), False),
        (_response(), True),
    ],
    ids=["error-response", "empty-response", "non-call-object", "empty-call-name",
         "non-object-call-arguments", "wrong-content-type", "aborted-call"],
)
def test_failed_or_empty_model_return_does_not_link_but_review_submission_remains(
    worker_context, response, failed
):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None
    assert binding.finish_model_execution(handle, result=response, failed=failed) is False

    _submit(binding, context["task_id"])
    snapshot, record = _read(context)

    assert snapshot["status"] == "review"
    assert record["accepted"] is False
    assert record["execution"]["availability"] == "unavailable"
    assert record["execution"]["reason"] in {
        "execution_not_recorded", "execution_evidence_invalid", "submission_not_current",
    }


@pytest.mark.parametrize(
    "stale_kind", ["run_generation", "generation", "stopped", "fence", "task_version"]
)
def test_stale_execution_context_cannot_finish_or_link(worker_context, stale_kind):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None

    conn = context["conn"]
    if stale_kind == "run_generation":
        context["current"]["value"] = False
    elif stale_kind == "generation":
        original_generation = binding._generation
        binding._generation = "stale-execution-generation"
    elif stale_kind == "stopped":
        context["stop"].set()
    elif stale_kind == "fence":
        conn.execute("UPDATE tasks SET claim_fence=claim_fence+1 WHERE id=?", (context["task_id"],))
        conn.commit()
    else:
        conn.execute("UPDATE tasks SET description='changed outside the bound snapshot' WHERE id=?",
                     (context["task_id"],))
        conn.commit()

    assert binding.finish_model_execution(handle, result=_response()) is False
    row = conn.execute(
        "SELECT result_id,link_event_id,linked_at FROM worker_model_executions WHERE task_id=?",
        (context["task_id"],),
    ).fetchone()
    assert row is not None
    assert tuple(row) == (None, None, None)
    if stale_kind == "generation":
        binding._generation = original_generation
    elif stale_kind in {"fence", "task_version"}:
        # The canonical task was deliberately made stale; avoid a cleanup
        # release with the superseded holder reference.
        context["current"]["value"] = False
    if stale_kind == "stopped":
        assert binding.return_lease() is True
        assert context["client"].task_snapshot(context["task_id"])["status"] == "pending"


@pytest.mark.parametrize("forged_handle", [object(), {}, "execution-id", 1],
                         ids=["object", "dict", "string-id", "integer-id"])
def test_foreign_or_fabricated_handle_cannot_confirm_another_binding(worker_context, forged_handle):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None
    assert binding.finish_model_execution(forged_handle, result=_response()) is False

    other_task_id = _insert_task(context["conn"], "Different bound task")
    other_binding, _, _ = _new_binding(
        context["client"], other_task_id, generation="other-execution-generation"
    )
    try:
        assert other_binding.finish_model_execution(handle, result=_response()) is False
        assert binding.finish_model_execution(handle, result=_response()) is True
        _submit(binding, context["task_id"])
        snapshot, record = _read(context)
        assert snapshot["status"] == "review"
        _assert_execution_available(record["execution"], record, binding)
    finally:
        if not other_binding.closed:
            other_binding.return_lease()


def test_submission_payload_cannot_assert_execution_or_reviewer_trust(worker_context):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None
    assert binding.finish_model_execution(handle, result=_response()) is True

    with pytest.raises(LeaseProtocolError):
        binding.execute_task_manage({
            "action": "submit_result",
            "task_id": context["task_id"],
            "result": SUBMISSION,
            "execution": {"verified": True, "response_sha256": "0" * 64},
            "reviewer_id": "worker-slot-2210",
            "claimed_by": "trusted-worker",
        })

    _submit(binding, context["task_id"])
    snapshot, record = _read(context)
    assert snapshot["status"] == "review"
    assert record["accepted"] is False
    _assert_execution_available(record["execution"], record, binding)


@pytest.mark.parametrize("tamper", ["receipt_digest", "link_history_actor"])
def test_changed_execution_receipt_or_link_event_is_unavailable(worker_context, tamper):
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert handle is not None
    assert binding.finish_model_execution(handle, result=_response()) is True
    _submit(binding, context["task_id"])
    _, record = _read(context)
    assert record["execution"]["availability"] == "available"

    conn = context["conn"]
    row = conn.execute(
        "SELECT id,link_event_id FROM worker_model_executions WHERE result_id=?",
        (record["result_id"],),
    ).fetchone()
    assert row is not None and row[1] is not None
    if tamper == "receipt_digest":
        conn.execute("UPDATE worker_model_executions SET receipt_sha256=? WHERE id=?",
                     ("0" * 64, row[0]))
    else:
        conn.execute("UPDATE task_history SET changed_by=? WHERE id=?",
                     ("unrelated-actor", row[1]))
    conn.commit()

    snapshot, changed = _read(context)
    assert snapshot["status"] == "review"
    assert changed["accepted"] is False
    assert changed["execution"]["availability"] == "unavailable"
    assert changed["execution"]["reason"] == "execution_evidence_invalid"


def test_readback_is_query_only_and_missing_execution_schema_stays_unavailable(worker_context):
    context = worker_context
    binding = context["binding"]
    _submit(binding, context["task_id"])
    conn = context["conn"]
    conn.execute("DROP TABLE IF EXISTS worker_model_executions")
    conn.commit()
    before = _schema_objects(conn)

    conn.execute("PRAGMA query_only=ON")
    first, record = _read(context)
    second, second_record = _read(context)
    assert first == second
    assert record["execution"]["availability"] == "unavailable"
    assert record["execution"]["reason"] in {
        "execution_not_recorded", "execution_schema_unavailable",
    }
    assert second_record["execution"] == record["execution"]
    assert _schema_objects(conn) == before
    conn.execute("PRAGMA query_only=OFF")


def test_remote_task_client_does_not_start_execution_or_fallback_to_local_db(
    worker_context, monkeypatch
):
    context = worker_context
    remote = TaskLeaseClient(
        conn=context["conn"], lead_url="https://lead.invalid", device_token="fixture-token"
    )
    assert remote.mode == "remote"
    requests = []

    def forbidden_http(*args, **kwargs):
        requests.append((args, kwargs))
        pytest.fail("Execution-Selbstauskunft darf keinen zusätzlichen HTTP-Aufruf starten")

    monkeypatch.setattr(remote, "_http_request", forbidden_http)
    before = _schema_objects(context["conn"])
    handle = remote._start_model_execution(
        context["binding"],
        backend_id=BACKEND,
        requested_model=REQUESTED_MODEL,
        slot_id=SLOT_ID,
        request_sha256=_request_sha(),
    )

    assert handle is None
    assert requests == []
    assert _schema_objects(context["conn"]) == before


@pytest.mark.parametrize("response,failed,failure,expected", [
    (_response(content=""), False, None, "empty_answer"),
    (_response(content="", tool_calls=[{"function": {"name": "write_file", "arguments": '{"path": "x'}}]),
     False, None, "invalid_tool_call"),
    (None, True, "backend_error:openrouter:http_error:400", "backend_error:openrouter:http_error:400"),
    (None, True, "Anbieter sagt: PRIVATE_PROVIDER_TEXT", "call_failed"),
])
def test_failed_model_execution_records_fixed_failure_code(worker_context, caplog, response, failed,
                                                           failure, expected):
    caplog.set_level("INFO", logger="bach.chat")
    context = worker_context
    binding = context["binding"]
    handle = _begin(binding)
    assert binding.finish_model_execution(handle, result=response, failed=failed, failure=failure) is False
    phase, receipt = context["conn"].execute(
        "SELECT phase, receipt FROM worker_model_executions WHERE task_id=?", (context["task_id"],)).fetchone()
    assert phase == "failed" and json.loads(receipt)["failure_code"] == expected
    terminal = context["conn"].execute(
        "SELECT new_value FROM task_history WHERE task_id=? AND action='worker_model_execution_terminal'",
        (context["task_id"],)).fetchone()[0]
    assert json.loads(terminal)["failure_code"] == expected
    assert (f"model_execution_failed code={expected} task_id={context['task_id']} "
            f"generation={GENERATION}") in caplog.text
    assert "PRIVATE_PROVIDER_TEXT" not in caplog.text + receipt + terminal


def test_failure_code_uses_only_the_normalized_backend_error():
    from hub._services.llm.backend_errors import BackendRequestFailure
    from hub._services.worker_execution_evidence import failure_code

    error = BackendRequestFailure({"provider": "openrouter", "kind": "http_error", "error_type": "HTTPStatusError",
                                   "quota_exceeded": False, "status_code": 400})
    assert failure_code(error=error) == "backend_error:openrouter:http_error:400"
    assert failure_code(error=RuntimeError("PRIVATE_PROVIDER_TEXT")) == "call_exception"
    assert failure_code({"error": "PRIVATE_PROVIDER_TEXT"}) == "backend_error:unclassified"


def test_returned_model_execution_has_no_failure_code(worker_context):
    context = worker_context
    handle = _begin(context["binding"])
    assert context["binding"].finish_model_execution(handle, result=_response()) is True
    receipt = context["conn"].execute("SELECT receipt FROM worker_model_executions").fetchone()[0]
    assert "failure_code" not in json.loads(receipt)
