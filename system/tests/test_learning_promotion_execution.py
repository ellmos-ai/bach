"""Target-specific native promotion, CAS, replay, recovery and revoke."""
import hashlib
import json
import sqlite3

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gui.api import unified_api
from hub._services.chat.sequence_store import SequenceConflict, SequenceStore
from hub._services.hermes_distillation_service import HermesDistillationService
from hub._services.learning_promotion_service import (
    LearningPromotionConflict,
    LearningPromotionService,
    LearningPromotionUnavailable,
)
from hub._services.nemofold_workflow_service import NemoFoldWorkflowService
from hub._services import skill_source_service


TOKEN = "isolated-learning-promotion-token"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "learning.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
        conn.commit()
    return path


def row_count(database, table, where="1"):
    with sqlite3.connect(database) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def review_binding(candidate, request_id):
    return {
        "expected_revision": candidate["candidate_revision"],
        "expected_digest": candidate["candidate_digest"],
        "request_id": request_id,
    }


def hermes_reviewed(database, *, skill_name="reviewed-learning", text=None):
    source = HermesDistillationService(database)
    result = source.run_pipeline(
        text or "Merke: Always verify before commit. Best Practice: Keep changes scoped.",
        session_id="isolated-promotion",
        skill_name_hint=skill_name,
    )
    candidate = source.get_candidate(result.candidate["id"])
    receipt = source.review_candidate(
        candidate["id"],
        actor="device:7",
        notes="Inhalt separat geprüft.",
        **review_binding(candidate, "hermes-review-0001"),
    )
    assert receipt["status"] == "reviewed"
    return source, source.get_candidate(candidate["id"])


def nemo_reviewed(database, *, name="learned-native-chain"):
    source = NemoFoldWorkflowService(str(database))
    candidate_id = source.store_candidate({
        "name": name,
        "title": "Unveröffentlichter Ablauf",
        "description": "Testkandidat",
        "steps": [{"step_index": 1, "name": "Prüfen", "agent": "worker-test"}],
        "tuv_status": "certified",
        "tuv_report": {"rating": "A+", "has_test_gate": True},
        "provenance": {"source": "isolated regression"},
    })
    candidate = source.get_candidate(candidate_id)
    receipt = source.review_candidate(
        candidate_id,
        actor="device:7",
        notes="Inhalt separat geprüft.",
        **review_binding(candidate, "nemo-review-0001"),
    )
    assert receipt["status"] == "reviewed"
    return source, source.get_candidate(candidate_id)


def sequence_proposal(candidate, *, name=None, config_version="cfg-v1"):
    chain_name = name or candidate["chain_name"]
    return {
        "schema": "bach.learning.native-sequence.v1",
        "source": {
            "provider": "nemofold",
            "candidate_id": candidate["id"],
            "candidate_revision": candidate["candidate_revision"],
            "candidate_digest": candidate["candidate_digest"],
        },
        "definition": {
            "name": chain_name,
            "title": "Geprüfte native Lernkette",
            "description": "Aus einem gebundenen, geprüften Kandidaten übersetzt.",
            "mode": "agents",
            "agent_slot": "",
            "steps": [{
                "label": "Prüfen",
                "agent_slot": "worker-test",
                "skill_ids": [],
                "instructions": "Führe den nativen, geprüften Schritt aus.",
            }],
        },
        "resolved": {
            "config_version": config_version,
            "agent_slots": [{"id": "worker-test", "config_version": "slot-v1"}],
            "skills": [],
        },
    }


def promotion_service(database, *, root=None, skill_roots=None, adapter=None, sequence_store=None, after_skill_write=None):
    return LearningPromotionService(
        database,
        write_root=root,
        skill_roots=skill_roots if skill_roots is not None else ([root] if root else None),
        write_guard=lambda _path: None,
        sequence_adapter=adapter,
        sequence_store=sequence_store,
        after_skill_write=after_skill_write,
    )


def test_hermes_skill_promotion_recovers_after_file_write_and_replays(database, tmp_path):
    _, candidate = hermes_reviewed(database)
    root = tmp_path / "skills"
    root.mkdir()
    crashes = [0]

    def fail_once():
        crashes[0] += 1
        if crashes[0] == 1:
            raise RuntimeError("simulated process interruption after target write")

    service = promotion_service(database, root=root, after_skill_write=fail_once)
    kwargs = dict(
        target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="skill-promote-0001",
        expected_target_version="0",
        actor="device:7",
    )
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        service.promote("hermes", candidate["id"], **kwargs)

    skill_id = candidate["name"]
    skill_file = root / skill_id / "SKILL.md"
    assert skill_file.is_file()
    target_hash = hashlib.sha256(skill_file.read_bytes()).hexdigest()
    with sqlite3.connect(database) as conn:
        payload = json.loads(conn.execute(
            "SELECT target_payload_json FROM learning_promotions WHERE request_id=?",
            (kwargs["request_id"],),
        ).fetchone()[0])
    assert payload["target_source_binding"] == {
        "source_kind": "local_override",
        "source_root": str(root.resolve()),
        "relative_path": f"{skill_id}/SKILL.md",
        "source_version": target_hash,
    }
    recovered = service.promote("hermes", candidate["id"], **kwargs)
    assert recovered["status"] == "published"
    assert recovered["target_version"] == target_hash
    assert recovered["recovered_after_target_write"] is True
    assert row_count(database, "learning_promotions", "state='published'") == 1

    replay = service.promote("hermes", candidate["id"], **kwargs)
    assert replay["replayed"] is True
    assert row_count(database, "learning_promotions", "state='published'") == 1

    revoked = service.revoke(
        "hermes", candidate["id"], target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="skill-promote-0001",
        request_id="skill-revoke-0001",
        actor="device:7",
    )
    assert revoked["status"] == "reverted"
    assert revoked["targets_revoked"] is True
    assert not skill_file.exists()
    assert service.target_states("hermes", candidate)["targets"]["skill"]["state"] == "reverted"


