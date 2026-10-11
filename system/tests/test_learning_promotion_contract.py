"""Real isolated stores: inactive drafts, explicit review, collision and use gates."""
import sqlite3
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hub._services.hermes_distillation_service import HermesDistillationService
from hub._services.nemofold_workflow_service import NemoFoldWorkflowService
from hub._services.chat.sequence_store import SequenceConflict, SequenceStore
from hub._services.learning_review_service import LearningConflict, LearningPromotionUnavailable


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "learning.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
    return path


def count(database, table, where="1"):
    with sqlite3.connect(database) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def nemo_candidate(service, status="certified", name="learned-chain"):
    return service.store_candidate({
        "name": name,
        "title": "Unveröffentlichter Ablauf",
        "steps": [{"step_index": 1, "name": "Prüfen", "agent": "worker-test"}],
        "tuv_status": status,
        "tuv_report": {"rating": "A+", "has_test_gate": True},
        "provenance": {"source": "isolated regression"},
    })


def hermes_candidate(service):
    result = service.run_pipeline(
        "Merke: Always test before commit. Best Practice: Run ruff check.",
        session_id="isolated-regression",
        skill_name_hint="reviewed-lesson",
    )
    assert result.candidate and result.lessons
    return result


def binding(service, candidate_id, request_id="review-regression-0001"):
    candidate = service.get_candidate(candidate_id)
    return {"expected_revision": candidate["candidate_revision"],
            "expected_digest": candidate["candidate_digest"], "request_id": request_id}


def native_definition(name="existing-chain"):
    return {
        "name": name,
        "title": "Vorhandene native Kette",
        "description": "Nicht durch Lernen überschreiben",
        "mode": "agents",
        "steps": [{
            "label": "Prüfen",
            "agent_slot": "worker-test",
            "skill_ids": [],
            "instructions": "Führe die freigegebene Aufgabe aus.",
        }],
    }


def test_hermes_drafts_are_not_active_memory(database):
    service = HermesDistillationService(database)
    result = hermes_candidate(service)
    assert all(lesson["is_active"] == 0 for lesson in result.lessons)
    assert count(database, "memory_lessons") == 0
    assert service.get_candidate(result.candidate["id"])["lessons_draft"] == result.lessons
    assert service.get_candidate(result.candidate["id"])["status"] == "pending"


def test_hermes_rejected_candidate_cannot_be_promoted(database):
    service = HermesDistillationService(database)
    result = hermes_candidate(service)
    candidate_id = result.candidate["id"]
    service.reject_candidate(candidate_id, reason="Ungeprüft", **binding(service, candidate_id))
    try:
        reply = service.approve_candidate(candidate_id, approved_by="operator")
    except (ValueError, RuntimeError):
        pass
    else:
        assert reply["status"] != "approved"
    assert service.get_candidate(candidate_id)["status"] == "rejected"
    assert count(database, "skill_versions") == 0
    assert count(database, "memory_lessons", "is_active = 1") == 0


def test_nemofold_rejected_candidate_cannot_be_promoted(database):
    service = NemoFoldWorkflowService(str(database))
    candidate_id = nemo_candidate(service)
    service.reject_candidate(candidate_id, reason="Keine Freigabe", **binding(service, candidate_id))
    with pytest.raises((ValueError, RuntimeError)):
        service.approve_candidate(candidate_id, operator="operator")
    assert service.get_candidate(candidate_id)["status"] == "rejected"
    assert count(database, "marblerun_chains") == 0


@pytest.mark.parametrize("gate", ["rejected", "needs_review"])
def test_nemofold_blocked_metadata_gate_does_not_activate(database, gate):
    service = NemoFoldWorkflowService(str(database))
    candidate_id = nemo_candidate(service, status=gate)
    with pytest.raises((ValueError, RuntimeError)):
        service.approve_candidate(candidate_id, operator="operator")
    assert count(database, "marblerun_chains") == 0
    assert service.get_candidate(candidate_id)["status"] == "pending"


def test_static_tuv_claim_is_not_review_evidence(database):
    service = NemoFoldWorkflowService(str(database))
    candidate_id = nemo_candidate(service)
    with pytest.raises((ValueError, RuntimeError)):
        service.approve_candidate(candidate_id, operator="operator", notes="A+ im Quelltext")
    assert count(database, "marblerun_chains") == 0


