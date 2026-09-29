"""Reusable append-only SQLite store for evidenced household inventory."""

from __future__ import annotations

import json
import os
import sqlite3
from hashlib import sha256
from pathlib import Path

from folderhome.contracts import (
    InventoryEventRecord,
    InventoryEvidence,
    InventoryImportAction,
    InventoryImportApproval,
)

_SCHEMA_VERSION = "folderhome.inventory-store.v1"


class InventoryStoreError(RuntimeError):
    """Raised when local inventory state is stale, unsafe, or inconsistent."""


class InventoryStore:
    """Read and transactionally append inventory observations."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = _safe_state_root(state_dir)
        self.path = self.state_dir / "inventory" / "inventory.sqlite3"

    def revision(self) -> str:
        return _revision(self.list_events())

    def list_events(
        self,
        *,
        profile_id: str | None = None,
        item_id: str | None = None,
        area: str | None = None,
    ) -> tuple[InventoryEventRecord, ...]:
        if not self.path.exists():
            return ()
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            clauses = []
            parameters: list[str] = []
            if profile_id is not None:
                clauses.append("profile_id = ?")
                parameters.append(profile_id)
            if item_id is not None:
                clauses.append("item_id = ?")
                parameters.append(item_id)
            if area is not None:
                clauses.append("area = ?")
                parameters.append(area)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(
                "SELECT * FROM inventory_events"
                f"{where} ORDER BY observed_on, event_id",
                parameters,
            ).fetchall()
            return tuple(_event_record(row) for row in rows)
        except sqlite3.Error as exc:
            raise InventoryStoreError(f"Inventar-State ist nicht lesbar: {exc}") from exc
        finally:
            connection.close()

    def current_items(
        self,
        *,
        profile_id: str | None = None,
        area: str | None = None,
        as_of: str | None = None,
    ) -> tuple[InventoryEventRecord, ...]:
        current: dict[str, InventoryEventRecord] = {}
        for event in self.list_events(profile_id=profile_id, area=area):
            if as_of is not None and event.observed_on > as_of:
                continue
            current[event.item_id] = event
        return tuple(sorted(current.values(), key=lambda item: item.item_id))

    def count_audit_events(self) -> int:
        if not self.path.exists():
            return 0
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            return int(
                connection.execute("SELECT COUNT(*) FROM inventory_audit_events").fetchone()[0]
            )
        finally:
            connection.close()

    def validate_execution(self, *, expected_revision: str, approval_id: str) -> None:
        if not self.path.exists():
            if expected_revision != EMPTY_INVENTORY_REVISION:
                raise InventoryStoreError("Inventar-State wurde seit der Planung verändert.")
            return
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            if self._revision_from_connection(connection) != expected_revision:
                raise InventoryStoreError("Inventar-State wurde seit der Planung verändert.")
            if connection.execute(
                "SELECT 1 FROM inventory_audit_events WHERE approval_id = ? LIMIT 1",
                (approval_id,),
            ).fetchone():
                raise InventoryStoreError("Inventarfreigabe wurde bereits verwendet.")
        finally:
            connection.close()

    def apply(
        self,
        *,
        expected_revision: str,
        actions: tuple[InventoryImportAction, ...],
        approval: InventoryImportApproval,
    ) -> tuple[tuple[str, ...], str]:
        connection = self._write_connection()
        event_ids: list[str] = []
        try:
            _initialize_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            if self._revision_from_connection(connection) != expected_revision:
                raise InventoryStoreError("Inventar-State wurde seit der Planung verändert.")
            if connection.execute(
                "SELECT 1 FROM inventory_audit_events WHERE approval_id = ? LIMIT 1",
                (approval.approval_id,),
            ).fetchone():
                raise InventoryStoreError("Inventarfreigabe wurde bereits verwendet.")
            for action in actions:
                observation = action.observation
                connection.execute(
                    "INSERT INTO inventory_events "
                    "(event_id, item_id, profile_id, area, name, unit, location, "
                    "quantity_milli, minimum_quantity_milli, observed_on, expiry_date, "
                    "source_document_id, source_sha256, source_path, evidence_json, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        observation.event_id,
                        observation.item_id,
                        observation.profile_id,
                        observation.area,
                        observation.name,
                        observation.unit,
                        observation.location,
                        observation.quantity_milli,
                        observation.minimum_quantity_milli,
                        observation.observed_on,
                        observation.expiry_date,
                        observation.source_document_id,
                        observation.source_sha256,
                        str(observation.source_path),
                        json.dumps(
                            [item.to_dict() for item in observation.evidence],
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        approval.approved_at,
                    ),
                )
                event_ids.append(observation.event_id)
                audit_material = f"{approval.approval_id}\0{action.action_id}"
                connection.execute(
                    "INSERT INTO inventory_audit_events "
                    "(audit_id, approval_id, plan_id, action_id, event_id, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"inventory_audit_{sha256(audit_material.encode('utf-8')).hexdigest()}",
                        approval.approval_id,
                        approval.plan_id,
                        action.action_id,
                        observation.event_id,
                        approval.approved_at,
                    ),
                )
            revision_after = self._revision_from_connection(connection)
            connection.commit()
            return tuple(event_ids), revision_after
        except InventoryStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise InventoryStoreError(
                f"Inventar-State konnte nicht ergänzt werden: {exc}"
            ) from exc
        finally:
            connection.close()

    def _revision_from_connection(self, connection: sqlite3.Connection) -> str:
        events = tuple(
            _event_record(row)
            for row in connection.execute(
                "SELECT * FROM inventory_events ORDER BY observed_on, event_id"
            ).fetchall()
        )
        return _revision(events)

    def _write_connection(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise InventoryStoreError("Inventar-State darf kein symbolischer Link sein.")
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _read_connection(self) -> sqlite3.Connection:
        if self.path.is_symlink() or not self.path.is_file():
            raise InventoryStoreError(
                f"Inventar-State fehlt oder ist keine reguläre Datei: {self.path}"
            )
        connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_events (
            event_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            area TEXT NOT NULL,
            name TEXT NOT NULL,
            unit TEXT NOT NULL,
            location TEXT NOT NULL,
            quantity_milli INTEGER NOT NULL,
            minimum_quantity_milli INTEGER NOT NULL,
            observed_on TEXT NOT NULL,
            expiry_date TEXT,
            source_document_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_path TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_inventory_item_date
            ON inventory_events(item_id, observed_on, event_id);
        CREATE INDEX IF NOT EXISTS idx_inventory_profile
            ON inventory_events(profile_id, item_id);
        CREATE TABLE IF NOT EXISTS inventory_audit_events (
            audit_id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            action_id TEXT NOT NULL UNIQUE,
            event_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        """
    )
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'schema'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO metadata (key, value) VALUES ('schema', ?)",
            (_SCHEMA_VERSION,),
        )
    elif row[0] != _SCHEMA_VERSION:
        raise InventoryStoreError("Inventar-State verwendet ein unbekanntes Schema.")


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise InventoryStoreError("Inventar-State besitzt kein gültiges Schema.") from exc
    if row is None or row[0] != _SCHEMA_VERSION:
        raise InventoryStoreError("Inventar-State verwendet ein unbekanntes Schema.")


