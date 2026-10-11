"""Reviewed NemoFold sources resolve only to existing, versioned native references."""
from __future__ import annotations

import hashlib
import json

import pytest

from hub._services import learning_review_service
from hub._services import nemofold_native_sequence_adapter as adapter
from hub._services.chat.sequence_store import definition as sequence_definition


CONFIG_VERSION = "a" * 64
SKILL_ID = "reviewed-skill"


def _candidate(steps=None, **changes):
    item = {
        "id": 41,
        "candidate_revision": 3,
        "chain_name": "Prüfung: Nächster Schritt",
        "title": "Geprüfte Sequenz",
        "description": "Ein sicherer Vorschlag.",
        "trigger_type": "manual",
        "steps_json": json.dumps(steps if steps is not None else [{
            "step_index": 1,
            "name": "Eingang prüfen",
            "agent": "Worker Test",
            "description": "Prüfe die bereitgestellte Aufgabe.",
        }], ensure_ascii=False),
        "confidence_score": 0.8,
        "tuv_status": "needs_review",
        "tuv_report_json": "{}",
        "provenance_json": "{}",
        "status": "reviewed",
        "review_state": "reviewed",
    }
    item.update(changes)
    payload, digest = learning_review_service.proposal_binding("nemofold", item)
    item["proposal_json"] = payload
    item["candidate_digest"] = digest
    item["_review_receipt"] = {
        "status": "reviewed",
        "candidate_id": item["id"],
        "candidate_revision": item["candidate_revision"],
        "candidate_digest": digest,
        "review_scope": "candidate_content_only",
        "empirically_validated": False,
        "targets_published": False,
    }
    return item


@pytest.fixture
def registry(monkeypatch):
    current = {"version": CONFIG_VERSION}
    agents = [
        {"id": "worker-test", "name": "Worker Test", "system": True,
         "execution_kind": "worker", "enabled": True},
    ]
    monkeypatch.setattr(adapter.slots_config, "core_system_agents_snapshot", lambda: {
        "configuration_version": current["version"], "agents": list(agents),
    })

    def profile_snapshot(slot_ids, expected_version=None):
        if expected_version != current["version"]:
            raise RuntimeError("configuration_version_conflict")
        return {
            "configuration_version": current["version"],
            "profiles": {slot_id: {"allow_tools": True} for slot_id in slot_ids},
        }

    monkeypatch.setattr(adapter.slots_config, "sequence_profile_snapshot", profile_snapshot)
    return current, agents


@pytest.fixture
def real_sequence_registry(tmp_path, monkeypatch):
    path = tmp_path / "slots.json"
    config = adapter.slots_config.initialize_slots_config(str(path))
    profile = config["slots"]["buddha_research"]
    profile.update({
        "enabled": True,
        "execution_kind": "worker",
        "allow_tools": True,
        "allowed_tools": ["task_manage"],
    })
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(adapter.slots_config, "DEFAULT_SLOTS_FILE", str(path))
    return path


@pytest.mark.parametrize(("field", "value"), [
    ("enabled", False),
    ("execution_kind", "chat"),
])
def test_rejects_disabled_or_non_worker_slot_via_real_profile_validator(
    real_sequence_registry, field, value,
):
    candidate = _candidate(steps=[{
        "name": "Inspect source",
        "agent_slot": "buddha_research",
        "instructions": "Inspect the bound source.",
    }])
    valid = adapter.build_native_sequence_proposal(candidate)
    assert valid["resolved"]["agent_slots"] == [{
        "id": "buddha_research", "config_version": valid["resolved"]["config_version"],
    }]

    config = json.loads(real_sequence_registry.read_text(encoding="utf-8"))
    config["slots"]["buddha_research"][field] = value
    real_sequence_registry.write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(candidate)

    assert exc.value.code == "agent_slot_unavailable"


def _skill_root(monkeypatch, tmp_path, content="# Prüfen\n"):
    root = tmp_path / "skills"
    skill = root / SKILL_ID
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(content, encoding="utf-8")
    monkeypatch.setattr(adapter.skill_source_service, "skill_roots", lambda: [root])
    return skill / "SKILL.md"


