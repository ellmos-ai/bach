# SPDX-License-Identifier: MIT
"""Paketgelieferte Systemvorlagen (P05 Schritt 3a) und ihr Capability-Status (3e).

Ein Provider ist ein konfigurierter Befehl ``{"id", "command": [...]}`` in
``BACH_TEMPLATE_PROVIDERS_FILE`` (Standard ``<BACH_LOCAL_DIR>/template_providers.json``,
Form ``{"providers": [...]}``). BACH ruft ihn ohne Shell mit Timeout auf, prüft
Schema, Version und sha256 und legt die Vorlage als ``is_template=1`` an –
eindeutig je (provider, id, version). Eine andere Version wird nie still
übernommen, sondern nur über ``migrate_template``. Materialisierte Agenten
behalten ihre Zeile; ein fehlender Provider sperrt nur neue Materialisierungen.

Prüfregel für ``sha256``: sha256 über kanonisches JSON (sort_keys, kompakt,
UTF-8) von ``{"schema", "id", "blueprint"}`` der Providerausgabe.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blueprint_service import (ALLOWED_KINDS, _ID, ensure_blueprint_schema,
                                synthesize_start_prompt, validate_blueprint_fields)

TIMEOUT_SECONDS = 20
MAX_OUTPUT_BYTES = 1024 * 1024
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]{1,32})?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
ENVELOPE_FIELDS = {"schema", "command", "ok", "mode", "data", "errors"}
DESCRIPTOR_FIELDS = {"schema", "id", "version", "sha256", "capability", "blueprint", "permissions"}
CAPABILITY_FIELDS = {"package", "version", "spi_version", "source_commit"}
BLUEPRINT_FIELDS = {"name", "title", "kind", "description", "persona_role", "persona_prompt",
                    "skills", "animus_type", "modus", "contractus", "governance"}

# ponytail: prozesslokal; nach Neustart "provider_not_probed" bis zum nächsten Sync.
_PROBES: dict[str, dict[str, Any]] = {}


class TemplateProviderError(RuntimeError):
    """Fail-closed mit stabilem Grundcode als Nachricht."""


def providers_file() -> Path:
    configured = os.environ.get("BACH_TEMPLATE_PROVIDERS_FILE")
    if configured:
        return Path(configured).expanduser()
    from hub.bach_paths import LOCAL_BACH_DIR
    return LOCAL_BACH_DIR / "template_providers.json"


def load_providers(path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path else providers_file()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TemplateProviderError("provider_config_invalid") from exc
    items = raw.get("providers") if isinstance(raw, dict) and set(raw) == {"providers"} else None
    if not isinstance(items, list):
        raise TemplateProviderError("provider_config_invalid")
    providers, seen = [], set()
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"id", "command"}
                or not isinstance(item["id"], str) or not _ID.fullmatch(item["id"]) or item["id"] in seen
                or not isinstance(item["command"], list) or not 0 < len(item["command"]) <= 32
                or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in item["command"])):
            raise TemplateProviderError("provider_config_invalid")
        seen.add(item["id"])
        providers.append({"id": item["id"], "command": list(item["command"])})
    return providers


def template_sha256(descriptor: dict[str, Any]) -> str:
    material = {key: descriptor[key] for key in ("schema", "id", "blueprint")}
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_descriptor(provider_id: str, payload: Any) -> dict[str, Any]:
    """Prüft die Providerausgabe streng; unbekannte Felder werden abgewiesen."""
    if isinstance(payload, dict) and payload.get("schema") == f"{provider_id}.result/v1":
        if set(payload) - ENVELOPE_FIELDS or payload.get("ok") is not True or payload.get("errors"):
            raise TemplateProviderError("provider_result_not_ok")
        payload = payload.get("data")
    if not isinstance(payload, dict):
        raise TemplateProviderError("schema_mismatch")
    if set(payload) - DESCRIPTOR_FIELDS:
        raise TemplateProviderError("unknown_fields")
    capability, blueprint = payload.get("capability"), payload.get("blueprint")
    if (payload.get("schema") != f"{provider_id}.system-agent/v1"
            or not DESCRIPTOR_FIELDS - {"permissions"} <= set(payload)
            or not isinstance(capability, dict) or not isinstance(blueprint, dict)):
        raise TemplateProviderError("schema_mismatch")
    if set(capability) - CAPABILITY_FIELDS or set(blueprint) - BLUEPRINT_FIELDS:
        raise TemplateProviderError("unknown_fields")
    version, template_id = payload["version"], payload["id"]
    if (not isinstance(version, str) or not _VERSION.fullmatch(version)
            or capability.get("version") != version or capability.get("package") != provider_id):
        raise TemplateProviderError("version_invalid")
    commit = capability.get("source_commit")
    if (not isinstance(template_id, str) or not _ID.fullmatch(template_id)
            or not _ID.fullmatch(f"{provider_id}.{template_id}.v{version}")
            or (commit is not None and (not isinstance(commit, str) or not _COMMIT.fullmatch(commit)))):
        raise TemplateProviderError("schema_mismatch")
    if not isinstance(payload["sha256"], str) or not _SHA256.fullmatch(payload["sha256"]) \
            or template_sha256(payload) != payload["sha256"]:
        raise TemplateProviderError("hash_mismatch")
    fields = {"title": blueprint.get("title", ""), "description": blueprint.get("description", ""),
              "persona_role": blueprint.get("persona_role", ""),
              "persona_prompt": blueprint.get("persona_prompt", ""),
              "animus_type": blueprint.get("animus_type", "subscription"),
              "modus": blueprint.get("modus", "casualis"), "skills": blueprint.get("skills", []),
              "contractus": blueprint.get("contractus", {}), "governance": blueprint.get("governance", {}),
              "kind": blueprint.get("kind", "agent")}
    try:
        validate_blueprint_fields(fields["title"], fields["description"], fields["persona_role"],
                                  fields["persona_prompt"], fields["animus_type"], fields["modus"],
                                  fields["skills"], fields["contractus"], fields["governance"])
    except ValueError as exc:
        raise TemplateProviderError("blueprint_invalid") from exc
    if (not fields["title"] or not isinstance(fields["kind"], str) or fields["kind"] not in ALLOWED_KINDS
            or (fields["kind"] in {"agent", "role"} and not fields["persona_prompt"].strip())):
        raise TemplateProviderError("blueprint_invalid")
    return {"id": template_id, "version": version, "sha256": payload["sha256"],
            "source_commit": commit, "fields": fields}


def probe(provider: dict[str, Any], *, runner=subprocess.run, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Echte Probe: Exitcode, Schema, Version und sha256. Wirft nie."""
    result = {"id": provider["id"], "available": False, "observed_at": datetime.now(timezone.utc).isoformat(),
              "template_id": None, "version": None, "sha256": None, "source_commit": None}
    try:
        try:
            done = runner(provider["command"], capture_output=True, timeout=timeout, shell=False, check=False,
                          stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError as exc:
            raise TemplateProviderError("provider_missing") from exc
        except subprocess.TimeoutExpired as exc:
            raise TemplateProviderError("provider_timeout") from exc
        except OSError as exc:
            raise TemplateProviderError("provider_not_executable") from exc
        if done.returncode != 0:
            raise TemplateProviderError("provider_exit_nonzero")
        if len(done.stdout or b"") > MAX_OUTPUT_BYTES:
            raise TemplateProviderError("provider_output_too_large")
        try:
            payload = json.loads((done.stdout or b"").decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TemplateProviderError("provider_output_invalid_json") from exc
        descriptor = validate_descriptor(provider["id"], payload)
    except TemplateProviderError as exc:
        result["reason"] = str(exc)
    else:
        result.update(available=True, reason="provider_probe_ok", descriptor=descriptor,
                      template_id=descriptor["id"], version=descriptor["version"],
                      sha256=descriptor["sha256"], source_commit=descriptor["source_commit"])
    _PROBES[provider["id"]] = {key: value for key, value in result.items() if key != "descriptor"}
    return result


def _set_status(conn, provider_id, status, reason, *, row_id=None, other_than=None):
    query = ("UPDATE agent_blueprints SET template_status = ?, template_status_reason = ?, updated_at = ? "
             "WHERE provider = ? AND COALESCE(template_status, '') != 'superseded'")
    params: list[Any] = [status, reason, datetime.now(timezone.utc).isoformat(), provider_id]
    if row_id is not None:
        query += " AND id = ?"
        params.append(row_id)
    if other_than is not None:
        query += " AND provider_template_id != ?"
        params.append(other_than)
    conn.execute(query, params)


def _active_row(conn, provider_id, template_id):
    return conn.execute(
        "SELECT id, provider_version, template_sha256 FROM agent_blueprints "
        "WHERE provider = ? AND provider_template_id = ? AND COALESCE(template_status, '') != 'superseded'",
        (provider_id, template_id)).fetchone()


def _version_row(conn, provider_id, descriptor):
    return conn.execute(
        "SELECT id, template_sha256 FROM agent_blueprints "
        "WHERE provider = ? AND provider_template_id = ? AND provider_version = ?",
        (provider_id, descriptor["id"], descriptor["version"])).fetchone()


def _insert_template(conn, provider_id, descriptor) -> int | None:
    name = f"{provider_id}.{descriptor['id']}.v{descriptor['version']}"
    if conn.execute("SELECT 1 FROM agent_blueprints WHERE name = ?", (name,)).fetchone():
        return None
    fields = descriptor["fields"]
    try:
        start_prompt = synthesize_start_prompt({"name": name, **fields})
    except (ValueError, KeyError):
        start_prompt = ""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute("""
        INSERT INTO agent_blueprints (
            name, title, description, persona_role, persona_prompt, skills_json, animus_type,
            contractus_json, modus, is_template, is_materialized, governance_json, kind, start_prompt,
            version, created_at, updated_at, provider, provider_template_id, provider_version,
            template_sha256, template_status, template_status_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'available', 'provider_probe_ok')
    """, (name, fields["title"], fields["description"], fields["persona_role"], fields["persona_prompt"],
          json.dumps(fields["skills"]), fields["animus_type"], json.dumps(fields["contractus"]),
          fields["modus"], json.dumps(fields["governance"]), fields["kind"], start_prompt, now, now,
          provider_id, descriptor["id"], descriptor["version"], descriptor["sha256"]))
    return cursor.lastrowid


def _register(conn, provider_id, probed) -> dict[str, Any]:
    out = {key: probed[key] for key in ("id", "available", "reason", "template_id", "version", "sha256")}
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not probed["available"]:
            _set_status(conn, provider_id, "unavailable", probed["reason"])
            out["action"] = "marked_unavailable"
        else:
            descriptor = probed["descriptor"]
            _set_status(conn, provider_id, "unavailable", "template_not_offered", other_than=descriptor["id"])
            active = _active_row(conn, provider_id, descriptor["id"])
            if active is None and _version_row(conn, provider_id, descriptor):
                out["action"] = "migration_required"
            elif active is None:
                out["blueprint_id"] = _insert_template(conn, provider_id, descriptor)
                out["action"] = "registered" if out["blueprint_id"] else "name_conflict"
            elif active[1] != descriptor["version"]:
                _set_status(conn, provider_id, "migration_required", "provider_version_changed", row_id=active[0])
                out.update(action="migration_required", blueprint_id=active[0], current_version=active[1])
            elif active[2] != descriptor["sha256"]:
                _set_status(conn, provider_id, "unavailable", "template_changed_without_version", row_id=active[0])
                out.update(action="marked_unavailable", blueprint_id=active[0])
            else:
                _set_status(conn, provider_id, "available", "provider_probe_ok", row_id=active[0])
                out.update(action="confirmed", blueprint_id=active[0])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return out


def sync_providers(conn: sqlite3.Connection, providers: list[dict[str, Any]] | None = None, *,
                   runner=subprocess.run, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Probt jeden konfigurierten Provider und gleicht seine Vorlagen ab (nie still überschreibend)."""
    ensure_blueprint_schema(conn)
    providers = load_providers() if providers is None else providers
    results = [_register(conn, provider["id"], probe(provider, runner=runner, timeout=timeout))
               for provider in providers]
    configured = {provider["id"] for provider in providers}
    stale = [row[0] for row in conn.execute(
        "SELECT DISTINCT provider FROM agent_blueprints WHERE provider IS NOT NULL").fetchall()
        if row[0] not in configured]
    if stale:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for provider_id in stale:
                _set_status(conn, provider_id, "unavailable", "provider_not_configured")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"schema": "bach.template-providers.sync.v1", "providers": results, "unconfigured": stale}


def migrate_template(conn: sqlite3.Connection, provider_id: str, template_id: str, *, to_version: str,
                     expected_sha256: str, providers: list[dict[str, Any]] | None = None,
                     runner=subprocess.run, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Explizite Übernahme einer anderen Vorlagenversion; die alte Zeile bleibt als 'superseded'."""
    ensure_blueprint_schema(conn)
    providers = load_providers() if providers is None else providers
    provider = next((item for item in providers if item["id"] == provider_id), None)
    if provider is None:
        raise TemplateProviderError("provider_not_configured")
    probed = probe(provider, runner=runner, timeout=timeout)
    if not probed["available"]:
        raise TemplateProviderError(probed["reason"])
    descriptor = probed["descriptor"]
    if (descriptor["id"], descriptor["version"], descriptor["sha256"]) != (template_id, to_version, expected_sha256):
        raise TemplateProviderError("offer_changed")
    conn.execute("BEGIN IMMEDIATE")
    try:
        active = _active_row(conn, provider_id, template_id)
        if active is None:
            raise TemplateProviderError("nothing_to_migrate")
        if active[1] == to_version:
            raise TemplateProviderError("already_current")
        _set_status(conn, provider_id, "superseded", f"migrated_to_{to_version}", row_id=active[0])
        previous = _version_row(conn, provider_id, descriptor)
        if previous is None:
            new_id = _insert_template(conn, provider_id, descriptor)
            if new_id is None:
                raise TemplateProviderError("name_conflict")
        elif previous[1] != expected_sha256:
            raise TemplateProviderError("template_changed_without_version")
        else:
            new_id = previous[0]
            conn.execute("UPDATE agent_blueprints SET template_status = 'available', "
                         "template_status_reason = 'provider_probe_ok' WHERE id = ?", (new_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"migrated": True, "provider": provider_id, "template_id": template_id,
            "from_version": active[1], "to_version": to_version, "blueprint_id": new_id,
            "superseded_blueprint_id": active[0]}


def capability_status() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Additive Einträge für /api/gui/capabilities; ohne Befehle oder lokale Pfade."""
    try:
        providers = load_providers()
    except TemplateProviderError as exc:
        return {"template-providers": {"adapter_registered": False, "runtime_verified": False,
                                       "available": False, "reason_code": str(exc), "observed_at": None}}, []
    modules, sources = {}, []
    for provider in providers:
        last = _PROBES.get(provider["id"]) or {}
        reason = last.get("reason", "provider_not_probed")
        modules[f"template-provider:{provider['id']}"] = {
            "adapter_registered": True, "runtime_verified": False, "available": last.get("available"),
            "reason_code": reason, "observed_at": last.get("observed_at"), "kind": "template-provider",
            "version": last.get("version")}
        sources.append({"id": provider["id"], "kind": "template-provider", "version": last.get("version"),
            "source_commit": last.get("source_commit"), "verified": False, "runtime_verified": False,
            "descriptor_verified": last.get("available") is True,
            "reason": "descriptor_probe_provenance_not_checked" if last.get("available") else reason,
            "template": ({"id": last["template_id"], "version": last["version"], "sha256": last["sha256"]}
                         if last.get("available") else None)})
    return modules, sources
