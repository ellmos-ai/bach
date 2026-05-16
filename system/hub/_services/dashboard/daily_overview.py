#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Daily Overview Service — Konsolidierter Tagesstatus (INT05)

Aggregiert tagesrelevante Daten aus allen BACH-Modulen:
- Haushalt: Routinen, Inventar-Ampel, Einkaufsliste
- Gesundheit: Medikamente, Termine
- Literatur: Ungelesene Quellen
- Kalender: Heutige Termine

Liefert strukturierte Dicts, die von Handlern formatiert werden.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


class DailyOverview:
    """Aggregiert tagesrelevante Daten aus bach.db."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _get_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_overview(self) -> Dict:
        """Liefert konsolidierten Tagesstatus.

        Returns:
            Dict mit Keys: routines, calendar, shopping, inventory,
                          health_meds, health_appointments, literatur, timestamp
        """
        conn = self._get_db()
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            return {
                "date": today_str,
                "weekday": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][now.weekday()],
                "routines": self._routines(conn, today_str),
                "calendar": self._calendar(conn, today_str),
                "shopping": self._shopping(conn),
                "inventory": self._inventory(),
                "health_meds": self._health_meds(conn),
                "health_appointments": self._health_appointments(conn, today_str),
                "literatur": self._literatur(conn),
                "timestamp": now.isoformat(),
            }
        finally:
            conn.close()

    # ================================================================
    # DATENQUELLEN
    # ================================================================

    def _routines(self, conn, today_str: str) -> Dict:
        """Faellige Routinen aus household_routines."""
        try:
            rows = conn.execute("""
                SELECT id, name, category, next_due
                FROM household_routines
                WHERE is_active = 1 AND next_due <= ?
                ORDER BY next_due ASC
            """, (today_str + " 23:59:59",)).fetchall()
            return {
                "count": len(rows),
                "items": [dict(r) for r in rows],
            }
        except Exception:
            return {"count": 0, "items": []}

    def _calendar(self, conn, today_str: str) -> Dict:
        """Heutige Termine aus assistant_calendar."""
        try:
            rows = conn.execute("""
                SELECT id, title, DATE(start_datetime) as event_date,
                       TIME(start_datetime) as event_time, event_type
                FROM assistant_calendar
                WHERE DATE(start_datetime) = ? AND status != 'erledigt'
                ORDER BY start_datetime ASC
            """, (today_str,)).fetchall()
            return {
                "count": len(rows),
                "items": [dict(r) for r in rows],
            }
        except Exception:
            return {"count": 0, "items": []}

    def _shopping(self, conn) -> Dict:
        """Offene Einkaufsartikel."""
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM household_shopping WHERE is_done = 0"
            ).fetchone()[0]
            return {"count": count}
        except Exception:
            return {"count": 0}

    def _inventory(self) -> Dict:
        """Inventar-Ampel-Zusammenfassung."""
        try:
            from hub._services.household.inventory_engine import (
                InventoryEngine, AMPEL_ROT, AMPEL_GELB, AMPEL_GRUEN, AMPEL_GRAU,
            )
            engine = InventoryEngine(self.db_path)
            overview = engine.get_ampel_overview()
            rot = [x for x in overview if x["ampel"] == AMPEL_ROT]
            gelb = [x for x in overview if x["ampel"] == AMPEL_GELB]
            return {
                "total": len(overview),
                "rot": len(rot),
                "gelb": len(gelb),
                "gruen": sum(1 for x in overview if x["ampel"] == AMPEL_GRUEN),
                "grau": sum(1 for x in overview if x["ampel"] == AMPEL_GRAU),
                "critical_items": [x["name"] for x in rot],
                "warning_items": [x["name"] for x in gelb],
            }
        except Exception:
            return {"total": 0, "rot": 0, "gelb": 0, "gruen": 0, "grau": 0,
                    "critical_items": [], "warning_items": []}

    def _health_meds(self, conn) -> Dict:
        """Aktive Medikamente."""
        try:
            rows = conn.execute("""
                SELECT hm.name, hm.dosage, hm.schedule
                FROM health_medications hm
                WHERE hm.status = 'aktiv'
                ORDER BY hm.name
            """).fetchall()
            return {
                "count": len(rows),
                "items": [dict(r) for r in rows],
            }
        except Exception:
            return {"count": 0, "items": []}

    def _health_appointments(self, conn, today_str: str) -> Dict:
        """Anstehende Gesundheitstermine (heute + naechste 7 Tage)."""
        try:
            week_end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d 23:59:59")
            rows = conn.execute("""
                SELECT ha.title, ha.appointment_date, ha.appointment_type,
                       hc.name as doctor_name
                FROM health_appointments ha
                LEFT JOIN health_contacts hc ON ha.doctor_id = hc.id
                WHERE ha.appointment_date >= ? AND ha.appointment_date <= ?
                      AND ha.status IN ('geplant', 'bestaetigt')
                ORDER BY ha.appointment_date ASC
            """, (today_str, week_end)).fetchall()
            return {
                "count": len(rows),
                "items": [dict(r) for r in rows],
            }
        except Exception:
            return {"count": 0, "items": []}

    def _literatur(self, conn) -> Dict:
        """Literatur-Status: ungelesene + in Bearbeitung."""
        try:
            unread = conn.execute(
                "SELECT COUNT(*) FROM lit_sources WHERE read_status = 'unread'"
            ).fetchone()[0]
            reading = conn.execute(
                "SELECT COUNT(*) FROM lit_sources WHERE read_status = 'reading'"
            ).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM lit_sources").fetchone()[0]
            return {
                "total": total,
                "unread": unread,
                "reading": reading,
            }
        except Exception:
            return {"total": 0, "unread": 0, "reading": 0}

    # ================================================================
    # FORMATIERTE AUSGABE
    # ================================================================

    def format_today(self) -> str:
        """Formatiert konsolidierten Tagesstatus als Text."""
        data = self.get_overview()
        lines = [f"=== HEUTE: {data['weekday']} {datetime.now().strftime('%d.%m.%Y')} ===", ""]

        # Routinen
        rt = data["routines"]
        if rt["count"] > 0:
            lines.append(f"  ROUTINEN ({rt['count']}):")
            for r in rt["items"]:
                lines.append(f"    [{r['id']:>3}] {r['name']:<30} ({r['category']})")
            lines.append("")
        else:
            lines.append("  Keine faelligen Routinen heute.")
            lines.append("")

        # Termine
        cal = data["calendar"]
        if cal["count"] > 0:
            lines.append(f"  TERMINE ({cal['count']}):")
            for a in cal["items"]:
                time = a.get("event_time") or "--:--"
                lines.append(f"    {time}  {a['title']}")
            lines.append("")

        # Medikamente
        meds = data["health_meds"]
        if meds["count"] > 0:
            lines.append(f"  MEDIKAMENTE ({meds['count']}):")
            for m in meds["items"]:
                schedule = m.get("schedule") or ""
                dosage = m.get("dosage") or ""
                lines.append(f"    {m['name']:<25} {dosage:<15} {schedule}")
            lines.append("")

        # Gesundheitstermine
        ha = data["health_appointments"]
        if ha["count"] > 0:
            lines.append(f"  ARZTTERMINE (naechste 7 Tage: {ha['count']}):")
            for a in ha["items"]:
                date_str = (a.get("appointment_date") or "---")[:10]
                doctor = a.get("doctor_name") or ""
                lines.append(f"    {date_str}  {a['title']:<30} {doctor}")
            lines.append("")

        # Inventar-Ampel
        inv = data["inventory"]
        if inv["total"] > 0:
            parts = []
            if inv["rot"] > 0:
                parts.append(f"ROT:{inv['rot']}")
            if inv["gelb"] > 0:
                parts.append(f"GELB:{inv['gelb']}")
            if inv["gruen"] > 0:
                parts.append(f"GRUEN:{inv['gruen']}")
            ampel_str = "  ".join(parts) if parts else "alles OK"
            lines.append(f"  VORRAT ({inv['total']} Artikel): {ampel_str}")
            if inv["critical_items"]:
                lines.append(f"    Leer: {', '.join(inv['critical_items'])}")
            if inv["warning_items"]:
                lines.append(f"    Niedrig: {', '.join(inv['warning_items'])}")
            lines.append("")

        # Einkaufsliste
        shop = data["shopping"]
        if shop["count"] > 0:
            lines.append(f"  EINKAUFSLISTE: {shop['count']} Artikel offen")
            lines.append("")

        # Literatur
        lit = data["literatur"]
        if lit["total"] > 0:
            parts = []
            if lit["unread"] > 0:
                parts.append(f"{lit['unread']} ungelesen")
            if lit["reading"] > 0:
                parts.append(f"{lit['reading']} in Bearbeitung")
            if parts:
                lines.append(f"  LITERATUR: {', '.join(parts)}")
                lines.append("")

        # Hinweise
        hints = []
        if rt["count"] > 0:
            hints.append("bach routine done <id>")
        if inv.get("rot", 0) > 0:
            hints.append("bach haushalt pull-check")
        if shop["count"] > 0:
            hints.append("bach haushalt shopping")
        if hints:
            lines.append(f"  Aktionen: {' | '.join(hints)}")

        return "\n".join(lines)