def test_skill_recovery_rejects_same_desired_hash_in_new_write_root(database, tmp_path):
    _, candidate = hermes_reviewed(database, skill_name="root-bound-recovery")
    root_a = tmp_path / "skills-a"
    root_b = tmp_path / "skills-b"
    root_a.mkdir()
    root_b.mkdir()
    crashes = [0]

    def fail_after_write():
        crashes[0] += 1
        if crashes[0] == 1:
            raise RuntimeError("simulated interruption after pinned-root write")

    service = promotion_service(
        database, root=root_a, skill_roots=[root_a, root_b], after_skill_write=fail_after_write
    )
    kwargs = dict(
        target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="root-switch-resume-001",
        expected_target_version="0",
        actor="device:7",
    )
    with pytest.raises(RuntimeError, match="simulated interruption"):
        service.promote("hermes", candidate["id"], **kwargs)

    skill_id = candidate["name"]
    file_a = root_a / skill_id / "SKILL.md"
    file_b = root_b / skill_id / "SKILL.md"
    bytes_a = file_a.read_bytes()
    file_b.parent.mkdir(parents=True)
    file_b.write_bytes(bytes_a)
    before_a = hashlib.sha256(file_a.read_bytes()).hexdigest()
    before_b = hashlib.sha256(file_b.read_bytes()).hexdigest()
    assert before_a == before_b

    service.write_root = root_b
    with pytest.raises(LearningPromotionConflict, match="Write-Root"):
        service.promote("hermes", candidate["id"], **kwargs)

    assert hashlib.sha256(file_a.read_bytes()).hexdigest() == before_a
    assert hashlib.sha256(file_b.read_bytes()).hexdigest() == before_b
    assert row_count(
        database, "learning_promotions",
        "request_id='root-switch-resume-001' AND state='conflict'",
    ) == 1


def test_skill_revoke_does_not_delete_matching_hash_in_new_write_root(database, tmp_path):
    _, candidate = hermes_reviewed(database, skill_name="root-bound-revoke")
    root_a = tmp_path / "skills-a"
    root_b = tmp_path / "skills-b"
    root_a.mkdir()
    root_b.mkdir()
    service = promotion_service(database, root=root_a, skill_roots=[root_a, root_b])
    published = service.promote(
        "hermes", candidate["id"], target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="root-switch-publish-01",
        expected_target_version="0",
        actor="device:7",
    )

    skill_id = candidate["name"]
    file_a = root_a / skill_id / "SKILL.md"
    file_b = root_b / skill_id / "SKILL.md"
    bytes_a = file_a.read_bytes()
    assert hashlib.sha256(bytes_a).hexdigest() == published["target_sha256"]
    file_b.parent.mkdir(parents=True)
    file_b.write_bytes(bytes_a)
    before_a = hashlib.sha256(file_a.read_bytes()).hexdigest()
    before_b = hashlib.sha256(file_b.read_bytes()).hexdigest()

    service.write_root = root_b
    with pytest.raises(LearningPromotionConflict, match="Ziel-Root"):
        service.revoke(
            "hermes", candidate["id"], target_kind="skill",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            source_request_id="root-switch-publish-01",
            request_id="root-switch-revoke-01",
            actor="device:7",
        )

    assert hashlib.sha256(file_a.read_bytes()).hexdigest() == before_a
    assert hashlib.sha256(file_b.read_bytes()).hexdigest() == before_b
    assert row_count(
        database, "learning_promotions",
        "request_id='root-switch-revoke-01' AND state='conflict'",
    ) == 1


