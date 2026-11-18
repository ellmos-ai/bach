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


@pytest.mark.parametrize("revision", [None, 0, "", "z" * 64])
def test_review_enrollment_requires_an_explicit_valid_registry_cas(registry_world, revision):
    w = registry_world
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as raised:
        registry.enroll_review_task_repository(w["client"], w["child"]["review_task_id"],
            task_version=w["child"]["task_version"], expected_registry_sha256=revision,
            operator="operator:test-review")
    assert raised.value.reason_code == "registry_changed"
    assert w["registry"].read_bytes() == before


def test_native_registry_fence_is_checked_before_any_marker_creation(registry_world, monkeypatch):
    from hub._services.chat import worker_write_guard
    w = registry_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    original_open = registry.os.open
    marker_opens = []
    def watched_open(path, flags, *args, **kwargs):
        if Path(path) == marker:
            marker_opens.append(flags)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(registry.os, "open", watched_open)
    monkeypatch.setattr(worker_write_guard, "_scan_locks",
                        lambda *args, **kwargs: {"locks": [], "hook_guards": ["locked"]})
    before = w["registry"].read_bytes()
    with pytest.raises(registry.RepositoryBindingError):
        enroll(w)
    assert marker_opens == []
    assert w["registry"].read_bytes() == before


@pytest.fixture(params=["legacy", "enrolled"])
def decomposition_world(registry_world, request):
    import threading
    w = registry_world
    with sqlite3.connect(w["database"]) as conn:
        parent = conn.execute(
            "INSERT INTO tasks(title,status,description,category,assigned_to,creation_origin) "
            "VALUES('Native decomposition','pending','Parent instructions','INBOX','OLLAMA','user')").lastrowid
    rewrite_registry(w, lambda data: data["tasks"].update({
        str(parent): dict(data["tasks"][str(w["task_id"])])}))
    if request.param == "enrolled":
        def modern(data):
            data["schema"] = registry.ENROLLED_SCHEMA
            data["tasks"][str(parent)].update(
                task_version=w["client"].task_snapshot(parent)["task_version"],
                operator="operator:test-decompose", registered_at="2026-11-17T23:00:00+00:00",
                source_proof_sha256="f" * 64)
        rewrite_registry(w, modern)
    binding = WorkerLeaseBinding.acquire(w["client"], parent, worker_id="decompose@test",
        host="test", generation="decompose-generation", is_current=lambda: True,
        stop_event=threading.Event())
    request = {"action": "decompose", "task_id": parent, "close_parent": False,
               "subtasks": [{"title": "Exact confirmed child"}]}
    return {**w, "parent": parent, "decomposer": binding, "request": request}


def child_receipt(world):
    with sqlite3.connect(world["database"]) as conn:
        raw = conn.execute(
            "SELECT new_value FROM task_history WHERE task_id=? AND action='lease_decompose' "
            "ORDER BY id DESC LIMIT 1", (world["parent"],)).fetchone()[0]
    return json.loads(raw)


