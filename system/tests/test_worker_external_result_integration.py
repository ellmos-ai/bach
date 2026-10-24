# SPDX-License-Identifier: MIT
"""External authors through the real lease, review and completion adapters.

Only temporary fixture databases are written. Deterministic Git snapshots
exercise binding/CAS; they are not evidence of a deployed real-Git workflow.
The native reviewer uses actual execution handles with fixture responses.
"""
import copy
import json
import os

import pytest
from gui.device_auth import revoke_device
from hub._services import worker_completion_policy as completion
from hub._services import worker_external_attestation as attestation
from hub._services import worker_policy_settings as settings
from hub._services import worker_result_review as review
from hub._services import worker_scope_evidence
from hub._services.chat import worker_write_guard
from hub._services.task_lease_client import TaskLeaseClient
from hub._services.task_result_service import ResultConflict, read_result
from hub._services.worker_result_provenance import (
    EXTERNAL_SCOPE_SCHEMA,
    author_principal,
    current_result_revision,
    source_pin,
)
from hub._services.worker_review_identity import (
    IdentityPermissionDenied,
    identity_snapshot,
)

from system.tests.test_task_lease_client import (
    mem_db as mem_db,  # noqa: PLC0414 -- pytest fixture registration
)
from system.tests.test_worker_execution_evidence import (
    worker_context as worker_context,  # noqa: PLC0414
)
from system.tests.test_worker_external_attestation import (
    capture,
    history_count,
)
from system.tests.test_worker_external_attestation import (
    external_world as external_world,  # noqa: PLC0414 -- pytest fixture registration
)
from system.tests.test_worker_external_evidence import register_sources, source
from system.tests.test_worker_result_review import (
    REVIEW_MODEL,
    REVIEW_OBSERVED,
    REVIEW_ROUTE,
    REVIEW_SLOT,
    _acquire_review,
    _grant,
    _paths,
    _request_hash,
    _response,
)
from system.tests.test_worker_scope_evidence import _review_submission, _scope_snapshot
from system.tests.test_worker_scope_snapshot import (
    _install_lock_scanner,
    _new_scope_repo,
)


@pytest.fixture
def integrated(external_world, tmp_path, monkeypatch):
    world = external_world
    world["client"] = TaskLeaseClient(conn=world["conn"])
    world["tree"] = {"repo": tmp_path / "repo", "worktrees": tmp_path / "trees"}
    for path in world["tree"].values():
        path.mkdir()

    def snapshot(task_id, **kwargs):
        assert not world["conn"].in_transaction, "Git observation under a SQLite writer"
        return copy.deepcopy(_scope_snapshot(task_id))

    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", snapshot)
    # The pre-existing completion adapter performs one bounded final Git check
    # under its writer. Keep that gate intact; no external attestation reader
    # or capture path may introduce additional Git work there.
    monkeypatch.setattr(worker_write_guard, "snapshot_task_scope",
                        lambda task_id, **kwargs: copy.deepcopy(_scope_snapshot(task_id)))
    return world


def target(world):
    return worker_scope_evidence.project_scope_evidence(
        read_result(world["conn"], world["task_id"]), **_paths(world))["result"]


def prepare(world):
    return review.prepare_external_review_task(world["conn"], world["task_id"],
        operator_token=world["operator"], **_paths(world))