def test_hermes_skill_revoke_restores_prior_target_and_refuses_changed_target(database, tmp_path):
    _, candidate = hermes_reviewed(database, skill_name="restorable-learning")
    root = tmp_path / "skills"
    skill_id = candidate["name"]
    skill_file = root / skill_id / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    old_content = (
        f"---\nname: {skill_id}\nversion: '1.0'\ncategory: test\ndescription: Vorherige Fassung\n---\n"
        "Vorheriger Inhalt.\n"
    )
    skill_file.write_text(old_content, encoding="utf-8")
    service = promotion_service(database, root=root)
    current = service._skill_version(skill_id)
    published = service.promote(
        "hermes", candidate["id"],
        target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="skill-restore-0001",
        expected_target_version=current,
        actor="device:7",
    )
    assert published["status"] == "published"
    revoked = service.revoke(
        "hermes", candidate["id"], target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="skill-restore-0001",
        request_id="skill-restore-revoke-01",
        actor="device:7",
    )
    assert revoked["status"] == "reverted"
    assert skill_file.read_text(encoding="utf-8") == old_content
    assert service._skill_version(skill_id) == current

    again = service.promote(
        "hermes", candidate["id"],
        target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="skill-restore-0002",
        expected_target_version=current,
        actor="device:7",
    )
    assert again["status"] == "published"
    skill_file.write_text("external change\n", encoding="utf-8")
    with pytest.raises(LearningPromotionConflict, match="verändert"):
        service.revoke(
            "hermes", candidate["id"], target_kind="skill",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            source_request_id="skill-restore-0002",
            request_id="skill-restore-revoke-02",
            actor="device:7",
        )
    assert skill_file.read_text(encoding="utf-8") == "external change\n"


def test_skill_revoke_removes_local_override_and_restores_unchanged_factory_source(database, tmp_path):
    _, candidate = hermes_reviewed(database, skill_name="factory-learning")
    local_root = tmp_path / "local-skills"
    factory_root = tmp_path / "factory-skills"
    factory_file = factory_root / candidate["name"] / "SKILL.md"
    factory_file.parent.mkdir(parents=True)
    local_root.mkdir()
    factory_content = (
        f"---\nname: {candidate['name']}\nversion: '1.0'\ncategory: system\n"
        "description: Native Factoryquelle\n---\nUnveränderte Systemfassung.\n"
    )
    factory_file.write_text(factory_content, encoding="utf-8")
    service = promotion_service(database, root=local_root, skill_roots=[local_root, factory_root])
    previous_binding = service._skill_binding(candidate["name"])
    assert previous_binding["source_kind"] == "underlay"
    assert previous_binding["source_root"] == str(factory_root.resolve())

    published = service.promote(
        "hermes", candidate["id"], target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="factory-promote-0001",
        expected_target_version=previous_binding["source_version"],
        actor="device:7",
    )
    assert published["status"] == "published"
    local_file = local_root / candidate["name"] / "SKILL.md"
    assert local_file.is_file()
    with sqlite3.connect(database) as conn:
        payload = json.loads(conn.execute(
            "SELECT target_payload_json FROM learning_promotions WHERE request_id='factory-promote-0001'"
        ).fetchone()[0])
    assert payload["previous_source_binding"] == previous_binding

    revoked = service.revoke(
        "hermes", candidate["id"], target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="factory-promote-0001",
        request_id="factory-revoke-0001",
        actor="device:7",
    )
    assert revoked["targets_revoked"] is True
    assert not local_file.exists()
    assert service._skill_binding(candidate["name"]) == previous_binding
    assert service._skill_version(candidate["name"]) == previous_binding["source_version"]


def test_skill_revoke_preserves_override_when_factory_underlay_changed(database, tmp_path):
    _, candidate = hermes_reviewed(database, skill_name="factory-change-learning")
    local_root = tmp_path / "local-skills"
    factory_root = tmp_path / "factory-skills"
    factory_file = factory_root / candidate["name"] / "SKILL.md"
    factory_file.parent.mkdir(parents=True)
    local_root.mkdir()
    factory_content = (
        f"---\nname: {candidate['name']}\nversion: '1.0'\ncategory: system\n"
        "description: Native Factoryquelle\n---\nUrsprüngliche Systemfassung.\n"
    )
    factory_file.write_text(factory_content, encoding="utf-8")
    service = promotion_service(database, root=local_root, skill_roots=[local_root, factory_root])
    previous_binding = service._skill_binding(candidate["name"])
    service.promote(
        "hermes", candidate["id"], target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="factory-change-promote-01",
        expected_target_version=previous_binding["source_version"],
        actor="device:7",
    )
    local_file = local_root / candidate["name"] / "SKILL.md"
    promoted = local_file.read_bytes()
    factory_file.write_text(factory_content.replace("Ursprüngliche", "Fremd geänderte"), encoding="utf-8")

    with pytest.raises(LearningPromotionConflict, match="darunterliegende"):
        service.revoke(
            "hermes", candidate["id"], target_kind="skill",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            source_request_id="factory-change-promote-01",
            request_id="factory-change-revoke-01",
            actor="device:7",
        )
    assert local_file.read_bytes() == promoted
    assert "Fremd geänderte" in factory_file.read_text(encoding="utf-8")
    assert service._skill_binding(candidate["name"])["source_kind"] == "local_override"


