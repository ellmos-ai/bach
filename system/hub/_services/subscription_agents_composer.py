# SPDX-License-Identifier: MIT
"""Versioned, side-effect-free onboarding prompt composition for subscription agents."""
from __future__ import annotations

import hashlib
import json
import re
import socket
import sqlite3
from pathlib import Path
from typing import Any, Callable

from . import blueprint_service, policy_registry_adapter, skill_source_service
from .task_lease_client import TaskLeaseClient


REQUEST_SCHEMA = "bach.subscription-agent-onboarding.request.v1"
PREVIEW_SCHEMA = "bach.subscription-agent-onboarding.preview.v1"
MAX_REQUEST_BYTES = 256 * 1024
MAX_PROMPT_CHARS = 120_000
MAX_USER_TASK_CHARS = 16_000
MAX_ROLE_PROMPT_CHARS = 20_000
MAX_TASK_REFS = 20
MAX_SKILLS = 30
MAX_POLICY_REFS = 20
MAX_BLUEPRINT_JSON_BYTES = 32 * 1024

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(
    r"(?ix)(?:\b(?:sk|ghp|github_pat|AKIA)[_-][A-Za-z0-9_-]{12,}\b|"
    r"\bbearer\s+[A-Za-z0-9._~+/=-]{12,}\b|"
    r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key|"
    r"password|passwd|authorization|credentials|secret)\s*[:=]\s*"
    r"(?:\"[^\"]{4,}\"|'[^']{4,}'|[^\s,;]{8,}))"
)
_CONTRACTUS_FIELDS = {
    "turns", "max_turns", "cooldown", "cooldown_seconds", "task_type",
    "modus", "wake_behavior", "animus_type",
}
_GOVERNANCE_FIELDS = {"profile", "tool_whitelist", "scope"}


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Quelle lässt sich nicht sicher versionieren") from None


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str) or "\x00" in value or len(value) > limit:
        raise ValueError(f"Ungültiger oder zu langer Text: {label}")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Text fehlt: {label}")
    return value


def _no_credentials(value: str, label: str) -> None:
    if _SECRET.search(value):
        raise ValueError(f"Credential-ähnlicher Inhalt in {label}; Vorschau gesperrt")


def _strict_mapping(value: Any, label: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Ungültige Zuordnung: {label}")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Nicht unterstützte Felder in {label}")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Doppelte Felder in gespeicherter Blueprint-Quelle")
        result[key] = value
    return result