def finish_review(world, prepared):
    conn = world["conn"]
    grant, stop, current = _grant(world, prepared["review_task_id"])
    assert grant is not None
    child = _acquire_review(world, prepared["review_task_id"], grant, stop, current)
    assert review.guard_review_dispatch(conn, child,
        route={"backend_id": "ollama", "route_sha256": REVIEW_ROUTE},
        requested_model=REVIEW_MODEL, **_paths(world))
    verdict = json.dumps({"status": "approved", "summary": "Checked the external work and its bound evidence.",
                          "task_contract_met": True})
    handle = child.begin_model_execution(backend_id="ollama", requested_model=REVIEW_MODEL,
        slot_id=REVIEW_SLOT, request_sha256=_request_hash("external-result-review-fixture"),
        route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(handle,
        result=_response(REVIEW_OBSERVED, verdict=(child.task_id, verdict)),
        route_sha256=REVIEW_ROUTE)
    submitted = child.execute_task_manage({"action": "submit_result", "task_id": child.task_id,
                                         "result": verdict})
    evidence = review.read_review_evidence(conn, read_result(conn, world["task_id"])["result"])
    if evidence.get("availability") != "recorded":
        evidence = review.record_review(conn, child, **_paths(world))
    assert evidence is not None, submitted
    return child, evidence


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_external_author_gets_separate_trusted_source_and_revision(integrated):
    world = integrated
    capture(world)
    record = target(world)
    assert record["source_kind"] == "external_attested"
    assert record["execution"]["availability"] == "unavailable"
    assert record["scope"]["schema"] == EXTERNAL_SCOPE_SCHEMA
    assert record["result_revision"] == current_result_revision(record)
    assert source_pin(record)["model_principal_id"] == "model:shared"
    assert author_principal(identity_snapshot(world["conn"]), record) == "model:shared"


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_external_review_intent_is_operator_bound_idempotent_and_slot_free(integrated):
    world = integrated
    capture(world)
    prepared = prepare(world)
    assert prepared is not None
    before = history_count(world["conn"])
    assert prepare(world) == prepared
    assert history_count(world["conn"]) == before
    found = review._intent(world["conn"], prepared["review_task_id"])
    receipt = found["receipt"]
    assert receipt["schema"] == review._EXTERNAL_INTENT_SCHEMA
    assert receipt["author_source"] == source_pin(target(world))
    for key in ["author_execution_id", "author_slot_id", "execution_revision"]:
        assert key not in receipt


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_external_result_native_independent_review_and_completion(integrated):
    world = integrated
    capture(world)
    original = target(world)
    prepared = prepare(world)
    assert prepared is not None
    child, evidence = finish_review(world, prepared)
    assert child.closed
    assert evidence["reviewer_id"] == "model:reviewer"
    assert evidence["independent"] is True
    assert evidence["result_revision"] == original["result_revision"]
    evaluated = completion.evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert evaluated["availability"] == "available", evaluated
    assert evaluated["decision"]["completion_allowed"] is True
    completion.reconcile_current_result(world["conn"], world["task_id"], **_paths(world))
    final = read_result(world["conn"], world["task_id"])
    assert final["status"] == "done", final
    assert final["result"]["accepted"] is True
    assert final["result"]["execution"]["availability"] == "unavailable"
    assert final["result"]["completion_decision"]["availability"] == "available"


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_external_review_creation_rejects_an_ordinary_device_before_git(integrated):
    world = integrated
    capture(world)
    calls = len(world["scope_calls"])
    with pytest.raises(IdentityPermissionDenied):
        review.prepare_external_review_task(world["conn"], world["task_id"],
            operator_token=world["ordinary"], **_paths(world))
    assert len(world["scope_calls"]) == calls


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_revoked_external_author_provenance_cannot_fall_back_to_native(integrated):
    world = integrated
    capture(world)
    revoke_device("external-operator-fixture", connection=world["conn"])
    record = read_result(world["conn"], world["task_id"])["result"]
    assert record["source_kind"] == "external_attested"
    assert record["external_provenance"]["availability"] == "unavailable"
    assert source_pin(record) is None
    evaluated = completion.evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert evaluated["availability"] == "unavailable"


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_unattested_result_cannot_create_review_or_satisfy_completion(integrated):
    world = integrated
    record = read_result(world["conn"], world["task_id"])["result"]
    assert record["source_kind"] == "unattested"
    assert prepare(world) is None
    assert completion.evaluate_current_result(world["conn"], world["task_id"], **_paths(world))["availability"] == "unavailable"


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
@pytest.mark.parametrize("change", ["operator", "mapping", "artifact", "policy", "task", "lease", "git"])
def test_changed_external_authority_cannot_complete_a_previously_reviewed_result(
        integrated, monkeypatch, change):
    world = integrated
    conn = world["conn"]
    # Delay only the optional SDK reconcile hook so this test can mutate the
    # authority before the explicit, otherwise unmodified completion writer.
    monkeypatch.setattr(world["client"], "_reconcile_task_completion", lambda task_id: None)
    capture(world)
    prepared = prepare(world)
    assert prepared is not None
    finish_review(world, prepared)
    assert completion.evaluate_current_result(conn, world["task_id"], **_paths(world))["decision"]["completion_allowed"] is True
    if change == "operator":
        revoke_device("external-operator-fixture", connection=conn)
    elif change == "mapping":
        register_sources(world["authority"], [source(model_labels=["different-model"])])
    elif change == "artifact":
        conn.execute("UPDATE worker_external_artifacts SET content=? WHERE artifact_id=?",
            (b"tampered fixture", world["request"]["source_artifact_ids"][0]))
    elif change == "policy":
        values = settings._defaults()
        values["policy"]["default_mode"] = "simple_task"
        settings._persist(conn, settings.GLOBAL_KEY, values, actor="changed-fixture-policy")
    elif change == "task":
        conn.execute("UPDATE tasks SET title='Changed after review' WHERE id=?", (world["task_id"],))
    elif change == "lease":
        conn.execute("UPDATE tasks SET claim_id='new-owner-fixture' WHERE id=?", (world["task_id"],))
    else:
        monkeypatch.setattr(attestation, "snapshot_task_scope",
                            lambda task_id, **kwargs: _scope_snapshot(task_id, head_oid="e" * 40))
    conn.commit()
    before = history_count(conn)
    outcome = completion.reconcile_current_result(conn, world["task_id"], **_paths(world))
    assert outcome["availability"] == "unavailable", outcome
    assert history_count(conn) == before
    final = read_result(conn, world["task_id"])
    assert final["status"] == "review" and final["result"]["accepted"] is False


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
@pytest.mark.parametrize("change", ["operator", "task", "status", "lease"])
def test_external_review_prepare_writer_rechecks_after_observation(integrated, monkeypatch, change):
    world = integrated
    conn = world["conn"]
    capture(world)
    native_authority = review._target_authority
    changed = False

    def racing_authority(connection, record):
        nonlocal changed
        authority = native_authority(connection, record)
        if not connection.in_transaction and not changed:
            changed = True
            if change == "operator":
                revoke_device("external-operator-fixture", connection=connection)
            else:
                field, value = {"task": ("title", "Changed before writer"),
                                "status": ("status", "pending"),
                                "lease": ("claim_id", "foreign-fixture-claim")}[change]
                connection.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, world["task_id"]))
                connection.commit()
        return authority

    monkeypatch.setattr(review, "_target_authority", racing_authority)
    if change == "operator":
        with pytest.raises(IdentityPermissionDenied):
            prepare(world)
    else:
        assert prepare(world) is None
    assert changed and not conn.in_transaction
    assert conn.execute("SELECT count(*) FROM tasks WHERE category='worker-review'").fetchone()[0] == 0


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_completion_writer_rechecks_external_provenance_after_both_observations(integrated, monkeypatch):
    world = integrated
    conn = world["conn"]
    monkeypatch.setattr(world["client"], "_reconcile_task_completion", lambda task_id: None)
    capture(world)
    finish_review(world, prepare(world))
    native_evaluate = completion.evaluate_current_result
    evaluations = 0

    def racing_evaluate(*args, **kwargs):
        nonlocal evaluations
        observed = native_evaluate(*args, **kwargs)
        evaluations += 1
        if evaluations == 2:
            revoke_device("external-operator-fixture", connection=conn)
        return observed

    monkeypatch.setattr(completion, "evaluate_current_result", racing_evaluate)
    before = history_count(conn)
    with pytest.raises(ResultConflict):
        completion.reconcile_current_result(conn, world["task_id"], **_paths(world))
    assert evaluations == 2 and not conn.in_transaction
    assert history_count(conn) == before
    final = read_result(conn, world["task_id"])
    assert final["status"] == "review" and final["result"]["accepted"] is False


