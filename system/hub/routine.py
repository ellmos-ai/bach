#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
RoutineHandler - Household Routine Management CLI

Operationen:
  list              Alle Routinen anzeigen
  due               Faellige Routinen anzeigen
  done <id> [id2..] Routine(n) als erledigt markieren
  add "Name"        Neue Routine anlegen
  show <id>         Routine-Details
  help              Hilfe anzeigen

Nutzt: bach.db / household_routines
Ref: DB_004_TERMINDATENBANK_ANALYSE.md
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from hub.base import BaseHandler


class RoutineHandler(BaseHandler):

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "routine"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Routinen anzeigen",
            "due": "Faellige Routinen anzeigen",
            "done": "Routine(n) als erledigt markieren",
            "add": "Neue Routine anlegen",
            "show": "Routine-Details anzeigen",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "list":
            return self._list(args)
        elif operation == "due":
            return self._due(args)
        elif operation == "done":
            return self._done(args)
        elif operation == "add":
            return self._add(args)
        elif operation == "show":
            return self._show(args)
        elif operation in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach routine help"

    # ------------------------------------------------------------------
    # LIST - Alle aktiven Routinen
    # ------------------------------------------------------------------
    def _list(self, args: List[str]) -> Tuple[bool, str]:
        category_filter = self._get_arg(args, "--category") or self._get_arg(args, "-c")
        show_all = "--all" in args

        conn = self._get_db()
        try:
            query = "SELECT * FROM household_routines"
            params = []

            if not show_all:
                query += " WHERE is_active = 1"
                if category_filter:
                    query += " AND category = ?"
                    params.append(category_filter)
            elif category_filter:
                query += " WHERE category = ?"
                params.append(category_filter)

            query += " ORDER BY next_due ASC, category ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[ROUTINES] Keine Routinen gefunden.\nNutze: bach routine add \"Name\" --freq woechentlich --cat Kueche"

            lines = [f"[ROUTINES] {len(rows)} Routine(n):\n"]
            current_cat = None
            now = datetime.now().strftime("%Y-%m-%d")

            for r in rows:
                # Kategorie-Gruppierung
                cat = r["category"] or "Sonstige"
                if cat != current_cat:
                    current_cat = cat
                    lines.append(f"  [{cat}]")

                # Status-Marker
                due = r["next_due"] or ""
                due_short = due[:10] if due else "---"
                overdue = due_short <= now if due_short != "---" else False
                marker = "!!!" if overdue else "   "
                active = "+" if r["is_active"] else "-"

                freq_short = (r["frequency"] or "?")[:4]
                last = (r["last_done"] or "---")[:10]

                lines.append(
                    f"  {marker} [{r['id']:>3}] {active} {r['name']:<30} "
                    f"{freq_short:<5} faellig: {due_short}  zuletzt: {last}"
                )

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DUE - Nur faellige Routinen
    # ------------------------------------------------------------------
    def _due(self, args: List[str]) -> Tuple[bool, str]:
        days = 7  # Default: naechste 7 Tage
        for a in args:
            try:
                days = int(a)
                break
            except ValueError:
                pass

        conn = self._get_db()
        try:
            cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            now_str = datetime.now().strftime("%Y-%m-%d")

            rows = conn.execute("""
                SELECT * FROM household_routines
                WHERE is_active = 1 AND next_due <= ?
                ORDER BY next_due ASC
            """, (cutoff,)).fetchall()

            if not rows:
                return True, f"[ROUTINES] Keine faelligen Routinen in den naechsten {days} Tagen."

            overdue = [r for r in rows if (r["next_due"] or "")[:10] <= now_str]
            upcoming = [r for r in rows if (r["next_due"] or "")[:10] > now_str]

            lines = [f"[ROUTINES] Faellig (naechste {days} Tage): {len(rows)}\n"]

            if overdue:
                lines.append(f"  *** UEBERFAELLIG ({len(overdue)}) ***")
                for r in overdue:
                    due_short = (r["next_due"] or "---")[:10]
                    lines.append(f"    [{r['id']:>3}] {r['name']:<30} faellig: {due_short}  ({r['category']})")
                lines.append("")

            if upcoming:
                lines.append(f"  Demnächst ({len(upcoming)}):")
                for r in upcoming:
                    due_short = (r["next_due"] or "---")[:10]
                    lines.append(f"    [{r['id']:>3}] {r['name']:<30} faellig: {due_short}  ({r['category']})")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DONE - Routine(n) als erledigt markieren (Multi-ID)
    # ------------------------------------------------------------------
    def _done(self, args: List[str]) -> Tuple[bool, str]:
        ids, rest = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach routine done <id> [id2 id3...]\n\nMarkiert Routinen als erledigt und berechnet naechstes Faelligkeitsdatum."

        note = self._get_arg(rest, "--note")
        results = []

        conn = self._get_db()
        try:
            for rid in ids:
                row = conn.execute("SELECT * FROM household_routines WHERE id = ?", (rid,)).fetchone()
                if not row:
                    results.append(f"[WARN] Routine {rid} nicht gefunden")
                    continue

                now = datetime.now()
                freq = (row["frequency"] or "").lower()

                # next_due berechnen
                if freq in ("taeglich", "täglich", "daily"):
                    next_due = now + timedelta(days=1)
                elif freq in ("woechentlich", "wöchentlich", "weekly"):
                    next_due = now + timedelta(days=7)
                elif freq in ("2-woechentlich", "2-wöchentlich", "biweekly"):
                    next_due = now + timedelta(days=14)
                elif freq in ("monatlich", "monthly"):
                    next_due = now + timedelta(days=30)
                elif freq in ("quartal", "quarterly"):
                    next_due = now + timedelta(days=90)
                elif freq in ("halbjaehrlich", "halbjährlich"):
                    next_due = now + timedelta(days=182)
                elif freq in ("jaehrlich", "jährlich", "yearly"):
                    next_due = now + timedelta(days=365)
                else:
                    next_due = now + timedelta(days=7)  # Fallback

                updates = {
                    "last_done": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "next_due": next_due.strftime("%Y-%m-%d %H:%M:%S"),
                }

                if note:
                    old_notes = row["notes"] or ""
                    stamp = now.strftime("%Y-%m-%d %H:%M")
                    new_notes = f"{old_notes}\n[{stamp}] {note}".strip()
                    updates["notes"] = new_notes

                set_clause = ", ".join(f"{k} = ?" for k in updates)
                params = list(updates.values()) + [rid]
                conn.execute(f"UPDATE household_routines SET {set_clause} WHERE id = ?", params)

                results.append(
                    f"[OK] Routine {rid} erledigt! "
                    f"({row['name']}) -> naechstes Mal: {next_due.strftime('%Y-%m-%d')}"
                )

            conn.commit()
            return True, "\n".join(results)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Neue Routine anlegen
    # ------------------------------------------------------------------
    def _add(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach routine add \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --freq, -f   Frequenz (taeglich|woechentlich|monatlich|jaehrlich)\n"
                "  --cat, -c    Kategorie (Kueche|Bad|Schlafzimmer|...)\n"
                "  --dur, -d    Dauer in Minuten\n"
                "  --note       Notiz\n"
                "  --schedule   Zeitplan-Details"
            )

        # Name = erster Arg der kein Flag ist
        name = None
        for a in args:
            if not a.startswith("-"):
                name = a
                break

        if not name:
            return False, "Kein Name angegeben. Usage: bach routine add \"Staubsaugen\""

        freq = self._get_arg(args, "--freq") or self._get_arg(args, "-f") or "woechentlich"
        cat = self._get_arg(args, "--cat") or self._get_arg(args, "-c") or "Sonstige"
        dur = self._get_arg(args, "--dur") or self._get_arg(args, "-d") or "0"
        note = self._get_arg(args, "--note") or ""
        schedule = self._get_arg(args, "--schedule") or ""

        try:
            dur_int = int(dur)
        except ValueError:
            dur_int = 0

        now = datetime.now()
        next_due = self._calc_next_due(now, freq)

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO household_routines
                (name, frequency, schedule, category, duration_minutes, last_done, next_due, is_active, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                name, freq, schedule, cat, dur_int,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                next_due.strftime("%Y-%m-%d %H:%M:%S"),
                note,
                now.strftime("%Y-%m-%d %H:%M:%S"),
            ))
            conn.commit()
            rid = cursor.lastrowid
            return True, f"[OK] Routine #{rid} erstellt: {name} ({freq}, {cat})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SHOW - Routine-Details
    # ------------------------------------------------------------------
    def _show(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach routine show <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM household_routines WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Routine {ids[0]} nicht gefunden"

            now_str = datetime.now().strftime("%Y-%m-%d")
            due = (row["next_due"] or "---")[:10]
            overdue = " *** UEBERFAELLIG ***" if due <= now_str and due != "---" else ""

            lines = [
                f"=== ROUTINE {row['id']} ===",
                f"Name:        {row['name']}",
                f"Frequenz:    {row['frequency']}",
                f"Kategorie:   {row['category']}",
                f"Dauer:       {row['duration_minutes']} Min.",
                f"Aktiv:       {'Ja' if row['is_active'] else 'Nein'}",
                f"Zuletzt:     {(row['last_done'] or '---')[:16]}",
                f"Faellig:     {due}{overdue}",
                f"Zeitplan:    {row['schedule'] or '---'}",
                f"Erstellt:    {(row['created_at'] or '---')[:16]}",
            ]
            if row["notes"]:
                lines.append(f"\nNotizen:\n{row['notes']}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _help(self) -> Tuple[bool, str]:
        return True, """ROUTINE - Haushaltsroutinen-Verwaltung
======================================

BEFEHLE:
  bach routine list              Alle Routinen anzeigen
  bach routine list --all        Inkl. inaktive
  bach routine list -c Kueche    Nach Kategorie filtern
  bach routine due               Faellige (7 Tage)
  bach routine due 14            Faellige (14 Tage)
  bach routine done <id> [id2..] Als erledigt markieren
  bach routine done 3 --note "Grundreinigung"
  bach routine add "Name"        Neue Routine
  bach routine add "Staubsaugen" --freq woechentlich --cat Wohnzimmer --dur 30
  bach routine show <id>         Details anzeigen

FREQUENZEN:
  taeglich, woechentlich, 2-woechentlich, monatlich, quartal, halbjaehrlich, jaehrlich

DATENBANK: bach.db / household_routines"""

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

    def _calc_next_due(self, from_dt: datetime, freq: str) -> datetime:
        freq = freq.lower()
        if freq in ("taeglich", "täglich", "daily"):
            return from_dt + timedelta(days=1)
        elif freq in ("woechentlich", "wöchentlich", "weekly"):
            return from_dt + timedelta(days=7)
        elif freq in ("2-woechentlich", "2-wöchentlich", "biweekly"):
            return from_dt + timedelta(days=14)
        elif freq in ("monatlich", "monthly"):
            return from_dt + timedelta(days=30)
        elif freq in ("quartal", "quarterly"):
            return from_dt + timedelta(days=90)
        elif freq in ("halbjaehrlich", "halbjährlich"):
            return from_dt + timedelta(days=182)
        elif freq in ("jaehrlich", "jährlich", "yearly"):
            return from_dt + timedelta(days=365)
        return from_dt + timedelta(days=7)
