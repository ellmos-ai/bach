"""PB-1 (#3985): broken host != broken task; follow-ups and returns are bounded.

Measured 06.11.2026 on the Mac Studio: a dehydrated OneDrive pointer made the
lock scanner report an unknown twin status. Two workers with write tools then
returned every task ~557 times an hour (fence up to 4835), Buddha without
explicit grants saw write tools it could never use and created 199 "Rest:"
follow-ups, and a Retry-After or a cloud ConnectError could stop or freeze a
worker. Diagnosis: Desktop/OCEAN/BERICHTE/2026-11-06_Diagnose/PB1-WORKER-ABBRUCH-URSACHE.md
"""
import importlib
import threading

import pytest

from system.tests.test_task_lease_client_review import T0
from system.tests.test_worker_lease_binding import mem_db, binding  # noqa: F401 -- fixtures
from system.tests.test_worker_lease_supervision import binding as leased_binding  # noqa: F401
from system.tests.test_worker_start_admission import admission  # noqa: F401
from system.tests.test_worker_tool_bridge import bridge  # noqa: F401
from hub._services.chat.slots_config import add_worker, update_slot


def _controller():
    return importlib.import_module("hub._services.chat.telegram_chat")


# --- host precondition: back off, never cycle through the queue -----------------------

def _run_loop_once(control, worker, binding, monkeypatch, start_error):
    from hub import worker_git
    from hub._services.chat import worker_write_guard
    observed = {"acquired": 0, "finish": [], "waits": [], "activity": []}

    def acquire(*_args):
        observed["acquired"] += 1
        return binding if observed["acquired"] == 1 else None
    monkeypatch.setattr(control, "_acquire_worker_task", acquire)
    monkeypatch.setattr(control, "begin_assignment", lambda **kwargs: kwargs)

    def finish(*_args, **kwargs):
        if kwargs.get("result") == "task_returned":
            observed["finish"].append(kwargs.get("reason"))
    monkeypatch.setattr(control, "finish_assignment", finish)

    def wait(ctrl, failures):
        observed["waits"].append((failures, control._host_precondition_delay(failures)))
        ctrl.stop_event.set()
        return False
    monkeypatch.setattr(control, "_wait_host_precondition", wait)
    real_record = control._record_worker_activity
    monkeypatch.setattr(control, "_record_worker_activity",
                        lambda ctrl, text, *a, **k: (observed["activity"].append(text), real_record(ctrl, text, *a, **k))[1])
    monkeypatch.setattr(control.runtime, "session_store", object())
    monkeypatch.setattr(control.runtime, "clear_session", lambda *_a, **_k: None)

    def start(task_id, **_kwargs):
        raise start_error
    monkeypatch.setattr(worker_git, "start_task_worktree", start)
    monkeypatch.setattr(worker_write_guard, "snapshot_task_start_scope", lambda b, **_k: {
        "availability": "available", "task_id": b.task_id,
        "branch": f"refs/heads/bach-task/{b.task_id}", "source_pin": None})

    async def process(*_a, **_k):
        pytest.fail("no model call before a confirmed task tree")
    monkeypatch.setattr(control.runtime, "process", process)
    response, code = control.start_worker_execution(worker["id"], start_request_id="8" * 32)
    assert code in {200, 202}
    run = control._WORKER_EXECUTIONS[worker["id"]]
    run.thread.join(10)
    assert not run.thread.is_alive()
    return observed


def test_host_precondition_failure_backs_off_instead_of_taking_the_next_task(
        admission, leased_binding, monkeypatch):  # noqa: F811
    from hub._services.chat.worker_write_guard import WorkerWriteGuardError
    control, _ = admission
    worker = add_worker({"name": "Looping kimi", "type": "continuous"})
    update_slot(worker["id"], {"allowed_tools": ["task_manage", "start_task_worktree"], "allow_tools": True})
    observed = _run_loop_once(control, worker, leased_binding, monkeypatch,
                              WorkerWriteGuardError("Twin-Sperrstatus ist unbekannt"))
    assert observed["finish"] == ["host_precondition:twin_status_unknown"]
    assert observed["acquired"] == 1, "a broken host must not churn through further leases"
    assert observed["waits"] == [(1, 60)]
    assert any("twin_status_unknown" in text for text in observed["activity"])
    assert leased_binding.closed


