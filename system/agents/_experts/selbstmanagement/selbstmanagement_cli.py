#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
Tool: selbstmanagement_cli
Version: 1.0.0
Author: Claude
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

Description:
    CLI fuer persoenliches Selbstmanagement:
    - Lebenskreise (7 Bereiche) bewerten
    - Berufsziele tracken
    - ADHS-Strategien verwalten

Usage:
    python selbstmanagement_cli.py kreise
    python selbstmanagement_cli.py kreise bewerten
    python selbstmanagement_cli.py ziele list
    python selbstmanagement_cli.py adhd list
"""

__version__ = "1.0.0"
__author__ = "Claude"

import sqlite3
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


# BACH Root ermitteln
BACH_ROOT = Path(__file__).parent.parent.parent.parent

# Den DB-Pfad zentral erfragen, nicht selbst bauen: BACH_ROOT/data/bach.db ist
# die veraltete Kopie im OneDrive-Ordner, nicht die kanonische Datenbank.
import sys

_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB as DB_PATH

# Lebenskreise Definitionen
LIFE_CIRCLES = {
    "health": ("Gesundheit", "Koerperliche & mentale Gesundheit, Fitness, Schlaf"),
    "relationships": ("Beziehungen", "Partner, Familie, Freunde, soziales Netzwerk"),
    "career": ("Karriere", "Beruf, Einkommen, berufliche Entwicklung"),
    "finances": ("Finanzen", "Ersparnisse, Investitionen, finanzielle Sicherheit"),
    "personal_growth": ("Persoenliche Entwicklung", "Lernen, Hobbys, Kreativitaet"),
    "leisure": ("Freizeit", "Erholung, Spass, Reisen, Abenteuer"),
    "environment": ("Umfeld", "Wohnen, Arbeitsumgebung, physische Umgebung"),
}

# ADHS-Strategien Kategorien
ADHD_CATEGORIES = [
    "zeitmanagement",
    "organisation",
    "fokus",
    "emotionsregulation",
    "motivation",
    "selbstfuersorge",
]

# Standard ADHS-Strategien
DEFAULT_ADHD_STRATEGIES = [
    ("Pomodoro-Technik", "zeitmanagement",
     "25 Min arbeiten, 5 Min Pause. Nach 4 Pomodoros: 15-30 Min Pause.",
     "Bei Aufgaben die Fokus erfordern",
     "1. Timer auf 25 Min stellen\n2. Fokussiert arbeiten\n3. Nach Timer: 5 Min Pause\n4. Wiederholen"),
    ("Body Doubling", "fokus",
     "Arbeiten in Anwesenheit einer anderen Person (auch virtuell).",
     "Bei Prokrastination oder wenn Aufgaben unangenehm sind",
     "1. Buddy finden (Freund, Coworking, Discord)\n2. Aufgabe benennen\n3. Gleichzeitig arbeiten"),
    ("Brain Dump", "organisation",
     "Alle Gedanken sofort aufschreiben ohne zu sortieren.",
     "Bei Gedankenchaos oder vor wichtigen Aufgaben",
     "1. Leeres Blatt/Notiz oeffnen\n2. Alles aufschreiben was im Kopf ist\n3. Spaeter sortieren"),
    ("2-Minuten-Regel", "zeitmanagement",
     "Aufgaben unter 2 Minuten sofort erledigen.",
     "Bei kleinen Aufgaben die sich ansammeln",
     "1. Aufgabe identifizieren\n2. Schaetzen: < 2 Min?\n3. Wenn ja: Sofort erledigen"),
    ("Temptation Bundling", "motivation",
     "Unangenehme Aufgabe mit angenehmer Aktivitaet verbinden.",
     "Bei Prokrastination von notwendigen Aufgaben",
     "1. Angenehme Aktivitaet waehlen (Podcast, Musik)\n2. Nur waehrend der Aufgabe erlauben\n3. Aufgabe mit Aktivitaet koppeln"),
    ("Externalisierung", "organisation",
     "Alles aus dem Kopf in ein System bringen.",
     "Bei Vergesslichkeit oder wenn viel zu behalten ist",
     "1. Trusted System waehlen (App, Notizbuch)\n2. Alles sofort notieren\n3. Regelmaessig reviewen"),
    ("Impulskontrolle-Pause", "emotionsregulation",
     "10 Sekunden warten vor impulsiven Reaktionen.",
     "Bei starken Emotionen oder Impulsen",
     "1. STOP sagen (mental oder laut)\n2. 10 Sekunden warten\n3. Durchatmen\n4. Dann entscheiden"),
    ("Belohnungssystem", "motivation",
     "Konkrete Belohnungen fuer erledigte Aufgaben festlegen.",
     "Bei mangelnder Motivation",
     "1. Aufgabe definieren\n2. Passende Belohnung waehlen\n3. Belohnung NUR nach Erledigung"),
]


class SelbstmanagementCLI:
    """CLI fuer Selbstmanagement-Funktionen."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._ensure_tables()

    def _get_db(self):
        """Datenbankverbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self):
        """Stellt sicher dass alle Tabellen existieren."""
        conn = self._get_db()

        # Lebenskreise
        conn.execute("""
            CREATE TABLE IF NOT EXISTS selfmgmt_life_circles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_date DATE NOT NULL,
                health INTEGER CHECK(health BETWEEN 1 AND 10),
                relationships INTEGER CHECK(relationships BETWEEN 1 AND 10),
                career INTEGER CHECK(career BETWEEN 1 AND 10),
                finances INTEGER CHECK(finances BETWEEN 1 AND 10),
                personal_growth INTEGER CHECK(personal_growth BETWEEN 1 AND 10),
                leisure INTEGER CHECK(leisure BETWEEN 1 AND 10),
                environment INTEGER CHECK(environment BETWEEN 1 AND 10),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Berufsziele
        conn.execute("""
            CREATE TABLE IF NOT EXISTS selfmgmt_career_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                target_date DATE,
                status TEXT DEFAULT 'active',
                progress INTEGER DEFAULT 0,
                resources TEXT,
                blockers TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)

        # Meilensteine
        conn.execute("""
            CREATE TABLE IF NOT EXISTS selfmgmt_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER REFERENCES selfmgmt_career_goals(id),
                title TEXT NOT NULL,
                due_date DATE,
                completed_at DATE,
                notes TEXT
            )
        """)

        # ADHS-Strategien
        conn.execute("""
            CREATE TABLE IF NOT EXISTS selfmgmt_adhd_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                when_to_use TEXT,
                steps TEXT,
                effectiveness INTEGER DEFAULT 3,
                personal_notes TEXT,
                times_used INTEGER DEFAULT 0,
                last_used DATE
            )
        """)

        conn.commit()
        conn.close()

    # =========================================================================
    # Lebenskreise
    # =========================================================================

    def kreise_show(self) -> Tuple[bool, str]:
        """Zeigt die letzte Lebenskreise-Bewertung."""
        conn = self._get_db()

        row = conn.execute("""
            SELECT * FROM selfmgmt_life_circles
            ORDER BY assessment_date DESC LIMIT 1
        """).fetchone()

        conn.close()

        if not row:
            return True, self._show_empty_circles()

        output = [
            "\n=== LEBENSKREISE ===",
            f"Bewertung vom: {row['assessment_date']}",
            "",
        ]

        total = 0
        for key, (name, _) in LIFE_CIRCLES.items():
            val = row[key] or 0
            total += val
            bar = "█" * val + "░" * (10 - val)
            output.append(f"  {name:<25} [{bar}] {val}/10")

        avg = total / 7
        output.extend([
            "",
            f"  Durchschnitt: {avg:.1f}/10",
            "",
        ])

        if row['notes']:
            output.append(f"Notizen: {row['notes']}")

        output.extend([
            "",
            "Neues Assessment: python selbstmanagement_cli.py kreise bewerten"
        ])

        return True, "\n".join(output)

    def _show_empty_circles(self) -> str:
        """Zeigt leere Lebenskreise (Erklaerung)."""
        output = [
            "\n=== LEBENSKREISE (7 Bereiche) ===",
            "",
            "Noch keine Bewertung vorhanden. Die 7 Lebensbereiche:",
            "",
        ]

        for key, (name, desc) in LIFE_CIRCLES.items():
            output.append(f"  {name:<25} {desc}")

        output.extend([
            "",
            "Bewertungsskala: 1 (sehr unzufrieden) bis 10 (exzellent)",
            "",
            "Erste Bewertung erstellen:",
            "  python selbstmanagement_cli.py kreise bewerten",
            "",
            "Oder mit Werten:",
            "  python selbstmanagement_cli.py kreise bewerten --health 7 --career 5 ..."
        ])

        return "\n".join(output)

    def kreise_bewerten(self, values: Dict[str, int], notes: str = None) -> Tuple[bool, str]:
        """Erstellt neue Lebenskreise-Bewertung."""
        conn = self._get_db()

        try:
            # Alle Werte muessen zwischen 1-10 sein
            for key, val in values.items():
                if key in LIFE_CIRCLES and (val < 1 or val > 10):
                    return False, f"Wert fuer {key} muss zwischen 1 und 10 sein."

            today = datetime.now().strftime("%Y-%m-%d")

            conn.execute("""
                INSERT INTO selfmgmt_life_circles
                (assessment_date, health, relationships, career, finances,
                 personal_growth, leisure, environment, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today,
                values.get("health"),
                values.get("relationships"),
                values.get("career"),
                values.get("finances"),
                values.get("personal_growth"),
                values.get("leisure"),
                values.get("environment"),
                notes
            ))
            conn.commit()

            return True, f"[OK] Lebenskreise-Bewertung gespeichert ({today})"

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def kreise_historie(self, limit: int = 5) -> Tuple[bool, str]:
        """Zeigt Bewertungs-Historie."""
        conn = self._get_db()

        rows = conn.execute("""
            SELECT * FROM selfmgmt_life_circles
            ORDER BY assessment_date DESC
            LIMIT ?
        """, (limit,)).fetchall()

        conn.close()

        if not rows:
            return True, "Keine Bewertungen vorhanden."

        output = [f"\n=== LEBENSKREISE HISTORIE (letzte {len(rows)}) ===\n"]

        # Header
        output.append(f"{'Datum':<12} {'Ges':>3} {'Bez':>3} {'Kar':>3} {'Fin':>3} {'Ent':>3} {'Fre':>3} {'Umf':>3} {'Avg':>5}")
        output.append("-" * 55)

        for r in rows:
            vals = [r['health'] or 0, r['relationships'] or 0, r['career'] or 0,
                   r['finances'] or 0, r['personal_growth'] or 0, r['leisure'] or 0,
                   r['environment'] or 0]
            avg = sum(vals) / 7
            output.append(
                f"{r['assessment_date']:<12} "
                f"{vals[0]:>3} {vals[1]:>3} {vals[2]:>3} {vals[3]:>3} "
                f"{vals[4]:>3} {vals[5]:>3} {vals[6]:>3} {avg:>5.1f}"
            )

        return True, "\n".join(output)

    # =========================================================================
    # Berufsziele
    # =========================================================================

    def ziele_list(self, status: str = "active") -> Tuple[bool, str]:
        """Listet Berufsziele."""
        conn = self._get_db()

        if status == "all":
            rows = conn.execute("""
                SELECT * FROM selfmgmt_career_goals ORDER BY target_date
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM selfmgmt_career_goals WHERE status = ?
                ORDER BY target_date
            """, (status,)).fetchall()

        conn.close()

        if not rows:
            return True, "Keine Berufsziele vorhanden.\n\nNeues Ziel: python selbstmanagement_cli.py ziele add \"Titel\""

        output = [f"\n=== BERUFSZIELE ({len(rows)}) ===\n"]

        for r in rows:
            progress_bar = "█" * (r['progress'] // 10) + "░" * (10 - r['progress'] // 10)
            target = r['target_date'] or "kein Datum"
            output.append(f"  [{r['id']}] {r['title'][:40]}")
            output.append(f"      [{progress_bar}] {r['progress']}%  Ziel: {target}")
            if r['blockers']:
                output.append(f"      Blocker: {r['blockers'][:50]}")
            output.append("")

        return True, "\n".join(output)

    def ziele_add(self, title: str, description: str = None,
                 target_date: str = None, category: str = None) -> Tuple[bool, str]:
        """Fuegt neues Berufsziel hinzu."""
        conn = self._get_db()

        try:
            conn.execute("""
                INSERT INTO selfmgmt_career_goals
                (title, description, category, target_date)
                VALUES (?, ?, ?, ?)
            """, (title, description, category, target_date))
            conn.commit()

            return True, f"[OK] Berufsziel erstellt: {title}"

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def ziele_progress(self, goal_id: int, progress: int) -> Tuple[bool, str]:
        """Aktualisiert Ziel-Fortschritt."""
        if progress < 0 or progress > 100:
            return False, "Fortschritt muss zwischen 0 und 100 liegen."

        conn = self._get_db()

        try:
            row = conn.execute("SELECT title FROM selfmgmt_career_goals WHERE id = ?", (goal_id,)).fetchone()
            if not row:
                return False, f"Ziel {goal_id} nicht gefunden."

            conn.execute("""
                UPDATE selfmgmt_career_goals
                SET progress = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (progress, goal_id))

            # Bei 100% Status auf "completed" setzen
            if progress >= 100:
                conn.execute("""
                    UPDATE selfmgmt_career_goals SET status = 'completed' WHERE id = ?
                """, (goal_id,))

            conn.commit()

            status = " (ABGESCHLOSSEN!)" if progress >= 100 else ""
            return True, f"[OK] Ziel '{row['title']}' auf {progress}% aktualisiert{status}"

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    # =========================================================================
    # ADHS-Strategien
    # =========================================================================

    def adhd_list(self, category: str = None) -> Tuple[bool, str]:
        """Listet ADHS-Strategien."""
        conn = self._get_db()

        # Pruefen ob Strategien existieren, sonst initialisieren
        count = conn.execute("SELECT COUNT(*) FROM selfmgmt_adhd_strategies").fetchone()[0]
        if count == 0:
            self._init_adhd_strategies(conn)

        if category:
            rows = conn.execute("""
                SELECT * FROM selfmgmt_adhd_strategies
                WHERE LOWER(category) = LOWER(?)
                ORDER BY times_used DESC, name
            """, (category,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM selfmgmt_adhd_strategies
                ORDER BY category, times_used DESC
            """).fetchall()

        conn.close()

        if not rows:
            return True, "Keine Strategien gefunden."

        output = [f"\n=== ADHS-STRATEGIEN ({len(rows)}) ===\n"]

        current_cat = None
        for r in rows:
            if r['category'] != current_cat:
                current_cat = r['category']
                output.append(f"\n[{current_cat.upper()}]")

            eff = "*" * r['effectiveness'] + "-" * (5 - r['effectiveness'])
            uses = f"({r['times_used']}x)" if r['times_used'] > 0 else ""
            output.append(f"  [{r['id']}] {r['name']} {eff} {uses}")

        output.extend([
            "",
            "Details: python selbstmanagement_cli.py adhd show <id>",
            "Verwenden: python selbstmanagement_cli.py adhd verwenden <id>",
        ])

        return True, "\n".join(output)

    def _init_adhd_strategies(self, conn):
        """Initialisiert Standard ADHS-Strategien."""
        for name, cat, desc, when, steps in DEFAULT_ADHD_STRATEGIES:
            conn.execute("""
                INSERT INTO selfmgmt_adhd_strategies
                (name, category, description, when_to_use, steps, effectiveness)
                VALUES (?, ?, ?, ?, ?, 3)
            """, (name, cat, desc, when, steps))
        conn.commit()

    def adhd_show(self, strategy_id: int) -> Tuple[bool, str]:
        """Zeigt Details einer Strategie."""
        conn = self._get_db()

        row = conn.execute("""
            SELECT * FROM selfmgmt_adhd_strategies WHERE id = ?
        """, (strategy_id,)).fetchone()

        conn.close()

        if not row:
            return False, f"Strategie {strategy_id} nicht gefunden."

        eff = "★" * row['effectiveness'] + "☆" * (5 - row['effectiveness'])

        output = [
            f"\n=== {row['name'].upper()} ===",
            f"Kategorie:    {row['category']}",
            f"Effektivitaet: {eff}",
            f"Verwendet:    {row['times_used']}x",
            "",
            "Beschreibung:",
            f"  {row['description']}",
            "",
            "Wann verwenden:",
            f"  {row['when_to_use']}",
            "",
            "Schritte:",
        ]

        if row['steps']:
            for line in row['steps'].split("\n"):
                output.append(f"  {line}")

        if row['personal_notes']:
            output.extend(["", "Persoenliche Notizen:", f"  {row['personal_notes']}"])

        return True, "\n".join(output)

    def adhd_verwenden(self, strategy_id: int, notes: str = None) -> Tuple[bool, str]:
        """Markiert Strategie als verwendet."""
        conn = self._get_db()

        try:
            row = conn.execute("SELECT name FROM selfmgmt_adhd_strategies WHERE id = ?", (strategy_id,)).fetchone()
            if not row:
                return False, f"Strategie {strategy_id} nicht gefunden."

            conn.execute("""
                UPDATE selfmgmt_adhd_strategies
                SET times_used = times_used + 1, last_used = date('now')
                WHERE id = ?
            """, (strategy_id,))

            if notes:
                conn.execute("""
                    UPDATE selfmgmt_adhd_strategies
                    SET personal_notes = COALESCE(personal_notes || char(10), '') || ?
                    WHERE id = ?
                """, (f"[{datetime.now().strftime('%Y-%m-%d')}] {notes}", strategy_id))

            conn.commit()

            return True, f"[OK] Strategie '{row['name']}' als verwendet markiert."

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    # =========================================================================
    # Status/Uebersicht
    # =========================================================================

    def status(self) -> Tuple[bool, str]:
        """Zeigt Gesamtuebersicht."""
        conn = self._get_db()

        # Letzte Lebenskreise
        circles = conn.execute("""
            SELECT * FROM selfmgmt_life_circles
            ORDER BY assessment_date DESC LIMIT 1
        """).fetchone()

        # Aktive Ziele
        goals_active = conn.execute("""
            SELECT COUNT(*) FROM selfmgmt_career_goals WHERE status = 'active'
        """).fetchone()[0]

        goals_completed = conn.execute("""
            SELECT COUNT(*) FROM selfmgmt_career_goals WHERE status = 'completed'
        """).fetchone()[0]

        # Top ADHS-Strategien
        top_strategies = conn.execute("""
            SELECT name, times_used FROM selfmgmt_adhd_strategies
            ORDER BY times_used DESC LIMIT 3
        """).fetchall()

        conn.close()

        output = [
            "\n=== SELBSTMANAGEMENT STATUS ===",
            "",
        ]

        # Lebenskreise
        if circles:
            vals = [circles['health'] or 0, circles['relationships'] or 0,
                   circles['career'] or 0, circles['finances'] or 0,
                   circles['personal_growth'] or 0, circles['leisure'] or 0,
                   circles['environment'] or 0]
            avg = sum(vals) / 7
            output.extend([
                f"Lebenskreise (vom {circles['assessment_date']}):",
                f"  Durchschnitt: {avg:.1f}/10",
                f"  Min: {min(vals)}/10  Max: {max(vals)}/10",
                "",
            ])
        else:
            output.extend([
                "Lebenskreise: Noch keine Bewertung",
                "",
            ])

        # Berufsziele
        output.extend([
            f"Berufsziele:",
            f"  Aktiv: {goals_active}",
            f"  Abgeschlossen: {goals_completed}",
            "",
        ])

        # ADHS-Strategien
        if top_strategies:
            output.append("Top ADHS-Strategien:")
            for s in top_strategies:
                output.append(f"  - {s['name']} ({s['times_used']}x)")
            output.append("")

        output.extend([
            "Befehle:",
            "  kreise, ziele, adhd, status",
        ])

        return True, "\n".join(output)


def main():
    parser = argparse.ArgumentParser(description="BACH Selbstmanagement CLI")
    subparsers = parser.add_subparsers(dest="command", help="Verfuegbare Befehle")

    # kreise
    kreise_p = subparsers.add_parser("kreise", help="Lebenskreise verwalten")
    kreise_sub = kreise_p.add_subparsers(dest="kreise_cmd")

    kreise_show = kreise_sub.add_parser("show", help="Aktuelle Bewertung")
    kreise_bewerten = kreise_sub.add_parser("bewerten", help="Neue Bewertung")
    kreise_bewerten.add_argument("--health", type=int, help="Gesundheit (1-10)")
    kreise_bewerten.add_argument("--relationships", type=int, help="Beziehungen (1-10)")
    kreise_bewerten.add_argument("--career", type=int, help="Karriere (1-10)")
    kreise_bewerten.add_argument("--finances", type=int, help="Finanzen (1-10)")
    kreise_bewerten.add_argument("--personal_growth", type=int, help="Persoenliche Entwicklung (1-10)")
    kreise_bewerten.add_argument("--leisure", type=int, help="Freizeit (1-10)")
    kreise_bewerten.add_argument("--environment", type=int, help="Umfeld (1-10)")
    kreise_bewerten.add_argument("--notes", "-n", help="Notizen")

    kreise_historie = kreise_sub.add_parser("historie", help="Bewertungs-Historie")
    kreise_historie.add_argument("--limit", type=int, default=5)

    # ziele
    ziele_p = subparsers.add_parser("ziele", help="Berufsziele verwalten")
    ziele_sub = ziele_p.add_subparsers(dest="ziele_cmd")

    ziele_list = ziele_sub.add_parser("list", help="Ziele auflisten")
    ziele_list.add_argument("--all", action="store_true", help="Alle (inkl. abgeschlossene)")

    ziele_add = ziele_sub.add_parser("add", help="Neues Ziel")
    ziele_add.add_argument("title", help="Titel des Ziels")
    ziele_add.add_argument("--description", "-d", help="Beschreibung")
    ziele_add.add_argument("--target", "-t", help="Zieldatum (YYYY-MM-DD)")
    ziele_add.add_argument("--category", "-c", help="Kategorie")

    ziele_progress = ziele_sub.add_parser("progress", help="Fortschritt aktualisieren")
    ziele_progress.add_argument("id", type=int, help="Ziel-ID")
    ziele_progress.add_argument("progress", type=int, help="Fortschritt (0-100)")

    # adhd
    adhd_p = subparsers.add_parser("adhd", help="ADHS-Strategien")
    adhd_sub = adhd_p.add_subparsers(dest="adhd_cmd")

    adhd_list = adhd_sub.add_parser("list", help="Strategien auflisten")
    adhd_list.add_argument("--category", "-c", help="Nach Kategorie filtern")

    adhd_show = adhd_sub.add_parser("show", help="Strategie-Details")
    adhd_show.add_argument("id", type=int, help="Strategie-ID")

    adhd_verwenden = adhd_sub.add_parser("verwenden", help="Strategie verwenden")
    adhd_verwenden.add_argument("id", type=int, help="Strategie-ID")
    adhd_verwenden.add_argument("--notes", "-n", help="Notizen zur Anwendung")

    # status
    status_p = subparsers.add_parser("status", help="Gesamtuebersicht")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    cli = SelbstmanagementCLI()

    if args.command == "kreise":
        if args.kreise_cmd == "bewerten":
            values = {}
            for key in LIFE_CIRCLES.keys():
                val = getattr(args, key, None)
                if val is not None:
                    values[key] = val
            if not values:
                print("Bitte mindestens einen Wert angeben:")
                print("  --health 7 --career 5 --relationships 8 ...")
                return 1
            success, msg = cli.kreise_bewerten(values, args.notes)
        elif args.kreise_cmd == "historie":
            success, msg = cli.kreise_historie(args.limit)
        else:
            success, msg = cli.kreise_show()

    elif args.command == "ziele":
        if args.ziele_cmd == "add":
            success, msg = cli.ziele_add(args.title, args.description, args.target, args.category)
        elif args.ziele_cmd == "progress":
            success, msg = cli.ziele_progress(args.id, args.progress)
        else:
            status = "all" if getattr(args, 'all', False) else "active"
            success, msg = cli.ziele_list(status)

    elif args.command == "adhd":
        if args.adhd_cmd == "show":
            success, msg = cli.adhd_show(args.id)
        elif args.adhd_cmd == "verwenden":
            success, msg = cli.adhd_verwenden(args.id, getattr(args, 'notes', None))
        else:
            cat = getattr(args, 'category', None)
            success, msg = cli.adhd_list(cat)

    elif args.command == "status":
        success, msg = cli.status()

    else:
        parser.print_help()
        return 1

    print(msg)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
