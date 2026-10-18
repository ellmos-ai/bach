"""Behavioral integration tests for policy-driven worker result completion.

All task, lease, result, review, and Git state in this module is local fixture
data. No real model, native task database, or GitHub service is contacted.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading

import pytest

from hub._services import worker_policy_settings as settings
from hub._services import worker_result_review as review
from hub._services import worker_scope_evidence
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_result_service import (
    ResultConflict,
    ResultPermissionDenied,
    accept_result,
    read_correction_context,
    read_result,
    read_result_history,
)
from hub._services.task_lease_client import TaskLeaseClient
from hub._services.task_schema import ensure_task_result_contract_columns
from hub._services.worker_completion_policy import (
    evaluate_current_result,
    reconcile_current_result,
)
from hub._services.worker_review_identity import KEY as IDENTITY_KEY
from hub._services.chat import worker_write_guard
from system.tests.test_task_lease_client import _init_db, _insert_task, mem_db
from system.tests.test_task_lease_client_review import T0
from system.tests.test_worker_execution_evidence import worker_context
from system.tests.test_worker_scope_snapshot import _install_lock_scanner, _new_scope_repo


def _legacy_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    return conn


def _schema_objects(conn):
    return tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    )


AUTHOR = "principal:completion-author"
STANDARD_REVIEWER = "principal:completion-standard"
TOP_REVIEWER = "principal:completion-top"
AUTHOR_ROUTE = hashlib.sha256(b"completion-author-route").hexdigest()
STANDARD_ROUTE = hashlib.sha256(b"completion-standard-route").hexdigest()
TOP_ROUTE = hashlib.sha256(b"completion-top-route").hexdigest()
AUTHOR_MODEL = "completion-author-model"
STANDARD_MODEL = "completion-standard-model"
TOP_MODEL = "completion-top-model"
AUTHOR_OBSERVED = "completion-author-observed"
STANDARD_OBSERVED = "completion-standard-observed"
TOP_OBSERVED = "completion-top-observed"
AUTHOR_SLOT = "completion-author-slot"
STANDARD_SLOT = "completion-standard-slot"
TOP_SLOT = "completion-top-slot"
GENERATION = "completion-generation-1"
TOP_GENERATION = "completion-generation-review-2"
RESULT_TEXT = "Concrete result with evidence and a clear outcome."


def _identity(principal, route, requested, reported):
    return {"principal_id": principal, "backend_id": "ollama",
            "route_sha256": route, "requested_models": [requested],
            "reported_models": [reported]}


def _model_response(model, *, content="Verified local model response", tool_calls=None):
    return {"model": model, "provider_reported_model": model,
            "content": content, "tool_calls": tool_calls}


def _contract(min_chars=12, *, include_readme_blob=False):
    criteria = [{"kind": "result_min_chars", "min_chars": min_chars}]
    if include_readme_blob:
        criteria.append({"kind": "git_blob_sha256", "path": "README.md",
                         "sha256": hashlib.sha256(b"public base\n").hexdigest()})
    return json.dumps({"schema": "bach.worker-task-contract.v1",
        "criteria": criteria},
        sort_keys=True, separators=(",", ":"))


@pytest.fixture
def completion_world(worker_context, tmp_path, monkeypatch):
    """Build a real local submission, execution receipt, and clean registered Git tree."""
    def build(*, mode="simple_task", contract_min_chars=12, contract_git_blob=False,
              contract_json_override=None,
              user_review=False, github_required=False, github_external_review=True,
              review_expiry_seconds=None, missing_scope=False):
        context = worker_context
        conn, client, task_id = context["conn"], context["client"], context["task_id"]
        old_binding = context["binding"]
        assert old_binding.return_lease() is True
        ensure_task_result_contract_columns(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

        values = settings._defaults()
        values["policy"]["default_mode"] = mode
        values["policy"]["review_expiry_seconds"] = review_expiry_seconds
        values["policy"]["reviewers"] = [
            {"reviewer_id": AUTHOR, "tier": "standard"},
            {"reviewer_id": STANDARD_REVIEWER, "tier": "standard"},
            {"reviewer_id": TOP_REVIEWER, "tier": "top"},
        ]
        values["policy"]["allow_review_task_pickup"] = True
        values["policy"]["github_external_review"] = github_external_review
        settings._persist(conn, settings.GLOBAL_KEY, values, actor="completion-fixture")
        settings._persist(conn, IDENTITY_KEY, [
            _identity(AUTHOR, AUTHOR_ROUTE, AUTHOR_MODEL, AUTHOR_OBSERVED),
            _identity(STANDARD_REVIEWER, STANDARD_ROUTE, STANDARD_MODEL, STANDARD_OBSERVED),
            _identity(TOP_REVIEWER, TOP_ROUTE, TOP_MODEL, TOP_OBSERVED),
        ], actor="completion-fixture")

        github_contract = None
        if github_required:
            github_contract = json.dumps({
                "schema": "bach.worker-github-review-contract.v1",
                "pull_url": "https://github.com/ellmos-ai/bach/pull/17",
                "required_checks": ["unit"], "min_approvals": 1,
                "require_merged": False,
            }, sort_keys=True, separators=(",", ":"))
        completion_contract = (_contract(contract_min_chars, include_readme_blob=contract_git_blob)
            if contract_min_chars is not None else None)
        if contract_json_override is not None:
            completion_contract = contract_json_override
        conn.execute("UPDATE tasks SET completion_contract_json=?, require_user_review=?, "
            "github_pr_review_required=?, github_review_contract_json=? WHERE id=?",
            (completion_contract,
             int(user_review), int(github_required), github_contract, task_id))
        conn.commit()

        native_git_environment = worker_write_guard._scope_git_env

        def isolated_test_git_environment():
            environment = native_git_environment()
            environment["GIT_CONFIG_GLOBAL"] = os.devnull
            environment["GIT_CONFIG_NOSYSTEM"] = "1"
            return environment

        monkeypatch.setattr(worker_write_guard, "_scope_git_env", isolated_test_git_environment)
        tree = _new_scope_repo(tmp_path, task_id=task_id)
        if missing_scope:
            # A real registered tree is removed through Git before submission;
            # its missing receipt is not simulated by deleting evidence rows.
            contract = json.dumps({"schema": "bach.worker-task-contract.v1",
                "criteria": [{"kind": "git_blob_sha256", "path": "README.md",
                    "sha256": hashlib.sha256(b"public base\n").hexdigest()}]},
                sort_keys=True, separators=(",", ":"))
            conn.execute("UPDATE tasks SET completion_contract_json=? WHERE id=?",
                         (contract, task_id))
            conn.commit()
        _install_lock_scanner(tmp_path, monkeypatch)
        native_snapshot = worker_scope_evidence.snapshot_task_scope

        def local_git_snapshot(requested_task_id, *, repo_root=None, worktrees_dir=None):
            return native_snapshot(requested_task_id, repo_root=repo_root or tree["repo"],
                                   worktrees_dir=worktrees_dir or tree["worktrees"])

        monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", local_git_snapshot)
        current, stop = {"value": True}, threading.Event()
        binding = WorkerLeaseBinding.acquire(client, task_id,
            worker_id="completion-author@HOST", host="HOST", generation=GENERATION,
            is_current=lambda: current["value"], stop_event=stop, clock=lambda: T0)
        context.update(binding=binding, current=current, stop=stop)
        handle = binding.begin_model_execution(backend_id="ollama",
            requested_model=AUTHOR_MODEL, slot_id=AUTHOR_SLOT,
            request_sha256=hashlib.sha256(b"completion author prompt").hexdigest(),
            route_sha256=AUTHOR_ROUTE)
        assert handle is not None
        assert binding.finish_model_execution(handle,
            result=_model_response(AUTHOR_OBSERVED), route_sha256=AUTHOR_ROUTE) is True
        if missing_scope:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree["target"])],
                cwd=tree["repo"], env=isolated_test_git_environment(), check=True,
                capture_output=True, timeout=8)
        binding.execute_task_manage({"action": "submit_result", "task_id": task_id,
                                     "result": RESULT_TEXT})
        assert worker_scope_evidence.capture_scope_evidence(conn, binding) is not missing_scope
        target = worker_scope_evidence.project_scope_evidence(read_result(conn, task_id),
            repo_root=tree["repo"], worktrees_dir=tree["worktrees"])["result"]
        assert (target["result_revision"] is None) is missing_scope
        return {**context, "tree": tree, "target": target}
    return build


def _paths(world):
    return {"repo_root": world["tree"]["repo"],
            "worktrees_dir": world["tree"]["worktrees"]}


def _correction_count(conn, task_id):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='task_result_corrections'").fetchone() is None:
        return 0
    return conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0]


def _record_independent_review(world, *, status="approved", task_contract_met=None,
                               read_current_evidence=True):
    conn, client, task_id = world["conn"], world["client"], world["task_id"]
    prepared = review.prepare_review_task(conn, world["binding"], **_paths(world))
    assert prepared is not None
    review_task_id = prepared["review_task_id"]
    grant = review.issue_review_grant(conn, review_task_id,
        worker_id="completion-reviewer@HOST", host="HOST", generation=TOP_GENERATION,
        slot_id=TOP_SLOT,
        route={"backend_id": "ollama", "route_sha256": TOP_ROUTE},
        requested_model=TOP_MODEL, is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0, **_paths(world))
    assert grant is not None
    stop = threading.Event()
    child = WorkerLeaseBinding.acquire(client, review_task_id,
        worker_id="completion-reviewer@HOST", host="HOST", generation=TOP_GENERATION,
        is_current=lambda: True, stop_event=stop, clock=lambda: T0,
        slot={"id": TOP_SLOT, "model": TOP_MODEL, "backend": "ollama"},
        automatic=True, _review_grant=grant)
    assert review.guard_review_dispatch(conn, child,
        route={"backend_id": "ollama", "route_sha256": TOP_ROUTE},
        requested_model=TOP_MODEL, **_paths(world)) is True
    if task_contract_met is None:
        task_contract_met = status == "approved"
    assert type(task_contract_met) is bool
    verdict = json.dumps({"status": status,
        "summary": "Reviewbeleg mit konkreten Beobachtungen.",
        "task_contract_met": task_contract_met}, ensure_ascii=False)
    answer = _model_response(TOP_OBSERVED, content=None, tool_calls=[{
        "id": "completion-review-submit", "type": "function", "function": {
            "name": "task_manage", "arguments": json.dumps({
                "action": "submit_result", "task_id": review_task_id, "result": verdict},
                ensure_ascii=False)}}])
    handle = child.begin_model_execution(backend_id="ollama", requested_model=TOP_MODEL,
        slot_id=TOP_SLOT, request_sha256=hashlib.sha256(b"independent completion review").hexdigest(),
        route_sha256=TOP_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(handle, result=answer, route_sha256=TOP_ROUTE) is True
    child.execute_task_manage({"action": "submit_result", "task_id": review_task_id,
                               "result": verdict})
    if not read_current_evidence:
        # Automatic correction consumes the current target revision. Its
        # caller verifies the historical review and canonical correction.
        return review_task_id
    # The real submit hook may already have recorded the review and completed
    # both tasks. Read its durable receipt before trying an open-target write.
    evidence = review.read_review_evidence(conn, read_result(conn, task_id)["result"])
    if evidence.get("availability") != "recorded":
        evidence = review.record_review(conn, child, **_paths(world))
    assert evidence is not None
    assert evidence["availability"] == "recorded"
    assert evidence["reviewer_id"] == TOP_REVIEWER
    assert evidence["independent"] is True
    assert evidence["result_revision"] == world["target"]["result_revision"]
    return evidence


def test_simple_policy_evaluation_is_read_only_and_completion_is_idempotent(completion_world):
    world = completion_world(mode="simple_task")
    conn, task_id = world["conn"], world["task_id"]
    before_schema = _schema_objects(conn)
    before_changes = conn.total_changes

    observed = evaluate_current_result(conn, task_id, **_paths(world))
    assert observed["availability"] == "available"
    assert observed["decision"]["state"] == "completed"
    assert observed["decision"]["completion_allowed"] is True
    assert observed["contract"]["met"] is True
    assert conn.total_changes == before_changes
    assert _schema_objects(conn) == before_schema
    assert read_result(conn, task_id)["status"] == "review"

    completed = reconcile_current_result(conn, task_id, **_paths(world))
    assert completed["availability"] == "available"
    assert completed["status"] == "done"
    current = read_result(conn, task_id)
    assert current["result"]["accepted"] is True
    assert current["result"]["accepted_by"] == "native-worker-completion-policy"
    assert current["result"]["completion_decision"]["availability"] == "available"
    counts = tuple(conn.execute(
        "SELECT SUM(action='worker_completion_decision'),SUM(action='result_acceptance') "
        "FROM task_history WHERE task_id=?", (task_id,)).fetchone())
    assert counts == (1, 1)

    again = reconcile_current_result(conn, task_id, **_paths(world))
    assert again["availability"] == "available"
    assert again["status"] == "done"
    assert tuple(conn.execute(
        "SELECT SUM(action='worker_completion_decision'),SUM(action='result_acceptance') "
        "FROM task_history WHERE task_id=?", (task_id,)).fetchone()) == counts


@pytest.mark.parametrize(
    ("review_status", "decision_reason"),
    [("approved", "review_approved"), ("findings", "non_blocking_review_findings")],
)
def test_balanced_policy_waits_for_an_independent_current_review(
    completion_world, review_status, decision_reason
):
    world = completion_world(mode="balanced")
    conn, task_id = world["conn"], world["task_id"]
    pending = evaluate_current_result(conn, task_id, **_paths(world))
    assert pending["availability"] == "available"
    assert pending["decision"]["state"] == "awaiting_review"
    assert pending["decision"]["completion_allowed"] is False
    assert pending["decision"]["worker_may_claim_next"] is True
    assert STANDARD_REVIEWER in pending["decision"]["eligible_reviewer_ids"]
    assert AUTHOR not in pending["decision"]["eligible_reviewer_ids"]
    reconcile_current_result(conn, task_id, **_paths(world))
    assert read_result(conn, task_id)["status"] == "review"

    evidence = _record_independent_review(
        world, status=review_status, task_contract_met=True)
    assert evidence["reviewer_id"] != AUTHOR
    ready = evaluate_current_result(conn, task_id, **_paths(world))
    assert ready["decision"]["state"] == "completed"
    assert ready["decision"]["reason"] == decision_reason
    assert reconcile_current_result(conn, task_id, **_paths(world))["status"] == "done"
    assert read_result(conn, task_id)["result"]["accepted"] is True


@pytest.mark.parametrize("hard_gate", ["none", "user", "github"])
def test_balanced_expiry_controller_poll_completes_only_without_hard_review_gates(
    completion_world, monkeypatch, hard_gate
):
    """A real local controller poll may expire review, but cannot bypass hard gates."""
    from hub._services.chat import telegram_chat
    from hub._services import worker_completion_policy
    from hub import worker_git

    world = completion_world(
        mode="balanced",
        review_expiry_seconds=1,
        user_review=hard_gate == "user",
        github_required=hard_gate == "github",
        github_external_review=False,
    )
    conn, binding, task_id = world["conn"], world["binding"], world["task_id"]
    if hard_gate == "github":
        # The controller still uses the real evaluation/reconciliation path;
        # only the external GitHub observation is a deterministic local fixture.
        monkeypatch.setattr(worker_completion_policy, "observe_github_review",
            lambda *args, **kwargs: {
                "availability": "unavailable",
                "status": "pending",
                "reason": "github_approval_missing",
            })

    # The real controller adapter deliberately calls reconciliation without
    # test-only path arguments. Point BACH's normal locators at this fixture so
    # its independent final Git read observes the same registered temp tree.
    monkeypatch.setattr(worker_git, "get_live_repo_root",
                        lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir",
                        lambda: world["tree"]["worktrees"])

    before = evaluate_current_result(conn, task_id, **_paths(world))
    assert before["availability"] == "available"
    assert before["decision"]["worker_may_claim_next"] is True
    if hard_gate == "none":
        assert before["decision"]["state"] == "completed_unreviewed"
    elif hard_gate == "user":
        assert before["decision"]["state"] == "awaiting_user_review"
    else:
        assert before["decision"]["state"] == "awaiting_external_review"

    control = telegram_chat._WorkerControl(worker_id=AUTHOR_SLOT, generation=GENERATION)
    control.task_binding = binding
    control.task_result_bindings = {task_id: binding}
    assert binding.closed is True and binding.submitted_result is not None
    assert binding._client.mode == "local"
    assert conn.in_transaction is False
    native_reconcile = binding._client._reconcile_task_completion
    reconcile_outcomes = []
    reconcile_errors = []

    def observe_reconcile(requested_task_id):
        try:
            outcome = native_reconcile(requested_task_id)
        except Exception as exc:
            reconcile_errors.append(type(exc).__name__ + ": " + str(exc))
            raise
        reconcile_outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(binding._client, "_reconcile_task_completion", observe_reconcile)
    polled = telegram_chat._poll_worker_completion(control)
    assert polled is True, {
        "mode": binding._client.mode,
        "transaction": conn.in_transaction,
        "reconcile_count": len(reconcile_outcomes),
        "reconcile_errors": reconcile_errors,
        "reconcile_state": (reconcile_outcomes[-1].get("decision", {}).get("state")
            if reconcile_outcomes and isinstance(reconcile_outcomes[-1], dict) else None),
        "status": read_result(conn, task_id)["status"],
    }
    assert len(reconcile_outcomes) == 1
    assert reconcile_errors == []

    current = read_result(conn, task_id)
    counts = tuple(conn.execute(
        "SELECT SUM(action='worker_completion_decision'),SUM(action='result_acceptance') "
        "FROM task_history WHERE task_id=?", (task_id,)).fetchone())
    if hard_gate == "none":
        assert current["status"] == "done"
        assert current["result"]["accepted"] is True
        assert counts == (1, 1)
        event = conn.execute(
            "SELECT new_value FROM task_history WHERE task_id=? "
            "AND action='worker_completion_decision'", (task_id,)).fetchone()
        assert json.loads(event[0])["decision"]["state"] == "completed_unreviewed"
        # Repeated controller observations remain idempotent.
        assert telegram_chat._poll_worker_completion(control) is True
        assert tuple(conn.execute(
            "SELECT SUM(action='worker_completion_decision'),SUM(action='result_acceptance') "
            "FROM task_history WHERE task_id=?", (task_id,)).fetchone()) == counts
    else:
        assert current["status"] == "review"
        assert current["result"]["accepted"] is False
        assert current["result"]["reason"] == "awaiting_review"
        assert counts == (0, 0)


def test_rejected_independent_review_requests_one_correction(completion_world):
    world = completion_world(mode="balanced")
    conn, task_id = world["conn"], world["task_id"]
    _record_independent_review(world, status="rejected")
    decision = evaluate_current_result(conn, task_id, **_paths(world))
    assert decision["decision"]["state"] == "correction_required"
    assert decision["decision"]["reason"] == "review_rejected"
    reconcile_current_result(conn, task_id, **_paths(world))
    assert read_result(conn, task_id)["status"] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1
    assert any(event["type"] == "correction_requested" for event in
               read_result_history(conn, task_id, limit=50)["events"])


def test_definitively_missing_task_tree_reopens_v1_for_real_correction(
    completion_world, monkeypatch,
):
    world = completion_world(missing_scope=True)
    conn, client, task_id = world["conn"], world["client"], world["task_id"]
    source = read_result(conn, task_id)["result"]
    assert source["submission"]["availability"] == "available"
    assert source["execution"]["availability"] == "available"
    assert source["scope"]["reason"] == "scope_not_recorded"
    assert source["result_revision"] is None
    assert world["binding"].closed is True
    assert client.read(task_id).leased is False

    outcome = reconcile_current_result(conn, task_id, **_paths(world))
    assert outcome["decision"]["state"] == "correction_required"
    assert outcome["decision"]["completion_allowed"] is False
    assert outcome["result_revision"] is None
    assert read_result(conn, task_id)["status"] == "pending"
    correction = conn.execute("SELECT id,correction_note,policy_decision_sha256 "
        "FROM task_result_corrections WHERE task_id=?", (task_id,)).fetchone()
    assert source["submission_revision"] in correction["correction_note"]
    assert "None" not in correction["correction_note"]
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id=? "
        "AND action='result_acceptance'", (task_id,)).fetchone()[0] == 0
    assert reconcile_current_result(conn, task_id, **_paths(world))["availability"] == "unavailable"
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1

    retry = WorkerLeaseBinding.acquire(client, task_id, worker_id="completion-author@HOST",
        host="HOST", generation="completion-correction-generation-2",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    from hub._services import task_lease
    monkeypatch.setattr(task_lease, "_utcnow", lambda: T0)
    context = read_correction_context(conn, task_id, lease_id=retry._ack.lease_id,
        fence=retry._ack.fence, task_version=retry.task_snapshot()["task_version"],
        generation="completion-correction-generation-2")
    assert context["correction"]["correction_id"] == correction["id"]


@pytest.mark.parametrize("capture_behavior", ["false", "raises"])
def test_failed_optional_scope_capture_triggers_local_correction_without_losing_ack(
    completion_world, monkeypatch, capture_behavior,
):
    world = completion_world(missing_scope=True)
    conn, client, task_id, binding = (world["conn"], world["client"],
                                      world["task_id"], world["binding"])
    before = read_result(conn, task_id)["result"]
    assert before["reason"] == "awaiting_review"
    assert binding._review_ack.released is True
    monkeypatch.setattr(client, "_reconcile_task_completion",
        lambda requested: reconcile_current_result(conn, requested, **_paths(world)))
    if capture_behavior == "raises":
        def unavailable_capture(_binding):
            raise RuntimeError("optional local Git reader failed")
        monkeypatch.setattr(client, "_capture_task_scope", unavailable_capture)
    assert binding.capture_confirmed_scope() is False
    after = read_result(conn, task_id)
    assert after["status"] == "pending"
    assert after["result"]["result_id"] == before["result_id"]
    assert after["result"]["submission_revision"] == before["submission_revision"]
    assert binding._review_ack.released is True
    assert after["result"]["accepted"] is False
    assert _correction_count(conn, task_id) == 1
    assert binding.capture_confirmed_scope() is False
    assert _correction_count(conn, task_id) == 1


@pytest.mark.parametrize("damage", ["existing_tree", "symlink", "recorded_scope", "legacy",
                                     "execution", "identity", "receipt", "task",
                                     "orphan_history", "lock_scanner", "git_command"])
def test_missing_scope_guard_rejects_nonpermanent_or_untrusted_cases(
    completion_world, damage, tmp_path, monkeypatch,
):
    world = completion_world(missing_scope=damage not in {"recorded_scope", "orphan_history"})
    conn, task_id = world["conn"], world["task_id"]
    if damage == "existing_tree":
        world["tree"]["target"].mkdir()
    elif damage == "symlink":
        try:
            os.symlink(world["tree"]["repo"], world["tree"]["target"],
                       target_is_directory=True)
        except OSError:
            pytest.skip("Testbetriebssystem erlaubt keine temporären Symlinks")
    elif damage in {"recorded_scope", "orphan_history"}:
        subprocess.run(["git", "worktree", "remove", "--force", str(world["tree"]["target"])],
            cwd=world["tree"]["repo"], env=worker_write_guard._scope_git_env(),
            check=True, capture_output=True, timeout=8)
        if damage == "orphan_history":
            conn.execute("DELETE FROM worker_scope_evidence WHERE task_id=?", (task_id,))
    elif damage == "legacy":
        conn.execute("UPDATE worker_task_results SET completion_policy_version=0 WHERE task_id=?",
                     (task_id,))
    elif damage == "execution":
        conn.execute("UPDATE worker_model_executions SET phase='failed' WHERE task_id=?",
                     (task_id,))
    elif damage == "identity":
        settings._persist(conn, IDENTITY_KEY, [
            _identity(STANDARD_REVIEWER, STANDARD_ROUTE, STANDARD_MODEL, STANDARD_OBSERVED)],
            actor="completion-fixture")
    elif damage == "receipt":
        conn.execute("UPDATE worker_task_results SET result='tampered' WHERE task_id=?", (task_id,))
    elif damage == "task":
        conn.execute("UPDATE tasks SET title=title || ' changed' WHERE id=?", (task_id,))
    elif damage == "lock_scanner":
        _install_lock_scanner(tmp_path, monkeypatch,
                              locks=[{"path": str(world["tree"]["worktrees"])}])
    elif damage == "git_command":
        def unavailable_git(*_args, **_kwargs):
            raise RuntimeError("bounded local Git read failed")
        monkeypatch.setattr(worker_write_guard, "_run_readonly", unavailable_git)
    conn.commit()
    outcome = reconcile_current_result(conn, task_id, **_paths(world))
    assert outcome["availability"] == "unavailable"
    assert read_result(conn, task_id)["status"] == "review"
    assert _correction_count(conn, task_id) == 0


def test_missing_scope_race_rolls_back_decision_and_correction(
    completion_world, monkeypatch,
):
    from hub._services import worker_completion_policy as policy
    world = completion_world(missing_scope=True)
    original = policy._definitely_missing_task_tree
    calls = 0

    def tree_arrives(task_id, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            world["tree"]["target"].mkdir()
        return original(task_id, **kwargs)

    monkeypatch.setattr(policy, "_definitely_missing_task_tree", tree_arrives)
    with pytest.raises(ResultConflict):
        reconcile_current_result(world["conn"], world["task_id"], **_paths(world))
    assert calls == 2
    assert read_result(world["conn"], world["task_id"])["status"] == "review"
    assert _correction_count(world["conn"], world["task_id"]) == 0
    assert world["conn"].execute("SELECT COUNT(*) FROM task_history WHERE task_id=? "
        "AND action='worker_completion_decision'", (world["task_id"],)).fetchone()[0] == 0


def test_high_security_findings_create_one_correction_and_allow_a_fresh_submission(
    completion_world,
):
    world = completion_world(mode="high_security")
    conn, client, task_id = world["conn"], world["client"], world["task_id"]
    pending = evaluate_current_result(conn, task_id, **_paths(world))
    assert pending["decision"]["state"] == "awaiting_review"
    assert pending["decision"]["eligible_reviewer_ids"] == [TOP_REVIEWER]
    assert pending["decision"]["worker_may_claim_next"] is False
    assert world["binding"].closed is True
    assert client.read(task_id).leased is False

    _record_independent_review(world, status="findings", task_contract_met=True)
    adverse = evaluate_current_result(conn, task_id, **_paths(world))
    assert adverse["decision"]["state"] == "correction_required"
    assert adverse["decision"]["reason"] == "high_security_findings"
    result_id = adverse["result_id"]

    after_correction = reconcile_current_result(conn, task_id, **_paths(world))
    assert after_correction["availability"] == "unavailable"
    assert read_result(conn, task_id)["status"] == "pending"
    correction_id = conn.execute(
        "SELECT result_correction_request_id FROM tasks WHERE id=?", (task_id,)
    ).fetchone()[0]
    assert type(correction_id) is int and correction_id > 0
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1

    repeated = reconcile_current_result(conn, task_id, **_paths(world))
    assert repeated["availability"] == "unavailable"
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1

    current, stop = {"value": True}, threading.Event()
    fresh = WorkerLeaseBinding.acquire(client, task_id,
        worker_id="completion-author@HOST", host="HOST", generation="completion-generation-2",
        is_current=lambda: current["value"], stop_event=stop, clock=lambda: T0)
    fresh.execute_task_manage({"action": "submit_result", "task_id": task_id,
                               "result": "Corrected result with the requested changes."})
    latest = read_result(conn, task_id)
    assert latest["status"] == "review"
    assert latest["result"]["result_id"] != result_id
    assert latest["result"]["generation"] == "completion-generation-2"
    assert latest["result"]["submission"]["availability"] == "available"
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1


def test_user_review_does_not_replace_the_separate_task_contract_finding(completion_world):
    world = completion_world(mode="simple_task", contract_min_chars=300, user_review=True)
    conn, task_id = world["conn"], world["task_id"]
    evaluation = evaluate_current_result(conn, task_id, **_paths(world))
    assert evaluation["decision"]["state"] == "result_incomplete"
    assert evaluation["contract"]["met"] is False

    from system.tests.test_worker_result_submission_receipt import _operator

    operator_token = _operator(conn)
    current = read_result(conn, task_id)
    record = current["result"]
    before_events = conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action LIKE 'worker_%review'",
        (task_id,),
    ).fetchone()[0]
    with pytest.raises(ResultConflict):
        # A pre-V1 accept call without the full result revision is not a legacy
        # acceptance path for a newly stored policy-managed submission.
        accept_result(conn, task_id, record["result_id"], digest=record["result_sha256"],
            task_version=current["task_version"], status_revision=current["status_revision"],
            task_contract_met=None, operator_token=operator_token, **_paths(world))
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action LIKE 'worker_%review'",
        (task_id,),
    ).fetchone()[0] == before_events
    with pytest.raises(ResultConflict):
        accept_result(conn, task_id, record["result_id"], digest=record["result_sha256"],
            task_version=current["task_version"], status_revision=current["status_revision"],
            result_revision="0" * 64, task_contract_met=None, operator_token=operator_token,
            **_paths(world))
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action LIKE 'worker_%review'",
        (task_id,),
    ).fetchone()[0] == before_events
    assert read_result(conn, task_id)["status"] == "review"

    accepted_review = accept_result(conn, task_id, record["result_id"],
        digest=record["result_sha256"], task_version=current["task_version"],
        status_revision=current["status_revision"], result_revision=evaluation["result_revision"],
        task_contract_met=None, operator_token=operator_token, **_paths(world))
    assert accepted_review["completion_evaluation"]["contract"]["met"] is False
    assert accepted_review["completion_evaluation"]["decision"]["state"] == "result_incomplete"
    assert read_result(conn, task_id)["status"] == "review"

    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_user_review'",
        (task_id,),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_contract_attestation'",
        (task_id,),
    ).fetchone()[0] == 0


def test_missing_contract_allows_revision_bound_user_and_contract_attestation(completion_world):
    world = completion_world(contract_min_chars=None, user_review=True)
    conn, task_id = world["conn"], world["task_id"]
    evaluation = evaluate_current_result(conn, task_id, **_paths(world))
    assert evaluation["contract"]["reason"] == "contract_not_predeclared"
    assert evaluation["decision"]["state"] == "result_incomplete"

    from system.tests.test_worker_result_submission_receipt import _operator

    operator_token = _operator(conn)
    record = read_result(conn, task_id)["result"]
    accepted = accept_result(conn, task_id, record["result_id"],
        digest=record["result_sha256"], task_version=evaluation["task_version"],
        status_revision=evaluation["status_revision"], result_revision=evaluation["result_revision"],
        task_contract_met=True, operator_token=operator_token, **_paths(world))
    assert accepted["completion_evaluation"]["contract_attested"] is True
    assert accepted["completion_evaluation"]["decision"]["state"] == "completed"
    assert read_result(conn, task_id)["status"] == "done"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_user_review'",
        (task_id,),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_contract_attestation'",
        (task_id,),
    ).fetchone()[0] == 1


def test_invalid_predeclared_contract_cannot_be_attested_as_met(completion_world):
    world = completion_world(contract_json_override='{"schema":"unknown-contract.v1","criteria":[]}')
    conn, task_id = world["conn"], world["task_id"]
    evaluation = evaluate_current_result(conn, task_id, **_paths(world))
    assert evaluation["availability"] == "available"
    assert evaluation["contract"]["availability"] == "unavailable"
    assert evaluation["contract"]["reason"] == "contract_invalid"
    assert evaluation["contract"]["met"] is False

    from system.tests.test_worker_result_submission_receipt import _operator

    operator_token = _operator(conn)
    result = read_result(conn, task_id)["result"]
    before = conn.execute(
        "SELECT SUM(action='worker_user_review'),SUM(action='worker_contract_attestation') "
        "FROM task_history WHERE task_id=?", (task_id,)
    ).fetchone()
    with pytest.raises(ResultConflict):
        accept_result(conn, task_id, result["result_id"],
            digest=result["result_sha256"], task_version=evaluation["task_version"],
            status_revision=evaluation["status_revision"],
            result_revision=evaluation["result_revision"], task_contract_met=True,
            operator_token=operator_token, **_paths(world))

    after = conn.execute(
        "SELECT SUM(action='worker_user_review'),SUM(action='worker_contract_attestation') "
        "FROM task_history WHERE task_id=?", (task_id,)
    ).fetchone()
    assert tuple(after) == tuple(before) == (0, 0)
    assert read_result(conn, task_id)["status"] == "review"
    assert read_result(conn, task_id)["result"]["accepted"] is False


def test_mandatory_github_review_blocks_even_when_external_routing_is_disabled(completion_world):
    world = completion_world(mode="simple_task", github_required=True,
                             github_external_review=False)
    conn, task_id = world["conn"], world["task_id"]
    head = world["target"]["scope"]["snapshot"]["head_oid"]

    def no_approval(number):
        assert number == 17
        return {"pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
            "head": {"sha": head}, "base": {"repo": {"full_name": "ellmos-ai/bach"}},
            "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "", "mergeStateStatus": "CLEAN"}}

    blocked = evaluate_current_result(conn, task_id, github_observer=no_approval, **_paths(world))
    assert blocked["github"]["availability"] == "unavailable"
    assert blocked["github"]["reason"] == "github_approval_missing"
    assert blocked["decision"]["state"] == "awaiting_external_review"
    reconcile_current_result(conn, task_id, github_observer=no_approval, **_paths(world))
    assert read_result(conn, task_id)["status"] == "review"

    def approved(number):
        assert number == 17
        return {"pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
            "head": {"sha": head}, "base": {"repo": {"full_name": "ellmos-ai/bach"}},
            "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [{"id": 101, "submitted_at": "2026-10-15T12:00:00Z",
                         "commit_id": head, "user": {"login": "independent-reviewer"},
                         "author_association": "MEMBER", "state": "APPROVED"}],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "APPROVED", "mergeStateStatus": "CLEAN"}}

    def untrusted_approval(number):
        observed = no_approval(number)
        observed["gate"] = {"reviewDecision": "APPROVED", "mergeStateStatus": "CLEAN"}
        observed["reviews"] = [{"id": 100, "submitted_at": "2026-10-15T11:59:00Z",
            "commit_id": head, "user": {"login": "untrusted-reviewer"},
            "author_association": "FIRST_TIME_CONTRIBUTOR", "state": "APPROVED"}]
        return observed

    untrusted = evaluate_current_result(conn, task_id,
        github_observer=untrusted_approval, **_paths(world))
    assert untrusted["github"]["availability"] == "unavailable"
    assert untrusted["github"]["reason"] == "github_approval_missing"
    assert untrusted["decision"]["state"] == "awaiting_external_review"

    def draft_pr(number):
        observed = approved(number)
        observed["pull"]["draft"] = True
        return observed

    draft = evaluate_current_result(conn, task_id,
        github_observer=draft_pr, **_paths(world))
    assert draft["github"]["availability"] == "unavailable"
    assert draft["github"]["reason"] == "github_pr_not_current"

    ready = evaluate_current_result(conn, task_id, github_observer=approved, **_paths(world))
    assert ready["github"]["availability"] == "available"
    assert ready["github"]["status"] == "verified"
    assert ready["decision"]["completion_allowed"] is True
    assert reconcile_current_result(conn, task_id, github_observer=approved,
                                    **_paths(world))["status"] == "done"


@pytest.mark.parametrize(
    ("reviewer", "association"),
    [("task-author", "OWNER"), ("untrusted-reviewer", "FIRST_TIME_CONTRIBUTOR")],
    ids=["author", "untrusted-reviewer"],
)
def test_untrusted_github_changes_requested_stays_pending_without_correction(
    completion_world, reviewer, association
):
    world = completion_world(mode="simple_task", github_required=True)
    conn, task_id = world["conn"], world["task_id"]
    head = world["target"]["scope"]["snapshot"]["head_oid"]

    def blocked_by_untrusted_review(number):
        assert number == 17
        return {
            "pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
                "head": {"sha": head}, "base": {"repo": {"full_name": "ellmos-ai/bach"}},
                "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [{"id": 201, "submitted_at": "2026-10-15T12:01:00Z",
                "commit_id": head, "user": {"login": reviewer},
                "author_association": association, "state": "CHANGES_REQUESTED"}],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            # GitHub may report the blocked gate even though this request cannot
            # authoritatively reject the task result.
            "gate": {"reviewDecision": "CHANGES_REQUESTED", "mergeStateStatus": "CLEAN"},
        }

    observed = evaluate_current_result(conn, task_id,
        github_observer=blocked_by_untrusted_review, **_paths(world))
    assert observed["github"]["availability"] == "unavailable"
    assert observed["github"]["status"] == "pending"
    assert observed["decision"]["state"] == "awaiting_external_review"

    reconcile_current_result(conn, task_id,
        github_observer=blocked_by_untrusted_review, **_paths(world))
    assert read_result(conn, task_id)["status"] == "review"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='result_correction_request'",
        (task_id,),
    ).fetchone()[0] == 0
    correction_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_result_corrections'"
    ).fetchone()
    assert correction_table is None or conn.execute(
        "SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 0


def test_eligible_github_changes_requested_creates_one_correction(completion_world):
    world = completion_world(mode="simple_task", github_required=True)
    conn, task_id = world["conn"], world["task_id"]
    head = world["target"]["scope"]["snapshot"]["head_oid"]

    def eligible_adverse_review(number):
        assert number == 17
        return {
            "pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
                "head": {"sha": head}, "base": {"repo": {"full_name": "ellmos-ai/bach"}},
                "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [{"id": 202, "submitted_at": "2026-10-15T12:02:00Z",
                "commit_id": head, "user": {"login": "independent-member"},
                "author_association": "MEMBER", "state": "CHANGES_REQUESTED"}],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "CHANGES_REQUESTED", "mergeStateStatus": "CLEAN"},
        }

    adverse = evaluate_current_result(conn, task_id,
        github_observer=eligible_adverse_review, **_paths(world))
    assert adverse["github"]["availability"] == "available"
    assert adverse["github"]["status"] == "rejected"
    assert adverse["decision"]["state"] == "correction_required"

    reconcile_current_result(conn, task_id,
        github_observer=eligible_adverse_review, **_paths(world))
    assert read_result(conn, task_id)["status"] == "pending"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 1
    reconcile_current_result(conn, task_id,
        github_observer=eligible_adverse_review, **_paths(world))
    assert conn.execute(
        "SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?", (task_id,)
    ).fetchone()[0] == 1


def test_operator_reconcile_post_rechecks_late_github_approval_and_authority(
    completion_world, tmp_path, monkeypatch
):
    """A late external approval needs a current operator and the full read revision."""
    import asyncio
    from types import SimpleNamespace
    from fastapi import HTTPException
    from gui import server
    from gui.device_auth import _hash_token, create_task_result_operator
    from hub._services.chat import worker_write_guard
    from hub._services import worker_github_review

    world = completion_world(mode="simple_task", github_required=True,
                             github_external_review=False)
    conn, task_id = world["conn"], world["task_id"]
    head = world["target"]["scope"]["snapshot"]["head_oid"]
    native_snapshot = worker_write_guard.snapshot_task_scope

    def local_scope_snapshot(requested_task_id, *, repo_root=None, worktrees_dir=None):
        return native_snapshot(requested_task_id,
            repo_root=repo_root or world["tree"]["repo"],
            worktrees_dir=worktrees_dir or world["tree"]["worktrees"])

    monkeypatch.setattr(worker_write_guard, "snapshot_task_scope", local_scope_snapshot)

    def no_approval(number):
        assert number == 17
        return {"pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
            "head": {"sha": head}, "base": {"repo": {"full_name": "ellmos-ai/bach"}},
            "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "", "mergeStateStatus": "CLEAN"}}

    def approved(number):
        assert number == 17
        return {"pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
            "head": {"sha": head}, "base": {"repo": {"full_name": "ellmos-ai/bach"}},
            "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [{"id": 101, "submitted_at": "2026-10-15T12:00:00Z",
                         "commit_id": head, "user": {"login": "independent-reviewer"},
                         "author_association": "MEMBER", "state": "APPROVED"}],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "APPROVED", "mergeStateStatus": "CLEAN"}}

    pending = evaluate_current_result(conn, task_id, github_observer=no_approval,
                                      **_paths(world))
    assert pending["decision"]["state"] == "awaiting_external_review"
    assert read_result(conn, task_id)["status"] == "review"

    db_path = tmp_path / "completion-operator-reconcile.sqlite"
    seed = sqlite3.connect(str(db_path), timeout=5)
    conn.backup(seed)
    seed.close()

    def connect():
        database = sqlite3.connect(str(db_path), timeout=5)
        database.row_factory = sqlite3.Row
        return database

    def task_status():
        database = connect()
        try:
            return database.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
        finally:
            database.close()

    monkeypatch.setattr(server, "get_bach_db", connect)
    keeper = connect()
    try:
        token = create_task_result_operator("late-github-operator", connection=keeper)
        monkeypatch.setattr(worker_github_review, "_public_observer", no_approval)
        body = server.TaskResultReconcileRequest(
            result_id=pending["result_id"], result_sha256=pending["result_sha256"],
            result_revision=pending["result_revision"], task_version=pending["task_version"],
            status_revision=pending["status_revision"],
        )

        def post(operator_token=None, request_body=body):
            headers = {} if operator_token is None else {
                "X-BACH-Result-Operator": operator_token,
            }
            return asyncio.run(server.reconcile_task_result(task_id, request_body,
                SimpleNamespace(headers=headers)))

        with pytest.raises(HTTPException) as missing_operator:
            post()
        assert missing_operator.value.status_code == 403

        stale_revision = ("0" if body.result_revision[0] != "0" else "1") + body.result_revision[1:]
        stale_body = body.model_copy(update={"result_revision": stale_revision})
        with pytest.raises(HTTPException) as stale:
            post(token, stale_body)
        assert stale.value.status_code == 409
        assert task_status() == "review"

        keeper.execute("UPDATE devices SET status='revoked',revoked_at=CURRENT_TIMESTAMP "
                       "WHERE token_hash=?", (_hash_token(token),))
        keeper.commit()
        with pytest.raises(HTTPException) as revoked_operator:
            post(token)
        assert revoked_operator.value.status_code == 403
        assert task_status() == "review"

        fresh_token = create_task_result_operator("late-github-operator-renewed", connection=keeper)
        monkeypatch.setattr(worker_github_review, "_public_observer", approved)
        result = post(fresh_token)
        assert result["status"] == "done"
        final_conn = connect()
        try:
            assert final_conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "done"
            assert final_conn.execute(
                "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_user_review'",
                (task_id,),
            ).fetchone()[0] == 0
            assert final_conn.execute(
                "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_completion_decision'",
                (task_id,),
            ).fetchone()[0] == 1
        finally:
            final_conn.close()
    finally:
        keeper.close()


def test_operator_reconcile_rejects_a_result_revision_race_before_deciding(
    completion_world, monkeypatch
):
    from gui.device_auth import create_task_result_operator
    from hub._services import worker_completion_policy

    world = completion_world(mode="simple_task")
    conn, task_id = world["conn"], world["task_id"]
    token = create_task_result_operator("completion-race-operator", connection=conn)
    observed = evaluate_current_result(conn, task_id, **_paths(world))
    native_evaluate = worker_completion_policy.evaluate_current_result
    calls = {"count": 0}

    def change_after_operator_evaluation(*args, **kwargs):
        result = native_evaluate(*args, **kwargs)
        calls["count"] += 1
        if calls["count"] == 1:
            conn.execute("UPDATE worker_task_results SET result_sha256=? WHERE id=?",
                (hashlib.sha256(b"replacement result revision").hexdigest(), observed["result_id"]))
            conn.commit()
        return result

    monkeypatch.setattr(worker_completion_policy, "evaluate_current_result",
                        change_after_operator_evaluation)
    with pytest.raises(ResultConflict):
        worker_completion_policy.reconcile_operator_result(conn, task_id,
            result_id=observed["result_id"], result_sha256=observed["result_sha256"],
            result_revision=observed["result_revision"], task_version=observed["task_version"],
            status_revision=observed["status_revision"], operator_token=token,
            **_paths(world))
    assert calls["count"] == 2
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_completion_decision'",
        (task_id,),
    ).fetchone()[0] == 0


@pytest.mark.parametrize("capability", ["missing", "revoked"])
def test_operator_authority_is_checked_before_git_or_github_evaluation(
    completion_world, monkeypatch, capability
):
    """A denied personal review must not trigger expensive evidence reads."""
    from gui.device_auth import _hash_token, create_task_result_operator
    from hub._services import worker_completion_policy

    world = completion_world(mode="simple_task", github_required=True,
                             github_external_review=False)
    conn, task_id = world["conn"], world["task_id"]
    head = world["target"]["scope"]["snapshot"]["head_oid"]

    def pending_github(number):
        assert number == 17
        return {
            "pull": {
                "html_url": "https://github.com/ellmos-ai/bach/pull/17",
                "head": {"sha": head},
                "base": {"repo": {"full_name": "ellmos-ai/bach"}},
                "user": {"login": "task-author"},
                "draft": False,
                "state": "open",
            },
            "reviews": [],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "", "mergeStateStatus": "CLEAN"},
        }

    observed = evaluate_current_result(
        conn, task_id, github_observer=pending_github, **_paths(world)
    )
    assert observed["decision"]["state"] == "awaiting_external_review"

    if capability == "missing":
        operator_token = None
    else:
        operator_token = create_task_result_operator(
            "completion-revoked-operator", connection=conn
        )
        conn.execute(
            "UPDATE devices SET status='revoked',revoked_at=CURRENT_TIMESTAMP "
            "WHERE token_hash=?", (_hash_token(operator_token),)
        )
        conn.commit()

    calls = []

    def forbidden_evidence(*args, **kwargs):
        calls.append("evidence")
        raise AssertionError("evidence evaluation ran before operator authorization")

    monkeypatch.setattr(worker_completion_policy, "evaluate_current_result", forbidden_evidence)
    monkeypatch.setattr(worker_completion_policy, "observe_github_review", forbidden_evidence)
    before = tuple(conn.execute(
        "SELECT SUM(action='worker_user_review'),SUM(action='worker_contract_attestation'),"
        "SUM(action='worker_completion_decision'),SUM(action='result_acceptance') "
        "FROM task_history WHERE task_id=?", (task_id,)).fetchone())
    with pytest.raises(ResultPermissionDenied):
        accept_result(conn, task_id, observed["result_id"],
            digest=observed["result_sha256"], task_version=observed["task_version"],
            status_revision=observed["status_revision"],
            result_revision=observed["result_revision"], task_contract_met=None,
            operator_token=operator_token, github_observer=forbidden_evidence,
            **_paths(world))
    after = tuple(conn.execute(
        "SELECT SUM(action='worker_user_review'),SUM(action='worker_contract_attestation'),"
        "SUM(action='worker_completion_decision'),SUM(action='result_acceptance') "
        "FROM task_history WHERE task_id=?", (task_id,)).fetchone())
    assert calls == []
    assert after == before == (0, 0, 0, 0)
    assert read_result(conn, task_id)["status"] == "review"
    assert read_result(conn, task_id)["result"]["accepted"] is False


@pytest.mark.parametrize(
    ("case", "may_claim", "stale_field", "expected"),
    [
        ("balanced-current", True, None, True),
        ("high-security-waits", False, None, False),
        ("stale-result-revision", True, "result_revision", False),
        ("stale-task-version", True, "task_version", False),
        ("stale-status-revision", True, "status_revision", False),
        ("unavailable-lead-evaluation", True, "availability", False),
    ],
)
def test_remote_controller_claim_gate_requires_exact_lead_completion_readback(
    monkeypatch, case, may_claim, stale_field, expected
):
    """Remote workers may claim again only from an exact current Lead decision."""
    import copy
    from types import SimpleNamespace
    from hub._services.chat import telegram_chat

    conn = sqlite3.connect(":memory:")
    task_id = 91021
    result_text = "Remote Lead result with a confirmed submission receipt."
    result_sha = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
    version = "a" * 64
    revision = "b" * 64
    result_id = 4201
    generation = "remote-completion-generation"
    fence = 31
    status_revision = 17
    record = {
        "schema": "bach.worker-result.v1", "task_id": task_id,
        "result_id": result_id, "result": result_text, "result_sha256": result_sha,
        "accepted": False, "completion_policy_version": 1,
        "submission": {"availability": "available"},
        "reason": "awaiting_review", "result_revision": revision,
        "generation": generation, "fence": fence, "task_version": version,
    }
    lead_decision = {"worker_may_claim_next": may_claim}
    evaluation = {
        "availability": "available", "task_id": task_id, "result_id": result_id,
        "result_revision": revision, "task_version": version,
        "status_revision": status_revision, "decision": lead_decision,
    }
    readback = {
        "schema": "bach.task-result-readback.v1", "task_id": task_id,
        "verified": True, "status": "review", "status_revision": status_revision,
        "task_version": version, "result": record,
        "completion_evaluation": evaluation,
    }
    if stale_field == "result_revision":
        readback["result"]["result_revision"] = "c" * 64
    elif stale_field == "task_version":
        readback["result"]["task_version"] = "c" * 64
        readback["task_version"] = "c" * 64
        readback["completion_evaluation"]["task_version"] = "c" * 64
    elif stale_field == "status_revision":
        readback["status_revision"] = status_revision + 1
    elif stale_field == "availability":
        readback["completion_evaluation"]["availability"] = "unavailable"

    remote = TaskLeaseClient(conn=conn, lead_url="https://lead.invalid",
                             device_token="fixture-remote-device")
    assert remote.mode == "remote"
    requests = []

    def lead_get(method, path, payload=None, headers=None):
        requests.append((method, path, payload, headers))
        return 200, copy.deepcopy(readback)

    monkeypatch.setattr(remote, "_http_request", lead_get)
    before_changes, before_schema = conn.total_changes, _schema_objects(conn)
    binding = SimpleNamespace(task_id=task_id, _client=remote, submitted_result={
        "result_id": result_id, "result_sha256": result_sha,
        "generation": generation, "fence": fence, "task_version": version,
    })
    control = telegram_chat._WorkerControl(worker_id=f"remote-{case}", generation=generation)
    control.task_binding = binding
    control.task_result_bindings = {task_id: binding}

    assert telegram_chat._poll_worker_completion(control) is expected
    assert requests == [("GET", f"/api/tasks/{task_id}/result", None, None)]
    assert control.completion_poll_blocked[task_id] is (not expected)
    assert conn.total_changes == before_changes
    assert _schema_objects(conn) == before_schema


def test_missing_contract_never_completes(completion_world):
    missing = completion_world(mode="simple_task", contract_min_chars=None)
    no_contract = evaluate_current_result(missing["conn"], missing["task_id"], **_paths(missing))
    assert no_contract["availability"] == "available"
    assert no_contract["contract"]["availability"] == "unavailable"
    assert no_contract["decision"]["state"] == "result_incomplete"
    reconcile_current_result(missing["conn"], missing["task_id"], **_paths(missing))
    assert read_result(missing["conn"], missing["task_id"])["status"] == "review"


@pytest.mark.parametrize("mode", ["simple_task", "balanced", "high_security"])
def test_unstructured_task_finishes_through_independent_review_without_personal_approval(
    completion_world, monkeypatch, mode
):
    """Actual review evidence drives the existing controller hook, without a user event."""
    from hub import worker_git

    world = completion_world(mode=mode, contract_min_chars=None)
    conn, task_id = world["conn"], world["task_id"]
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: world["tree"]["worktrees"])
    before = evaluate_current_result(conn, task_id, **_paths(world))
    assert before["decision"]["completion_allowed"] is False
    evidence = _record_independent_review(world)
    assert evidence["reviewer_asserted_task_contract_met"] is True

    completed = world["client"]._reconcile_task_completion(task_id)
    assert completed["availability"] == "available"
    assert completed["status"] == "done"
    assert completed["contract"]["met"] is False  # No invented machine proof.
    assert completed["contract_attested"] is False
    assert completed["user_approved"] is False
    assert completed["contract_finding"] == {
        "met": True, "source": "independent_model_review",
        "review_task_id": evidence["review_task_id"],
    }
    assert read_result(conn, task_id)["result"]["accepted"] is True
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id=? AND action IN "
        "('worker_user_review','worker_contract_attestation')", (task_id,)).fetchone()[0] == 0
    assert world["client"]._reconcile_task_completion(task_id)["status"] == "done"
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id=? "
        "AND action='result_acceptance'", (task_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("gate", ["user", "github"])
def test_independent_semantic_finding_never_supplies_a_mandatory_external_approval(
    completion_world, gate
):
    world = completion_world(mode="balanced", contract_min_chars=None,
        user_review=gate == "user", github_required=gate == "github")
    _record_independent_review(world)
    observed = evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert observed["contract_finding"]["source"] == "independent_model_review"
    assert observed["contract_finding"]["met"] is True
    assert observed["user_approved"] is False
    assert observed["decision"]["completion_allowed"] is False
    reconcile_current_result(world["conn"], world["task_id"], **_paths(world))
    assert read_result(world["conn"], world["task_id"])["status"] == "review"


@pytest.mark.parametrize("invalid_contract", ["", "{}", "not-json", "unmet-criterion"])
def test_independent_review_cannot_replace_invalid_or_unmet_machine_criteria(
    completion_world, invalid_contract
):
    world = completion_world(mode="balanced",
        contract_min_chars=300 if invalid_contract == "unmet-criterion" else None,
        contract_json_override=None if invalid_contract == "unmet-criterion" else invalid_contract)
    _record_independent_review(world)
    observed = evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert observed["contract_finding"] == {
        "met": False, "source": "unconfirmed", "review_task_id": None,
    }
    assert observed["decision"]["completion_allowed"] is False
    reconcile_current_result(world["conn"], world["task_id"], **_paths(world))
    assert read_result(world["conn"], world["task_id"])["status"] == "review"


@pytest.mark.parametrize("review_status", ["findings", "rejected"])
def test_adverse_review_never_establishes_semantic_task_contract(
    completion_world, review_status
):
    world = completion_world(mode="balanced", contract_min_chars=None)
    evidence = _record_independent_review(world, status=review_status)
    assert evidence["reviewer_asserted_task_contract_met"] is False
    observed = evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert observed["contract_finding"]["met"] is False
    assert observed["decision"]["completion_allowed"] is False


@pytest.mark.parametrize("mode", ["simple_task", "balanced", "high_security"])
@pytest.mark.parametrize("review_status", ["findings", "rejected"])
def test_current_negative_review_vetoes_green_predeclared_contract_and_requeues(
    completion_world, monkeypatch, mode, review_status
):
    from hub import worker_git
    from hub._services.task_result_service import active_correction_request

    world = completion_world(mode=mode, contract_min_chars=12, contract_git_blob=True)
    conn, client, task_id = world["conn"], world["client"], world["task_id"]
    before = evaluate_current_result(conn, task_id, **_paths(world))
    assert before["contract"]["met"] is True
    old_result_id = before["result_id"]
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: world["tree"]["worktrees"])

    review_task_id = _record_independent_review(
        world, status=review_status, task_contract_met=False, read_current_evidence=False)

    assert read_result(conn, task_id)["status"] == "pending"
    request = active_correction_request(conn, task_id)
    assert request is not None and request["source_result_id"] == old_result_id
    assert _correction_count(conn, task_id) == 1
    recorded = conn.execute(
        "SELECT receipt FROM worker_result_model_reviews WHERE target_task_id=? "
        "AND target_result_id=? AND review_task_id=?",
        (task_id, old_result_id, review_task_id),
    ).fetchone()
    assert recorded is not None
    receipt = json.loads(recorded[0])
    assert receipt["status"] == review_status
    assert receipt["reviewer_asserted_task_contract_met"] is False
    assert receipt["target_revision"] == before["result_revision"]
    decision_rows = conn.execute(
        "SELECT new_value FROM task_history WHERE task_id=? "
        "AND action='worker_completion_decision'", (task_id,),
    ).fetchall()
    assert len(decision_rows) == 1
    decision = json.loads(decision_rows[0][0])["decision"]
    assert decision["state"] == "correction_required"
    assert decision["completion_allowed"] is False
    assert decision["dependents_may_start"] is False
    assert decision["worker_may_claim_next"] is (mode != "high_security")
    if review_status == "findings":
        assert decision["reason"] == "review_findings_contract_not_met"


def test_balanced_findings_with_positive_contract_attestation_remain_nonblocking(
    completion_world
):
    world = completion_world(mode="balanced", contract_min_chars=12, contract_git_blob=True)
    evidence = _record_independent_review(
        world, status="findings", task_contract_met=True)
    observed = evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert evidence["reviewer_asserted_task_contract_met"] is True
    assert observed["contract"]["met"] is True
    assert observed["contract_finding"]["met"] is True
    assert observed["decision"]["state"] == "completed"
    assert observed["decision"]["reason"] == "non_blocking_review_findings"
    assert observed["decision"]["completion_allowed"] is True


@pytest.mark.parametrize("mismatch", ["task_id", "result_id", "result_revision", "independent"])
def test_noncurrent_negative_review_cannot_veto_a_green_contract(
    completion_world, monkeypatch, mismatch
):
    from hub._services import worker_completion_policy as completion_policy

    world = completion_world(mode="balanced", contract_min_chars=12, contract_git_blob=True)
    real_read_result = completion_policy.read_result

    def read_with_noncurrent_review(conn, task_id):
        observed = real_read_result(conn, task_id)
        record = observed.get("result")
        if task_id == world["task_id"] and isinstance(record, dict):
            projected = worker_scope_evidence.project_scope_evidence(
                observed, **_paths(world))["result"]
            review_evidence = {
                "schema": "bach.worker-result-review-evidence.v1",
                "availability": "available", "status": "findings",
                "independent": True, "task_id": task_id,
                "reviewer_id": TOP_REVIEWER,
                "review_task_id": task_id + 100,
                "result_id": record["result_id"],
                "result_revision": projected["result_revision"],
                "reviewer_asserted_task_contract_met": False,
            }
            if mismatch == "task_id":
                review_evidence["task_id"] = task_id + 1
            elif mismatch == "result_id":
                review_evidence["result_id"] += 1
            elif mismatch == "result_revision":
                review_evidence["result_revision"] = "f" * 64
            elif mismatch == "independent":
                review_evidence["independent"] = False
            record["model_review"] = review_evidence
        return observed

    monkeypatch.setattr(completion_policy, "read_result", read_with_noncurrent_review)
    observed = evaluate_current_result(world["conn"], world["task_id"], **_paths(world))
    assert observed["contract"]["met"] is True
    assert observed["contract_finding"]["met"] is True
    assert observed["contract_finding"]["source"] == "predeclared_criteria"
    assert observed["decision"]["state"] != "correction_required"
    assert observed["decision"]["reason"] != "review_findings_contract_not_met"


@pytest.mark.parametrize(("review_status", "decision_reason"), [
    ("findings", "review_findings_contract_not_met"),
    ("rejected", "review_rejected"),
])
def test_external_github_approval_does_not_override_negative_contract_finding(
    completion_world, monkeypatch, review_status, decision_reason
):
    from hub._services import worker_completion_policy as completion_policy

    world = completion_world(mode="balanced", contract_min_chars=12,
                             contract_git_blob=True, github_required=True,
                             github_external_review=True)
    conn, task_id = world["conn"], world["task_id"]
    head = world["target"]["scope"]["snapshot"]["head_oid"]
    real_read_result = completion_policy.read_result

    def read_with_current_negative_review(connection, requested_task_id):
        observed = real_read_result(connection, requested_task_id)
        record = observed.get("result")
        if requested_task_id == task_id and isinstance(record, dict):
            projected = worker_scope_evidence.project_scope_evidence(
                observed, **_paths(world))["result"]
            record["model_review"] = {
                "schema": "bach.worker-result-review-evidence.v1",
                "availability": "available", "status": review_status,
                "independent": True, "task_id": task_id,
                "reviewer_id": TOP_REVIEWER,
                "result_id": record["result_id"],
                "result_revision": projected["result_revision"],
                "review_task_id": task_id + 100,
                "reviewer_asserted_task_contract_met": False,
            }
        return observed

    def approved_github(number):
        assert number == 17
        return {
            "pull": {"html_url": "https://github.com/ellmos-ai/bach/pull/17",
                "head": {"sha": head},
                "base": {"repo": {"full_name": "ellmos-ai/bach"}},
                "user": {"login": "task-author"}, "draft": False, "state": "open"},
            "reviews": [{"id": 901, "submitted_at": "2026-10-15T12:00:00Z",
                "commit_id": head, "user": {"login": "independent-reviewer"},
                "author_association": "MEMBER", "state": "APPROVED"}],
            "checks": [{"head_sha": head, "name": "unit", "conclusion": "success"}],
            "gate": {"reviewDecision": "APPROVED", "mergeStateStatus": "CLEAN"},
        }

    monkeypatch.setattr(completion_policy, "read_result", read_with_current_negative_review)
    observed = evaluate_current_result(conn, task_id, github_observer=approved_github,
                                      **_paths(world))
    assert observed["contract"]["met"] is True
    assert observed["github"]["availability"] == "available"
    assert observed["github"]["status"] == "verified"
    assert observed["contract_finding"]["met"] is False
    assert observed["contract_finding"]["source"] == "independent_model_review"
    assert observed["contract_finding"]["review_status"] == review_status
    assert observed["contract_finding"]["reviewer_asserted_task_contract_met"] is False
    assert observed["contract_finding"]["review_task_id"] == task_id + 100
    assert observed["decision"]["state"] == "correction_required"
    assert observed["decision"]["reason"] == decision_reason
    assert observed["decision"]["completion_allowed"] is False
    assert observed["decision"]["dependents_may_start"] is False
    reconcile_current_result(conn, task_id, github_observer=approved_github,
                             **_paths(world))
    assert read_result(conn, task_id)["status"] == "pending"
    assert _correction_count(conn, task_id) == 1


@pytest.mark.parametrize("contract_min_chars", [None, 300], ids=["missing-contract", "failed-contract"])
@pytest.mark.parametrize(("mode", "review_status"), [
    ("simple_task", "rejected"), ("balanced", "rejected"),
    ("high_security", "rejected"), ("high_security", "findings"),
])
def test_unmet_contract_adverse_review_requeues_once_and_allows_fresh_generation(
    completion_world, monkeypatch, mode, review_status, contract_min_chars
):
    from hub import worker_git
    from hub._services.task_result_service import active_correction_request

    world = completion_world(mode=mode, contract_min_chars=contract_min_chars)
    conn, client, task_id = world["conn"], world["client"], world["task_id"]
    observed = evaluate_current_result(conn, task_id, **_paths(world))
    assert observed["contract_finding"]["met"] is False
    assert observed["decision"]["completion_allowed"] is False
    old_result_id = observed["result_id"]
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: world["tree"]["worktrees"])
    # The actual child Submit -> review receipt -> SDK reconciliation must
    # perform this transition, without an explicit test-side Reconcile call.
    review_task_id = _record_independent_review(
        world, status=review_status, read_current_evidence=False)
    assert read_result(conn, task_id)["status"] == "pending"
    request = active_correction_request(conn, task_id)
    assert request is not None and request["source_result_id"] == old_result_id
    assert conn.execute("SELECT requested_by_device_id FROM task_result_corrections "
        "WHERE task_id=?", (task_id,)).fetchone()[0] == 0
    recorded = conn.execute("SELECT receipt,receipt_sha256,event_id FROM worker_result_model_reviews "
        "WHERE target_task_id=? AND target_result_id=? AND review_task_id=?",
        (task_id, old_result_id, review_task_id)).fetchone()
    assert recorded is not None
    receipt = json.loads(recorded[0])
    assert review._digest(receipt) == recorded[1]
    assert receipt["status"] == review_status
    assert receipt["reviewer_asserted_task_contract_met"] is False
    assert receipt["target_revision"] == observed["result_revision"]
    assert receipt["reviewer_id"] == TOP_REVIEWER != receipt["author_id"]
    event = conn.execute("SELECT new_value FROM task_history WHERE id=? AND task_id=? "
        "AND action='worker_result_model_review'", (recorded[2], task_id)).fetchone()
    assert event is not None and json.loads(event[0])["receipt_sha256"] == recorded[1]
    decisions = conn.execute("SELECT new_value FROM task_history WHERE task_id=? "
        "AND action='worker_completion_decision'", (task_id,)).fetchall()
    assert len(decisions) == 1
    decision = json.loads(decisions[0][0])["decision"]
    assert decision["state"] == "correction_required"
    assert decision["completion_allowed"] is False
    reconcile_current_result(conn, task_id, **_paths(world))
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1
    fresh = WorkerLeaseBinding.acquire(client, task_id,
        worker_id="completion-author@HOST", host="HOST", generation="unmet-rework-generation-2",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    fresh.execute_task_manage({"action": "submit_result", "task_id": task_id,
                               "result": "Fresh correction submission with its own result revision."})
    current = read_result(conn, task_id)
    assert current["status"] == "review"
    assert current["result"]["result_id"] != old_result_id
    assert current["result"]["generation"] == "unmet-rework-generation-2"
    assert current["result"]["submission"]["availability"] == "available"
    assert current["result"]["accepted"] is False
    assert conn.execute("SELECT COUNT(*) FROM task_result_corrections WHERE task_id=?",
                        (task_id,)).fetchone()[0] == 1


def test_stale_task_content_never_completes(completion_world):
    stale = completion_world(mode="simple_task")
    stale["conn"].execute("UPDATE tasks SET description='Changed after submission' WHERE id=?",
                          (stale["task_id"],))
    stale["conn"].commit()
    changed = evaluate_current_result(stale["conn"], stale["task_id"], **_paths(stale))
    assert changed["availability"] == "unavailable"
    assert changed["reason"] == "result_not_current"
    reconcile_current_result(stale["conn"], stale["task_id"], **_paths(stale))
    assert read_result(stale["conn"], stale["task_id"])["status"] == "review"
    assert stale["conn"].execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_completion_decision'",
        (stale["task_id"],),
    ).fetchone()[0] == 0


def test_completion_audit_failure_rolls_back_and_can_be_retried(completion_world, monkeypatch):
    world = completion_world(mode="simple_task")
    conn, task_id = world["conn"], world["task_id"]
    from hub._services import task_lease

    original_history = task_lease._history
    failed = {"once": False}

    def fail_after_status_change(connection, requested_task_id, action, *args, **kwargs):
        if action == "result_acceptance" and not failed["once"]:
            failed["once"] = True
            raise sqlite3.OperationalError("simulated audit storage failure")
        return original_history(connection, requested_task_id, action, *args, **kwargs)

    monkeypatch.setattr(task_lease, "_history", fail_after_status_change)
    with pytest.raises(sqlite3.OperationalError):
        reconcile_current_result(conn, task_id, **_paths(world))
    assert read_result(conn, task_id)["status"] == "review"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_completion_decision'",
        (task_id,),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='result_acceptance'",
        (task_id,),
    ).fetchone()[0] == 0

    monkeypatch.setattr(task_lease, "_history", original_history)
    retried = reconcile_current_result(conn, task_id, **_paths(world))
    assert retried["availability"] == "available"
    assert retried["status"] == "done"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='worker_completion_decision'",
        (task_id,),
    ).fetchone()[0] == 1


def test_additive_completion_fields_preserve_a_live_legacy_lease_fingerprint():
    """NULL-only completion columns must not stale a lease acquired on an old schema."""
    conn = _legacy_db()
    try:
        task_id = _insert_task(conn, "Pre-completion-schema task")
        client = TaskLeaseClient(conn=conn)
        before = client.task_snapshot(task_id)
        generation = "legacy-schema-generation"
        lease = client.acquire(
            task_id,
            worker_id="legacy-worker@HOST",
            host="HOST",
            intent="schema compatibility regression",
            task_version=before["task_version"],
            result_generation=generation,
            now=T0,
        )
        assert lease.lease_id and lease.fence == 1

        ensure_task_result_contract_columns(conn)

        after = client.task_snapshot(task_id)
        assert after["task_version"] == before["task_version"]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert {
            "completion_contract_json",
            "require_user_review",
            "github_pr_review_required",
            "github_review_contract_json",
        } <= columns
        row = conn.execute(
            "SELECT completion_contract_json,require_user_review,"
            "github_pr_review_required,github_review_contract_json "
            "FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        assert tuple(row) == (None, None, None, None)

        # The original claim still passes the real submit/release CAS after the
        # additive migration. This is stronger than comparing a hash alone.
        ack = client.submit_result(
            task_id,
            lease_id=lease.lease_id,
            fence=lease.fence,
            task_version=before["task_version"],
            generation=generation,
            result="Legacy claim remains valid after nullable completion columns.",
            now=T0,
        )
        assert ack.release.task_id == task_id
        assert ack.record["task_id"] == task_id
        snapshot = client.task_result_snapshot(task_id)
        assert snapshot["status"] == "review"
        assert snapshot["result"] is not None
        assert snapshot["result"]["submission"]["availability"] == "available"
    finally:
        conn.close()


@pytest.mark.parametrize("with_result_table", [False, True], ids=["no-result-table", "empty-result-table"])
@pytest.mark.parametrize(
    ("gate_column", "gate_value"),
    [
        ("require_user_review", 1),
        ("github_pr_review_required", 1),
        ("completion_contract_json", _contract()),
    ],
    ids=["user-review", "github-review", "predeclared-contract"],
)
def test_task_audit_cannot_done_a_pre_gated_task_without_a_worker_result(
    with_result_table, gate_column, gate_value
):
    from hub.task_audit import apply_task_field_changes

    conn = _legacy_db()
    try:
        ensure_task_result_contract_columns(conn)
        if with_result_table:
            from hub._services.task_result_service import ensure_result_schema

            ensure_result_schema(conn)
        gated_id = _insert_task(conn, "Pre-gated task without result")
        conn.execute(f"UPDATE tasks SET {gate_column}=? WHERE id=?", (gate_value, gated_id))
        conn.commit()

        with pytest.raises(ResultConflict):
            apply_task_field_changes(conn, gated_id,
                dict(conn.execute("SELECT * FROM tasks WHERE id=?", (gated_id,)).fetchone()),
                {"status": "done"}, changed_by="fixture-operator",
                now="2026-10-15T12:00:00.000000")
        assert conn.execute("SELECT status FROM tasks WHERE id=?", (gated_id,)).fetchone()[0] == "open"
        assert conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id=?", (gated_id,)).fetchone()[0] == 0

        # The guard preserves the existing path for a historical ungated task.
        legacy_id = _insert_task(conn, "Historical ungated task")
        changed = apply_task_field_changes(conn, legacy_id,
            dict(conn.execute("SELECT * FROM tasks WHERE id=?", (legacy_id,)).fetchone()),
            {"status": "done"}, changed_by="fixture-operator",
            now="2026-10-15T12:00:00.000000")
        assert changed is True
        assert conn.execute("SELECT status FROM tasks WHERE id=?", (legacy_id,)).fetchone()[0] == "done"
    finally:
        conn.close()


@pytest.mark.parametrize("drop_result_table", [False, True], ids=["delete-v1-row", "drop-result-table"])
def test_task_audit_cannot_launder_an_ungated_v1_submission_after_result_loss(
    completion_world, drop_result_table
):
    from hub.task_audit import apply_task_field_changes

    world = completion_world(mode="simple_task", contract_min_chars=None)
    conn, task_id = world["conn"], world["task_id"]
    current = read_result(conn, task_id)
    record = current["result"]
    assert record["completion_policy_version"] == 1
    assert record["submission"]["availability"] == "available"
    assert conn.execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='lease_release' "
        "AND instr(new_value,'bach-task-result:')>0", (task_id,)
    ).fetchone()[0] == 1
    task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert task.get("require_user_review") in (None, 0)
    assert task.get("github_pr_review_required") in (None, 0)
    assert task.get("completion_contract_json") is None

    if drop_result_table:
        conn.execute("DROP TABLE worker_task_results")
    else:
        conn.execute("DELETE FROM worker_task_results WHERE id=?", (record["result_id"],))
    conn.commit()

    with pytest.raises(ResultConflict):
        apply_task_field_changes(conn, task_id, task, {"status": "done"},
            changed_by="fixture-operator", now="2026-10-15T12:00:00.000000")
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"


def test_controller_does_not_authorize_another_claim_for_an_unavailable_v1_receipt(
    completion_world,
):
    from hub._services.chat import telegram_chat

    world = completion_world(mode="high_security")
    conn, binding, task_id = world["conn"], world["binding"], world["task_id"]
    record = read_result(conn, task_id)["result"]
    assert record["completion_policy_version"] == 1
    conn.execute("UPDATE worker_task_results SET submission_receipt_sha256=NULL WHERE id=?",
                 (record["result_id"],))
    conn.commit()

    control = telegram_chat._WorkerControl(worker_id=AUTHOR_SLOT, generation=GENERATION)
    control.task_binding = binding
    control.task_result_bindings = {task_id: binding}
    assert binding.closed is True
    assert binding.submitted_result is not None
    assert telegram_chat._poll_worker_completion(control) is False
    assert read_result(conn, task_id)["result"]["submission"]["availability"] == "unavailable"
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    assert conn.execute("SELECT claim_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0] is None