def test_native_skill_read_write_cas_race_maps_to_api_409(database, tmp_path, monkeypatch):
    _, candidate = hermes_reviewed(database, skill_name="api-skill-cas-race")
    root = tmp_path / "race-skills"
    root.mkdir()
    service = promotion_service(database, root=root)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')", (hashlib.sha256(TOKEN.encode()).hexdigest(),))
        conn.commit()
    monkeypatch.setattr(unified_api, "BACH_DB", database)
    monkeypatch.setattr(unified_api, "_get_learning_promotion_service_instance", lambda: service)
    app = FastAPI()
    app.include_router(unified_api.router)
    client = TestClient(app)
    original_save = skill_source_service.save_skill
    race_started = []
    native_conflicts = []

    def race_between_read_and_write(skill_id, content, expected_version, **kwargs):
        if not race_started:
            race_started.append(True)
            original_save(skill_id, "concurrent writer won\n", expected_version, **kwargs)
        try:
            return original_save(skill_id, content, expected_version, **kwargs)
        except RuntimeError as exc:
            native_conflicts.append(str(exc))
            raise

    monkeypatch.setattr(skill_source_service, "save_skill", race_between_read_and_write)
    response = client.post(
        f"/api/learning/hermes/candidates/{candidate['id']}/promote",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "target_kind": "skill",
            "expected_revision": candidate["candidate_revision"],
            "expected_digest": candidate["candidate_digest"],
            "request_id": "api-cas-race-0001",
            "expected_target_version": "0",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "learning_promotion_conflict"
    assert native_conflicts == ["skill_source_version_conflict"]
    assert (root / candidate["name"] / "SKILL.md").read_text(encoding="utf-8") == "concurrent writer won\n"


def test_unknown_native_skill_runtime_error_is_not_relabelled_as_cas_conflict(database, tmp_path, monkeypatch):
    root = tmp_path / "unknown-error-skills"
    root.mkdir()
    service = promotion_service(database, root=root)

    def fail_with_unknown_runtime(*_args, **_kwargs):
        raise RuntimeError("unclassified native writer failure")

    monkeypatch.setattr(skill_source_service, "save_skill", fail_with_unknown_runtime)
    with pytest.raises(RuntimeError, match="unclassified native writer failure"):
        service._save_skill("unknown-runtime-skill", "not empty", "0")


def test_hermes_lessons_publish_atomically_replay_and_revoke(database):
    _, candidate = hermes_reviewed(database, skill_name="lesson-learning")
    assert candidate["lessons_draft"]
    with sqlite3.connect(database) as conn:
        conn.execute("ALTER TABLE memory_lessons ADD COLUMN reviewer_metadata TEXT")
        conn.commit()
    service = promotion_service(database)
    first = service.promote(
        "hermes", candidate["id"],
        target_kind="lessons",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="lessons-promote-0001",
        expected_target_version="absent",
        actor="device:7",
    )
    assert first["status"] == "published"
    assert len(first["target_ids"]) == len(candidate["lessons_draft"])
    assert row_count(database, "memory_lessons", "is_active=1") == len(first["target_ids"])

    with sqlite3.connect(database) as conn:
        for lesson_id in first["target_ids"]:
            item = conn.execute(
                """SELECT target_snapshot_json FROM learning_promotion_items
                   WHERE promotion_request_id=? AND target_kind='lessons' AND target_key=?""",
                ("lessons-promote-0001", str(lesson_id)),
            ).fetchone()
            snapshot = json.loads(item[0])
            assert set(snapshot) == {"id", "category", "title", "solution", "is_active"}
            conn.execute(
                "UPDATE memory_lessons SET reviewer_metadata=? WHERE id=?",
                ("nach der Promotion ergänzt", lesson_id),
            )
        conn.commit()

    replay = service.promote(
        "hermes", candidate["id"],
        target_kind="lessons",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="lessons-promote-0001",
        expected_target_version="absent",
        actor="device:7",
    )
    assert replay["replayed"] is True
    assert row_count(database, "memory_lessons", "is_active=1") == len(first["target_ids"])

    revoked = service.revoke(
        "hermes", candidate["id"], target_kind="lessons",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="lessons-promote-0001",
        request_id="lessons-revoke-0001",
        actor="device:7",
    )
    assert revoked["status"] == "reverted"
    assert revoked["targets_revoked"] is True
    assert row_count(database, "memory_lessons", "is_active=1") == 0
    assert row_count(database, "memory_lessons", "is_active=0") == len(first["target_ids"])
    with sqlite3.connect(database) as conn:
        for lesson_id in first["target_ids"]:
            row = conn.execute(
                "SELECT is_active,reviewer_metadata FROM memory_lessons WHERE id=?",
                (lesson_id,),
            ).fetchone()
            assert row == (0, "nach der Promotion ergänzt")


def test_hermes_revoke_accepts_unchanged_manually_inactive_lesson(database):
    _, candidate = hermes_reviewed(database, skill_name="manual-inactive-lesson")
    service = promotion_service(database)
    promoted = service.promote(
        "hermes", candidate["id"], target_kind="lessons",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="manual-inactive-promote-01",
        expected_target_version="absent",
        actor="device:7",
    )
    assert promoted["target_ids"]
    manually_inactive_id = promoted["target_ids"][0]

    with sqlite3.connect(database) as conn:
        before = conn.execute(
            "SELECT category,title,solution,is_active FROM memory_lessons WHERE id=?",
            (manually_inactive_id,),
        ).fetchone()
        assert before is not None and before[3] == 1
        conn.execute("UPDATE memory_lessons SET is_active=0 WHERE id=?", (manually_inactive_id,))
        conn.commit()
        after_manual_deactivation = conn.execute(
            "SELECT category,title,solution,is_active FROM memory_lessons WHERE id=?",
            (manually_inactive_id,),
        ).fetchone()
    assert after_manual_deactivation == (*before[:3], 0)

    revoked = service.revoke(
        "hermes", candidate["id"], target_kind="lessons",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="manual-inactive-promote-01",
        request_id="manual-inactive-revoke-01",
        actor="device:7",
    )
    assert revoked["status"] == "reverted"
    assert revoked["already_inactive_count"] == 1
    assert revoked["disabled_count"] == len(promoted["target_ids"]) - 1
    with sqlite3.connect(database) as conn:
        after_revoke = conn.execute(
            "SELECT category,title,solution,is_active FROM memory_lessons WHERE id=?",
            (manually_inactive_id,),
        ).fetchone()
    assert after_revoke == after_manual_deactivation


def test_hermes_lesson_conflict_and_database_failure_leave_no_partial_targets(database):
    _, candidate = hermes_reviewed(database, skill_name="lesson-atomicity")
    drafts = candidate["lessons_draft"]
    assert drafts
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO memory_lessons(category,title,solution,is_active) VALUES(?,?,?,1)",
            (drafts[0]["category"], drafts[0]["title"], "Existing active memory"),
        )
        conn.commit()
    service = promotion_service(database)
    with pytest.raises(LearningPromotionConflict, match="kollidiert"):
        service.promote(
            "hermes", candidate["id"],
            target_kind="lessons",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            request_id="lessons-conflict-001",
            expected_target_version="absent",
            actor="device:7",
        )
    assert row_count(database, "memory_lessons", "is_active=1") == 1
    assert row_count(database, "learning_promotions", "target_kind='lessons'") == 0

    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM memory_lessons")
        conn.execute("""CREATE TRIGGER fail_lesson_publish BEFORE INSERT ON memory_lessons
            BEGIN SELECT RAISE(ABORT, 'simulated target store failure'); END""")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="simulated target store failure"):
        service.promote(
            "hermes", candidate["id"],
            target_kind="lessons",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            request_id="lessons-failure-001",
            expected_target_version="absent",
            actor="device:7",
        )
    assert row_count(database, "memory_lessons") == 0
    assert row_count(database, "learning_promotions", "target_kind='lessons'") == 0


