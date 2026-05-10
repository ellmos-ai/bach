# SPDX-License-Identifier: MIT
"""
Status Handler - Schnelle System-Uebersicht
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


class StatusHandler(BaseHandler):
    """Handler fuer --status"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "status"
    
    @property
    def target_file(self) -> Path:
        return self.base_path
    
    def get_operations(self) -> dict:
        return {"show": "Systemstatus anzeigen (Standard)"}
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        return self._show_status()

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _count(self, cursor, table: str, where: str = "", params: tuple = ()) -> int:
        query = f"SELECT COUNT(*) FROM {table}"
        if where:
            query += f" WHERE {where}"
        return cursor.execute(query, params).fetchone()[0]
    
    def _show_status(self) -> tuple:
        """Sammelt und zeigt den aktuellen DB-basierten Systemstatus."""
        now = datetime.now()
        results = []

        results.append(f"BACH Status @ {now.strftime('%Y-%m-%d %H:%M')}")
        results.append("=" * 45)
        if not self.db_path.exists():
            results.append("Session:  Keine aktive Session")
            results.append("Partner:  0 online")
            results.append("Memory:   0 Working | 0 Facts | 0 Lessons")
            results.append("Chat:     0 ungelesen")
            results.append("Tasks:    0 offen (0 P1/P2, 0 blocked)")
            results.append("Tools:    0 registriert")
            results.append("Health:   FEHLER (bach.db fehlt)")
            return False, "\n".join(results)

        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()

                active_session = cursor.execute("""
                    SELECT session_id, partner_id
                    FROM memory_sessions
                    WHERE ended_at IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                """).fetchone()

                online_rows = cursor.execute("""
                    SELECT partner_name
                    FROM partner_presence
                    WHERE status = 'online'
                    ORDER BY clocked_in DESC
                """).fetchall()

                working_count = self._count(cursor, "memory_working")
                facts_count = self._count(cursor, "memory_facts")
                lessons_count = self._count(cursor, "memory_lessons")
                unread_count = self._count(cursor, "messages", "status = ?", ("unread",))
                open_tasks = self._count(cursor, "tasks", "status = ?", ("pending",))
                blocked_tasks = self._count(cursor, "tasks", "status = ?", ("blocked",))
                high_prio = self._count(
                    cursor,
                    "tasks",
                    "status = ? AND priority IN ('P1', 'P2')",
                    ("pending",),
                )
                tool_count = self._count(
                    cursor,
                    "tools",
                    "COALESCE(is_available, 1) = 1",
                )

                # Essential table checks should raise immediately if the runtime is broken.
                for table in ("memory_sessions", "partner_presence", "messages", "tasks", "tools"):
                    self._count(cursor, table)

        except Exception as exc:
            results.append("Session:  Unbekannt")
            results.append("Partner:  Unbekannt")
            results.append("Memory:   Unbekannt")
            results.append("Chat:     Unbekannt")
            results.append("Tasks:    Unbekannt")
            results.append("Tools:    Unbekannt")
            results.append(f"Health:   FEHLER ({exc})")
            return False, "\n".join(results)

        if active_session:
            results.append(
                f"Session:  Aktiv ({active_session['partner_id']} / {active_session['session_id']})"
            )
        else:
            results.append("Session:  Keine aktive Session")

        if online_rows:
            partner_names = [row["partner_name"] for row in online_rows]
            preview = ", ".join(partner_names[:3])
            extra = f" +{len(partner_names) - 3}" if len(partner_names) > 3 else ""
            results.append(f"Partner:  {len(partner_names)} online ({preview}{extra})")
        else:
            results.append("Partner:  0 online")

        results.append(
            f"Memory:   {working_count} Working | {facts_count} Facts | {lessons_count} Lessons"
        )
        results.append(f"Chat:     {unread_count} ungelesen")
        results.append(f"Tasks:    {open_tasks} offen ({high_prio} P1/P2, {blocked_tasks} blocked)")
        results.append(f"Tools:    {tool_count} registriert")
        results.append("Health:   OK")

        return True, "\n".join(results)
