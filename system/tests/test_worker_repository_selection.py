"""The canonical task repo is checked against worker capability before claim."""
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.chat.worker_repo_registry import RepositoryBindingError
from hub._services.chat.worker_queue_status import project_selection_policy
from hub._services.task_lease_client import TaskLeaseClient
from system.tests.test_task_lease_client import _init_db, _insert_task as _base_insert_task
from system.tests.test_task_lease_client_review import T0


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    yield conn
    conn.close()


def add_task(conn, assigned_to="BACH"):
    task_id = _base_insert_task(conn)
    conn.execute("UPDATE tasks SET assigned_to=? WHERE id=?", (assigned_to, task_id))
    conn.commit()
    return task_id


def acquire(client, reports, slot, **extra):
    return WorkerLeaseBinding.acquire_next(
        client, slot, observe_queue=reports.append,
        worker_id="repo-test-worker@HOST", host="HOST", generation="repo-test-generation",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0,
        **extra,
    )


def slot(**changes):
    return {"id": "repo-worker", "allowed_repositories": ["ellmos-ai/bach"], **changes}


def test_repo_capability_skips_higher_priority_foreign_repo_before_acquire(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    foreign_id = add_task(mem_db, "BACH")
    bach_id = add_task(mem_db, "BACH")
    repositories = {foreign_id: "other/agent", bach_id: "ellmos-ai/bach"}
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda task_id: SimpleNamespace(repository=repositories[int(task_id)]))
    client = TaskLeaseClient(conn=mem_db)
    client.task_candidates = lambda **kwargs: {"tasks": [client.task_snapshot(foreign_id),
        client.task_snapshot(bach_id)] if kwargs.get("offset", 0) == 0 else [],
        "has_more": False, "offset": kwargs.get("offset", 0)}
    reports = []

    binding = acquire(client, reports, slot())

    assert binding.task_id == bach_id
    report, = reports
    assert report["selected_task_id"] == bach_id
    assert report["rejected_counts"] == {"repository_not_allowed": 1}
    assert report["matched_count"] == report["attempted_count"] == 1
    assert not client.read(foreign_id).leased


def test_missing_or_unverified_repo_binding_fails_closed_without_lease(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: (_ for _ in ()).throw(RepositoryBindingError("unavailable")))
    client = TaskLeaseClient(conn=mem_db)
    reports = []

    assert acquire(client, reports, slot()) is None
    report, = reports
    assert report["rejected_counts"] == {"repository_unverified": 1}
    assert report["matched_count"] == report["attempted_count"] == 0
    assert not client.read(task_id).leased


def test_legacy_profile_without_allowlist_fails_closed(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository="ellmos-ai/bach"))
    client = TaskLeaseClient(conn=mem_db)
    reports = []

    assert acquire(client, reports, {"id": "legacy-worker"}) is None
    report, = reports
    assert report["rejected_counts"] == {"repository_capability_missing": 1}
    assert report["matched_count"] == report["attempted_count"] == 0
    assert not client.read(task_id).leased


def test_fixed_task_checks_repository_before_attempt_counter(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository="other/agent"))
    client = TaskLeaseClient(conn=mem_db)
    reports = []

    assert acquire(client, reports, slot(task_id=task_id)) is None
    report, = reports
    assert report["rejected_counts"] == {"repository_not_allowed": 1}
    assert report["candidate_count"] == 1
    assert report["matched_count"] == report["attempted_count"] == 0
    assert not client.read(task_id).leased


def test_registry_change_between_preview_and_acquire_is_rejected_before_claim(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    repositories = iter(("ellmos-ai/bach", "other/agent"))
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository=next(repositories)))
    client = TaskLeaseClient(conn=mem_db)
    client.task_candidates = lambda **kwargs: {"tasks": [client.task_snapshot(task_id)]
        if kwargs.get("offset", 0) == 0 else [], "has_more": False, "offset": kwargs.get("offset", 0)}
    native_acquire = client.acquire
    calls = []
    def tracked_acquire(*args, **kwargs):
        calls.append(True)
        return native_acquire(*args, **kwargs)
    client.acquire = tracked_acquire
    reports = []

    assert acquire(client, reports, slot()) is None
    report, = reports
    assert report["rejected_counts"] == {"repository_changed": 1}
    assert report["matched_count"] == 1 and report["attempted_count"] == 1
    assert not calls
    assert not client.read(task_id).leased


