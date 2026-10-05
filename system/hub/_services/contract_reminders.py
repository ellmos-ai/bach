# SPDX-License-Identifier: MIT
"""hub/_services/contract_reminders.py - Reminder-Service für contract_reminders.

Kapselt alle Zugriffe auf die Tabelle contract_reminders
(Tabellen-Schema in hub/contract_cockpit.py):

- sync_contract_reminders: legt fällige Erinnerungen für einen Vertrag an
  (Kündigungsfrist / Ablaufdatum, INSERT OR IGNORE -> idempotent)
- get_due_reminders: pendende Erinnerungen innerhalb des Lookahead-Fensters
- get_pending_reminders: alle pendenden Erinnerungen
- mark_reminder: Status einer Erinnerung setzen (sent/done/dismissed)
"""

import sqlite3
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from hub._services.contract_dates import _format_date, _parse_date

VALID_REMINDER_STATUS = ("sent", "done", "dismissed")


def sync_contract_reminders(
    conn: sqlite3.Connection,
    contract: Dict[str, Any],
    today: Optional[date] = None,
    lookahead_days: int = 60,
) -> List[Dict[str, Any]]:
    """Legt fällige Erinnerungen für einen Vertrag an.

    Erwartet im contract-Dict mindestens: id, name, anbieter,
    naechste_kuendigung, ablauf_datum. Erinnerungen im Fenster
    [today, today + lookahead_days] werden per INSERT OR IGNORE angelegt
    (kein Duplikat-Schutz nötig aufruferseitig).

    Rückgabe: Liste der berücksichtigten Erinnerungen als Dicts mit den
    Keys contract_id, type, trigger_date, subject.
    """
    today = today or date.today()
    horizon = today + timedelta(days=lookahead_days)
    reminders: List[Dict[str, Any]] = []

    cid = contract.get("id")
    if cid is None:
        return reminders

    label = contract.get("name") or contract.get("anbieter") or "Vertrag"
    nk = _parse_date(contract.get("naechste_kuendigung"))
    ablauf = _parse_date(contract.get("ablauf_datum"))

    if nk and today <= nk <= horizon:
        subject = f"Kündigungsfrist für {label}"
        conn.execute(
            """INSERT OR IGNORE INTO contract_reminders
            (contract_id, reminder_type, trigger_date, subject)
            VALUES (?, ?, ?, ?)""",
            (cid, "kuendigungsfrist", _format_date(nk), subject),
        )
        reminders.append(
            {
                "contract_id": cid,
                "type": "kuendigungsfrist",
                "trigger_date": _format_date(nk),
                "subject": subject,
            }
        )

    if ablauf and today <= ablauf <= horizon:
        subject = f"Ablaufdatum für {label}"
        conn.execute(
            """INSERT OR IGNORE INTO contract_reminders
            (contract_id, reminder_type, trigger_date, subject)
            VALUES (?, ?, ?, ?)""",
            (cid, "ablauf", _format_date(ablauf), subject),
        )
        reminders.append(
            {
                "contract_id": cid,
                "type": "ablauf",
                "trigger_date": _format_date(ablauf),
                "subject": subject,
            }
        )

    return reminders


def get_due_reminders(
    conn: sqlite3.Connection,
    today: Optional[date] = None,
    lookahead_days: int = 60,
) -> List[Dict[str, Any]]:
    """Liefert pendende Erinnerungen, deren trigger_date im Fenster liegt."""
    today = today or date.today()
    horizon = today + timedelta(days=lookahead_days)
    rows = conn.execute(
        """SELECT r.*, c.name, c.anbieter, c.type
           FROM contract_reminders r
           JOIN contracts c ON c.id = r.contract_id
           WHERE r.status = 'pending' AND r.trigger_date <= ?
           ORDER BY r.trigger_date""",
        (_format_date(horizon),),
    ).fetchall()
    return [dict(row) for row in rows]


def get_pending_reminders(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Liefert alle pendenden Erinnerungen (älteste zuerst)."""
    rows = conn.execute(
        """SELECT r.*, c.name, c.anbieter, c.type
           FROM contract_reminders r
           JOIN contracts c ON c.id = r.contract_id
           WHERE r.status='pending'
           ORDER BY r.trigger_date"""
    ).fetchall()
    return [dict(row) for row in rows]


def mark_reminder(conn: sqlite3.Connection, reminder_id: int, status: str) -> bool:
    """Setzt den Status einer Erinnerung ('sent'|'done'|'dismissed').

    Rückgabe: True, wenn eine Zeile aktualisiert wurde.
    """
    if status not in VALID_REMINDER_STATUS:
        raise ValueError(
            f"Ungültiger Reminder-Status: {status!r} "
            f"(erlaubt: {', '.join(VALID_REMINDER_STATUS)})"
        )
    cur = conn.execute(
        "UPDATE contract_reminders SET status=? WHERE id=?",
        (status, reminder_id),
    )
    return cur.rowcount > 0