def test_task_scope_failure_keeps_the_short_task_path(admission, leased_binding, monkeypatch):  # noqa: F811
    control, _ = admission
    worker = add_worker({"name": "Task scope", "type": "continuous"})
    update_slot(worker["id"], {"allowed_tools": ["task_manage"], "allow_tools": True})
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda ctrl, **_k: (ctrl.stop_event.set(), False)[1])
    observed = _run_loop_once(control, worker, leased_binding, monkeypatch,
                              RuntimeError("Task-Branch existiert bereits"))
    assert observed["finish"] == ["task_scope_unavailable"]
    assert observed["waits"] == []


def test_host_precondition_delay_doubles_to_fifteen_minutes():
    control = _controller()
    assert [control._host_precondition_delay(n) for n in range(1, 8)] == [60, 120, 240, 480, 900, 900, 900]


# --- repeated identical task-scoped returns end in blocked ----------------------------

def _cycle(client, tid, note, generation):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    bound = WorkerLeaseBinding.acquire(client, tid, worker_id="physical-worker@HOST", host="HOST",
                                       generation=generation, is_current=lambda: True,
                                       stop_event=threading.Event(), clock=lambda: T0)
    assert bound.return_lease(note=note)


def test_fifth_identical_task_return_blocks_with_fixed_reason(binding, mem_db):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    assert binding.return_lease(note="task_scope_unavailable")
    for i in range(3):
        _cycle(client, tid, "task_scope_unavailable", f"g{i}")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"
    _cycle(client, tid, "task_scope_unavailable", "g-last")
    status, = mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()
    note = mem_db.execute("SELECT json_extract(new_value, '$.note') FROM task_history WHERE task_id=? "
                          "AND action='lease_release' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()[0]
    assert status == "blocked"
    assert note == "repeated_return:task_scope_unavailable"


def test_host_precondition_returns_never_block_the_task(binding, mem_db):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    assert binding.return_lease(note="host_precondition:twin_status_unknown")
    for i in range(6):
        _cycle(client, tid, "host_precondition:twin_status_unknown", f"g{i}")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"


def test_returns_without_reason_never_block(binding, mem_db):  # noqa: F811
    """Review R1 (task-master#24): the kernel never blocks an empty reason; BACH relies on that."""
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    assert binding.return_lease(note="")
    for i in range(6):
        _cycle(client, tid, "", f"g{i}")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"


def test_return_stats_adapter_reports_api_fields(binding, mem_db):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    from hub._services.task_return_stats import summarize_task_returns
    client, tid = binding._client, binding.task_id
    assert binding.return_lease(note="model_failure:invalid_tool_call")
    _cycle(client, tid, "model_failure:invalid_tool_call", "g1")
    summary = summarize_task_returns(mem_db, tid)
    assert summary["available"] is True
    assert summary["return_count"] == 2
    assert summary["last_return_reason"] == "model_failure:invalid_tool_call"
    assert summary["flapping"] is False


def test_return_stats_adapter_says_unavailable_without_kernel(mem_db, monkeypatch):  # noqa: F811
    from hub._services import task_return_stats
    monkeypatch.setattr(task_return_stats, "_policy", lambda: None)
    assert task_return_stats.summarize_task_returns(mem_db, 1) == {"available": False}


# --- follow-up tasks are bounded -------------------------------------------------------

def test_followup_add_is_refused_after_a_missing_capability(binding):  # noqa: F811
    from hub._services.chat.worker_lease_binding import WorkerTaskManageArgumentError
    from hub._services.chat.bach_tools import exec_tool
    denied = exec_tool("write_file", {"path": "x.txt", "content": "x"}, "full",
                       worker_task_binding=binding, require_task_binding=True, allowed_tools=None)
    assert "Schreibfreigabe" in str(denied)
    with pytest.raises(WorkerTaskManageArgumentError) as refused:
        binding.execute_task_manage({"action": "add", "title": "Rest: Schreibfreigabe fehlt"})
    assert refused.value.reason == "followup_capability_missing"
    assert "complete=false" in refused.value.user_message


def test_followup_add_stays_allowed_without_a_capability_denial(binding):  # noqa: F811
    # Existing contract (test_worker_tool_trace): several follow-ups per lease, same title reuses.
    assert "erstellt" in binding.execute_task_manage({"action": "add", "title": "Rest: Teil B"})
    assert "erstellt" in binding.execute_task_manage({"action": "add", "title": "Rest: Teil C"})


# --- allowed_tools=None means read-only, not "all write tools visible" ----------------

def test_bound_run_without_explicit_grants_sees_no_write_tools():
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.chat.worker_write_guard import _WRITE_TOOLS
    from system.tests.test_tool_groups_on_demand import _Backend, _names, _session
    session = _session(None)
    names = _names(ChatRuntime(_Backend())._bound_worker_tools_for_request(session, _Backend(), enabled=True))
    assert "read_file" in names and "task_manage" in names
    assert not names & _WRITE_TOOLS


# --- error continuation ------------------------------------------------------------------

def test_retry_after_is_bounded_by_the_cooldown_helper():
    control = _controller()
    detail = {"provider": "ollama", "kind": "rate_limited", "status_code": 429,
              "quota_exceeded": False, "retry_after_seconds": 2_000_000_000}
    assert control._worker_backend_retry_delay({"backend": "ollama", "type": "continuous"}, detail,
        model="glm-5.3:cloud", retries=0, waited_seconds=0) == 3600


def test_cloud_connect_error_backs_off_instead_of_stopping_the_worker():
    control = _controller()
    kwargs = dict(model="glm-5.3:cloud", retries=0, waited_seconds=0, transient_failure="httpx_connect_error")
    assert control._worker_backend_retry_delay({"backend": "ollama", "type": "continuous"}, None, **kwargs) == 60
    assert control._worker_backend_retry_delay({"backend": "ollama", "type": "once"}, None, **kwargs) is None
    assert control._worker_backend_retry_delay({"backend": "ollama", "type": "continuous"}, None,
        model="glm-5.3:cloud", retries=0, waited_seconds=0) is None


def test_failed_answer_marks_connect_errors_as_typed_transient():
    import httpx
    from hub._services.chat.chat_runtime import FailedAnswer
    assert FailedAnswer.from_exception(httpx.ConnectError("All connection attempts failed")
                                       ).transient_failure == "httpx_connect_error"
    assert FailedAnswer.from_exception(httpx.ReadTimeout("x")).transient_failure == "httpx_read_timeout"
    assert FailedAnswer.from_exception(ValueError("x")).transient_failure is None



# --- follow-up to #657 (review R2): transient host/provider failures never block -----------

def _connect_error_note():
    """The return note the controller writes for a cloud ConnectError (same derivation as the loop)."""
    import httpx
    from hub._services.chat.chat_runtime import FailedAnswer
    from hub._services.llm.backend_errors import normalize_backend_error
    answer = FailedAnswer.from_exception(httpx.ConnectError("All connection attempts failed"))
    return _controller()._worker_return_note(
        normalize_backend_error(answer.backend_error), answer.reason_code, answer.transient_failure)


def test_connect_error_return_note_is_not_task_scoped():
    from hub._services.task_return_stats import _TASK_SCOPED_PREFIXES
    note = _connect_error_note()
    assert note == "backend_error:transient:httpx_connect_error"
    assert not note.startswith(_TASK_SCOPED_PREFIXES)


def test_thirty_minute_connect_outage_never_blocks_the_task(binding, mem_db):  # noqa: F811
    """Backoff 60/120/240/480/900 s: about seven returns of the same task in 30 min."""
    pytest.importorskip("taskplan.return_policy")
    from hub._services.task_return_stats import summarize_task_returns
    client, tid = binding._client, binding.task_id
    note = _connect_error_note()
    assert binding.return_lease(note=note)
    for i in range(6):
        _cycle(client, tid, note, f"g{i}")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"
    summary = summarize_task_returns(mem_db, tid)
    assert summary["return_count"] == 7 and summary["last_return_reason"] == note


@pytest.mark.parametrize("note", [
    "model_failure:local_reserve_reserve_wait_expired",
    "model_failure:temporary_connection_error",
    "model_failure:cloud_call_retry_exhausted",
])
def test_host_and_provider_model_failures_never_block(binding, mem_db, note):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    assert binding.return_lease(note=note)
    for i in range(6):
        _cycle(client, tid, note, f"g{i}")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"


def test_task_scoped_model_failure_still_blocks_after_five(binding, mem_db):  # noqa: F811
    """Negative control: the exemption above must not switch the loop guard off."""
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    assert binding.return_lease(note="model_failure:invalid_tool_call")
    for i in range(4):
        _cycle(client, tid, "model_failure:invalid_tool_call", f"g{i}")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "blocked"


def test_resolver_closes_again_after_a_second_outage(monkeypatch):
    """Success closes the resolver; a later host outage opens one; the next success closes it again."""
    control = _controller()
    calls = []
    monkeypatch.setattr(control, "_ensure_worker_resolver", lambda ident, code: calls.append(("open", code)))
    monkeypatch.setattr(control, "_close_worker_resolver", lambda ident: calls.append(("close", ident)))
    ctrl = control._WorkerControl("worker-x")
    control._close_worker_resolver_once(ctrl, "worker-x")   # first successful task
    control._close_worker_resolver_once(ctrl, "worker-x")   # further tasks: no extra close
    control._open_worker_resolver(ctrl, "worker-x", "twin_status_unknown")  # second outage escalates
    control._close_worker_resolver_once(ctrl, "worker-x")   # recovery
    assert calls == [("close", "worker-x"), ("open", "twin_status_unknown"), ("close", "worker-x")]


# --- resolver tasks close when the worker works again -----------------------------------

def test_worker_resolver_closes_itself(tmp_path):
    from system.tests import test_task_lease_service as service
    from hub.task_audit import close_worker_error_resolver, ensure_worker_error_resolver
    database = tmp_path / "canonical.db"
    service._create_db(database)
    conn = service._connect(database)
    resolver = ensure_worker_error_resolver(conn, "worker-fdb98a89", "cleanup_error")
    assert close_worker_error_resolver(conn, "worker-fdb98a89") == resolver
    status, description = conn.execute("SELECT status, description FROM tasks WHERE id=?", (resolver,)).fetchone()
    assert status == "done" and "wieder in Betrieb" in description
    assert close_worker_error_resolver(conn, "worker-fdb98a89") is None
    assert ensure_worker_error_resolver(conn, "worker-fdb98a89", "cleanup_error") not in (None, resolver)


def test_running_worker_closes_its_resolver_once(admission, leased_binding, monkeypatch):  # noqa: F811
    control, _ = admission
    worker = add_worker({"name": "Back in business", "type": "continuous"})
    update_slot(worker["id"], {"allowed_tools": ["task_manage"], "allow_tools": True})
    closed = []
    monkeypatch.setattr(control, "_close_worker_resolver", lambda ident: closed.append(ident))
    monkeypatch.setattr(control, "_acquire_worker_task", lambda *_a: leased_binding)
    monkeypatch.setattr(control, "begin_assignment", lambda **kwargs: kwargs)
    monkeypatch.setattr(control, "finish_assignment", lambda *_a, **_k: None)
    monkeypatch.setattr(control.runtime, "session_store", object())
    monkeypatch.setattr(control.runtime, "clear_session", lambda *_a, **_k: None)
    monkeypatch.setattr(control, "_prepare_bound_task_scope", lambda *_a: None)

    async def process(*_a, **_k):
        control._WORKER_CONTROLS[worker["id"]].stop_event.set()
        return "Teilstand"
    monkeypatch.setattr(control.runtime, "process", process)
    response, code = control.start_worker_execution(worker["id"], start_request_id="7" * 32)
    assert code in {200, 202}
    run = control._WORKER_EXECUTIONS[worker["id"]]
    run.thread.join(10)
    assert closed == [worker["id"]]


# --- read-only API for the GUI (PB-4) ----------------------------------------------------

def test_task_returns_api_reports_fields_and_rejects_bad_ids(tmp_path, monkeypatch):
    pytest.importorskip("taskplan.return_policy")
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hub import bach_paths
    from gui.api.task_returns import router
    from system.tests import test_task_lease_service as service
    database = tmp_path / "canonical.db"
    service._create_db(database)
    conn = service._connect(database)
    tid = service._insert(conn)
    for i in range(5):
        conn.execute("INSERT INTO task_history (task_id, action, field_changed, old_value, new_value, changed_by, "
                     "changed_at) VALUES (?, 'lease_release', 'lease', 'in_progress', ?, 'worker-x@HOST', ?)",
                     (tid, json.dumps({"fence": i + 1, "note": "host_precondition:twin_status_unknown",
                                       "outcome": "return"}), f"2026-11-06T18:0{i}:00+00:00"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(bach_paths, "BACH_DB", database)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.get(f"/api/tasks/{tid}/returns").json()
    assert body["available"] is True and body["task_id"] == tid
    assert body["return_count"] == 5 and body["host_scoped"] is True
    assert body["last_return_reason"] == "host_precondition:twin_status_unknown"
    batch = client.get(f"/api/task-returns?ids={tid},{tid}").json()["tasks"]
    assert list(batch) == [str(tid)] and batch[str(tid)]["return_count"] == 5
    assert client.get("/api/task-returns?ids=abc").status_code == 400
    assert client.get("/api/task-returns?ids=0").status_code == 400


# --- pickup filter reads the tags the native write path stores --------------------------

@pytest.mark.parametrize("tags", ['["delegated"]', '["bauort:x","delegated"]', "delegated", "x, delegated"])
def test_pickup_filter_excludes_native_json_tags(tags):
    from hub._services.chat.slots_config import pickup_filter_rejection
    from hub.task_audit import normalize_task_tags
    slot = {"id": "buddha_always_on", "pickup_filter": {"enabled": True, "categories": [], "priorities": [],
                                                       "tags": [], "exclude_tags": ["delegated", "waiting"]}}
    task = {"id": 1, "title": "x", "category": "bach-ci", "priority": "P2", "status": "pending",
            "assigned_to": "BACH", "tags": tags}
    assert pickup_filter_rejection(task, slot) == "excluded_tag"
    stored = normalize_task_tags(["delegated"])  # what apply_task_field_changes writes
    assert pickup_filter_rejection({**task, "tags": stored}, slot) == "excluded_tag"


def test_pickup_include_filter_matches_native_json_tags():
    from hub._services.chat.slots_config import pickup_filter_rejection
    slot = {"id": "w", "pickup_filter": {"enabled": True, "categories": [], "priorities": [],
                                        "tags": ["bauort:ellmos-talk"], "exclude_tags": []}}
    task = {"id": 1, "title": "x", "category": "c", "priority": "P2", "status": "pending",
            "assigned_to": "BACH", "tags": '["bauort:ellmos-talk","ocean-plan"]'}
    assert pickup_filter_rejection(task, slot) is None


# --- PB-14 (#3999): uncommitted task-tree work is committed locally before a return ------

@pytest.fixture
def local_task_tree(bridge, tmp_path, monkeypatch):  # noqa: F811
    """A real git repo + registered task worktree; only the lock scan is stubbed."""
    import subprocess
    from hub import worker_git
    from hub._services.chat import worker_write_guard
    from system.tests.test_bound_worker_git import _add_task_tree
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["git", "init", "-b", "main"], ["git", "config", "user.name", "Test"],
                ["git", "config", "user.email", "test@example.com"]):
        subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True)
    (repo / "README.md").write_text("# Test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True)
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setenv("BACH_ROOT", str(repo))
    monkeypatch.setenv("BACH_WORKTREES_DIR", str(root))
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: repo)
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: root)
    monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
    target = _add_task_tree(bridge.binding.task_id)
    (target / "half_done.py").write_text("print('half')\n", encoding="utf-8")
    return bridge.binding, target