def test_task_content_change_after_preview_is_revalidated_before_claim(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository="ellmos-ai/bach"))
    client = TaskLeaseClient(conn=mem_db)
    candidate = client.task_snapshot(task_id)
    client.task_candidates = lambda **kwargs: {"tasks": [candidate]
        if kwargs.get("offset", 0) == 0 else [], "has_more": False, "offset": kwargs.get("offset", 0)}
    fresh_snapshot = dict(candidate, assigned_slot="someone-else")
    client.task_snapshot = lambda _task_id: fresh_snapshot
    native_acquire = client.acquire
    calls = []
    def tracked_acquire(*args, **kwargs):
        calls.append(True)
        return native_acquire(*args, **kwargs)
    client.acquire = tracked_acquire
    reports = []

    assert acquire(client, reports, slot()) is None
    report, = reports
    assert report["rejected_counts"] == {"changed_selection": 1}
    assert report["matched_count"] == report["attempted_count"] == 1
    assert not calls
    assert not TaskLeaseClient(conn=mem_db).read(task_id).leased


def test_review_candidate_is_repo_checked_before_grant_or_acquire(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository="other/agent"))
    client = TaskLeaseClient(conn=mem_db)
    grants = []
    client.task_candidates = lambda **kwargs: {"tasks": [], "has_more": False,
        "offset": kwargs.get("offset", 0)}
    client._review_candidates = lambda **_kwargs: {"tasks": [client.task_snapshot(task_id)],
        "has_more": False, "offset": 0}
    client._issue_review_grant = lambda *_args, **_kwargs: grants.append(True)
    reports = []

    assert acquire(client, reports, slot(), review_route={"model": "review-model"},
        review_requested_model="review-model") is None
    report, = reports
    assert report["rejected_counts"].get("repository_not_allowed") == 1
    assert not grants
    assert not client.read(task_id).leased


def test_allowed_review_repository_reaches_native_grant_path(mem_db, monkeypatch):
    from hub._services.chat import worker_repo_registry
    task_id = add_task(mem_db)
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository="ellmos-ai/bach"))
    client = TaskLeaseClient(conn=mem_db)
    candidate = client.task_snapshot(task_id)
    client.task_candidates = lambda **kwargs: {"tasks": [], "has_more": False,
        "offset": kwargs.get("offset", 0)}
    client._review_candidates = lambda **kwargs: {"tasks": [candidate], "has_more": False,
        "offset": kwargs.get("offset", 0)}
    grants = []
    client._issue_review_grant = lambda *_args, **_kwargs: grants.append(True) or object()
    sentinel = SimpleNamespace(task_id=task_id)
    monkeypatch.setattr(WorkerLeaseBinding, "acquire", classmethod(
        lambda cls, *_args, **_kwargs: sentinel))
    reports = []

    assert acquire(client, reports, slot(), review_route={"model": "review-model"},
        review_requested_model="review-model") is sentinel
    assert grants == [True]
    report, = reports
    assert report["matched_count"] == report["attempted_count"] == 1
    assert report["rejected_counts"] == {}


@pytest.mark.parametrize("repositories", [
    ["ellmos-ai/bach", "other/agent"],
    [],
])
def test_selection_policy_projects_only_canonical_bounded_capabilities(repositories):
    policy = project_selection_policy({
        "schema": "bach.worker-selection.v1", "require_assigned_slot": False,
        "allowed_repositories": repositories,
        "pickup_filter": {"enabled": False, "categories": [], "priorities": [], "tags": [], "exclude_tags": []},
    })
    assert policy["allowed_repositories"] == repositories


@pytest.mark.parametrize("repositories", [
    ["Ellmos-ai/bach"], ["ellmos-ai/bach", "ellmos-ai/bach"],
    ["https://github.com/ellmos-ai/bach"], ["../bach"], ["ellmos-ai/bach/extra"],
])
def test_selection_policy_rejects_noncanonical_or_duplicate_repo_ids(repositories):
    assert project_selection_policy({
        "schema": "bach.worker-selection.v1", "require_assigned_slot": False,
        "allowed_repositories": repositories,
        "pickup_filter": {"enabled": False, "categories": [], "priorities": [], "tags": [], "exclude_tags": []},
    }) is None


def test_worker_configuration_validator_accepts_only_canonical_repo_capabilities():
    from hub._services.chat.slots_config import (
        CORE_EDITABLE_FIELDS, WORKER_EDITABLE_FIELDS, _validated_core_edits,
        _validated_worker_repository_allowlist,
    )
    values = ["ellmos-ai/bach", "other/agent"]
    assert _validated_worker_repository_allowlist(values) == values
    assert _validated_core_edits({"allowed_repositories": values})["allowed_repositories"] == values
    assert "allowed_repositories" in CORE_EDITABLE_FIELDS and "allowed_repositories" in WORKER_EDITABLE_FIELDS
    with pytest.raises(ValueError):
        _validated_worker_repository_allowlist(["ellmos-ai/bach", "ellmos-ai/bach"])


