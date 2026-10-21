# SPDX-License-Identifier: MIT
"""Operator-owned external identities and private, immutable source artifacts.

These are foundations for an explicit ``external_attested`` result contract.
They never create native model execution, a scope receipt or an acceptance.
Only an enrolled task-result operator may register identities or store/read
artifact bytes. Public result projections must not expose these private bytes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import uuid

from . import worker_policy_settings as settings
from .worker_review_identity import require_operator, model_principal_catalog, _principal

REGISTRY_KEY = "worker_external_principals.v1"
REGISTRY_SCHEMA = "bach.worker-external-principals.v1"
ARTIFACT_SCHEMA = "bach.worker-external-artifact.v1"
VERIFICATION_METHOD = "operator_checked_artifacts"
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_ARTIFACT_ID = re.compile(r"[a-f0-9]{32}\Z")
_MEDIA_TYPES = frozenset({"application/json", "application/x-ndjson", "text/plain"})
_ENTRY_FIELDS = {"source_id", "platform_id", "tenant_id", "account_id", "model_key",
                 "source_principal_id", "model_principal_id", "model_labels"}


class ExternalEvidenceConflict(settings.PolicyConflict):
    """The caller's identity revision or immutable artifact changed."""


class ExternalEvidenceUnavailable(settings.PolicyUnavailable):
    """Stored external evidence cannot be verified."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("Eindeutige externe Kennung ohne URLs erforderlich")
    return value


def _label(value):
    if (type(value) is not str or not value or value != value.strip()
            or len(value) > 256 or "://" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Ungültige externe Modellbezeichnung")
    return value


def validate_principals(values):
    """Keep source/account identity separate from global model identity.

    A different account or platform is never evidence of a different model.
    The operator must map aliases to the SAME global model principal used by
    native model routes. Independence compares that principal, not source_id.
    """
    if type(values) is not list or len(values) > 128:
        raise ValueError("Liste externer Principal-Zuordnungen erforderlich")
    result, source_ids, identities, observed = [], set(), set(), {}
    for value in values:
        settings._object(value, _ENTRY_FIELDS)
        entry = {key: _identifier(value[key]) for key in _ENTRY_FIELDS - {"model_labels", "model_principal_id"}}
        entry["model_principal_id"] = _principal(value["model_principal_id"])
        labels = value["model_labels"]
        if (type(labels) is not list or not 1 <= len(labels) <= 64
                or len(set(_label(label) for label in labels)) != len(labels)):
            raise ValueError("Explizite eindeutige externe Modellaliasliste erforderlich")
        entry["model_labels"] = list(labels)
        source_id = entry["source_id"]
        identity = tuple(entry[key] for key in (
            "platform_id", "tenant_id", "account_id", "source_principal_id", "model_key"))
        if source_id in source_ids or identity in identities:
            raise ValueError("Externe Quelle oder Identität ist mehrfach zugeordnet")
        source_ids.add(source_id)
        identities.add(identity)
        # The same platform's deployment key may not be split into different
        # global principals merely by changing a tenant/account/source id.
        key = (entry["platform_id"], entry["model_key"])
        previous = observed.get(key)
        if previous is not None and previous != entry["model_principal_id"]:
            raise ValueError("Ein externes Modell hat mehrere globale Principals")
        observed[key] = entry["model_principal_id"]
        result.append(entry)
    return result


def registry_snapshot(conn):
    """Pure DB read, including on a database without any external tables."""
    stored = settings._stored(conn, REGISTRY_KEY)
    try:
        entries = validate_principals([] if stored["values"] is None else stored["values"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ExternalEvidenceUnavailable("Externe Principal-Zuordnungen sind ungültig") from exc
    catalog = model_principal_catalog(conn)
    return {"schema": REGISTRY_SCHEMA, "availability": "available",
            "configuration_version": _digest({"external": stored,
                "catalog_configuration_version": catalog["configuration_version"]}),
            "canonical_model_principal_ids": catalog["principal_ids"], "principals": entries}


def read_external_principals(db_path=None):
    with settings._connection(db_path) as conn:
        return registry_snapshot(conn)


def write_external_principals(payload, *, operator_token, db_path=None):
    settings._object(payload, {"configuration_version", "principals"})
    entries = validate_principals(payload["principals"])
    if type(payload["configuration_version"]) is not str or not _HEX.fullmatch(payload["configuration_version"]):
        raise ValueError("Gültige externe Konfigurationsrevision erforderlich")
    with settings._connection(db_path, write=True) as conn:
        actor = require_operator(conn, operator_token)
        before = registry_snapshot(conn)
        if payload["configuration_version"] != before["configuration_version"]:
            raise ExternalEvidenceConflict("Externe Zuordnungen wurden parallel geändert")
        if any(entry["model_principal_id"] not in before["canonical_model_principal_ids"] for entry in entries):
            raise ValueError("Globalen Modellprincipal zuerst ausdrücklich registrieren")
        settings._persist(conn, REGISTRY_KEY, entries, actor=actor)
        after = registry_snapshot(conn)
        return {"schema": REGISTRY_SCHEMA, "updated": True, "worker_started": False,
                "configuration_version": after["configuration_version"]}


def resolve_external_principal(snapshot, *, source_id, model_key, model_label, binding_sha256=None):
    """Resolve an explicit current mapping; never infer identity from a label.

    binding_sha256 pins only the selected mapping. An unrelated source edit
    must not silently invalidate an unchanged source/model binding.
    """
    if (not isinstance(snapshot, dict) or snapshot.get("schema") != REGISTRY_SCHEMA
            or snapshot.get("availability") != "available"):
        return None
    try:
        entries = validate_principals(snapshot.get("principals"))
        _identifier(source_id)
        _identifier(model_key)
        _label(model_label)
    except (ValueError, TypeError, KeyError):
        return None
    matches = [entry for entry in entries
               if entry["source_id"] == source_id and entry["model_key"] == model_key
               and model_label in entry["model_labels"]
               and entry["model_principal_id"] in snapshot.get("canonical_model_principal_ids", [])]
    if len(matches) != 1:
        return None
    entry = matches[0]
    digest = _digest(entry)
    if binding_sha256 is not None and binding_sha256 != digest:
        return None
    return {**entry, "binding_sha256": digest,
            "registry_configuration_version": snapshot.get("configuration_version")}


def _ensure_artifact_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_external_artifacts (
        artifact_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE,
        media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
        content BLOB NOT NULL, stored_at TEXT NOT NULL, stored_by TEXT NOT NULL)""")