def _stored_json(value: Any, label: str, expected_type: type, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_BLUEPRINT_JSON_BYTES:
            raise ValueError(f"Gespeicherte Blueprint-Quelle überschreitet das Größenlimit: {label}")
        try:
            value = json.loads(value, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, RecursionError, ValueError):
            raise ValueError(f"Gespeicherte Blueprint-Quelle ist ungültig: {label}") from None
    if not isinstance(value, expected_type):
        raise ValueError(f"Gespeicherte Blueprint-Quelle hat einen ungültigen Typ: {label}")
    if len(_canonical_bytes(value)) > MAX_BLUEPRINT_JSON_BYTES:
        raise ValueError(f"Gespeicherte Blueprint-Quelle überschreitet das Größenlimit: {label}")
    return value


def _source_record(*, source_id: str, kind: str, state: str, version: Any,
                   sha256: str | None, host: str | None, path: str | None,
                   source_bytes: int = 0, included_chars: int = 0,
                   included_bytes: int = 0, details: dict | None = None) -> dict:
    record = {
        "id": source_id,
        "kind": kind,
        "state": state,
        "version": version,
        "sha256": sha256,
        "host": host,
        "path": path,
        "source_bytes": source_bytes,
        "included_chars": included_chars,
        "included_bytes": included_bytes,
    }
    if details:
        record.update(details)
    return record


class SubscriptionAgentsComposer:
    """Build a bounded prompt preview from current BACH sources; never dispatch work."""

    def __init__(self, *, skill_roots: list[Path] | None = None,
                 task_snapshot_reader: Callable[[int], dict] | None = None,
                 blueprint_snapshot_reader: Callable[[int, int], dict] | None = None,
                 policy_observer: Callable[..., dict] | None = None,
                 task_db_path: str | Path | None = None,
                 host: str | None = None):
        self.skill_roots = [Path(root) for root in skill_roots] if skill_roots is not None else None
        self.task_snapshot_reader = task_snapshot_reader
        self.blueprint_snapshot_reader = blueprint_snapshot_reader
        self.policy_observer = policy_observer or policy_registry_adapter.observe
        self.task_db_path = Path(task_db_path) if task_db_path is not None else None
        self.host = host or socket.gethostname()

    def _read_saved_blueprint(self, blueprint_id: int, expected_version: int) -> dict:
        """Read one exact persisted revision through the existing execution validator."""
        if self.blueprint_snapshot_reader is not None:
            try:
                return self.blueprint_snapshot_reader(blueprint_id, expected_version)
            except KeyError:
                raise ValueError("Gespeicherter Blueprint wurde nicht gefunden") from None
            except RuntimeError as error:
                if str(error) == "blueprint_version_conflict":
                    raise ValueError("Angezeigte Blueprint-Revision stimmt nicht mehr mit der Quelle überein") from None
                raise

        db_path = self.task_db_path
        if db_path is None:
            from hub.bach_paths import BACH_DB
            db_path = Path(BACH_DB)
        db_path = Path(db_path)
        try:
            if not db_path.is_file():
                raise ValueError("Kanonische Blueprint-Quelle ist nicht verfügbar")
            connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        except (OSError, sqlite3.Error, ValueError):
            raise ValueError("Kanonische Blueprint-Quelle ist nicht lesbar") from None
        try:
            return blueprint_service._execution_blueprint(
                connection, blueprint_id, expected_version=expected_version,
            )
        except KeyError:
            raise ValueError("Gespeicherter Blueprint wurde nicht gefunden") from None
        except RuntimeError as error:
            if str(error) == "blueprint_version_conflict":
                raise ValueError("Angezeigte Blueprint-Revision stimmt nicht mehr mit der Quelle überein") from None
            raise
        except sqlite3.Error:
            raise ValueError("Gespeicherter Blueprint konnte nicht gelesen werden") from None
        finally:
            connection.close()

    def _blueprint(self, value: Any) -> tuple[dict, dict, dict]:
        reference = _strict_mapping(value, "blueprint", {"id", "version"})
        blueprint_id = reference.get("id")
        if type(blueprint_id) is not int or blueprint_id <= 0:
            raise ValueError("Blueprint-ID muss eine positive Ganzzahl sein")
        expected_version = reference.get("version")
        if type(expected_version) is not int or expected_version <= 0:
            raise ValueError("Blueprint-Version muss eine positive Ganzzahl sein")

        raw = self._read_saved_blueprint(blueprint_id, expected_version)
        if not isinstance(raw, dict) or type(raw.get("id")) is not int or raw["id"] != blueprint_id:
            raise ValueError("Blueprint-Reader lieferte keine passende gespeicherte Quelle")
        if type(raw.get("version")) is not int or raw["version"] != expected_version:
            raise ValueError("Angezeigte Blueprint-Revision stimmt nicht mehr mit der Quelle überein")
        stored = {
            "id": raw["id"],
            "name": raw.get("name"),
            "title": raw.get("title") or raw.get("name"),
            "version": raw["version"],
            "kind": raw.get("kind") or "agent",
            "persona_role": raw.get("persona_role"),
            "persona_prompt": raw.get("persona_prompt"),
            "skills": _stored_json(raw.get("skills_json", "[]"), "skills_json", list, []),
            "contractus": _stored_json(raw.get("contractus_json", "{}"), "contractus_json", dict, {}),
            "governance": _stored_json(raw.get("governance_json", "{}"), "governance_json", dict, {}),
            "modus": raw.get("modus") or "casualis",
            "animus_type": raw.get("animus_type") or "subscription",
        }
        return self._normalize_blueprint(stored)

    @staticmethod
    def _normalize_blueprint(value: Any) -> tuple[dict, dict, dict]:
        allowed = {
            "id", "name", "title", "version", "kind", "persona_role", "persona_prompt",
            "skills", "contractus", "governance", "modus", "animus_type",
        }
        raw = _strict_mapping(value, "blueprint", allowed)
        blueprint_id = raw.get("id")
        if type(blueprint_id) is int:
            if blueprint_id <= 0:
                raise ValueError("Blueprint-ID muss positiv sein")
            blueprint_id = str(blueprint_id)
        elif not isinstance(blueprint_id, str) or not _ID.fullmatch(blueprint_id):
            raise ValueError("Blueprint-ID ist ungültig")
        version = raw.get("version")
        if type(version) is not int or version <= 0:
            raise ValueError("Blueprint-Version muss eine positive Ganzzahl sein")
        kind = raw.get("kind", "agent")
        if not isinstance(kind, str) or kind not in {"agent", "role"}:
            raise ValueError("Nur Agent- und Rollen-Blueprints können komponiert werden")
        name = _text(raw.get("name"), "blueprint.name", 80)
        if len(name) < 2:
            raise ValueError("Blueprint-Name muss mindestens zwei Zeichen enthalten")
        title = _text(raw.get("title", name), "blueprint.title", 200)
        role = _text(raw.get("persona_role"), "blueprint.persona_role", 160)
        persona = _text(raw.get("persona_prompt"), "blueprint.persona_prompt", MAX_ROLE_PROMPT_CHARS)
        _no_credentials(persona, "Blueprint-Rolle")

        skills = raw.get("skills", [])
        if not isinstance(skills, list) or len(skills) > MAX_SKILLS:
            raise ValueError("Blueprint darf höchstens 30 Skill-IDs enthalten")
        if any(not isinstance(item, str) or not _SKILL_ID.fullmatch(item) for item in skills):
            raise ValueError("Blueprint enthält eine ungültige Skill-ID")
        if len(set(skills)) != len(skills):
            raise ValueError("Blueprint enthält doppelte Skill-IDs")

        contractus = _strict_mapping(raw.get("contractus", {}), "contractus", _CONTRACTUS_FIELDS)
        normalized_contractus = {}
        for key, item in contractus.items():
            if key in {"turns", "max_turns", "cooldown", "cooldown_seconds"}:
                if type(item) is not int or item < 0 or item > 100_000:
                    raise ValueError("Contractus-Zeit- und Turnwerte müssen begrenzte Ganzzahlen sein")
            else:
                item = _text(item, f"contractus.{key}", 120)
            normalized_contractus[key] = item
        _no_credentials(_canonical_bytes(normalized_contractus).decode("utf-8"), "Blueprint-Contractus")

        governance = _strict_mapping(raw.get("governance", {}), "blueprint.governance", _GOVERNANCE_FIELDS)
        normalized_governance = {}
        if "profile" in governance:
            normalized_governance["profile"] = _text(governance["profile"], "governance.profile", 120)
        if "scope" in governance:
            normalized_governance["scope"] = _text(governance["scope"], "governance.scope", 256)
        if "tool_whitelist" in governance:
            tools = governance["tool_whitelist"]
            if (not isinstance(tools, list) or len(tools) > 32
                    or any(not isinstance(tool, str) or not _ID.fullmatch(tool) for tool in tools)
                    or len(set(tools)) != len(tools)):
                raise ValueError("Governance-Toolliste ist ungültig oder zu groß")
            normalized_governance["tool_whitelist"] = list(tools)
        _no_credentials(_canonical_bytes(normalized_governance).decode("utf-8"), "Blueprint-Governance")

        modus = _text(raw.get("modus", "casualis"), "blueprint.modus", 64)
        animus = _text(raw.get("animus_type", "subscription"), "blueprint.animus_type", 80)
        for label, item in (("Blueprint-Name", name), ("Blueprint-Titel", title),
                            ("Blueprint-Rolle", role), ("Blueprint-Modus", modus),
                            ("Blueprint-Animus", animus)):
            _no_credentials(item, label)
        normalized = {
            "id": blueprint_id, "name": name, "title": title, "version": version,
            "kind": kind, "persona_role": role, "persona_prompt": persona,
            "skills": list(skills), "contractus": normalized_contractus,
            "governance": normalized_governance, "modus": modus, "animus_type": animus,
        }
        source = {key: normalized[key] for key in normalized}
        role_source = {"blueprint_id": blueprint_id, "blueprint_version": version,
                       "persona_role": role, "persona_prompt": persona}
        return normalized, source, role_source

    @staticmethod
    def _target(value: Any) -> dict:
        target = _strict_mapping(value, "target_client", {"client_id", "host", "name"})
        client_id = _text(target.get("client_id"), "target_client.client_id", 64)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", client_id):
            raise ValueError("Zielclient-ID ist ungültig")
        host = _text(target.get("host"), "target_client.host", 128)
        name = _text(target.get("name", client_id), "target_client.name", 120)
        _no_credentials(client_id, "Zielclient-ID")
        _no_credentials(host, "Zielclient-Host")
        _no_credentials(name, "Zielclient-Name")
        return {"client_id": client_id, "host": host, "name": name}

    def _read_tasks(self, task_ids: list[int]) -> tuple[list[dict], list[dict]]:
        if not task_ids:
            return [], []
        reader = self.task_snapshot_reader
        client = None
        if reader is None:
            try:
                client = TaskLeaseClient(db_path=self.task_db_path)
                client.__enter__()
                reader = client.task_snapshot
            except Exception:
                if client is not None:
                    client.__exit__(None, None, None)
                return [], [{"id": task_id, "kind": "task", "reason": "reader_unavailable"}
                            for task_id in task_ids]
        sources, missing = [], []
        try:
            for task_id in task_ids:
                try:
                    snapshot = reader(task_id)
                    if (not isinstance(snapshot, dict) or type(snapshot.get("id")) is not int
                            or snapshot["id"] != task_id
                            or not isinstance(snapshot.get("task_version"), str)
                            or not _SHA256.fullmatch(snapshot["task_version"])):
                        raise ValueError("invalid_snapshot")
                    title = _text(snapshot.get("title", f"Task {task_id}"),
                                  f"Task {task_id} title", 240)
                    status = _text(snapshot.get("status", "unknown"), f"Task {task_id} status", 40)
                    priority = snapshot.get("priority")
                    if priority is not None and (type(priority) is not int and not isinstance(priority, str)):
                        raise ValueError("invalid_priority")
                    if isinstance(priority, str):
                        priority = _text(priority, f"Task {task_id} priority", 40)
                    display = f"Task #{task_id}: {title} (Status: {status}"
                    if priority is not None:
                        display += f", Priorität: {priority}"
                    display += ")"
                    _no_credentials(display, f"Task #{task_id}")
                    included = {"id": task_id, "title": title, "status": status, "priority": priority}
                    sources.append({
                        "display": display,
                        "source": _source_record(
                            source_id=f"task:{task_id}", kind="task_snapshot", state="included",
                            version=snapshot["task_version"], sha256=snapshot["task_version"],
                            host="BACH-TaskLeaseClient", path=None,
                            source_bytes=len(_canonical_bytes(included)),
                            included_chars=len(display),
                            included_bytes=len(_canonical_bytes(included)),
                            details={"task_id": task_id, "task_reference_only": True},
                        ),
                    })
                except Exception:
                    missing.append({"id": task_id, "kind": "task", "reason": "snapshot_unavailable"})
        finally:
            if client is not None:
                client.__exit__(None, None, None)
        return sources, missing

    def _governance(self, *, scope: str, consumer: str,
                    queries: dict[str, str]) -> tuple[list[dict], list[dict], list[str]]:
        records, missing, prompt_refs = [], [], []
        for kind in ("policy", "decision"):
            try:
                result = self.policy_observer(scope=scope, consumer=consumer,
                                              query=queries.get(kind, ""), kind=kind)
            except Exception:
                result = None
            if not isinstance(result, dict) or result.get("availability") != "available":
                missing.append({"id": f"policy-registry:{kind}", "kind": kind,
                                "reason": "provider_unavailable"})
                records.append(_source_record(
                    source_id=f"policy-registry:{kind}", kind=kind, state="unavailable",
                    version=None, sha256=None, host="policy-registry", path=None,
                    details={"enforcement_verified": False, "read_only": True, "count": 0},
                ))
                continue
            registry_version = result.get("registry_version")
            if not isinstance(registry_version, str) or not _SHA256.fullmatch(registry_version):
                registry_version = None
            entries = result.get("entries")
            if not isinstance(entries, list):
                entries = []
            projected = []
            for entry in entries[:MAX_POLICY_REFS]:
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("id")
                entry_kind = entry.get("kind")
                if (not isinstance(entry_id, str) or not _ID.fullmatch(entry_id)
                        or entry_kind != kind):
                    continue
                ref = {
                    "id": entry_id,
                    "kind": kind,
                    "scope": entry.get("scope")[:256] if isinstance(entry.get("scope"), str) else None,
                    "version": entry.get("version")[:80] if isinstance(entry.get("version"), str) else None,
                    "status": entry.get("status")[:40] if isinstance(entry.get("status"), str) else None,
                    "source_state": entry.get("source_state")[:40] if isinstance(entry.get("source_state"), str) else "unknown",
                    "source_sha256": entry.get("source_sha256") if isinstance(entry.get("source_sha256"), str)
                        and _SHA256.fullmatch(entry["source_sha256"]) else None,
                    "enforcement_verified": False,
                }
                _no_credentials(_canonical_bytes(ref).decode("utf-8"), f"Governance-Referenz {entry_id}")
                projected.append(ref)
                prompt_refs.append(
                    f"- {kind}: {entry_id}; Version: {ref['version'] or 'unbekannt'}; "
                    f"Quellenstatus: {ref['source_state']}; Durchsetzung nicht bestätigt"
                )
            state = "available" if projected else "available_empty"
            if not projected and kind == "policy":
                missing.append({"id": "policy-registry:policy", "kind": kind,
                                "reason": "no_matching_policy_references"})
            records.append(_source_record(
                source_id=f"policy-registry:{kind}", kind=kind, state=state,
                version=registry_version, sha256=registry_version, host="policy-registry", path=None,
                details={"enforcement_verified": False, "read_only": True,
                         "count": len(projected), "truncated": len(entries) > MAX_POLICY_REFS,
                         "refs": projected},
            ))
        return records, missing, prompt_refs

    def compose(self, request: dict) -> dict:
        """Compose a bounded preview from a normalized request; all reads are non-mutating."""
        top = _strict_mapping(request, "request", {
            "schema", "target_client", "blueprint", "selected_skill_ids", "user_task",
            "task_refs", "task_selection_rule", "governance",
        })
        if top.get("schema") != REQUEST_SCHEMA:
            raise ValueError(f"schema muss {REQUEST_SCHEMA} sein")
        target = self._target(top.get("target_client"))
        blueprint, blueprint_source, role_source = self._blueprint(top.get("blueprint"))

        selected = top.get("selected_skill_ids", [])
        if (not isinstance(selected, list) or len(selected) > MAX_SKILLS
                or any(not isinstance(item, str) or not _SKILL_ID.fullmatch(item) for item in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError("Bis zu 30 unterschiedliche Skill-IDs auswählen")
        skill_ids = list(dict.fromkeys(blueprint["skills"] + selected))
        if len(skill_ids) > MAX_SKILLS:
            raise ValueError("Blueprint und Auswahl überschreiten zusammen 30 Skills")

        user_task = _text(top.get("user_task", ""), "user_task", MAX_USER_TASK_CHARS, required=False)
        _no_credentials(user_task, "Nutzerauftrag")
        task_refs = top.get("task_refs", [])
        if (not isinstance(task_refs, list) or len(task_refs) > MAX_TASK_REFS
                or any(type(task_id) is not int or task_id <= 0 for task_id in task_refs)
                or len(set(task_refs)) != len(task_refs)):
            raise ValueError("Bis zu 20 unterschiedliche positive Task-IDs angeben")
        selection_rule = _text(top.get("task_selection_rule", ""),
                               "task_selection_rule", 2_000, required=False)
        _no_credentials(selection_rule, "Task-Auswahlregel")
        if not user_task and not task_refs and not selection_rule:
            raise ValueError("Nutzerauftrag, Task-Referenzen oder eine Task-Auswahlregel erforderlich")

        request_governance = _strict_mapping(top.get("governance", {}), "governance",
                                             {"scope", "policy_query", "decision_query"})
        bp_governance = blueprint["governance"]
        scope = _text(request_governance.get("scope", bp_governance.get("scope", "BACH")),
                      "governance.scope", 256)
        _no_credentials(scope, "Governance-Geltungsbereich")
        # Queries are bounded and versioned as request metadata; canonical policy references
        # remain read-only and the adapter never returns policy bodies.
        queries = {
            "policy": _text(request_governance.get("policy_query", ""),
                             "governance.policy_query", 128, required=False),
            "decision": _text(request_governance.get("decision_query", ""),
                               "governance.decision_query", 128, required=False),
        }

        source_records = []
        missing = []
        blueprint_hash = _digest(blueprint_source)
        source_records.append(_source_record(
            source_id=f"blueprint:{blueprint['id']}", kind="blueprint", state="included",
            version=blueprint["version"], sha256=blueprint_hash, host=self.host, path=None,
            source_bytes=len(_canonical_bytes(blueprint_source)),
            included_chars=len(blueprint["persona_prompt"]),
            included_bytes=len(blueprint["persona_prompt"].encode("utf-8")),
            details={"kind_id": blueprint["kind"],
                     "snapshot_source": "blueprint_service._execution_blueprint",
                     "projection_only": True},
        ))
        role_hash = _digest(role_source)
        source_records.append(_source_record(
            source_id=f"role:{blueprint['persona_role']}", kind="role", state="included",
            version=blueprint["version"], sha256=role_hash, host=self.host, path=None,
            source_bytes=len(_canonical_bytes(role_source)),
            included_chars=len(blueprint["persona_prompt"]),
            included_bytes=len(blueprint["persona_prompt"].encode("utf-8")),
            details={"blueprint_sha256": blueprint_hash},
        ))

        skill_pins = []
        skill_display = []
        for skill_id in skill_ids:
            try:
                item = skill_source_service.read_skill(skill_id, roots=self.skill_roots)
            except KeyError:
                missing.append({"id": skill_id, "kind": "skill", "reason": "source_missing"})
                source_records.append(_source_record(
                    source_id=f"skill:{skill_id}", kind="skill", state="missing",
                    version=None, sha256=None, host=self.host, path=None,
                    details={"tools_granted": False},
                ))
                continue
            content = item.get("content")
            revision = item.get("source_version")
            if (not isinstance(content, str) or not isinstance(revision, str)
                    or not _SHA256.fullmatch(revision)):
                missing.append({"id": skill_id, "kind": "skill", "reason": "source_invalid"})
                source_records.append(_source_record(
                    source_id=f"skill:{skill_id}", kind="skill", state="invalid",
                    version=None, sha256=None, host=self.host, path=None,
                    details={"tools_granted": False},
                ))
                continue
            _no_credentials(content, f"Skill {skill_id}")
            skill_pins.append({"id": skill_id, "source_version": revision,
                               "version": str(item.get("version") or "")})
            skill_display.append({"id": skill_id, "content": content, "version": str(item.get("version") or "")})
            source_records.append(_source_record(
                source_id=f"skill:{skill_id}", kind="skill", state="included",
                version=item.get("version"), sha256=revision, host=self.host,
                path=item.get("source_path") if isinstance(item.get("source_path"), str) else None,
                source_bytes=len(content.encode("utf-8")), included_chars=len(content),
                included_bytes=len(content.encode("utf-8")),
                details={"tools_granted": False},
            ))
        if skill_pins:
            # Re-read through the existing pin validator. A changed source fails closed.
            pinned_instructions = skill_source_service.load_skill_instructions(
                skill_pins, roots=self.skill_roots)
            _no_credentials(pinned_instructions, "gebundene Skill-Anleitungen")
        else:
            pinned_instructions = ""

        task_sources, task_missing = self._read_tasks(task_refs)
        source_records.extend(item["source"] for item in task_sources)
        missing.extend(task_missing)
        governance_records, governance_missing, governance_refs = self._governance(
            scope=scope, consumer=target["client_id"], queries=queries)
        source_records.extend(governance_records)
        missing.extend(governance_missing)

        task_sections = []
        if user_task:
            task_sections.append("Nutzerauftrag:\n" + user_task)
        if task_sources:
            task_sections.append("Aktuelle Task-Referenzen (nur Kontext; keine Zuweisung oder Lease):\n" +
                                 "\n".join(item["display"] for item in task_sources))
        if task_missing:
            task_sections.append("Nicht aufgelöste Task-Referenzen: " + ", ".join(
                f"#{item['id']} ({item['reason']})" for item in task_missing))
        if selection_rule:
            task_sections.append("Vom Nutzer beschriebene Auswahlregel (nur Text; keine Queue-Suche oder Claim):\n" + selection_rule)
        task_sections.append(
            "Vor tatsächlicher Arbeit aktuellen Taskstatus, Abhängigkeiten, Identität und Locks prüfen; "
            "danach die zuständige native Lease beziehen. Diese Vorschau erteilt keine Berechtigung."
        )
        task_override = "\n\n".join(task_sections)

        # Advertise only skills whose exact source pin was re-read successfully.
        prompt_blueprint = {**blueprint, "skills": [pin["id"] for pin in skill_pins]}
        base_prompt = blueprint_service.synthesize_start_prompt(prompt_blueprint, task_override=task_override)
        prompt_parts = [
            "## Zielclient\n" + f"- Client: {target['name']} ({target['client_id']})\n"
            + f"- Zielhost: {target['host']}\n"
            + "- Dies ist nur eine Vorschau; den Client nicht automatisch starten.",
            base_prompt,
        ]
        if pinned_instructions:
            prompt_parts.append("## Ausgewählte Skill-Anleitungen\n\n" + pinned_instructions)
        prompt_parts.append("## Governance-Quellen und Geltungsbereich\n" +
            f"- Angefragter Geltungsbereich: {scope}\n" +
            ("\n".join(governance_refs) if governance_refs else "- Keine passenden Policy- oder Decision-Verweise verfügbar."))
        prompt_parts.append(
            "Policy- und Decision-Verweise sind lesende Metadaten; Durchsetzung wurde nicht bestätigt. "
            "Fehlende Governance-Quellen nicht durch Annahmen ersetzen. Vor externen Effekten aktuelle "
            "Governance und Freigaben prüfen. Promptzusammenstellung startet keinen Agenten und claimt keine Task."
        )
        prompt = "\n\n".join(prompt_parts).strip()
        _no_credentials(prompt, "zusammengesetzte Vorschau")
        prompt_bytes = len(prompt.encode("utf-8"))
        if len(prompt) > MAX_PROMPT_CHARS or prompt_bytes > MAX_PROMPT_CHARS * 4:
            raise ValueError("Zusammengesetzte Vorschau überschreitet das feste Größenbudget")

        user_task_record = _source_record(
            source_id="user-task", kind="user_instruction", state="included" if user_task else "empty",
            version=1, sha256=_digest(user_task) if user_task else None,
            host="request", path=None, source_bytes=len(user_task.encode("utf-8")),
            included_chars=len(user_task), included_bytes=len(user_task.encode("utf-8")),
        )
        source_records.append(user_task_record)
        if selection_rule:
            source_records.append(_source_record(
                source_id="task-selection-rule", kind="selection_rule", state="included",
                version=1, sha256=_digest(selection_rule), host="request", path=None,
                source_bytes=len(selection_rule.encode("utf-8")), included_chars=len(selection_rule),
                included_bytes=len(selection_rule.encode("utf-8")),
                details={"queue_scanned": False, "tasks_claimed": False},
            ))

        return {
            "schema": PREVIEW_SCHEMA,
            "status": "needs_sources" if missing else "ready_for_review",
            "target_client": target,
            "blueprint": {"id": blueprint["id"], "name": blueprint["name"],
                          "version": blueprint["version"], "sha256": blueprint_hash},
            "governance_scope": scope,
            "prompt": prompt,
            "prompt_chars": len(prompt),
            "prompt_bytes": prompt_bytes,
            "max_prompt_chars": MAX_PROMPT_CHARS,
            "sources": source_records,
            "missing": missing,
            "actions": {"agent_started": False, "task_claimed": False,
                        "queue_scanned": False, "clipboard_written": False},
            "limits": {"credential_scan": "heuristic_only",
                       "task_context": "reference_only", "governance_enforcement_verified": False},
        }
