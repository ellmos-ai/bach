#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
CalendarHandler - Termin- und Kalenderverwaltung CLI

Operationen:
  list              Alle Termine anzeigen
  week              Diese Woche
  month             Dieser Monat
  add "Titel"       Neuen Termin anlegen
  show <id>         Termin-Details
  done <id>         Termin als erledigt markieren
  delete <id>       Termin löschen
  help              Hilfe anzeigen

Nutzt: bach.db / assistant_calendar + household_routines (kombiniert)
Ref: DB_004_TERMINDATENBANK_ANALYSE.md
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from .base import BaseHandler


class CalendarHandler(BaseHandler):

    WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "calendar"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle kommenden Termine",
            "week": "Diese Woche",
            "month": "Dieser Monat",
            "today": "Heute",
            "add": "Termin hinzufügen",
            "show": "Termin-Details",
            "done": "Termin als erledigt",
            "delete": "Termin löschen",
            "help": "Hilfe",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "list":
            return self._list(args)
        elif operation == "week":
            return self._week(args)
        elif operation == "month":
            return self._month(args)
        elif operation == "today":
            return self._today(args)
        elif operation == "add":
            return self._add(args)
        elif operation == "show":
            return self._show(args)
        elif operation == "done":
            return self._done(args)
        elif operation == "delete":
            return self._delete(args)
        elif operation in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach calendar help"

    # ------------------------------------------------------------------
    # WEEK - Diese Woche (inkl. fällige Routinen)
    # ------------------------------------------------------------------
    def _week(self, args: List[str]) -> Tuple[bool, str]:
        now = datetime.now()
        # Montag dieser Woche
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)

        return self._range_view(
            monday, sunday,
            f"KW {now.strftime('%V')} ({monday.strftime('%d.%m.')} - {sunday.strftime('%d.%m.%Y')})"
        )

    # ------------------------------------------------------------------
    # MONTH - Dieser Monat
    # ------------------------------------------------------------------
    def _month(self, args: List[str]) -> Tuple[bool, str]:
        now = datetime.now()
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Letzter Tag des Monats
        if now.month == 12:
            last = first.replace(year=now.year + 1, month=1) - timedelta(seconds=1)
        else:
            last = first.replace(month=now.month + 1) - timedelta(seconds=1)

        monat_name = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        return self._range_view(first, last, f"{monat_name[now.month - 1]} {now.year}")

    # ------------------------------------------------------------------
    # TODAY
    # ------------------------------------------------------------------
    def _today(self, args: List[str]) -> Tuple[bool, str]:
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59)
        wd = self.WEEKDAYS_DE[now.weekday()]
        return self._range_view(start, end, f"Heute ({wd}, {now.strftime('%d.%m.%Y')})")

    # ------------------------------------------------------------------
    # Gemeinsame Range-View (Termine + Routinen)
    # ------------------------------------------------------------------
    def _range_view(self, start: datetime, end: datetime, label: str) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            start_str = start.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end.strftime("%Y-%m-%d %H:%M:%S")

            # 1. Kalender-Termine
            events = conn.execute("""
                SELECT id, title, event_type, start_datetime, end_datetime, location, status
                FROM assistant_calendar
                WHERE start_datetime BETWEEN ? AND ?
                ORDER BY start_datetime ASC
            """, (start_str, end_str)).fetchall()

            # 2. Fällige Routinen
            routines = conn.execute("""
                SELECT id, name, frequency, category, next_due
                FROM household_routines
                WHERE is_active = 1 AND next_due BETWEEN ? AND ?
                ORDER BY next_due ASC
            """, (start_str, end_str)).fetchall()

            total = len(events) + len(routines)
            lines = [ f"[KALENDER] {label} - {total} Einträge\n" ]

            if not events and not routines:
                lines.append("  Keine Termine oder fälligen Routinen.")
                return True, "\n".join(lines)

            # Nach Tagen gruppieren
            current_date = start
            while current_date <= end:
                date_str = current_date.strftime("%Y-%m-%d")
                wd = self.WEEKDAYS_DE[current_date.weekday()]
                day_label = f"{wd} {current_date.strftime('%d.%m.')}"

                day_events = [e for e in events if (e["start_datetime"] or "")[:10] == date_str]
                day_routines = [r for r in routines if (r["next_due"] or "")[:10] == date_str]

                if day_events or day_routines:
                    lines.append(f"  --- {day_label} ---")

                    for e in day_events:
                        time_str = (e["start_datetime"] or "")[11:16]
                        loc = f" @ {e['location']}" if e["location"] else ""
                        status = f" [{e['status']}]" if e["status"] and e["status"] != "geplant" else ""
                        lines.append(f"    [{e['id']:>3}] {time_str} {e['title']}{loc}{status}")

                    for r in day_routines:
                        lines.append(f"    [R{r['id']:>2}] ---- {r['name']} ({r['frequency']}, {r['category']})")

                current_date += timedelta(days=1)

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # LIST - Alle kommenden Termine (30 Tage)
    # ------------------------------------------------------------------
    def _list(self, args: List[str]) -> Tuple[bool, str]:
        days = 30
        for a in args:
            try:
                days = int(a)
                break
            except ValueError:
                pass

        now = datetime.now()
        end = now + timedelta(days=days)
        return self._range_view(now, end, f"Nächste {days} Tage")

    # ------------------------------------------------------------------
    # ADD - Termin anlegen
    # ------------------------------------------------------------------
    def _add(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach calendar add \"Titel\" [Optionen]\n\n"
                "Optionen:\n"
                "  --date, -d    Datum (YYYY-MM-DD oder DD.MM.YYYY)\n"
                "  --time, -t    Uhrzeit (HH:MM)\n"
                "  --end         Ende-Uhrzeit (HH:MM)\n"
                "  --location    Ort\n"
                "  --type        Typ (termin|erinnerung|aufgabe)\n"
                "  --note        Beschreibung\n"
                "  --reminder-minutes, --reminder  Erinnerung in Minuten vor Beginn\n"
                "  --recurrence-rule, --recurrence iCal-Regel, z. B. FREQ=WEEKLY\n"
                "                                   oder daily|weekly|monthly|yearly"
            )

        # Titel: erstes Argument das kein Flag und kein Flag-Wert ist
        known_flags = {
            "--date", "-d", "--time", "-t", "--end", "--location",
            "--type", "--note", "--reminder-minutes", "--reminder",
            "--recurrence-rule", "--recurrence",
        }
        title = None
        skip_next = False
        for a in args:
            if skip_next:
                skip_next = False
                continue
            if a in known_flags:
                skip_next = True
                continue
            if a.startswith("-"):
                continue
            title = a
            break
        if not title:
            return False, "Kein Titel angegeben."

        date_str = self._get_arg(args, "--date") or self._get_arg(args, "-d")
        time_str = self._get_arg(args, "--time") or self._get_arg(args, "-t") or "09:00"
        end_time = self._get_arg(args, "--end")
        location = self._get_arg(args, "--location")
        event_type = self._get_arg(args, "--type") or "termin"
        note = self._get_arg(args, "--note") or ""
        reminder_raw = (
            self._get_arg(args, "--reminder-minutes")
            or self._get_arg(args, "--reminder")
        )
        recurrence_raw = (
            self._get_arg(args, "--recurrence-rule")
            or self._get_arg(args, "--recurrence")
        )

        reminder_minutes = None
        if reminder_raw is not None:
            try:
                reminder_minutes = int(reminder_raw)
            except ValueError:
                return False, "Erinnerungszeit muss eine ganze Zahl in Minuten sein."
            if reminder_minutes < 0:
                return False, "Erinnerungszeit darf nicht negativ sein."

        try:
            recurrence_rule = self._normalize_recurrence_rule(recurrence_raw)
        except ValueError as exc:
            return False, str(exc)
        is_recurring = 1 if recurrence_rule else 0

        # Datum parsen
        now = datetime.now()
        if date_str:
            if "." in date_str:
                parts = date_str.split(".")
                if len(parts) == 3:
                    date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
                elif len(parts) == 2:
                    date_str = f"{now.year}-{parts[1]}-{parts[0]}"
        else:
            date_str = now.strftime("%Y-%m-%d")

        start_dt = f"{date_str} {time_str}:00"
        end_dt = f"{date_str} {end_time}:00" if end_time else None

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO assistant_calendar
                (title, event_type, start_datetime, end_datetime, location,
                 description, status, reminder_minutes, is_recurring,
                 recurrence_rule, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'geplant', ?, ?, ?, ?, ?)
            """, (title, event_type, start_dt, end_dt, location, note,
                  reminder_minutes, is_recurring, recurrence_rule,
                  now.isoformat(), now.isoformat()))
            conn.commit()
            eid = cursor.lastrowid
            return True, f"[OK] Termin #{eid} erstellt: {title} am {date_str} um {time_str}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SHOW
    # ------------------------------------------------------------------
    def _show(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach calendar show <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM assistant_calendar WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Termin {ids[0]} nicht gefunden"

            lines = [
                f"=== TERMIN {row['id']} ===",
                f"Titel:       {row['title']}",
                f"Typ:         {row['event_type'] or '---'}",
                f"Start:       {row['start_datetime'] or '---'}",
                f"Ende:        {row['end_datetime'] or '---'}",
                f"Ort:         {row['location'] or '---'}",
                f"Status:      {row['status'] or '---'}",
                f"Wiederholt:  {'Ja' if row['is_recurring'] else 'Nein'}",
                f"Regel:       {row['recurrence_rule'] or '---'}",
                "Erinnerung:  "
                + (
                    f"{row['reminder_minutes']} Minuten vorher"
                    if row["reminder_minutes"] is not None
                    else "---"
                ),
            ]
            if row["description"]:
                lines.append(f"\nBeschreibung:\n{row['description']}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DONE
    # ------------------------------------------------------------------
    def _done(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach calendar done <id> [id2...]"

        conn = self._get_db()
        try:
            results = []
            for eid in ids:
                row = conn.execute("SELECT title FROM assistant_calendar WHERE id = ?", (eid,)).fetchone()
                if not row:
                    results.append(f"[WARN] Termin {eid} nicht gefunden")
                    continue
                conn.execute("""
                    UPDATE assistant_calendar SET status = 'erledigt', updated_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), eid))
                results.append(f"[OK] Termin {eid} erledigt ({row['title']})")
            conn.commit()
            return True, "\n".join(results)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------
    def _delete(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach calendar delete <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT title FROM assistant_calendar WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Termin {ids[0]} nicht gefunden"
            conn.execute("DELETE FROM assistant_calendar WHERE id = ?", (ids[0],))
            conn.commit()
            return True, f"[OK] Termin {ids[0]} gelöscht ({row['title']})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _help(self) -> Tuple[bool, str]:
        return True, """CALENDAR - Termin- und Kalenderverwaltung
==========================================

BEFEHLE:
  bach calendar today                         Heute
  bach calendar week                          Diese Woche (KW)
  bach calendar month                         Dieser Monat
  bach calendar list                          Nächste 30 Tage
  bach calendar list 60                       Nächste 60 Tage
  bach calendar add "Titel" -d 2026-02-15     Termin anlegen
  bach calendar add "Zahnarzt" -d 15.02.2026 -t 10:30 --location "Praxis Dr. X"
  bach calendar add "Jour fixe" -d 18.08.2026 --reminder 30 --recurrence weekly
  bach calendar add "Review" -d 18.08.2026 --recurrence-rule "FREQ=WEEKLY;COUNT=4"
  bach calendar show <id>                     Details
  bach calendar done <id>                     Als erledigt
  bach calendar delete <id>                   Löschen

HINWEIS:
  Zeigt kombiniert: Kalender-Termine + fällige Haushaltsroutinen

DATENBANK: bach.db / assistant_calendar + household_routines"""

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------
    def _parse_ids(self, args: List[str]) -> Tuple[List[int], List[str]]:
        ids = []
        rest = []
        for arg in args:
            try:
                ids.append(int(arg))
            except ValueError:
                rest.append(arg)
        return ids, rest

    def _get_arg(self, args: List[str], flag: str) -> Optional[str]:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None

    def _normalize_recurrence_rule(self, value: Optional[str]) -> Optional[str]:
        """Normalisiert Kurzformen und prüft die minimale iCal-RRULE-Struktur."""
        if value is None:
            return None

        rule = value.strip()
        if not rule:
            raise ValueError("Wiederholungsregel darf nicht leer sein.")

        shorthand = {
            "daily": "FREQ=DAILY",
            "weekly": "FREQ=WEEKLY",
            "monthly": "FREQ=MONTHLY",
            "yearly": "FREQ=YEARLY",
            "täglich": "FREQ=DAILY",
            "wöchentlich": "FREQ=WEEKLY",
            "monatlich": "FREQ=MONTHLY",
            "jährlich": "FREQ=YEARLY",
        }
        normalized = shorthand.get(rule.lower(), rule.upper())
        if normalized.startswith("RRULE:"):
            normalized = normalized[6:]

        parts = normalized.split(";")
        fields = {}
        for part in parts:
            if "=" not in part:
                raise ValueError(
                    "Wiederholungsregel muss eine iCal-RRULE sein, z. B. FREQ=WEEKLY."
                )
            key, val = part.split("=", 1)
            if not key or not val:
                raise ValueError(
                    "Wiederholungsregel muss eine iCal-RRULE sein, z. B. FREQ=WEEKLY."
                )
            fields[key] = val

        if fields.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
            raise ValueError(
                "Wiederholungsregel benötigt FREQ=DAILY, WEEKLY, MONTHLY oder YEARLY."
            )
        return normalized