def test_builds_canonical_proposal_from_reviewed_candidate_and_existing_worker(registry, monkeypatch, tmp_path):
    _skill_root(monkeypatch, tmp_path)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Proposalbau darf weder Slots materialisieren noch Sequenzen speichern")

    monkeypatch.setattr(adapter.slots_config, "materialize_sequence_slot", forbidden)
    monkeypatch.setattr(adapter.sequence_store.SequenceStore, "save_chain", forbidden)
    candidate = _candidate(steps=[{
        "name": "Eingang prüfen",
        "agent": "Worker Test",
        "skill_ids": [SKILL_ID],
        "instructions": "Prüfe die bereitgestellte Aufgabe.",
        "expected_output": "Prüfbericht",
    }])

    proposal = adapter.build_native_sequence_proposal(candidate)

    assert set(proposal) == {"schema", "source", "definition", "resolved"}
    assert proposal["schema"] == "bach.learning.native-sequence.v1"
    assert proposal["source"] == {
        "provider": "nemofold",
        "candidate_id": 41,
        "candidate_revision": 3,
        "candidate_digest": candidate["candidate_digest"],
    }
    assert proposal["definition"] == sequence_definition(proposal["definition"])
    assert proposal["definition"]["name"].startswith("nemofold-41-")
    assert proposal["definition"]["mode"] == "agents"
    assert proposal["definition"]["steps"] == [{
        "label": "Eingang prüfen",
        "agent_slot": "worker-test",
        "skill_ids": [SKILL_ID],
        "instructions": "Prüfe die bereitgestellte Aufgabe.\n\nErwartetes Ergebnis: Prüfbericht",
    }]
    assert proposal["resolved"] == {
        "config_version": CONFIG_VERSION,
        "agent_slots": [{"id": "worker-test", "config_version": CONFIG_VERSION}],
        "skills": [{
            "id": SKILL_ID,
            "source_version": hashlib.sha256("# Prüfen\n".encode("utf-8")).hexdigest(),
        }],
    }


@pytest.mark.parametrize("status, review_state", [
    ("pending", "pending"),
    ("rejected", "rejected"),
    ("reviewed", "legacy_unverified"),
])
def test_rejects_candidates_without_current_review(registry, status, review_state):
    candidate = _candidate(status=status, review_state=review_state)
    candidate["_review_receipt"]["status"] = status
    with pytest.raises(adapter.NativeSequenceAdapterError, match="inhaltsgeprüft"):
        adapter.build_native_sequence_proposal(candidate)


def test_rejects_missing_or_misbound_review_receipt(registry):
    candidate = _candidate()
    candidate.pop("_review_receipt")
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(candidate)
    assert exc.value.code == "candidate_review_receipt_invalid"

    candidate = _candidate()
    candidate["_review_receipt"]["candidate_revision"] = 2
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(candidate)
    assert exc.value.code == "candidate_review_receipt_invalid"


def test_rejects_changed_candidate_digest_or_revision(registry):
    candidate = _candidate()
    candidate["candidate_digest"] = "0" * 64
    candidate["_review_receipt"]["candidate_digest"] = "0" * 64
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(candidate)
    assert exc.value.code == "candidate_binding_conflict"

    candidate = _candidate()
    candidate["candidate_revision"] = 4
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(candidate)
    assert exc.value.code == "candidate_review_receipt_invalid"


def test_ignores_untrusted_client_native_definition(registry):
    candidate = _candidate()
    candidate["native_definition"] = {
        "name": "attacker-chain",
        "title": "Nicht übernehmen",
        "mode": "agents",
        "steps": [],
    }

    proposal = adapter.build_native_sequence_proposal(candidate)

    assert proposal["definition"]["name"] != "attacker-chain"
    assert proposal["definition"]["steps"][0]["agent_slot"] == "worker-test"


def test_rejects_control_characters_in_native_definition_text(registry):
    candidate = _candidate(title="Ungültig\x00Titel")
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(candidate)
    assert exc.value.code == "candidate_definition_invalid"


