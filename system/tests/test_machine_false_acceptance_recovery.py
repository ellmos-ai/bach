"""Real SQLite and Git regression for a historical false machine acceptance."""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest

from hub._services import worker_completion_policy as policy
from hub._services import worker_result_review as review
from hub._services.machine_false_acceptance_recovery import SCHEMA
from hub._services.task_lease_client import TaskLeaseClient
from hub._services.task_result_service import (
    ResultConflict, ensure_result_correction_schema, read_result, read_result_history,
)
from system.tests.test_worker_completion_policy import (
    AUTHOR, AUTHOR_MODEL, AUTHOR_OBSERVED, AUTHOR_ROUTE, IDENTITY_KEY,
    STANDARD_MODEL, STANDARD_OBSERVED, STANDARD_REVIEWER, STANDARD_ROUTE,
    _identity, _paths, _record_independent_review, completion_world, settings,
)
from system.tests.test_worker_execution_evidence import worker_context
from system.tests.test_task_lease_client import mem_db


def _false_acceptance(completion_world, monkeypatch):
    from hub import worker_git

    world = completion_world(mode="balanced", contract_min_chars=12, contract_git_blob=True)
    conn, client, task_id = world["conn"], world["client"], world["task_id"]
    ensure_result_correction_schema(conn)
    conn.commit()
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: world["tree"]["worktrees"])
    current_evaluator = policy.evaluate_current_result

    def historical_evaluator(*args, **kwargs):
        value = current_evaluator(*args, **kwargs)
        if (value.get("availability") == "available"
                and value.get("contract_finding", {}).get("reviewer_asserted_task_contract_met") is False):
            # Reproduce the old bug's decision while leaving every real
            # submission, scope, execution, identity and review row intact.
            value = dict(value)
            value["decision"] = dict(value["decision"], state="completed",
                reason="non_blocking_review_findings", completion_allowed=True,
                dependents_may_start=True)
        return value

    with monkeypatch.context() as old_policy:
        old_policy.setattr(policy, "evaluate_current_result", historical_evaluator)
        _record_independent_review(world, status="findings", task_contract_met=False,
                                   read_current_evidence=False)
        if read_result(conn, task_id)["status"] == "review":
            policy.reconcile_current_result(conn, task_id, **_paths(world))

    snapshot = client.task_result_snapshot(task_id)
    result = snapshot["result"]
    assert snapshot["status"] == "done" and result["accepted"] is True
    assert result["accepted_by"] == "native-worker-completion-policy"
    assert result["model_review"]["status"] == "findings"
    assert result["model_review"]["reviewer_asserted_task_contract_met"] is False
    corrected = policy.evaluate_current_result(conn, task_id, **_paths(world))
    assert corrected["decision"]["state"] == "correction_required"
    expected = {
        "result_id": result["result_id"],
        "result_sha256": result["result_sha256"],
        "result_revision": result["result_revision"],
        "task_version": snapshot["task_version"],
        "status_revision": snapshot["status_revision"],
        "acceptance_event_id": result["acceptance_event_id"],
        "completion_decision_event_id": result["completion_decision_event_id"],
        "completion_decision_sha256": result["completion_decision_sha256"],
        "review_event_id": result["model_review"]["event_id"],
        "review_task_id": result["model_review"]["review_task_id"],
        "child_result_id": result["model_review"]["child_result_id"],
    }
    return world, expected


def _repair(world, expected, request_id=None):
    return world["client"]._repair_machine_false_acceptance(
        world["task_id"], expected=expected, request_id=request_id or str(uuid.uuid4()),
        **_paths(world))


def test_requeues_exact_false_acceptance_preserving_original_history(
    completion_world, monkeypatch,
):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    conn, task_id = world["conn"], world["task_id"]
    old = dict(conn.execute("SELECT * FROM worker_task_results WHERE id=?",
                            (expected["result_id"],)).fetchone())
    ack = _repair(world, expected)
    assert ack["schema"] == SCHEMA and ack["status"] == "pending"
    assert ack["replayed"] is False
    task = world["client"].task_snapshot(task_id)
    assert task["status"] == "pending"
    assert task["result_correction_request_id"] == ack["correction_id"]
    current = world["client"].task_result_snapshot(task_id)
    assert current["status"] == "pending"
    assert current["result"]["result_id"] == expected["result_id"]
    assert current["result"]["accepted"] is False
    result = dict(conn.execute("SELECT * FROM worker_task_results WHERE id=?",
                               (expected["result_id"],)).fetchone())
    assert result == old
    history = read_result_history(conn, task_id, limit=20)
    assert any(item["type"] == "correction_requested"
               and item["correction"]["correction_id"] == ack["correction_id"]
               for item in history["events"])
    assert any(item["type"] == "result_accepted" for item in history["events"])
    assert _repair(world, expected, ack["request_id"]) == {**ack, "replayed": True}
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1


def test_request_id_reuse_with_different_expectation_conflicts(
    completion_world, monkeypatch,
):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    ack = _repair(world, expected)
    with pytest.raises(ResultConflict):
        _repair(world, {**expected, "review_event_id": expected["review_event_id"] + 1},
                ack["request_id"])