def _event_record(row: sqlite3.Row) -> InventoryEventRecord:
    evidence_payload = json.loads(str(row["evidence_json"]))
    evidence = tuple(
        InventoryEvidence(
            field=str(item["field"]),
            line_number=int(item["line_number"]),
            label=str(item["label"]),
        )
        for item in evidence_payload
    )
    return InventoryEventRecord(
        event_id=str(row["event_id"]),
        item_id=str(row["item_id"]),
        profile_id=str(row["profile_id"]),
        area=str(row["area"]),
        name=str(row["name"]),
        unit=str(row["unit"]),
        location=str(row["location"]),
        quantity_milli=int(row["quantity_milli"]),
        minimum_quantity_milli=int(row["minimum_quantity_milli"]),
        observed_on=str(row["observed_on"]),
        expiry_date=str(row["expiry_date"]) if row["expiry_date"] is not None else None,
        source_document_id=str(row["source_document_id"]),
        source_sha256=str(row["source_sha256"]),
        source_path=str(row["source_path"]),
        evidence=evidence,
        recorded_at=str(row["recorded_at"]),
    )


def _revision(events: tuple[InventoryEventRecord, ...]) -> str:
    material = json.dumps(
        [item.to_dict() for item in events],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"inventory_revision_{sha256(material).hexdigest()}"


def _safe_state_root(state_dir: Path) -> Path:
    absolute = Path(os.path.abspath(state_dir))
    if absolute.is_symlink() or absolute.resolve(strict=False) != absolute:
        raise InventoryStoreError(
            f"State-Verzeichnis enthält einen symbolischen Link oder Alias: {absolute}"
        )
    return absolute


EMPTY_INVENTORY_REVISION = _revision(())
