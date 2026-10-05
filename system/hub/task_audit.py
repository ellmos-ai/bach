# SPDX-License-Identifier: MIT
"""Gemeinsame Task-Update-Audit-Logik fuer GUI-Server (Port 8000), Headless-API
(Port 8001), CLI `bach task` und den Chat-Tool `task_manage`.

T-20260906-985973908 (server.py), T-20260906-240256515 (headless.py),
T-20260906-833218904 + T-20260906-382894453 (task.py, chat_runtime.py): alle
vier mutieren dieselbe `tasks`-Tabelle und hatten dieselbe Luecke --
`task_history` blieb leer, `started_at` wurde beim Uebergang auf 'in_progress'
nie gesetzt. Damit die Logik nicht mehrfach gepflegt wird (und beim naechsten
Fix nicht wieder nur eine Kopie getroffen wird), liegt sie hier zentral; alle
vier Aufrufer rufen `apply_task_field_changes` auf.

Die Aufrufer haben leicht unterschiedliche Statuswortschaetze (GUI:
'completed', CLI/Headless/Chat: 'done') -- deshalb sind beide als "Abschluss"-
Status anerkannt, statt einen dritten, gemeinsamen Wortschatz zu erzwingen,
der eine der APIs brechen wuerde.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

try:
    from hub._services.task_schema import ensure_task_claim_columns
except ImportError:
    from ._services.task_schema import ensure_task_claim_columns

# Status, bei denen completed_at gesetzt wird. GUI-Server nutzt 'completed',
# CLI/Headless/Chat nutzen 'done' -- beide bleiben gueltig, keiner wird umbenannt.
COMPLETED_STATUSES = frozenset({"completed", "done"})

# Status, bei dem started_at EINMALIG gesetzt wird (nicht erneut ueberschrieben,
# falls der Task spaeter wieder auf in_progress zurueckfaellt).
IN_PROGRESS_STATUSES = frozenset({"in_progress"})

# Reviewer-Fund PR #22 (merge-reviewer-bach22): field_values-Keys landen per
# f-string direkt im UPDATE-Statement (`f"{column} = ?"`). Bei den bisherigen
# Aufrufern unkritisch, weil die Keys aus deklarierten Pydantic-Feldern bzw.
# fest im Code stehenden Strings stammen -- aber je mehr Aufrufer dazukommen,
# desto eher wird das versehentlich zur Injektionsflaeche, falls irgendwo ein
# Schluessel aus freierem Input gebildet wird. Deshalb Allowlist statt Vertrauen.
ALLOWED_COLUMNS = frozenset({
    "title", "description", "priority", "status", "category",
    "assigned_to", "created_by", "depends_on", "required_model", "assigned_slot",
    "due_date",
})

# Spalten, die NICHT ueber field_values gesetzt werden (sie sind Ergebnis der
# Status-Uebergangslogik oben), aber ueber clear_fields explizit auf NULL
# zurueckgesetzt werden duerfen -- fuer T-20260906-382894453 (_reopen: 'done'
# -> 'pending' soll completed_at wieder loeschen).
CLEARABLE_COLUMNS = frozenset({"started_at", "completed_at", "claimed_by", "claimed_at"})

# Status, auf die ein terminal-geparkter Task NICHT wieder gesetzt werden darf
# (T-20260916-1330 / #1235 Resurrektion-Bypass). 'open'/'pending'/'in_progress'
# sind die claimbaren Stati, auf die ein API-Reopen den Task wieder zuruecksetzt.
CLAIMABLE_OPENING_STATUSES = frozenset({"open", "pending", "in_progress"})


class GateReopenBlocked(Exception):
    """Fail-Closed-Guard (T-20260916-1330 / #1235 Resurrektion-Bypass).

    `apply_task_field_changes` ist der generische Choke-Point fuer ALLE
    Task-Updates (GUI/Headless/CLI/Chat). Ohne Guard konnte ein beliebiger
    API-Aufruf (PUT /api/tasks/{id} mit status=open|pending|in_progress) einen
    gate-geparkten Task wieder claimbar setzen -- dann greift der Terminal-
    Waechter in chat_tray (_is_terminal_parked, 5. Pfad claimed_by+in_progress)
    nicht mehr, weil claimed_by beim Reopen gecleart wird (Resurrektion).

    Ein Reopen auf einen claimbaren Status wird auf einem terminal-geparkten
    Task blockiert, SOFERN nicht explizit allow_reopen=True uebergeben wird.
    """


def _is_terminal_parked(existing_row: Mapping[str, Any], now: Optional[str] = None) -> bool:
    """Fail-Closed Terminal-Park-Pruefung -- spiegelbildlich zu chat_tray's
    _is_terminal_parked (T-20260912-1240loop / #1235 4x-Claim / #1293 Option A),
    hier aber als Guard im API-Choke-Point. Ein Task gilt als terminal geparkt
    (nicht via API wieder aufziehbar), wenn EINER dieser Gate-Marker gesetzt ist:

      - status == 'blocked'
      - due_date liegt in der Zukunft (Gate-Haltefrist, z.B. G1/G2/G5 -> 2026-10-12)
      - claimed_by ist gesetzt UND status in ('in_progress', 'blocked')

    Absichtlich NICHT aufgenommen: completed_at -- ein 'done'/'completed'-Task
    darf per Operator legitim wieder geoeffnet werden (kein Gate-Park). Das
    haelt die Blast-Radius klein und vermeidet das Blockieren legitimer
    Unfinish-Reopens.
    """
    if not isinstance(existing_row, Mapping):
        return False
    if existing_row.get("status") == "blocked":
        return True
    if existing_row.get("claimed_by") and existing_row.get("status") in ("in_progress", "blocked"):
        return True
    due = existing_row.get("due_date")
    if due:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(str(due).replace("Z", ""))
            if d.tzinfo is not None:
                d = d.replace(tzinfo=None)
            ref = datetime.now()
            if now:
                try:
                    raw = str(now).strip()
                    if raw.endswith("Z") or raw.endswith("z"):
                        raw = raw[:-1] + "+00:00"
                    if " " in raw and "T" not in raw:
                        raw = raw.replace(" ", "T")
                    ref = datetime.fromisoformat(raw)
                    if ref.tzinfo is not None:
                        ref = ref.replace(tzinfo=None)
                except Exception:
                    ref = datetime.now()
            return d > ref
        except Exception:
            return False
    return False


def _iso_now(dt: Optional[datetime | str] = None) -> str:
    """Erzeugt oder normalisiert einen ISO-Zeitstempel MIT Mikrosekunden (%Y-%m-%dT%H:%M:%S.%f).

    Erzwingt einheitliche String-Laenge (26 Zeichen) fuer konsistente lexikografische
    Zeitvergleiche in SQLite (verhindert '...:00' vs '...:00.123456'-Fehlvergleiche).
    """
    if dt is None:
        target = datetime.now()
    elif isinstance(dt, datetime):
        target = dt
    else:
        raw = str(dt).strip()
        if raw.endswith("Z") or raw.endswith("z"):
            raw = raw[:-1] + "+00:00"
        if " " in raw and "T" not in raw:
            raw = raw.replace(" ", "T")
        target = datetime.fromisoformat(raw)

    if target.tzinfo is not None:
        target = target.astimezone().replace(tzinfo=None)

    return target.strftime("%Y-%m-%dT%H:%M:%S.%f")


def apply_task_field_changes(
    conn: sqlite3.Connection,
    task_id: int,
    existing_row: Mapping[str, Any],
    field_values: Mapping[str, Any],
    *,
    changed_by: str = "api",
    now: Optional[str] = None,
    clear_fields: Iterable[str] = (),
    allow_reopen: bool = False,
) -> bool:
    """Schreibt das UPDATE auf `tasks` plus die zugehoerigen `task_history`-
    Zeilen. Committet NICHT selbst -- der Aufrufer bleibt fuer Transaktions-
    grenzen (und ggf. weitere Statements in derselben Transaktion) zustaendig.

    field_values: {DB-Spaltenname: neuer_wert} fuer alle vom Aufrufer
    tatsaechlich gesetzten Felder. Schema-Aliase (z.B. GUI's `project` ->
    `category`) werden VOM AUFRUFER aufgeloest, bevor dieses dict entsteht.
    Jeder Schluessel MUSS in ALLOWED_COLUMNS stehen (ValueError sonst) --
    das ist absichtlich eine Allowlist, keine Blacklist.

    clear_fields: Spaltennamen aus CLEARABLE_COLUMNS, die zusaetzlich auf NULL
    gesetzt werden (z.B. `completed_at` beim Wiederoeffnen eines erledigten
    Tasks). Wird als eigene field_change-History-Zeile protokolliert, wenn der
    alte Wert nicht schon NULL war.

    existing_row: der VOR dem Update gelesene `tasks`-Datensatz (fuer
    old_value-Vergleich und die started_at-Einmaligkeit).

    Gibt True zurueck, wenn tatsaechlich etwas geschrieben wurde (leere
    field_values UND leere clear_fields sind ein No-Op und geben False
    zurueck, ohne die DB anzufassen).
    """
    now = _iso_now(now)

    # T-20260916-1330 (TRANSFER-09 / #1235 Resurrektion-Bypass): Terminal-Park-
    # Guard im generischen Choke-Point. Ohne ihn konnte jeder API-Aufruf einen
    # gate-geparkten Task per Status-Change wieder claimbar setzen, worauf der
    # Terminal-Waechter in chat_tray nicht mehr greift (claimed_by gecleart).
    new_status = field_values.get("status")
    if (
        not allow_reopen
        and new_status in CLAIMABLE_OPENING_STATUSES
        and new_status != existing_row.get("status")
        and _is_terminal_parked(existing_row, now)
    ):
        raise GateReopenBlocked(
            f"Task #{task_id} ist terminal geparkt "
            f"(status={existing_row.get('status')!r}, "
            f"due_date={existing_row.get('due_date')!r}, "
            f"claimed_by={existing_row.get('claimed_by')!r}); "
            f"Reopen auf '{new_status}' ist blockiert. Fuer einen bewussten "
            f"Operator-Reopen allow_reopen=True uebergeben."
        )

    updates = []
    values = []
    history_entries = []  # (field_changed, old_value, new_value, action)

    for column, new_value in field_values.items():
        if column not in ALLOWED_COLUMNS:
            raise ValueError(
                f"apply_task_field_changes: Spalte '{column}' ist nicht in "
                f"ALLOWED_COLUMNS zugelassen"
            )
        old_value = existing_row.get(column)
        updates.append(f"{column} = ?")
        values.append(new_value)
        if old_value != new_value:
            action = "status_change" if column == "status" else "field_change"
            history_entries.append((column, old_value, new_value, action))

    for column in clear_fields:
        if column not in CLEARABLE_COLUMNS:
            raise ValueError(
                f"apply_task_field_changes: Spalte '{column}' ist nicht in "
                f"CLEARABLE_COLUMNS zugelassen"
            )
        old_value = existing_row.get(column)
        updates.append(f"{column} = NULL")
        if old_value is not None:
            history_entries.append((column, old_value, None, "field_change"))

    if not updates:
        return False

    status_value = field_values.get("status")
    if status_value in COMPLETED_STATUSES:
        # Task #1361: Eine Aufgabe, die Dateien geändert hat, lässt sich nicht auf
        # completed/done setzen, solange kein PR eingetragen ist.
        try:
            from hub.worker_git import task_has_file_changes
            has_changes = task_has_file_changes(task_id, conn)
        except Exception:
            has_changes = False

        if has_changes:
            desc = str(existing_row.get("description") or "") + " " + str(field_values.get("description") or "")
            has_pr = bool(re.search(r"https?://github\.com/[^/]+/[^/]+/pull/\d+", desc) or "pull/" in desc.lower())
            if not has_pr:
                raise ValueError(
                    f"Task #{task_id} hat Codeänderungen, kann aber erst mit eingetragenem PR auf completed gesetzt werden."
                )

        # Keep the original completion instant on repeated completion requests.
        # Legacy terminal rows without a timestamp are repaired on the next write.
        if not existing_row.get("completed_at"):
            updates.append("completed_at = ?")
            values.append(now)
    elif status_value in IN_PROGRESS_STATUSES and not existing_row.get("started_at"):
        # Nur beim ERSTEN Uebergang setzen -- ein wiederholtes in_progress
        # (z.B. nach einem Rueckfall auf 'open'/'pending') darf den Erststart
        # nicht ueberschreiben.
        updates.append("started_at = ?")
        values.append(now)

    updates.append("updated_at = ?")
    values.append(now)
    values.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)

    for field_changed, old_value, new_value, action in history_entries:
        conn.execute(
            """INSERT INTO task_history
               (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, action, field_changed, old_value, new_value, changed_by, now),
        )

    return True


def claim_task_atomic(
    conn: sqlite3.Connection,
    task_id: int,
    claimed_by: str,
    *,
    now: Optional[str] = None,
    lease_seconds: int = 1800,
) -> bool:
    """Beansprucht einen Task exklusiv. True nur, wenn DIESER Aufruf gewonnen hat.

    Bedingtes UPDATE mit rowcount-Pruefung -- das ist der eigentliche Fix:
    kein Read-Then-Write, sondern ein einziges atomares Statement, das nur
    dann etwas aendert, wenn der Task noch offen ODER sein Lease abgelaufen
    ist. `conn` muss eine SCHREIBENDE Verbindung sein (kein `mode=ro`).
    """
    ensure_task_claim_columns(conn)
    now = _iso_now(now)
    lease_cutoff = (datetime.fromisoformat(now) - timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")

    # Vorher SELECT * FROM tasks WHERE id = ? NUR um existing_row fuer
    # die History-Zeile UND fuer die started_at-Einmaligkeit zu haben.
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    existing_row: dict[str, Any] = {}
    if row is not None:
        if isinstance(row, sqlite3.Row) or isinstance(row, dict):
            existing_row = dict(row)
        else:
            cols = [desc[0] for desc in cur.description]
            existing_row = dict(zip(cols, row))

    cursor = conn.execute(
        """UPDATE tasks
           SET status = 'in_progress', claimed_by = ?, claimed_at = ?, updated_at = ?
           WHERE id = ?
             AND status NOT IN ('done', 'completed', 'cancelled', 'blocked')
             AND (status != 'in_progress' OR claimed_by IS NULL OR claimed_at IS NULL OR claimed_at < ?)""",
        (claimed_by, now, now, task_id, lease_cutoff),
    )
    if cursor.rowcount != 1:
        return False

    # started_at einmalig setzen (falls noch NULL)
    if not existing_row.get("started_at"):
        conn.execute(
            "UPDATE tasks SET started_at = ? WHERE id = ? AND started_at IS NULL",
            (now, task_id),
        )

    old_status = existing_row.get("status")
    conn.execute(
        """INSERT INTO task_history
           (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, "status_change", "status", old_status, "in_progress", claimed_by, now),
    )

    return True


def release_claim(conn: sqlite3.Connection, task_id: int, claimed_by: str) -> bool:
    """Gibt einen Claim vorzeitig frei (Abbruch/Fehler) -- Task faellt auf
    'open' zurueck und ist sofort wieder claimbar. True nur bei echter
    Aenderung (WHERE status='in_progress' AND claimed_by=? verhindert, einen laengst
    abgeschlossenen oder an einen neuen Owner uebergegangenen Task versehentlich freizugeben)."""
    ensure_task_claim_columns(conn)
    now = _iso_now()

    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    existing_row: dict[str, Any] = {}
    if row is not None:
        if isinstance(row, sqlite3.Row) or isinstance(row, dict):
            existing_row = dict(row)
        else:
            cols = [desc[0] for desc in cur.description]
            existing_row = dict(zip(cols, row))

    cursor = conn.execute(
        """UPDATE tasks
           SET status = 'open', claimed_by = NULL, claimed_at = NULL, updated_at = ?
           WHERE id = ? AND status = 'in_progress' AND claimed_by = ?""",
        (now, task_id, claimed_by),
    )
    if cursor.rowcount != 1:
        return False

    old_claimed_by = existing_row.get("claimed_by") or claimed_by
    conn.execute(
        """INSERT INTO task_history
           (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, "status_change", "status", "in_progress", "open", claimed_by, now),
    )

    return True



def reap_stale_in_progress_tasks(
    conn: sqlite3.Connection,
    *,
    lease_seconds: int = 1800,
    now: Optional[str] = None,
    reaped_by: str = "reaper",
) -> list[int]:
    """Finds tasks stuck in 'in_progress' whose claim/start has expired, and resets them to 'pending'.

    Preserves tasks with a future due_date (gate haltefristen).
    Does NOT reap tasks started or claimed within the last lease_seconds.
    Defensively handles stripped schemas (missing optional columns).
    Returns the list of reaped task IDs.
    """
    from datetime import timezone
    ensure_task_claim_columns(conn)
    now_iso = _iso_now(now)
    now_ref = datetime.fromisoformat(now_iso)
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    now_utc = (now_ref.astimezone(timezone.utc) if now_ref.tzinfo is not None
               else now_ref.replace(tzinfo=local_tz).astimezone(timezone.utc))

    cur = conn.cursor()
    cols = {col[1] for col in cur.execute("PRAGMA table_info(tasks)").fetchall()}
    has_due = "due_date" in cols
    has_started = "started_at" in cols
    has_claimed_by = "claimed_by" in cols
    has_claimed_at = "claimed_at" in cols
    has_updated = "updated_at" in cols
    has_history = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_history'").fetchone() is not None

    select_sql = f"""
        SELECT id,
               {("claimed_by" if has_claimed_by else "NULL as claimed_by")},
               {("claimed_at" if has_claimed_at else "NULL as claimed_at")},
               {("started_at" if has_started else "NULL as started_at")},
               {("due_date" if has_due else "NULL as due_date")},
               {("updated_at" if has_updated else "NULL as updated_at")}
        FROM tasks
        WHERE status = 'in_progress'
    """
    rows = cur.execute(select_sql).fetchall()
    reaped_ids = []

    def _parse_iso_utc(val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            raw = str(val).strip()
            if raw.endswith("Z") or raw.endswith("z"):
                raw = raw[:-1] + "+00:00"
            if " " in raw and "T" not in raw:
                raw = raw.replace(" ", "T")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc)
            dt_local = dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
            dt_utc = dt.replace(tzinfo=timezone.utc)
            if abs((now_utc - dt_utc).total_seconds()) < abs((now_utc - dt_local).total_seconds()):
                return dt_utc
            return dt_local
        except Exception:
            return None

    cutoff_utc = now_utc - timedelta(seconds=lease_seconds)

    for row in rows:
        tid = row[0]
        cby = row[1]
        cat = row[2]
        sat = row[3]
        due = row[4]
        updated_at = row[5]

        # 1. Skip future due_date (gate-haltefrist)
        due_utc = _parse_iso_utc(due)
        if due_utc and due_utc > now_utc:
            continue

        # 2. Check if active within lease window
        cat_utc = _parse_iso_utc(cat)
        sat_utc = _parse_iso_utc(sat)
        # Manually started tasks may have neither timestamp. Their last update
        # still starts a lease; an unknown timestamp must never imply expiry.
        fallback_utc = _parse_iso_utc(updated_at) if not cat_utc and not sat_utc else None
        if not cat_utc and not sat_utc and (fallback_utc is None or fallback_utc > cutoff_utc):
            continue

        if cat_utc and cat_utc > cutoff_utc:
            continue
        if sat_utc and sat_utc > cutoff_utc:
            continue

        update_clauses = ["status = 'pending'"]
        update_vals = []
        if has_claimed_by:
            update_clauses.append("claimed_by = NULL")
        if has_claimed_at:
            update_clauses.append("claimed_at = NULL")
        if has_updated:
            update_clauses.append("updated_at = ?")
            update_vals.append(now_iso)
        update_vals.append(tid)

        cursor = conn.execute(
            f"""UPDATE tasks
               SET {', '.join(update_clauses)}
               WHERE id = ? AND status = 'in_progress'""",
            update_vals,
        )
        if cursor.rowcount > 0:
            reaped_ids.append(tid)
            if has_history:
                try:
                    conn.execute(
                        """INSERT INTO task_history
                           (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tid,
                            "status_change",
                            "status",
                            "in_progress",
                            "pending",
                            f"{reaped_by}:stale_claim_expired",
                            now_iso,
                        ),
                    )
                except Exception:
                    pass

    return reaped_ids