def test_learning_never_silently_overwrites_existing_native_chain(database):
    store = SequenceStore(database)
    existing = store.save_chain(native_definition())
    service = NemoFoldWorkflowService(str(database))
    candidate_id = nemo_candidate(service, name=existing["name"])
    with pytest.raises((ValueError, RuntimeError)):
        service.approve_candidate(candidate_id, operator="operator")
    assert store.chain(existing["id"]) == existing


def test_inactive_chain_cannot_create_native_run(database):
    store = SequenceStore(database)
    chain = store.save_chain(native_definition())
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE marblerun_chains SET is_active=0 WHERE id=?", (chain["id"],))
    with pytest.raises(SequenceConflict):
        store.create_run(
            "isolated-inactive-run", chain["id"], chain["version"], "a" * 64,
            "b" * 32, "c" * 40, {"input": "Prüfe"},
        )
    assert count(database, "native_sequence_runs") == 0


def test_active_chain_still_creates_native_run(database):
    store = SequenceStore(database)
    chain = store.save_chain(native_definition())
    assert store.create_run(
        "isolated-active-run", chain["id"], chain["version"], "a" * 64,
        "b" * 32, "c" * 40, {"input": "Prüfe"},
    )
    assert count(database, "native_sequence_runs") == 1


@pytest.fixture(params=["hermes", "nemofold"])
def candidate_case(request, database):
    if request.param == "hermes":
        service = HermesDistillationService(database)
        candidate_id = hermes_candidate(service).candidate["id"]
    else:
        service = NemoFoldWorkflowService(str(database))
        candidate_id = nemo_candidate(service)
    return request.param, service, candidate_id


def test_bound_content_review_is_idempotent_and_publishes_nothing(candidate_case, database):
    _, service, candidate_id = candidate_case
    kwargs = binding(service, candidate_id)
    first = service.review_candidate(candidate_id, actor="device:7", notes="Inhalt gelesen", **kwargs)
    second = service.review_candidate(candidate_id, actor="device:7", notes="Inhalt gelesen", **kwargs)
    assert first["status"] == "reviewed"
    assert {**first, "replayed": True} == second
    assert first["review_scope"] == "candidate_content_only"
    assert first["empirically_validated"] is False
    assert first["targets_published"] is False
    assert service.get_candidate(candidate_id)["status"] == "reviewed"
    assert count(database, "learning_candidate_reviews") == 1
    assert count(database, "memory_lessons") == 0
    assert count(database, "skill_versions") == 0
    assert count(database, "marblerun_chains") == 0
    with pytest.raises(LearningPromotionUnavailable):
        service.approve_candidate(candidate_id)


def test_review_rejects_wrong_revision_digest_and_reused_request(candidate_case, database):
    _, service, candidate_id = candidate_case
    kwargs = binding(service, candidate_id)
    for change in ({"expected_revision": 99}, {"expected_digest": "0" * 64}):
        with pytest.raises(LearningConflict):
            service.review_candidate(candidate_id, actor="device:7", notes="Gelesen", **{**kwargs, **change})
    assert count(database, "learning_candidate_reviews") == 0
    service.review_candidate(candidate_id, actor="device:7", notes="Gelesen", **kwargs)
    with pytest.raises(LearningConflict):
        service.review_candidate(candidate_id, actor="device:7", notes="Anderer Auftrag", **kwargs)
    assert count(database, "learning_candidate_reviews") == 1


def test_review_rolls_back_if_receipt_write_fails(candidate_case, database):
    _, service, candidate_id = candidate_case
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TRIGGER reject_review_receipt BEFORE INSERT ON learning_candidate_reviews
            BEGIN SELECT RAISE(ABORT, 'isolated receipt fault'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="receipt fault"):
        service.review_candidate(candidate_id, actor="device:7", notes="Gelesen", **binding(service, candidate_id))
    assert service.get_candidate(candidate_id)["status"] == "pending"
    assert count(database, "learning_candidate_reviews") == 0


