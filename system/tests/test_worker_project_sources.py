"""Project-source policy with isolated Git repositories and synthetic metadata.

No network, model, live TaskDB or credentials are used by these fixtures.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
import threading
from pathlib import Path

import pytest
from hub import worker_git
from hub._services import task_lease_client
from hub._services.chat import slots_config
from hub._services.chat import worker_project_sources as sources
from hub._services.chat import worker_write_guard as guard
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub.task_audit import apply_task_field_changes

from system.tests.test_task_tags import _create_db


def git(repo, *args):
    return subprocess.check_output(["git", "-c", "commit.gpgsign=false", *args],
                                   cwd=repo, text=True, encoding="utf-8").strip()


@pytest.fixture
def projects(tmp_path, monkeypatch):
    records = {}
    for project, repository in (("bach", "ellmos-ai/bach"), ("chat", "ellmos-ai/ellmos-chat")):
        repo = tmp_path / (project + "-repo")
        repo.mkdir()
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.name", "Source fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        (repo / "README.md").write_text(project + " public fixture\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-m", "fixture")
        origin = "https://github.com/" + repository
        git(repo, "remote", "add", "origin", origin)
        records[project] = {"repository": repository, "origin": origin, "repo_root": str(repo),
                            "worktrees_root": str(tmp_path / (project + "-trees")),
                            "lock_scope": str(repo), "source_class": "public", "retired": False,
                            "source_ref": "refs/heads/main", "source_sha": git(repo, "rev-parse", "HEAD")}
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps({"schema": sources.REGISTRY_SCHEMA, "entries": records}), encoding="utf-8")
    monkeypatch.setattr(sources, "registry_path", lambda: registry)
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    def metadata(url):
        for record in records.values():
            base = "https://api.github.com/repos/" + record["repository"]
            if url == base:
                return {"full_name": record["repository"], "private": False, "visibility": "public"}
            if url == base + "/commits/" + record["source_sha"]:
                return {"sha": record["source_sha"]}
            if url == base + "/git/ref/heads/main":
                return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": record["source_sha"]}}
            if url == base + "/compare/" + record["source_sha"] + "..." + record["source_sha"]:
                return {"status": "identical", "base_commit": {"sha": record["source_sha"]},
                        "merge_base_commit": {"sha": record["source_sha"]}}
        raise AssertionError("Unexpected metadata request")
    monkeypatch.setattr(worker_git, "_github_json", metadata)
    monkeypatch.setattr(guard, "_fresh_locks", lambda *args, **kwargs: None)
    return records, registry


def source_task(projects, tmp_path, project="chat"):
    database = tmp_path / "tasks.db"
    _create_db(database)
    client = task_lease_client.TaskLeaseClient(db_path=database)
    snapshot = client.task_snapshot(1)
    with sqlite3.connect(database) as conn:
        receipt = sources.operator_bind_task_project(conn, 1, snapshot["task_version"], project)
    binding = WorkerLeaseBinding.acquire(client, 1, worker_id="source-fixture@HOST", host="HOST",
                                         generation="source-fixture-v1", is_current=lambda: True,
                                         stop_event=threading.Event())
    assert binding.task_snapshot()["task_version"] == receipt["task_version"]
    return client, binding, database


def test_task_tags_pin_entry_digest_and_commit(projects, tmp_path):
    _, binding, _ = source_task(projects, tmp_path)
    selector = sources.task_source_selector(binding.task_snapshot())
    source = sources.project_for_binding(binding)
    assert selector == ("chat", projects[0]["chat"]["source_sha"], sources._digest(projects[0]["chat"]))
    assert source.repository == "ellmos-ai/ellmos-chat"
    assert len(base64.urlsafe_b64encode(bytes.fromhex(source.entry_sha256)).decode().rstrip("=")) == 43


@pytest.mark.parametrize("changes", [
    {"worker-project:chat": "worker-project:missing"},
    {"worker-commit:": "worker-commit:" + "0" * 40},
    {"worker-entry:": "worker-entry:" + "A" * 43},
    {"worker-source:v1": "worker-source:v2"},
])
def test_generic_and_holder_updates_cannot_retarget(projects, tmp_path, changes):
    client, binding, database = source_task(projects, tmp_path)
    snapshot = binding.task_snapshot()
    tags = json.loads(snapshot["tags"])
    for index, tag in enumerate(tags):
        for prefix, replacement in changes.items():
            if tag.startswith(prefix):
                tags[index] = replacement
    with sqlite3.connect(database) as conn, pytest.raises(ValueError, match="Operator-Projektvertrag"):
        apply_task_field_changes(conn, 1, snapshot, {"tags": tags}, changed_by="user")
    with pytest.raises((ValueError, RuntimeError)):
        client.update(1, **binding._ref(), changes={"tags": tags})
    assert client.task_snapshot(1)["task_version"] == snapshot["task_version"]


def test_operator_binding_requires_free_lease_and_current_version(projects, tmp_path):
    client, binding, database = source_task(projects, tmp_path)
    current = binding.task_snapshot()["task_version"]
    with sqlite3.connect(database) as conn, pytest.raises(sources.ProjectSourceError, match="übernommen"):
        sources.operator_bind_task_project(conn, 1, current, "bach")
    assert binding.return_lease()
    with sqlite3.connect(database) as conn, pytest.raises(sources.ProjectSourceError, match="Taskversion"):
        sources.operator_bind_task_project(conn, 1, "f" * 64, "bach")
    assert client.task_snapshot(1)["task_version"] == current


def test_unrelated_registry_changes_do_not_invalidate_binding(projects, tmp_path):
    _, binding, _ = source_task(projects, tmp_path)
    source = sources.project_for_binding(binding)
    catalogue = json.loads(projects[1].read_text())
    catalogue["entries"]["unrelated"] = {"not": "this task's entry"}
    projects[1].write_text(json.dumps(catalogue), encoding="utf-8")
    binding.assert_active()
    assert sources.project_for_binding(binding) == source


@pytest.mark.parametrize("field,value", [("retired", True), ("source_sha", "0" * 40),
                                         ("repository", "ellmos-ai/other"), ("repo_root", "/other")])
def test_changed_entry_stops_call_boundary_and_tools(projects, tmp_path, field, value):
    _, binding, _ = source_task(projects, tmp_path)
    sources.project_for_binding(binding)
    catalogue = json.loads(projects[1].read_text())
    catalogue["entries"]["chat"][field] = value
    projects[1].write_text(json.dumps(catalogue), encoding="utf-8")
    with pytest.raises(sources.ProjectSourceError):
        binding.assert_active()
    with pytest.raises(sources.ProjectSourceError):
        guard.authorize_start(binding, 1)
    # Revocation does not prevent native cleanup from returning the known lease.
    assert binding.return_lease()


def test_source_metadata_does_not_change_operational_pickup_filters(projects):
    record = projects[0]["chat"]
    entry = base64.urlsafe_b64encode(bytes.fromhex(sources._digest(record))).decode().rstrip("=")
    tags = ["ordinary", "worker-source:v1", "worker-project:chat", "worker-commit:" + record["source_sha"], "worker-entry:" + entry]
    slot = {"pickup_filter": {"enabled": True, "tags": ["ordinary"], "exclude_tags": ["worker-project:chat"]}}
    assert slots_config.match_task_to_pickup_filter({"tags": json.dumps(tags)}, slot)
    assert slots_config.match_task_to_pickup_filter({"tags": json.dumps(["ordinary"])}, slot)


def test_unknown_foreign_legacy_metadata_is_not_bach():
    with pytest.raises(sources.ProjectSourceError, match="native Projektquellenbindung"):
        sources.task_source_selector({"project": "ellmos-chat", "tags": None})
    assert sources.task_source_selector({"project": None, "tags": None}) is None


def test_registry_cannot_overwrite_existing_or_retired_identifier(projects):
    import hashlib
    records, path = projects
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(sources.ProjectSourceError, match="unveränderlich"):
        sources.operator_register_project("chat", records["chat"], expected_registry_sha256=expected)
    catalogue = json.loads(path.read_text())
    catalogue["entries"]["chat"]["retired"] = True
    path.write_text(json.dumps(catalogue), encoding="utf-8")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(sources.ProjectSourceError, match="unveränderlich"):
        sources.operator_register_project("chat", records["chat"], expected_registry_sha256=expected)


def test_enabled_registry_requires_explicit_finite_legacy_classification(projects, tmp_path):
    import hashlib
    _, path = projects
    database = tmp_path / "legacy.db"
    _create_db(database)
    client = task_lease_client.TaskLeaseClient(db_path=database)
    snapshot = client.task_snapshot(1)
    with pytest.raises(sources.ProjectSourceError, match="Legacy-BACH"):
        sources._assert_legacy_classification(snapshot)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(database) as conn:
        receipt = sources.operator_classify_legacy_task(conn, 1, snapshot["task_version"],
                                                       expected_registry_sha256=before)
    assert receipt["task_version"] == snapshot["task_version"]
    assert client.task_snapshot(1) == snapshot
    sources._assert_legacy_classification(snapshot)
    with pytest.raises(sources.ProjectSourceError, match="Legacy-BACH"):
        sources._assert_legacy_classification({**snapshot, "id": 2})
    with pytest.raises(sources.ProjectSourceError, match="Legacy-BACH"):
        sources._assert_legacy_classification({**snapshot, "task_version": "0" * 64})
    with pytest.raises(sources.ProjectSourceError, match="Legacy-BACH"):
        sources._assert_legacy_classification({"id": 999})
    # A fenced run retains its initial classification across its own native
    # content updates. A fresh claim must classify the new content revision.
    sources._assert_legacy_classification({**snapshot, "task_version": "0" * 64},
                                         classification_version=snapshot["task_version"])


def test_operator_retirement_keeps_id_tombstone_and_revokes_bound_calls(projects, tmp_path):
    import hashlib
    records, path = projects
    _, binding, _ = source_task(projects, tmp_path)
    sources.project_for_binding(binding)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = sources.operator_retire_project("chat", expected_registry_sha256=before)
    assert receipt["registry_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert sources.load_registry()["entries"]["chat"]["retired"] is True
    with pytest.raises(sources.ProjectSourceError):
        sources.assert_source_current(binding)
    with pytest.raises(sources.ProjectSourceError, match="unveränderlich"):
        sources.operator_register_project("chat", records["chat"],
                                         expected_registry_sha256=receipt["registry_sha256"])


def test_native_decomposition_inherits_only_parent_project_source(projects, tmp_path):
    client, binding, database = source_task(projects, tmp_path)
    parent_tags = sources.source_tags(binding.task_snapshot()["tags"])
    result = binding.execute_task_manage({"action": "decompose", "task_id": 1,
        "subtasks": [{"title": "Child in same source"}], "close_parent": False})
    assert result
    with sqlite3.connect(database) as conn:
        children = conn.execute("SELECT id,tags FROM tasks WHERE id<>1").fetchall()
    assert len(children) == 1
    assert sources.source_tags(children[0][1]) == parent_tags
    assert sources.task_source_selector(client.task_snapshot(children[0][0])) == sources.task_source_selector(binding.task_snapshot())


def _unclaimed_source_task(projects, tmp_path):
    database = tmp_path / "unclaimed-source.db"
    _create_db(database)
    client = task_lease_client.TaskLeaseClient(db_path=database)
    snapshot = client.task_snapshot(1)
    with sqlite3.connect(database) as conn:
        sources.operator_bind_task_project(conn, 1, snapshot["task_version"], "chat")
    return database, client.task_snapshot(1)


def test_unreadable_explicit_source_is_never_reported_as_unchanged(projects, tmp_path, monkeypatch):
    database, snapshot = _unclaimed_source_task(projects, tmp_path)
    record = projects[0]["chat"]
    root = Path(record["worktrees_root"])
    root.mkdir()
    target = root / "task-1"
    git(record["repo_root"], "worktree", "add", str(target), "-b", "bach-task/1", record["source_sha"])
    (target / "README.md").write_text("actual uncommitted project work\n", encoding="utf-8")
    def denied(*args, **kwargs):
        raise PermissionError("fixture source unreadable")
    monkeypatch.setattr(sources, "resolve_project", denied)
    with sqlite3.connect(database) as conn:
        assert worker_git.task_has_file_changes(1, conn, task_snapshot=snapshot) is True
        with pytest.raises(ValueError, match="eingetragenem PR"):
            apply_task_field_changes(conn, 1, snapshot, {"status": "completed"}, changed_by="user")


def test_unexpected_completion_inspection_error_blocks_explicit_source(projects, tmp_path, monkeypatch):
    database, snapshot = _unclaimed_source_task(projects, tmp_path)
    def denied(*args, **kwargs):
        raise PermissionError("fixture inspection unavailable")
    monkeypatch.setattr(worker_git, "task_has_file_changes", denied)
    with sqlite3.connect(database) as conn:
        with pytest.raises(ValueError, match="nicht zuverlässig geprüft"):
            apply_task_field_changes(conn, 1, snapshot, {"status": "completed"}, changed_by="user")
        assert conn.execute("SELECT status FROM tasks WHERE id=1").fetchone()[0] != "completed"


@pytest.mark.parametrize("mode", ["missing", "wrong_ref", "tag", "behind", "diverged", "wrong_ancestor"])
def test_public_source_rejects_unverified_branch_or_pin(projects, monkeypatch, mode):
    source = sources.resolve_project("chat", projects[0]["chat"]["source_sha"])
    original = worker_git._github_json
    def metadata(url):
        if "/git/ref/" in url:
            if mode == "missing":
                raise RuntimeError("fixture HTTP404")
            return {"ref": "refs/heads/other" if mode == "wrong_ref" else source.source_ref,
                    "object": {"type": "tag" if mode == "tag" else "commit", "sha": source.source_sha}}
        if "/compare/" in url:
            return {"status": mode if mode in ("behind", "diverged") else "identical",
                    "base_commit": {"sha": source.source_sha},
                    "merge_base_commit": {"sha": "f" * 40 if mode == "wrong_ancestor" else source.source_sha}}
        return original(url)
    monkeypatch.setattr(worker_git, "_github_json", metadata)
    with pytest.raises(RuntimeError):
        sources.verify_public_source(source)


def test_public_source_verifies_pin_ancestor_of_observed_tip(projects, monkeypatch):
    source = sources.resolve_project("chat", projects[0]["chat"]["source_sha"])
    original = worker_git._github_json
    tip = "f" * 40
    calls = []
    def metadata(url):
        calls.append(url)
        if "/git/ref/" in url:
            return {"ref": source.source_ref, "object": {"type": "commit", "sha": tip}}
        if "/compare/" in url:
            assert url.endswith(source.source_sha + "..." + tip)
            return {"status": "ahead", "base_commit": {"sha": source.source_sha},
                    "merge_base_commit": {"sha": source.source_sha}}
        return original(url)
    monkeypatch.setattr(worker_git, "_github_json", metadata)
    proof = sources.verify_public_source(source)
    assert proof["ref_verified"] is True and proof["pin_ancestor_verified"] is True
    assert proof["observed_ref_sha"] == tip
    assert len(calls) == 4
