# SPDX-License-Identifier: MIT
"""Review repository inheritance exercises real private intents in a private HOME."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from hub._services import task_lease_client
from hub._services import worker_result_review as review
from hub._services.chat import worker_repo_registry as registry
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub import worker_git
from system.tests.test_task_lease_client import mem_db
from system.tests.test_worker_execution_evidence import worker_context
from system.tests.test_worker_result_review import review_world, _prepare, _paths


@pytest.fixture
def registry_world(review_world, tmp_path, monkeypatch):
    world = review_world
    child = _prepare(world)
    private_home = tmp_path / "private-home"
    local = private_home / ".bach"
    local.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: private_home))
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    database = local / "bach.db"
    copied = sqlite3.connect(database)
    world["conn"].backup(copied)
    copied.close()
    client = task_lease_client.TaskLeaseClient()
    native_intent_target = review._intent_target
    def private_scope_target(conn, found, **kwargs):
        pair = native_intent_target(conn, found, **_paths(world))
        return pair
    monkeypatch.setattr(review, "_intent_target", private_scope_target)
    source_sha = "b" * 40
    data = {
        "schema": registry.REGISTRY_SCHEMA,
        "repositories": {"ellmos-ai/bach": {
            "origin": "https://github.com/ellmos-ai/bach",
            "default_branch": "main", "visibility": "public"}},
        "tasks": {str(world["task_id"]): {
            "repository": "ellmos-ai/bach", "source_sha": source_sha}},
    }
    path = registry.registry_path()
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(0o600)
    source = registry.source_clone_path("ellmos-ai/bach", source_sha)
    source.mkdir(parents=True)
    monkeypatch.setattr(worker_git, "_safe_source_clone_path", lambda binding: source)
    calls = []

    def verify(path, binding, *, require_current):
        calls.append((binding.task_id, require_current))
        assert path == source
        return {"schema": "bach.task-public-source.v2",
                "repository": binding.repository, "origin": binding.origin,
                "source_sha": binding.source_sha, "source_ref": "refs/heads/main",
                "visibility": "public", "private": False,
                "metadata_verified": True, "ref_verified": True}
    monkeypatch.setattr(worker_git, "_validate_pinned_source_clone", verify)
    from hub._services.chat import worker_write_guard
    native_scan = worker_write_guard._scan_locks
    def source_scan(path, **kwargs):
        if Path(path) in {local, source}:
            return {"locks": [], "hook_guards": []}
        return native_scan(path, **kwargs)
    monkeypatch.setattr(worker_write_guard, "_scan_locks", source_scan)
    return {**world, "child": child, "client": client, "registry": path,
            "database": database, "source": source, "source_sha": source_sha,
            "verification_calls": calls, "verify": verify}


def enroll(world, **extra):
    return registry.enroll_review_task_repository(
        world["client"], world["child"]["review_task_id"],
        task_version=world["child"]["task_version"],
        expected_registry_sha256=hashlib.sha256(world["registry"].read_bytes()).hexdigest(),
        operator="operator:test-review", **extra)


def rewrite_registry(world, mutate):
    data = json.loads(world["registry"].read_text())
    mutate(data)
    world["registry"].write_text(json.dumps(data), encoding="utf-8")


def mutate_database(world, sql, args=()):
    with sqlite3.connect(world["database"]) as conn:
        conn.execute(sql, args)


def test_verified_review_inherits_parent_repository_without_task_or_grant_changes(registry_world):
    w = registry_world
    tid = w["child"]["review_task_id"]
    before = w["client"].task_snapshot(tid)
    result = enroll(w)
    assert result["state"] == "enrolled"
    assert result["task_mutated"] is False
    bound = registry.resolve_task_repository(tid)
    assert bound.repository == "ellmos-ai/bach"
    assert bound.source_sha == w["source_sha"]
    assert bound.task_version == before["task_version"]
    assert w["client"].task_snapshot(tid) == before
    assert w["client"].read(tid).leased is False
    assert len(w["verification_calls"]) >= 2
    # Review inherits the parent's immutable source, not a newer unrelated main.
    assert all(current is False for _, current in w["verification_calls"])


def test_matching_existing_binding_is_idempotent(registry_world):
    w = registry_world
    enroll(w)
    before = w["registry"].read_bytes()
    assert enroll(w)["state"] == "already_bound"
    assert w["registry"].read_bytes() == before


@pytest.mark.parametrize("damage,reason", [
    ("missing_parent", "parent_binding_missing"),
    ("damaged_intent", "review_provenance_unavailable"),
    ("changed_parent", "review_provenance_unavailable"),
    ("leased_child", "review_not_pending"),
    ("conflicting_child", "review_binding_conflict"),
])
def test_review_inheritance_rejects_missing_stale_or_conflicting_evidence(registry_world, damage, reason):
    w = registry_world
    tid = w["child"]["review_task_id"]
    if damage == "missing_parent":
        rewrite_registry(w, lambda data: data["tasks"].pop(str(w["task_id"])))
    elif damage == "damaged_intent":
        mutate_database(w, "UPDATE worker_result_review_intents SET intent_sha256=? WHERE review_task_id=?",
                        ("0" * 64, tid))
    elif damage == "changed_parent":
        mutate_database(w, "UPDATE tasks SET description='changed after submission' WHERE id=?",
                        (w["task_id"],))
    elif damage == "leased_child":
        mutate_database(w, "UPDATE tasks SET claim_id='foreign-lease' WHERE id=?", (tid,))
    else:
        rewrite_registry(w, lambda data: data["tasks"].update({
            str(tid): {"repository": "ellmos-ai/bach", "source_sha": "c" * 40}}))
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        enroll(w)
    assert raised.value.reason_code == reason
    assert w["registry"].read_bytes() == before


def test_source_verification_failure_does_not_publish_binding(registry_world, monkeypatch):
    w = registry_world
    def fail(*args, **kwargs):
        raise RuntimeError("private path must not appear in diagnostics")
    monkeypatch.setattr(worker_git, "_validate_pinned_source_clone", fail)
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        enroll(w)
    assert raised.value.reason_code == "review_source_unverified"
    assert "private path" not in str(raised.value)
    assert w["registry"].read_bytes() == before


def test_expected_registry_revision_is_required_and_compared(registry_world):
    w = registry_world
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        registry.enroll_review_task_repository(w["client"], w["child"]["review_task_id"],
            task_version=w["child"]["task_version"], expected_registry_sha256="0" * 64,
            operator="operator:test-review")
    assert raised.value.reason_code == "registry_changed"
    assert w["registry"].read_bytes() == before


def test_existing_operator_fence_blocks_review_and_decomposition_writers(registry_world):
    w = registry_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        enroll(w)
    assert raised.value.reason_code == "registry_busy"
    binding = object.__new__(WorkerLeaseBinding)
    binding._ack = type("Ack", (), {"task_id": w["task_id"]})()
    binding._client = w["client"]
    assert binding._inherit_decomposed_subtask_bindings((987654,)) is False
    assert w["registry"].read_bytes() == before
    assert marker.exists()


def test_parent_change_during_source_check_fails_cas(registry_world, monkeypatch):
    w = registry_world
    calls = []
    def changing(path, binding, *, require_current):
        calls.append(1)
        if len(calls) == 2:
            mutate_database(w, "UPDATE tasks SET description='racing mutation' WHERE id=?",
                            (w["task_id"],))
        return w["verify"](path, binding, require_current=require_current)
    monkeypatch.setattr(worker_git, "_validate_pinned_source_clone", changing)
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        enroll(w)
    assert raised.value.reason_code in {"review_provenance_unavailable", "review_provenance_changed"}
    assert w["registry"].read_bytes() == before


def test_noncanonical_client_cannot_publish_live_repository_bindings(registry_world):
    w = registry_world
    borrowed = task_lease_client.TaskLeaseClient(conn=w["conn"])
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        registry.enroll_review_task_repository(borrowed, w["child"]["review_task_id"],
            task_version=w["child"]["task_version"],
            expected_registry_sha256=hashlib.sha256(before).hexdigest(),
            operator="operator:test-review")
    assert raised.value.reason_code == "canonical_lead_required"
    assert w["registry"].read_bytes() == before


def test_native_creator_binds_existing_pending_child_idempotently(registry_world):
    w = registry_world
    with sqlite3.connect(w["database"]) as conn:
        result = review._prepare_native_review(conn, w["task_id"], **_paths(w))
    assert result["repository_binding"]["state"] == "enrolled"
    assert registry.resolve_task_repository(result["review_task_id"]).repository == "ellmos-ai/bach"


def test_native_creator_exposes_binding_failure_without_accepting_or_granting(registry_world, caplog):
    w = registry_world
    rewrite_registry(w, lambda data: data["tasks"].pop(str(w["task_id"])))
    before = w["registry"].read_bytes()
    with sqlite3.connect(w["database"]) as conn:
        result = review._prepare_native_review(conn, w["task_id"], **_paths(w))
    assert result["repository_binding"] == {
        "state": "unavailable", "reason_code": "parent_binding_missing"}
    assert "parent_binding_missing" in caplog.text
    assert w["registry"].read_bytes() == before
    assert w["client"].read(result["review_task_id"]).leased is False
    assert w["client"].task_snapshot(result["review_task_id"])["status"] == "pending"
