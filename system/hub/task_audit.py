# SPDX-License-Identifier: MIT
"""Gemeinsame Task-Update-Audit-Logik fuer GUI-Server (Port 8000) und Headless-
API (Port 8001).

T-20260906-985973908 (server.py) und T-20260906-240256515 (headless.py):
beide PUT-Handler mutieren dieselbe `tasks`-Tabelle und hatten dieselbe
Luecke -- `task_history` blieb leer, `started_at` wurde beim Uebergang auf
'in_progress' nie gesetzt. Damit die Logik nicht zweimal gepflegt wird (und
beim naechsten Fix nicht wieder nur eine Kopie getroffen wird), liegt sie
hier zentral; beide Server rufen `apply_task_field_changes` auf.

Die beiden Server haben leicht unterschiedliche Statuswortschaetze (GUI:
'completed', Headless: 'done') -- deshalb sind beide als "Abschluss"-Status
anerkannt, statt einen dritten, gemeinsamen Wortschatz zu erzwingen, der
beide APIs brechen wuerde.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Mapping, Optional

# Status, bei denen completed_at gesetzt wird. GUI-Server nutzt 'completed',
# Headless-API nutzt 'done' -- beide bleiben gueltig, keiner wird umbenannt.
COMPLETED_STATUSES = frozenset({"completed", "done"})

# Status, bei dem started_at EINMALIG gesetzt wird (nicht erneut ueberschrieben,
# falls der Task spaeter wieder auf in_progress zurueckfaellt).
IN_PROGRESS_STATUSES = frozenset({"in_progress"})


def apply_task_field_changes(
    conn: sqlite3.Connection,
    task_id: int,
    existing_row: Mapping[str, Any],
    field_values: Mapping[str, Any],
    *,
    changed_by: str = "api",
    now: Optional[str] = None,
) -> bool:
    """Schreibt das UPDATE auf `tasks` plus die zugehoerigen `task_history`-
    Zeilen. Committet NICHT selbst -- der Aufrufer bleibt fuer Transaktions-
    grenzen (und ggf. weitere Statements in derselben Transaktion) zustaendig.

    field_values: {DB-Spaltenname: neuer_wert} fuer alle vom Aufrufer
    tatsaechlich gesetzten Felder. Schema-Aliase (z.B. GUI's `project` ->
    `category`) werden VOM AUFRUFER aufgeloest, bevor dieses dict entsteht --
    diese Funktion kennt nur echte `tasks`-Spaltennamen.

    existing_row: der VOR dem Update gelesene `tasks`-Datensatz (fuer
    old_value-Vergleich und die started_at-Einmaligkeit).

    Gibt True zurueck, wenn tatsaechlich etwas geschrieben wurde (leeres
    field_values ist ein No-Op und gibt False zurueck, ohne die DB anzufassen).
    """
    if now is None:
        now = datetime.now().isoformat()

    updates = []
    values = []
    history_entries = []  # (field_changed, old_value, new_value, action)

    for column, new_value in field_values.items():
        old_value = existing_row.get(column)
        updates.append(f"{column} = ?")
        values.append(new_value)
        if old_value != new_value:
            action = "status_change" if column == "status" else "field_change"
            history_entries.append((column, old_value, new_value, action))

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
