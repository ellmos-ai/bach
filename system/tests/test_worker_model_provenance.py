# SPDX-License-Identifier: MIT
"""Provider-reported model provenance through the real private execution ledger.

The tests use the existing temporary TaskLeaseClient/WorkerLeaseBinding fixture.
The OpenAI adapter's HTTP transport is replaced with deterministic responses;
no provider request, model process, or task acceptance is involved.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

import pytest

from hub._services import worker_execution_evidence
from hub._services.task_result_service import read_result
from system.tests.test_task_lease_client import mem_db  # registers worker_context's dependency
from system.tests.test_worker_execution_evidence import (
    BACKEND,
    RAW_REQUEST,
    REQUESTED_MODEL,
    SLOT_ID,
    _response,
    _schema_objects,
    _submit,
    worker_context,
)


_RAW_RESPONSE = "Local result text used only as a digest input."
_REQUEST_SHA256 = hashlib.sha256(RAW_REQUEST.encode("utf-8")).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _read(context):
    data = read_result(context["conn"], context["task_id"])
    return data, data.get("result")


def _begin(binding, *, backend_id=BACKEND):
    return binding.begin_model_execution(
        backend_id=backend_id,
        requested_model=REQUESTED_MODEL,
        slot_id=SLOT_ID,
        request_sha256=_REQUEST_SHA256,
    )


def _finish_and_submit(context, answer, *, backend_id=BACKEND):
    binding = context["binding"]
    handle = _begin(binding, backend_id=backend_id)
    assert handle is not None
    start_row = context["conn"].execute(
        "SELECT receipt FROM worker_model_executions WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
        (context["task_id"],),
    ).fetchone()
    assert start_row is not None
    start_receipt = json.loads(start_row[0])
    assert start_receipt["schema"] == "bach.worker-model-execution.v2"
    assert start_receipt["model_provenance"] == "unknown"
    assert start_receipt["observed_model"] is None
    assert binding.finish_model_execution(handle, result=answer) is True
    _submit(binding, context["task_id"])
    readback, record = _read(context)
    assert readback["status"] == "review"
    assert record["accepted"] is False
    return record


def _model_execution_row(conn, result_id):
    row = conn.execute(
        "SELECT * FROM worker_model_executions WHERE result_id=?", (result_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _replace_receipt_and_history(conn, row, record, receipt):
    """Rebuild the coherent immutable event chain around a synthetic receipt."""
    receipt_sha256 = _digest(receipt)
    conn.execute(
        "UPDATE worker_model_executions SET receipt=?,receipt_sha256=? WHERE id=?",
        (_json(receipt), receipt_sha256, row["id"]),
    )

    started = dict(receipt, phase="attempted", returned_at=None,
                   response_sha256=None, observed_model=None)
    if receipt.get("schema") == "bach.worker-model-execution.v2":
        started["model_provenance"] = "unknown"
    conn.execute(
        "UPDATE task_history SET new_value=? WHERE id=?",
        (_json(started), row["started_event_id"]),
    )
    terminal = {"execution_id": row["id"], "phase": "returned",
                "receipt_sha256": receipt_sha256}
    conn.execute(
        "UPDATE task_history SET new_value=? WHERE id=?",
        (_json(terminal), row["terminal_event_id"]),
    )

    revised_row = dict(row, receipt_sha256=receipt_sha256)
    revision = worker_execution_evidence._revision(revised_row, record)
    link = {
        "execution_id": row["id"],
        "execution_revision": revision,
        "result_id": record["result_id"],
        "submission_revision": record["submission_revision"],
        "submission_task_version": record["task_version"],
        "linked_at": row["linked_at"],
    }
    conn.execute(
        "UPDATE task_history SET new_value=? WHERE id=?",
        (_json(link), row["link_event_id"]),
    )
    conn.commit()
    return revision


@pytest.mark.parametrize(
    "case",
    ["missing", "blank", "non_string", "raw_response_model_only"],
)
def test_missing_or_invalid_provider_model_keeps_execution_available_but_unknown(
    worker_context, case,
):
    context = worker_context
    answer = {
        "model": "display-fallback-model",
        "content": _RAW_RESPONSE,
        "tool_calls": None,
    }
    if case == "blank":
        answer["provider_reported_model"] = "  "
    elif case == "non_string":
        answer["provider_reported_model"] = 17
    elif case == "raw_response_model_only":
        answer["raw_response"] = {"model": "untrusted-raw-model"}

    record = _finish_and_submit(context, answer)
    execution = record["execution"]
    assert execution["schema"] == "bach.worker-execution-evidence.v2"
    assert execution["availability"] == "available"
    assert execution["requested_model"] == REQUESTED_MODEL
    assert execution["observed_model"] is None
    assert execution["model_provenance"] == "unknown"
    assert re.fullmatch(r"[a-f0-9]{64}", execution["response_sha256"])


@pytest.mark.parametrize(
    ("provider_model", "expected_observed", "expected_provenance"),
    [
        (None, None, "unknown"),
        ("provider-served-model-42", "provider-served-model-42", "provider_reported"),
    ],
    ids=["provider-omitted", "provider-reports-model-different-from-request"],
)
def test_openai_backend_reported_model_flows_through_binding_and_ledger(
    worker_context, monkeypatch, provider_model, expected_observed, expected_provenance,
):
    import httpx
    from hub._services.llm.model_backend import OpenAIBackend

    calls = []
    provider_message = {
        "content": "Answer from the deterministic OpenAI transport fixture.",
        # This nested field must not be promoted to provider-level provenance.
        "model": "message-only-untrusted-model",
    }
    provider_response = {"choices": [{"message": provider_message}]}
    if provider_model is not None:
        provider_response["model"] = provider_model

    class FakeResponse:
        def json(self):
            return provider_response

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, json, headers, timeout):
            calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    backend = OpenAIBackend(
        base_url="https://provider.invalid/v1",
        api_key="test-only-openai-token",
        default_model="default-display-model",
    )
    adapter_answer = asyncio.run(backend.chat(
        [{"role": "user", "content": "fixture request"}],
        model=REQUESTED_MODEL,
    ))

    assert adapter_answer["provider_reported_model"] == expected_observed
    assert adapter_answer["model"] == (expected_observed or REQUESTED_MODEL)
    assert adapter_answer["raw_message"]["model"] == "message-only-untrusted-model"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://provider.invalid/v1/chat/completions"
    assert calls[0]["json"]["model"] == REQUESTED_MODEL
    assert calls[0]["headers"]["Authorization"] == "Bearer test-only-openai-token"

    record = _finish_and_submit(context, adapter_answer, backend_id="openai")
    execution = record["execution"]
    assert execution["availability"] == "available"
    assert execution["requested_model"] == REQUESTED_MODEL
    assert execution["observed_model"] == expected_observed
    assert execution["model_provenance"] == expected_provenance
    assert "test-only-openai-token" not in json.dumps(execution, sort_keys=True)


def test_legacy_v1_placeholder_is_projected_as_unknown_without_read_writes(worker_context):
    context = worker_context
    record = _finish_and_submit(context, _response())
    conn = context["conn"]
    row = _model_execution_row(conn, record["result_id"])
    assert row is not None
    receipt = json.loads(row["receipt"])
    receipt["schema"] = "bach.worker-model-execution.v1"
    receipt.pop("model_provenance", None)
    # Valid old v1 could contain a display/request fallback as observed_model.
    receipt["observed_model"] = "legacy-display-fallback"
    expected_revision = _replace_receipt_and_history(conn, row, record, receipt)

    before_schema = _schema_objects(conn)
    before_row = tuple(conn.execute(
        "SELECT * FROM worker_model_executions WHERE result_id=?", (record["result_id"],),
    ).fetchone())
    before_events = tuple(tuple(event) for event in conn.execute(
        "SELECT * FROM task_history WHERE task_id=? ORDER BY id", (context["task_id"],),
    ))

    _, read_record = _read(context)
    execution = read_record["execution"]
    assert execution["schema"] == "bach.worker-execution-evidence.v2"
    assert execution["availability"] == "available"
    assert execution["requested_model"] == REQUESTED_MODEL
    assert execution["observed_model"] is None
    assert execution["model_provenance"] == "legacy_unknown"
    assert execution["execution_revision"] == expected_revision

    assert _schema_objects(conn) == before_schema
    assert tuple(conn.execute(
        "SELECT * FROM worker_model_executions WHERE result_id=?", (record["result_id"],),
    ).fetchone()) == before_row
    assert tuple(tuple(event) for event in conn.execute(
        "SELECT * FROM task_history WHERE task_id=? ORDER BY id", (context["task_id"],),
    )) == before_events
    assert json.loads(_model_execution_row(conn, record["result_id"])["receipt"])["observed_model"] == "legacy-display-fallback"


@pytest.mark.parametrize(
    ("provenance", "observed"),
    [
        ("provider_reported", None),
        ("unknown", "unjustified-model"),
        ("provider_reported", " invalid-model "),
        ("not-a-provenance", None),
    ],
    ids=["reported-without-model", "unknown-with-model", "invalid-reported-model", "unknown-provenance"],
)
def test_v2_provenance_observed_model_inconsistency_is_unavailable(
    worker_context, provenance, observed,
):
    context = worker_context
    record = _finish_and_submit(context, _response())
    conn = context["conn"]
    row = _model_execution_row(conn, record["result_id"])
    assert row is not None
    receipt = json.loads(row["receipt"])
    receipt["schema"] = "bach.worker-model-execution.v2"
    receipt["model_provenance"] = provenance
    receipt["observed_model"] = observed
    _replace_receipt_and_history(conn, row, record, receipt)

    before_schema = _schema_objects(conn)
    before_row = tuple(conn.execute(
        "SELECT * FROM worker_model_executions WHERE result_id=?", (record["result_id"],),
    ).fetchone())
    before_events = tuple(tuple(event) for event in conn.execute(
        "SELECT * FROM task_history WHERE task_id=? ORDER BY id", (context["task_id"],),
    ))

    _, read_record = _read(context)
    assert read_record["execution"]["schema"] == "bach.worker-execution-evidence.v2"
    assert read_record["execution"]["availability"] == "unavailable"
    assert read_record["execution"]["reason"] == "execution_evidence_invalid"
    assert _schema_objects(conn) == before_schema
    assert tuple(conn.execute(
        "SELECT * FROM worker_model_executions WHERE result_id=?", (record["result_id"],),
    ).fetchone()) == before_row
    assert tuple(tuple(event) for event in conn.execute(
        "SELECT * FROM task_history WHERE task_id=? ORDER BY id", (context["task_id"],),
    )) == before_events