def _git_out(target, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=str(target), capture_output=True, text=True, check=True).stdout.strip()


def test_local_wip_commits_without_push_and_leaves_the_tree_clean(local_task_tree):
    from hub import worker_git
    binding, target = local_task_tree
    message = f"wip(task-{binding.task_id}): worker_stopped"
    result = worker_git.finish_task(binding.task_id, message, is_wip=True, run_tests=False,
                                    worker_task_binding=binding, push=False)
    assert result["success"] is True and result["status"] == "wip_committed"
    assert _git_out(target, "status", "--porcelain") == ""
    assert _git_out(target, "log", "-1", "--format=%s") == message
    assert "lokal" in binding.task_snapshot()["description"]


def test_controller_secures_worktree_wip_before_a_return(local_task_tree, monkeypatch):
    from types import SimpleNamespace
    control = _controller()
    binding, target = local_task_tree
    monkeypatch.setattr(control, "_execution_worker_slot", lambda ident: {"allowed_tools": ["write_file"]})
    result = control._secure_worktree_wip(SimpleNamespace(task_binding=binding, worker_id="w"), "backend_error")
    assert result["success"] is True
    assert _git_out(target, "status", "--porcelain") == ""
    assert _git_out(target, "log", "-1", "--format=%s") == f"wip(task-{binding.task_id}): backend_error"


