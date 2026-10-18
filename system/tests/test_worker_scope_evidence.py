# SPDX-License-Identifier: MIT
"""Behavioral tests for immutable, result-bound worker scope receipts.

These tests reuse the real temporary TaskLeaseClient/WorkerLeaseBinding and
submission fixtures. Git snapshots are deterministic test inputs; they do not
stand in for the separate real-Git adapter tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

import pytest

from hub._services import worker_scope_evidence
from hub._services.task_result_service import read_result, request_result_correction
from system.tests.test_task_result_correction import _correction_payload, _operator
from system.tests.test_task_lease_client import mem_db
from system.tests.test_worker_execution_evidence import (
    _begin as _begin_execution,
    _response,
    _schema_objects,
    _submit,
    worker_context,
)


_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _hash_json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _scope_snapshot(task_id, *, head_oid="a" * 40, tree_oid="b" * 40,
                    status_sha256=_EMPTY_SHA256, availability="available"):
    snapshot = {
        "schema": "bach.task-scope-snapshot.v1",
        "availability": availability,
        "task_id": task_id,
        "repository": "ellmos-ai/bach",
        "origin": "https://github.com/ellmos-ai/bach",
        "branch": f"refs/heads/bach-task/{task_id}",
        "head_oid": head_oid,
        "tree_oid": tree_oid,
        "repo_path_sha256": "1" * 64,
        "worktree_path_sha256": "2" * 64,
        "common_dir_sha256": "3" * 64,
        "source_pin": None,
        "clean_scope": "porcelain-v1-z-all-untracked-no-ignored",
        "status_sha256": status_sha256,
        "index_sha256": "4" * 64,
        "project_state_ref": "",
        "workspace_fingerprint": "",
    }
    snapshot["project_state_ref"] = _hash_json({
        "repository": snapshot["repository"],
        "origin": snapshot["origin"],
        "source_pin": snapshot["source_pin"],
        "head_oid": snapshot["head_oid"],
    })
    snapshot["workspace_fingerprint"] = _hash_json({
        "worktree_path_sha256": snapshot["worktree_path_sha256"],
        "common_dir_sha256": snapshot["common_dir_sha256"],
        "branch": snapshot["branch"],
        "tree_oid": snapshot["tree_oid"],
        "clean_scope": snapshot["clean_scope"],
        "status_sha256": snapshot["status_sha256"],
        "index_sha256": snapshot["index_sha256"],
    })
    return snapshot


def _review_submission(context, *, with_execution=True):
    binding = context["binding"]
    if with_execution:
        handle = _begin_execution(binding)
        assert handle is not None
        assert binding.finish_model_execution(handle, result=_response()) is True
    _submit(binding, context["task_id"])
    readback, record = _read(context)
    assert readback["status"] == "review"
    assert record["accepted"] is False
    return readback, record


def _install_snapshot(monkeypatch, context, snapshot, *, observe_transaction=False):
    calls = []

    def snapshot_reader(task_id, **kwargs):
        assert task_id == context["task_id"]
        if observe_transaction:
            assert context["conn"].in_transaction is False
        calls.append(kwargs)
        return copy.deepcopy(snapshot)

    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", snapshot_reader)
    return calls


def _read(context):
    readback = read_result(context["conn"], context["task_id"])
    return readback, readback.get("result")


def _scope_row(context, result_id):
    table = context["conn"].execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_scope_evidence'"
    ).fetchone()
    if table is None:
        return None
    return context["conn"].execute(
        "SELECT * FROM worker_scope_evidence WHERE result_id=?", (result_id,)
    ).fetchone()


def test_scope_capture_is_result_bound_event_backed_and_idempotent(
    worker_context, monkeypatch, tmp_path,
):
    context = worker_context
    binding = context["binding"]
    _, record = _review_submission(context)
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", record["submission_revision"])
    snapshot = _scope_snapshot(context["task_id"])
    calls = _install_snapshot(monkeypatch, context, snapshot, observe_transaction=True)

    assert worker_scope_evidence.capture_scope_evidence(context["conn"], binding) is True
    readback, captured = _read(context)
    scope = captured["scope"]
    assert scope["schema"] == "bach.worker-scope-evidence.v1"
    assert scope["availability"] == "recorded"
    assert scope["task_id"] == context["task_id"]
    assert scope["result_id"] == record["result_id"]
    assert scope["submission_revision"] == record["submission_revision"]
    assert scope["task_scope_version"] == record["task_version"]
    assert scope["snapshot"] == snapshot
    assert scope["execution_revision"] == captured["execution"]["execution_revision"]
    assert len(calls) == 1

    row = _scope_row(context, record["result_id"])
    assert row is not None
    assert row["task_version"] == record["task_version"]
    assert row["submission_revision"] == record["submission_revision"]
    assert row["receipt_sha256"] == scope["scope_receipt_sha256"]
    assert row["event_id"] == scope["scope_event_id"]
    event = context["conn"].execute(
        "SELECT * FROM task_history WHERE id=?", (scope["scope_event_id"],)
    ).fetchone()
    assert event is not None
    assert event["action"] == "worker_result_scope_capture"
    assert event["field_changed"] == "lease"
    assert event["changed_by"] == "native-scope-controller"
    assert event["old_value"] is None
    assert json.loads(event["new_value"]) == {
        "task_id": context["task_id"],
        "result_id": record["result_id"],
        "fence": record["fence"],
        "generation": record["generation"],
        "submission_revision": record["submission_revision"],
        "task_scope_version": record["task_version"],
        "scope_receipt_sha256": scope["scope_receipt_sha256"],
        "captured_at": row["captured_at"],
    }

    before = tuple(row)
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], binding) is True
    changed = _scope_snapshot(context["task_id"], head_oid="c" * 40, tree_oid="d" * 40)
    _install_snapshot(monkeypatch, context, changed)
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], binding) is False
    assert tuple(_scope_row(context, record["result_id"])) == before
    assert context["conn"].execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_result_scope_capture'",
        (context["task_id"],),
    ).fetchone()[0] == 1

    _install_snapshot(monkeypatch, context, snapshot)
    projected = worker_scope_evidence.project_scope_evidence(
        scope, repo_root=tmp_path / "repo", worktrees_dir=tmp_path / "worktrees",
    )
    assert projected["availability"] == "available"
    assert re.fullmatch(r"[a-f0-9]{64}", projected["result_revision"])
    projected_readback = worker_scope_evidence.project_scope_evidence(
        readback, repo_root=tmp_path / "repo", worktrees_dir=tmp_path / "worktrees",
    )
    assert projected_readback["result"]["scope"]["availability"] == "available"
    assert projected_readback["result"]["result_revision"] == projected["result_revision"]


def test_sdk_task_result_snapshot_projects_current_scope_after_readback(
    worker_context, monkeypatch,
):
    context = worker_context
    _, record = _review_submission(context)
    snapshot = _scope_snapshot(context["task_id"])
    _install_snapshot(monkeypatch, context, snapshot)
    assert worker_scope_evidence.capture_scope_evidence(
        context["conn"], context["binding"],
    ) is True

    calls = _install_snapshot(monkeypatch, context, snapshot, observe_transaction=True)
    readback = context["client"].task_result_snapshot(context["task_id"])
    projected = readback["result"]
    assert projected["result_id"] == record["result_id"]
    assert projected["scope"]["availability"] == "available"
    assert projected["result_revision"] == projected["scope"]["result_revision"]
    assert re.fullmatch(r"[a-f0-9]{64}", projected["result_revision"])
    assert len(calls) == 1


def test_scope_receipt_can_precede_cli_return_and_revision_is_projected_later(
    worker_context, monkeypatch, tmp_path,
):
    context = worker_context
    binding = context["binding"]
    handle = _begin_execution(binding)
    assert handle is not None
    _submit(binding, context["task_id"])
    _, before = _read(context)
    assert before["execution"]["availability"] == "unavailable"

    snapshot = _scope_snapshot(context["task_id"])
    _install_snapshot(monkeypatch, context, snapshot)
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], binding) is True
    _, captured_before_return = _read(context)
    scope_before = captured_before_return["scope"]
    assert scope_before["availability"] == "recorded"
    assert scope_before["execution_revision"] is None
    assert scope_before["result_revision"] is None
    row_before = _scope_row(context, before["result_id"])
    immutable_before = tuple(row_before)

    assert binding.finish_model_execution(handle, result=_response()) is True
    _, after = _read(context)
    assert after["execution"]["availability"] == "available"
    assert after["scope"]["scope_receipt_sha256"] == scope_before["scope_receipt_sha256"]
    assert after["scope"]["scope_event_id"] == scope_before["scope_event_id"]
    assert after["scope"]["execution_revision"] == after["execution"]["execution_revision"]
    assert tuple(_scope_row(context, before["result_id"])) == immutable_before

    projected = worker_scope_evidence.project_scope_evidence(
        after["scope"], repo_root=tmp_path / "repo", worktrees_dir=tmp_path / "worktrees",
    )
    assert projected["availability"] == "available"
    assert re.fullmatch(r"[a-f0-9]{64}", projected["result_revision"])


def test_scope_capture_reconciles_canonical_submission_after_lost_ack(
    worker_context, monkeypatch,
):
    context = worker_context
    binding = context["binding"]
    client = context["client"]
    original_submit = client.submit_result

    def commit_then_lose_ack(*args, **kwargs):
        original_submit(*args, **kwargs)
        raise RuntimeError("isolierter verlorener Submit-ACK")

    monkeypatch.setattr(client, "submit_result", commit_then_lose_ack)
    from hub._services.task_lease_client import LeaseProtocolError
    with pytest.raises(LeaseProtocolError):
        _submit(binding, context["task_id"])

    readback, record = _read(context)
    assert readback["status"] == "review"
    assert record["reason"] == "awaiting_review"
    _install_snapshot(monkeypatch, context, _scope_snapshot(context["task_id"]))
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], binding) is True
    _, recovered = _read(context)
    assert recovered["accepted"] is False
    assert recovered["scope"]["availability"] == "recorded"
    assert recovered["scope"]["result_id"] == record["result_id"]


def test_scope_capture_rechecks_canonical_submission_after_snapshot_read(
    worker_context, monkeypatch,
):
    context = worker_context
    _, record = _review_submission(context, with_execution=False)
    conn = context["conn"]
    before_schema = _schema_objects(conn)

    def snapshot_then_concurrent_task_edit(task_id):
        assert task_id == context["task_id"]
        assert conn.in_transaction is False
        snapshot = _scope_snapshot(task_id)
        conn.execute("UPDATE tasks SET description=? WHERE id=?",
                     ("Changed during Git snapshot", task_id))
        conn.commit()
        return snapshot

    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope",
                        snapshot_then_concurrent_task_edit)
    assert worker_scope_evidence.capture_scope_evidence(conn, context["binding"]) is False
    assert _scope_row(context, record["result_id"]) is None
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_result_scope_capture'",
        (context["task_id"],),
    ).fetchone()[0] == 0
    assert _schema_objects(conn) == before_schema
    context["current"]["value"] = False


def test_correction_makes_old_scope_submission_unavailable(worker_context, monkeypatch):
    context = worker_context
    _, record = _review_submission(context)
    _install_snapshot(monkeypatch, context, _scope_snapshot(context["task_id"]))
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], context["binding"]) is True
    before = _scope_row(context, record["result_id"])
    assert before is not None

    readback, _ = _read(context)
    operator_token = _operator(context["conn"], correction=True)
    request_result_correction(
        context["conn"], context["task_id"], _correction_payload(readback),
        operator_token=operator_token,
    )
    corrected, current_record = _read(context)
    assert corrected["status"] == "pending"
    assert current_record["scope"]["availability"] == "unavailable"
    assert current_record["scope"]["reason"] == "submission_not_current"
    assert current_record["scope"]["result_revision"] is None
    assert tuple(_scope_row(context, record["result_id"])) == tuple(before)


@pytest.mark.parametrize("current_state", ["same", "stale_head", "dirty", "unavailable"])
def test_scope_projection_requires_same_current_clean_git_snapshot(
    worker_context, monkeypatch, tmp_path, current_state,
):
    context = worker_context
    _, record = _review_submission(context)
    recorded = _scope_snapshot(context["task_id"])
    _install_snapshot(monkeypatch, context, recorded)
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], context["binding"]) is True
    _, readback = _read(context)
    scope = readback["scope"]

    if current_state == "same":
        current = recorded
    elif current_state == "stale_head":
        current = _scope_snapshot(context["task_id"], head_oid="c" * 40, tree_oid="d" * 40)
    elif current_state == "dirty":
        current = {**recorded, "availability": "unavailable", "reason": "worktree_dirty"}
    else:
        current = {"schema": "bach.task-scope-snapshot.v1", "availability": "unavailable",
                   "task_id": context["task_id"], "reason": "repository_unavailable"}
    _install_snapshot(monkeypatch, context, current)
    projected = worker_scope_evidence.project_scope_evidence(
        scope, repo_root=tmp_path / "repo", worktrees_dir=tmp_path / "worktrees",
    )

    if current_state == "same":
        assert projected["availability"] == "available"
        assert re.fullmatch(r"[a-f0-9]{64}", projected["result_revision"])
    else:
        assert projected["availability"] == "unavailable"
        assert projected["result_revision"] is None
        assert projected["reason"] == (
            "current_git_changed" if current_state == "stale_head" else "current_git_unavailable"
        )


def test_scope_only_projection_never_claims_full_result_revision(worker_context, monkeypatch, tmp_path):
    context = worker_context
    _, record = _review_submission(context, with_execution=False)
    snapshot = _scope_snapshot(context["task_id"])
    _install_snapshot(monkeypatch, context, snapshot)
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], context["binding"]) is True
    _, readback = _read(context)
    scope = readback["scope"]
    assert scope["execution_revision"] is None

    _install_snapshot(monkeypatch, context, snapshot)
    projected = worker_scope_evidence.project_scope_evidence(
        scope, repo_root=tmp_path / "repo", worktrees_dir=tmp_path / "worktrees",
    )
    assert projected["availability"] == "available"
    assert projected["result_revision"] is None

    forged = {**scope, "execution_revision": "not-a-valid-execution-revision"}
    _install_snapshot(monkeypatch, context, snapshot)
    still_scope_only = worker_scope_evidence.project_scope_evidence(
        forged, repo_root=tmp_path / "repo", worktrees_dir=tmp_path / "worktrees",
    )
    assert still_scope_only["availability"] == "available"
    assert still_scope_only["result_revision"] is None


@pytest.mark.parametrize(
    "tamper",
    ["receipt_digest", "receipt_snapshot", "row_task_id", "row_fence", "row_generation",
     "row_task_version", "row_submission_revision", "row_event_id", "event_actor", "event_detail"],
)
def test_scope_receipt_and_history_tampering_is_unavailable(worker_context, monkeypatch, tamper):
    context = worker_context
    _, record = _review_submission(context)
    _install_snapshot(monkeypatch, context, _scope_snapshot(context["task_id"]))
    assert worker_scope_evidence.capture_scope_evidence(context["conn"], context["binding"]) is True
    conn = context["conn"]
    row = _scope_row(context, record["result_id"])
    assert row is not None

    if tamper == "receipt_digest":
        conn.execute("UPDATE worker_scope_evidence SET receipt_sha256=? WHERE result_id=?",
                     ("0" * 64, record["result_id"]))
    elif tamper == "receipt_snapshot":
        receipt = json.loads(row["receipt"])
        receipt["snapshot"]["head_oid"] = "f" * 40
        conn.execute("UPDATE worker_scope_evidence SET receipt=? WHERE result_id=?",
                     (json.dumps(receipt, sort_keys=True, separators=(",", ":")), record["result_id"]))
    elif tamper == "row_task_id":
        conn.execute("UPDATE worker_scope_evidence SET task_id=? WHERE result_id=?",
                     (context["task_id"] + 1, record["result_id"]))
    elif tamper == "row_fence":
        conn.execute("UPDATE worker_scope_evidence SET fence=fence+1 WHERE result_id=?",
                     (record["result_id"],))
    elif tamper == "row_generation":
        conn.execute("UPDATE worker_scope_evidence SET generation='foreign-generation' WHERE result_id=?",
                     (record["result_id"],))
    elif tamper == "row_task_version":
        conn.execute("UPDATE worker_scope_evidence SET task_version=? WHERE result_id=?",
                     ("0" * 64, record["result_id"]))
    elif tamper == "row_submission_revision":
        conn.execute("UPDATE worker_scope_evidence SET submission_revision=? WHERE result_id=?",
                     ("0" * 64, record["result_id"]))
    elif tamper == "row_event_id":
        conn.execute("UPDATE worker_scope_evidence SET event_id=? WHERE result_id=?",
                     (record["submission_event_id"], record["result_id"]))
    elif tamper == "event_actor":
        conn.execute("UPDATE task_history SET changed_by='unrelated-actor' WHERE id=?",
                     (row["event_id"],))
    else:
        conn.execute("UPDATE task_history SET new_value='{}' WHERE id=?", (row["event_id"],))
    conn.commit()

    _, changed = _read(context)
    assert changed["scope"]["availability"] == "unavailable"
    assert changed["scope"]["reason"] == "scope_evidence_invalid"
    assert changed["scope"]["result_revision"] is None


def test_scope_reader_is_query_only_and_missing_schema_does_not_migrate(
    worker_context, monkeypatch,
):
    context = worker_context
    binding = context["binding"]
    _, record = _review_submission(context, with_execution=False)
    conn = context["conn"]
    before = _schema_objects(conn)
    _install_snapshot(monkeypatch, context, _scope_snapshot(context["task_id"]))

    conn.execute("PRAGMA query_only=ON")
    try:
        first = worker_scope_evidence.read_scope_evidence(conn, record)
        second = worker_scope_evidence.read_scope_evidence(conn, record)
        _, readback = _read(context)
        assert first == second
        assert first["availability"] == "unavailable"
        assert first["reason"] == "scope_not_recorded"
        assert readback["scope"] == first
        assert _schema_objects(conn) == before
        assert worker_scope_evidence.capture_scope_evidence(conn, binding) is False
        assert _schema_objects(conn) == before
    finally:
        conn.execute("PRAGMA query_only=OFF")


def test_optional_scope_capture_failure_does_not_block_personal_review_submission(
    worker_context, monkeypatch,
):
    context = worker_context
    _, submitted = _review_submission(context, with_execution=False)

    def unavailable_git(_task_id):
        raise OSError("isolated Git snapshot unavailable")

    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", unavailable_git)
    assert worker_scope_evidence.capture_scope_evidence(
        context["conn"], context["binding"],
    ) is False
    snapshot, record = _read(context)
    assert snapshot["status"] == "review"
    assert record["accepted"] is False
    assert record["reason"] == "awaiting_review"
    assert record["result_id"] == submitted["result_id"]
    assert record["scope"]["availability"] == "unavailable"
    assert record["scope"]["reason"] == "scope_not_recorded"
    assert _scope_row(context, submitted["result_id"]) is None
