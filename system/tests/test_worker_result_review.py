# SPDX-License-Identifier: MIT
"""Real TaskDB/lease and Git-scope behavior for controller-bound model review."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import uuid

import pytest

from hub._services import worker_policy_settings as settings
from hub._services import worker_result_review as review
from hub._services import worker_scope_evidence
from hub._services.chat import worker_write_guard
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import LeaseDeniedError
from hub._services.task_lease_client import LeaseProtocolError
from hub._services.task_result_service import (CorrectionContextDenied,
    active_correction_request, read_result)
from hub._services.worker_review_identity import KEY as IDENTITY_KEY
from system.tests.test_task_lease_client import mem_db
from system.tests.test_task_lease_client_review import T0
from system.tests.test_worker_execution_evidence import worker_context
from system.tests.test_worker_scope_snapshot import _git, _install_lock_scanner, _new_scope_repo


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


def _review_settings(conn, monkeypatch):
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


@pytest.fixture
def review_world(worker_context, tmp_path, monkeypatch, request):
    """Real SQLite submissions and registered clean Git worktree; no model calls."""
    context = worker_context
    conn, author = context["conn"], context["binding"]
    _review_settings(conn, monkeypatch)
    tree = _new_scope_repo(tmp_path, task_id=context["task_id"],
                           pinned=getattr(request, "param", False))
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
    assert "Abschlussstatus wird nach Policy ermittelt" in author.execute_task_manage({
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


def _acquire_review(world, task_id, grant, stop, current, *, generation=REVIEW_GENERATION,
                    slot=REVIEW_SLOT, model=REVIEW_MODEL):
    return WorkerLeaseBinding.acquire(
        world["client"], task_id, worker_id="review-worker@HOST", host="HOST",
        generation=generation, is_current=lambda: current["value"],
        stop_event=stop, clock=lambda: T0,
        slot={"id": slot, "model": model, "backend": "ollama"},
        automatic=True, _review_grant=grant)


def _ban_author_model(world):
    settings._persist(world["conn"], settings.INDEPENDENCE_KEY,
                      {"exclude_author_model": True}, actor="test-operator")
    world["conn"].commit()


def _review_reader(world, monkeypatch):
    from hub import worker_git

    # Use the actual SDK grant/revision check with this isolated registered
    # repository. The reviewer child deliberately has no worktree of its own.
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: world["tree"]["repo"])
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: world["tree"]["worktrees"])
    child_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, child_id)
    assert grant is not None
    child = _acquire_review(world, child_id, grant, stop, current)
    assert not (world["tree"]["worktrees"] / f"task-{child_id}").exists()
    return child, stop


@pytest.mark.parametrize("review_world", [True], indirect=True)
def test_review_reads_registered_parent_without_starting_child_worktree(review_world, monkeypatch):
    from hub._services.chat import bach_tools, telegram_chat

    world = review_world
    child, _stop = _review_reader(world, monkeypatch)
    source = worker_write_guard.review_source_root(child)
    assert source == world["tree"]["target"]
    context = json.loads(telegram_chat._bound_worker_prompt(child, "ignored").splitlines()[-1])
    assert context["review_source"]["worktree"] == str(source)
    assert context["review_source"]["read_only"] is True
    assert context["review_source"]["result_revision"] == world["target"]["result_revision"]
    assert not (world["tree"]["worktrees"] / f"task-{child.task_id}").exists()
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        pytest.skip("Secure descriptor-relative reading is exercised on POSIX")
    grants = {"read_file", "search_text"}
    answer = bach_tools.exec_tool("read_file", {"path": "README.md"}, "safe",
        worker_task_binding=child, require_task_binding=True, allowed_tools=grants)
    assert "public base" in answer and "BLOCKIERT" not in answer
    found = bach_tools.exec_tool("search_text", {"path": ".", "pattern": "public base"}, "safe",
        worker_task_binding=child, require_task_binding=True, allowed_tools=grants)
    assert "public base" in found and "BLOCKIERT" not in found
    denied = bach_tools.exec_tool("start_task_worktree", {"task_id": child.task_id}, "full",
        worker_task_binding=child, require_task_binding=True,
        allowed_tools={"read_file", "search_text", "start_task_worktree"})
    assert "BLOCKIERT" in denied
    assert not (world["tree"]["worktrees"] / f"task-{child.task_id}").exists()


@pytest.mark.parametrize("review_world", [True], indirect=True)
@pytest.mark.parametrize("tool", ["read_file", "search_text"])
def test_review_cannot_fall_back_to_permissive_host_reader(review_world, monkeypatch, tmp_path, tool):
    from hub._services.chat import bach_tools

    child, _stop = _review_reader(review_world, monkeypatch)
    outside = tmp_path / "unrelated.txt"
    outside.write_text("Unrelated host content must stay private", encoding="utf-8")
    # Even when the ordinary home reader would allow a path, the review grant
    # must choose its registered parent scope and deny the escaped request.
    monkeypatch.setattr(bach_tools, "_fs_root_allowed", lambda _path: True)
    answer = bach_tools.exec_tool(tool, {"path": str(outside), "pattern": "Unrelated"}, "safe",
        worker_task_binding=child, require_task_binding=True,
        allowed_tools={"read_file", "search_text"})
    assert "BLOCKIERT" in answer
    assert "Unrelated host content" not in answer


@pytest.mark.parametrize("review_world", [True], indirect=True)
@pytest.mark.parametrize("damage", ["source_changed", "target_terminal", "child_stopped", "foreign_target"])
def test_review_read_rechecks_current_target_and_child(review_world, monkeypatch, damage):
    from hub._services.chat import bach_tools

    world = review_world
    child, stop = _review_reader(world, monkeypatch)
    assert worker_write_guard.review_source_root(child) == world["tree"]["target"]
    if damage == "source_changed":
        (world["tree"]["target"] / "README.md").write_text("changed after submission\n", encoding="utf-8")
    elif damage == "target_terminal":
        world["conn"].execute("UPDATE tasks SET status='done' WHERE id=?", (world["task_id"],))
        world["conn"].commit()
    elif damage == "child_stopped":
        stop.set()
    else:
        child._review_grant.target_task_id += 10000
    for tool in ["read_file", "search_text"]:
        answer = bach_tools.exec_tool(tool, {"path": "README.md", "pattern": "public"}, "safe",
            worker_task_binding=child, require_task_binding=True,
            allowed_tools={"read_file", "search_text"})
        assert "BLOCKIERT" in answer
        assert "public base" not in answer


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
    assert "Abschlussstatus wird nach Policy ermittelt" in child.execute_task_manage({
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


def test_same_model_and_slot_review_own_result_in_fresh_run(review_world):
    # User decision 2026-10-24: the run, not the model or agent slot, is the
    # independence unit; the author's model may review in its own new run.
    world = review_world
    prepared = _prepare(world)
    grant, stop, current = _grant(world, prepared["review_task_id"], slot=AUTHOR_SLOT,
                                  route=AUTHOR_ROUTE, requested=AUTHOR_MODEL)
    assert grant is not None
    child = _acquire_review(world, prepared["review_task_id"], grant, stop, current,
                            slot=AUTHOR_SLOT, model=AUTHOR_MODEL)
    verdict = json.dumps({"status": "approved", "summary": "Frische Prüfung bestanden.",
                          "task_contract_met": True}, ensure_ascii=False)
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=AUTHOR_MODEL, slot_id=AUTHOR_SLOT,
        request_sha256=_request_hash("fresh review prompt"), route_sha256=AUTHOR_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(
        handle, result=_response(AUTHOR_OBSERVED, verdict=(child.task_id, verdict)),
        route_sha256=AUTHOR_ROUTE) is True
    assert "Abschlussstatus wird nach Policy ermittelt" in child.execute_task_manage({
        "action": "submit_result", "task_id": child.task_id, "result": verdict})
    evidence = review.record_review(world["conn"], child, **_paths(world))
    assert evidence["availability"] == "recorded"
    assert evidence["reviewer_id"] == AUTHOR
    assert evidence["independent"] is True


def test_author_run_never_reviews_and_model_ban_is_a_rule(review_world):
    # The author's own run is always excluded. Excluding the author's model is
    # an explicit operator rule; an independent model stays eligible.
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    author_generation = world["binding"].generation
    assert _grant(world, task_id, route=AUTHOR_ROUTE, requested=AUTHOR_MODEL,
                  generation=author_generation)[0] is None
    _ban_author_model(world)
    assert _grant(world, task_id, route=AUTHOR_ROUTE, requested=AUTHOR_MODEL)[0] is None
    assert _grant(world, task_id, route=AUTHOR_ALIAS_ROUTE,
                  requested=AUTHOR_ALIAS_MODEL)[0] is None
    parent = read_result(world["conn"], world["task_id"])
    assert parent["status"] == "review"
    assert parent["result"]["accepted"] is False
    assert _grant(world, task_id)[0] is not None


def test_unreadable_independence_setting_fails_closed_to_the_model_ban(review_world):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    world["conn"].execute("INSERT INTO system_config(key,value) VALUES (?,?)",
                          (settings.INDEPENDENCE_KEY, "{not json"))
    world["conn"].commit()
    assert _grant(world, task_id, route=AUTHOR_ROUTE, requested=AUTHOR_MODEL)[0] is None
    assert _grant(world, task_id)[0] is not None


@pytest.mark.parametrize("failure", ["no_return", "backend_error", "extra_call", "invalid_json",
                                     "unconfirmed_route", "unknown_provider_model",
                                     "terminal_history_tamper"])
def test_review_submit_requires_one_confirmed_matching_structured_answer(review_world, failure):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    child = _acquire_review(world, task_id, grant, stop, current)
    assert f"id: {task_id}" in child.execute_task_manage({"action": "detail", "task_id": task_id})
    verdict = json.dumps({"status": "findings", "summary": "Quelle fehlt.",
                          "task_contract_met": False}, ensure_ascii=False)
    proposed = "Konkrete erledigte Arbeit am Zieltask." if failure == "invalid_json" else verdict
    answer = _response(REVIEW_OBSERVED, verdict=(task_id, proposed))
    if failure == "extra_call":
        answer["tool_calls"].append(copy.deepcopy(answer["tool_calls"][0]))
    if failure == "unknown_provider_model":
        answer["provider_reported_model"] = None
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("review prompt"), route_sha256=REVIEW_ROUTE)
    assert handle is not None
    if failure != "no_return":
        assert child.finish_model_execution(handle,
            result=answer if failure != "backend_error" else None,
            failed=failure == "backend_error",
            route_sha256=AUTHOR_ROUTE if failure == "unconfirmed_route" else REVIEW_ROUTE) is (failure != "backend_error")
    if failure == "terminal_history_tamper":
        event_id = world["conn"].execute(
            "SELECT terminal_event_id FROM worker_model_executions WHERE id=?",
            (handle._execution_id,)).fetchone()[0]
        world["conn"].execute("UPDATE task_history SET new_value='{}' WHERE id=?", (event_id,))
        world["conn"].commit()
    before = world["conn"].total_changes
    with pytest.raises((LeaseProtocolError, LeaseDeniedError)) as denied:
        child.execute_task_manage({"action": "submit_result", "task_id": task_id,
                                   "result": proposed})
    if failure in {"unconfirmed_route", "unknown_provider_model", "terminal_history_tamper"}:
        assert isinstance(denied.value, LeaseDeniedError)
        assert denied.value.reason == "completion_guard"
    assert world["conn"].total_changes == before
    assert read_result(world["conn"], task_id)["status"] == "in_progress"
    assert read_result(world["conn"], task_id)["result"] is None
    assert read_result(world["conn"], world["task_id"])["result"]["model_review"]["availability"] == "unavailable"


def test_review_release_writer_rechecks_parent_after_model_return(review_world):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    child = _acquire_review(world, task_id, grant, stop, current)
    verdict = json.dumps({"status": "findings", "summary": "Quellbeleg fehlt.",
                          "task_contract_met": False}, ensure_ascii=False)
    answer = _response(REVIEW_OBSERVED, verdict=(task_id, verdict))
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("review before parent change"), route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(handle, result=answer, route_sha256=REVIEW_ROUTE) is True
    # A parent content edit after the real model return makes the old intent stale.
    world["conn"].execute("UPDATE tasks SET title='Changed while reviewer answered' WHERE id=?",
                          (world["task_id"],))
    world["conn"].commit()
    with pytest.raises(LeaseProtocolError):
        child.execute_task_manage({"action": "submit_result", "task_id": task_id,
                                   "result": verdict})
    # Independently exercise the canonical release writer, not only the
    # lock-free preflight in the bound tool path.
    with pytest.raises(LeaseDeniedError):
        child._operation(child._client.submit_result, generation=child.generation,
                         result=verdict, _review_binding=child)
    assert read_result(world["conn"], task_id)["status"] == "in_progress"
    assert read_result(world["conn"], task_id)["result"] is None


@pytest.mark.parametrize("drift", ["git", "git_dirty", "parent_status", "parent_content",
                                     "full_revision", "full_revision_and_git", "git_unavailable"])
def test_released_review_child_is_cancelled_only_for_proven_target_drift(
        review_world, monkeypatch, drift):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    child = _acquire_review(world, task_id, grant, stop, current)
    verdict = json.dumps({"status": "approved", "summary": "Geprüfte Arbeit.",
                          "task_contract_met": True}, ensure_ascii=False)
    answer = _response(REVIEW_OBSERVED, verdict=(task_id, verdict))
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("target may drift after release"), route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(handle, result=answer, route_sha256=REVIEW_ROUTE) is True
    actual_record = world["client"]._record_result_review

    def after_canonical_release(binding):
        assert read_result(world["conn"], task_id)["status"] == "review"
        if drift in {"git", "git_dirty"}:
            (world["tree"]["target"] / "changed-after-submit.txt").write_text(
                "new work\n", encoding="utf-8")
            if drift == "git":
                _git(["add", "changed-after-submit.txt"], world["tree"]["target"])
                _git(["commit", "-m", "change target after review submission"],
                     world["tree"]["target"])
        elif drift == "parent_status":
            world["conn"].execute("UPDATE tasks SET status='pending' WHERE id=?",
                                  (world["task_id"],))
            world["conn"].commit()
        elif drift == "parent_content":
            world["conn"].execute("UPDATE tasks SET title='changed after submit' WHERE id=?",
                                  (world["task_id"],))
            world["conn"].commit()
        elif drift in {"full_revision", "full_revision_and_git"}:
            # Model a different internally valid scope event with the same
            # parent task status and result ID. The production capture API is
            # immutable; this exercises a future/versioned receipt race.
            from datetime import datetime, timezone
            from hub._services.task_lease import _fmt, _history
            old = world["conn"].execute("SELECT receipt FROM worker_scope_evidence "
                "WHERE result_id=?", (world["target"]["result_id"],)).fetchone()
            receipt = json.loads(old[0])
            now = datetime.now(timezone.utc)
            receipt["captured_at"] = _fmt(now)
            digest = worker_scope_evidence._digest(receipt)
            event = _history(world["conn"], world["task_id"],
                "worker_result_scope_capture", "native-scope-controller", now,
                worker_scope_evidence._event_detail(receipt, digest))
            world["conn"].execute("UPDATE worker_scope_evidence SET receipt=?,"
                "receipt_sha256=?,event_id=?,captured_at=? WHERE result_id=?",
                (worker_scope_evidence._json(receipt), digest, event,
                 receipt["captured_at"], world["target"]["result_id"]))
            world["conn"].commit()
            changed = worker_scope_evidence.project_scope_evidence(
                read_result(world["conn"], world["task_id"]), **_paths(world))["result"]
            assert changed["scope"]["availability"] == "available"
            assert changed["result_id"] == world["target"]["result_id"]
            assert changed["result_revision"] != world["target"]["result_revision"]
            if drift == "full_revision_and_git":
                (world["tree"]["target"] / "second-drift.txt").write_text(
                    "changed too\n", encoding="utf-8")
                _git(["add", "second-drift.txt"], world["tree"]["target"])
                _git(["commit", "-m", "change target after scope revision"],
                     world["tree"]["target"])
        else:
            monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope",
                lambda *args, **kwargs: {"availability": "unavailable", "reason": "scanner_unknown"})
        return actual_record(binding)

    monkeypatch.setattr(world["client"], "_record_result_review", after_canonical_release)
    tool_result = child.execute_task_manage({
        "action": "submit_result", "task_id": task_id, "result": verdict})
    unavailable = drift in {"git_dirty", "git_unavailable"}
    assert ("Abschlussstatus wird nach Policy ermittelt" if unavailable else "wurde storniert") in tool_result
    expected = "review" if unavailable else "cancelled"
    assert read_result(world["conn"], task_id)["status"] == expected
    assert read_result(world["conn"], task_id)["result"]["accepted"] is False
    event_count = world["conn"].execute(
        "SELECT COUNT(*) FROM task_history WHERE task_id=? "
        "AND action='worker_result_review_obsolete'", (task_id,)).fetchone()[0]
    assert event_count == (0 if unavailable else 1)
    if not unavailable:
        assert not any(row["id"] == task_id for row in review.list_review_candidates(world["conn"]))
        assert world["conn"].execute("SELECT COUNT(*) FROM worker_result_model_reviews "
            "WHERE review_task_id=?", (task_id,)).fetchone()[0] == 0
        assert review.cancel_obsolete_review_child(world["conn"], child, **_paths(world)) is None
        assert world["conn"].execute("SELECT COUNT(*) FROM task_history WHERE task_id=? "
            "AND action='worker_result_review_obsolete'", (task_id,)).fetchone()[0] == 1
    assert read_result(world["conn"], world["task_id"])["result"]["accepted"] is False


def test_obsolete_cancel_rejects_child_status_revision_race(review_world, monkeypatch):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    child = _acquire_review(world, task_id, grant, stop, current)
    verdict = json.dumps({"status": "findings", "summary": "Erneut prüfen.",
                          "task_contract_met": False}, ensure_ascii=False)
    answer = _response(REVIEW_OBSERVED, verdict=(task_id, verdict))
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("review status race"), route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(handle, result=answer, route_sha256=REVIEW_ROUTE) is True
    monkeypatch.setattr(world["client"], "_record_result_review", lambda binding: None)
    assert "Abschlussstatus wird nach Policy ermittelt" in child.execute_task_manage({
        "action": "submit_result", "task_id": task_id, "result": verdict})
    before = read_result(world["conn"], task_id)["status_revision"]
    (world["tree"]["target"] / "race.txt").write_text("changed\n", encoding="utf-8")
    _git(["add", "race.txt"], world["tree"]["target"])
    _git(["commit", "-m", "change target before cancel race"],
         world["tree"]["target"])
    actual_reason = review._obsolete_target_reason
    first = {"value": True}

    def between_precheck_and_writer(conn, found, grant, **kwargs):
        reason = actual_reason(conn, found, grant, **kwargs)
        if first["value"] and reason == "current_git_changed":
            first["value"] = False
            from hub.task_audit import apply_task_field_changes
            row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
            apply_task_field_changes(conn, task_id, row, {"status": "pending"},
                                     changed_by="test-operator", allow_reopen=True)
            row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
            apply_task_field_changes(conn, task_id, row, {"status": "review"},
                                     changed_by="test-operator", allow_reopen=True)
            conn.commit()
        return reason

    monkeypatch.setattr(review, "_obsolete_target_reason", between_precheck_and_writer)
    assert review.cancel_obsolete_review_child(world["conn"], child, **_paths(world)) is None
    after = read_result(world["conn"], task_id)
    assert after["status"] == "review" and after["status_revision"] > before
    assert world["conn"].execute("SELECT COUNT(*) FROM task_history WHERE task_id=? "
        "AND action='worker_result_review_obsolete'", (task_id,)).fetchone()[0] == 0


def _old_invalid_review_result(world, monkeypatch):
    """Exercise the old canonical release without the new pre-submit guard."""
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    child = _acquire_review(world, task_id, grant, stop, current)
    bad = world["target"]["result"]
    answer = _response(REVIEW_OBSERVED, verdict=(task_id, bad))
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("old review prompt"), route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(handle, result=answer, route_sha256=REVIEW_ROUTE) is True
    child._submission_expected = {"task_id": task_id, "fence": child._ack.fence,
        "generation": child.generation, "task_version": child._snapshot["task_version"],
        "result_sha256": hashlib.sha256(bad.encode("utf-8")).hexdigest(), "result": bad}
    # Materialize a real old V1 result through the pre-guard release path.
    # Only this historical fixture suppresses today's reserved-child marker;
    # all assertions and all subsequent operations use the production guard.
    with monkeypatch.context() as historical:
        historical.setattr(review, "review_task_marker", lambda *_: False)
        ack = child._operation(child._client.submit_result,
                               generation=child.generation, result=bad)
    child._completion_result = copy.deepcopy(ack.record)
    child._review_ack = ack.release
    child._closed = True
    child._active = False
    assert child._link_confirmed_model_execution() is True
    observed = read_result(world["conn"], task_id)
    assert observed["status"] == "review"
    assert observed["result"]["execution"]["availability"] == "available"
    assert review.record_review(world["conn"], child, **_paths(world)) is None
    return task_id, observed


def test_old_invalid_review_child_requeues_with_verified_correction_and_replay_denied(review_world, monkeypatch):
    world = review_world
    task_id, observed = _old_invalid_review_result(world, monkeypatch)
    result_id = observed["result"]["result_id"]
    status_revision = observed["status_revision"]
    recovered = world["client"]._recover_invalid_review_child(task_id,
        result_id=result_id, status_revision=status_revision)
    assert recovered["availability"] == "recorded"
    assert recovered["status"] == "pending"
    assert review.recover_invalid_review_child(world["conn"], task_id,
        result_id=result_id, status_revision=status_revision, **_paths(world)) is None
    correction = active_correction_request(world["conn"], task_id)
    assert correction["source_result_id"] == result_id
    assert "strukturierte Review-Abgabe" in correction["correction_note"]
    assert read_result(world["conn"], task_id)["status"] == "pending"
    assert read_result(world["conn"], world["task_id"])["result"]["model_review"]["availability"] == "unavailable"
    assert review.list_review_candidates(world["conn"])[0]["id"] == task_id
    fresh_generation = "review-generation-3"
    fresh_grant, fresh_stop, fresh_current = _grant(world, task_id,
        generation=fresh_generation)
    assert fresh_grant is not None
    fresh = _acquire_review(world, task_id, fresh_grant, fresh_stop, fresh_current,
        generation=fresh_generation)
    assert fresh.generation == fresh_generation
    assert fresh._ack.fence > observed["result"]["fence"]
    event_id = world["conn"].execute("SELECT completion_decision_event_id FROM worker_task_results "
        "WHERE id=?", (result_id,)).fetchone()[0]
    world["conn"].execute("UPDATE task_history SET changed_by='foreign' WHERE id=?", (event_id,))
    world["conn"].commit()
    with pytest.raises(CorrectionContextDenied):
        active_correction_request(world["conn"], task_id)


@pytest.mark.parametrize("mutation", ["foreign_identity", "live_child", "changed_target", "stale_status"])
def test_invalid_review_recovery_rejects_unproven_context(review_world, monkeypatch, mutation):
    world = review_world
    task_id, observed = _old_invalid_review_result(world, monkeypatch)
    if mutation == "foreign_identity":
        from hub._services.worker_review_identity import identity_snapshot
        bindings = identity_snapshot(world["conn"])["bindings"]
        settings._persist(world["conn"], IDENTITY_KEY, bindings[:2], actor="test-operator")
        world["conn"].commit()
    elif mutation == "live_child":
        world["conn"].execute("UPDATE tasks SET claim_id='foreign' WHERE id=?", (task_id,))
        world["conn"].commit()
    elif mutation == "changed_target":
        (world["tree"]["target"] / "changed.txt").write_text("changed\n", encoding="utf-8")
    else:
        observed["status_revision"] += 1
    before = world["conn"].total_changes
    assert review.recover_invalid_review_child(world["conn"], task_id,
        result_id=observed["result"]["result_id"],
        status_revision=observed["status_revision"], **_paths(world)) is None
    assert world["conn"].total_changes == before


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


def test_review_task_requires_a_private_fresh_run_grant(review_world):
    world = review_world
    task_id = _prepare(world)["review_task_id"]
    snapshot = world["client"].task_snapshot(task_id)
    with pytest.raises(LeaseDeniedError):
        world["client"].acquire(task_id, worker_id="review-worker@HOST", host="HOST",
            task_version=snapshot["task_version"], result_generation=REVIEW_GENERATION,
            now=T0)
    # Only the author's run is a fixed exclusion; slot and model are no criterion.
    assert _grant(world, task_id, generation=world["binding"].generation)[0] is None
    assert _grant(world, task_id, slot=AUTHOR_SLOT)[0] is not None
    assert _grant(world, task_id, route=AUTHOR_ALIAS_ROUTE,
                  requested=AUTHOR_ALIAS_MODEL)[0] is not None
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


TEXT_RESULT = "Bericht: Hilfedateien a bis c geprüft; drei Stämme ohne Übersetzung, zwölf veraltet."
UNSCOPED_INTENT = "bach.worker-result-review-intent.submission-bound.v1"
ABSENT_TREE = {"availability": "absent"}


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _bound_revision(record, tree_state):
    # Independent oracle: submission plus the exact stored tree package.
    return _canonical_sha({"schema": "bach.worker-submission-bound-revision.v1",
                           "submission_revision": record["submission_revision"],
                           "tree_sha256": _canonical_sha(tree_state)})


def _unscoped_world(context, tmp_path, monkeypatch, *, result=TEXT_RESULT, own_tree=False,
                    write_tool=None, before_submit=None):
    """Real native submission whose result scope was never captured."""
    conn, author = context["conn"], context["binding"]
    _review_settings(conn, monkeypatch)
    # Without own_tree the repository registers only another task's tree.
    tree = _new_scope_repo(tmp_path, task_id=context["task_id"] + (0 if own_tree else 1000))
    _install_lock_scanner(tmp_path, monkeypatch)
    handle = author.begin_model_execution(
        backend_id="ollama", requested_model=AUTHOR_MODEL, slot_id=AUTHOR_SLOT,
        request_sha256=_request_hash("author unscoped prompt"), route_sha256=AUTHOR_ROUTE)
    assert handle is not None
    assert author.finish_model_execution(
        handle, result=_response(AUTHOR_OBSERVED), route_sha256=AUTHOR_ROUTE) is True
    if write_tool is not None:
        from hub._services import task_lease

        # One complete real trace chain at the binding's lease time.
        with monkeypatch.context() as at_lease_time:
            at_lease_time.setattr(task_lease, "_utcnow", lambda: T0)
            trace = author.trace_tool_started(source="normal-loop", request_id=uuid.uuid4().hex,
                tool_name=write_tool, arguments_sha256=_request_hash("{}"))
            receipt = uuid.uuid4().hex
            author.trace_tool_phase(trace, "returned", receipt_id=receipt,
                                    result_sha256=_request_hash("written"))
            author.trace_tool_phase(trace, "acknowledged", receipt_id=receipt)
    if before_submit is not None:
        before_submit(tree)
    assert "Abschlussstatus wird nach Policy ermittelt" in author.execute_task_manage({
        "action": "submit_result", "task_id": context["task_id"], "result": result})
    target = read_result(conn, context["task_id"])["result"]
    assert target["scope"]["reason"] == "scope_not_recorded"
    assert target["execution"]["model_principal_id"] == AUTHOR
    return {**context, "tree": tree, "target": {**target, "result_revision": _bound_revision(
        target, ABSENT_TREE)}}


@pytest.fixture
def text_world(worker_context, tmp_path, monkeypatch):
    return _unscoped_world(worker_context, tmp_path, monkeypatch)


def _uncommitted_work(tree):
    (tree["target"] / "README.md").write_text("public base\nchanged by the worker\n", encoding="utf-8")
    (tree["target"] / "report.txt").write_text("Bericht ohne Commit\n", encoding="utf-8")


def _intent_receipt(world):
    return json.loads(world["conn"].execute(
        "SELECT intent FROM worker_result_review_intents").fetchone()[0])


def _approved_review(child):
    verdict = json.dumps({"status": "approved", "summary": "Ergebnis erfüllt die Anforderung.",
                          "task_contract_met": True}, ensure_ascii=False)
    handle = child.begin_model_execution(
        backend_id="ollama", requested_model=REVIEW_MODEL, slot_id=REVIEW_SLOT,
        request_sha256=_request_hash("unscoped review prompt"), route_sha256=REVIEW_ROUTE)
    assert handle is not None
    assert child.finish_model_execution(
        handle, result=_response(REVIEW_OBSERVED, verdict=(child.task_id, verdict)),
        route_sha256=REVIEW_ROUTE) is True
    return verdict


def test_unscoped_result_creates_exactly_one_review_task_bound_to_its_submission(text_world):
    world = text_world
    first = _prepare(world)
    assert first["schema"] == UNSCOPED_INTENT
    assert review.prepare_review_task(world["conn"], world["binding"], **_paths(world)) == first
    assert world["conn"].execute(
        "SELECT COUNT(*) FROM tasks WHERE category='worker-review'").fetchone()[0] == 1
    intent = _intent_receipt(world)
    assert intent["submission_revision"] == world["target"]["submission_revision"]
    assert intent["tree_state"] == ABSENT_TREE
    assert "scope_receipt_sha256" not in intent
    assert read_result(world["conn"], world["task_id"])["status"] == "review"


def test_unscoped_review_runs_without_git_and_records_one_verdict(text_world, monkeypatch):
    from hub._services.chat import telegram_chat

    world = text_world
    task_id = _prepare(world)["review_task_id"]
    calls = []

    def no_subprocess(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("no Git or lock scan after the review package exists")

    # Grant, dispatch, prompt, release and record are DB-only for this route.
    monkeypatch.setattr(worker_write_guard, "_RUN", no_subprocess)
    grant, stop, current = _grant(world, task_id)
    assert grant is not None and grant.target_kind == "submission"
    child = _acquire_review(world, task_id, grant, stop, current)
    assert review.guard_review_dispatch(
        world["conn"], child, route={"backend_id": "ollama", "route_sha256": REVIEW_ROUTE},
        requested_model=REVIEW_MODEL) is True
    prompt = telegram_chat._bound_worker_prompt(child, "ignored")
    context = json.loads(prompt.splitlines()[-1])
    task = world["client"].task_snapshot(world["task_id"])
    assert context["target_task"]["title"] == task["title"]
    assert context["target_task"]["description"] == task["description"]
    assert context["target_result"] == {"result_id": world["target"]["result_id"],
                                        "result": TEXT_RESULT}
    assert context["target_tree"] == ABSENT_TREE and "review_source" not in context
    verdict = _approved_review(child)
    assert "Abschlussstatus wird nach Policy ermittelt" in child.execute_task_manage({
        "action": "submit_result", "task_id": task_id, "result": verdict})
    evidence = review.record_review(world["conn"], child)
    assert evidence["availability"] == "recorded"
    assert evidence["reviewer_id"] == REVIEWER and evidence["independent"] is True
    assert evidence["result_revision"] == world["target"]["result_revision"]
    assert world["conn"].execute("SELECT COUNT(*) FROM worker_result_model_reviews").fetchone()[0] == 1
    parent = read_result(world["conn"], world["task_id"])
    assert parent["status"] == "review" and parent["result"]["accepted"] is False
    assert read_result(world["conn"], task_id)["status"] == "done"
    projected = worker_scope_evidence.project_scope_evidence(parent)
    assert projected["result"]["model_review"]["availability"] == "available"
    assert calls == []


@pytest.mark.parametrize("limit", [None, 40])
def test_written_but_uncommitted_work_is_reviewed_with_its_diff(
        worker_context, tmp_path, monkeypatch, limit):
    from hub._services.chat import telegram_chat

    # Cases 330/331/332: write tools, uncommitted changes, then a result text.
    world = _unscoped_world(worker_context, tmp_path, monkeypatch, own_tree=True,
                            write_tool="write_file", before_submit=_uncommitted_work)
    if limit is not None:
        monkeypatch.setattr(review, "_TREE_DIFF_LIMIT", limit)
    prepared = review.prepare_review_task(world["conn"], world["binding"], **_paths(world))
    assert prepared is not None and prepared["schema"] == UNSCOPED_INTENT
    tree_state = _intent_receipt(world)["tree_state"]
    assert tree_state["availability"] == "diff"
    assert tree_state["truncated"] is (limit is not None)
    if limit is None:
        assert "+changed by the worker" in tree_state["diff"]
        assert "+Bericht ohne Commit" in tree_state["diff"]
    assert prepared["target_revision"] == _bound_revision(world["target"], tree_state)
    grant, stop, current = _grant(world, prepared["review_task_id"])
    child = _acquire_review(world, prepared["review_task_id"], grant, stop, current)
    # The stored package is the review subject; later tree edits do not change it.
    (world["tree"]["target"] / "later.txt").write_text("after the package\n", encoding="utf-8")
    assert review.guard_review_dispatch(
        world["conn"], child, route={"backend_id": "ollama", "route_sha256": REVIEW_ROUTE},
        requested_model=REVIEW_MODEL) is True
    context = json.loads(telegram_chat._bound_worker_prompt(child, "ignored").splitlines()[-1])
    assert context["target_tree"]["diff"] == tree_state["diff"]
    assert context["target_tree"]["truncated"] is tree_state["truncated"]
    assert "later.txt" not in context["target_tree"]["diff"]


@pytest.mark.parametrize("change", ["result_text", "task_content"])
def test_changed_unscoped_result_invalidates_the_review_grant(text_world, change):
    from hub._services.chat import telegram_chat

    world = text_world
    task_id = _prepare(world)["review_task_id"]
    grant, stop, current = _grant(world, task_id)
    child = _acquire_review(world, task_id, grant, stop, current)
    route = {"backend_id": "ollama", "route_sha256": REVIEW_ROUTE}
    assert review.guard_review_dispatch(world["conn"], child, route=route,
                                        requested_model=REVIEW_MODEL) is True
    if change == "result_text":
        world["conn"].execute("UPDATE worker_task_results SET result=? WHERE id=?",
                              ("Anderer Bericht.", world["target"]["result_id"]))
    else:
        world["conn"].execute("UPDATE tasks SET description='Andere Ausgabeanforderung' WHERE id=?",
                              (world["task_id"],))
    world["conn"].commit()
    assert review.guard_review_dispatch(world["conn"], child, route=route,
                                        requested_model=REVIEW_MODEL) is False
    with pytest.raises((RuntimeError, LeaseProtocolError)):
        telegram_chat._bound_worker_prompt(child, "ignored")
    verdict = _approved_review(child)
    with pytest.raises(LeaseProtocolError):
        child.execute_task_manage({"action": "submit_result", "task_id": task_id, "result": verdict})
    assert world["conn"].execute("SELECT COUNT(*) FROM worker_result_model_reviews").fetchone()[0] == 0


def test_result_with_github_pr_link_stays_on_the_github_route(worker_context, tmp_path, monkeypatch):
    world = _unscoped_world(worker_context, tmp_path, monkeypatch,
                            result=TEXT_RESULT + " Siehe https://github.com/ellmos-ai/bach/pull/519")
    assert review.prepare_review_task(world["conn"], world["binding"], **_paths(world)) is None
    assert world["conn"].execute(
        "SELECT COUNT(*) FROM tasks WHERE category='worker-review'").fetchone()[0] == 0


def test_backlog_backfill_prepares_waiting_results_once(text_world):
    world = text_world
    first = review.prepare_pending_review_tasks(world["conn"], **_paths(world))
    assert [item["target_result_id"] for item in first] == [world["target"]["result_id"]]
    assert first[0]["schema"] == UNSCOPED_INTENT
    again = review.prepare_pending_review_tasks(world["conn"], **_paths(world))
    assert [item["review_task_id"] for item in again] == [first[0]["review_task_id"]]
    assert world["conn"].execute(
        "SELECT COUNT(*) FROM tasks WHERE category='worker-review'").fetchone()[0] == 1


def test_code_scope_result_keeps_its_git_bound_route(review_world):
    world = review_world
    (world["tree"]["target"] / "unreviewed.txt").write_text("changed\n", encoding="utf-8")
    # A captured scope never falls back to the submission-bound route.
    assert review.prepare_review_task(world["conn"], world["binding"], **_paths(world)) is None
    (world["tree"]["target"] / "unreviewed.txt").unlink()
    prepared = _prepare(world)
    assert prepared["schema"] == "bach.worker-result-review-intent.v1"
    grant = _grant(world, prepared["review_task_id"])[0]
    assert grant is not None and grant.target_kind == "scope"