def test_failed_wip_is_noted_and_never_blocks_the_return(local_task_tree, monkeypatch):
    from types import SimpleNamespace
    from hub import worker_git
    control = _controller()
    binding, _ = local_task_tree
    monkeypatch.setattr(control, "_execution_worker_slot", lambda ident: {"allowed_tools": ["write_file"]})
    monkeypatch.setattr(worker_git, "finish_task", lambda *a, **k: {"success": False, "error": "Secrets-Scan fehlgeschlagen"})
    result = control._secure_worktree_wip(SimpleNamespace(task_binding=binding, worker_id="w"), "worker_stopped")
    assert result["success"] is False
    assert "[WIP nicht gesichert] worker_stopped" in binding.task_snapshot()["description"]
    assert binding.return_lease(note="worker_stopped")


def test_read_only_worker_never_attempts_a_wip(local_task_tree, monkeypatch):
    from types import SimpleNamespace
    from hub import worker_git
    control = _controller()
    binding, _ = local_task_tree
    monkeypatch.setattr(control, "_execution_worker_slot", lambda ident: {"allowed_tools": ["read_file"]})
    monkeypatch.setattr(worker_git, "finish_task", lambda *a, **k: pytest.fail("no WIP without write grant"))
    assert control._secure_worktree_wip(SimpleNamespace(task_binding=binding, worker_id="w"), "x") is None


