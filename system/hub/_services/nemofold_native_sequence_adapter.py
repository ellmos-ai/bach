"""Build a read-only native SequenceStore proposal from a reviewed NemoFold source."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from . import learning_review_service, skill_source_service
from .chat import sequence_store, slots_config


SCHEMA = "bach.learning.native-sequence.v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SLOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_SOURCE_BYTES = 1_000_000


class NativeSequenceAdapterError(ValueError):
    """A reviewed provider candidate cannot be represented safely as a sequence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise NativeSequenceAdapterError(code, message)


def _candidate_binding(candidate: Mapping[str, Any]) -> tuple[int, int, str]:
    candidate_id = candidate.get("id")
    revision = candidate.get("candidate_revision")
    digest = candidate.get("candidate_digest")
    if type(candidate_id) is not int or candidate_id <= 0:
        _fail("candidate_binding_invalid", "Die NemoFold-Kandidaten-ID ist ungültig.")
    if type(revision) is not int or revision <= 0:
        _fail("candidate_binding_invalid", "Die NemoFold-Kandidatenrevision ist ungültig.")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        _fail("candidate_binding_invalid", "Der NemoFold-Kandidatendigest ist ungültig.")
    if candidate.get("status") != "reviewed" or candidate.get("review_state") != "reviewed":
        _fail("candidate_not_reviewed", "Nur ein aktuell inhaltsgeprüfter NemoFold-Kandidat ist zulässig.")

    receipt = candidate.get("_review_receipt")
    if (not isinstance(receipt, Mapping)
            or receipt.get("status") != "reviewed"
            or receipt.get("candidate_id") != candidate_id
            or receipt.get("candidate_revision") != revision
            or receipt.get("candidate_digest") != digest
            or receipt.get("review_scope") != "candidate_content_only"
            or receipt.get("empirically_validated") is not False
            or receipt.get("targets_published") is not False):
        _fail("candidate_review_receipt_invalid", "Das Inhaltsreview-Receipt bindet diese Revision nicht.")

    try:
        bound_payload, bound_digest = learning_review_service.proposal_binding("nemofold", candidate)
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise NativeSequenceAdapterError(
            "candidate_binding_invalid", "Der gebundene NemoFold-Kandidateninhalt ist ungültig."
        ) from exc
    if candidate.get("proposal_json") != bound_payload or bound_digest != digest:
        _fail("candidate_binding_conflict", "Der Kandidateninhalt stimmt nicht mit Revision und Digest überein.")
    return candidate_id, revision, digest


