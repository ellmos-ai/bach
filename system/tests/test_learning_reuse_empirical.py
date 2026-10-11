"""Synthetic, isolated contract test for learning review, promotion and reuse.

This test checks source-to-reader binding only. It does not call a model and
cannot establish answer quality.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.session_store import SQLiteChatSessionStore
from hub._services.hermes_distillation_service import HermesDistillationService
from hub._services.learning_promotion_service import (
    LearningPromotionService,
    LearningPromotionUnavailable,
)


FIXTURES = Path(__file__).parent / "fixtures" / "learning_reuse"
FIXTURE_MANIFEST_SHA256 = "4892a1823bc07618d3e4723946a62e6f3d95345b5aa4f868cd184a28f5d429e0"
EXPECTED_FILES = {
    "source-session-v1.json",
    "panel-v1.json",
    "paired-experiment-plan-v1.json",
    "raw-run-record.schema.json",
    "blind-rating.schema.json",
}


def _read_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_isolated_bach_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "bach.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            CREATE TABLE memory_working (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE memory_facts (
                id INTEGER PRIMARY KEY,
                category TEXT,
                key TEXT,
                value TEXT,
                confidence REAL,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE memory_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                severity TEXT,
                title TEXT,
                problem TEXT,
                solution TEXT,
                related_tools TEXT,
                related_files TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE session_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                name TEXT NOT NULL,
                snapshot_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
    return database


def test_synthetic_panel_and_reader_schemas_are_hash_bound() -> None:
    manifest_bytes = (FIXTURES / "fixture-manifest.json").read_bytes()
    assert _sha256(manifest_bytes) == FIXTURE_MANIFEST_SHA256

    manifest = json.loads(manifest_bytes)
    assert manifest["schema"] == "bach.learning-reuse.fixture-manifest.v1"
    assert manifest["provenance"] == "synthetic"
    entries = {item["path"]: item for item in manifest["files"]}
    assert set(entries) == EXPECTED_FILES

    for name, entry in entries.items():
        payload = (FIXTURES / name).read_bytes()
        assert len(payload) == entry["bytes"]
        assert _sha256(payload) == entry["sha256"]

    source = _read_json("source-session-v1.json")
    assert source["schema"] == "bach.learning-reuse.synthetic-source.v1"
    assert source["provenance"] == "synthetic"
    assert source["messages"] and source["source_session_id"]

    panel = _read_json("panel-v1.json")
    case_ids = [case["case_id"] for case in panel["cases"]]
    assert panel["schema"] == "bach.learning-reuse.panel.v1"
    assert panel["provenance"] == "synthetic"
    assert len(case_ids) == 8
    assert len(set(case_ids)) == len(case_ids)
    assert all(case["prompt"] and case["must_cover"] for case in panel["cases"])

    raw_schema = _read_json("raw-run-record.schema.json")
    raw_properties = raw_schema["properties"]
    assert raw_schema["additionalProperties"] is False
    assert raw_properties["arm_code"]["enum"] == ["A", "B"]
    assert raw_properties["retry_count"]["const"] == 0
    assert {"timeout", "provider_error", "empty_response"} <= set(
        raw_properties["outcome"]["enum"]
    )
    assert "raw_output_sha256" in raw_properties

    blind_schema = _read_json("blind-rating.schema.json")
    blind_properties = blind_schema["properties"]
    assert blind_schema["additionalProperties"] is False
    assert blind_properties["scores"]["additionalProperties"] is False
    assert not {
        "arm_code",
        "condition",
        "model",
        "provider",
        "candidate_revision",
        "candidate_digest",
        "target_version",
    }.intersection(blind_properties)


def test_reviewed_hermes_lesson_is_retrievable_in_a_fresh_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _read_json("source-session-v1.json")
    database = _new_isolated_bach_db(tmp_path)
    hermes = HermesDistillationService(database)

    extracted = hermes.run_pipeline(
        source["messages"],
        session_id=source["source_session_id"],
        skill_name_hint="synthetic-learning-reuse",
        persist=True,
    )
    candidate = extracted.candidate
    assert extracted.status == "completed"
    assert candidate["status"] == "pending"
    assert candidate["id"] > 0
    assert candidate["candidate_revision"] > 0
    assert len(candidate["candidate_digest"]) == 64
    assert len(candidate["lessons_draft"]) == 1
    draft = candidate["lessons_draft"][0]
    assert draft["title"] == "Änderungen klein und überprüfbar halten"
    assert "freigegebenen Dateien" in draft["solution"]

    candidate_id = candidate["id"]
    revision = candidate["candidate_revision"]
    digest = candidate["candidate_digest"]
    promotion = LearningPromotionService(db_path=database)

    # A pending proposal is not reusable until its exact revision is reviewed.
    with pytest.raises(LearningPromotionUnavailable):
        promotion.promote(
            "hermes",
            candidate_id,
            target_kind="lessons",
            expected_revision=revision,
            expected_digest=digest,
            request_id="promote-before-review-v1",
            expected_target_version="absent",
            actor="test:synthetic-harness",
        )
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_lessons").fetchone()[0] == 0

    review = hermes.review_candidate(
        candidate_id,
        expected_revision=revision,
        expected_digest=digest,
        request_id="review-synthetic-source-v1",
        actor="reviewer:synthetic-panel",
        notes="Inhaltsreview der synthetischen Quelle; keine Ergebnisqualitätsbewertung.",
    )
    assert review["status"] == "reviewed"
    assert review["review_scope"] == "candidate_content_only"
    assert review["empirically_validated"] is False
    assert review["targets_published"] is False

    reviewed_candidate = hermes.get_candidate(candidate_id)
    assert reviewed_candidate is not None
    assert reviewed_candidate["status"] == "reviewed"
    assert reviewed_candidate["candidate_revision"] == revision
    assert reviewed_candidate["candidate_digest"] == digest

    receipt = promotion.promote(
        "hermes",
        candidate_id,
        target_kind="lessons",
        expected_revision=revision,
        expected_digest=digest,
        request_id="promote-synthetic-lesson-v1",
        expected_target_version="absent",
        actor="test:synthetic-harness",
    )
    assert receipt["status"] == "published"
    assert receipt["candidate_revision"] == revision
    assert receipt["candidate_digest"] == digest
    assert receipt["targets_published"] is True
    assert receipt["empirically_validated"] is False
    assert receipt["tools_granted"] is False
    assert receipt["agent_started"] is False

    target_state = promotion.target_states("hermes", reviewed_candidate)
    assert target_state["targets"]["lessons"]["state"] == "published"
    assert target_state["targets"]["lessons"]["targets_published"] is True

    # The actual memoryhooker adapter reads only from this isolated database.
    # No ChatRuntime.process call occurs, so this checks retrieval, not inference.
    monkeypatch.delenv("BACH_USE_EXTERNAL_MEMORYHOOKS", raising=False)
    from hub.memory_hook_provider import ExternalMemoryHook

    hook = ExternalMemoryHook(
        db_path=database,
        config_path=tmp_path / "memoryhooker.toml",
        mode="remember+search",
    )
    runtime = ChatRuntime(
        backend=None,
        session_store=SQLiteChatSessionStore(database),
    )
    monkeypatch.setattr(runtime, "_memory_hook", lambda: hook)
    new_session_id = "synthetic-independent-session-v1"
    fresh_session = runtime.get_session(new_session_id)
    assert fresh_session.chat_id == new_session_id
    assert fresh_session.messages == []

    context = runtime._get_memory_hook_context(
        "Wie halte ich Änderungen klein und überprüfbar und prüfe freigegebene Dateien?",
        new_session_id,
    )
    assert isinstance(context, str) and context
    assert draft["title"] in context
    assert "freigegebenen Dateien" in context
    assert fresh_session.messages == []
    assert source["source_session_id"] not in context