def test_decomposition_busy_registry_is_visible_and_same_request_retries_without_new_children(decomposition_world):
    w = decomposition_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        first = w["decomposer"].execute_task_manage(w["request"])
    finally:
        marker.unlink()
    assert "noch nicht bestätigt" in first
    receipt = child_receipt(w)
    child = receipt["created_ids"][0]
    assert receipt["child_task_versions"][str(child)] == w["client"].task_snapshot(child)["task_version"]
    with sqlite3.connect(w["database"]) as conn:
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    second = w["decomposer"].execute_task_manage(w["request"])
    assert "Repository-Bindungen bestätigt" in second
    assert registry.resolve_task_repository(child).repository == "ellmos-ai/bach"
    third = w["decomposer"].execute_task_manage(w["request"])
    assert "keine neuen Teilaufgaben" in third
    with sqlite3.connect(w["database"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == count
        assert conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id=? AND action='lease_decompose'",
                            (w["parent"],)).fetchone()[0] == 1


def test_decomposition_repairs_after_process_loss_from_native_history_and_fresh_lease(decomposition_world):
    import threading
    w = decomposition_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        w["decomposer"].execute_task_manage(w["request"])
    finally:
        marker.unlink()
    receipt = child_receipt(w)
    before = w["registry"].read_bytes()
    ack = w["decomposer"]._ack
    w["client"].release(w["parent"], lease_id=ack.lease_id, fence=ack.fence,
                       task_version=ack.task_version, outcome="return")
    fresh = WorkerLeaseBinding.acquire(w["client"], w["parent"], worker_id="new-process@test",
        host="test", generation="new-process-generation", is_current=lambda: True,
        stop_event=threading.Event())
    assert fresh._decomposition_receipt is None
    result = fresh.execute_task_manage(w["request"])
    assert "Repository-Bindungen bestätigt" in result
    assert w["registry"].read_bytes() != before
    assert registry.resolve_task_repository(receipt["created_ids"][0]).repository == "ellmos-ai/bach"
    assert child_receipt(w) == receipt


@pytest.mark.parametrize("changed", ["child", "parent_lease"])
def test_decomposition_retry_never_publishes_with_changed_child_or_parent_lease(decomposition_world, changed):
    w = decomposition_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        w["decomposer"].execute_task_manage(w["request"])
    finally:
        marker.unlink()
    child = child_receipt(w)["created_ids"][0]
    if changed == "child":
        mutate_database(w, "UPDATE tasks SET description='changed after child creation' WHERE id=?", (child,))
    else:
        mutate_database(w, "UPDATE tasks SET claim_fence=claim_fence+1 WHERE id=?", (w["parent"],))
    before = w["registry"].read_bytes()
    result = w["decomposer"].execute_task_manage(w["request"])
    assert "noch nicht bestätigt" in result
    assert w["registry"].read_bytes() == before


def test_historical_decomposition_without_child_pins_has_existing_explicit_operator_repair(decomposition_world):
    w = decomposition_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        w["decomposer"].execute_task_manage(w["request"])
    finally:
        marker.unlink()
    receipt = child_receipt(w)
    receipt.pop("child_task_versions")
    mutate_database(w, "UPDATE task_history SET new_value=? WHERE task_id=? AND action='lease_decompose'",
                    (json.dumps(receipt), w["parent"]))
    before = w["registry"].read_bytes()
    result = w["decomposer"].execute_task_manage(w["request"])
    assert "decomposition_receipt_legacy" in result
    assert w["registry"].read_bytes() == before
    # Existing canonical operator API: IDs originate in the durable native receipt.
    for tid in receipt["created_ids"]:
        snapshot = w["client"].task_snapshot(tid)
        repaired = registry.enroll_task_repository(w["client"], tid,
            repository="ellmos-ai/bach", task_version=snapshot["task_version"],
            source_sha=w["source_sha"],
            expected_registry_sha256=hashlib.sha256(w["registry"].read_bytes()).hexdigest(),
            operator="operator:test-repair")
        assert repaired["task_mutated"] is False
        assert registry.resolve_task_repository(tid).repository == "ellmos-ai/bach"
    assert "Repository-Bindungen bestätigt" in w["decomposer"].execute_task_manage(w["request"])


def test_decomposition_publish_reserves_the_native_sqlite_writer(decomposition_world, monkeypatch):
    w = decomposition_world
    original = registry._RegistryWriter.publish
    probes = []
    def publish(writer, value):
        with sqlite3.connect(w["database"], timeout=.01) as rival:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                rival.execute("UPDATE tasks SET description='racing writer' WHERE id=?", (w["parent"],))
        probes.append(True)
        return original(writer, value)
    monkeypatch.setattr(registry._RegistryWriter, "publish", publish)
    result = w["decomposer"].execute_task_manage(w["request"])
    assert "noch nicht bestätigt" not in result
    assert probes == [True]
    child = child_receipt(w)["created_ids"][0]
    assert registry.resolve_task_repository(child).repository == "ellmos-ai/bach"


@pytest.mark.parametrize("changed", ["child", "parent", "restart"])
def test_new_add_after_completed_inheritance_keeps_normal_operation(decomposition_world, changed):
    import threading
    w = decomposition_world
    binding = w["decomposer"]
    result = binding.execute_task_manage(w["request"])
    assert "noch nicht bestätigt" not in result
    previous = child_receipt(w)
    child = previous["created_ids"][0]
    old_binding = registry.resolve_task_repository(child)
    if changed in {"child", "restart"}:
        mutate_database(w, "UPDATE tasks SET description='Ordinary follow-up notes' WHERE id=?", (child,))
    if changed in {"parent", "restart"}:
        binding.execute_task_manage({"action": "update", "task_id": w["parent"],
                                     "description": "Additional parent instructions"})
    if changed == "restart":
        ack = binding._ack
        w["client"].release(w["parent"], lease_id=ack.lease_id, fence=ack.fence,
                            task_version=ack.task_version, outcome="return")
        binding = WorkerLeaseBinding.acquire(w["client"], w["parent"], worker_id="new-process@test",
            host="test", generation="new-followup-generation", is_current=lambda: True,
            stop_event=threading.Event())
    result = binding.execute_task_manage({"action": "add", "title": "New distinct follow-up"})
    with sqlite3.connect(w["database"]) as conn:
        rows = conn.execute("SELECT id FROM tasks WHERE title='New distinct follow-up'").fetchall()
    assert len(rows) == 1, result
    assert "erstellt" in result
    assert registry.resolve_task_repository(rows[0][0]).repository == "ellmos-ai/bach"
    assert registry.resolve_task_repository(child) == old_binding
    assert child_receipt(w)["created_ids"] == [rows[0][0]]


def test_new_add_is_not_reinterpreted_as_a_different_pending_operation(decomposition_world):
    w = decomposition_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        first = w["decomposer"].execute_task_manage(w["request"])
    finally:
        marker.unlink()
    assert "noch nicht bestätigt" in first
    before = w["registry"].read_bytes()
    receipt = child_receipt(w)
    result = w["decomposer"].execute_task_manage({"action": "add", "title": "Different requested work"})
    assert "Repository-Bindungen bestätigt" not in result
    assert "repository_inheritance_pending" in result
    assert w["registry"].read_bytes() == before
    assert child_receipt(w) == receipt
    with sqlite3.connect(w["database"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE title='Different requested work'").fetchone()[0] == 0
    # Only the matching operation retries the existing children.
    assert "Repository-Bindungen bestätigt" in w["decomposer"].execute_task_manage(w["request"])


def test_pending_add_repeat_uses_its_native_operation_without_duplicate_creation(decomposition_world):
    w = decomposition_world
    args = {"action": "add", "title": "One native add", "description": "Original intent"}
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        first = w["decomposer"].execute_task_manage(args)
    finally:
        marker.unlink()
    assert "noch nicht bestätigt" in first
    receipt = child_receipt(w)
    before = w["registry"].read_bytes()
    different = w["decomposer"].execute_task_manage({**args, "description": "Different intent"})
    assert "repository_inheritance_pending" in different
    assert w["registry"].read_bytes() == before
    assert child_receipt(w) == receipt
    result = w["decomposer"].execute_task_manage(args)
    assert "Repository-Bindungen bestätigt" in result
    assert child_receipt(w) == receipt
    with sqlite3.connect(w["database"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE title='One native add'").fetchone()[0] == 1


def test_completed_decomposition_does_not_claim_a_different_request_succeeded(decomposition_world):
    from hub._services.chat.worker_lease_binding import WorkerTaskManageArgumentError
    w = decomposition_world
    w["decomposer"].execute_task_manage(w["request"])
    before = child_receipt(w)
    with pytest.raises(WorkerTaskManageArgumentError) as raised:
        w["decomposer"].execute_task_manage({
            **w["request"], "subtasks": [{"title": "Different decomposition"}]})
    assert raised.value.reason == "decompose_already_decomposed"
    assert child_receipt(w) == before
    with sqlite3.connect(w["database"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE title='Different decomposition'").fetchone()[0] == 0


def test_completed_historical_binding_allows_new_add_after_child_edits(decomposition_world):
    w = decomposition_world
    w["decomposer"].execute_task_manage(w["request"])
    old = child_receipt(w)
    old.pop("request_sha256")
    old.pop("child_task_versions")
    mutate_database(w, "UPDATE task_history SET new_value=? WHERE task_id=? AND action='lease_decompose'",
                    (json.dumps(old), w["parent"]))
    mutate_database(w, "UPDATE tasks SET description='Legitimate later edit' WHERE id=?",
                    (old["created_ids"][0],))
    result = w["decomposer"].execute_task_manage({"action": "add", "title": "Follow-up after old event"})
    assert "erstellt" in result
    new = child_receipt(w)
    assert new["created_ids"] != old["created_ids"]
    assert registry.resolve_task_repository(new["created_ids"][0]).repository == "ellmos-ai/bach"


def test_pending_historical_operation_without_signature_has_explicit_operator_repair(decomposition_world):
    w = decomposition_world
    marker = w["registry"].with_name(w["registry"].name + ".operator-lock")
    marker.touch(mode=0o600)
    try:
        w["decomposer"].execute_task_manage(w["request"])
    finally:
        marker.unlink()
    old = child_receipt(w)
    old.pop("request_sha256")
    mutate_database(w, "UPDATE task_history SET new_value=? WHERE task_id=? AND action='lease_decompose'",
                    (json.dumps(old), w["parent"]))
    before = w["registry"].read_bytes()
    result = w["decomposer"].execute_task_manage(w["request"])
    assert "repository_inheritance_pending" in result
    assert w["registry"].read_bytes() == before
    for tid in old["created_ids"]:
        repaired = registry.enroll_task_repository(w["client"], tid,
            repository="ellmos-ai/bach", task_version=w["client"].task_snapshot(tid)["task_version"],
            source_sha=w["source_sha"],
            expected_registry_sha256=hashlib.sha256(w["registry"].read_bytes()).hexdigest(),
            operator="operator:test-historical-repair")
        assert repaired["task_mutated"] is False
        assert registry.resolve_task_repository(tid).repository == "ellmos-ai/bach"
    result = w["decomposer"].execute_task_manage({"action": "add", "title": "After explicit repair"})
    assert "erstellt" in result
    new = child_receipt(w)
    assert new["created_ids"] != old["created_ids"]
    assert registry.resolve_task_repository(new["created_ids"][0]).repository == "ellmos-ai/bach"