def _steps(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = candidate.get("steps_json")
    if not isinstance(raw, str):
        _fail("candidate_steps_invalid", "Die gebundene NemoFold-Schrittquelle ist ungültig oder zu groß.")
    try:
        if len(raw.encode("utf-8")) > _MAX_SOURCE_BYTES:
            _fail("candidate_steps_invalid", "Die gebundene NemoFold-Schrittquelle ist ungültig oder zu groß.")
    except UnicodeError as exc:
        raise NativeSequenceAdapterError(
            "candidate_steps_invalid", "Die gebundene NemoFold-Schrittquelle enthält ungültiges Unicode."
        ) from exc
    try:
        steps = json.loads(raw)
    except (json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise NativeSequenceAdapterError(
            "candidate_steps_invalid", "Die gebundene NemoFold-Schrittquelle ist kein gültiges JSON."
        ) from exc
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        _fail("candidate_steps_invalid", "Eine native Sequenz benötigt ein bis 32 gebundene Schritte.")
    if any(not isinstance(step, Mapping) for step in steps):
        _fail("candidate_steps_invalid", "Jeder NemoFold-Schritt muss ein Objekt sein.")

    for step in steps:
        if _nonempty(step.get("tool")) or _nonempty(step.get("inputs")):
            _fail(
                "unsupported_legacy_tool_semantics",
                "Legacy-tool/inputs besitzen hier keine nachgewiesene native Ausführungssemantik.",
            )
        if _nonempty(step.get("skills")) or _nonempty(step.get("skill_versions")):
            _fail(
                "unsupported_skill_pin_format",
                "Skills müssen über explizite skill_ids an aktuelle native SKILL.md-Quellen gebunden sein.",
            )
    return [dict(step) for step in steps]


def _nonempty(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _agent_snapshot() -> tuple[str, dict[str, dict[str, Any]]]:
    try:
        snapshot = slots_config.core_system_agents_snapshot()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise NativeSequenceAdapterError(
            "agent_registry_unavailable", "Die vorhandene System-Agenten-Registry konnte nicht geprüft werden."
        ) from exc
    if not isinstance(snapshot, Mapping):
        _fail("agent_registry_invalid", "Die System-Agenten-Registry hat kein gültiges Schema.")
    config_version = snapshot.get("configuration_version")
    if not isinstance(config_version, str) or not _DIGEST.fullmatch(config_version):
        _fail("agent_registry_invalid", "Die System-Agentenkonfiguration hat keine gültige Version.")
    agents = snapshot.get("agents")
    if not isinstance(agents, list):
        _fail("agent_registry_invalid", "Die System-Agenten-Registry enthält keine Agentenliste.")
    result: dict[str, dict[str, Any]] = {}
    for item in agents:
        if (not isinstance(item, Mapping) or item.get("system") is not True
                or not isinstance(item.get("id"), str) or not _SLOT_ID.fullmatch(item["id"])
                or item["id"] in result):
            _fail("agent_registry_invalid", "Die System-Agenten-Registry enthält eine ungültige oder doppelte ID.")
        result[item["id"]] = dict(item)
    return config_version, result


def _resolve_agent(step: Mapping[str, Any], agents: Mapping[str, Mapping[str, Any]]) -> str:
    explicit = step.get("agent_slot")
    legacy_agent = step.get("agent")
    explicit_id: str | None = None
    legacy_id: str | None = None

    if explicit is not None:
        if not isinstance(explicit, str) or not _SLOT_ID.fullmatch(explicit) or explicit not in agents:
            _fail("agent_slot_unavailable", "Der explizite Agentensteckplatz ist nicht vorhanden.")
        explicit_id = explicit

    if legacy_agent is not None:
        if not isinstance(legacy_agent, str) or not legacy_agent.strip() or "\x00" in legacy_agent:
            _fail("agent_reference_invalid", "Die NemoFold-Agentenreferenz ist ungültig.")
        if legacy_agent in agents:
            legacy_id = legacy_agent
        else:
            matches = [item_id for item_id, item in agents.items() if item.get("name") == legacy_agent]
            if len(matches) != 1:
                code = "agent_reference_ambiguous" if matches else "agent_slot_unavailable"
                _fail(code, "Die NemoFold-Agentenreferenz ist nicht eindeutig in der bestehenden Registry auflösbar.")
            legacy_id = matches[0]

    if explicit_id is None and legacy_id is None:
        _fail("agent_slot_unavailable", "Der Schritt enthält keine auflösbare vorhandene Workerbindung.")
    if explicit_id is not None and legacy_id is not None and explicit_id != legacy_id:
        _fail("agent_reference_conflict", "Agenten-ID und vorhandener Steckplatz widersprechen einander.")
    return explicit_id or legacy_id or ""


def _resolve_skills(skill_ids: list[str]) -> list[dict[str, str]]:
    unique_ids = sorted(set(skill_ids))
    if not unique_ids:
        return []
    try:
        pins = skill_source_service.pin_skills(unique_ids)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, UnicodeError) as exc:
        raise NativeSequenceAdapterError(
            "skill_source_unavailable", "Mindestens eine explizit gebundene Skillquelle ist nicht verfügbar."
        ) from exc
    if not isinstance(pins, list):
        _fail("skill_source_invalid", "Die native Skillquelle lieferte keine gültigen Versionspins.")
    by_id: dict[str, str] = {}
    for pin in pins:
        if (not isinstance(pin, Mapping) or not isinstance(pin.get("id"), str)
                or not _SKILL_ID.fullmatch(pin["id"])
                or not isinstance(pin.get("source_version"), str)
                or not _DIGEST.fullmatch(pin["source_version"])
                or pin["id"] in by_id):
            _fail("skill_source_invalid", "Die native Skillquelle lieferte ungültige oder doppelte Versionspins.")
        by_id[pin["id"]] = pin["source_version"]
    if set(by_id) != set(unique_ids):
        _fail("skill_source_conflict", "Die geladenen Skillversionen passen nicht exakt zu den Schritten.")
    return [{"id": skill_id, "source_version": by_id[skill_id]} for skill_id in unique_ids]


def _native_name(candidate_id: int, source_name: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", source_name.strip().lower()).strip("._-")
    if not slug:
        slug = "candidate"
    return f"nemofold-{candidate_id}-{slug[:50]}"


def build_native_sequence_proposal(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the exact version-bound proposal expected by LearningPromotionService.

    This function reads existing registries and SKILL.md sources only. It never
    creates a worker slot, writes a SequenceStore row, or starts a sequence.
    """
    if not isinstance(candidate, Mapping):
        _fail("candidate_invalid", "Ein NemoFold-Kandidatobjekt ist erforderlich.")
    candidate_id, revision, digest = _candidate_binding(candidate)
    steps = _steps(candidate)
    chain_name = candidate.get("chain_name")
    title = candidate.get("title")
    description = candidate.get("description", "")
    if (not isinstance(chain_name, str) or not chain_name.strip() or "\x00" in chain_name
            or not isinstance(title, str) or not title.strip() or chr(0) in title
            or not isinstance(description, str) or "\x00" in description):
        _fail("candidate_definition_invalid", "Titel, Kettenname oder Beschreibung des Kandidaten sind ungültig.")

    config_version, agents = _agent_snapshot()
    native_steps: list[dict[str, Any]] = []
    all_skill_ids: list[str] = []
    used_agent_ids: set[str] = set()
    for step in steps:
        label = step.get("label", step.get("name"))
        if not isinstance(label, str) or not label.strip() or "\x00" in label:
            _fail("candidate_step_invalid", "Jeder Schritt benötigt eine gültige Beschriftung.")
        slot_id = _resolve_agent(step, agents)
        used_agent_ids.add(slot_id)

        explicit_skills = step.get("skill_ids", [])
        if (not isinstance(explicit_skills, list) or len(explicit_skills) > 4
                or any(not isinstance(item, str) or not _SKILL_ID.fullmatch(item) for item in explicit_skills)
                or len(set(explicit_skills)) != len(explicit_skills)):
            _fail("candidate_skill_refs_invalid", "Jeder Schritt darf bis zu vier eindeutige skill_ids enthalten.")
        all_skill_ids.extend(explicit_skills)

        instruction_parts: list[str] = []
        for key in ("instructions", "description"):
            value = step.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if not isinstance(value, str) or "\x00" in value:
                _fail("candidate_step_invalid", "Schrittanweisungen müssen sicherer Text sein.")
            if value not in instruction_parts:
                instruction_parts.append(value)
        expected_output = step.get("expected_output")
        if expected_output is not None and expected_output != "":
            if not isinstance(expected_output, str) or "\x00" in expected_output:
                _fail("candidate_step_invalid", "Die erwartete Ausgabe muss sicherer Text sein.")
            instruction_parts.append("Erwartetes Ergebnis: " + expected_output)
        if not instruction_parts:
            _fail("candidate_step_invalid", "Jeder Schritt braucht geprüfte Anweisungen oder eine Beschreibung.")
        native_steps.append({
            "label": label,
            "agent_slot": slot_id,
            "skill_ids": explicit_skills,
            "instructions": "\n\n".join(instruction_parts),
        })

    try:
        profile_snapshot = slots_config.sequence_profile_snapshot(
            sorted(used_agent_ids), expected_version=config_version
        )
    except RuntimeError as exc:
        code = "configuration_version_conflict" if "configuration_version_conflict" in str(exc) else "agent_slot_unavailable"
        raise NativeSequenceAdapterError(
            code, "Die vorhandene Agentenkonfiguration änderte sich oder erlaubt diese Workerbindung nicht."
        ) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise NativeSequenceAdapterError(
            "agent_slot_unavailable", "Die vorhandene Agentenkonfiguration erlaubt diese Workerbindung nicht."
        ) from exc
    if (not isinstance(profile_snapshot, Mapping)
            or profile_snapshot.get("configuration_version") != config_version
            or not isinstance(profile_snapshot.get("profiles"), Mapping)
            or set(profile_snapshot["profiles"]) != used_agent_ids
            or any(not isinstance(profile, Mapping) for profile in profile_snapshot["profiles"].values())):
        _fail("configuration_version_conflict", "Die geprüfte Agentenauflösung passt nicht zur aktuellen Konfigurationsversion.")

    skills = _resolve_skills(all_skill_ids)
    proposed = {
        "name": _native_name(candidate_id, chain_name),
        "title": title,
        "description": description,
        "mode": "agents",
        "agent_slot": "",
        "steps": native_steps,
    }
    try:
        clean_definition = sequence_store.definition(proposed)
    except (TypeError, ValueError) as exc:
        raise NativeSequenceAdapterError(
            "candidate_definition_invalid", "Der gebundene Kandidat passt nicht in das native SequenceStore-Schema."
        ) from exc
    return {
        "schema": SCHEMA,
        "source": {
            "provider": "nemofold",
            "candidate_id": candidate_id,
            "candidate_revision": revision,
            "candidate_digest": digest,
        },
        "definition": clean_definition,
        "resolved": {
            "config_version": config_version,
            "agent_slots": [
                {"id": slot_id, "config_version": config_version}
                for slot_id in sorted(used_agent_ids)
            ],
            "skills": skills,
        },
    }