def test_invalid_review_receipt_fails_closed(completion_world, monkeypatch):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    conn, task_id = world["conn"], world["task_id"]
    conn.execute("UPDATE worker_result_model_reviews SET receipt_sha256=? "
                 "WHERE target_result_id=?", ("0" * 64, expected["result_id"]))
    conn.commit()
    with pytest.raises(ResultConflict):
        _repair(world, expected)
    assert read_result(conn, task_id)["status"] == "done"


def test_revoked_reviewer_identity_fails_closed(completion_world, monkeypatch):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    conn, task_id = world["conn"], world["task_id"]
    settings._persist(conn, IDENTITY_KEY, [
        _identity(AUTHOR, AUTHOR_ROUTE, AUTHOR_MODEL, AUTHOR_OBSERVED),
        _identity(STANDARD_REVIEWER, STANDARD_ROUTE, STANDARD_MODEL, STANDARD_OBSERVED),
    ], actor="completion-fixture-revocation")
    conn.commit()
    with pytest.raises(ResultConflict):
        _repair(world, expected)
    assert read_result(conn, task_id)["status"] == "done"


@pytest.mark.parametrize("race", ["result", "review", "policy"])
def test_external_sqlite_change_after_last_evaluation_rolls_back(
    completion_world, monkeypatch, tmp_path, race,
):
    from hub._services import machine_false_acceptance_recovery as repair

    world, expected = _false_acceptance(completion_world, monkeypatch)
    db_path = tmp_path / "concurrent-correction.sqlite"
    with sqlite3.connect(db_path) as seed:
        world["conn"].backup(seed)
    reader = sqlite3.connect(db_path)
    writer = sqlite3.connect(db_path)
    reader.row_factory = writer.row_factory = sqlite3.Row
    world["conn"] = reader
    world["client"] = TaskLeaseClient(conn=reader)
    original = repair.evaluate_current_result
    calls = 0

    def evaluate_then_compete(connection, task_id, **paths):
        nonlocal calls
        value = original(connection, task_id, **paths)
        calls += 1
        if calls == 2:
            assert not connection.in_transaction
            if race == "result":
                writer.execute("UPDATE worker_task_results SET result=result||' [race]' "
                               "WHERE id=?", (expected["result_id"],))
            elif race == "review":
                writer.execute("UPDATE worker_result_model_reviews SET receipt_sha256=? "
                               "WHERE target_result_id=?", ("0" * 64, expected["result_id"]))
            else:
                global_policy = settings._global(writer)
                settings._persist(writer, settings.GLOBAL_KEY,
                    {"policy": global_policy["policy"],
                     "selection": global_policy["selection"]}, actor="completion-fixture-race")
            writer.commit()
        return value

    monkeypatch.setattr(repair, "evaluate_current_result", evaluate_then_compete)
    try:
        with pytest.raises(ResultConflict):
            _repair(world, expected)
        assert calls == 2
        assert read_result(reader, world["task_id"])["status"] == "done"
        assert reader.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                              (world["task_id"],)).fetchone()[0] == 0
    finally:
        reader.close()
        writer.close()


@pytest.mark.parametrize("race", ["revision", "lease"])
def test_stale_cas_or_claim_residue_fails_closed(completion_world, monkeypatch, race):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    conn, task_id = world["conn"], world["task_id"]
    if race == "revision":
        expected = {**expected, "status_revision": expected["status_revision"] + 1}
    else:
        conn.execute("UPDATE tasks SET claim_id=? WHERE id=?", ("foreign-claim", task_id))
        conn.commit()
    with pytest.raises(ResultConflict):
        _repair(world, expected)
    assert read_result(conn, task_id)["status"] == "done"


def test_personal_user_approval_cannot_be_repaired_by_controller(
    completion_world, monkeypatch,
):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    conn, task_id = world["conn"], world["task_id"]
    conn.execute("UPDATE worker_task_results SET user_review_revision=?, "
                 "user_review_event_id=? WHERE id=?",
                 (expected["result_revision"], expected["review_event_id"],
                  expected["result_id"]))
    conn.commit()
    with pytest.raises(ResultConflict):
        _repair(world, expected)
    assert read_result(conn, task_id)["status"] == "done"


def test_tampered_repair_audit_is_not_reported_as_valid_history(
    completion_world, monkeypatch,
):
    world, expected = _false_acceptance(completion_world, monkeypatch)
    conn, task_id = world["conn"], world["task_id"]
    ack = _repair(world, expected)
    event = conn.execute("SELECT event_id FROM task_result_corrections WHERE id=?",
                         (ack["correction_id"],)).fetchone()[0]
    value = json.loads(conn.execute("SELECT new_value FROM task_history WHERE id=?",
                                    (event,)).fetchone()[0])
    value["repair_event_id"] += 1
    conn.execute("UPDATE task_history SET new_value=? WHERE id=?", (json.dumps(value), event))
    conn.commit()
    from hub._services.task_result_service import ResultHistoryUnavailable
    with pytest.raises(ResultHistoryUnavailable):
        read_result_history(conn, task_id, limit=20)