def test_rejection_is_bound_terminal_and_idempotent(candidate_case, database):
    _, service, candidate_id = candidate_case
    with pytest.raises(ValueError, match="revision"):
        service.reject_candidate(candidate_id, reason="Keine Bindung")
    kwargs = binding(service, candidate_id)
    first = service.reject_candidate(candidate_id, actor="device:7", reason="Keine Evidenz", **kwargs)
    second = service.reject_candidate(candidate_id, actor="device:7", reason="Keine Evidenz", **kwargs)
    assert {**first, "replayed": True} == second
    with pytest.raises(LearningConflict):
        service.review_candidate(candidate_id, actor="device:7", notes="Neues Review",
            **{**kwargs, "request_id": "other-review-request"})
    assert service.get_candidate(candidate_id)["status"] == "rejected"
    assert count(database, "learning_candidate_reviews") == 1


def test_nemo_changed_proposal_invalidates_review_and_returns_correct_id(database):
    service = NemoFoldWorkflowService(str(database))
    candidate_id = nemo_candidate(service)
    kwargs = binding(service, candidate_id)
    service.review_candidate(candidate_id, actor="device:7", notes="Version 1 gelesen", **kwargs)
    # An unrelated last insertion must not be mistaken for this upsert's ID.
    nemo_candidate(service, name="unrelated-candidate")
    assert nemo_candidate(service) == candidate_id
    assert service.get_candidate(candidate_id)["status"] == "reviewed"
    assert nemo_candidate(service, status="needs_review") == candidate_id
    current = service.get_candidate(candidate_id)
    assert current["candidate_revision"] == 2
    assert current["status"] == "pending"
    historic = service.review_candidate(candidate_id, actor="device:7", notes="Version 1 gelesen", **kwargs)
    assert historic["replayed"] is True
    assert historic["candidate_revision"] == 1
    assert service.get_candidate(candidate_id)["status"] == "pending"
    with pytest.raises(LearningConflict):
        service.review_candidate(candidate_id, actor="device:7", notes="Alte Ansicht",
            **{**kwargs, "request_id": "stale-review-request"})
    assert count(database, "learning_candidate_reviews") == 1


def test_nemo_preserves_historical_published_proposal(database):
    service = NemoFoldWorkflowService(str(database))
    candidate_id = nemo_candidate(service)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE nemofold_workflow_candidates SET status='approved',promoted_to_chain_id=123 WHERE id=?",
            (candidate_id,))
    before = service.get_candidate(candidate_id)
    with pytest.raises(LearningConflict):
        nemo_candidate(service, status="needs_review")
    assert service.get_candidate(candidate_id) == before


def test_nemo_integer_confidence_has_stable_database_binding(database):
    service = NemoFoldWorkflowService(str(database))
    proposal = {"name": "integer-confidence", "steps": [], "confidence_score": 1}
    candidate_id = service.store_candidate(proposal)
    candidate = service.get_candidate(candidate_id)
    assert candidate["review_available"] is True
    assert service.store_candidate({**proposal, "confidence_score": 1.0}) == candidate_id
    assert service.get_candidate(candidate_id)["candidate_revision"] == 1
    assert service.review_candidate(candidate_id, actor="device:7", notes="Gelesen",
        **binding(service, candidate_id))["status"] == "reviewed"


@pytest.mark.parametrize("confidence", [True, "0.8", float("nan"), float("inf"), -1, 1.1])
def test_nemo_invalid_confidence_does_not_store_proposal(database, confidence):
    service = NemoFoldWorkflowService(str(database))
    with pytest.raises(ValueError, match="Konfidenz"):
        service.store_candidate({"name": "invalid-confidence", "confidence_score": confidence})
    assert service.list_candidates() == []


@pytest.mark.parametrize("field", ["name", "title", "description", "trigger_type", "tuv_status"])
def test_nemo_does_not_bind_numbers_as_sqlite_text(database, field):
    service = NemoFoldWorkflowService(str(database))
    with pytest.raises(ValueError, match="muss Text sein"):
        service.store_candidate({"name": "bad-text-affinity", field: 1})
    assert service.list_candidates() == []


def test_candidate_tampering_and_legacy_rows_are_not_reviewable(candidate_case, database):
    provider, service, candidate_id = candidate_case
    table = "hermes_skill_candidates" if provider == "hermes" else "nemofold_workflow_candidates"
    column = "content" if provider == "hermes" else "description"
    kwargs = binding(service, candidate_id)
    with sqlite3.connect(database) as conn:
        conn.execute(f"UPDATE {table} SET {column}='Ungebundener Inhalt' WHERE id=?", (candidate_id,))
    assert service.get_candidate(candidate_id)["review_available"] is False
    with pytest.raises(LearningConflict):
        service.review_candidate(candidate_id, actor="device:7", notes="Gelesen", **kwargs)
    with sqlite3.connect(database) as conn:
        conn.execute(f"UPDATE {table} SET candidate_revision=0,status='approved' WHERE id=?", (candidate_id,))
    current = service.get_candidate(candidate_id)
    assert current["status"] == "approved"  # Historical information remains intact.
    assert current["review_state"] == "legacy_unverified"
    assert current["promotion_available"] is False


