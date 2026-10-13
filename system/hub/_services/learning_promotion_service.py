"""Explicit, recoverable publication of reviewed learning candidates.

Content review remains a separate, version-bound decision. This module only
publishes an exact reviewed revision through existing native target stores.
It never grants tools, starts agents, or claims empirical validation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from . import skill_source_service
from .learning_review_service import (
    LearningConflict, LearningNotFound, LearningPromotionUnavailable,
    encoded, project_candidate,
)
from .chat.sequence_store import SequenceStore, definition as sequence_definition

_TABLES = {
    "hermes": "hermes_skill_candidates",
    "nemofold": "nemofold_workflow_candidates",
}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REQUEST = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_CATEGORY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}$")
_SKILL_TRANSFORM_SCHEMA = "bach.learning.hermes-skill-frontmatter.v1"


class LearningPromotionConflict(LearningConflict):
    code = "learning_promotion_conflict"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_json(value: Any) -> str:
    return _sha(encoded(value).encode("utf-8"))


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class LearningPromotionService:
    """Promote one reviewed target at a time; all state remains in the BACH DB."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        write_root: Path | None = None,
        skill_roots: list[Path] | None = None,
        write_guard: Callable[[Path], None] | None = None,
        sequence_adapter: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        sequence_store: Any | None = None,
        after_skill_write: Callable[[], None] | None = None,
    ) -> None:
        if db_path is None:
            from hub.bach_paths import BACH_DB
            db_path = BACH_DB
        self.db_path = Path(db_path).expanduser().resolve()
        self.write_root = Path(write_root).expanduser().resolve() if write_root else None
        self._skill_roots = [Path(item).expanduser().resolve() for item in skill_roots] if skill_roots else None
        self.write_guard = write_guard
        self.sequence_adapter = sequence_adapter
        self.sequence_store = sequence_store
        self._after_skill_write = after_skill_write

    @contextmanager
    def _write(self):
        if not self.db_path.is_file():
            raise RuntimeError("Kanonische BACH-Datenbank fehlt")
        guard = self.write_guard or skill_source_service.check_write_locks
        guard(self.db_path)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_schema(conn)
            yield conn
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute("""CREATE TABLE IF NOT EXISTS learning_promotions (
            provider TEXT NOT NULL,
            request_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            candidate_id INTEGER NOT NULL,
            candidate_revision INTEGER NOT NULL,
            candidate_digest TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            source_request_id TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL,
            state TEXT NOT NULL,
            target_key TEXT NOT NULL DEFAULT '',
            expected_target_version TEXT NOT NULL DEFAULT '',
            previous_target_version TEXT NOT NULL DEFAULT '',
            target_version TEXT NOT NULL DEFAULT '',
            target_payload_json TEXT NOT NULL DEFAULT '{}',
            receipt_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, request_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS learning_promotion_items (
            provider TEXT NOT NULL,
            promotion_request_id TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            target_key TEXT NOT NULL,
            target_digest TEXT NOT NULL,
            target_snapshot_json TEXT NOT NULL,
            PRIMARY KEY(provider,promotion_request_id,target_kind,ordinal),
            UNIQUE(provider,promotion_request_id,target_key)
        )""")
        conn.execute("""CREATE INDEX IF NOT EXISTS learning_promotions_candidate_idx
            ON learning_promotions(provider,candidate_id,candidate_revision,target_kind,action,state)""")

    @staticmethod
    def _validate_identity(candidate_id, expected_revision, expected_digest, request_id, actor):
        if type(candidate_id) is not int or candidate_id <= 0:
            raise ValueError("Gültige Kandidaten-ID erforderlich")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Aktuelle Kandidatenrevision erforderlich")
        if not isinstance(expected_digest, str) or not _DIGEST.fullmatch(expected_digest):
            raise ValueError("Aktueller Kandidatendigest erforderlich")
        if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
            raise ValueError("Explizite Promotions-Request-ID erforderlich")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 180 or "\x00" in actor:
            raise ValueError("Authentifizierter Promotionsakteur erforderlich")

    def _candidate(self, conn, provider, candidate_id, expected_revision, expected_digest):
        if provider not in _TABLES:
            raise ValueError("Unbekannter Lernanbieter")
        try:
            row = conn.execute(
                f"SELECT * FROM {_TABLES[provider]} WHERE id=?", (candidate_id,)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise LearningNotFound(f"Kandidat #{candidate_id} nicht gefunden") from exc
        if row is None:
            raise LearningNotFound(f"Kandidat #{candidate_id} nicht gefunden")
        item = project_candidate(provider, row)
        if (item.get("review_state") != "reviewed" or item.get("status") != "reviewed"
                or item.get("candidate_revision") != expected_revision
                or item.get("candidate_digest") != expected_digest):
            raise LearningPromotionUnavailable(
                "Nur die exakt gebundene, aktuell inhaltsgeprüfte Kandidatenrevision kann veröffentlicht werden."
            )
        proof = conn.execute("""SELECT receipt_json FROM learning_candidate_reviews
            WHERE provider=? AND candidate_id=? AND candidate_revision=?
              AND candidate_digest=? AND decision='reviewed'
            ORDER BY created_at DESC LIMIT 1""",
            (provider, candidate_id, expected_revision, expected_digest)).fetchone()
        if proof is None:
            raise LearningPromotionUnavailable("Ein persistiertes Review-Receipt für diese Revision fehlt.")
        try:
            receipt = json.loads(proof["receipt_json"])
        except (ValueError, TypeError):
            raise LearningPromotionUnavailable("Das Inhaltsreview-Receipt ist ungültig.") from None
        if (receipt.get("review_scope") != "candidate_content_only"
                or receipt.get("empirically_validated") is not False
                or receipt.get("targets_published") is not False):
            raise LearningPromotionUnavailable("Das gespeicherte Review-Receipt verletzt den Inhaltsreview-Vertrag.")
        return {**item, "_review_receipt": receipt}

    @staticmethod
    def _parse_json(value, default):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return default
        return value if value is not None else default

    def _write_root_path(self) -> Path:
        return Path(self.write_root or skill_source_service.user_skills_root()).expanduser().resolve()

    def _target_skill_binding(self, skill_id: str, source_version: str) -> dict:
        return {
            "source_kind": "local_override",
            "source_root": str(self._write_root_path()),
            "relative_path": f"{skill_id}/SKILL.md",
            "source_version": source_version,
        }

    def _roots(self) -> list[Path]:
        write_root = self._write_root_path()
        roots = self._skill_roots if self._skill_roots is not None else skill_source_service.skill_roots()
        return list(dict.fromkeys([write_root, *roots]))

    def _skill_binding(self, skill_id: str, *, exclude_write_root: bool = False) -> dict:
        write_root = self._write_root_path()
        roots = self._roots()
        if exclude_write_root:
            roots = [root for root in roots
                     if Path(root).expanduser().resolve() != write_root]
        item = skill_source_service.source_catalog(roots).get(skill_id)
        if item is None:
            return {"source_kind": "absent", "source_root": None,
                    "relative_path": None, "source_version": "0"}
        root = Path(item["root"]).expanduser().resolve()
        path = Path(item["path"]).resolve()
        try:
            relative_path = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise LearningPromotionConflict("Skill-Quelle liegt außerhalb ihrer nativen Root-Bindung.") from exc
        return {
            "source_kind": "local_override" if root == write_root else "underlay",
            "source_root": str(root),
            "relative_path": relative_path,
            "source_version": item["source_version"],
        }

    def _skill_version(self, skill_id: str) -> str:
        return self._skill_binding(skill_id)["source_version"]

    def _skill_payload(self, candidate: Mapping[str, Any]) -> tuple[str, str, str]:
        skill_id = candidate.get("name")
        content = candidate.get("content")
        if not isinstance(skill_id, str) or not _SKILL_ID.fullmatch(skill_id):
            raise LearningPromotionUnavailable("Kandidatenname ist keine native Skill-ID.")
        if not isinstance(content, str) or not content.strip() or "\x00" in content:
            raise LearningPromotionUnavailable("Der geprüfte Kandidat enthält keinen gültigen Skill-Inhalt.")
        frontmatter = self._parse_json(candidate.get("frontmatter"), {})
        if not isinstance(frontmatter, dict) or frontmatter.get("name") != skill_id:
            raise LearningPromotionUnavailable("Frontmatter-JSON ist nicht an die Kandidaten-ID gebunden.")
        for key in ("version", "category", "description"):
            if frontmatter.get(key) != candidate.get(key):
                raise LearningPromotionUnavailable(f"Frontmatter-JSON passt bei {key} nicht zum Kandidaten.")
        lines = content.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise LearningPromotionUnavailable("SKILL.md-Kandidat enthält keinen gebundenen YAML-Header.")
        closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if closing is None:
            raise LearningPromotionUnavailable("SKILL.md-Kandidat hat keinen abgeschlossenen YAML-Header.")
        raw_header = "".join(lines[1:closing])
        try:
            import yaml
        except ImportError as exc:
            raise LearningPromotionUnavailable("Sicherer YAML-Serializer für native SKILL.md fehlt.") from exc

        class UniqueSafeLoader(yaml.SafeLoader):
            pass

        def construct_unique_mapping(loader, node, deep=False):
            loader.flatten_mapping(node)
            mapping = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                try:
                    duplicate = key in mapping
                except TypeError as exc:
                    raise yaml.constructor.ConstructorError(
                        "while reading SKILL.md frontmatter", node.start_mark,
                        "frontmatter mapping keys must be scalar", key_node.start_mark,
                    ) from exc
                if duplicate:
                    raise yaml.constructor.ConstructorError(
                        "while reading SKILL.md frontmatter", node.start_mark,
                        "duplicate frontmatter key", key_node.start_mark,
                    )
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        UniqueSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
        )
        try:
            parsed_header = yaml.load(raw_header, Loader=UniqueSafeLoader)
        except yaml.YAMLError as parse_error:
            # Die einzige Legacy-Ausnahme ist eine ungequotierte einzeilige
            # Hermes-Beschreibung mit Doppelpunkt; ihr Rohwert muss exakt dem
            # gebundenen Review-JSON entsprechen.
            description = frontmatter.get("description")
            header_lines = raw_header.splitlines(keepends=True)
            description_indexes = [
                index for index, line in enumerate(header_lines)
                if re.match(r"^description:[ \t]*", line)
            ]
            if (not isinstance(description, str) or "\n" in description or "\r" in description
                    or len(description_indexes) != 1):
                raise LearningPromotionUnavailable(
                    "SKILL.md-YAML-Header ist ungültig und nicht exakt an das geprüfte Frontmatter gebunden."
                ) from parse_error
            index = description_indexes[0]
            line = header_lines[index]
            line_content = line.removesuffix("\r\n").removesuffix("\n").removesuffix("\r")
            raw_description = line_content.split(":", 1)[1].lstrip(" \t")
            if raw_description != description:
                raise LearningPromotionUnavailable(
                    "Ungültiger SKILL.md-Beschreibungstext unterscheidet sich vom geprüften Frontmatter."
                ) from parse_error
            ending = line[len(line_content):]
            quoted_description = yaml.safe_dump(
                {"description": description}, sort_keys=False, allow_unicode=True,
                default_flow_style=False, width=4096,
            ).splitlines()[0]
            header_lines[index] = quoted_description + ending
            try:
                parsed_header = yaml.load("".join(header_lines), Loader=UniqueSafeLoader)
            except yaml.YAMLError as exc:
                raise LearningPromotionUnavailable(
                    "SKILL.md-YAML-Header ist nach der eng begrenzten Legacy-Prüfung ungültig."
                ) from exc
        if not isinstance(parsed_header, dict) or parsed_header != frontmatter:
            raise LearningPromotionUnavailable(
                "SKILL.md-YAML-Header und gebundenes Frontmatter-JSON unterscheiden sich."
            )
        try:
            rendered_header = yaml.safe_dump(
                frontmatter, sort_keys=True, allow_unicode=True,
                default_flow_style=False, width=4096,
            )
        except yaml.YAMLError as exc:
            raise LearningPromotionUnavailable("Native SKILL.md-Frontmatter-Kanonisierung ist fehlgeschlagen.") from exc
        if not isinstance(rendered_header, str) or not rendered_header:
            raise LearningPromotionUnavailable("Native SKILL.md-Kanonisierung ist fehlgeschlagen.")
        body = "".join(lines[closing + 1:])
        canonical = "---\n" + rendered_header.rstrip("\n") + "\n---\n" + body
        raw = canonical.encode("utf-8")
        if not raw.strip() or len(raw) > skill_source_service.MAX_SOURCE_BYTES:
            raise LearningPromotionUnavailable("Die kanonische SKILL.md überschreitet die native Größengrenze.")
        metadata = skill_source_service._metadata(canonical)
        if metadata.get("name") != skill_id:
            raise LearningPromotionUnavailable("Kanonisches SKILL.md-Frontmatter ist ungültig.")
        return skill_id, canonical, _sha(raw)

    def _save_skill(self, skill_id, content, expected_version):
        kwargs = {"roots": self._roots(), "write_root": self._write_root_path()}
        if self.write_guard is not None:
            kwargs["guard"] = self.write_guard
        try:
            return skill_source_service.save_skill(skill_id, content, expected_version, **kwargs)
        except RuntimeError as exc:
            if str(exc) == "skill_source_version_conflict":
                raise LearningPromotionConflict(
                    "Skill-Quelle änderte sich während des nativen CAS-Schreibvorgangs."
                ) from exc
            raise

    def _delete_skill(self, skill_id, expected_version):
        kwargs = {"roots": self._roots(), "write_root": self._write_root_path()}
        if self.write_guard is not None:
            kwargs["guard"] = self.write_guard
        try:
            return skill_source_service.delete_skill(skill_id, expected_version, **kwargs)
        except RuntimeError as exc:
            if str(exc) == "skill_source_version_conflict":
                raise LearningPromotionConflict(
                    "Skill-Quelle änderte sich während des nativen CAS-Löschvorgangs."
                ) from exc
            raise

    def _restore_skill(self, skill_id, previous_version, published_version, previous_binding, target_binding):
        binding_keys = {"source_kind", "source_root", "relative_path", "source_version"}
        if (not isinstance(previous_binding, dict)
                or set(previous_binding) != binding_keys
                or previous_binding.get("source_version") != previous_version):
            raise LearningPromotionConflict("Vorherige native Skill-Root-Bindung fehlt oder ist ungültig.")
        if (not isinstance(target_binding, dict)
                or set(target_binding) != binding_keys
                or target_binding.get("source_kind") != "local_override"
                or target_binding.get("source_version") != published_version
                or target_binding != self._target_skill_binding(skill_id, published_version)):
            raise LearningPromotionConflict(
                "Konfigurierte Skill-Ziel-Root oder relativer Zielpfad weicht von der Promotionsbindung ab."
            )

        current = self._skill_binding(skill_id)
        if current == previous_binding:
            return {"already_restored": True}
        if current != target_binding:
            raise LearningPromotionConflict(
                "Skill-Zielquelle, Write-Root oder Digest änderte sich; fremde Root bleibt unverändert."
            )

        if previous_binding["source_kind"] in {"underlay", "absent"}:
            underlay = self._skill_binding(skill_id, exclude_write_root=True)
            if underlay != previous_binding:
                raise LearningPromotionConflict(
                    "Die darunterliegende native Skill-Quelle änderte sich; der lokale Override bleibt erhalten."
                )
            self._delete_skill(skill_id, published_version)
        elif previous_binding["source_kind"] == "local_override":
            if previous_binding["source_root"] != target_binding["source_root"]:
                raise LearningPromotionConflict("Vorheriger lokaler Skill-Override verweist auf eine andere Root.")
            historical = skill_source_service.read_skill_history(
                skill_id, previous_version, write_root=self._write_root_path()
            )
            self._save_skill(skill_id, historical["content"], published_version)
        else:
            raise LearningPromotionConflict("Vorherige native Skill-Quelle hat einen unbekannten Typ.")

        restored = self._skill_binding(skill_id)
        if restored != previous_binding:
            raise LearningPromotionConflict(
                "Native Skill-Rücknahme stimmt nicht mit der gebundenen Vorversion und Root überein."
            )
        return {"already_restored": False}

    @staticmethod
    def _request_row(conn, provider, request_id, request_digest):
        row = conn.execute(
            "SELECT * FROM learning_promotions WHERE provider=? AND request_id=?",
            (provider, request_id)).fetchone()
        if row is not None and row["request_digest"] != request_digest:
            raise LearningPromotionConflict("Promotions-Request-ID wurde anders verwendet.")
        return row

    @staticmethod
    def _receipt(row) -> dict:
        try:
            value = json.loads(row["receipt_json"])
        except (ValueError, TypeError):
            value = {}
        if not value:
            value = {"status": row["state"], "request_id": row["request_id"],
                     "target_kind": row["target_kind"], "targets_published": False}
        return {**value, "replayed": True}

    @staticmethod
    def _insert_operation(conn, *, provider, request_id, action, target_kind,
                          candidate_id, revision, digest, request_digest, actor,
                          state="prepared", source_request_id="", target_key="",
                          expected_target_version="", previous_target_version="",
                          target_version="", target_payload=None):
        stamp = _stamp()
        conn.execute("""INSERT INTO learning_promotions (
            provider,request_id,action,target_kind,candidate_id,candidate_revision,
            candidate_digest,request_digest,source_request_id,actor,state,target_key,
            expected_target_version,previous_target_version,target_version,
            target_payload_json,receipt_json,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            provider,request_id,action,target_kind,candidate_id,revision,digest,
            request_digest,source_request_id,actor,state,target_key,
            str(expected_target_version),str(previous_target_version),str(target_version),
            encoded(target_payload if target_payload is not None else {}), "{}", stamp, stamp,
        ))

    @staticmethod
    def _update_operation(conn, provider, request_id, *, state, receipt, target_version=None):
        stamp = _stamp()
        if target_version is None:
            conn.execute("""UPDATE learning_promotions SET state=?,receipt_json=?,updated_at=?
                WHERE provider=? AND request_id=?""",
                (state, encoded(receipt), stamp, provider, request_id))
        else:
            conn.execute("""UPDATE learning_promotions SET state=?,target_version=?,receipt_json=?,updated_at=?
                WHERE provider=? AND request_id=?""",
                (state,str(target_version),encoded(receipt),stamp,provider,request_id))

    def promote(self, provider: str, candidate_id: int, *, target_kind: str,
                expected_revision: int, expected_digest: str, request_id: str,
                expected_target_version: str | int, actor: str) -> dict:
        self._validate_identity(candidate_id, expected_revision, expected_digest, request_id, actor)
        if target_kind == "skill" and provider == "hermes":
            return self._promote_skill(candidate_id, expected_revision, expected_digest,
                request_id, expected_target_version, actor)
        if target_kind == "lessons" and provider == "hermes":
            return self._promote_lessons(candidate_id, expected_revision, expected_digest,
                request_id, expected_target_version, actor)
        if target_kind == "sequence" and provider == "nemofold":
            return self._promote_sequence(candidate_id, expected_revision, expected_digest,
                request_id, expected_target_version, actor)
        raise LearningPromotionUnavailable(
            "Dieser Zieltyp ist für den Lernanbieter nicht freigegeben."
        )

    def _promote_skill(self, candidate_id, revision, digest, request_id, expected_version, actor):
        if (not isinstance(expected_version, str)
                or (expected_version != "0" and not _DIGEST.fullmatch(expected_version))):
            raise ValueError("Skill-Zielversion als SHA256 oder '0' erforderlich")
        request_digest = _digest_json({
            "action":"promote","provider":"hermes","candidate_id":candidate_id,
            "candidate_revision":revision,"candidate_digest":digest,"target_kind":"skill",
            "expected_target_version":expected_version,"actor":actor,
        })
        with self._write() as conn:
            prior = self._request_row(conn, "hermes", request_id, request_digest)
            if prior is not None:
                if prior["state"] != "prepared":
                    return self._receipt(prior)
            else:
                candidate = self._candidate(conn, "hermes", candidate_id, revision, digest)
                skill_id, content, target_digest = self._skill_payload(candidate)
                previous_binding = self._skill_binding(skill_id)
                target_binding = self._target_skill_binding(skill_id, target_digest)
                actual = previous_binding["source_version"]
                if actual != expected_version:
                    raise LearningPromotionConflict("Skill-Zielversion geändert; aktuelle Version neu laden.")
                active = conn.execute("""SELECT request_id,state FROM learning_promotions
                    WHERE provider='hermes' AND candidate_id=? AND candidate_revision=?
                      AND target_kind='skill' AND action='promote'
                      AND state IN ('prepared','published')""", (candidate_id,revision)).fetchone()
                if active is not None:
                    raise LearningPromotionConflict("Diese Kandidatenrevision besitzt bereits eine aktive Skill-Promotion.")
                self._insert_operation(conn, provider="hermes", request_id=request_id,
                    action="promote", target_kind="skill", candidate_id=candidate_id,
                    revision=revision, digest=digest, request_digest=request_digest,
                    actor=actor, target_key=skill_id, expected_target_version=expected_version,
                    previous_target_version=expected_version, target_version=target_digest,
                    target_payload={"content":content,"transform_schema":_SKILL_TRANSFORM_SCHEMA,
                                    "target_sha256":target_digest,
                                    "previous_source_binding":previous_binding,
                                    "target_source_binding":target_binding})
        return self._execute_skill_promotion(request_id)

    def _execute_skill_promotion(self, request_id):
        error = None
        result = None
        with self._write() as conn:
            op = self._request_row(conn, "hermes", request_id,
                conn.execute("SELECT request_digest FROM learning_promotions WHERE provider='hermes' AND request_id=?",
                    (request_id,)).fetchone()[0])
            if op["state"] != "prepared":
                return self._receipt(op)
            skill_id = op["target_key"]
            payload = json.loads(op["target_payload_json"])
            content = payload.get("content")
            previous_binding = payload.get("previous_source_binding")
            target_binding = payload.get("target_source_binding")
            previous = op["previous_target_version"]
            desired = op["target_version"]
            binding_keys = {"source_kind", "source_root", "relative_path", "source_version"}
            if (not isinstance(content, str)
                    or payload.get("transform_schema") != _SKILL_TRANSFORM_SCHEMA
                    or payload.get("target_sha256") != desired
                    or _sha(content.encode("utf-8")) != desired
                    or not isinstance(previous_binding, dict)
                    or set(previous_binding) != binding_keys
                    or previous_binding.get("source_version") != previous
                    or not isinstance(target_binding, dict)
                    or set(target_binding) != binding_keys
                    or target_binding.get("source_kind") != "local_override"
                    or target_binding.get("source_version") != desired
                    or target_binding.get("relative_path") != f"{skill_id}/SKILL.md"):
                raise RuntimeError("Persistierter Skill-Promotionssnapshot ist ungültig.")
            target_root = target_binding.get("source_root")
            if (not isinstance(target_root, str)
                    or not Path(target_root).is_absolute()
                    or str(Path(target_root).expanduser().resolve()) != target_root):
                raise RuntimeError("Persistierte Skill-Write-Root ist nicht kanonisch absolut.")
            candidate_ok = True
            try:
                self._candidate(conn,"hermes",op["candidate_id"],op["candidate_revision"],op["candidate_digest"])
            except (LearningConflict, LearningNotFound, LearningPromotionUnavailable):
                candidate_ok = False

            actual_binding = self._skill_binding(skill_id)
            actual = actual_binding["source_version"]
            if target_binding != self._target_skill_binding(skill_id, desired):
                error = "Konfigurierte Skill-Write-Root änderte sich nach der Vorbereitung."
                receipt = {"status":"conflict","request_id":request_id,"target_kind":"skill",
                    "candidate_id":op["candidate_id"],"target_id":skill_id,
                    "target_source_binding_sha256":_digest_json(target_binding),
                    "targets_published":False,"code":"learning_promotion_conflict"}
                self._update_operation(conn,"hermes",request_id,state="conflict",receipt=receipt)
            elif not candidate_ok:
                if actual_binding == previous_binding and actual == previous:
                    receipt = {"status":"cancelled","request_id":request_id,"target_kind":"skill",
                        "candidate_id":op["candidate_id"],"candidate_revision":op["candidate_revision"],
                        "candidate_digest":op["candidate_digest"],"targets_published":False,
                        "recovered_after_candidate_change":True}
                    self._update_operation(conn,"hermes",request_id,state="cancelled",receipt=receipt)
                elif actual_binding == target_binding and actual == desired:
                    try:
                        restore = self._restore_skill(
                            skill_id, previous, desired, previous_binding, target_binding
                        )
                        receipt = {"status":"cancelled","request_id":request_id,"target_kind":"skill",
                            "candidate_id":op["candidate_id"],"candidate_revision":op["candidate_revision"],
                            "candidate_digest":op["candidate_digest"],"targets_published":False,
                            "recovered_after_candidate_change":True,**restore}
                        self._update_operation(conn,"hermes",request_id,state="cancelled",receipt=receipt)
                    except (LearningConflict, OSError, RuntimeError, ValueError) as exc:
                        error = str(exc)
                        receipt = {"status":"conflict","request_id":request_id,"target_kind":"skill",
                            "target_source_binding_sha256":_digest_json(target_binding),
                            "targets_published":False,"code":"learning_promotion_conflict"}
                        self._update_operation(conn,"hermes",request_id,state="conflict",receipt=receipt)
                else:
                    error = "Kandidatreview änderte sich und das gebundene Skill-Ziel ist nicht wiederherstellbar."
                    receipt = {"status":"conflict","request_id":request_id,"target_kind":"skill",
                        "target_source_binding_sha256":_digest_json(target_binding),
                        "targets_published":False,"code":"learning_promotion_conflict"}
                    self._update_operation(conn,"hermes",request_id,state="conflict",receipt=receipt)
            elif actual_binding == target_binding and actual == desired:
                receipt = {"status":"published","request_id":request_id,"target_kind":"skill",
                    "candidate_id":op["candidate_id"],"candidate_revision":op["candidate_revision"],
                    "candidate_digest":op["candidate_digest"],"target_id":skill_id,
                    "target_version":desired,"target_sha256":desired,"target_schema":"SKILL.md",
                    "content_transform":_SKILL_TRANSFORM_SCHEMA,
                    "previous_source_binding_sha256":_digest_json(previous_binding),
                    "target_source_binding_sha256":_digest_json(target_binding),
                    "targets_published":True,"empirically_validated":False,
                    "tools_granted":False,"agent_started":False,"recovered_after_target_write":True}
                self._update_operation(conn,"hermes",request_id,state="published",receipt=receipt)
                result = receipt
            elif actual_binding != previous_binding or actual != previous:
                error = "Skill-Ziel oder native Root-Bindung änderte sich nach Promotionsvorbereitung."
                receipt = {"status":"conflict","request_id":request_id,"target_kind":"skill",
                    "candidate_id":op["candidate_id"],"target_id":skill_id,
                    "expected_target_version":previous,"actual_target_version":actual,
                    "target_source_binding_sha256":_digest_json(target_binding),
                    "targets_published":False,"code":"learning_promotion_conflict"}
                self._update_operation(conn,"hermes",request_id,state="conflict",receipt=receipt)
            else:
                self._save_skill(skill_id,content,previous)
                if self._after_skill_write is not None:
                    self._after_skill_write()
                actual_binding = self._skill_binding(skill_id)
                if actual_binding != target_binding:
                    raise RuntimeError("Native Skill-Readback stimmt nicht mit der gebundenen Ziel-Root überein.")
                receipt = {"status":"published","request_id":request_id,"target_kind":"skill",
                    "candidate_id":op["candidate_id"],"candidate_revision":op["candidate_revision"],
                    "candidate_digest":op["candidate_digest"],"target_id":skill_id,
                    "target_version":desired,"target_sha256":desired,"previous_target_version":previous,
                    "previous_source_binding_sha256":_digest_json(previous_binding),
                    "target_source_binding_sha256":_digest_json(target_binding),
                    "target_schema":"SKILL.md","content_transform":_SKILL_TRANSFORM_SCHEMA,
                    "targets_published":True,"empirically_validated":False,
                    "tools_granted":False,"agent_started":False,"recovered_after_target_write":False}
                self._update_operation(conn,"hermes",request_id,state="published",receipt=receipt)
                result = receipt
        if error:
            raise LearningPromotionConflict(error)
        return result or {"status":"prepared","request_id":request_id,"targets_published":False}

    def _lesson_drafts(self, candidate):
        drafts = self._parse_json(candidate.get("lessons_draft_json"), [])
        if not isinstance(drafts, list) or len(drafts) > 30:
            raise LearningPromotionUnavailable("Hermes-Lessonentwürfe sind ungültig oder zu umfangreich.")
        clean, seen = [], set()
        for draft in drafts:
            if not isinstance(draft, dict) or set(draft) - {
                    "category", "title", "solution", "is_active", "confidence",
                    "confidence_status"}:
                raise LearningPromotionUnavailable("Lesson-Entwurf enthält unbekannte Felder.")
            category, title, solution = draft.get("category"), draft.get("title"), draft.get("solution")
            if (not isinstance(category,str) or not _CATEGORY.fullmatch(category)
                    or not isinstance(title,str) or not title.strip() or len(title) > 200
                    or not isinstance(solution,str) or not solution.strip() or len(solution) > 5000
                    or draft.get("is_active",0) not in (0,False)):
                raise LearningPromotionUnavailable("Lesson-Entwurf erfüllt den nativen Zielvertrag nicht.")
            key = title.strip().casefold()
            if key in seen:
                raise LearningPromotionConflict("Der Kandidat enthält doppelte Lesson-Titel.")
            seen.add(key)
            confidence = draft.get("confidence")
            confidence_status = draft.get("confidence_status")
            if confidence is not None and (
                    type(confidence) not in (int, float) or not 0 <= confidence <= 1
                    or not math.isfinite(confidence)):
                raise LearningPromotionUnavailable("Lesson-Konfidenz ist ungültig.")
            if confidence_status not in (None, "not_measured", "legacy_heuristic_unvalidated"):
                raise LearningPromotionUnavailable("Lesson-Konfidenzstatus ist ungültig.")
            if confidence_status == "not_measured" and confidence is not None:
                raise LearningPromotionUnavailable("Nicht erhobene Lesson-Konfidenz darf keinen Zahlenwert tragen.")
            if confidence_status == "legacy_heuristic_unvalidated" and confidence is None:
                raise LearningPromotionUnavailable("Historischer Heuristikwert fehlt.")
            clean.append({"category":category,"title":title.strip(),"solution":solution.strip()})
        if not clean:
            raise LearningPromotionUnavailable("Diese Hermes-Revision enthält keine freizugebenden Lessons.")
        return clean

    @staticmethod
    def _lesson_snapshot(row):
        snapshot = {"id": row["id"], "category": row["category"], "title": row["title"],
                    "solution": row["solution"], "is_active": row["is_active"]}
        if "confidence" in row.keys():
            snapshot["confidence"] = row["confidence"]
        return snapshot

    @staticmethod
    def _lesson_target_digest(snapshot, *, include_confidence=None):
        fields = ("category", "title", "solution")
        if include_confidence is None:
            include_confidence = "confidence" in snapshot
        if include_confidence:
            fields += ("confidence",)
        return _digest_json({key: snapshot[key] for key in fields})

    def _promote_lessons(self, candidate_id, revision, digest, request_id, expected_version, actor):
        if expected_version != "absent":
            raise ValueError("Lessons erwarten die native Zielvorbedingung 'absent'.")
        request_digest = _digest_json({
            "action":"promote","provider":"hermes","candidate_id":candidate_id,
            "candidate_revision":revision,"candidate_digest":digest,"target_kind":"lessons",
            "expected_target_version":expected_version,"actor":actor,
        })
        with self._write() as conn:
            prior = self._request_row(conn,"hermes",request_id,request_digest)
            if prior is not None and prior["state"] != "prepared":
                return self._receipt(prior)
            if prior is None:
                candidate = self._candidate(conn,"hermes",candidate_id,revision,digest)
                drafts = self._lesson_drafts(candidate)
                active = conn.execute("""SELECT request_id,state FROM learning_promotions
                    WHERE provider='hermes' AND candidate_id=? AND candidate_revision=?
                      AND target_kind='lessons' AND action='promote'
                      AND state IN ('prepared','published')""",(candidate_id,revision)).fetchone()
                if active is not None:
                    raise LearningPromotionConflict("Diese Kandidatenrevision besitzt bereits eine Lessons-Promotion.")
                columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_lessons)")}
                if not {"id","category","title","solution","is_active"}.issubset(columns):
                    raise LearningPromotionUnavailable("Der native memory_lessons-Zielspeicher ist nicht verfügbar.")
                active_titles = {str(row[0]).strip().casefold() for row in conn.execute(
                    "SELECT title FROM memory_lessons WHERE is_active=1")}
                collisions = [draft["title"] for draft in drafts if draft["title"].casefold() in active_titles]
                if collisions:
                    raise LearningPromotionConflict("Aktiver Lesson-Titel kollidiert: " + collisions[0])
                self._insert_operation(conn,provider="hermes",request_id=request_id,
                    action="promote",target_kind="lessons",candidate_id=candidate_id,
                    revision=revision,digest=digest,request_digest=request_digest,actor=actor,
                    expected_target_version=expected_version,previous_target_version="absent",
                    target_payload={"lessons":drafts})
                items=[]
                for ordinal,draft in enumerate(drafts):
                    stamp=_stamp()
                    values={"category":draft["category"],"title":draft["title"],
                            "solution":draft["solution"],"is_active":1}
                    if "confidence" in columns: values["confidence"] = None
                    if "created_at" in columns: values["created_at"]=stamp
                    if "updated_at" in columns: values["updated_at"]=stamp
                    names=list(values)
                    cur=conn.execute(
                        f"INSERT INTO memory_lessons ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                        [values[name] for name in names])
                    row=conn.execute("SELECT * FROM memory_lessons WHERE id=?",(cur.lastrowid,)).fetchone()
                    snap=self._lesson_snapshot(row)
                    target_digest = self._lesson_target_digest(snap)
                    conn.execute("""INSERT INTO learning_promotion_items
                        (provider,promotion_request_id,target_kind,ordinal,target_key,target_digest,target_snapshot_json)
                        VALUES ('hermes',?,'lessons',?,?,?,?)""",
                        (request_id,ordinal,str(cur.lastrowid),target_digest,encoded(snap)))
                    items.append({"target_id":cur.lastrowid,"target_digest":target_digest})
                target_version=_digest_json(items)
                receipt={"status":"published","request_id":request_id,"target_kind":"lessons",
                    "candidate_id":candidate_id,"candidate_revision":revision,"candidate_digest":digest,
                    "targets_published":True,"target_ids":[item["target_id"] for item in items],
                    "target_version":target_version,"empirically_validated":False,
                    "tools_granted":False,"agent_started":False,"replayed":False}
                self._update_operation(conn,"hermes",request_id,state="published",receipt=receipt,target_version=target_version)
                return receipt
            # A lessons write and its receipt share one SQLite transaction, so a
            # persisted prepared state indicates a prior implementation anomaly.
            raise LearningPromotionConflict("Lesson-Promotion braucht eine erneute, explizite Request-ID.")

    def _sequence_proposal(self, candidate):
        if self.sequence_adapter is None:
            raise LearningPromotionUnavailable(
                "waiting_for_native_definition: NemoFold-Legacy-Schritte bleiben bis zum #2001-Adapter inaktiv."
            )
        proposal = self.sequence_adapter(candidate)
        if (not isinstance(proposal, Mapping)
                or set(proposal) != {"schema", "source", "definition", "resolved"}
                or proposal.get("schema") != "bach.learning.native-sequence.v1"):
            raise LearningPromotionUnavailable("Native NemoFold-Sequenzdefinition fehlt oder enthält unbekannte Felder.")
        source = proposal.get("source")
        expected = {
            "provider": "nemofold",
            "candidate_id": candidate["id"],
            "candidate_revision": candidate["candidate_revision"],
            "candidate_digest": candidate["candidate_digest"],
        }
        if not isinstance(source, Mapping) or dict(source) != expected:
            raise LearningPromotionConflict("Native Sequenzdefinition ist nicht an die aktuelle Revision gebunden.")
        clean = sequence_definition(proposal.get("definition"))
        if clean != proposal.get("definition"):
            raise LearningPromotionUnavailable("Native Sequenzdefinition ist nicht kanonisch.")
        resolved = proposal.get("resolved")
        if (not isinstance(resolved, Mapping) or set(resolved) != {"config_version", "agent_slots", "skills"}
                or not isinstance(resolved.get("config_version"), str)
                or not resolved["config_version"].strip() or len(resolved["config_version"]) > 200
                or "\x00" in resolved["config_version"]
                or not isinstance(resolved.get("agent_slots"), list)
                or not isinstance(resolved.get("skills"), list)):
            raise LearningPromotionUnavailable("Native Agenten-/Skillauflösung fehlt.")
        agent_ids = {step["agent_slot"] for step in clean["steps"]}
        skill_ids = {skill for step in clean["steps"] for skill in step["skill_ids"]}
        agents, skills = resolved["agent_slots"], resolved["skills"]
        if (any(not isinstance(item, Mapping) or set(item) != {"id", "config_version"}
                or not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(item.get("config_version"), str) or not item["config_version"]
                or len(item["config_version"]) > 200 or "\x00" in item["config_version"] for item in agents)
                or len({item["id"] for item in agents}) != len(agents)
                or {item["id"] for item in agents} != agent_ids
                or any(not isinstance(item, Mapping) or set(item) != {"id", "source_version"}
                       or not isinstance(item.get("id"), str) or not item["id"]
                       or not isinstance(item.get("source_version"), str) or not item["source_version"]
                       or len(item["source_version"]) > 200 or "\x00" in item["source_version"] for item in skills)
                or len({item["id"] for item in skills}) != len(skills)
                or {item["id"] for item in skills} != skill_ids):
            raise LearningPromotionUnavailable("Agenten-/Skillauflösung passt nicht eindeutig zu den Schritten.")
        return {
            "schema": proposal["schema"],
            "source": dict(source),
            "definition": clean,
            "resolved": {
                "config_version": resolved["config_version"],
                "agent_slots": [dict(item) for item in agents],
                "skills": [dict(item) for item in skills],
            },
        }

    def _promote_sequence(self, candidate_id, revision, digest, request_id, expected_version, actor):
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("SequenceStore-Zielversion als nichtnegative Ganzzahl erforderlich.")
        if self.sequence_store is None:
            guard = lambda: skill_source_service.check_write_locks(self.db_path)
            self.sequence_store = SequenceStore(self.db_path, write_guard=guard)
        publish = getattr(self.sequence_store, "publish_learning_candidate", None)
        if publish is None:
            raise LearningPromotionUnavailable(
                "waiting_for_atomic_sequence_receipt: SequenceStore braucht die atomare Promotionsschnittstelle."
            )
        with self._write() as conn:
            candidate = self._candidate(conn, "nemofold", candidate_id, revision, digest)
            proposal = self._sequence_proposal(candidate)

        def validate_source(conn):
            current = self._candidate(conn, "nemofold", candidate_id, revision, digest)
            return self._sequence_proposal(current)

        return publish(
            proposal,
            request_id=request_id,
            expected_version=expected_version,
            actor=actor,
            source_validator=validate_source,
        )

    def revoke(self, provider: str, candidate_id: int, *, target_kind: str,
               expected_revision: int, expected_digest: str, source_request_id: str,
               request_id: str, actor: str) -> dict:
        self._validate_identity(candidate_id,expected_revision,expected_digest,request_id,actor)
        if not isinstance(source_request_id,str) or not _REQUEST.fullmatch(source_request_id):
            raise ValueError("Promotions-Request-ID zur Rücknahme erforderlich.")
        if target_kind=="skill" and provider=="hermes":
            return self._revoke_skill(candidate_id,expected_revision,expected_digest,source_request_id,request_id,actor)
        if target_kind=="lessons" and provider=="hermes":
            return self._revoke_lessons(candidate_id,expected_revision,expected_digest,source_request_id,request_id,actor)
        if target_kind=="sequence" and provider=="nemofold":
            if self.sequence_store is None:
                guard=lambda: skill_source_service.check_write_locks(self.db_path)
                self.sequence_store=SequenceStore(self.db_path,write_guard=guard)
            revoke=getattr(self.sequence_store,"revoke_learning_candidate",None)
            if revoke is None:
                raise LearningPromotionUnavailable("waiting_for_atomic_sequence_receipt: Rücknahmevertrag fehlt.")
            return revoke(source_request_id,request_id=request_id,actor=actor,
                          candidate_id=candidate_id,candidate_revision=expected_revision,
                          candidate_digest=expected_digest)
        raise LearningPromotionUnavailable("Dieser Zieltyp kann nicht zurückgenommen werden.")

    def _revoke_skill(self,candidate_id,revision,digest,source_request_id,request_id,actor):
        request_digest=_digest_json({"action":"revoke","provider":"hermes","candidate_id":candidate_id,
            "candidate_revision":revision,"candidate_digest":digest,"target_kind":"skill",
            "source_request_id":source_request_id,"actor":actor})
        with self._write() as conn:
            prior=self._request_row(conn,"hermes",request_id,request_digest)
            if prior is not None and prior["state"]!="prepared":
                return self._receipt(prior)
            source=conn.execute("""SELECT * FROM learning_promotions
                WHERE provider='hermes' AND request_id=? AND action='promote' AND target_kind='skill'
                  AND candidate_id=? AND candidate_revision=? AND candidate_digest=?""",
                (source_request_id,candidate_id,revision,digest)).fetchone()
            if source is None or source["state"] not in {"published","reverted"}:
                raise LearningPromotionConflict("Keine bestätigte Skill-Promotion dieser Revision vorhanden.")
            if prior is None:
                source_payload=self._parse_json(source["target_payload_json"], {})
                self._insert_operation(conn,provider="hermes",request_id=request_id,action="revoke",
                    target_kind="skill",candidate_id=candidate_id,revision=revision,digest=digest,
                    request_digest=request_digest,actor=actor,source_request_id=source_request_id,
                    target_key=source["target_key"],previous_target_version=source["previous_target_version"],
                    target_version=source["target_version"],target_payload={
                        "source_request_id":source_request_id,
                        "previous_source_binding":source_payload.get("previous_source_binding"),
                        "target_source_binding":source_payload.get("target_source_binding"),
                    })
        return self._execute_skill_revoke(request_id)

    def _execute_skill_revoke(self,request_id):
        error=None
        result=None
        with self._write() as conn:
            op=conn.execute("SELECT * FROM learning_promotions WHERE provider='hermes' AND request_id=?",(request_id,)).fetchone()
            if op["state"]!="prepared":
                return self._receipt(op)
            source=conn.execute("SELECT * FROM learning_promotions WHERE provider='hermes' AND request_id=?",
                (op["source_request_id"],)).fetchone()
            source_payload=self._parse_json(source["target_payload_json"], {})
            revoke_payload=self._parse_json(op["target_payload_json"], {})
            previous=source["previous_target_version"]
            published=source["target_version"]
            previous_binding=revoke_payload.get("previous_source_binding")
            target_binding=revoke_payload.get("target_source_binding")
            if (previous_binding != source_payload.get("previous_source_binding")
                    or target_binding != source_payload.get("target_source_binding")):
                error="Vorbereitete Rücknahme stimmt nicht mit der bestätigten Skill-Zielbindung überein."
                receipt={"status":"conflict","request_id":request_id,"target_kind":"skill",
                    "source_request_id":source["request_id"],"targets_revoked":False,
                    "code":"learning_promotion_conflict"}
                self._update_operation(conn,"hermes",request_id,state="conflict",receipt=receipt)
            else:
                try:
                    restore=self._restore_skill(
                        source["target_key"],previous,published,previous_binding,target_binding
                    )
                except LearningPromotionConflict as exc:
                    error=str(exc)
                    receipt={"status":"conflict","request_id":request_id,"target_kind":"skill",
                        "source_request_id":source["request_id"],"targets_revoked":False,
                        "target_source_binding_sha256":_digest_json(target_binding),
                        "code":"learning_promotion_conflict"}
                    self._update_operation(conn,"hermes",request_id,state="conflict",receipt=receipt)
                else:
                    receipt={"status":"reverted","request_id":request_id,"target_kind":"skill",
                        "source_request_id":source["request_id"],"candidate_id":source["candidate_id"],
                        "candidate_revision":source["candidate_revision"],"candidate_digest":source["candidate_digest"],
                        "target_id":source["target_key"],"previous_target_version":previous,
                        "target_version":published,"target_source_binding_sha256":_digest_json(target_binding),
                        "targets_published":False,"targets_revoked":True,
                        "empirically_validated":False,"already_restored":restore["already_restored"]}
                    self._update_operation(conn,"hermes",request_id,state="reverted",receipt=receipt)
                    source_receipt=json.loads(source["receipt_json"])
                    source_receipt.update(status="reverted",targets_published=False,historical_publication=True,
                                          revoked_by=request_id)
                    self._update_operation(conn,"hermes",source["request_id"],state="reverted",receipt=source_receipt)
                    result=receipt
        if error:
            raise LearningPromotionConflict(error)
        return result

    def target_states(self, provider: str, candidate: Mapping[str, Any]) -> dict:
        if provider not in _TABLES or not isinstance(candidate, Mapping):
            raise ValueError("Lernanbieter und Kandidat erforderlich")
        candidate_id = candidate.get("id")
        revision = candidate.get("candidate_revision")
        candidate_digest = candidate.get("candidate_digest")
        if (type(candidate_id) is not int or type(revision) is not int
                or not isinstance(candidate_digest, str) or not _DIGEST.fullmatch(candidate_digest)):
            return {"targets": {
                kind: {"state": "legacy_unverified", "targets_published": False}
                for kind in (("skill", "lessons") if provider == "hermes" else ("sequence",))
            }}
        kinds = ("skill", "lessons") if provider == "hermes" else ("sequence",)
        result = {}
        if not self.db_path.is_file():
            return {"candidate_id": candidate_id, "candidate_revision": revision,
                    "candidate_digest": candidate_digest,
                    "targets": {kind: {"state": "store_unavailable", "targets_published": False} for kind in kinds}}
        try:
            conn = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            try:
                for kind in kinds:
                    operation = None
                    table = "learning_promotions" if provider == "hermes" else "native_sequence_learning_promotions"
                    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                          (table,)).fetchone()
                    if exists:
                        if provider == "hermes":
                            operation = conn.execute("""SELECT state,receipt_json FROM learning_promotions
                                WHERE provider=? AND candidate_id=? AND candidate_revision=?
                                  AND candidate_digest=? AND target_kind=? AND action='promote'
                                ORDER BY created_at DESC LIMIT 1""",
                                (provider, candidate_id, revision, candidate_digest, kind)).fetchone()
                        else:
                            operation = conn.execute("""SELECT state,receipt_json FROM native_sequence_learning_promotions
                                WHERE candidate_id=? AND candidate_revision=? AND candidate_digest=?
                                  AND action='promote' ORDER BY created_at DESC LIMIT 1""",
                                (candidate_id, revision, candidate_digest)).fetchone()
                    if operation is not None:
                        try:
                            receipt = json.loads(operation["receipt_json"])
                        except (TypeError, ValueError):
                            receipt = {}
                        result[kind] = {
                            "state": operation["state"],
                            "targets_published": operation["state"] == "published",
                            "receipt": receipt,
                        }
                        continue
                    review_state = candidate.get("review_state", candidate.get("status", "review_required"))
                    if review_state != "reviewed":
                        state = "review_required" if review_state == "pending" else str(review_state)
                        result[kind] = {"state": state, "targets_published": False}
                        continue
                    try:
                        if provider == "hermes" and kind == "skill":
                            self._skill_payload(candidate)
                            state = "ready_for_target_cas"
                        elif provider == "hermes" and kind == "lessons":
                            drafts = self._lesson_drafts(candidate)
                            active_titles = {str(row[0]).strip().casefold() for row in conn.execute(
                                "SELECT title FROM memory_lessons WHERE is_active=1")}
                            state = ("target_conflict" if any(
                                draft["title"].casefold() in active_titles for draft in drafts
                            ) else "ready_for_target_cas")
                        elif self.sequence_adapter is None:
                            state = "waiting_for_native_definition"
                        else:
                            self._sequence_proposal(candidate)
                            state = ("ready_for_target_cas" if self.sequence_store is None
                                     or getattr(self.sequence_store, "publish_learning_candidate", None)
                                     else "waiting_for_atomic_sequence_receipt")
                    except LearningPromotionUnavailable as exc:
                        state = ("waiting_for_native_definition"
                                 if str(exc).startswith("waiting_for_native_definition")
                                 else "target_unavailable")
                    except (LearningPromotionConflict, ValueError, TypeError):
                        state = "target_unavailable"
                    result[kind] = {"state": state, "targets_published": False}
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            result = {kind: {"state": "store_unavailable", "targets_published": False} for kind in kinds}
        return {
            "candidate_id": candidate_id,
            "candidate_revision": revision,
            "candidate_digest": candidate_digest,
            "targets": result,
        }

    def _revoke_lessons(self,candidate_id,revision,digest,source_request_id,request_id,actor):
        request_digest=_digest_json({"action":"revoke","provider":"hermes","candidate_id":candidate_id,
            "candidate_revision":revision,"candidate_digest":digest,"target_kind":"lessons",
            "source_request_id":source_request_id,"actor":actor})
        with self._write() as conn:
            prior=self._request_row(conn,"hermes",request_id,request_digest)
            if prior is not None and prior["state"]!="prepared":
                return self._receipt(prior)
            source=conn.execute("""SELECT * FROM learning_promotions
                WHERE provider='hermes' AND request_id=? AND action='promote' AND target_kind='lessons'
                  AND candidate_id=? AND candidate_revision=? AND candidate_digest=?""",
                (source_request_id,candidate_id,revision,digest)).fetchone()
            if source is None or source["state"] not in {"published","reverted"}:
                raise LearningPromotionConflict("Keine bestätigte Lessons-Promotion dieser Revision vorhanden.")
            if prior is None:
                self._insert_operation(conn,provider="hermes",request_id=request_id,action="revoke",
                    target_kind="lessons",candidate_id=candidate_id,revision=revision,digest=digest,
                    request_digest=request_digest,actor=actor,source_request_id=source_request_id,
                    target_version=source["target_version"],target_payload={"source_request_id":source_request_id})
            columns={row[1] for row in conn.execute("PRAGMA table_info(memory_lessons)")}
            disabled=already_inactive=0
            items=conn.execute("""SELECT * FROM learning_promotion_items
                WHERE provider='hermes' AND promotion_request_id=? AND target_kind='lessons'
                ORDER BY ordinal""",(source_request_id,)).fetchall()
            if not items:
                raise LearningPromotionConflict("Lessons-Promotionreceipt enthält keine Zielbindungen.")
            for item in items:
                row=conn.execute("SELECT * FROM memory_lessons WHERE id=?",(int(item["target_key"]),)).fetchone()
                if row is None:
                    raise LearningPromotionConflict("Promovierte Lesson fehlt; Rücknahme bleibt gesperrt.")
                snap = self._lesson_snapshot(row)
                try:
                    expected_snapshot = json.loads(item["target_snapshot_json"])
                    if not isinstance(expected_snapshot, dict):
                        raise TypeError("invalid snapshot")
                    if expected_snapshot.get("id") != int(item["target_key"]):
                        raise ValueError("snapshot target mismatch")
                    include_confidence = "confidence" in expected_snapshot
                    expected_digest = self._lesson_target_digest(
                        expected_snapshot, include_confidence=include_confidence
                    )
                    target_digest = self._lesson_target_digest(
                        snap, include_confidence=include_confidence
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    raise LearningPromotionConflict(
                        "Lesson-Promotionreceipt ist ungültig; Rücknahme bleibt gesperrt."
                    ) from None
                if (expected_digest != item["target_digest"]
                        or target_digest != item["target_digest"]):
                    raise LearningPromotionConflict("Lesson-Inhalt wurde seit der Promotion verändert.")
                if snap["is_active"] == 1:
                    updates=["is_active=0"]; params=[]
                    if "updated_at" in columns:
                        updates.append("updated_at=?"); params.append(_stamp())
                    where = "id=? AND category IS ? AND title=? AND solution=? AND is_active=1"
                    params.extend([row["id"], row["category"], row["title"], row["solution"]])
                    if include_confidence:
                        where += " AND confidence IS ?"
                        params.append(expected_snapshot["confidence"])
                    cur = conn.execute(
                        f"UPDATE memory_lessons SET {','.join(updates)} WHERE {where}", params
                    )
                    if cur.rowcount!=1:
                        raise LearningPromotionConflict("Lesson-Aktivstatus änderte sich; Rücknahme-CAS abgelehnt.")
                    disabled+=1
                elif snap["is_active"] == 0:
                    already_inactive+=1
                else:
                    raise LearningPromotionConflict("Lesson-Aktivstatus ist außerhalb des Vertrags.")
            receipt={"status":"reverted","request_id":request_id,"target_kind":"lessons",
                "source_request_id":source_request_id,"candidate_id":candidate_id,
                "candidate_revision":revision,"candidate_digest":digest,"targets_published":False,
                "targets_revoked":True,"disabled_count":disabled,"already_inactive_count":already_inactive,
                "target_version":source["target_version"],"empirically_validated":False}
            self._update_operation(conn,"hermes",request_id,state="reverted",receipt=receipt)
            source_receipt=json.loads(source["receipt_json"])
            source_receipt.update(status="reverted",targets_published=False,historical_publication=True,
                                  revoked_by=request_id)
            self._update_operation(conn,"hermes",source_request_id,state="reverted",receipt=source_receipt)
            return receipt
