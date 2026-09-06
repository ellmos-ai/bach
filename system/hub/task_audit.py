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

import sqlite3
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

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
    "assigned_to", "created_by", "depends_on",
})

# Spalten, die NICHT ueber field_values gesetzt werden (sie sind Ergebnis der
# Status-Uebergangslogik oben), aber ueber clear_fields explizit auf NULL
# zurueckgesetzt werden duerfen -- fuer T-20260906-382894453 (_reopen: 'done'
# -> 'pending' soll completed_at wieder loeschen).
CLEARABLE_COLUMNS = frozenset({"started_at", "completed_at"})


def apply_task_field_changes(
    conn: sqlite3.Connection,
    task_id: int,
    existing_row: Mapping[str, Any],
    field_values: Mapping[str, Any],
    *,
    changed_by: str = "api",
    now: Optional[str] = None,
    clear_fields: Iterable[str] = (),
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
    if now is None:
        now = datetime.now().isoformat()

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
