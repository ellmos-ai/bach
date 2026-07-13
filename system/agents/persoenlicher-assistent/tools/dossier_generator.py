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
Tool: dossier_generator
Version: 1.0.0
Author: Claude
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

Description:
    Generiert Personen-Dossiers aus verschiedenen Quellen.
    Sammelt und strukturiert Informationen zu Personen fuer
    Meeting-Vorbereitung, Kontaktmanagement etc.

Usage:
    python dossier_generator.py create "Max Mustermann" --context beruflich
    python dossier_generator.py update "Max Mustermann" --add-note "Treffen am 15.02"
    python dossier_generator.py show "Max Mustermann"
    python dossier_generator.py list
"""

__version__ = "1.0.0"
__author__ = "Claude"

import sqlite3
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# BACH Root ermitteln
BACH_ROOT = Path(__file__).parent.parent.parent.parent.parent

# Den DB-Pfad zentral erfragen, nicht selbst bauen: BACH_ROOT/data/bach.db ist
# die veraltete Kopie im OneDrive-Ordner, nicht die kanonische Datenbank.
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB as DB_PATH
DOSSIERS_DIR = BACH_ROOT / "user" / "persoenlicher_assistent" / "dossiers"


class DossierGenerator:
    """Generiert und verwaltet Personen-Dossiers."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.dossiers_dir = DOSSIERS_DIR
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)

    def _get_db(self):
        """Datenbankverbindung holen."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self, conn):
        """Stellt sicher dass Dossier-Tabelle existiert."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assistant_dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                context TEXT DEFAULT 'allgemein',
                company TEXT,
                position TEXT,
                email TEXT,
                phone TEXT,
                linkedin_url TEXT,
                notes TEXT,
                tags TEXT,
                last_contact DATE,
                next_action TEXT,
                source_urls TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    def create_dossier(self, name: str, context: str = "allgemein",
                       company: str = None, position: str = None,
                       notes: str = None) -> Tuple[bool, str]:
        """Erstellt ein neues Dossier."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            # Pruefen ob bereits existiert
            existing = conn.execute(
                "SELECT id FROM assistant_dossiers WHERE LOWER(name) = LOWER(?)",
                (name,)
            ).fetchone()

            if existing:
                return False, f"Dossier fuer '{name}' existiert bereits (ID: {existing['id']})"

            conn.execute("""
                INSERT INTO assistant_dossiers (name, context, company, position, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (name, context, company, position, notes))
            conn.commit()

            # Markdown-Datei erstellen
            md_path = self._create_markdown(name, context, company, position, notes)

            return True, f"[OK] Dossier erstellt: {name}\n  Datei: {md_path}"

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def _create_markdown(self, name: str, context: str, company: str,
                         position: str, notes: str) -> Path:
        """Erstellt Markdown-Datei fuer Dossier."""
        safe_name = name.lower().replace(" ", "_").replace(".", "")
        md_path = self.dossiers_dir / f"{safe_name}.md"

        content = f"""# Dossier: {name}

**Erstellt:** {datetime.now().strftime('%Y-%m-%d')}
**Kontext:** {context}

## Basisdaten

| Feld | Wert |
|------|------|
| Name | {name} |
| Firma | {company or '-'} |
| Position | {position or '-'} |
| Kontext | {context} |

## Notizen

{notes or '_Noch keine Notizen_'}

## Kontakthistorie

_Noch keine Eintraege_

## Quellen

_Noch keine Quellen erfasst_

---
*Generiert mit BACH Dossier-Generator*
"""
        md_path.write_text(content, encoding="utf-8")
        return md_path

    def update_dossier(self, name: str, add_note: str = None,
                       company: str = None, position: str = None,
                       email: str = None, phone: str = None,
                       linkedin: str = None) -> Tuple[bool, str]:
        """Aktualisiert ein Dossier."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            row = conn.execute(
                "SELECT * FROM assistant_dossiers WHERE LOWER(name) = LOWER(?)",
                (name,)
            ).fetchone()

            if not row:
                return False, f"Dossier '{name}' nicht gefunden"

            updates = []
            params = []

            if add_note:
                old_notes = row['notes'] or ""
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
                new_notes = f"{old_notes}\n\n[{timestamp}] {add_note}".strip()
                updates.append("notes = ?")
                params.append(new_notes)

            if company:
                updates.append("company = ?")
                params.append(company)

            if position:
                updates.append("position = ?")
                params.append(position)

            if email:
                updates.append("email = ?")
                params.append(email)

            if phone:
                updates.append("phone = ?")
                params.append(phone)

            if linkedin:
                updates.append("linkedin_url = ?")
                params.append(linkedin)

            if updates:
                updates.append("updated_at = datetime('now')")
                params.append(row['id'])
                conn.execute(f"""
                    UPDATE assistant_dossiers
                    SET {', '.join(updates)}
                    WHERE id = ?
                """, params)
                conn.commit()

            return True, f"[OK] Dossier aktualisiert: {name}"

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def show_dossier(self, name: str) -> Tuple[bool, str]:
        """Zeigt ein Dossier an."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            row = conn.execute(
                "SELECT * FROM assistant_dossiers WHERE LOWER(name) LIKE LOWER(?)",
                (f"%{name}%",)
            ).fetchone()

            if not row:
                return False, f"Dossier '{name}' nicht gefunden"

            output = [
                f"\n=== DOSSIER: {row['name']} ===",
                f"ID:        {row['id']}",
                f"Kontext:   {row['context']}",
                f"Firma:     {row['company'] or '-'}",
                f"Position:  {row['position'] or '-'}",
                f"Email:     {row['email'] or '-'}",
                f"Telefon:   {row['phone'] or '-'}",
                f"LinkedIn:  {row['linkedin_url'] or '-'}",
                f"Erstellt:  {row['created_at']}",
                f"Update:    {row['updated_at']}",
            ]

            if row['notes']:
                output.append(f"\nNotizen:\n{row['notes']}")

            if row['tags']:
                output.append(f"\nTags: {row['tags']}")

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()

    def list_dossiers(self, context: str = None) -> Tuple[bool, str]:
        """Listet alle Dossiers."""
        conn = self._get_db()
        self._ensure_table(conn)

        try:
            if context:
                rows = conn.execute(
                    "SELECT id, name, context, company, updated_at FROM assistant_dossiers WHERE context = ? ORDER BY name",
                    (context,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, context, company, updated_at FROM assistant_dossiers ORDER BY name"
                ).fetchall()

            if not rows:
                return True, "Keine Dossiers gefunden."

            output = [f"\n[DOSSIERS] {len(rows)} Eintraege:\n"]
            for r in rows:
                company = f" ({r['company']})" if r['company'] else ""
                output.append(f"  [{r['id']}] {r['name']}{company} - {r['context']}")

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ERROR] {e}"
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="BACH Dossier Generator")
    subparsers = parser.add_subparsers(dest="command", help="Verfuegbare Befehle")

    # create
    create_p = subparsers.add_parser("create", help="Neues Dossier erstellen")
    create_p.add_argument("name", help="Name der Person")
    create_p.add_argument("--context", "-c", default="allgemein",
                         help="Kontext (beruflich, privat, allgemein)")
    create_p.add_argument("--company", help="Firma")
    create_p.add_argument("--position", help="Position")
    create_p.add_argument("--notes", "-n", help="Initiale Notizen")

    # update
    update_p = subparsers.add_parser("update", help="Dossier aktualisieren")
    update_p.add_argument("name", help="Name der Person")
    update_p.add_argument("--add-note", help="Notiz hinzufuegen")
    update_p.add_argument("--company", help="Firma aktualisieren")
    update_p.add_argument("--position", help="Position aktualisieren")
    update_p.add_argument("--email", help="Email setzen")
    update_p.add_argument("--phone", help="Telefon setzen")
    update_p.add_argument("--linkedin", help="LinkedIn URL setzen")

    # show
    show_p = subparsers.add_parser("show", help="Dossier anzeigen")
    show_p.add_argument("name", help="Name (auch Teilmatch)")

    # list
    list_p = subparsers.add_parser("list", help="Alle Dossiers auflisten")
    list_p.add_argument("--context", "-c", help="Nach Kontext filtern")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    gen = DossierGenerator()

    if args.command == "create":
        success, msg = gen.create_dossier(
            args.name, args.context, args.company, args.position, args.notes
        )
    elif args.command == "update":
        success, msg = gen.update_dossier(
            args.name, args.add_note, args.company, args.position,
            args.email, args.phone, args.linkedin
        )
    elif args.command == "show":
        success, msg = gen.show_dossier(args.name)
    elif args.command == "list":
        success, msg = gen.list_dossiers(args.context)
    else:
        parser.print_help()
        return 1

    print(msg)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