def _artifact_record(conn, artifact_id):
    if type(artifact_id) is not str or _ARTIFACT_ID.fullmatch(artifact_id) is None:
        raise ValueError("Ungültige private Artefakt-ID")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='worker_external_artifacts'").fetchone() is None:
        return None
    cursor = conn.execute("SELECT artifact_id,sha256,media_type,size_bytes,content,stored_at,stored_by "
                          "FROM worker_external_artifacts WHERE artifact_id=?", (artifact_id,))
    value = cursor.fetchone()
    if value is None:
        return None
    record = dict(zip((column[0] for column in cursor.description), value))
    content = record["content"]
    if (type(content) is not bytes or type(record["size_bytes"]) is not int
            or not 0 < record["size_bytes"] <= MAX_ARTIFACT_BYTES
            or len(content) != record["size_bytes"]
            or type(record["sha256"]) is not str or not _HEX.fullmatch(record["sha256"])
            or hashlib.sha256(content).hexdigest() != record["sha256"]
            or record["media_type"] not in _MEDIA_TYPES
            or type(record["stored_by"]) is not str
            or not record["stored_by"].startswith("operator-device:")):
        raise ExternalEvidenceUnavailable("Privates Herkunftsartefakt ist ungültig")
    try:
        captured = datetime.fromisoformat(record["stored_at"])
        if captured.tzinfo is None or captured.utcoffset() != timezone.utc.utcoffset(captured):
            raise ValueError("UTC required")
    except (ValueError, TypeError) as exc:
        raise ExternalEvidenceUnavailable("Artefaktzeit ist ungültig") from exc
    return record


def _artifact_metadata(record):
    return {"schema": ARTIFACT_SCHEMA,
            **{key: record[key] for key in ("artifact_id", "sha256", "media_type",
                                           "size_bytes", "stored_at", "stored_by")}}


def store_external_artifact(content, *, media_type, operator_token, db_path=None):
    """Hash actual supplied bytes on BACH; never accept a client digest.

    Content is private database storage, not a task-result field. Storing an
    artifact alone neither authenticates its author nor approves any result.
    """
    if type(content) is not bytes or not 0 < len(content) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Privates Herkunftsartefakt muss 1 bis 2097152 Bytes enthalten")
    if type(media_type) is not str or media_type not in _MEDIA_TYPES:
        raise ValueError("Unterstützter Herkunftsartefakt-Typ erforderlich")
    digest = hashlib.sha256(content).hexdigest()
    with settings._connection(db_path, write=True) as conn:
        actor = require_operator(conn, operator_token)
        _ensure_artifact_schema(conn)
        old = conn.execute("SELECT artifact_id FROM worker_external_artifacts WHERE sha256=?",
                           (digest,)).fetchone()
        if old is not None:
            existing = _artifact_record(conn, old[0])
            if existing["content"] != content or existing["media_type"] != media_type:
                raise ExternalEvidenceConflict("Unveränderliches Herkunftsartefakt weicht ab")
            return {**_artifact_metadata(existing), "created": False}
        artifact_id = uuid.uuid4().hex
        stored_at = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO worker_external_artifacts "
                     "(artifact_id,sha256,media_type,size_bytes,content,stored_at,stored_by) "
                     "VALUES (?,?,?,?,?,?,?)", (artifact_id, digest, media_type, len(content),
                                              content, stored_at, actor))
        record = _artifact_record(conn, artifact_id)
        return {**_artifact_metadata(record), "created": True}


def read_external_artifact(artifact_id, *, operator_token, db_path=None):
    """Explicit operator-only private read, never part of a public result DTO."""
    # Operator authorization uses an existing transaction. BEGIN IMMEDIATE is
    # deliberate so revocation cannot race this private byte read.
    with settings._connection(db_path, write=True) as conn:
        require_operator(conn, operator_token)
        record = _artifact_record(conn, artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        return {**_artifact_metadata(record), "content": record["content"]}


def artifact_manifest(conn, artifact_ids):
    """Internal pure read for a future attestation; verifies the stored bytes."""
    if (type(artifact_ids) is not list or not 1 <= len(artifact_ids) <= 8
            or any(type(value) is not str for value in artifact_ids)
            or len(set(artifact_ids)) != len(artifact_ids)):
        raise ValueError("Ein bis acht eindeutige private Herkunftsartefakte erforderlich")
    records = []
    for artifact_id in artifact_ids:
        record = _artifact_record(conn, artifact_id)
        if record is None:
            raise ExternalEvidenceUnavailable("Privates Herkunftsartefakt fehlt")
        records.append({key: record[key] for key in ("artifact_id", "sha256", "size_bytes", "media_type")})
    return records
