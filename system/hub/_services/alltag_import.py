"""Versionierte Dateiimporte für AboTracker und VersicherungsManager."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


MAX_IMPORT_BYTES = 10 * 1024 * 1024
_INTERVAL_RE = re.compile(r"^[1-9][0-9]*[smhd]$")


class AlltagImportError(ValueError):
    """Ein Importvertrag ist ungültig oder nicht sicher ausführbar."""


def load_payload(
    path: Path,
    expected_schema: str,
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Lädt ein begrenztes UTF-8-JSON und prüft den exakten Schemavertrag."""
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise AlltagImportError(f"Importdatei nicht gefunden: {path}") from exc
    if not resolved.is_file():
        raise AlltagImportError(f"Importpfad ist keine Datei: {resolved}")
    if resolved.stat().st_size > MAX_IMPORT_BYTES:
        raise AlltagImportError("Importdatei überschreitet das Limit von 10 MiB.")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise AlltagImportError("Importdatei muss UTF-8-kodiert sein.") from exc
    except json.JSONDecodeError as exc:
        raise AlltagImportError(f"Ungültiges JSON: Zeile {exc.lineno}, Spalte {exc.colno}.") from exc
    if not isinstance(payload, dict):
        raise AlltagImportError("Importwurzel muss ein JSON-Objekt sein.")
    if payload.get("schema") != expected_schema:
        raise AlltagImportError(
            f"Falsches Schema: erwartet {expected_schema}, erhalten "
            f"{payload.get('schema')!r}."
        )
    if expected_version is not None and payload.get("schema_version") != expected_version:
        raise AlltagImportError(
            f"Falsche Schema-Version: erwartet {expected_version}, erhalten "
            f"{payload.get('schema_version')!r}."
        )
    return payload


def parse_interval(value: str | None) -> str:
    interval = (value or "24h").strip().lower()
    if not _INTERVAL_RE.fullmatch(interval):
        raise AlltagImportError(
            "Intervall muss eine positive Zahl mit s, m, h oder d sein, z. B. 24h."
        )
    return interval


def scheduler_job_upsert(
    conn,
    *,
    name: str,
    profile_name: str,
    description: str,
    schedule: str,
    script_path: Path,
    arguments: str,
    dry_run: bool,
) -> str:
    """Legt einen aktiven, idempotenten Dateiimport-Job an oder aktualisiert ihn."""
    existing = conn.execute(
        "SELECT id FROM scheduler_jobs WHERE name = ?", (name,)
    ).fetchone()
    action = "aktualisiert" if existing else "angelegt"
    if dry_run:
        return action

    now = datetime.now().isoformat()
    if existing:
        conn.execute(
            """
            UPDATE scheduler_jobs
            SET profile_name = ?, description = ?, job_type = 'interval',
                schedule = ?, command = ?, script_path = ?, arguments = ?,
                is_active = 1, retry_on_fail = 0, updated_at = ?
            WHERE id = ?
            """,
            (
                profile_name,
                description,
                schedule,
                f"bach {profile_name} import",
                str(script_path),
                arguments,
                now,
                existing[0],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO scheduler_jobs
                (name, profile_name, description, job_type, schedule, command,
                 script_path, arguments, is_active, timeout_seconds,
                 retry_on_fail, created_at, updated_at)
            VALUES (?, ?, ?, 'interval', ?, ?, ?, ?, 1, 120, 0, ?, ?)
            """,
            (
                name,
                profile_name,
                description,
                schedule,
                f"bach {profile_name} import",
                str(script_path),
                arguments,
                now,
                now,
            ),
        )
    return action


def import_cli_arguments(profile_name: str, path: Path) -> str:
    if profile_name not in {"abo", "versicherung"}:
        raise AlltagImportError(f"Unzulässiges Importprofil: {profile_name!r}.")
    resolved = path.expanduser().resolve(strict=True)
    if '"' in str(resolved):
        raise AlltagImportError("Importpfad darf kein Anführungszeichen enthalten.")
    return f'{profile_name} import "{resolved}"'