def test_nemofold_legacy_steps_stay_waiting_without_target_mutation(database):
    _, candidate = nemo_reviewed(database)
    service = promotion_service(database, sequence_store=SequenceStore(database, write_guard=lambda: None))
    status = service.target_states("nemofold", candidate)
    assert status["targets"]["sequence"]["state"] == "waiting_for_native_definition"
    with pytest.raises(LearningPromotionUnavailable, match="waiting_for_native_definition"):
        service.promote(
            "nemofold", candidate["id"],
            target_kind="sequence",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            request_id="nemo-wait-0001",
            expected_target_version=0,
            actor="device:7",
        )
    assert row_count(database, "marblerun_chains") == 0


def test_native_sequence_publication_replays_and_revoke_deletes_new_chain(database):
    _, candidate = nemo_reviewed(database)
    store = SequenceStore(database, write_guard=lambda: None)
    service = promotion_service(
        database,
        adapter=sequence_proposal,
        sequence_store=store,
    )
    kwargs = dict(
        target_kind="sequence",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="nemo-promote-0001",
        expected_target_version=0,
        actor="device:7",
    )
    published = service.promote("nemofold", candidate["id"], **kwargs)
    assert published["status"] == "published"
    assert published["target_version"] == 1
    assert published["target_active"] is True
    assert published["empirically_validated"] is False
    assert row_count(database, "marblerun_chains") == 1
    assert row_count(database, "native_sequence_learning_promotions", "action='promote'") == 1

    replay = service.promote("nemofold", candidate["id"], **kwargs)
    assert replay["replayed"] is True
    assert row_count(database, "marblerun_chains") == 1

    revoked = service.revoke(
        "nemofold", candidate["id"], target_kind="sequence",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="nemo-promote-0001",
        request_id="nemo-revoke-0001",
        actor="device:7",
    )
    assert revoked["target_state"] == "deleted"
    assert revoked["targets_revoked"] is True
    assert row_count(database, "marblerun_chains") == 0
    assert service.target_states("nemofold", candidate)["targets"]["sequence"]["state"] == "reverted"