def test_dynamic_worker_creation_persists_and_validates_repository_capability(tmp_path):
    from pathlib import Path
    from hub._services.chat import slots_config
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    worker = slots_config.add_worker({"name": "Repo-bound", "type": "continuous",
        "allowed_repositories": ["ellmos-ai/bach"]}, path=path)
    assert worker["allowed_repositories"] == ["ellmos-ai/bach"]
    assert slots_config.get_worker_slot(worker["id"], path=path)[
        "allowed_repositories"] == ["ellmos-ai/bach"]
    before = Path(path).read_bytes()
    with pytest.raises(ValueError):
        slots_config.add_worker({"name": "Invalid repo", "allowed_repositories": [
            "https://github.com/ellmos-ai/bach"]}, path=path)
    assert Path(path).read_bytes() == before


def test_legacy_update_slot_validates_repository_capability_before_write(tmp_path):
    from hub._services.chat import slots_config
    from pathlib import Path
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    before = Path(path).read_bytes()
    with pytest.raises(ValueError):
        slots_config.update_slot("buddha_chat", {
            "allowed_repositories": ["https://github.com/ellmos-ai/bach"]
        }, path=path)
    assert Path(path).read_bytes() == before
    slots_config.update_slot("buddha_chat", {
        "allowed_repositories": ["ellmos-ai/bach"]
    }, path=path)
    assert slots_config.load_slots_config(path, strict=True)["slots"]["buddha_chat"][
        "allowed_repositories"
    ] == ["ellmos-ai/bach"]


@pytest.mark.parametrize("scope_repository", ["other/agent", "not canonical"])
def test_pre_model_scope_rechecks_resolved_repository_against_slot_capability(monkeypatch,
                                                                                scope_repository):
    from hub._services.chat import telegram_chat, worker_write_guard
    from hub import worker_git

    task_id = 918273
    class Binding:
        def __init__(self):
            self.task_id = task_id
        def assert_active(self):
            return True

    monkeypatch.setattr(worker_git, "start_task_worktree", lambda *_args, **_kwargs: "/tmp/task-tree")
    monkeypatch.setattr(worker_write_guard, "snapshot_task_start_scope", lambda *_args, **_kwargs: {
        "schema": "bach.task-start-scope.v1", "availability": "available", "task_id": task_id,
        "repository": scope_repository, "branch": f"refs/heads/bach-task/{task_id}",
        "source_pin": None})
    slot_policy = {"type": "continuous", "allowed_tools": ["task_manage"],
        "allowed_repositories": ["ellmos-ai/bach"]}

    with pytest.raises(RuntimeError, match="nicht bestätigt"):
        telegram_chat._prepare_bound_task_scope(Binding(), slot_policy)


def test_pre_model_scope_blocks_unallowed_repository_before_worktree_creation(monkeypatch):
    from hub._services.chat import telegram_chat
    from hub import worker_git

    task_id = 918274
    class Binding:
        def __init__(self):
            self.task_id = task_id
        def assert_active(self):
            return True

    starts = []
    monkeypatch.setattr(worker_git, "start_task_worktree",
        lambda *_args, **_kwargs: starts.append(True))
    from hub._services.chat import worker_repo_registry
    monkeypatch.setattr(worker_repo_registry, "resolve_task_repository",
        lambda _task_id: SimpleNamespace(repository="other/agent"))
    with pytest.raises(RuntimeError, match="nicht bestätigt"):
        telegram_chat._prepare_bound_task_scope(Binding(), {
            "type": "continuous", "allowed_tools": ["task_manage"],
            "allowed_repositories": ["ellmos-ai/bach"]})
    assert starts == []


def test_worktree_creation_rejects_registry_change_before_foreign_tree_side_effects(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from hub import worker_git

    task_id = 918275
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    worktrees = tmp_path / "worktrees"
    binding = SimpleNamespace(repository="other/agent", source_sha="0" * 40)
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: worktrees)
    monkeypatch.setattr(worker_git, "_resolve_task_source",
        lambda *_args, **_kwargs: (binding, source_repo, None))
    with pytest.raises(RuntimeError, match="änderte sich"):
        worker_git.start_task_worktree(task_id, worker_task_binding=object(),
            require_task_binding=True, expected_repository="ellmos-ai/bach")
    assert not (worktrees / f"task-{task_id}").exists()
    assert not worktrees.exists()
