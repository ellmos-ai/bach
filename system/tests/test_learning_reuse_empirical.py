"""Synthetic, isolated test of review, promotion and prompt delivery.

The regression follows a promoted lesson through ExternalMemoryHook and
ChatRuntime.process into a recording backend; it never calls a model and
cannot establish answer quality.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from hub._services.chat.chat_runtime import ChatRuntime
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


class _RecordingBackend:
    def __init__(self):
        self.calls = []

    def get_default_model(self):
        return "fixture-model"

    def get_context_limit(self):
        return 32768

    async def chat(self, messages, **_kwargs):
        self.calls.append(messages)
        return {"content": "fixture-answer"}

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


def _process_with_memory_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    *,
    opt_in: bool,
    worker_label: str,
    prompt: str,
) -> str:
    """Run the real hook through ChatRuntime.process into a local recorder."""
    from hub._services.chat import slots_config as slots
    from hub.memory_hook_provider import ExternalMemoryHook

    monkeypatch.delenv("BACH_USE_EXTERNAL_MEMORYHOOKS", raising=False)
    slots_path = tmp_path / f"{worker_label}-slots.json"
    slots.initialize_slots_config(str(slots_path))
    worker = slots.add_worker(
        {
            "name": f"Synthetic MemoryHook {worker_label}",
            "model": "fixture-model",
            "backend": "ollama",
            "allow_tools": False,
            "task_prompt": "Use the verified synthetic memory when relevant.",
        },
        path=str(slots_path),
    )
    worker_id = worker["id"]
    snapshot = slots.worker_configuration_snapshot(worker_id, path=str(slots_path))
    slots.change_worker_configuration(
        worker_id, snapshot["configuration_version"],
        {"memory_hook_opt_in": opt_in}, path=str(slots_path),
    )

    backend = _RecordingBackend()
    runtime = ChatRuntime(backend)
    runtime._get_bach_context = lambda _text: ""
    hook = ExternalMemoryHook(
        db_path=database,
        config_path=tmp_path / f"{worker_label}-memoryhooker.toml",
        mode="remember+search",
    )
    monkeypatch.setattr(runtime, "_memory_hook", lambda: hook)
    session = runtime.get_session(worker_id)
    session.custom_system_prompt = "PERSONA SYSTEMPROMPT"
    session.worker_slot_reader = lambda: slots.get_worker_slot(
        worker_id, path=str(slots_path)
    )

    answer = asyncio.run(
        runtime.process(prompt, worker_id, backend=backend, model="fixture-model")
    )
    assert answer == "fixture-answer"
    assert backend.calls
    messages = backend.calls[-1]
    assert messages and messages[0]["role"] == "system"
    return messages[0]["content"]


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

    # This is the actual process -> ExternalMemoryHook -> backend prompt path.
    query = "Wie halte ich Änderungen klein und überprüfbar und prüfe freigegebene Dateien?"
    delivered_prompt = _process_with_memory_hook(
        tmp_path, monkeypatch, database, opt_in=True, worker_label="published-on",
        prompt=query,
    )
    assert draft["title"] in delivered_prompt
    assert "freigegebenen Dateien" in delivered_prompt
    assert source["source_session_id"] not in delivered_prompt
    assert delivered_prompt.index("PERSONA SYSTEMPROMPT") < delivered_prompt.index(
        "--- MEMORY-HOOK ---"
    ) < delivered_prompt.index(draft["title"])

    # Published content remains gated by the native worker opt-in.
    opted_out_prompt = _process_with_memory_hook(
        tmp_path, monkeypatch, database, opt_in=False, worker_label="published-off",
        prompt=query,
    )
    assert draft["title"] not in opted_out_prompt
    assert "--- MEMORY-HOOK ---" not in opted_out_prompt
    assert source["source_session_id"] not in opted_out_prompt

    # Revocation keeps the target row for audit but makes it unavailable to the hook.
    revoked = promotion.revoke(
        "hermes", candidate_id, target_kind="lessons",
        expected_revision=revision, expected_digest=digest,
        source_request_id="promote-synthetic-lesson-v1",
        request_id="revoke-synthetic-lesson-v1", actor="test:synthetic-harness",
    )
    assert revoked["status"] == "reverted"
    assert revoked["targets_revoked"] is True
    with sqlite3.connect(database) as conn:
        target = conn.execute(
            "SELECT title, solution, is_active FROM memory_lessons WHERE title=?",
            (draft["title"],),
        ).fetchone()
    assert target is not None and target[2] == 0
    assert target[0] == draft["title"] and "freigegebenen Dateien" in target[1]

    revoked_prompt = _process_with_memory_hook(
        tmp_path, monkeypatch, database, opt_in=True, worker_label="revoked-on",
        prompt=query,
    )
    assert draft["title"] not in revoked_prompt
    assert "freigegebenen Dateien" not in revoked_prompt
    assert source["source_session_id"] not in revoked_prompt


def test_pending_and_rejected_lessons_never_reach_backend_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _read_json("source-session-v1.json")
    database = _new_isolated_bach_db(tmp_path)
    hermes = HermesDistillationService(database)
    query = "Wie halte ich Änderungen klein und überprüfbar und prüfe freigegebene Dateien?"

    pending = hermes.run_pipeline(
        source["messages"], session_id="synthetic-pending-source-v1",
        skill_name_hint="synthetic-pending-learning-reuse", persist=True,
    ).candidate
    pending_title = pending["lessons_draft"][0]["title"]
    assert pending["status"] == "pending"
    pending_prompt = _process_with_memory_hook(
        tmp_path, monkeypatch, database, opt_in=True, worker_label="pending-on",
        prompt=query,
    )
    assert pending_title not in pending_prompt
    assert "freigegebenen Dateien" not in pending_prompt
    assert "synthetic-pending-source-v1" not in pending_prompt

    rejected = hermes.run_pipeline(
        source["messages"], session_id="synthetic-rejected-source-v1",
        skill_name_hint="synthetic-rejected-learning-reuse", persist=True,
    ).candidate
    rejected_title = rejected["lessons_draft"][0]["title"]
    rejection = hermes.reject_candidate(
        rejected["id"], "Abgelehnter synthetischer Testkandidat.",
        expected_revision=rejected["candidate_revision"],
        expected_digest=rejected["candidate_digest"],
        request_id="reject-synthetic-learning-reuse-v1",
        actor="reviewer:synthetic-panel",
    )
    assert rejection["status"] == "rejected"
    rejected_prompt = _process_with_memory_hook(
        tmp_path, monkeypatch, database, opt_in=True, worker_label="rejected-on",
        prompt=query,
    )
    assert rejected_title not in rejected_prompt
    assert "freigegebenen Dateien" not in rejected_prompt
    assert "synthetic-rejected-source-v1" not in rejected_prompt
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_lessons").fetchone()[0] == 0
