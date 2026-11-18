"""Native maintenance creation keeps provenance across ACK loss and restarts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub._services.docs.maintenance_dispatch import DocumentationDispatcher
from hub._services.chat import worker_repo_registry as registry
from hub._services.task_lease import task_content_version


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def native(tmp_path, monkeypatch):
    from core.hooks import hooks
    from hub.task import TaskHandler
    from hub import worker_git
    from system import bach_api

    home = tmp_path / "home"
    private = home / ".bach"
    private.mkdir(parents=True, mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("BACH_RHEINGOLD_DISABLED", "1")
    root = tmp_path / "bach"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "README.md").write_text("Native docs source\n")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "add", "docs/README.md")
    _git(root, "commit", "-m", "Fixture")
    revision = _git(root, "rev-parse", "HEAD")
    _git(root, "remote", "add", "origin", "https://github.com/ellmos-ai/bach")
    monkeypatch.setenv("BACH_ROOT", str(root))
    source = registry.source_clone_path("ellmos-ai/bach", revision)
    source.parent.mkdir(parents=True)
    os.chmod(registry.source_root(), 0o700)
    subprocess.run(["git", "clone", "--no-local", str(root), str(source)],
                   check=True, capture_output=True, text=True)
    _git(source, "remote", "set-url", "origin", "https://github.com/ellmos-ai/bach")
    monkeypatch.setattr(worker_git, "_public_default_branch_metadata",
                        lambda *_: {"source_sha": revision})
    from hub._services.chat import worker_write_guard
    monkeypatch.setattr(worker_write_guard, "_scan_locks", lambda _: {"hook_guards": []})
    path = registry.registry_path()
    path.write_text(json.dumps({"schema": registry.REGISTRY_SCHEMA, "repositories": {
        "ellmos-ai/bach": {"origin": "https://github.com/ellmos-ai/bach",
                          "default_branch": "main", "visibility": "public"}},
        "tasks": {}}))
    path.chmod(0o600)
    db = private / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.executescript((Path(__file__).parents[1] / "data/schema/schema.sql").read_text())
    monkeypatch.setattr(bach_api, "_resolve_db_path", lambda: db)
    monkeypatch.setattr(hooks, "emit", lambda *_args, **_kwargs: None)
    handler = TaskHandler(root / "system")
    handler.db_path = db
    proxy = bach_api._TaskProxy("task")
    monkeypatch.setattr(proxy, "raw", lambda operation, *args: handler.handle(operation, list(args)))
    monkeypatch.setattr(bach_api, "task", proxy)
    monkeypatch.setattr(bach_api, "get_app", lambda: SimpleNamespace(get_handler=lambda _: handler))
    # The installed facade and implementation are distinct module objects.
    import bach_api as facade
    monkeypatch.setattr(facade, "task", proxy)
    monkeypatch.setattr(facade, "get_app", lambda: SimpleNamespace(get_handler=lambda _: handler))

    def result(task_id):
        return {"verified": True, "task_id": task_id,
                "status": proxy.show(task_id)["status"], "result": None}

    def dispatcher():
        return DocumentationDispatcher(root, private / "maintenance" / "documentation.json",
            proxy, result, lambda _: None,
            snapshot=lambda *_: (revision, ["docs/README.md"]))

    def rows(table="tasks"):
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM " + table)]

    return SimpleNamespace(root=root, db=db, private=private, source=source,
        revision=revision, handler=handler, proxy=proxy, dispatcher=dispatcher, rows=rows)


def test_native_dispatch_produces_a_verified_repository_binding(native):
    dispatched = native.dispatcher().dispatch()
    task_id = dispatched["task_id"]
    binding = registry.resolve_task_repository(task_id)
    assert binding.repository == "ellmos-ai/bach"
    assert binding.source_sha == native.revision
    row = native.proxy.show(task_id)
    assert binding.task_version == task_content_version(native.rows()[0])
    assert row["status"] == "pending" and row["assigned_to"] == "BACH"
    assert len(native.rows("maintenance_task_intents")) == 1


def test_public_fields_cannot_forge_producer_authority(native):
    from hub._services.task_lease_client import TaskLeaseClient
    row = native.proxy.add("Doku-Delta root spoofed", category="WORKER",
                           assigned_to="BACH", creation_origin="native-docs-maintenance")
    before = registry.registry_path().read_bytes()
    with pytest.raises(registry.RepositoryBindingError, match="maintenance_provenance"):
        registry.enroll_maintenance_task_repository(TaskLeaseClient(), row["id"],
            expected_registry_sha256=hashlib.sha256(before).hexdigest())
    assert registry.registry_path().read_bytes() == before


def test_create_ack_loss_recovers_after_restart_without_duplicate(native, monkeypatch):
    add = native.handler._add
    calls = []

    def lose_ack(*args, **kwargs):
        answer = add(*args, **kwargs)
        calls.append(answer)
        raise RuntimeError("lost native create ACK")

    monkeypatch.setattr(native.handler, "_add", lose_ack)
    with pytest.raises(RuntimeError, match="lost native create ACK"):
        native.dispatcher().dispatch()
    assert len(native.rows()) == 1
    assert len(native.rows("maintenance_task_intents")) == 1
    assert not (native.private / "maintenance" / "documentation.json").exists()
    monkeypatch.setattr(native.handler, "_add", add)
    native.dispatcher().dispatch()
    assert len(calls) == 1 and len(native.rows()) == 1
    assert registry.resolve_task_repository(native.rows()[0]["id"]).source_sha == native.revision


def test_enrollment_failure_retries_before_existing_pending_return(native, monkeypatch):
    enroll = registry.enroll_maintenance_task_repository

    def busy(*_args, **_kwargs):
        raise registry.RepositoryBindingError("registry_busy", reason_code="registry_busy")

    monkeypatch.setattr(registry, "enroll_maintenance_task_repository", busy)
    with pytest.raises(RuntimeError, match="registry_busy"):
        native.dispatcher().dispatch()
    assert len(native.rows()) == 1
    monkeypatch.setattr(registry, "enroll_maintenance_task_repository", enroll)
    native.dispatcher().dispatch()
    assert len(native.rows()) == 1
    registry.resolve_task_repository(native.rows()[0]["id"])


def test_missing_source_never_creates_an_unbound_task(native):
    native.source.rename(native.source.with_name("unavailable"))
    with pytest.raises(RuntimeError, match="maintenance_source_unverified"):
        native.dispatcher().dispatch()
    assert native.rows() == []


def test_task_and_private_receipt_roll_back_together(native, monkeypatch):
    from hub._services.docs import maintenance_task_provenance as provenance
    original = provenance._record_intent

    def fail_after_intent(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(provenance, "_record_intent", fail_after_intent)
    with pytest.raises(RuntimeError, match="injected transaction failure"):
        native.dispatcher().dispatch()
    assert native.rows() == []


def test_unknown_same_title_task_is_not_adopted(native):
    dispatcher = native.dispatcher()
    root_id = hashlib.sha256(str(native.root.resolve()).encode()).hexdigest()[:8]
    native.proxy.add(f"Doku-Delta root {root_id} {native.revision[:12]}",
        description=dispatcher._analysis_description("root", native.revision, ["docs/README.md"]),
        category="WORKER", assigned_to="BACH")
    with pytest.raises(RuntimeError, match="maintenance_provenance_unavailable"):
        dispatcher.dispatch()
    assert len(native.rows()) == 1
    assert registry.load_registry()["tasks"] == {}


def _failed_enrollment(native, monkeypatch):
    enroll = registry.enroll_maintenance_task_repository

    def fail(*_args, **_kwargs):
        raise registry.RepositoryBindingError("registry_busy", reason_code="registry_busy")

    monkeypatch.setattr(registry, "enroll_maintenance_task_repository", fail)
    with pytest.raises(RuntimeError, match="registry_busy"):
        native.dispatcher().dispatch()
    monkeypatch.setattr(registry, "enroll_maintenance_task_repository", enroll)
    return native.rows()[0]["id"]


def test_unbound_task_version_drift_is_visible_and_never_duplicates(native, monkeypatch):
    task_id = _failed_enrollment(native, monkeypatch)
    with sqlite3.connect(native.db) as conn:
        conn.execute("UPDATE tasks SET description=description||' edited' WHERE id=?", (task_id,))
    with pytest.raises(RuntimeError, match="maintenance_task_version_changed"):
        native.dispatcher().dispatch()
    assert len(native.rows()) == 1
    assert registry.load_registry()["tasks"] == {}


def test_bound_task_stays_complete_after_legitimate_task_edit(native):
    task_id = native.dispatcher().dispatch()["task_id"]
    before = registry.registry_path().read_bytes()
    with sqlite3.connect(native.db) as conn:
        conn.execute("UPDATE tasks SET description=description||' clarification' WHERE id=?", (task_id,))
    assert native.dispatcher().dispatch()["state"] == "idle"
    assert len(native.rows()) == 1
    assert registry.registry_path().read_bytes() == before


def test_source_main_drift_does_not_repin_or_duplicate_pending_operation(native, monkeypatch):
    from hub import worker_git
    task_id = _failed_enrollment(native, monkeypatch)
    (native.root / "docs/README.md").write_text("A newer integrated source\n")
    _git(native.root, "add", "docs/README.md")
    _git(native.root, "commit", "-m", "Newer source")
    newest = _git(native.root, "rev-parse", "HEAD")
    monkeypatch.setattr(worker_git, "_public_default_branch_metadata", lambda *_: {"source_sha": newest})
    dispatcher = native.dispatcher()
    dispatcher.snapshot = lambda *_: (newest, ["docs/README.md"])
    dispatcher.dispatch()
    assert len(native.rows()) == 1
    assert registry.resolve_task_repository(task_id).source_sha == native.revision
    state = json.loads(dispatcher.state_path.read_text())
    assert state["packages"]["root"]["revision"] == native.revision


def test_registry_publish_ack_loss_is_idempotent_on_restart(native, monkeypatch):
    publish = registry._RegistryWriter.publish

    def lose_ack(writer, value):
        publish(writer, value)
        raise RuntimeError("lost registry publish ACK")

    monkeypatch.setattr(registry._RegistryWriter, "publish", lose_ack)
    with pytest.raises(RuntimeError, match="lost registry publish ACK"):
        native.dispatcher().dispatch()
    before = registry.registry_path().read_bytes()
    monkeypatch.setattr(registry._RegistryWriter, "publish", publish)
    native.dispatcher().dispatch()
    assert len(native.rows()) == 1
    assert registry.registry_path().read_bytes() == before


def test_final_native_writer_rechecks_task_version(native, monkeypatch):
    from hub._services.docs import maintenance_task_provenance as provenance
    task_id = _failed_enrollment(native, monkeypatch)
    verify = provenance._verify_source
    calls = []

    def edit_after_source(*args, **kwargs):
        proof = verify(*args, **kwargs)
        calls.append(kwargs["require_current"])
        if len(calls) == 2:
            with sqlite3.connect(native.db) as conn:
                conn.execute("UPDATE tasks SET description=description||' concurrent edit' WHERE id=?",
                             (task_id,))
        return proof

    monkeypatch.setattr(provenance, "_verify_source", edit_after_source)
    with pytest.raises(RuntimeError, match="maintenance_task_version_changed"):
        native.dispatcher().dispatch()
    assert calls == [False, False]
    assert registry.load_registry()["tasks"] == {}
    assert len(native.rows()) == 1


def test_native_receipt_needs_matching_private_audit_event(native, monkeypatch):
    task_id = _failed_enrollment(native, monkeypatch)
    with sqlite3.connect(native.db) as conn:
        conn.execute("DELETE FROM task_history WHERE task_id=? AND action='maintenance_producer_create'",
                     (task_id,))
    with pytest.raises(RuntimeError, match="maintenance_provenance_unavailable"):
        native.dispatcher().dispatch()
    assert registry.load_registry()["tasks"] == {}


def test_conflicting_registry_binding_is_never_overwritten(native, monkeypatch):
    task_id = _failed_enrollment(native, monkeypatch)
    data = registry.load_registry()
    data["tasks"][str(task_id)] = {"repository": "ellmos-ai/bach", "source_sha": "f" * 40}
    registry.registry_path().write_text(json.dumps(data))
    before = registry.registry_path().read_bytes()
    with pytest.raises(RuntimeError, match="maintenance_binding_conflict"):
        native.dispatcher().dispatch()
    assert registry.registry_path().read_bytes() == before


def test_registry_cas_is_explicit_and_foreign_db_is_rejected(native, monkeypatch):
    from hub._services.task_lease_client import TaskLeaseClient
    task_id = _failed_enrollment(native, monkeypatch)
    before = registry.registry_path().read_bytes()
    with pytest.raises(RuntimeError, match="registry_changed"):
        registry.enroll_maintenance_task_repository(TaskLeaseClient(), task_id,
                                                    expected_registry_sha256=None)
    with pytest.raises(RuntimeError, match="Kanonischer lokaler Leadclient"):
        registry.enroll_maintenance_task_repository(TaskLeaseClient(db_path=native.root / "foreign.db"),
            task_id, expected_registry_sha256=hashlib.sha256(before).hexdigest())
    assert not (native.root / "foreign.db").exists()
    assert registry.registry_path().read_bytes() == before


def test_known_native_lock_blocks_before_task_or_marker_creation(native, monkeypatch):
    from hub._services.chat import worker_write_guard

    def locked(_):
        raise RuntimeError("native lock held")

    monkeypatch.setattr(worker_write_guard, "_scan_locks", locked)
    with pytest.raises(RuntimeError, match="Native Registry"):
        native.dispatcher().dispatch()
    assert native.rows() == []
    assert not registry.registry_path().with_name(registry.registry_path().name + ".operator-lock").exists()


def test_legacy_reference_requires_explicit_operator_enrollment(native):
    from hub._services.task_lease_client import TaskLeaseClient
    dispatcher = native.dispatcher()
    legacy = native.proxy.add("Existing verified maintenance inventory item", assigned_to="BACH",
                              category="WORKER", description="Operator checked old documentation task")
    dispatcher.state_path.parent.mkdir()
    dispatcher.state_path.write_text(json.dumps({"schema": "bach.docs-maintenance.v1",
        "packages": {"root": {"task_id": legacy["id"], "revision": native.revision}}}))
    with pytest.raises(RuntimeError, match="maintenance_legacy_enrollment_required"):
        dispatcher.dispatch()
    original = native.rows()[0]
    registry.enroll_task_repository(TaskLeaseClient(), legacy["id"], repository="ellmos-ai/bach",
        task_version=task_content_version(original), source_sha=native.revision,
        expected_registry_sha256=hashlib.sha256(registry.registry_path().read_bytes()).hexdigest(),
        operator="operator:fixture-maintenance-backfill")
    assert dispatcher.dispatch()["state"] == "idle"
    assert native.rows() == [original]


def test_routine_ack_loss_recovers_before_open_task_branch(native, monkeypatch):
    from hub._services.docs.maintenance_recurring import dispatch_routine
    definition = {"name": "roadmap_review", "legacy_title": "Legacy roadmap review",
                  "priority": "P2", "dispatch_marker": "legacy-marker"}
    scheduled_for = "2026-11-18T03:00:00+00:00"
    add = native.handler._add

    def lose_ack(*args, **kwargs):
        add(*args, **kwargs)
        raise RuntimeError("routine create ACK lost")

    monkeypatch.setattr(native.handler, "_add", lose_ack)
    with pytest.raises(RuntimeError, match="routine create ACK lost"):
        dispatch_routine(native.dispatcher(), definition, scheduled_for=scheduled_for)
    monkeypatch.setattr(native.handler, "_add", add)
    receipt = dispatch_routine(native.dispatcher(), definition, scheduled_for=scheduled_for)
    assert receipt["state"] == "waiting_review_or_work"
    assert len(native.rows()) == 1
    registry.resolve_task_repository(receipt["task_id"])


def test_private_create_parameter_cannot_be_supplied_as_public_metadata(native):
    with pytest.raises(RuntimeError, match="maintenance_provenance_unavailable"):
        native.handler._add(["Forged producer", "--creation-origin", "native-docs-maintenance"],
                            _maintenance_request={"producer": "native-docs-maintenance"})
    assert native.rows() == []


def test_worker_repository_gate_accepts_only_after_native_enrollment(native, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    task_id = _failed_enrollment(native, monkeypatch)
    slot = {"allowed_repositories": ["ellmos-ai/bach"]}
    row = native.rows()[0]
    assert WorkerLeaseBinding._repository_rejection_reason(row, slot) == "repository_unverified"
    native.dispatcher().dispatch()
    assert WorkerLeaseBinding._repository_rejection_reason(row, slot) is None
    assert WorkerLeaseBinding._repository_rejection_reason(
        row, {"allowed_repositories": ["ellmos-ai/open-ocean"]}) == "repository_not_allowed"


def test_create_hook_sees_committed_private_receipt(native, monkeypatch):
    from core.hooks import hooks
    observed = []

    def observe(event, data):
        if event == "after_task_create":
            observed.append((data["task_id"], native.rows("maintenance_task_intents")))

    monkeypatch.setattr(hooks, "emit", observe)
    task_id = native.dispatcher().dispatch()["task_id"]
    assert len(observed) == 1 and observed[0][0] == task_id
    assert observed[0][1][0]["task_id"] == task_id


def test_source_repository_mismatch_never_creates_a_task(native):
    _git(native.root, "remote", "set-url", "origin", "https://github.com/ellmos-ai/open-ocean")
    with pytest.raises(RuntimeError, match="maintenance_source_unverified"):
        native.dispatcher().dispatch()
    assert native.rows() == []


def test_unknown_registry_writer_cannot_be_taken_over(native, monkeypatch):
    _failed_enrollment(native, monkeypatch)
    marker = registry.registry_path().with_name(registry.registry_path().name + ".operator-lock")
    marker.write_text("other canonical writer")
    marker.chmod(0o600)
    with pytest.raises(RuntimeError, match="belegt"):
        native.dispatcher().dispatch()
    assert marker.read_text() == "other canonical writer"
    assert len(native.rows()) == 1
    assert registry.load_registry()["tasks"] == {}


def test_unbound_claimed_task_is_not_implicitly_changed(native, monkeypatch):
    from hub._services.task_lease import acquire_lease, LeaseConfig
    task_id = _failed_enrollment(native, monkeypatch)
    version = task_content_version(native.rows()[0])
    with sqlite3.connect(native.db) as conn:
        conn.row_factory = sqlite3.Row
        acquire_lease(conn, task_id, worker_id="fixture@other-host", host="other-host",
                      request_id="fixture-maintenance-lease-01", task_version=version,
                      config=LeaseConfig(creator_window_seconds=0))
    before = native.rows()
    assert before[0]["status"] == "in_progress" and before[0]["claim_id"]
    with pytest.raises(RuntimeError, match="maintenance_task_not_pending"):
        native.dispatcher().dispatch()
    assert native.rows() == before
    assert registry.load_registry()["tasks"] == {}


def test_task_edit_during_registry_publish_is_excluded_by_native_writer(native, monkeypatch):
    task_id = _failed_enrollment(native, monkeypatch)
    publish = registry._RegistryWriter.publish
    attempted = []

    def concurrent_edit(writer, value):
        with sqlite3.connect(native.db, timeout=0) as other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE tasks SET description='racing writer' WHERE id=?", (task_id,))
        attempted.append(True)
        publish(writer, value)

    monkeypatch.setattr(registry._RegistryWriter, "publish", concurrent_edit)
    native.dispatcher().dispatch()
    assert attempted == [True]
    assert native.rows()[0]["description"] != "racing writer"
    registry.resolve_task_repository(task_id)


def test_disappearing_canonical_database_is_never_recreated(native, monkeypatch):
    from hub._services.task_lease_client import TaskLeaseClient
    task_id = _failed_enrollment(native, monkeypatch)
    canonical = registry._canonical_review_client
    preserved = native.db.with_name("preserved.db")

    def lose_authority(client):
        answer = canonical(client)
        native.db.rename(preserved)
        return answer

    monkeypatch.setattr(registry, "_canonical_review_client", lose_authority)
    before = registry.registry_path().read_bytes()
    with pytest.raises(registry.RepositoryBindingError, match="canonical_lead_required"):
        registry.enroll_maintenance_task_repository(TaskLeaseClient(), task_id,
            expected_registry_sha256=hashlib.sha256(before).hexdigest())
    assert preserved.is_file()
    assert not native.db.exists()
    assert registry.registry_path().read_bytes() == before


def test_completed_edited_routine_allows_a_distinct_later_operation(native):
    from hub._services.docs.maintenance_recurring import dispatch_routine
    definition = {"name": "roadmap_review", "legacy_title": "Legacy roadmap review",
                  "priority": "P2", "dispatch_marker": "legacy-marker"}
    first = dispatch_routine(native.dispatcher(), definition, scheduled_for="2026-11-18T03:00:00Z")
    with sqlite3.connect(native.db) as conn:
        conn.execute("UPDATE tasks SET status='archived',description=description||' accepted clarification' "
                     "WHERE id=?", (first["task_id"],))
    # Equivalent native timestamp spelling is the same occurrence.
    replay = dispatch_routine(native.dispatcher(), definition,
                              scheduled_for="2026-11-18T03:00:00+00:00")
    assert replay["task_id"] == first["task_id"] and len(native.rows()) == 1
    later = dispatch_routine(native.dispatcher(), definition,
                             scheduled_for="2026-11-19T03:00:00+00:00")
    assert later["task_id"] != first["task_id"]
    assert len(native.rows()) == 2
    registry.resolve_task_repository(later["task_id"])


def _producer_request(native, **changes):
    return {"kind": "delta", "name": "root", "occurrence": native.revision,
            "revision": native.revision, "title": "Native producer request CAS",
            "description": "Original bounded analysis", "priority": "P2",
            "binding": {}, **changes}


@pytest.mark.parametrize("changes", [
    {"description": "Different requested analysis"},
    {"priority": "P1"},
    {"title": "Different requested title"},
    {"binding": {"assigned_slot": "buddha_always_on"}},
    {"binding": {"required_model": "fixture-model"}},
])
@pytest.mark.parametrize("bound", [False, True])
def test_same_operation_requires_same_request_before_any_enrollment(native, monkeypatch, changes, bound):
    owner = native.dispatcher().producer
    payload = _producer_request(native)
    enroll = registry.enroll_maintenance_task_repository
    if not bound:
        def busy(*_args, **_kwargs):
            raise registry.RepositoryBindingError("registry_busy", reason_code="registry_busy")

        monkeypatch.setattr(registry, "enroll_maintenance_task_repository", busy)
        with pytest.raises(RuntimeError, match="registry_busy"):
            owner.ensure(**payload)
        monkeypatch.setattr(registry, "enroll_maintenance_task_repository", enroll)
    else:
        owner.ensure(**payload)
    before = native.rows()
    registered = registry.registry_path().read_bytes()
    with pytest.raises(registry.RepositoryBindingError, match="maintenance_operation_conflict"):
        native.dispatcher().producer.ensure(**{**payload, **changes})
    assert native.rows() == before
    assert len(native.rows("maintenance_task_intents")) == 1
    assert registry.registry_path().read_bytes() == registered


def test_identical_request_replay_keeps_confirmed_pin_after_main_and_task_drift(native):
    owner = native.dispatcher().producer
    payload = _producer_request(native)
    task_id, action = owner.ensure(**payload)
    assert action == "created"
    with sqlite3.connect(native.db) as conn:
        conn.execute("UPDATE tasks SET description=description||' accepted clarification' WHERE id=?", (task_id,))
    (native.root / "docs/README.md").write_text("Later integrated root\n")
    _git(native.root, "add", "docs/README.md")
    _git(native.root, "commit", "-m", "Later integrated root")
    before = registry.registry_path().read_bytes()
    assert native.dispatcher().producer.ensure(**payload) == (task_id, "recovered")
    assert registry.registry_path().read_bytes() == before
    assert registry.resolve_task_repository(task_id).source_sha == native.revision
    assert len(native.rows()) == 1


@pytest.mark.parametrize("remote_available", [False, True])
def test_role_loss_cannot_route_private_request_to_federation_or_draft(native, monkeypatch, remote_available):
    from hub import task, rheingold
    from hub._services.docs import maintenance_task_provenance as producer
    permit = producer.check_create_request
    lookups, posts = [], []

    def change_role(request, args):
        permit(request, args)
        monkeypatch.delenv("BACH_RHEINGOLD_DISABLED", raising=False)
        monkeypatch.setattr(native.handler, "_canonical_db", native.db)
        monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "worker"})
        monkeypatch.setattr(task, "get_lead_config", lambda: {"mode": "worker"})

    def remote_url(**kwargs):
        lookups.append(True)
        return "https://fixture.invalid" if remote_available else None

    def post(url, payload):
        posts.append(payload)
        return True, {"id": 5991}

    monkeypatch.setattr(producer, "check_create_request", change_role)
    monkeypatch.setattr(task, "get_rheingold_url", remote_url)
    monkeypatch.setattr(task, "post_task_to_rheingold", post)
    with pytest.raises(registry.RepositoryBindingError):
        native.dispatcher().producer.ensure(**_producer_request(native))
    assert lookups == [] and posts == []
    assert native.rows() == []
    assert registry.load_registry()["tasks"] == {}


def test_role_loss_inside_native_create_rolls_back_task_and_receipt(native, monkeypatch):
    from hub import rheingold
    from hub._services.docs import maintenance_task_provenance as producer
    record = producer._record_intent

    def lose_role(conn, request, task_id):
        monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "worker"})
        return record(conn, request, task_id)

    monkeypatch.setattr(producer, "_record_intent", lose_role)
    with pytest.raises(registry.RepositoryBindingError, match="maintenance_provenance_unavailable"):
        native.dispatcher().producer.ensure(**_producer_request(native))
    assert native.rows() == []
    assert registry.load_registry()["tasks"] == {}


@pytest.mark.parametrize("change", ["head", "origin", "dirty", "native_fence"])
def test_new_task_rechecks_live_source_and_fences_after_external_proof(native, monkeypatch, change):
    from hub import worker_git
    owner = native.dispatcher().producer
    changed = []

    def guard(_):
        if changed and change == "native_fence":
            raise RuntimeError("native_root_fence_held")

    def metadata(*args):
        if not changed:
            if change in {"head", "dirty"}:
                (native.root / "docs/README.md").write_text("Changed during source attestation\n")
                if change == "head":
                    _git(native.root, "add", "docs/README.md")
                    _git(native.root, "commit", "-m", "Concurrent live source advancement")
            elif change == "origin":
                _git(native.root, "remote", "set-url", "origin", "https://github.com/ellmos-ai/open-ocean")
            changed.append(change)
        return {"source_sha": native.revision}

    owner.guard = guard
    monkeypatch.setattr(worker_git, "_public_default_branch_metadata", metadata)
    reason = "native_root_fence_held" if change == "native_fence" else "maintenance_source_unverified"
    with pytest.raises(RuntimeError, match=reason):
        owner.ensure(**_producer_request(native))
    assert changed == [change] and native.rows() == []
    assert registry.load_registry()["tasks"] == {}
