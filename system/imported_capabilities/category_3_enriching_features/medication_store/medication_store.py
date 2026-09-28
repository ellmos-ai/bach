"""Append-only SQLite store for medication schedules and intake confirmations."""

from __future__ import annotations

import json
import os
import sqlite3
from hashlib import sha256
from pathlib import Path

from folderhome.contracts import (
    MedicationEvidence,
    MedicationImportAction,
    MedicationImportApproval,
    MedicationIntakeConfirmation,
    MedicationIntakeEventRecord,
    MedicationScheduleRecord,
)

_SCHEMA_VERSION = "folderhome.medication-store.v1"


class MedicationStoreError(RuntimeError):
    """Raised when medication state is stale, unsafe, or inconsistent."""


class MedicationStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = _safe_state_root(state_dir)
        self.path = self.state_dir / "medication" / "medication.sqlite3"

    def revision(self) -> str:
        return _revision(self.list_schedules(), self.list_intake_events())

    def list_schedules(
        self,
        *,
        profile_id: str | None = None,
    ) -> tuple[MedicationScheduleRecord, ...]:
        if not self.path.exists():
            return ()
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            if profile_id is None:
                rows = connection.execute(
                    "SELECT * FROM medication_schedules "
                    "ORDER BY valid_from, scheduled_time, schedule_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM medication_schedules WHERE profile_id = ? "
                    "ORDER BY valid_from, scheduled_time, schedule_id",
                    (profile_id,),
                ).fetchall()
            return tuple(_schedule_record(row) for row in rows)
        except sqlite3.Error as exc:
            raise MedicationStoreError(f"Medikamenten-State ist nicht lesbar: {exc}") from exc
        finally:
            connection.close()

    def current_schedules(
        self,
        *,
        profile_id: str,
        on_date: str,
    ) -> tuple[MedicationScheduleRecord, ...]:
        current: dict[str, MedicationScheduleRecord] = {}
        for schedule in self.list_schedules(profile_id=profile_id):
            if schedule.valid_from > on_date:
                continue
            if schedule.valid_to is not None and schedule.valid_to < on_date:
                continue
            current[schedule.schedule_key] = schedule
        return tuple(
            sorted(current.values(), key=lambda item: (item.scheduled_time, item.schedule_id))
        )

    def get_schedule(self, schedule_id: str) -> MedicationScheduleRecord | None:
        return next(
            (item for item in self.list_schedules() if item.schedule_id == schedule_id),
            None,
        )

    def list_intake_events(
        self,
        *,
        profile_id: str | None = None,
    ) -> tuple[MedicationIntakeEventRecord, ...]:
        if not self.path.exists():
            return ()
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            if profile_id is None:
                rows = connection.execute(
                    "SELECT * FROM medication_intake_events "
                    "ORDER BY scheduled_date, dose_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM medication_intake_events WHERE profile_id = ? "
                    "ORDER BY scheduled_date, dose_id",
                    (profile_id,),
                ).fetchall()
            return tuple(_intake_record(row) for row in rows)
        except sqlite3.Error as exc:
            raise MedicationStoreError(f"Einnahme-State ist nicht lesbar: {exc}") from exc
        finally:
            connection.close()

    def find_intake_event(self, dose_id: str) -> MedicationIntakeEventRecord | None:
        return next(
            (item for item in self.list_intake_events() if item.dose_id == dose_id),
            None,
        )

    def count_audit_events(self) -> int:
        if not self.path.exists():
            return 0
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            return int(
                connection.execute("SELECT COUNT(*) FROM medication_audit_events").fetchone()[0]
            )
        finally:
            connection.close()

    def validate_execution(self, *, expected_revision: str, approval_id: str) -> None:
        if not self.path.exists():
            if expected_revision != EMPTY_MEDICATION_REVISION:
                raise MedicationStoreError("Medikamenten-State wurde seit der Planung verändert.")
            return
        connection = self._read_connection()
        try:
            _validate_schema(connection)
            if self._revision_from_connection(connection) != expected_revision:
                raise MedicationStoreError("Medikamenten-State wurde seit der Planung verändert.")
            if connection.execute(
                "SELECT 1 FROM medication_audit_events WHERE approval_id = ? LIMIT 1",
                (approval_id,),
            ).fetchone():
                raise MedicationStoreError("Medikamentenfreigabe wurde bereits verwendet.")
        finally:
            connection.close()

    def apply_import(
        self,
        *,
        expected_revision: str,
        actions: tuple[MedicationImportAction, ...],
        approval: MedicationImportApproval,
    ) -> tuple[tuple[str, ...], str]:
        connection = self._write_connection()
        schedule_ids: list[str] = []
        try:
            _initialize_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            self._validate_write_transaction(
                connection,
                expected_revision=expected_revision,
                approval_id=approval.approval_id,
            )
            for action in actions:
                schedule = action.schedule
                connection.execute(
                    "INSERT INTO medication_schedules "
                    "(schedule_id, schedule_key, profile_id, medication_name, "
                    "dose_quantity_milli, dose_unit, scheduled_time, timezone, "
                    "weekdays_json, valid_from, valid_to, inventory_item_id, "
                    "source_document_id, source_sha256, source_path, evidence_json, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        schedule.schedule_id,
                        schedule.schedule_key,
                        schedule.profile_id,
                        schedule.medication_name,
                        schedule.dose_quantity_milli,
                        schedule.dose_unit,
                        schedule.scheduled_time,
                        schedule.timezone,
                        json.dumps(schedule.weekdays, separators=(",", ":")),
                        schedule.valid_from,
                        schedule.valid_to,
                        schedule.inventory_item_id,
                        schedule.source_document_id,
                        schedule.source_sha256,
                        str(schedule.source_path),
                        _evidence_json(schedule.evidence),
                        approval.approved_at,
                    ),
                )
                schedule_ids.append(schedule.schedule_id)
                _insert_audit(
                    connection,
                    approval_id=approval.approval_id,
                    plan_id=approval.plan_id,
                    action_id=action.action_id,
                    subject_id=schedule.schedule_id,
                    kind="schedule_import",
                    recorded_at=approval.approved_at,
                )
            revision_after = self._revision_from_connection(connection)
            connection.commit()
            return tuple(schedule_ids), revision_after
        except MedicationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise MedicationStoreError(
                f"Medikamenten-State konnte nicht ergänzt werden: {exc}"
            ) from exc
        finally:
            connection.close()

    def append_intake(
        self,
        *,
        confirmation: MedicationIntakeConfirmation,
        schedule: MedicationScheduleRecord,
        event_id: str,
    ) -> tuple[str, str]:
        connection = self._write_connection()
        try:
            _initialize_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            self._validate_write_transaction(
                connection,
                expected_revision=confirmation.medication_revision,
                approval_id=confirmation.confirmation_id,
            )
            if connection.execute(
                "SELECT 1 FROM medication_intake_events WHERE dose_id = ? LIMIT 1",
                (confirmation.dose_id,),
            ).fetchone():
                raise MedicationStoreError("Einnahme wurde bereits bestätigt.")
            connection.execute(
                "INSERT INTO medication_intake_events "
                "(event_id, dose_id, schedule_id, profile_id, scheduled_date, "
                "confirmed_at, confirmation_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    confirmation.dose_id,
                    confirmation.schedule_id,
                    schedule.profile_id,
                    confirmation.scheduled_date,
                    confirmation.confirmed_at,
                    confirmation.confirmation_id,
                ),
            )
            _insert_audit(
                connection,
                approval_id=confirmation.confirmation_id,
                plan_id="intake_confirmation",
                action_id=confirmation.dose_id,
                subject_id=event_id,
                kind="intake_confirmation",
                recorded_at=confirmation.confirmed_at,
            )
            revision_after = self._revision_from_connection(connection)
            connection.commit()
            return event_id, revision_after
        except MedicationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise MedicationStoreError(
                f"Einnahmebestätigung konnte nicht ergänzt werden: {exc}"
            ) from exc
        finally:
            connection.close()

    def _validate_write_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        expected_revision: str,
        approval_id: str,
    ) -> None:
        if self._revision_from_connection(connection) != expected_revision:
            raise MedicationStoreError("Medikamenten-State wurde seit der Planung verändert.")
        if connection.execute(
            "SELECT 1 FROM medication_audit_events WHERE approval_id = ? LIMIT 1",
            (approval_id,),
        ).fetchone():
            raise MedicationStoreError("Medikamentenfreigabe wurde bereits verwendet.")

    def _revision_from_connection(self, connection: sqlite3.Connection) -> str:
        schedules = tuple(
            _schedule_record(row)
            for row in connection.execute(
                "SELECT * FROM medication_schedules "
                "ORDER BY valid_from, scheduled_time, schedule_id"
            ).fetchall()
        )
        intake_events = tuple(
            _intake_record(row)
            for row in connection.execute(
                "SELECT * FROM medication_intake_events ORDER BY scheduled_date, dose_id"
            ).fetchall()
        )
        return _revision(schedules, intake_events)

    def _write_connection(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise MedicationStoreError("Medikamenten-State darf kein symbolischer Link sein.")
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _read_connection(self) -> sqlite3.Connection:
        if self.path.is_symlink() or not self.path.is_file():
            raise MedicationStoreError(
                f"Medikamenten-State fehlt oder ist keine reguläre Datei: {self.path}"
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
        CREATE TABLE IF NOT EXISTS medication_schedules (
            schedule_id TEXT PRIMARY KEY,
            schedule_key TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            medication_name TEXT NOT NULL,
            dose_quantity_milli INTEGER NOT NULL,
            dose_unit TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            timezone TEXT NOT NULL,
            weekdays_json TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            inventory_item_id TEXT NOT NULL,
            source_document_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_path TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_medication_schedule_key
            ON medication_schedules(schedule_key, valid_from, schedule_id);
        CREATE TABLE IF NOT EXISTS medication_intake_events (
            event_id TEXT PRIMARY KEY,
            dose_id TEXT NOT NULL UNIQUE,
            schedule_id TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            confirmed_at TEXT NOT NULL,
            confirmation_id TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS medication_audit_events (
            audit_id TEXT PRIMARY KEY,
            approval_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            kind TEXT NOT NULL,
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
        raise MedicationStoreError("Medikamenten-State verwendet ein unbekanntes Schema.")


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise MedicationStoreError("Medikamenten-State besitzt kein gültiges Schema.") from exc
    if row is None or row[0] != _SCHEMA_VERSION:
        raise MedicationStoreError("Medikamenten-State verwendet ein unbekanntes Schema.")


def _schedule_record(row: sqlite3.Row) -> MedicationScheduleRecord:
    evidence = tuple(
        MedicationEvidence(
            field=str(item["field"]),
            line_number=int(item["line_number"]),
            label=str(item["label"]),
        )
        for item in json.loads(str(row["evidence_json"]))
    )
    return MedicationScheduleRecord(
        schedule_id=str(row["schedule_id"]),
        schedule_key=str(row["schedule_key"]),
        profile_id=str(row["profile_id"]),
        medication_name=str(row["medication_name"]),
        dose_quantity_milli=int(row["dose_quantity_milli"]),
        dose_unit=str(row["dose_unit"]),
        scheduled_time=str(row["scheduled_time"]),
        timezone=str(row["timezone"]),
        weekdays=tuple(int(item) for item in json.loads(str(row["weekdays_json"]))),
        valid_from=str(row["valid_from"]),
        valid_to=str(row["valid_to"]) if row["valid_to"] is not None else None,
        inventory_item_id=str(row["inventory_item_id"]),
        source_document_id=str(row["source_document_id"]),
        source_sha256=str(row["source_sha256"]),
        source_path=str(row["source_path"]),
        evidence=evidence,
        recorded_at=str(row["recorded_at"]),
    )


def _intake_record(row: sqlite3.Row) -> MedicationIntakeEventRecord:
    return MedicationIntakeEventRecord(
        event_id=str(row["event_id"]),
        dose_id=str(row["dose_id"]),
        schedule_id=str(row["schedule_id"]),
        profile_id=str(row["profile_id"]),
        scheduled_date=str(row["scheduled_date"]),
        confirmed_at=str(row["confirmed_at"]),
        confirmation_id=str(row["confirmation_id"]),
    )


def _evidence_json(evidence: tuple[MedicationEvidence, ...]) -> str:
    return json.dumps(
        [item.to_dict() for item in evidence],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _insert_audit(
    connection: sqlite3.Connection,
    *,
    approval_id: str,
    plan_id: str,
    action_id: str,
    subject_id: str,
    kind: str,
    recorded_at: str,
) -> None:
    material = f"{approval_id}\0{action_id}\0{kind}"
    connection.execute(
        "INSERT INTO medication_audit_events "
        "(audit_id, approval_id, plan_id, action_id, subject_id, kind, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"medication_audit_{sha256(material.encode('utf-8')).hexdigest()}",
            approval_id,
            plan_id,
            action_id,
            subject_id,
            kind,
            recorded_at,
        ),
    )


def _revision(
    schedules: tuple[MedicationScheduleRecord, ...],
    intake_events: tuple[MedicationIntakeEventRecord, ...],
) -> str:
    payload = {
        "schedules": [item.to_dict() for item in schedules],
        "intake_events": [item.to_dict() for item in intake_events],
    }
    material = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"medication_revision_{sha256(material).hexdigest()}"


def _safe_state_root(state_dir: Path) -> Path:
    absolute = Path(os.path.abspath(state_dir))
    if absolute.is_symlink() or absolute.resolve(strict=False) != absolute:
        raise MedicationStoreError(
            f"State-Verzeichnis enthält einen symbolischen Link oder Alias: {absolute}"
        )
    return absolute


EMPTY_MEDICATION_REVISION = _revision((), ())
