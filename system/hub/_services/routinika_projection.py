# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Read-only BACH consumer for the ratified Routinika reminder projection.

The allowlist is pinned to sqlite-transit-sync contract C1 at
``fd19d5e6717c1b51950dc521bd41763967d21739`` (contract blob
``6033191c84d450b5c490b9ef4aa3e2ec4c5ba138``).  This module only verifies and
reads a closed projection.  It never publishes, copies, merges, migrates, or
advances federation state.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


CONTRACT_ID = "org.ellmos.routinika.reminder-projection"
CONTRACT_VERSION = "1.0.0"
PUBLISHER_COMPONENT = "routinika-projection-adapter"
CONSUMER_ID = "bach-reminder-consumer"
DEFAULT_MINIMUM_OFFLINE_SECONDS = 30 * 24 * 60 * 60
CONTRACT_SOURCE_COMMIT = "fd19d5e6717c1b51950dc521bd41763967d21739"
CONTRACT_SOURCE_BLOB = "6033191c84d450b5c490b9ef4aa3e2ec4c5ba138"

_OPAQUE_REF = re.compile(r"^[0-9a-f]{32,64}$")
_SAFE_PARTICIPANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_ACTIVE_STATES = frozenset({"due", "overdue"})
_ALL_STATES = _ACTIVE_STATES | {"completed", "skipped", "cancelled"}

# name, SQLite type, NOT NULL, primary-key position
_EXPECTED_SCHEMA = {
    "projection_metadata": (
        ("contract_id", "TEXT", True, 1),
        ("contract_version", "TEXT", True, 0),
        ("publisher_component", "TEXT", True, 0),
        ("publisher_instance", "TEXT", True, 0),
        ("generated_at", "TEXT", True, 0),
        ("source_checkpoint", "INTEGER", True, 0),
    ),
    "routine_due": (
        ("record_ref", "TEXT", True, 1),
        ("due_at", "TEXT", True, 0),
        ("window_end_at", "TEXT", True, 0),
        ("state", "TEXT", True, 0),
        ("record_version", "INTEGER", True, 0),
        ("source_checkpoint", "INTEGER", True, 0),
        ("publisher_instance", "TEXT", True, 0),
    ),
    "projection_tombstones": (
        ("record_type", "TEXT", True, 1),
        ("record_ref", "TEXT", True, 2),
        ("deleted_at", "TEXT", True, 0),
        ("retain_until", "TEXT", True, 0),
        ("record_version", "INTEGER", True, 0),
        ("source_checkpoint", "INTEGER", True, 0),
        ("publisher_instance", "TEXT", True, 0),
    ),
}


class RoutinikaProjectionError(ValueError):
    """The closed projection does not satisfy the pinned consumer contract."""


@dataclass(frozen=True, slots=True)
class RoutinikaDueRecord:
    record_ref: str
    due_at: str
    window_end_at: str
    state: str
    record_version: int


@dataclass(frozen=True, slots=True)
class RoutinikaProjection:
    publisher_instance: str
    generated_at: str
    source_checkpoint: int
    database_name: str
    database_sha256: str
    row_counts: dict[str, int]
    due_records: tuple[RoutinikaDueRecord, ...]
    read_only: bool = True
    contract_id: str = CONTRACT_ID
    contract_version: str = CONTRACT_VERSION