def test_model_return_leaves_a_committed_not_a_dirty_task_tree(admission, local_task_tree, monkeypatch):  # noqa: F811
    control, _ = admission
    binding, target = local_task_tree
    worker = add_worker({"name": "Writer", "type": "continuous"})
    update_slot(worker["id"], {"allowed_tools": ["task_manage", "write_file"], "allow_tools": True})
    monkeypatch.setattr(control, "_acquire_worker_task", lambda *_a: binding)
    monkeypatch.setattr(control, "begin_assignment", lambda **kwargs: kwargs)
    monkeypatch.setattr(control, "finish_assignment", lambda *_a, **_k: None)
    monkeypatch.setattr(control, "_close_worker_resolver", lambda ident: None)
    monkeypatch.setattr(control.runtime, "session_store", object())
    monkeypatch.setattr(control.runtime, "clear_session", lambda *_a, **_k: None)
    monkeypatch.setattr(control, "_prepare_bound_task_scope", lambda *_a: None)

    async def process(*_a, **_k):
        # The model writes, then hands the task back open (the Rest-cascade path).
        (target / "more_work.py").write_text("x = 1\n", encoding="utf-8")
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id, "status": "pending"})
        control._WORKER_CONTROLS[worker["id"]].stop_event.set()
        return "Teilstand"
    monkeypatch.setattr(control.runtime, "process", process)
    response, code = control.start_worker_execution(worker["id"], start_request_id="6" * 32)
    assert code in {200, 202}
    run = control._WORKER_EXECUTIONS[worker["id"]]
    run.thread.join(20)
    assert not run.thread.is_alive()
    assert binding.closed
    assert _git_out(target, "status", "--porcelain") == ""
    assert _git_out(target, "log", "-1", "--format=%s") == f"wip(task-{binding.task_id}): worker_returned_open"