def test_native_sequence_revoke_restores_prior_definition_and_blocks_external_change(database):
    _, candidate = nemo_reviewed(database, name="existing-native-chain")
    store = SequenceStore(database, write_guard=lambda: None)
    previous = store.save_chain({
        "name": "existing-native-chain",
        "title": "Vorherige Kette",
        "description": "Vorheriger Zustand",
        "mode": "agents",
        "agent_slot": "",
        "steps": [{
            "label": "Vorher",
            "agent_slot": "worker-test",
            "skill_ids": [],
            "instructions": "Vorherige Anweisung.",
        }],
    })
    service = promotion_service(database, adapter=sequence_proposal, sequence_store=store)
    published = service.promote(
        "nemofold", candidate["id"],
        target_kind="sequence",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="nemo-update-0001",
        expected_target_version=previous["version"],
        actor="device:7",
    )
    assert published["target_id"] == previous["id"]
    changed = store.chain(previous["id"])
    assert changed["version"] == previous["version"] + 1

    revoked = service.revoke(
        "nemofold", candidate["id"], target_kind="sequence",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        source_request_id="nemo-update-0001",
        request_id="nemo-update-revoke-01",
        actor="device:7",
    )
    restored = store.chain(previous["id"])
    assert revoked["target_state"] == "restored"
    assert restored["title"] == previous["title"]
    assert restored["description"] == previous["description"]
    assert restored["steps"] == previous["steps"]
    assert restored["version"] == changed["version"] + 1

    second = service.promote(
        "nemofold", candidate["id"],
        target_kind="sequence",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="nemo-update-0002",
        expected_target_version=restored["version"],
        actor="device:7",
    )
    assert second["status"] == "published"
    external = dict(store.chain(previous["id"]))
    external["title"] = "Extern geändert"
    store.save_chain(
        {key: external[key] for key in ("name", "title", "description", "mode", "agent_slot", "steps")},
        chain_id=previous["id"],
        expected_version=external["version"],
    )
    with pytest.raises(SequenceConflict, match="verändert"):
        service.revoke(
            "nemofold", candidate["id"], target_kind="sequence",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            source_request_id="nemo-update-0002",
            request_id="nemo-update-revoke-02",
            actor="device:7",
        )
    assert store.chain(previous["id"])["title"] == "Extern geändert"