@pytest.mark.parametrize("identical_request", [True, False])
def test_concurrent_decisions_use_one_bound_receipt(candidate_case, database, identical_request):
    _, service, candidate_id = candidate_case
    kwargs = binding(service, candidate_id)
    barrier = threading.Barrier(2)
    def decide(index):
        barrier.wait(timeout=5)
        selected = kwargs if identical_request else {**kwargs, "request_id": f"race-review-{index:04}"}
        try:
            return service.review_candidate(candidate_id, actor="device:7", notes="Gelesen", **selected)
        except LearningConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(decide, [1, 2]))
    assert count(database, "learning_candidate_reviews") == 1
    if identical_request:
        assert sorted(reply["replayed"] for reply in replies) == [False, True]
    else:
        assert replies.count("conflict") == 1
    assert service.get_candidate(candidate_id)["status"] == "reviewed"


def test_concurrent_initial_schema_migrations_are_serialized(database):
    barrier = threading.Barrier(2)
    def initialize(_):
        barrier.wait(timeout=5)
        service = HermesDistillationService(database)
        service.ensure_schema()
        return service.list_candidates(status="all")
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(initialize, [1, 2])) == [[], []]
    with sqlite3.connect(database) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(hermes_skill_candidates)")]
    assert columns.count("candidate_revision") == 1


def test_authenticated_api_review_reject_and_unavailable_promotion(candidate_case, database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gui.api import unified_api

    provider, service, candidate_id = candidate_case
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')",
            (hashlib.sha256(b"isolated-test-token").hexdigest(),))
    monkeypatch.setattr(unified_api, "BACH_DB", database)
    calls = []
    def service_factory():
        calls.append(True)
        return service
    monkeypatch.setattr(unified_api, f"_get_{provider}_service_instance", service_factory)
    app = FastAPI()
    app.include_router(unified_api.router)
    client = TestClient(app)
    prefix = f"/api/learning/{provider}/candidates/{candidate_id}"
    headers = {"Authorization": "Bearer isolated-test-token"}
    kwargs = binding(service, candidate_id)
    assert client.post(prefix + "/review", json={**kwargs, "notes": "Gelesen"}).status_code == 401
    assert calls == []  # Reject before a constructor can perform schema DDL.
    assert client.post(prefix + "/review", headers=headers,
        json={**kwargs, "notes": "Gelesen", "approved_by": "forged-operator"}).status_code == 422
    response = client.post(prefix + "/review", headers=headers, json={**kwargs, "notes": "Gelesen"})
    assert response.status_code == 200
    assert response.json()["actor"] == "device:7"
    assert response.json()["targets_published"] is False
    unavailable = client.post(prefix + "/approve", headers=headers, json={"approved_by": "operator"})
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "native_learning_promotion_unavailable"
    assert client.post(f"/api/learning/{provider}/candidates/99999/approve",
        headers=headers, json={}).status_code == 404
    if provider == "hermes":
        other_id = hermes_candidate(service).candidate["id"]
    else:
        other_id = nemo_candidate(service, name="another-candidate")
    other_prefix = f"/api/learning/{provider}/candidates/{other_id}"
    other_kwargs = binding(service, other_id, request_id="other-reject-request")
    assert client.post(other_prefix + "/reject", headers=headers, json={"reason": "Ohne Bindung"}).status_code == 422
    rejection = client.post(other_prefix + "/reject", headers=headers,
        json={**other_kwargs, "reason": "Keine Evidenz"})
    assert rejection.status_code == 200
    assert rejection.json()["status"] == "rejected"
    assert rejection.json()["actor"] == "device:7"
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE devices SET status='revoked'")
    previous_calls = len(calls)
    assert client.post(prefix + "/review", headers=headers,
        json={**kwargs, "notes": "Gelesen"}).status_code == 403
    assert len(calls) == previous_calls
    assert count(database, "learning_candidate_reviews") == 2