def test_after_an_operator_stop_no_write_happens_but_the_return_does(local_task_tree, monkeypatch):
    """Known limit: a stopped binding forbids every mutation, the WIP included."""
    from types import SimpleNamespace
    control = _controller()
    binding, target = local_task_tree
    monkeypatch.setattr(control, "_execution_worker_slot", lambda ident: {"allowed_tools": ["write_file"]})
    binding.before_return = lambda note: control._secure_worktree_wip(
        SimpleNamespace(task_binding=binding, worker_id="w"), note)
    binding._stop_event.set()
    assert binding.return_lease(note="worker_stopped")
    assert "half_done.py" in _git_out(target, "status", "--porcelain")


# --- PB-1 follow-up: rotation loop (description kept, no follow-ups of follow-ups, no-progress block) ----

def _acquire(client, tid, generation):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    return WorkerLeaseBinding.acquire(client, tid, worker_id="physical-worker@HOST", host="HOST",
                                      generation=generation, is_current=lambda: True,
                                      stop_event=threading.Event(), clock=lambda: T0)


def _description(db, tid):
    return db.execute("SELECT description FROM tasks WHERE id=?", (tid,)).fetchone()[0]


def test_worker_update_appends_partial_state_and_keeps_assignment(binding, mem_db):  # noqa: F811
    tid = binding.task_id
    binding.execute_task_manage({"action": "update", "task_id": tid, "description": "Auftrag X"})
    for text in ("Teilstand 1", "Teilstand 2"):
        binding.execute_task_manage({"action": "update", "task_id": tid, "description": text})
    stored = _description(mem_db, tid)
    assert stored.startswith("Auftrag X")
    assert stored.index("Teilstand 1") < stored.index("Teilstand 2")