def read_routinika_projection(
    database: str | Path,
    *,
    minimum_offline_seconds: int = DEFAULT_MINIMUM_OFFLINE_SECONDS,
    previous_checkpoint: int | None = None,
) -> RoutinikaProjection:
    """Verify and read one closed projection without mutating either database."""
    if type(minimum_offline_seconds) is not int or minimum_offline_seconds < 0:
        raise RoutinikaProjectionError(
            "minimum_offline_seconds muss eine nicht negative Ganzzahl sein."
        )
    if previous_checkpoint is not None and (
        type(previous_checkpoint) is not int or previous_checkpoint < 0
    ):
        raise RoutinikaProjectionError(
            "previous_checkpoint muss eine nicht negative Ganzzahl sein."
        )

    path = _closed_regular_database(Path(database))
    before_hash = _sha256(path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            raise RoutinikaProjectionError(
                f"SQLite quick_check fehlgeschlagen: {quick_check!r}"
            )
        _verify_schema(connection)
        metadata_rows = connection.execute(
            "SELECT * FROM projection_metadata"
        ).fetchall()
        routine_rows = connection.execute("SELECT * FROM routine_due").fetchall()
        tombstone_rows = connection.execute(
            "SELECT * FROM projection_tombstones"
        ).fetchall()

        publisher, generated_at, checkpoint = _verify_metadata(
            metadata_rows, previous_checkpoint=previous_checkpoint
        )
        due_records = _verify_routines(
            routine_rows, publisher=publisher, checkpoint=checkpoint
        )
        _verify_tombstones(
            tombstone_rows,
            routine_rows,
            publisher=publisher,
            checkpoint=checkpoint,
            minimum_offline_seconds=minimum_offline_seconds,
        )
    except sqlite3.Error as exc:
        raise RoutinikaProjectionError(
            f"Routinika-Projektion konnte nicht verifiziert werden: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    after_hash = _sha256(path)
    if after_hash != before_hash:
        raise RoutinikaProjectionError(
            "Routinika-Projektion hat sich während der read-only Prüfung verändert."
        )

    return RoutinikaProjection(
        publisher_instance=publisher,
        generated_at=generated_at,
        source_checkpoint=checkpoint,
        database_name=path.name,
        database_sha256=after_hash,
        row_counts={
            "projection_metadata": len(metadata_rows),
            "routine_due": len(routine_rows),
            "projection_tombstones": len(tombstone_rows),
        },
        due_records=tuple(
            sorted(due_records, key=lambda row: (row.due_at, row.record_ref))
        ),
    )


def format_routinika_briefing(
    projection: RoutinikaProjection, *, include_receipt: bool = False
) -> str:
    """Render only due/overdue opaque records plus optional receipt metadata."""
    parts = [f"\nROUTINIKA-FÄLLIGKEITEN ({len(projection.due_records)}):"]
    state_labels = {"due": "fällig", "overdue": "überfällig"}
    for row in projection.due_records[:10]:
        due = _display_utc(row.due_at)
        window_end = _display_utc(row.window_end_at)
        parts.append(
            f"  - Routine {row.record_ref[:12]}…: {state_labels[row.state]} "
            f"({due}; Fenster bis {window_end})"
        )
    if len(projection.due_records) > 10:
        parts.append(f"  - … und {len(projection.due_records) - 10} weitere")
    if include_receipt:
        counts = ",".join(
            f"{name}:{count}" for name, count in projection.row_counts.items()
        )
        parts.append(
            "  [Receipt] "
            f"contract={projection.contract_id}@{projection.contract_version}; "
            f"publisher={projection.publisher_instance}; "
            f"checkpoint={projection.source_checkpoint}; "
            f"generated_at={projection.generated_at}; rows={counts}; "
            f"sha256={projection.database_sha256}; read_only=true"
        )
    return "\n".join(parts)


def _closed_regular_database(path: Path) -> Path:
    candidate = path.expanduser()
    try:
        attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RoutinikaProjectionError(
            f"Routinika-Projektion ist keine lesbare reguläre Datei: {candidate}"
        ) from exc
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if candidate.is_symlink() or bool(attributes & reparse) or not resolved.is_file():
        raise RoutinikaProjectionError(
            "Routinika-Projektion muss eine direkte reguläre Datei sein."
        )
    sidecars = sorted(item.name for item in resolved.parent.glob(f"{resolved.name}-*"))
    if sidecars:
        raise RoutinikaProjectionError(
            f"Routinika-Projektion ist nicht geschlossen; Sidecars vorhanden: {sidecars}"
        )
    return resolved


def _verify_schema(connection: sqlite3.Connection) -> None:
    actual_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    expected_tables = set(_EXPECTED_SCHEMA)
    if actual_tables != expected_tables:
        raise RoutinikaProjectionError(
            "Tabellen-Allowlist verletzt; "
            f"extra={sorted(actual_tables - expected_tables)}, "
            f"fehlend={sorted(expected_tables - actual_tables)}"
        )
    unexpected = connection.execute(
        "SELECT type, name FROM sqlite_schema "
        "WHERE type IN ('view', 'trigger') "
        "OR (type = 'index' AND sql IS NOT NULL)"
    ).fetchall()
    if unexpected:
        raise RoutinikaProjectionError(
            f"Nicht erlaubte SQLite-Objekte: {[tuple(row) for row in unexpected]}"
        )

    for table, expected_columns in _EXPECTED_SCHEMA.items():
        actual = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        if len(actual) != len(expected_columns):
            raise RoutinikaProjectionError(
                f"Spalten-Allowlist für {table} verletzt."
            )
        for row, expected in zip(actual, expected_columns, strict=True):
            name, sqlite_type, not_null, primary_key = expected
            if (
                row[1] != name
                or str(row[2]).upper() != sqlite_type
                or bool(row[3]) != not_null
                or row[4] is not None
                or int(row[5]) != primary_key
            ):
                raise RoutinikaProjectionError(
                    f"Spalten-Allowlist für {table}.{name} verletzt."
                )


def _verify_metadata(
    rows: list[sqlite3.Row], *, previous_checkpoint: int | None
) -> tuple[str, str, int]:
    if len(rows) != 1:
        raise RoutinikaProjectionError(
            "projection_metadata muss genau eine Zeile enthalten."
        )
    row = rows[0]
    expected = {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "publisher_component": PUBLISHER_COMPONENT,
    }
    for column, value in expected.items():
        if row[column] != value:
            raise RoutinikaProjectionError(
                f"Metadatenfeld {column} entspricht nicht dem Vertrag."
            )
    publisher = _participant(row["publisher_instance"], "publisher_instance")
    if publisher == CONSUMER_ID:
        raise RoutinikaProjectionError("Loop-Guard hat den eigenen Consumer abgewiesen.")
    generated_at = row["generated_at"]
    _utc_timestamp(generated_at, "projection_metadata.generated_at")
    checkpoint = _integer(row["source_checkpoint"], "source_checkpoint", minimum=0)
    if previous_checkpoint is not None and checkpoint <= previous_checkpoint:
        raise RoutinikaProjectionError(
            "Projektions-Checkpoint ist nicht neuer als der Consumer-Checkpoint."
        )
    return publisher, generated_at, checkpoint


def _verify_routines(
    rows: list[sqlite3.Row], *, publisher: str, checkpoint: int
) -> list[RoutinikaDueRecord]:
    due_records = []
    for index, row in enumerate(rows):
        ref = _opaque_ref(row["record_ref"], f"routine_due[{index}].record_ref")
        due = _utc_timestamp(row["due_at"], f"routine_due[{index}].due_at")
        window_end = _utc_timestamp(
            row["window_end_at"], f"routine_due[{index}].window_end_at"
        )
        if window_end < due:
            raise RoutinikaProjectionError(
                f"Ungültiges Fälligkeitsfenster in routine_due[{index}]."
            )
        state_value = row["state"]
        if not isinstance(state_value, str) or state_value not in _ALL_STATES:
            raise RoutinikaProjectionError(
                f"Unzulässiger Zustand in routine_due[{index}]."
            )
        version = _integer(
            row["record_version"], f"routine_due[{index}].record_version", minimum=1
        )
        _matching_provenance(row, publisher=publisher, checkpoint=checkpoint)
        if state_value in _ACTIVE_STATES:
            due_records.append(
                RoutinikaDueRecord(
                    record_ref=ref,
                    due_at=row["due_at"],
                    window_end_at=row["window_end_at"],
                    state=state_value,
                    record_version=version,
                )
            )
    return due_records


def _verify_tombstones(
    rows: list[sqlite3.Row],
    routine_rows: list[sqlite3.Row],
    *,
    publisher: str,
    checkpoint: int,
    minimum_offline_seconds: int,
) -> None:
    active = {row["record_ref"]: row for row in routine_rows}
    for index, row in enumerate(rows):
        if row["record_type"] != "routine_due":
            raise RoutinikaProjectionError(
                f"Unzulässiger record_type in projection_tombstones[{index}]."
            )
        ref = _opaque_ref(
            row["record_ref"], f"projection_tombstones[{index}].record_ref"
        )
        deleted = _utc_timestamp(
            row["deleted_at"], f"projection_tombstones[{index}].deleted_at"
        )
        retained = _utc_timestamp(
            row["retain_until"], f"projection_tombstones[{index}].retain_until"
        )
        version = _integer(
            row["record_version"],
            f"projection_tombstones[{index}].record_version",
            minimum=1,
        )
        _matching_provenance(row, publisher=publisher, checkpoint=checkpoint)
        if (retained - deleted).total_seconds() < minimum_offline_seconds:
            raise RoutinikaProjectionError(
                "Tombstone-Aufbewahrung deckt das Offline-Intervall nicht ab."
            )
        active_row = active.get(ref)
        if active_row is not None and active_row["record_version"] <= version:
            raise RoutinikaProjectionError(
                "Tombstone kollidiert mit einer gleich alten oder älteren aktiven Zeile."
            )


def _matching_provenance(
    row: sqlite3.Row, *, publisher: str, checkpoint: int
) -> None:
    if row["publisher_instance"] != publisher:
        raise RoutinikaProjectionError("Publisher-Provenienz stimmt nicht überein.")
    if row["source_checkpoint"] != checkpoint:
        raise RoutinikaProjectionError("Quell-Checkpoint stimmt nicht überein.")


def _participant(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SAFE_PARTICIPANT.fullmatch(value) is None:
        raise RoutinikaProjectionError(f"{label} enthält unsichere Zeichen.")
    return value


def _opaque_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or _OPAQUE_REF.fullmatch(value) is None:
        raise RoutinikaProjectionError(f"{label} ist keine opake Hex-Referenz.")
    return value


def _integer(value: Any, label: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise RoutinikaProjectionError(
            f"{label} muss eine Ganzzahl ab {minimum} sein."
        )
    return value


def _utc_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise RoutinikaProjectionError(f"{label} muss ein UTC-Zeitstempel sein.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RoutinikaProjectionError(
            f"{label} muss ein ISO-8601-UTC-Zeitstempel sein."
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise RoutinikaProjectionError(f"{label} muss UTC verwenden.")
    return parsed


def _display_utc(value: str) -> str:
    parsed = _utc_timestamp(value, "briefing timestamp")
    return parsed.strftime("%d.%m.%Y %H:%M UTC")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
