"""Bounded learning sources and versioned drafts in the existing candidate stores.

Original NemoFold receipts and Hermes mutation manifests are source evidence.
The two extraction SKILL.md files are instructions, not executable extractors.
Source reading, selection and draft storage never publish or start anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from hub._services.learning_review_service import (
    LearningConflict, encoded, project_candidate, proposal_binding,
)
from hub._services.skill_source_service import (
    check_write_locks, read_skill, source_catalog,
)

MAX_SOURCE_BYTES = 1_000_000
MAX_EVENTS = 200
MAX_REQUEST_BYTES = 200_000
SOURCE_SCHEMA = "bach.learning-source.v1"
CONTRACT_SCHEMA = "bach.learning-candidate.v1"
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}")
_HASH = re.compile(r"[0-9a-f]{64}")
_PRIVATE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:Users|home)/|[\w.+-]+@[\w.-]+\.\w+|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b)"
)
_SECRET = re.compile(
    r"(?:\b(?:sk|ghp|github_pat|AKIA)[_-][A-Za-z0-9_-]{12,}|"
    r"(?i:authorization\s*:\s*bearer|api[_-]?key\s*[:=]|password\s*[:=]|"
    r"(?:access[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]))"
)
_CREDENTIAL_KEYS = frozenset({
    "apikey", "password", "passwd", "authorization", "credentials", "secret",
    "clientsecret", "accesstoken", "authtoken", "apitoken", "privatekey", "token",
})


def _credential_key(value):
    return isinstance(value, str) and re.sub(r"[-_\s]", "", value).casefold() in _CREDENTIAL_KEYS
_MARKER = re.compile(
    r"(?i:merk dir|beim nächsten mal|so machen wir|als skill|"
    r"wiederverwendbar|remember this|next time|reusable|nicht.*sondern)"
)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def configured_source_roots():
    """Host configuration grants read scope; request bodies cannot grant roots."""
    roots = json.loads(os.environ.get("BACH_LEARNING_SOURCE_ROOTS", "{}"))
    if not isinstance(roots, dict) or len(roots) > 16:
        raise ValueError("Lernquellen-Wurzeln müssen eine begrenzte Zuordnung sein")
    result = {}
    for key, value in roots.items():
        if not isinstance(key, str) or not _ID.fullmatch(key) or not isinstance(value, str):
            raise ValueError("Ungültige Lernquellen-Wurzel")
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir() or path.is_symlink():
            raise ValueError("Lernquellen-Wurzel fehlt oder ist nicht absolut")
        result[key] = path.resolve()
    return result


def _read(root, relative, *, expected_hash=None, maximum=MAX_SOURCE_BYTES):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Quelle braucht einen relativen Dateipfad")
    root = Path(root).resolve()
    path = root / relative
    if ".." in Path(relative).parts or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Quelle liegt außerhalb der freigegebenen Wurzel")
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Quelle fehlt oder überschreitet die Lesegrenze")
    # Read at most the configured bound, even if the file grows after stat().
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum or b"\x00" in raw:
        raise ValueError("Quelle überschreitet die Lesegrenze oder enthält NUL")
    raw.decode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    if expected_hash is not None and (
        not isinstance(expected_hash, str) or not _HASH.fullmatch(expected_hash) or sha != expected_hash
    ):
        raise LearningConflict("Quelleninhalt geändert; neue Freigabe mit aktuellem Hash erforderlich")
    return path, raw, sha


def _source(spec, roots):
    if not isinstance(spec, dict) or set(spec) - {
        "kind", "root", "path", "sha256", "entry_id"
    }:
        raise ValueError("Unbekannte Quellenfelder")
    root_id = spec.get("root")
    if not isinstance(root_id, str) or not _ID.fullmatch(root_id):
        raise ValueError("Lernquelle braucht eine gültige Wurzel-ID")
    if root_id not in roots:
        raise PermissionError("Lernquelle ist auf diesem Host nicht freigegeben")
    root = Path(roots[root_id])
    if not isinstance(spec.get("sha256"), str) or not _HASH.fullmatch(spec["sha256"]):
        raise ValueError("Expliziter Quellenhash erforderlich")
    path, raw, sha = _read(root, spec.get("path"), expected_hash=spec["sha256"])
    kind = spec.get("kind")
    events, provenance = [], {"adapter": kind, "adapter_version": 1}
    if kind == "session":
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("schema") != SOURCE_SCHEMA:
            raise ValueError("Begrenzter Sessionexport mit bach.learning-source.v1 erforderlich")
        session_id = value.get("session_id")
        rows = value.get("events")
        if (not isinstance(session_id, str) or not session_id or len(session_id) > 180
                or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_EVENTS):
            raise ValueError("Ungültiger Sessionexport")
        seen = set()
        for index, event in enumerate(rows):
            if (not isinstance(event, dict) or set(event) - {"id", "role", "content", "tool", "outcome"}
                    or not isinstance(event.get("id"), str) or not _ID.fullmatch(event["id"])
                    or event["id"] in seen or not isinstance(event.get("role"), str)
                    or event["role"] not in {"user", "assistant", "tool"}
                    or not isinstance(event.get("content"), str)
                    or any(k in event and (not isinstance(event[k], str) or len(event[k]) > 300)
                           for k in ("tool", "outcome"))):
                raise ValueError("Ungültiges oder doppeltes Sessionereignis")
            seen.add(event["id"])
            events.append({**event, "locator": {"session_id": session_id,
                "event_id": event["id"], "event_index": index}})
        provenance["evidence_kind"] = "supplied_session_export"
    elif kind == "hermes_ledger":
        entry_id = spec.get("entry_id")
        if not isinstance(entry_id, str) or not re.fullmatch(r"[0-9a-f]{12}", entry_id):
            raise ValueError("Explizite Hermes-Ledger-ID erforderlich")
        entries = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        selected = [(i, item) for i, item in enumerate(entries)
                    if isinstance(item, dict) and item.get("id") == entry_id]
        if len(selected) != 1:
            raise ValueError("Hermes-Ledger-Eintrag fehlt oder ist mehrdeutig")
        line, entry = selected[0]
        if entry.get("action") not in {"create", "edit", "update", "patch"}:
            raise ValueError("Dieser Hermes-Eintrag ist kein Pflegevorschlag")
        after = entry.get("after")
        if not isinstance(after, list) or not 1 <= len(after) <= 10:
            raise ValueError("Hermes-Nachhermanifest fehlt oder ist zu groß")
        manifests, total = [], len(raw)
        for item in after:
            if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                    or not isinstance(item["path"], str)):
                raise ValueError("Ungültiges Hermes-Dateimanifest")
            target = Path(item["path"])
            if not target.is_absolute() or not target.resolve().is_relative_to(root.resolve()):
                raise PermissionError("Hermes-Dateimanifest liegt außerhalb der freigegebenen Wurzel")
            _, data, file_hash = _read(root, str(target.relative_to(root)),
                                      expected_hash=item["sha256"], maximum=200_000)
            total += len(data)
            if total > MAX_SOURCE_BYTES:
                raise ValueError("Hermes-Quelle überschreitet die gesamte Lesegrenze")
            manifests.append({"path": str(target.relative_to(root)), "sha256": file_hash})
        provenance.update(evidence_kind="native_hermes_mutation_manifest",
                          ledger_is_authorization=False, manifest=manifests)
        evidence = entry.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ValueError("Ungültiger Hermes-Evidenzlokator")
        events = [{"id": entry_id, "role": "tool", "content": encoded({
            "action": entry["action"], "skill": entry.get("skill"), "manifest": manifests,
        }), "locator": {"entry_id": entry_id, "line": line + 1,
                       "session_id": evidence.get("session_id")}}]
    elif kind == "nemofold_voyage":
        # Call the original native reader, including its receipt and job-contract checks.
        try:
            import nemofold
            from nemofold import voyages
        except ImportError as exc:
            raise ValueError("Nativer NemoFold-Provider ist nicht installiert") from exc
        library = root / "run-reports" / "web-console" / "voyages"
        if path.parent.resolve() != library.resolve():
            raise ValueError("Quelle ist keine native NemoFold-Voyagebibliothek")
        receipt_relative = str((library / "_receipts" / path.name).relative_to(root))
        _, receipt_raw, receipt_hash = _read(root, receipt_relative, maximum=4096)
        value = voyages.VoyageStore(root, (str(root),)).load(path.stem, require_receipt=True)
        # A provider read must observe exactly the already approved file bytes.
        _read(root, spec["path"], expected_hash=sha)
        _read(root, receipt_relative, expected_hash=receipt_hash, maximum=4096)
        if json.loads(raw) != value or json.loads(receipt_raw).get("sha256") != sha:
            raise LearningConflict("NemoFold-Quelle während der Vertragsprüfung geändert")
        if value.get("voyage_id") != path.stem:
            raise LearningConflict("NemoFold-Voyageidentität passt nicht zur Quelldatei")
        provenance.update(evidence_kind="native_nemofold_saved_plan",
            provider_version=nemofold.__version__,
            reader_sha256=hashlib.sha256(Path(voyages.__file__).read_bytes()).hexdigest(),
            receipt_sha256=receipt_hash, executed=False)
        events = [{"id": value["voyage_id"], "role": "tool",
            "content": encoded(value), "locator": {"voyage_id": value["voyage_id"]}}]
    else:
        raise ValueError("Nicht unterstützte Lernquellenart")
    return {
        "kind": kind, "root": root_id, "path": spec["path"], "sha256": sha,
        "provenance": provenance, "events": events,
    }


def _guidance(roots=None):
    sources = []
    for skill_id in ("skill-extractor", "workflow-extract"):
        try:
            item = read_skill(skill_id, roots=roots)
        except KeyError as exc:
            raise ValueError("Aktuelle Extraktionsanleitung fehlt: " + skill_id) from exc
        references = []
        names = ("neutralisierung.md", "transcript-quellen.md") if skill_id == "skill-extractor" else ("automation-bausteine.md",)
        for name in names:
            if name in item["content"]:
                _, data, sha = _read(Path(item["source_path"]).parent, name, maximum=200_000)
                references.append({"path": name, "sha256": sha, "bytes_read": len(data),
                                   "evidence_kind": "instructions_read", "executed": False})
        sources.append({"id": skill_id, "version": item["version"],
                        "sha256": item["source_version"], "content": item["content"],
                        "references": references,
                        "evidence_kind": "instructions_read", "executed": False})
    return sources


def _neutralize(value, parameters):
    if not isinstance(parameters, list) or len(parameters) > 30:
        raise ValueError("Begrenzte Parameterliste erforderlich")
    replacements, definitions = [], []
    for parameter in parameters:
        if (not isinstance(parameter, dict) or set(parameter) != {"name", "value", "description"}
                or not isinstance(parameter["name"], str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,39}", parameter["name"])
                or _credential_key(parameter["name"])
                or not isinstance(parameter["value"], str) or not parameter["value"]
                or not isinstance(parameter["description"], str) or not parameter["description"].strip()
                or _SECRET.search(parameter["value"])):
            raise ValueError("Ungültiger Parameter; Credentials werden nicht übernommen")
        if parameter["name"] in {p["name"] for p in definitions}:
            raise ValueError("Doppelter Parametername")
        replacements.append((parameter["value"], "<" + parameter["name"] + ">"))
        definitions.append({"name": parameter["name"], "description": parameter["description"]})
    def walk(item):
        if isinstance(item, str):
            for original, placeholder in sorted(replacements, key=lambda pair: -len(pair[0])):
                item = item.replace(original, placeholder)
            if _PRIVATE.search(item) or _SECRET.search(item) or "\x00" in item:
                raise ValueError("Vorschlag enthält nicht neutralisierte Pfade, Accounts oder Credentials")
            return item
        if isinstance(item, list):
            return [walk(v) for v in item]
        if isinstance(item, dict):
            if any(not isinstance(k, str) or _credential_key(k) for k in item):
                raise ValueError("Vorschlag enthält Credentialfelder oder ungültige Schlüssel")
            return {walk(k): walk(v) for k, v in item.items()}
        if item is None or type(item) in {bool, int, float}:
            return item
        raise ValueError("Vorschlag enthält nicht unterstützte Werte")
    return walk(value), walk(definitions)


def _skill_metadata(body, name):
    """Parse the proposed frontmatter and bind its identity; no quality assertion."""
    import yaml
    if not isinstance(body, str):
        raise ValueError("Skill braucht SKILL.md-Text mit geschlossener Frontmatter")
    text = body.replace("\r\n", "\n")
    parts = text[4:].split("\n---\n", 1) if text.startswith("---\n") else []
    if len(parts) != 2 or not parts[1].strip():
        raise ValueError("Skill braucht geschlossene Frontmatter und einen Inhalt")
    try:
        meta = yaml.safe_load(parts[0])
    except yaml.YAMLError as exc:
        raise ValueError("Ungültige Skill-Frontmatter") from exc
    if (not isinstance(meta, dict) or meta.get("name") != name
            or not isinstance(meta.get("version"), str) or not meta["version"].strip()
            or len(meta["version"]) > 80):
        raise ValueError("Skillidentität oder Versionsnummer passt nicht zum Kandidaten")
    return {"name": name, "version": meta["version"]}


def _neighbors(proposal, db_path, roots):
    """Read current native sources rather than comparing only catalogue names."""
    items = []
    if proposal["kind"] in {"skill", "rule"}:
        catalog = source_catalog(roots)
        terms = set(re.findall(r"\w+", proposal["name"].casefold() + " " + proposal["trigger"].casefold()))
        ranked = sorted(catalog, key=lambda key: (
            -len(terms & set(re.findall(r"\w+", (key + " " + catalog[key]["role"]).casefold()))), key))
        target = proposal["dedup"].get("target")
        ids = ([target] if target in catalog else []) + ranked
        for skill_id in dict.fromkeys(ids):
            if len(items) == 3:
                break
            source = read_skill(skill_id, roots=roots)
            items.append({"id": skill_id, "basis_version": source["source_version"],
                          "content": source["content"], "kind": "skill"})
    else:
        from hub._services.chat.sequence_store import SequenceStore
        # Native catalogue is explicitly read-only, including absent-schema handling.
        chains = SequenceStore(db_path).chains()
        if len(chains) > 1000:
            raise ValueError("Kettenkatalog überschreitet die Lesegrenze")
        target = proposal["dedup"].get("target")
        for chain in sorted(chains, key=lambda c: (c["id"] != target, c["name"]))[:3]:
            items.append({"id": chain["id"], "basis_version": chain["version"],
                          "content": encoded(chain), "kind": "chain"})
    return items


class LearningSourceService:
    def __init__(self, db_path, *, source_roots=None, skill_roots=None, write_guard=None):
        self.db_path = Path(db_path)
        self.roots = configured_source_roots() if source_roots is None else source_roots
        self.skill_roots = skill_roots
        self.write_guard = write_guard or (lambda: check_write_locks(self.db_path))

    def analyze(self, payload, *, actor, persist=False):
        try:
            return self._analyze(payload, actor=actor, persist=persist)
        except RecursionError as exc:
            raise ValueError("Analyseauftrag enthält zu tief verschachtelte Lernquellen- oder Vorschlagsdaten") from exc

    def _analyze(self, payload, *, actor, persist=False):
        if not isinstance(payload, dict) or set(payload) - {"source", "proposal", "expected_revision", "expected_digest"}:
            raise ValueError("Unbekannte Analysefelder")
        if len(encoded(payload).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("Analyseauftrag überschreitet die Größe")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 180:
            raise ValueError("Authentifizierter Analyseakteur erforderlich")
        cas_keys = {"expected_revision", "expected_digest"} & set(payload)
        if cas_keys and (len(cas_keys) != 2 or type(payload["expected_revision"]) is not int
                or payload["expected_revision"] <= 0 or not isinstance(payload["expected_digest"], str)
                or not _HASH.fullmatch(payload["expected_digest"])):
            raise ValueError("CAS braucht eine positive ganzzahlige Revision und einen SHA-256-Digest")
        source = _source(payload.get("source"), self.roots)
        proposal = payload.get("proposal")
        if proposal is None:
            return {"status": "no_candidate", "reason": "Kein ausgewählter Lernvorschlag",
                    "source": {k: v for k, v in source.items() if k != "events"},
                    "persisted": False, "targets_published": False}
        fields = {"kind", "name", "trigger", "reason", "body", "event_ids", "parameters",
                  "side_effects", "required_capabilities", "dedup"}
        if not isinstance(proposal, dict) or set(proposal) != fields:
            raise ValueError("Vollständiger strukturierter Kandidatenvorschlag erforderlich")
        if (not isinstance(proposal["kind"], str) or proposal["kind"] not in {"skill", "chain", "rule"}
                or not isinstance(proposal["name"], str) or not _ID.fullmatch(proposal["name"])
                or not all(isinstance(proposal[k], str) and proposal[k].strip() and len(proposal[k]) <= 12000
                           for k in ("reason", "trigger"))):
            raise ValueError("Ungültiger Kandidatentyp, Name oder Begründung")
        ids = proposal["event_ids"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_EVENTS
                or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids)):
            raise ValueError("Ausgewählte eindeutige Ereignislokatoren erforderlich")
        by_id = {event["id"]: event for event in source["events"]}
        if set(ids) - set(by_id):
            raise ValueError("Vorschlag verweist auf nicht gelesene Ereignisse")
        selected = [by_id[event_id] for event_id in ids]
        signal = source["kind"] != "session" or any(
            e["role"] == "user" and _MARKER.search(e["content"]) for e in selected)
        if not signal:
            return {"status": "no_candidate", "reason": "Kein belegtes Auswahlsignal in den gelesenen Ereignissen",
                    "persisted": False, "targets_published": False}
        for field in ("side_effects", "required_capabilities"):
            if (not isinstance(proposal[field], list) or len(proposal[field]) > 30
                    or any(not isinstance(v, str) or not v.strip() or len(v) > 300 for v in proposal[field])):
                raise ValueError("Fähigkeiten und Nebenwirkungen brauchen begrenzte Textlisten")
        dedup = proposal["dedup"]
        if (not isinstance(dedup, dict) or set(dedup) - {"decision", "reason", "target", "basis_version"}
                or not isinstance(dedup.get("decision"), str) or dedup["decision"] not in {"new", "extend", "covered"}
                or not isinstance(dedup.get("reason"), str) or not dedup["reason"].strip()):
            raise ValueError("Begründete Dedup-Entscheidung erforderlich")
        guides = _guidance(self.skill_roots)
        neighbors = _neighbors(proposal, self.db_path, self.skill_roots)
        basis = "0"
        if dedup["decision"] in {"extend", "covered"}:
            target = next((n for n in neighbors if n["id"] == dedup.get("target")), None)
            if target is None or dedup.get("basis_version") != target["basis_version"]:
                raise LearningConflict("Zielquelle oder Basisversion fehlt bzw. wurde geändert")
            basis = target["basis_version"]
        elif "target" in dedup or "basis_version" in dedup:
            raise ValueError("Neuanlage darf kein unbegründetes Erweiterungsziel tragen")
        if dedup["decision"] == "covered":
            return {"status": "no_candidate", "reason": "Vorhandene Fähigkeit deckt den Vorschlag ab",
                    "persisted": False, "targets_published": False,
                    "target": dedup["target"], "basis_version": basis}
        clean, parameters = _neutralize({k: v for k, v in proposal.items()
            if k not in {"parameters", "event_ids"}}, proposal["parameters"])
        if clean["kind"] == "skill":
            _skill_metadata(clean["body"], clean["name"])
        elif clean["kind"] == "chain":
            from hub._services.chat.sequence_store import definition
            clean["body"] = definition(clean["body"])
            if clean["body"]["name"] != clean["name"]:
                raise ValueError("Kettenidentität passt nicht zum Kandidaten")
        elif not isinstance(clean["body"], dict) or not clean["body"]:
            raise ValueError("Regel braucht einen strukturierten Vorschlag")
        contract = {
            "schema": CONTRACT_SCHEMA, "kind": clean["kind"], "name": clean["name"],
            "proposal": clean, "parameters": parameters, "basis_version": basis,
            "source": {k: v for k, v in source.items() if k != "events"},
            "events": [{"locator": e["locator"], "sha256": digest({
                k: v for k, v in e.items() if k != "locator"})} for e in selected],
            "extractors": [{k: v for k, v in guide.items() if k != "content"} for guide in guides],
            "neighbors": [{k: v for k, v in n.items() if k != "content"} for n in neighbors],
            "selection": {"kind": "supplied_proposal_with_observed_signal",
                          "semantic_review_required": True, "empirically_validated": False},
            "scheduler": {"configured": False, "separate_approval_required": True},
            "tools_granted": False, "targets_published": False,
        }
        result = {"status": "candidate", "contract": contract, "contract_digest": digest(contract),
                  "persisted": False, "targets_published": False}
        if persist:
            result.update(self._persist(contract, payload))
        return result

    def _persist(self, contract, request):
        # Candidate storage is the only side effect. Never create a second authority.
        self.write_guard()
        if not self.db_path.is_file():
            raise ValueError("Kanonische BACH-Datenbank fehlt")
        from hub._services.hermes_distillation_service import HermesDistillationService
        from hub._services.nemofold_workflow_service import NemoFoldWorkflowService
        provider = "hermes" if contract["kind"] == "skill" else "nemofold"
        if provider == "hermes":
            service = HermesDistillationService(self.db_path)
            service.ensure_schema()
            table, key_field = "hermes_skill_candidates", "name"
        else:
            service = NemoFoldWorkflowService(str(self.db_path))
            table, key_field = "nemofold_workflow_candidates", "chain_name"
        name = contract["name"]
        proposal = contract["proposal"]
        if provider == "hermes":
            metadata = _skill_metadata(proposal["body"], name)
            item = {"name": name, "category": "learning", "role": "",
                "version": metadata["version"], "description": proposal["trigger"],
                "trigger_phrases": encoded([proposal["trigger"]]), "frontmatter": encoded(metadata),
                "content": proposal["body"], "confidence": None, "source_session": "",
                "noise_reduction_ratio": None, "lessons_draft_json": "[]"}
        else:
            item = {"chain_name": name, "title": name, "description": proposal["trigger"],
                "trigger_type": "manual", "steps_json": encoded(
                    proposal["body"]["steps"] if contract["kind"] == "chain" else []),
                "confidence_score": None, "tuv_status": "needs_review",
                "tuv_report_json": encoded({"empirically_validated": False}),
                "provenance_json": encoded({"candidate_kind": contract["kind"]})}
        item["candidate_contract_json"] = encoded(contract)
        bound, sha = proposal_binding(provider, item)
        stamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(f"SELECT * FROM {table} WHERE {key_field}=?", (name,)).fetchall()
            if len(prior) > 1:
                raise LearningConflict("Mehrdeutiger Kandidatenname; Bestand zuerst klären")
            if prior:
                previous = dict(prior[0])
                if project_candidate(provider, previous)["review_state"] == "legacy_unverified":
                    raise LearningConflict("Bestehender Kandidatenvertrag ist nicht verifizierbar")
                if "expected_revision" in request and (
                        previous["candidate_revision"] != request["expected_revision"]
                        or previous["candidate_digest"] != request["expected_digest"]):
                    raise LearningConflict("Kandidatenversion geändert")
                if previous["proposal_json"] == bound and previous["candidate_digest"] == sha:
                    if not project_candidate(provider, previous)["review_state"] == "legacy_unverified":
                        return {"persisted": True, "provider": provider, "candidate_id": previous["id"],
                            "candidate_revision": previous["candidate_revision"], "candidate_digest": sha,
                            "replayed": True}
                if (not previous.get("candidate_contract_json") or previous["status"] == "approved"
                        or (provider == "nemofold" and previous["promoted_to_chain_id"] is not None)
                        or previous["candidate_revision"] != request.get("expected_revision")
                        or previous["candidate_digest"] != request.get("expected_digest")):
                    raise LearningConflict("Kandidatenname belegt oder Kandidatenversion geändert")
                revision = previous["candidate_revision"] + 1
                resets = ",approved_at=NULL,approved_by=NULL,rejection_reason=NULL" if provider == "hermes" else ",reviewed_by=NULL,review_notes=NULL,updated_at=?"
                keys = tuple(item)
                args = [*item.values(), revision, sha, bound]
                if provider == "nemofold":
                    args.append(stamp)
                updated = conn.execute(f"UPDATE {table} SET " + ",".join(f"{key}=?" for key in keys)
                    + f",candidate_revision=?,candidate_digest=?,proposal_json=?,status='pending'{resets} WHERE id=?",
                    (*args, previous["id"]))
                if (updated.rowcount != 1 or conn.execute(
                        f"SELECT 1 FROM {table} WHERE id=?", (previous["id"],)).fetchone() is None):
                    raise LearningConflict("Kandidatenzeile beim Update verschwunden; keine Neuanlage")
                candidate_id = previous["id"]
            else:
                if "expected_revision" in request:
                    raise LearningConflict("Erwarteter Update-Kandidat fehlt; keine Neuanlage")
                keys = tuple(item)
                revision = 1
                cursor = conn.execute(f"INSERT INTO {table} ({','.join(keys)},candidate_revision,"
                    f"candidate_digest,proposal_json,status,created_at) VALUES "
                    f"({','.join('?' for _ in keys)},?,?,?,'pending',?)",
                    (*item.values(), revision, sha, bound, stamp))
                candidate_id = cursor.lastrowid
            self.write_guard()
        return {"persisted": True, "provider": provider, "candidate_id": candidate_id,
                "candidate_revision": revision, "candidate_digest": sha, "replayed": False}