def test_worker_update_that_extends_the_assignment_is_taken_as_is(binding, mem_db):  # noqa: F811
    tid = binding.task_id
    binding.execute_task_manage({"action": "update", "task_id": tid, "description": "Auftrag X"})
    binding.execute_task_manage({"action": "update", "task_id": tid, "description": "Auftrag X\n\nErgaenzung"})
    assert _description(mem_db, tid) == "Auftrag X\n\nErgaenzung"


def test_worker_interim_states_stay_bounded(binding, mem_db):  # noqa: F811
    tid = binding.task_id
    binding.execute_task_manage({"action": "update", "task_id": tid, "description": "Auftrag X"})
    for i in range(30):
        binding.execute_task_manage({"action": "update", "task_id": tid, "description": f"Stand {i} " + "z" * 9000})
    stored = _description(mem_db, tid)
    assert stored.startswith("Auftrag X") and "Stand 29" in stored and "Stand 0 " not in stored
    assert len(stored) < 20000


def test_worker_created_task_cannot_spawn_further_followups(binding, mem_db):  # noqa: F811
    from hub._services.chat.worker_lease_binding import WorkerTaskManageArgumentError
    client = binding._client
    assert "erstellt" in binding.execute_task_manage({"action": "add", "title": "Rest: Teil B"})
    child, = mem_db.execute("SELECT id FROM tasks WHERE title='Rest: Teil B'").fetchone(),
    child_id = child[0]
    assert binding.return_lease(note="x")
    bound = _acquire(client, child_id, "g-child")
    count = mem_db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    for action in ({"action": "add", "title": "Rest: Teil C"},
                   {"action": "decompose", "task_id": child_id, "subtasks": [{"title": "Teil D"}],
                    "close_parent": False}):
        with pytest.raises(WorkerTaskManageArgumentError) as refused:
            bound.execute_task_manage(action)
        assert refused.value.reason == "followup_depth_exceeded"
    assert mem_db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == count


