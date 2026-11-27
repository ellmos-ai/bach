# BACH Adapter: Automation Lifecycle Bridge & Deprecated Local Fallback (#2329)
# SPDX-License-Identifier: MIT
"""Gemeinsamer Routinen-, Ready- und Kalender-Lifecycle für Jobs, Miniagenten und Automations-Agenten.

Autoritative Implementierung liegt in Ocean (`open-ocean/tools/agent_library.py`).
Die lokale Klasse bleibt gemäß OCEAN-TRANSFER-PLAN als mit `@deprecated_legacy_bach`
markierter Offline-Fallback erhalten.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hub._services.ocean_stack_bridge import deprecated_legacy_bach

FAMILIES = frozenset({"job", "automation_agent", "mini_agent"})
TRIGGERS = frozenset({"manual", "event", "routine", "calendar_once"})
CALENDAR_SYNC_DIRECTIONS = frozenset({"bidirectional", "to_calendar", "from_calendar"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_timezone(tz_name: Any) -> str:
    text = str(tz_name or "Europe/Berlin").strip() or "Europe/Berlin"
    try:
        ZoneInfo(text)
    except Exception as exc:
        raise ValueError(f"Ungültige Zeitzone: {text}") from exc
    return text


def _parse_iso_datetime(value: Any, tz_name: str) -> tuple[datetime, str, str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Zeitstempel fehlt")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    parsed = datetime.fromisoformat(normalized)
    tz = ZoneInfo(tz_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    local_dt = parsed.astimezone(tz)
    utc_dt = local_dt.astimezone(timezone.utc)
    return local_dt, local_dt.isoformat(), utc_dt.isoformat(), local_dt.strftime("%z")


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


@deprecated_legacy_bach("agent-library")
@dataclass
class AutomationLifecycleRegistry:
    """Verwaltet Jobs ohne Modell, Miniagenten und Automations-Agenten mit Persistenz, Kalender & Fence-Schutz (#2329)."""

    db_path: str | Path | None = None
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_triggers: dict[str, str] = field(default_factory=dict)
    calendar_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.db_path is not None:
            self.db_path = Path(self.db_path)
            self._init_schema()
            self._reload_from_db()

    def _connect(self) -> sqlite3.Connection:
        assert self.db_path is not None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS automation_lifecycle_entries (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    family TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
                    state TEXT NOT NULL,
                    fence INTEGER NOT NULL DEFAULT 1,
                    scheduled INTEGER NOT NULL DEFAULT 1,
                    from_module INTEGER NOT NULL DEFAULT 0,
                    schedule_spec TEXT,
                    last_start_trigger TEXT,
                    started_at_local TEXT,
                    started_at_utc TEXT,
                    tz_offset TEXT,
                    input_schema_json TEXT,
                    output_schema_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_lifecycle_active_triggers (
                    entry_id TEXT PRIMARY KEY REFERENCES automation_lifecycle_entries(id) ON DELETE CASCADE,
                    dedup_key TEXT NOT NULL,
                    start_trigger TEXT NOT NULL,
                    run_id TEXT,
                    activated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_lifecycle_calendar (
                    binding_id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL REFERENCES automation_lifecycle_entries(id) ON DELETE CASCADE,
                    calendar_event_id TEXT NOT NULL,
                    sync_direction TEXT NOT NULL DEFAULT 'bidirectional',
                    scheduled_at_utc TEXT NOT NULL,
                    scheduled_at_local TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    tz_offset TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    external_etag TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(entry_id, calendar_event_id)
                );
                CREATE TABLE IF NOT EXISTS automation_lifecycle_runs (
                    run_id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL REFERENCES automation_lifecycle_entries(id) ON DELETE CASCADE,
                    family TEXT NOT NULL,
                    configured_trigger TEXT NOT NULL,
                    start_trigger TEXT NOT NULL,
                    dedup_key TEXT NOT NULL,
                    fence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    started_at_local TEXT NOT NULL,
                    started_at_utc TEXT NOT NULL,
                    tz_offset TEXT NOT NULL,
                    stopped_at_utc TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_alc_runs_trigger ON automation_lifecycle_runs(start_trigger, started_at_utc);
                CREATE INDEX IF NOT EXISTS idx_alc_runs_entry ON automation_lifecycle_runs(entry_id, started_at_utc);
                CREATE INDEX IF NOT EXISTS idx_alc_cal_entry ON automation_lifecycle_calendar(entry_id, status);
                """
            )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "family": row["family"],
            "trigger": row["trigger"],
            "timezone": row["timezone"],
            "state": row["state"],
            "fence": int(row["fence"]),
            "scheduled": bool(row["scheduled"]),
            "from_module": bool(row["from_module"]),
            "schedule_spec": row["schedule_spec"],
            "last_start_trigger": row["last_start_trigger"],
            "started_at_local": row["started_at_local"],
            "started_at_utc": row["started_at_utc"],
            "tz_offset": row["tz_offset"],
            "input_schema": _json_loads(row["input_schema_json"]),
            "output_schema": _json_loads(row["output_schema_json"]),
            "metadata": _json_loads(row["metadata_json"]) or {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "binding_id": row["binding_id"],
            "entry_id": row["entry_id"],
            "calendar_event_id": row["calendar_event_id"],
            "sync_direction": row["sync_direction"],
            "scheduled_at_utc": row["scheduled_at_utc"],
            "scheduled_at_local": row["scheduled_at_local"],
            "timezone": row["timezone"],
            "tz_offset": row["tz_offset"],
            "status": row["status"],
            "external_etag": row["external_etag"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "entry_id": row["entry_id"],
            "family": row["family"],
            "configured_trigger": row["configured_trigger"],
            "start_trigger": row["start_trigger"],
            "dedup_key": row["dedup_key"],
            "fence": int(row["fence"]),
            "status": row["status"],
            "timezone": row["timezone"],
            "started_at_local": row["started_at_local"],
            "started_at_utc": row["started_at_utc"],
            "tz_offset": row["tz_offset"],
            "stopped_at_utc": row["stopped_at_utc"],
        }

    def _reload_from_db(self) -> None:
        if self.db_path is None:
            return
        with self._connect() as conn:
            self.entries = {
                r["id"]: self._row_to_entry(r)
                for r in conn.execute("SELECT * FROM automation_lifecycle_entries ORDER BY id").fetchall()
            }
            self.active_triggers = {
                r["entry_id"]: r["dedup_key"]
                for r in conn.execute("SELECT entry_id, dedup_key FROM automation_lifecycle_active_triggers").fetchall()
            }
            self.calendar_bindings = {
                r["binding_id"]: self._row_to_binding(r)
                for r in conn.execute("SELECT * FROM automation_lifecycle_calendar ORDER BY updated_at, binding_id").fetchall()
            }
            self.runs = [
                self._row_to_run(r)
                for r in conn.execute("SELECT * FROM automation_lifecycle_runs ORDER BY started_at_utc, run_id").fetchall()
            ]

    @staticmethod
    def _validate_family_contract(family: str, payload: dict[str, Any]) -> None:
        if family not in FAMILIES:
            raise ValueError(f"Ungültige Familie: {family}")
        if family == "job" and payload.get("requires_model"):
            raise ValueError("Jobs ohne Modell dürfen kein Sprachmodell anfordern")
        if family == "mini_agent":
            if not payload.get("input_schema") or not payload.get("output_schema"):
                raise ValueError("Miniagenten benötigen festen Ein-/Ausgabevertrag (input_schema/output_schema)")
            if payload.get("allows_open_work") or payload.get("allows_reviews"):
                raise ValueError("Miniagenten erlauben keine offene Agentenarbeit oder Reviews")

    def register_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        eid = str(payload.get("id") or "").strip()
        family = str(payload.get("family") or "").strip()
        trigger = str(payload.get("trigger") or "routine").strip()
        if not eid:
            raise ValueError("id fehlt")
        self._validate_family_contract(family, payload)
        if trigger not in TRIGGERS:
            raise ValueError(f"Ungültige Startart: {trigger}")
        tz_name = _validate_timezone(payload.get("timezone"))
        from_module = bool(payload.get("from_module", False))
        scheduled = bool(payload.get("scheduled", not from_module))
        if "scheduled" in payload:
            scheduled = bool(payload["scheduled"])
        state = "available" if from_module and not scheduled else "ready"
        now_utc = _utc_now_iso()
        record = {
            "id": eid,
            "title": str(payload.get("title") or eid),
            "family": family,
            "trigger": trigger,
            "timezone": tz_name,
            "state": state,
            "fence": int(payload.get("fence") or 1),
            "scheduled": scheduled,
            "from_module": from_module,
            "schedule_spec": payload.get("schedule_spec"),
            "last_start_trigger": None,
            "started_at_local": None,
            "started_at_utc": None,
            "tz_offset": None,
            "input_schema": payload.get("input_schema"),
            "output_schema": payload.get("output_schema"),
            "metadata": dict(payload.get("metadata") or {}),
            "created_at": now_utc,
            "updated_at": now_utc,
        }
        if self.db_path is not None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO automation_lifecycle_entries (
                        id, title, family, trigger, timezone, state, fence,
                        scheduled, from_module, schedule_spec, last_start_trigger,
                        started_at_local, started_at_utc, tz_offset,
                        input_schema_json, output_schema_json, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        family=excluded.family,
                        trigger=excluded.trigger,
                        timezone=excluded.timezone,
                        state=excluded.state,
                        fence=excluded.fence,
                        scheduled=excluded.scheduled,
                        from_module=excluded.from_module,
                        schedule_spec=excluded.schedule_spec,
                        input_schema_json=excluded.input_schema_json,
                        output_schema_json=excluded.output_schema_json,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        record["id"],
                        record["title"],
                        record["family"],
                        record["trigger"],
                        record["timezone"],
                        record["state"],
                        record["fence"],
                        int(record["scheduled"]),
                        int(record["from_module"]),
                        record["schedule_spec"],
                        record["last_start_trigger"],
                        record["started_at_local"],
                        record["started_at_utc"],
                        record["tz_offset"],
                        _json_dumps(record["input_schema"]),
                        _json_dumps(record["output_schema"]),
                        _json_dumps(record["metadata"]),
                        record["created_at"],
                        record["updated_at"],
                    ),
                )
            self._reload_from_db()
            return dict(self.entries[eid])
        self.entries[eid] = record
        return dict(record)

    def get_entry(self, eid: str) -> dict[str, Any]:
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        return dict(self.entries[eid])

    def list_entries(
        self,
        *,
        family: str | None = None,
        state: str | None = None,
        trigger: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.db_path is not None:
            self._reload_from_db()
        items = list(self.entries.values())
        if family is not None:
            items = [item for item in items if item["family"] == family]
        if state is not None:
            items = [item for item in items if item["state"] == state]
        if trigger is not None:
            items = [item for item in items if item["trigger"] == trigger]
        items.sort(key=lambda item: item["id"])
        return [dict(item) for item in items]

    def update_entry(
        self,
        eid: str,
        patch: dict[str, Any],
        *,
        expected_fence: int | None = None,
    ) -> dict[str, Any]:
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        current = dict(self.entries[eid])
        cur_fence = int(current["fence"])
        if expected_fence is not None and cur_fence != expected_fence:
            raise RuntimeError(f"Fence-Konflikt beim Update: erwartet {expected_fence}, aktuell {cur_fence}")

        merged = {**current, **patch, "id": eid}
        self._validate_family_contract(str(merged.get("family") or ""), merged)
        trigger = str(merged.get("trigger") or "").strip()
        if trigger not in TRIGGERS:
            raise ValueError(f"Ungültige Startart: {trigger}")
        tz_name = _validate_timezone(merged.get("timezone"))
        now_utc = _utc_now_iso()
        new_fence = cur_fence + 1
        updated = {
            **current,
            "title": str(merged.get("title") or current["title"]),
            "family": str(merged["family"]),
            "trigger": trigger,
            "timezone": tz_name,
            "scheduled": bool(merged.get("scheduled", current.get("scheduled", True))),
            "schedule_spec": merged.get("schedule_spec", current.get("schedule_spec")),
            "input_schema": merged.get("input_schema", current.get("input_schema")),
            "output_schema": merged.get("output_schema", current.get("output_schema")),
            "metadata": dict(merged.get("metadata") if merged.get("metadata") is not None else current.get("metadata") or {}),
            "fence": new_fence,
            "updated_at": now_utc,
        }
        if current["state"] == "available" and updated["scheduled"]:
            updated["state"] = "ready"

        if self.db_path is not None:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE automation_lifecycle_entries
                    SET title=?, family=?, trigger=?, timezone=?, state=?, fence=?,
                        scheduled=?, schedule_spec=?, input_schema_json=?, output_schema_json=?,
                        metadata_json=?, updated_at=?
                    WHERE id=? AND fence=?
                    """,
                    (
                        updated["title"],
                        updated["family"],
                        updated["trigger"],
                        updated["timezone"],
                        updated["state"],
                        new_fence,
                        int(updated["scheduled"]),
                        updated["schedule_spec"],
                        _json_dumps(updated["input_schema"]),
                        _json_dumps(updated["output_schema"]),
                        _json_dumps(updated["metadata"]),
                        now_utc,
                        eid,
                        cur_fence,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"Fence-Konflikt beim Update: konkurrierende Änderung für {eid}")
            self._reload_from_db()
            return dict(self.entries[eid])
        self.entries[eid] = updated
        return dict(updated)

    def schedule_entry(
        self,
        eid: str,
        *,
        schedule_spec: str | None = None,
        timezone: str | None = None,
        expected_fence: int | None = None,
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {"scheduled": True}
        if schedule_spec is not None:
            patch["schedule_spec"] = schedule_spec
        if timezone is not None:
            patch["timezone"] = timezone
        return self.update_entry(eid, patch, expected_fence=expected_fence)

    def delete_entry(self, eid: str, *, expected_fence: int | None = None) -> dict[str, Any]:
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        current = dict(self.entries[eid])
        cur_fence = int(current["fence"])
        if expected_fence is not None and cur_fence != expected_fence:
            raise RuntimeError(f"Fence-Konflikt beim Löschen: erwartet {expected_fence}, aktuell {cur_fence}")
        if current["state"] == "running":
            raise RuntimeError(f"Laufender Eintrag {eid} muss vor dem Löschen gestoppt werden")

        if self.db_path is not None:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM automation_lifecycle_entries WHERE id=? AND fence=?",
                    (eid, cur_fence),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"Fence-Konflikt beim Löschen: konkurrierende Änderung für {eid}")
            self._reload_from_db()
        else:
            self.entries.pop(eid, None)
            self.active_triggers.pop(eid, None)
            for bid in [k for k, v in self.calendar_bindings.items() if v["entry_id"] == eid]:
                self.calendar_bindings.pop(bid, None)
        return {"deleted": True, "id": eid, "fence": cur_fence}

    def bind_calendar_event(
        self,
        eid: str,
        *,
        calendar_event_id: str,
        scheduled_at: str,
        sync_direction: str = "bidirectional",
        external_etag: str | None = None,
        confirm_schedule: bool = True,
    ) -> dict[str, Any]:
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        cal_id = str(calendar_event_id or "").strip()
        if not cal_id:
            raise ValueError("calendar_event_id fehlt")
        if sync_direction not in CALENDAR_SYNC_DIRECTIONS:
            raise ValueError(f"Ungültige Kalender-Sync-Richtung: {sync_direction}")

        entry = self.entries[eid]
        tz_name = entry["timezone"]
        _, local_iso, utc_iso, tz_offset = _parse_iso_datetime(scheduled_at, tz_name)
        now_utc = _utc_now_iso()

        if confirm_schedule and entry["state"] == "available":
            self.schedule_entry(eid, schedule_spec=utc_iso, expected_fence=int(entry["fence"]))

        existing = next(
            (b for b in self.calendar_bindings.values() if b["entry_id"] == eid and b["calendar_event_id"] == cal_id),
            None,
        )
        binding_id = existing["binding_id"] if existing else f"calbind-{uuid.uuid4().hex[:12]}"
        binding = {
            "binding_id": binding_id,
            "entry_id": eid,
            "calendar_event_id": cal_id,
            "sync_direction": sync_direction,
            "scheduled_at_utc": utc_iso,
            "scheduled_at_local": local_iso,
            "timezone": tz_name,
            "tz_offset": tz_offset,
            "status": "scheduled",
            "external_etag": external_etag,
            "updated_at": now_utc,
        }
        if self.db_path is not None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO automation_lifecycle_calendar (
                        binding_id, entry_id, calendar_event_id, sync_direction,
                        scheduled_at_utc, scheduled_at_local, timezone, tz_offset,
                        status, external_etag, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entry_id, calendar_event_id) DO UPDATE SET
                        sync_direction=excluded.sync_direction,
                        scheduled_at_utc=excluded.scheduled_at_utc,
                        scheduled_at_local=excluded.scheduled_at_local,
                        timezone=excluded.timezone,
                        tz_offset=excluded.tz_offset,
                        status='scheduled',
                        external_etag=excluded.external_etag,
                        updated_at=excluded.updated_at
                    """,
                    (
                        binding["binding_id"],
                        binding["entry_id"],
                        binding["calendar_event_id"],
                        binding["sync_direction"],
                        binding["scheduled_at_utc"],
                        binding["scheduled_at_local"],
                        binding["timezone"],
                        binding["tz_offset"],
                        binding["status"],
                        binding["external_etag"],
                        binding["updated_at"],
                    ),
                )
            self._reload_from_db()
            return dict(self.calendar_bindings[binding_id])
        self.calendar_bindings[binding_id] = binding
        return dict(binding)

    def cancel_calendar_event(
        self,
        eid: str,
        *,
        calendar_event_id: str | None = None,
        binding_id: str | None = None,
        source: str = "local",
    ) -> dict[str, Any]:
        if source not in {"local", "calendar"}:
            raise ValueError(f"Ungültige Storno-Quelle: {source}")
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")

        match = None
        for b in self.calendar_bindings.values():
            if b["entry_id"] != eid:
                continue
            if binding_id and b["binding_id"] == binding_id:
                match = b
                break
            if calendar_event_id and b["calendar_event_id"] == calendar_event_id:
                match = b
                break
        if match is None:
            raise KeyError(f"Keine Kalenderbindung gefunden für {eid}")

        if source == "calendar" and match["sync_direction"] == "to_calendar":
            raise PermissionError("Einseitige Kalenderbindung (to_calendar) blockiert externes Storno")

        now_utc = _utc_now_iso()
        updated = {**match, "status": "cancelled", "updated_at": now_utc}
        if self.db_path is not None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE automation_lifecycle_calendar SET status='cancelled', updated_at=? WHERE binding_id=?",
                    (now_utc, match["binding_id"]),
                )
            self._reload_from_db()
            return {**self.calendar_bindings[match["binding_id"]], "cancelled_by": source}
        self.calendar_bindings[match["binding_id"]] = updated
        return {**updated, "cancelled_by": source}

    def list_calendar_bindings(
        self,
        eid: str | None = None,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.db_path is not None:
            self._reload_from_db()
        items = list(self.calendar_bindings.values())
        if eid is not None:
            items = [item for item in items if item["entry_id"] == eid]
        if status is not None:
            items = [item for item in items if item["status"] == status]
        items.sort(key=lambda item: (item["scheduled_at_utc"], item["binding_id"]))
        return [dict(item) for item in items]

    def trigger_start(
        self,
        eid: str,
        *,
        start_trigger: str,
        dedup_key: str,
        tz_now: datetime | None = None,
    ) -> dict[str, Any]:
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        if start_trigger not in TRIGGERS:
            raise ValueError(f"Ungültiger Startanlass: {start_trigger}")
        if not str(dedup_key or "").strip():
            raise ValueError("dedup_key fehlt")
        if self.active_triggers.get(eid) == dedup_key:
            return {**self.entries[eid], "deduplicated": True}

        rec = self.entries[eid]
        if rec["state"] == "available":
            raise RuntimeError("Mitgelieferte Pflegeaufgaben laufen erst nach bestätigter Planung")

        tz = ZoneInfo(rec["timezone"])
        base_now = tz_now or datetime.now(tz)
        if base_now.tzinfo is None:
            base_now = base_now.replace(tzinfo=tz)
        now_local = base_now.astimezone(tz)
        now_utc = now_local.astimezone(timezone.utc)
        started_local_iso = now_local.isoformat()
        started_utc_iso = now_utc.isoformat()
        tz_offset = now_local.strftime("%z")
        cur_fence = int(rec["fence"])
        new_fence = cur_fence + 1
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now_stamp = _utc_now_iso()

        run_record = {
            "run_id": run_id,
            "entry_id": eid,
            "family": rec["family"],
            "configured_trigger": rec["trigger"],
            "start_trigger": start_trigger,
            "dedup_key": dedup_key,
            "fence": new_fence,
            "status": "running",
            "timezone": rec["timezone"],
            "started_at_local": started_local_iso,
            "started_at_utc": started_utc_iso,
            "tz_offset": tz_offset,
            "stopped_at_utc": None,
        }

        if self.db_path is not None:
            with self._connect() as conn:
                existing_trig = conn.execute(
                    "SELECT dedup_key FROM automation_lifecycle_active_triggers WHERE entry_id=?",
                    (eid,),
                ).fetchone()
                if existing_trig and existing_trig["dedup_key"] == dedup_key:
                    self._reload_from_db()
                    return {**self.entries[eid], "deduplicated": True}
                cur = conn.execute(
                    """
                    UPDATE automation_lifecycle_entries
                    SET fence=?, state='running', last_start_trigger=?,
                        started_at_local=?, started_at_utc=?, tz_offset=?, updated_at=?
                    WHERE id=? AND fence=? AND state != 'available'
                    """,
                    (
                        new_fence,
                        start_trigger,
                        started_local_iso,
                        started_utc_iso,
                        tz_offset,
                        now_stamp,
                        eid,
                        cur_fence,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"Fence-Konflikt beim Start: konkurrierende Änderung für {eid}")
                conn.execute(
                    """
                    INSERT INTO automation_lifecycle_active_triggers (
                        entry_id, dedup_key, start_trigger, run_id, activated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        dedup_key=excluded.dedup_key,
                        start_trigger=excluded.start_trigger,
                        run_id=excluded.run_id,
                        activated_at=excluded.activated_at
                    """,
                    (eid, dedup_key, start_trigger, run_id, now_stamp),
                )
                conn.execute(
                    """
                    INSERT INTO automation_lifecycle_runs (
                        run_id, entry_id, family, configured_trigger, start_trigger,
                        dedup_key, fence, status, timezone, started_at_local,
                        started_at_utc, tz_offset, stopped_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        run_record["run_id"],
                        run_record["entry_id"],
                        run_record["family"],
                        run_record["configured_trigger"],
                        run_record["start_trigger"],
                        run_record["dedup_key"],
                        run_record["fence"],
                        run_record["status"],
                        run_record["timezone"],
                        run_record["started_at_local"],
                        run_record["started_at_utc"],
                        run_record["tz_offset"],
                    ),
                )
            self._reload_from_db()
            return {**self.entries[eid], "deduplicated": False, "run_id": run_id}

        rec["fence"] = new_fence
        rec["state"] = "running"
        rec["last_start_trigger"] = start_trigger
        rec["started_at_local"] = started_local_iso
        rec["started_at_utc"] = started_utc_iso
        rec["tz_offset"] = tz_offset
        rec["updated_at"] = now_stamp
        self.active_triggers[eid] = dedup_key
        self.runs.append(run_record)
        return {**rec, "deduplicated": False, "run_id": run_id}

    def stop_entry(self, eid: str, *, expected_fence: int, status: str = "stopped") -> dict[str, Any]:
        if self.db_path is not None:
            self._reload_from_db()
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        rec = self.entries[eid]
        cur_fence = int(rec["fence"])
        if cur_fence != expected_fence:
            raise RuntimeError(f"Fence-Konflikt beim Stopp: erwartet {expected_fence}, aktuell {cur_fence}")
        new_fence = cur_fence + 1
        now_utc = _utc_now_iso()

        if self.db_path is not None:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE automation_lifecycle_entries
                    SET fence=?, state='ready', updated_at=?
                    WHERE id=? AND fence=?
                    """,
                    (new_fence, now_utc, eid, expected_fence),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"Fence-Konflikt beim Stopp: konkurrierende Änderung für {eid}")
                trig_row = conn.execute(
                    "SELECT run_id FROM automation_lifecycle_active_triggers WHERE entry_id=?",
                    (eid,),
                ).fetchone()
                if trig_row and trig_row["run_id"]:
                    conn.execute(
                        "UPDATE automation_lifecycle_runs SET status=?, stopped_at_utc=? WHERE run_id=?",
                        (status, now_utc, trig_row["run_id"]),
                    )
                conn.execute("DELETE FROM automation_lifecycle_active_triggers WHERE entry_id=?", (eid,))
                if rec.get("trigger") == "calendar_once":
                    conn.execute(
                        "UPDATE automation_lifecycle_calendar SET status='executed', updated_at=? WHERE entry_id=? AND status='scheduled'",
                        (now_utc, eid),
                    )
            self._reload_from_db()
            return dict(self.entries[eid])

        rec["fence"] = new_fence
        rec["state"] = "ready"
        rec["updated_at"] = now_utc
        self.active_triggers.pop(eid, None)
        for run in reversed(self.runs):
            if run["entry_id"] == eid and run["status"] == "running":
                run["status"] = status
                run["stopped_at_utc"] = now_utc
                break
        if rec.get("trigger") == "calendar_once":
            for b in self.calendar_bindings.values():
                if b["entry_id"] == eid and b["status"] == "scheduled":
                    b["status"] = "executed"
                    b["updated_at"] = now_utc
        return dict(rec)

    def list_runs(
        self,
        eid: str | None = None,
        *,
        start_trigger: str | None = None,
        group_by_trigger: bool = False,
    ) -> list[dict[str, Any]] | dict[str, list[dict[str, Any]]]:
        if start_trigger is not None and start_trigger not in TRIGGERS:
            raise ValueError(f"Ungültiger Startanlass: {start_trigger}")
        if self.db_path is not None:
            self._reload_from_db()
        items = list(self.runs)
        if eid is not None:
            items = [r for r in items if r["entry_id"] == eid]
        if start_trigger is not None:
            items = [r for r in items if r["start_trigger"] == start_trigger]
        items = [dict(r) for r in items]
        if not group_by_trigger:
            return items
        grouped: dict[str, list[dict[str, Any]]] = {t: [] for t in sorted(TRIGGERS)}
        for run in items:
            grouped.setdefault(run["start_trigger"], []).append(run)
        return grouped


def get_automation_lifecycle_registry(db_path: str | Path | None = None) -> tuple[Any, str]:
    """Delegiert bevorzugt an Oceans `agent-library` und fällt nur lokal auf das Legacy-Registry zurück."""
    try:
        from hub._services import ocean_stack_bridge

        err_cls = getattr(ocean_stack_bridge, "OceanModuleUnavailable", RuntimeError)
        try:
            reg = ocean_stack_bridge.get_ocean_automation_lifecycle_registry(db_path=db_path)
            return reg, "ocean.agent_library"
        except (err_cls, FileNotFoundError, ImportError, TypeError, AttributeError, RuntimeError):
            return AutomationLifecycleRegistry(db_path=db_path), "bach.legacy_fallback"
    except (ImportError, AttributeError):
        return AutomationLifecycleRegistry(db_path=db_path), "bach.legacy_fallback"