@pytest.mark.parametrize("external_world", [{"review_models": True, "same_model_reviewer": True}], indirect=True)
def test_native_alias_of_external_author_is_not_an_independent_model(integrated):
    world = integrated
    capture(world)
    prepared = prepare(world)
    assert prepared is not None
    conn = world["conn"]
    assert author_principal(identity_snapshot(conn), target(world)) == "model:shared"
    before = history_count(conn)
    grant, _, _ = _grant(world, prepared["review_task_id"])
    assert grant is None
    assert history_count(conn) == before
    evidence = review.read_review_evidence(conn, read_result(conn, world["task_id"])["result"])
    assert evidence["availability"] == "unavailable"
    assert conn.execute(
        "SELECT count(*) FROM worker_result_model_reviews WHERE target_task_id=?",
        (world["task_id"],),
    ).fetchone()[0] == 0
    evaluated = completion.evaluate_current_result(conn, world["task_id"], **_paths(world))
    assert evaluated["availability"] == "available", evaluated
    assert evaluated["decision"]["completion_allowed"] is False
    assert evaluated["decision"]["worker_may_claim_next"] is True
    final = read_result(world["conn"], world["task_id"])
    assert final["status"] == "review" and final["result"]["accepted"] is False


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_external_result_with_real_registered_git_scope(external_world, tmp_path, monkeypatch):
    """Actual temporary Git/worktree reads, fixture locks and model response."""
    from hub import worker_git

    world = external_world
    world["client"] = TaskLeaseClient(conn=world["conn"])
    native_environment = worker_write_guard._scope_git_env

    def isolated_git_environment():
        environment = native_environment()
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        return environment

    monkeypatch.setattr(worker_write_guard, "_scope_git_env", isolated_git_environment)
    world["tree"] = _new_scope_repo(tmp_path, task_id=world["task_id"], pinned=True)
    _install_lock_scanner(tmp_path, monkeypatch)
    native_snapshot = worker_write_guard.snapshot_task_scope

    def actual_snapshot(task_id, *, repo_root=None, worktrees_dir=None):
        assert not world["conn"].in_transaction
        return native_snapshot(task_id, repo_root=repo_root or world["tree"]["repo"],
                               worktrees_dir=worktrees_dir or world["tree"]["worktrees"])

    monkeypatch.setattr(attestation, "snapshot_task_scope", actual_snapshot)
    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", actual_snapshot)
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: world["tree"]["worktrees"])
    capture(world, **_paths(world))
    prepared = prepare(world)
    assert prepared is not None
    child, evidence = finish_review(world, prepared)
    assert child.closed and evidence["independent"] is True
    final = read_result(world["conn"], world["task_id"])
    assert final["status"] == "done" and final["result"]["accepted"] is True
    assert final["result"]["execution"]["availability"] == "unavailable"


@pytest.mark.parametrize("change", ["scope_only", "execution_id", "execution_revision", "slot_id"])
def test_native_scope_obsolescence_never_relaxes_normal_intent_matching(worker_context, monkeypatch, change):
    """Internal helper contract; the native Git suite checks actual receipts."""
    world = worker_context
    _review_submission(world)
    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", _scope_snapshot)
    assert worker_scope_evidence.capture_scope_evidence(world["conn"], world["binding"])
    original = read_result(world["conn"], world["task_id"])["result"]
    intent = {"schema": review._INTENT_SCHEMA, **review._intent_author_fields(original)}
    assert review._intent_source_matches(intent, original)
    changed = copy.deepcopy(original)
    changed["scope"]["scope_receipt_sha256"] = "f" * 64
    if change != "scope_only":
        changed["execution"][change] = "e" * 64 if change == "execution_revision" else "changed-fixture"
    assert review._intent_same_author(intent, changed) is (change == "scope_only")
    assert review._intent_source_matches(intent, changed) is False
