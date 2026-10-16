# SPDX-License-Identifier: MIT
"""Real TaskDB/lease and Git-scope behavior for controller-bound model review."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading

import pytest

from hub._services import worker_policy_settings as settings
from hub._services import worker_result_review as review
from hub._services import worker_scope_evidence
from hub._services.chat import worker_write_guard
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import LeaseDeniedError
from hub._services.task_result_service import read_result
from hub._services.worker_review_identity import KEY as IDENTITY_KEY
from system.tests.test_task_lease_client import mem_db
from system.tests.test_task_lease_client_review import T0
from system.tests.test_worker_execution_evidence import worker_context
from system.tests.test_worker_scope_snapshot import _install_lock_scanner, _new_scope_repo


AUTHOR = "principal:author"
REVIEWER = "principal:reviewer"
AUTHOR_ROUTE = hashlib.sha256(b"controller-author-route").hexdigest()
AUTHOR_ALIAS_ROUTE = hashlib.sha256(b"controller-author-alias-route").hexdigest()
REVIEW_ROUTE = hashlib.sha256(b"controller-review-route").hexdigest()
AUTHOR_MODEL = "author-requested"
AUTHOR_ALIAS_MODEL = "author-alias-requested"
REVIEW_MODEL = "review-requested"
AUTHOR_OBSERVED = "author-returned"
REVIEW_OBSERVED = "review-returned"
AUTHOR_SLOT = "physical-author-slot"
REVIEW_SLOT = "physical-review-slot"
REVIEW_GENERATION = "review-generation-2"


def _binding(principal, route, requested, observed):
    return {"principal_id": principal, "backend_id": "ollama",
            "route_sha256": route, "requested_models": [requested],
            "reported_models": [observed]}


def _response(model, *, verdict=None):
    calls = None
    if verdict is not None:
        task_id, result = verdict
        calls = [{"id": "review-submit", "type": "function", "function": {
            "name": "task_manage", "arguments": json.dumps({
                "action": "submit_result", "task_id": task_id, "result": result})}}]
    return {"model": model, "provider_reported_model": model,
            "content": None if calls else "Belegter Modellaufruf", "tool_calls": calls}


def _request_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def review_world(worker_context, tmp_path, monkeypatch):
    """Real SQLite submissions and registered clean Git worktree; no model calls."""
    context = worker_context
    conn, author = context["conn"], context["binding"]
    conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    values = settings._defaults()
    values["policy"]["reviewers"] = [
        {"reviewer_id": AUTHOR, "tier": "standard"},
        {"reviewer_id": REVIEWER, "tier": "top"},
    ]
    values["policy"]["allow_review_task_pickup"] = True
    settings._persist(conn, settings.GLOBAL_KEY, values, actor="test-operator")
    settings._persist(conn, IDENTITY_KEY, [
        _binding(AUTHOR, AUTHOR_ROUTE, AUTHOR_MODEL, AUTHOR_OBSERVED),
        _binding(AUTHOR, AUTHOR_ALIAS_ROUTE, AUTHOR_ALIAS_MODEL, AUTHOR_OBSERVED),
        _binding(REVIEWER, REVIEW_ROUTE, REVIEW_MODEL, REVIEW_OBSERVED),
    ], actor="test-operator")
    conn.commit()

    native_git_environment = worker_write_guard._scope_git_env

    def isolated_test_git_environment():
        environment = native_git_environment()
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        return environment

    # Exercise the real Git adapter against only this test repository. CI
    # machines may have unrelated global/system Git clean filters installed.
    monkeypatch.setattr(worker_write_guard, "_scope_git_env", isolated_test_git_environment)
    tree = _new_scope_repo(tmp_path, task_id=context["task_id"])
    _install_lock_scanner(tmp_path, monkeypatch)
    native_snapshot = worker_scope_evidence.snapshot_task_scope

    def local_git_snapshot(task_id, *, repo_root=None, worktrees_dir=None):
        return native_snapshot(task_id, repo_root=repo_root or tree["repo"],
                               worktrees_dir=worktrees_dir or tree["worktrees"])

    monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", local_git_snapshot)
    handle = author.begin_model_execution(
        backend_id="ollama", requested_model=AUTHOR_MODEL, slot_id=AUTHOR_SLOT,
        request_sha256=_request_hash("author prompt"), route_sha256=AUTHOR_ROUTE)
    assert handle is not None
    assert author.finish_model_execution(
        handle, result=_response(AUTHOR_OBSERVED), route_sha256=AUTHOR_ROUTE) is True
    assert "wartet in Review" in author.execute_task_manage({
        "action": "submit_result", "task_id": context["task_id"],
        "result": "Konkrete erledigte Arbeit am Zieltask."})
    assert worker_scope_evidence.capture_scope_evidence(conn, author) is True
    target = worker_scope_evidence.project_scope_evidence(
        read_result(conn, context["task_id"]),
        repo_root=tree["repo"], worktrees_dir=tree["worktrees"])["result"]
    assert target["result_revision"] and target["execution"]["model_principal_id"] == AUTHOR
    return {**context, "tree": tree, "target": target}


def _paths(world):
    return {"repo_root": world["tree"]["repo"],
            "worktrees_dir": world["tree"]["worktrees"]}


def _prepare(world):
    prepared = review.prepare_review_task(world["conn"], world["binding"], **_paths(world))
    assert prepared is not None
    assert prepared["target_result_id"] == world["target"]["result_id"]
    assert prepared["target_revision"] == world["target"]["result_revision"]
    return prepared


def _grant(world, task_id, *, slot=REVIEW_SLOT, generation=REVIEW_GENERATION,
           route=REVIEW_ROUTE, requested=REVIEW_MODEL, stop=None, current=None):
    stop = stop or threading.Event()
    current = current or {"value": True}
    grant = review.issue_review_grant(
        world["conn"], task_id, worker_id="review-worker@HOST", host="HOST",
        generation=generation, slot_id=slot,
        route={"backend_id": "ollama", "route_sha256": route},
        requested_model=requested, is_current=lambda: current["value"],
        stop_event=stop, clock=lambda: T0, **_paths(world))
    return grant, stop, current


def _acquire_review(world, task_id, grant, stop, current):
    return WorkerLeaseBinding.acquire(
        world["client"], task_id, worker_id="review-worker@HOST", host="HOST",
        generation=REVIEW_GENERATION, is_current=lambda: current["value"],
        stop_event=stop, clock=lambda: T0,
        slot={"id": REVIEW_SLOT, "model": REVIEW_MODEL, "backend": "ollama"},
        automatic=True, _review_grant=grant)


def test_real_git_author_submission_second_model_review_and_child_completion(review_world):
    world = review_world
    prepared = _prepare(world)
    grant, stop, current = _grant(world, prepared["review_task_id"])
    assert grant is not None
    child = _acquire_review(world, prepared["review_task_id"], grant, stop, current)
    route = {"backend_id": "ollama", "route_sha256": REVIEW_ROUTE}
    assert review.guard_review_dispatch(
        world["conn"], child, route=route, requested_model=REVIEW_MODEL,
        **_paths(world)) is True

    verdict = json.dumps({"status": "approved", "summary": "Prüfung der Zielarbeit bestanden.",
                          "task_contract_met": True}, ensure_ascii=False)
    answer = _response(REVIEW_OBSERVED, verdict=(child.task_id, verdict))
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("independent review prompt"),
        route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(
        handle, result=answer, route_sha256=REVIEW_ROUTE) is True
    assert "wartet in Review" in child.execute_task_manage({
        "action": "submit_result", "task_id": child.task_id, "result": verdict})
    evidence = review.record_review(world["conn"], child, **_paths(world))
    assert evidence["availability"] == "recorded"
    assert evidence["reviewer_id"] == REVIEWER
    assert evidence["independent"] is True
    assert evidence["result_revision"] == world["target"]["result_revision"]
    assert review.read_review_evidence(world["conn"],
        read_result(world["conn"], child.task_id)["result"])["availability"] == "unavailable"
    parent = read_result(world["conn"], world["task_id"])
    assert parent["status"] == "review"
    assert parent["result"]["accepted"] is False
    assert read_result(world["conn"], child.task_id)["status"] == "done"
    assert read_result(world["conn"], child.task_id)["result"]["accepted"] is True
    projected = worker_scope_evidence.project_scope_evidence(parent, **_paths(world))
    assert projected["result"]["model_review"]["availability"] == "available"
    before = world["conn"].total_changes
    assert review.record_review(world["conn"], child, **_paths(world)) == evidence
    assert world["conn"].total_changes == before
    (world["tree"]["target"] / "after-review.txt").write_text("changed\n", encoding="utf-8")
    stale = worker_scope_evidence.project_scope_evidence(
        read_result(world["conn"], world["task_id"]), **_paths(world))
    assert stale["result"]["model_review"]["availability"] == "unavailable"
    assert review.record_review(world["conn"], child, **_paths(world)) is None


def test_review_task_creation_is_idempotent_and_stays_in_normal_task_table(review_world):
    world = review_world
    first = _prepare(world)
    second = review.prepare_review_task(world["conn"], world["binding"], **_paths(world))
    assert second == first
    assert world["conn"].execute("SELECT COUNT(*) FROM tasks WHERE category='worker-review'").fetchone()[0] == 1
    assert world["conn"].execute("SELECT COUNT(*) FROM task_history WHERE action='worker_result_review_task'").fetchone()[0] == 1
    tasks = review.list_review_candidates(world["conn"])
    assert [task["id"] for task in tasks] == [first["review_task_id"]]
    assert read_result(world["conn"], world["task_id"])["status"] == "review"


def test_review_task_requires_private_fresh_grant_and_separate_principal(review_world):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    snapshot = world["client"].task_snapshot(task_id)
    with pytest.raises(LeaseDeniedError):
        world["client"].acquire(task_id, worker_id="review-worker@HOST", host="HOST",
            task_version=snapshot["task_version"], result_generation=REVIEW_GENERATION,
            now=T0)
    assert _grant(world, task_id, slot=AUTHOR_SLOT)[0] is None
    assert _grant(world, task_id, generation=world["binding"].generation)[0] is None
    assert _grant(world, task_id, route=AUTHOR_ALIAS_ROUTE,
                  requested=AUTHOR_ALIAS_MODEL)[0] is None
    assert _grant(world, task_id)[0] is not None


def test_git_scope_change_after_grant_blocks_dispatch(review_world):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    assert grant is not None
    child = _acquire_review(world, task_id, grant, stop, current)
    (world["tree"]["target"] / "uncommitted-change.txt").write_text(
        "new unreviewed work\n", encoding="utf-8")
    assert review.guard_review_dispatch(
        world["conn"], child,
        route={"backend_id": "ollama", "route_sha256": REVIEW_ROUTE},
        requested_model=REVIEW_MODEL, **_paths(world)) is False


@pytest.mark.parametrize("mutation", ["stop", "current", "task_content", "policy", "identity"])
def test_grant_fails_closed_after_context_or_version_change(review_world, mutation):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    assert grant is not None
    row = dict(world["conn"].execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    world["conn"].execute("BEGIN IMMEDIATE")
    try:
        assert review.validate_review_acquire(world["conn"], row,
            worker_id="review-worker@HOST", host="HOST", grant=grant, now=T0) is True
    finally:
        world["conn"].rollback()
    if mutation == "stop":
        stop.set()
    elif mutation == "current":
        current["value"] = False
    elif mutation == "task_content":
        world["conn"].execute("UPDATE tasks SET title='Verändertes Reviewziel' WHERE id=?", (task_id,))
        world["conn"].commit()
    elif mutation == "policy":
        policy = settings._global(world["conn"])
        values = {"policy": copy.deepcopy(policy["policy"]),
                  "selection": copy.deepcopy(policy["selection"])}
        values["policy"]["review_expiry_seconds"] = 600
        settings._persist(world["conn"], settings.GLOBAL_KEY, values, actor="test-operator")
        world["conn"].commit()
    else:
        from hub._services.worker_review_identity import identity_snapshot
        bindings = identity_snapshot(world["conn"])["bindings"]
        settings._persist(world["conn"], IDENTITY_KEY, bindings[:1], actor="test-operator")
        world["conn"].commit()
    row = dict(world["conn"].execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    world["conn"].execute("BEGIN IMMEDIATE")
    try:
        assert review.validate_review_acquire(world["conn"], row,
            worker_id="review-worker@HOST", host="HOST", grant=grant, now=T0) is False
    finally:
        world["conn"].rollback()


def test_corrupt_intent_cannot_be_picked_up_as_ordinary_task(review_world):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    world["conn"].execute("UPDATE worker_result_review_intents SET intent='{}' WHERE review_task_id=?",
                          (task_id,))
    world["conn"].commit()
    assert review.review_task_marker(world["conn"], task_id) is True
    assert review.review_task_metadata(world["conn"], task_id) is None
    assert review.list_review_candidates(world["conn"]) == []
    assert _grant(world, task_id)[0] is None
    snapshot = world["client"].task_snapshot(task_id)
    with pytest.raises(LeaseDeniedError):
        world["client"].acquire(task_id, worker_id="review-worker@HOST", host="HOST",
            task_version=snapshot["task_version"], result_generation=REVIEW_GENERATION,
            now=T0)