def test_resolves_explicit_slot_id_and_rejects_unknown_or_ambiguous_names(registry):
    candidate = _candidate(steps=[{
        "name": "Schritt",
        "agent_slot": "worker-test",
        "description": "Prüfe die Aufgabe.",
    }])
    proposal = adapter.build_native_sequence_proposal(candidate)
    assert proposal["definition"]["steps"][0]["agent_slot"] == "worker-test"

    unknown = _candidate(steps=[{
        "name": "Schritt", "agent": "Nicht vorhanden", "description": "Prüfe die Aufgabe.",
    }])
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(unknown)
    assert exc.value.code == "agent_slot_unavailable"

    _, agents = registry
    agents.append({"id": "worker-test-2", "name": "Worker Test", "system": True,
                   "execution_kind": "worker", "enabled": True})
    ambiguous = _candidate()
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(ambiguous)
    assert exc.value.code == "agent_reference_ambiguous"


def test_rejects_profile_that_is_changed_or_not_available(registry, monkeypatch):
    current, _ = registry

    def changed_profile_snapshot(slot_ids, expected_version=None):
        current["version"] = "b" * 64
        raise RuntimeError("configuration_version_conflict")

    monkeypatch.setattr(adapter.slots_config, "sequence_profile_snapshot", changed_profile_snapshot)
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(_candidate())
    assert exc.value.code == "configuration_version_conflict"


def test_changed_native_config_version_changes_proposal_for_transactional_recheck(registry):
    current, _ = registry
    candidate = _candidate()
    first = adapter.build_native_sequence_proposal(candidate)
    current["version"] = "b" * 64
    second = adapter.build_native_sequence_proposal(candidate)

    assert first["resolved"]["config_version"] == CONFIG_VERSION
    assert second["resolved"]["config_version"] == current["version"]
    assert first != second


@pytest.mark.parametrize("legacy_fields", [
    {"tool": "write_to_file"},
    {"inputs": {"target_path": "docs/"}},
    {"tool": "write_to_file", "inputs": {"target_path": "docs/"},
     "instructions": "Schreibe die Datei."},
])
def test_legacy_tool_or_input_semantics_remain_unpromotable(registry, legacy_fields):
    step = {"name": "Schritt", "agent_slot": "worker-test", "description": "Prüfe die Aufgabe."}
    step.update(legacy_fields)
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(_candidate(steps=[step]))
    assert exc.value.code == "unsupported_legacy_tool_semantics"


def test_rejects_unavailable_or_malformed_explicit_skill_pins(registry, monkeypatch, tmp_path):
    _skill_root(monkeypatch, tmp_path)
    missing = _candidate(steps=[{
        "name": "Schritt", "agent_slot": "worker-test", "skill_ids": ["missing-skill"],
        "description": "Prüfe die Aufgabe.",
    }])
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(missing)
    assert exc.value.code == "skill_source_unavailable"

    monkeypatch.setattr(adapter.skill_source_service, "pin_skills", lambda ids: [
        {"id": SKILL_ID, "source_version": "not-a-digest"},
    ])
    malformed = _candidate(steps=[{
        "name": "Schritt", "agent_slot": "worker-test", "skill_ids": [SKILL_ID],
        "description": "Prüfe die Aufgabe.",
    }])
    with pytest.raises(adapter.NativeSequenceAdapterError) as exc:
        adapter.build_native_sequence_proposal(malformed)
    assert exc.value.code == "skill_source_invalid"


def test_changed_native_skill_pin_changes_proposal_for_transactional_recheck(registry, monkeypatch, tmp_path):
    skill_path = _skill_root(monkeypatch, tmp_path, "# Erste Fassung\n")
    candidate = _candidate(steps=[{
        "name": "Schritt", "agent_slot": "worker-test", "skill_ids": [SKILL_ID],
        "description": "Prüfe die Aufgabe.",
    }])
    first = adapter.build_native_sequence_proposal(candidate)
    skill_path.write_text("# Geänderte Fassung\n", encoding="utf-8")
    second = adapter.build_native_sequence_proposal(candidate)

    assert first["resolved"]["skills"][0]["source_version"] != second["resolved"]["skills"][0]["source_version"]
    assert first != second