def test_native_sequence_receipt_failure_rolls_back_target_and_can_retry(database):
    _, candidate = nemo_reviewed(database, name="atomic-native-chain")
    store = SequenceStore(database, write_guard=lambda: None)
    store.initialize()
    with store.connection(write=True) as conn:
        store._ensure_learning_promotion_schema(conn)
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TRIGGER fail_sequence_receipt
            BEFORE INSERT ON native_sequence_learning_promotions
            WHEN NEW.action='promote'
            BEGIN SELECT RAISE(ABORT, 'simulated receipt failure'); END""")
        conn.commit()
    service = promotion_service(database, adapter=sequence_proposal, sequence_store=store)
    kwargs = dict(
        target_kind="sequence",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="nemo-atomic-0001",
        expected_target_version=0,
        actor="device:7",
    )
    with pytest.raises(sqlite3.IntegrityError, match="simulated receipt failure"):
        service.promote("nemofold", candidate["id"], **kwargs)
    assert row_count(database, "marblerun_chains") == 0
    assert row_count(database, "native_sequence_learning_promotions") == 0

    with sqlite3.connect(database) as conn:
        conn.execute("DROP TRIGGER fail_sequence_receipt")
        conn.commit()
    receipt = service.promote("nemofold", candidate["id"], **kwargs)
    assert receipt["status"] == "published"
    assert row_count(database, "marblerun_chains") == 1
    assert row_count(database, "native_sequence_learning_promotions", "action='promote'") == 1


def test_native_sequence_rejects_changed_resolution_and_stale_target_cas(database):
    _, candidate = nemo_reviewed(database, name="cas-native-chain")
    store = SequenceStore(database, write_guard=lambda: None)
    calls = [0]

    def changing_resolution(item):
        calls[0] += 1
        return sequence_proposal(item, config_version=f"cfg-v{calls[0]}")

    service = promotion_service(database, adapter=changing_resolution, sequence_store=store)
    with pytest.raises(SequenceConflict, match="Auflösung änderte sich"):
        service.promote(
            "nemofold", candidate["id"],
            target_kind="sequence",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            request_id="nemo-resolution-01",
            expected_target_version=0,
            actor="device:7",
        )
    assert row_count(database, "marblerun_chains") == 0

    stable = promotion_service(database, adapter=sequence_proposal, sequence_store=store)
    with pytest.raises(SequenceConflict, match="version"):
        stable.promote(
            "nemofold", candidate["id"],
            target_kind="sequence",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            request_id="nemo-stale-cas-01",
            expected_target_version=4,
            actor="device:7",
        )
    assert row_count(database, "marblerun_chains") == 0


def test_promotion_api_binds_actor_target_and_rejects_client_definition(database, tmp_path, monkeypatch):
    _, candidate = hermes_reviewed(database, skill_name="api-learning")
    root = tmp_path / "api-skills"
    root.mkdir()
    service = promotion_service(database, root=root)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')", (hashlib.sha256(TOKEN.encode()).hexdigest(),))
        conn.commit()
    monkeypatch.setattr(unified_api, "BACH_DB", database)
    monkeypatch.setattr(unified_api, "_get_learning_promotion_service_instance", lambda: service)
    app = FastAPI()
    app.include_router(unified_api.router)
    client = TestClient(app)
    path = f"/api/learning/hermes/candidates/{candidate['id']}/promote"
    payload = {
        "target_kind": "skill",
        "expected_revision": candidate["candidate_revision"],
        "expected_digest": candidate["candidate_digest"],
        "request_id": "api-promote-0001",
        "expected_target_version": "0",
    }
    assert client.post(path, json=payload).status_code == 401
    forged = client.post(path, headers={"Authorization": f"Bearer {TOKEN}"},
                         json={**payload, "definition": {"name": "attacker-chain"}})
    assert forged.status_code == 422
    response = client.post(path, headers={"Authorization": f"Bearer {TOKEN}"}, json=payload)
    assert response.status_code == 200
    assert response.json()["target_kind"] == "skill"
    with sqlite3.connect(database) as conn:
        actor = conn.execute(
            "SELECT actor FROM learning_promotions WHERE request_id='api-promote-0001'"
        ).fetchone()[0]
    assert actor == "device:7"


@pytest.mark.parametrize(
    ("target_state", "expected_available"),
    [("ready_for_target_cas", True), ("target_unavailable", False), ("published", False)],
)
def test_candidate_detail_projects_compatibility_availability_from_target_states(
    database, monkeypatch, target_state, expected_available
):
    source, candidate = hermes_reviewed(database, skill_name=f"detail-projection-{target_state.replace('_', '-')}")
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')", (hashlib.sha256(TOKEN.encode()).hexdigest(),))
        conn.commit()

    class ProjectedTargets:
        def target_states(self, provider, selected):
            return {
                "candidate_id": selected["id"],
                "candidate_revision": selected["candidate_revision"],
                "candidate_digest": selected["candidate_digest"],
                "targets": {"skill": {
                    "state": target_state,
                    "targets_published": target_state == "published",
                }},
            }

    monkeypatch.setattr(unified_api, "BACH_DB", database)
    monkeypatch.setattr(unified_api, "_get_hermes_service_instance", lambda: source)
    monkeypatch.setattr(unified_api, "_get_learning_promotion_service_instance", ProjectedTargets)
    app = FastAPI()
    app.include_router(unified_api.router)
    response = TestClient(app).get(
        f"/api/learning/hermes/candidates/{candidate['id']}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["promotion_targets"]["targets"]["skill"]["state"] == target_state
    assert body["promotion_available"] is expected_available
    assert body["promotion_availability_deprecated"] is False
    assert body["promotion_availability_source"] == "promotion_targets"
    if expected_available:
        assert body["promotion_unavailable_reason"] is None
    else:
        assert "promotion_targets.targets" in body["promotion_unavailable_reason"]


def test_promotion_api_reports_waiting_for_native_definition(database, monkeypatch):
    _, candidate = nemo_reviewed(database, name="api-nemo-wait")
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')", (hashlib.sha256(TOKEN.encode()).hexdigest(),))
        conn.commit()
    service = promotion_service(database, sequence_store=SequenceStore(database, write_guard=lambda: None))
    monkeypatch.setattr(unified_api, "BACH_DB", database)
    monkeypatch.setattr(unified_api, "_get_learning_promotion_service_instance", lambda: service)
    app = FastAPI()
    app.include_router(unified_api.router)
    client = TestClient(app)
    path = f"/api/learning/nemofold/candidates/{candidate['id']}/promote"
    response = client.post(
        path,
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "target_kind": "sequence",
            "expected_revision": candidate["candidate_revision"],
            "expected_digest": candidate["candidate_digest"],
            "request_id": "api-nemo-wait-01",
            "expected_target_version": 0,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "waiting_for_native_definition"
    assert row_count(database, "marblerun_chains") == 0

def _custom_reviewed_hermes(database, *, skill_name, frontmatter, content):
    import json
    from hub._services.learning_review_service import proposal_binding

    source = HermesDistillationService(database)
    result = source.run_pipeline(
        "Merke: Prüfe zuerst den Kontext. Best Practice: Bewahre Änderungen nachvollziehbar.",
        session_id="promotion-frontmatter-regression",
        skill_name_hint=skill_name,
    )
    candidate_id = result.candidate["id"]
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """UPDATE hermes_skill_candidates
               SET name=?, category=?, role=?, version=?, description=?,
                   trigger_phrases=?, frontmatter=?, content=?
               WHERE id=?""",
            (
                skill_name,
                frontmatter.get("category", "utilities"),
                frontmatter.get("role", ""),
                frontmatter["version"],
                frontmatter["description"],
                json.dumps(frontmatter.get("triggers", []), ensure_ascii=False),
                json.dumps(frontmatter, ensure_ascii=False),
                content,
                candidate_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM hermes_skill_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        payload, digest = proposal_binding("hermes", dict(row))
        conn.execute(
            """UPDATE hermes_skill_candidates
               SET proposal_json=?, candidate_digest=? WHERE id=?""",
            (payload, digest, candidate_id),
        )
        conn.commit()

    candidate = source.get_candidate(candidate_id)
    assert candidate["review_state"] == "pending"
    receipt = source.review_candidate(
        candidate_id,
        actor="device:7",
        notes="Frontmatter-Regression separat geprüft.",
        **review_binding(candidate, "hermes-frontmatter-review-0001"),
    )
    assert receipt["status"] == "reviewed"
    return source, source.get_candidate(candidate_id)


def test_skill_promotion_canonicalizes_reviewed_yaml_and_binds_receipt_to_bytes(database, tmp_path):
    import yaml

    skill_name = "frontmatter-colon-umlauts"
    frontmatter = {
        "name": skill_name,
        "version": "1.0.0",
        "role": "Prüfen und erklären\nmit Sorgfalt\n",
        "category": "utilities",
        "description": "Währung prüfen: Größe beachten",
        "triggers": ["Prüfe: Änderungen", "Maßstäbe bestätigen"],
        "provenance": {
            "distilled_by": "hermes",
            "source_session": "promotion-frontmatter-regression",
            "distilled_at": "2026-10-11T00:00:00Z",
            "confidence": 0.88,
            "noise_reduction_percent": 25,
        },
    }
    body = "# Bewahrte Quelle: sicher\n\nText mit ä, ö, ü und ß.\n"
    content = (
        "---\n"
        f"name: {skill_name}\n"
        "version: 1.0.0\n"
        "role: |\n"
        "  Prüfen und erklären\n"
        "  mit Sorgfalt\n"
        "category: utilities\n"
        "description: Währung prüfen: Größe beachten\n"
        "triggers:\n"
        '  - "Prüfe: Änderungen"\n'
        '  - "Maßstäbe bestätigen"\n'
        "provenance:\n"
        "  distilled_by: hermes\n"
        "  source_session: promotion-frontmatter-regression\n"
        "  distilled_at: '2026-10-11T00:00:00Z'\n"
        "  confidence: 0.88\n"
        "  noise_reduction_percent: 25\n"
        "---\n"
        + body
    )
    _, candidate = _custom_reviewed_hermes(
        database, skill_name=skill_name, frontmatter=frontmatter, content=content
    )
    root = tmp_path / "skills"
    root.mkdir()
    service = promotion_service(database, root=root)
    receipt = service.promote(
        "hermes",
        candidate["id"],
        target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="skill-frontmatter-promote-0001",
        expected_target_version="0",
        actor="device:7",
    )

    target = root / skill_name / "SKILL.md"
    target_bytes = target.read_bytes()
    target_sha256 = hashlib.sha256(target_bytes).hexdigest()
    target_text = target_bytes.decode("utf-8")
    leading, after_open = target_text.split("---\n", 1)
    header, written_body = after_open.split("\n---\n", 1)
    assert leading == ""
    assert yaml.safe_load(header) == frontmatter
    assert written_body == body
    assert "description: 'Währung prüfen: Größe beachten'" in target_text
    assert receipt["status"] == "published"
    assert receipt["target_schema"] == "SKILL.md"
    assert receipt["content_transform"] == "bach.learning.hermes-skill-frontmatter.v1"
    assert receipt["target_sha256"] == target_sha256
    assert receipt["target_version"] == target_sha256

    replay = service.promote(
        "hermes",
        candidate["id"],
        target_kind="skill",
        expected_revision=candidate["candidate_revision"],
        expected_digest=candidate["candidate_digest"],
        request_id="skill-frontmatter-promote-0001",
        expected_target_version="0",
        actor="device:7",
    )
    assert replay["replayed"] is True
    assert hashlib.sha256(target.read_bytes()).hexdigest() == target_sha256


@pytest.mark.parametrize(
    "header",
    [
        (
            "name: {name}\n"
            "version: 1.0.0\n"
            "category: utilities\n"
            "description: Abweichende, nicht geprüfte Beschreibung\n"
        ),
        (
            "name: {name}\n"
            "version: 1.0.0\n"
            "category: utilities\n"
            "category: utilities\n"
            "description: Geprüfte Beschreibung\n"
        ),
    ],
    ids=["inconsistent-frontmatter", "duplicate-yaml-key"],
)
def test_skill_promotion_rejects_inconsistent_or_duplicate_frontmatter(database, tmp_path, header):
    skill_name = "frontmatter-mismatch"
    frontmatter = {
        "name": skill_name,
        "version": "1.0.0",
        "category": "utilities",
        "description": "Geprüfte Beschreibung",
    }
    content = "---\n" + header.format(name=skill_name) + "---\n# Nicht veröffentlichen\n"
    _, candidate = _custom_reviewed_hermes(
        database, skill_name=skill_name, frontmatter=frontmatter, content=content
    )
    root = tmp_path / "skills"
    root.mkdir()
    service = promotion_service(database, root=root)

    with pytest.raises(LearningPromotionUnavailable):
        service.promote(
            "hermes",
            candidate["id"],
            target_kind="skill",
            expected_revision=candidate["candidate_revision"],
            expected_digest=candidate["candidate_digest"],
            request_id="skill-invalid-frontmatter-0001",
            expected_target_version="0",
            actor="device:7",
        )

    assert not (root / skill_name / "SKILL.md").exists()
    assert row_count(database, "learning_promotions") == 0