def _return_open(client, tid, generation, *, progress=False):
    bound = _acquire(client, tid, generation)
    if progress:
        bound.note_progress()
    bound.execute_task_manage({"action": "update", "task_id": tid, "status": "pending"})


def _last_release_note(db, tid):
    return db.execute("SELECT json_extract(new_value, '$.note') FROM task_history WHERE task_id=? "
                      "AND action='lease_release' ORDER BY id DESC LIMIT 1", (tid,)).fetchone()[0]


def test_open_returns_without_progress_block_after_three(binding, mem_db):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    binding.execute_task_manage({"action": "update", "task_id": tid, "description": "Neufassung statt Arbeit"})
    binding.execute_task_manage({"action": "update", "task_id": tid, "status": "pending"})
    _return_open(client, tid, "g1")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"
    assert _last_release_note(mem_db, tid) == "worker_returned_open:no_progress"
    _return_open(client, tid, "g2")
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "blocked"
    assert _last_release_note(mem_db, tid) == "repeated_return:worker_returned_open:no_progress"


def test_open_returns_with_progress_keep_the_five_return_rule(binding, mem_db):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    binding.note_progress()
    binding.execute_task_manage({"action": "update", "task_id": tid, "status": "pending"})
    for i in range(3):
        _return_open(client, tid, f"g{i}", progress=True)
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "pending"
    assert _last_release_note(mem_db, tid) == "worker_returned_open"
    _return_open(client, tid, "g-last", progress=True)
    assert mem_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "blocked"
    assert _last_release_note(mem_db, tid) == "repeated_return:worker_returned_open"


def test_no_progress_block_opens_exactly_one_resolver(binding, mem_db):  # noqa: F811
    pytest.importorskip("taskplan.return_policy")
    client, tid = binding._client, binding.task_id
    binding.execute_task_manage({"action": "update", "task_id": tid, "status": "pending"})
    _return_open(client, tid, "g1")
    _return_open(client, tid, "g2")
    source = f"resolver:task:{tid}"
    assert mem_db.execute("SELECT COUNT(*) FROM tasks WHERE source=?", (source,)).fetchone()[0] == 1


def test_wip_commit_counts_as_progress(local_task_tree):
    from hub import worker_git
    binding, _ = local_task_tree
    assert binding._progress is False
    worker_git.finish_task(binding.task_id, f"wip(task-{binding.task_id}): x", is_wip=True, run_tests=False,
                           worker_task_binding=binding, push=False)
    assert binding._progress is True


def test_decomposing_counts_as_progress(binding):  # noqa: F811
    assert binding._progress is False
    binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                 "subtasks": [{"title": "Kind A"}], "close_parent": False})
    assert binding._progress is True


def test_a_bare_add_is_no_progress(binding):  # noqa: F811
    binding.execute_task_manage({"action": "add", "title": "Rest: nur ein Folgetask"})
    assert binding._progress is False
