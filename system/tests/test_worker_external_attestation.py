# SPDX-License-Identifier: MIT
"""External receipts use real temporary lease/results, never live BACH data.

Git snapshots below are deterministic adapter inputs, not real Git acceptance.
The existing worker_write_guard suite separately exercises real worktrees.
"""
import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

from gui.device_auth import create_device, create_task_result_operator, revoke_device
from hub._services import worker_external_attestation as attestation
from hub._services import worker_external_evidence as evidence
from hub._services import worker_review_identity as identity
from hub._services.task_result_service import read_result
from hub._services.task_lease_client import TaskLeaseClient
from system.tests.test_task_lease_client import mem_db, _insert_task
from system.tests.test_worker_execution_evidence import worker_context, _new_binding, _submit
from system.tests.test_worker_external_evidence import register_model, register_sources, source
from system.tests.test_worker_scope_evidence import _review_submission, _scope_snapshot


@pytest.fixture
def external_world(worker_context, tmp_path, monkeypatch, request):
    context = worker_context
    if getattr(request, "param", {}).get("review_models"):
        from hub._services import worker_policy_settings as settings
        from system.tests.test_worker_result_review import (
            _binding, AUTHOR_ROUTE, AUTHOR_MODEL, AUTHOR_OBSERVED,
            REVIEW_ROUTE, REVIEW_MODEL, REVIEW_OBSERVED,
        )
        original = context["conn"]
        original.execute("CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        values = settings._defaults()
        values["policy"].update(default_mode="balanced", allow_review_task_pickup=True,
            github_external_review=False, reviewers=[
                {"reviewer_id": "model:shared", "tier": "standard"},
                {"reviewer_id": "model:reviewer", "tier": "top"}])
        settings.validate_policy(values["policy"])
        settings._persist(original, settings.GLOBAL_KEY, values, actor="external-integration-fixture")
        settings._persist(original, identity.KEY, [
            _binding("model:shared", AUTHOR_ROUTE, AUTHOR_MODEL, AUTHOR_OBSERVED),
            _binding("model:shared" if request.param.get("same_model_reviewer") else "model:reviewer",
                     REVIEW_ROUTE, REVIEW_MODEL, REVIEW_OBSERVED),
        ], actor="external-integration-fixture")
        original.commit()
    _review_submission(context, with_execution=False)
    original = context["conn"]
    original.execute("CREATE TABLE IF NOT EXISTS system_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    original.commit()
    token = create_task_result_operator("external-operator-fixture", connection=original)
    ordinary = create_device("ordinary-device-fixture", connection=original)
    path = tmp_path / "external-attestation.sqlite"
    conn = sqlite3.connect(path)
    original.backup(conn)
    conn.row_factory = sqlite3.Row
    authority = SimpleNamespace(path=path, operator=token)
    register_model(authority)
    register_sources(authority)
    view = read_result(conn, context["task_id"])
    record = view["result"]
    bound = evidence.resolve_external_principal(evidence.read_external_principals(path),
        source_id="source:luna", model_key="served-model-v1", model_label="fixture-model")
    result_file = evidence.store_external_artifact(record["result"].encode("utf-8"),
        media_type="text/plain", operator_token=token, db_path=path)
    proof = evidence.store_external_artifact(b'private source transcript fixture with model and run/turn',
        media_type="text/plain", operator_token=token, db_path=path)
    request = {**{key: record[key] for key in attestation._BINDING_FIELDS},
        "source_id": "source:luna", "model_key": "served-model-v1", "model_label": "fixture-model",
        "binding_sha256": bound["binding_sha256"], "run_id": "run-fixture", "turn_id": "turn-fixture",
        "source_artifact_ids": [proof["artifact_id"]], "result_artifact_id": result_file["artifact_id"],
        "source_reported_at": "2026-10-19T09:00:00+00:00",
        "verification_method": evidence.VERIFICATION_METHOD,
        "checked": {key: True for key in attestation._CHECKS}}
    calls = []

    def scope(task_id, **kwargs):
        assert conn.in_transaction is False
        calls.append((task_id, kwargs))
        return _scope_snapshot(task_id)

    monkeypatch.setattr(attestation, "snapshot_task_scope", scope)
    world = {"conn": conn, "path": path, "operator": token, "ordinary": ordinary,
             "task_id": context["task_id"], "request": request, "record": record,
             "authority": authority, "scope_calls": calls}
    yield world
    conn.close()


def capture(world, **kwargs):
    return attestation.attest_external_result(world["conn"], world["task_id"], world["request"],
        operator_token=world["operator"], **kwargs)


def read(world):
    record = read_result(world["conn"], world["task_id"])["result"]
    return attestation.read_external_attestation(world["conn"], record)


def objects(conn):
    return list(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name"))


def history_count(conn):
    return conn.execute("SELECT count(*) FROM task_history").fetchone()[0]


def test_capture_is_a_separate_event_backed_receipt_without_acceptance(external_world):
    world = external_world
    result = capture(world, repo_root="trusted-repo-override", worktrees_dir="trusted-trees-override")
    assert result["created"] is True
    assert result["availability"] == "recorded"
    assert result["source_kind"] == "external_attested"
    assert result["result_revision"] is None
    assert result["model_principal_id"] == "model:shared"
    assert datetime.fromisoformat(result["attested_at"]) > datetime.fromisoformat(result["source_reported_at"])
    assert world["scope_calls"] == [(world["task_id"], {
        "repo_root": "trusted-repo-override", "worktrees_dir": "trusted-trees-override"})]
    assert read(world) == {key: value for key, value in result.items() if key != "created"}
    conn = world["conn"]
    dto = read_result(conn, world["task_id"])
    assert dto["status"] == "review" and dto["result"]["accepted"] is False
    assert dto["result"]["execution"]["availability"] == "unavailable"
    assert dto["result"]["source_kind"] == "external_attested"
    assert dto["result"]["scope"]["availability"] == "recorded"
    assert dto["result"]["scope"]["schema"] == "bach.worker-external-scope-evidence.v1"
    assert conn.execute("SELECT claim_id FROM tasks WHERE id=?", (world["task_id"],)).fetchone()[0] is None
    assert not attestation._exists(conn, "worker_model_executions")
    events = list(conn.execute("SELECT action,changed_by FROM task_history WHERE id IN (?,?) ORDER BY id",
        (result["attestation_event_id"], result["scope_event_id"])))
    assert events[0][0] == "worker_external_result_attested" and events[0][1].startswith("operator-device:")
    assert tuple(events[1]) == ("worker_external_result_scope_capture", "external-scope-controller")


def test_public_projection_contains_no_private_artifact_or_account_run_data(external_world):
    world = external_world
    captured = capture(world)
    projected = attestation.project_external_attestation(captured)
    assert projected["availability"] == "available"
    assert projected["result_revision"] == attestation.external_result_revision(captured)
    rendered = json.dumps(projected)
    for private in ("source:luna", "tenant:fixture", "account:fixture", "agent:luna", "run-fixture",
                    "turn-fixture", "private source transcript", world["request"]["result_artifact_id"],
                    *world["request"]["source_artifact_ids"]):
        assert private not in rendered
    assert "execution_revision" not in projected and "execution_id" not in projected


def test_identical_current_replay_is_idempotent(external_world):
    world = external_world
    first = capture(world)
    before = history_count(world["conn"])
    again = capture(world)
    assert again == {**first, "created": False}
    assert history_count(world["conn"]) == before
    assert len(world["scope_calls"]) == 2


@pytest.mark.parametrize("field,value", [
    ("task_id", True), ("result_id", 0), ("fence", False), ("generation", "bad/generation"),
    ("task_version", "bad"), ("result_sha256", "bad"), ("submission_revision", "a" * 64),
    ("submission_event_id", 0), ("submitted_status_event_id", 0), ("status_revision", False),
    ("binding_sha256", "bad"), ("model_label", " label "), ("model_key", "https://model"),
    ("run_id", "file:///tmp/run"), ("turn_id", ""), ("source_artifact_ids", []),
    ("source_artifact_ids", ["a" * 32, "a" * 32]), ("result_artifact_id", "a" * 64),
    ("source_reported_at", "2026-10-19T09:00:00"), ("verification_method", "worker_self_report"),
    ("checked", {key: 1 for key in attestation._CHECKS}),
])
def test_strict_request_rejects_unknown_or_ambiguous_values(external_world, field, value):
    world = external_world
    payload = {**world["request"], field: value}
    with pytest.raises(ValueError):
        attestation.attest_external_result(world["conn"], world["task_id"], payload, operator_token=world["operator"])
    assert not world["scope_calls"]
    assert not attestation._exists(world["conn"], attestation._TABLE)


def test_client_cannot_supply_a_scope_or_attestation_time(external_world):
    world = external_world
    for extra in ("snapshot", "repo_root", "attested_at", "model_principal_id"):
        with pytest.raises(ValueError):
            attestation.attest_external_result(world["conn"], world["task_id"],
                {**world["request"], extra: "client-controlled"}, operator_token=world["operator"])
    assert not world["scope_calls"]


@pytest.mark.parametrize("credential", ["ordinary", "missing", "revoked"])
def test_capture_requires_current_enrolled_operator_before_observing_git(external_world, credential):
    world = external_world
    token = world["ordinary"] if credential == "ordinary" else None
    if credential == "revoked":
        revoke_device("external-operator-fixture", connection=world["conn"])
        token = world["operator"]
    before = objects(world["conn"])
    with pytest.raises(identity.IdentityPermissionDenied):
        attestation.attest_external_result(world["conn"], world["task_id"], world["request"], operator_token=token)
    assert objects(world["conn"]) == before and not world["scope_calls"]


@pytest.mark.parametrize("change", ["revoke", "task", "claim", "source", "artifact"])
def test_writer_rechecks_auth_cas_mapping_and_actual_bytes_after_git(external_world, monkeypatch, change):
    world = external_world
    conn = world["conn"]

    def changed(task_id, **kwargs):
        assert not conn.in_transaction
        if change == "revoke":
            revoke_device("external-operator-fixture", connection=conn)
        elif change == "task":
            conn.execute("UPDATE tasks SET description='Changed after observation' WHERE id=?", (task_id,))
        elif change == "claim":
            conn.execute("UPDATE tasks SET claim_id='new-claim-fixture' WHERE id=?", (task_id,))
        elif change == "source":
            register_sources(world["authority"], [source(model_labels=["changed-model"])])
        else:
            conn.execute("UPDATE worker_external_artifacts SET content=? WHERE artifact_id=?",
                         (b"corrupt fixture", world["request"]["source_artifact_ids"][0]))
        conn.commit()
        return _scope_snapshot(task_id)

    monkeypatch.setattr(attestation, "snapshot_task_scope", changed)
    with pytest.raises((identity.IdentityPermissionDenied, evidence.ExternalEvidenceConflict, evidence.ExternalEvidenceUnavailable)):
        capture(world)
    assert not attestation._exists(conn, attestation._TABLE)
    assert conn.execute("SELECT count(*) FROM task_history WHERE action LIKE 'worker_external_%'").fetchone()[0] == 0
    assert not conn.in_transaction


def test_source_proof_cannot_replace_the_exact_result_artifact(external_world):
    world = external_world
    artifact = evidence.store_external_artifact(b"Different result text", media_type="text/plain",
        operator_token=world["operator"], db_path=world["path"])
    world["request"]["result_artifact_id"] = artifact["artifact_id"]
    with pytest.raises(evidence.ExternalEvidenceConflict, match="vollständigen"):
        capture(world)
    assert not world["scope_calls"]


@pytest.mark.parametrize("problem", ["missing", "dirty", "wrong_task", "exception"])
def test_unavailable_or_wrong_scope_never_creates_receipts(external_world, monkeypatch, problem):
    world = external_world

    def scope(task_id, **kwargs):
        assert not world["conn"].in_transaction
        if problem == "exception":
            raise RuntimeError("scanner unavailable")
        if problem == "wrong_task":
            return _scope_snapshot(task_id + 1)
        return _scope_snapshot(task_id, availability="unavailable" if problem == "missing" else "available",
                               status_sha256="e" * 64)

    monkeypatch.setattr(attestation, "snapshot_task_scope", scope)
    with pytest.raises(evidence.ExternalEvidenceUnavailable):
        capture(world)
    assert not attestation._exists(world["conn"], attestation._TABLE)


def test_current_projection_and_replay_reject_changed_git(external_world, monkeypatch):
    world = external_world
    first = capture(world)
    monkeypatch.setattr(attestation, "snapshot_task_scope", lambda task_id, **kwargs:
        _scope_snapshot(task_id, head_oid="c" * 40))
    projected = attestation.project_external_attestation(first)
    assert projected["availability"] == "unavailable" and projected["result_revision"] is None
    assert projected["reason"] == "current_git_changed"
    with pytest.raises(evidence.ExternalEvidenceConflict):
        capture(world)


@pytest.mark.parametrize("change", ["attestation", "digest", "actor", "event_bool", "scope", "scope_digest",
                                   "event_order", "platform", "request", "artifact", "revoke", "mapping"])
def test_reader_revalidates_immutable_receipt_events_artifacts_and_authority(external_world, change):
    world = external_world
    first = capture(world)
    conn = world["conn"]
    if change == "actor":
        conn.execute("UPDATE task_history SET changed_by='worker:self' WHERE id=?", (first["attestation_event_id"],))
    elif change == "event_bool":
        event = conn.execute("SELECT new_value FROM task_history WHERE id=?", (first["attestation_event_id"],)).fetchone()
        detail = json.loads(event[0])
        detail["binding"]["fence"] = True
        conn.execute("UPDATE task_history SET new_value=? WHERE id=?",
                     (json.dumps(detail), first["attestation_event_id"]))
    elif change == "artifact":
        conn.execute("UPDATE worker_external_artifacts SET content=? WHERE artifact_id=?",
            (b"changed fixture", world["request"]["source_artifact_ids"][0]))
    elif change == "revoke":
        revoke_device("external-operator-fixture", connection=conn)
    elif change == "mapping":
        register_sources(world["authority"], [source(model_labels=["different-model"])])
    else:
        column, value = {
            "attestation": ("attestation", "{}"), "digest": ("attestation_sha256", "f" * 64),
            "scope": ("scope_receipt", "{}"), "scope_digest": ("scope_receipt_sha256", "f" * 64),
            "event_order": ("scope_event_id", first["attestation_event_id"]),
            "platform": ("platform_id", "another-platform"), "request": ("request", "{}"),
        }[change]
        conn.execute(f"UPDATE worker_external_attestations SET {column}=?", (value,))
    conn.commit()
    before = objects(conn)
    result = read(world)
    assert result["availability"] == "unavailable" and result["result_revision"] is None
    assert objects(conn) == before and not conn.in_transaction


def test_read_without_ledger_is_pure_and_does_not_initialize_schema(external_world):
    world = external_world
    before = objects(world["conn"])
    assert read(world)["reason"] == "external_attestation_not_recorded"
    assert objects(world["conn"]) == before


def test_different_second_attestation_for_same_result_is_conflict(external_world):
    world = external_world
    capture(world)
    before = history_count(world["conn"])
    world["request"]["turn_id"] = "another-turn"
    with pytest.raises(evidence.ExternalEvidenceConflict):
        capture(world)
    assert history_count(world["conn"]) == before


def test_run_turn_is_unique_across_tasks_and_rollback_removes_attempt_events(external_world):
    world = external_world
    capture(world)
    conn = world["conn"]
    task_id = _insert_task(conn, "Another external task")
    binding, _, _ = _new_binding(TaskLeaseClient(conn=conn), task_id, generation="another-generation")
    _submit(binding, task_id)
    record = read_result(conn, task_id)["result"]
    request = {**world["request"], **{key: record[key] for key in attestation._BINDING_FIELDS}}
    before = history_count(conn)
    with pytest.raises(evidence.ExternalEvidenceConflict, match="bereits"):
        attestation.attest_external_result(conn, task_id, request, operator_token=world["operator"])
    assert history_count(conn) == before
    assert conn.execute("SELECT count(*) FROM worker_external_attestations").fetchone()[0] == 1
    assert read_result(conn, task_id)["status"] == "review"


def test_unrelated_identity_edit_preserves_the_attested_model_binding(external_world):
    world = external_world
    first = capture(world)
    register_sources(world["authority"], [source(), source(source_id="other-source", account_id="other-account",
                                                          source_principal_id="other-agent")])
    assert attestation.external_result_revision(read(world)) == attestation.external_result_revision(first)


def test_corrupt_global_catalog_disables_the_reader_without_creating_schema(external_world):
    world = external_world
    capture(world)
    conn = world["conn"]
    conn.execute("UPDATE system_config SET value='invalid-json' WHERE key=?", (identity.CATALOG_KEY,))
    conn.commit()
    before = objects(conn)
    assert read(world)["availability"] == "unavailable"
    assert objects(conn) == before


def test_native_execution_cannot_be_replaced_even_if_its_receipt_is_corrupt(external_world):
    world = external_world
    conn = world["conn"]
    from hub._services.worker_execution_evidence import _ensure_schema
    _ensure_schema(conn)
    conn.execute("INSERT INTO worker_model_executions "
        "(id,task_id,fence,generation,phase,receipt,receipt_sha256,started_event_id,result_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)", ("corrupt-native-fixture", world["task_id"], world["record"]["fence"],
        world["record"]["generation"], "returned", "{}", "a" * 64, 1, world["record"]["result_id"]))
    conn.commit()
    with pytest.raises(evidence.ExternalEvidenceConflict, match="Native"):
        capture(world)
    assert read(world)["reason"] == "native_execution_present"
    assert not world["scope_calls"]
