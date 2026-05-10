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
CookbookHandler - Rezeptbuch-Tool fuer DB-Doku-Generierung (SQ069)
===================================================================

CLI-Befehle:
  bach cookbook list                   Alle Rezepte anzeigen
  bach cookbook generate <rezept>      Rohfassung aus Rezept generieren
  bach cookbook add <name> --json <f>  Rezept hinzufuegen
  bach cookbook delete <name>          Rezept loeschen
  bach cookbook help                   Hilfe anzeigen

Nutzt: bach.db / cookbook_recipes
Referenz: BACH_Dev/docs/SQ069_REZEPTBUCH_KONZEPT.md
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from hub.base import BaseHandler


class CookbookHandler(BaseHandler):
    """Handler fuer Rezeptbuch-basierte Doku-Generierung."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.output_dir = base_path / "data" / "generated"
        self.output_dir.mkdir(exist_ok=True)

    @property
    def profile_name(self) -> str:
        return "cookbook"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Rezepte anzeigen",
            "generate": "Rohfassung aus Rezept generieren",
            "add": "Rezept hinzufuegen",
            "delete": "Rezept loeschen",
            "help": "Hilfe anzeigen"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        """
        Haupt-Handler-Methode.

        Args:
            operation: Operation (list, generate, add, delete, help)
            args: Argumente
            dry_run: Testmodus

        Returns:
            (success: bool, message: str)
        """
        if operation == "list":
            return self._list_recipes(args)
        elif operation == "generate":
            return self._generate(args, dry_run)
        elif operation == "add":
            return self._add_recipe(args, dry_run)
        elif operation == "delete":
            return self._delete_recipe(args, dry_run)
        elif operation == "help":
            return self._show_help()
        else:
            return (False, f"[ERROR] Unbekannte Operation: {operation}")

    def _list_recipes(self, args: list) -> tuple:
        """Zeigt alle verfuegbaren Rezepte."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT name, title, description, dist_type
                FROM cookbook_recipes
                ORDER BY name
            """)

            recipes = cursor.fetchall()
            conn.close()

            if not recipes:
                return (True, "[INFO] Keine Rezepte vorhanden")

            output = ["Verfuegbare Rezepte:\n"]
            for idx, recipe in enumerate(recipes, 1):
                dist_label = "[CORE]" if recipe["dist_type"] == 2 else "[USER]"
                output.append(f"  [{idx}] {recipe['name']:20} {dist_label}")
                if recipe['title']:
                    output.append(f"      {recipe['title']}")
                if recipe['description']:
                    output.append(f"      {recipe['description']}")
                output.append("")

            return (True, "\n".join(output))

        except Exception as e:
            return (False, f"[ERROR] Fehler beim Lesen der Rezepte: {e}")

    def _generate(self, args: list, dry_run: bool) -> tuple:
        """Generiert Rohfassung aus einem Rezept."""
        if not args:
            return (False, "[ERROR] Rezeptname fehlt. Nutzung: bach cookbook generate <name>")

        recipe_name = args[0]

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Rezept laden
            cursor.execute("""
                SELECT name, title, description, recipe_json
                FROM cookbook_recipes
                WHERE name = ?
            """, (recipe_name,))

            recipe_row = cursor.fetchone()
            if not recipe_row:
                conn.close()
                return (False, f"[ERROR] Rezept '{recipe_name}' nicht gefunden")

            recipe = json.loads(recipe_row["recipe_json"])

            # SQL aus Rezept bauen und ausfuehren
            sql = self._build_sql(recipe)
            cursor.execute(sql)
            rows = cursor.fetchall()

            conn.close()

            # Template anwenden
            content = self._apply_template(recipe, rows)

            # Output-Pfad
            output_file = self.output_dir / recipe.get("output_file", f"{recipe_name.upper()}.md")

            if dry_run:
                return (True, f"[DRY-RUN] Wuerde schreiben: {output_file}\n\nInhalt:\n{content[:500]}...")

            # Datei schreiben
            output_file.write_text(content, encoding="utf-8")

            return (True, f"[OK] Rohfassung generiert: {output_file} ({len(rows)} Zeilen)")

        except Exception as e:
            return (False, f"[ERROR] Fehler beim Generieren: {e}")

    def _build_sql(self, recipe: dict) -> str:
        """Baut SQL-Query aus Rezept-Definition."""
        # Einfache SELECT-Query ohne JOINs (Phase 1)
        table = recipe.get("tables", [])[0] if recipe.get("tables") else "unknown"
        columns = ", ".join(recipe.get("columns", ["*"]))
        where = recipe.get("where", "")
        order = recipe.get("order_by", "")

        sql = f"SELECT {columns} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"

        return sql

    def _apply_template(self, recipe: dict, rows: list) -> str:
        """Wendet Template auf Daten an."""
        template_type = recipe.get("template", "markdown_table")
        title = recipe.get("title", recipe.get("name", "Untitled"))

        if template_type == "markdown_table":
            return self._template_markdown_table(title, rows)
        elif template_type == "markdown_list":
            return self._template_markdown_list(title, rows)
        elif template_type == "json_export":
            return self._template_json_export(title, rows)
        else:
            return f"# {title}\n\n[ERROR] Unbekanntes Template: {template_type}"

    def _template_markdown_table(self, title: str, rows: list) -> str:
        """Markdown-Tabelle Template."""
        if not rows:
            return f"# {title}\n\n*Keine Daten vorhanden*\n"

        # Header aus erstem Row
        headers = list(rows[0].keys())

        lines = [f"# {title}\n"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in rows:
            values = [str(row[h] or "") for h in headers]
            lines.append("| " + " | ".join(values) + " |")

        lines.append(f"\n---\n*Auto-generiert am {datetime.now().strftime('%Y-%m-%d %H:%M')} aus bach.db*\n")

        return "\n".join(lines)

    def _template_markdown_list(self, title: str, rows: list) -> str:
        """Markdown-Liste Template."""
        if not rows:
            return f"# {title}\n\n*Keine Daten vorhanden*\n"

        lines = [f"# {title}\n"]

        for row in rows:
            first_key = list(row.keys())[0]
            lines.append(f"## {row[first_key]}\n")
            for key in list(row.keys())[1:]:
                lines.append(f"- **{key}:** {row[key]}")
            lines.append("")

        lines.append(f"---\n*Auto-generiert am {datetime.now().strftime('%Y-%m-%d %H:%M')} aus bach.db*\n")

        return "\n".join(lines)

    def _template_json_export(self, title: str, rows: list) -> str:
        """JSON-Export Template."""
        data = {
            "title": title,
            "generated_at": datetime.now().isoformat(),
            "rows": [dict(row) for row in rows]
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _add_recipe(self, args: list, dry_run: bool) -> tuple:
        """
        Fuegt ein neues Rezept hinzu.

        Usage:
            bach cookbook add <name> --title "..." --sql "..." [--template <type>] [--output <file>] [--desc "..."]
        """
        if not args:
            return (False, "Fehler: Rezept-Name fehlt\n\nBeispiel: bach cookbook add my_recipe --title \"Mein Rezept\" --sql \"SELECT * FROM tools\"")

        name = args[0]

        # Parse Flags
        title = None
        description = None
        sql_query = None
        template_type = "markdown_table"  # Default
        output_file = None

        i = 1
        while i < len(args):
            if args[i] == "--title" and i + 1 < len(args):
                title = args[i + 1]
                i += 2
            elif args[i] == "--desc" and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif args[i] == "--sql" and i + 1 < len(args):
                sql_query = args[i + 1]
                i += 2
            elif args[i] == "--template" and i + 1 < len(args):
                template_type = args[i + 1]
                i += 2
            elif args[i] == "--output" and i + 1 < len(args):
                output_file = args[i + 1]
                i += 2
            else:
                i += 1

        # Validierung
        if not title:
            return (False, "Fehler: --title ist erforderlich")
        if not sql_query:
            return (False, "Fehler: --sql ist erforderlich")

        # Template-Type Validierung
        valid_templates = ["markdown_table", "markdown_list", "json_export"]
        if template_type not in valid_templates:
            return (False, f"Fehler: Ungueltiger Template-Typ: {template_type}\n\nGueltig: {', '.join(valid_templates)}")

        # Output-File Default
        if not output_file:
            output_file = f"{name}.md"

        # Recipe JSON erstellen
        recipe_json = json.dumps({
            "sql_query": sql_query,
            "template_type": template_type,
            "output_file": output_file
        })

        # Dry-Run?
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Rezept hinzufuegen:\n\nName: {name}\nTitle: {title}\nDescription: {description or '(keine)'}\nSQL: {sql_query}\nTemplate: {template_type}\nOutput: {output_file}")

        # In DB einfuegen
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Pruefe ob Rezept schon existiert
            existing = cursor.execute("""
                SELECT name FROM cookbook_recipes WHERE name = ?
            """, (name,)).fetchone()

            if existing:
                conn.close()
                return (False, f"[ERROR] Rezept '{name}' existiert bereits\n\nNutze 'bach cookbook delete {name}' um es zuerst zu loeschen")

            # Einfuegen
            cursor.execute("""
                INSERT INTO cookbook_recipes (name, title, description, recipe_json, dist_type)
                VALUES (?, ?, ?, ?, ?)
            """, (name, title, description or "", recipe_json, 0))  # dist_type=0 (USER)

            conn.commit()
            conn.close()

            return (True, f"✓ Rezept hinzugefuegt: {name}\n\nTitle: {title}\nSQL: {sql_query}\nTemplate: {template_type}\nOutput: {output_file}\n\nGenerieren mit: bach cookbook generate {name}")

        except Exception as e:
            return (False, f"[ERROR] Rezept konnte nicht hinzugefuegt werden: {e}")

    def _delete_recipe(self, args: list, dry_run: bool) -> tuple:
        """
        Loescht ein Rezept.

        Usage:
            bach cookbook delete <name> [--force]
        """
        if not args:
            return (False, "Fehler: Rezept-Name fehlt\n\nBeispiel: bach cookbook delete my_recipe")

        name = args[0]
        force = "--force" in args

        # Pruefe ob Rezept existiert
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            recipe = cursor.execute("""
                SELECT name, title, dist_type
                FROM cookbook_recipes
                WHERE name = ?
            """, (name,)).fetchone()

            if not recipe:
                conn.close()
                return (False, f"[ERROR] Rezept nicht gefunden: {name}")

            dist_type = recipe['dist_type']
            dist_type_name = {0: "USER", 1: "TEMPLATE", 2: "CORE"}.get(dist_type, "?")

            # Warnung bei CORE/TEMPLATE
            if dist_type in (1, 2) and not force:
                conn.close()
                return (False, f"[WARNUNG] Rezept '{name}' ist ein {dist_type_name}-Rezept\n\nNutze --force um es trotzdem zu loeschen")

            # Dry-Run?
            if dry_run:
                conn.close()
                return (True, f"[DRY-RUN] Wuerde Rezept loeschen:\n\nName: {name}\nTitle: {recipe['title']}\nTyp: {dist_type_name}")

            # Loeschen
            cursor.execute("""
                DELETE FROM cookbook_recipes WHERE name = ?
            """, (name,))

            conn.commit()
            conn.close()

            return (True, f"✓ Rezept geloescht: {name}")

        except Exception as e:
            return (False, f"[ERROR] Rezept konnte nicht geloescht werden: {e}")

    def _show_help(self) -> tuple:
        """Zeigt Hilfe an."""
        help_text = """
BACH Cookbook - Rezeptbuch-Tool
================================

Generiert Doku-Rohfassungen aus DB-Tabellen-Kombinationen via Rezepte.

VERWENDUNG:
  bach cookbook list                   Alle Rezepte anzeigen
  bach cookbook generate <rezept>      Rohfassung generieren
  bach cookbook add <name> --json <f>  Rezept hinzufuegen (Phase 2)
  bach cookbook delete <name>          Rezept loeschen (Phase 2)
  bach cookbook help                   Diese Hilfe

BEISPIELE:
  bach cookbook list
  bach cookbook generate tools_overview

REZEPT-STRUKTUR:
  Rezepte sind JSON-Definitionen in der 'cookbook_recipes' Tabelle.
  Sie definieren:
  - Welche DB-Tabellen abgefragt werden
  - Welche Spalten ausgegeben werden
  - Welches Template verwendet wird
  - Wohin die Ausgabe geschrieben wird

TEMPLATES:
  - markdown_table: Standard-Markdown-Tabelle
  - markdown_list: Strukturierte Liste
  - json_export: JSON-Export

REFERENZ:
  BACH_Dev/docs/SQ069_REZEPTBUCH_KONZEPT.md

---
SQ069 | Phase 1: Basis-Implementierung
        """
        return (True, help_text.strip())


# TODO Phase 2:
# - _add_recipe() mit JSON-File-Import
# - _delete_recipe() mit Bestaetigung
# - Multi-Table JOINs in _build_sql()
# - Custom Templates aus DB (cookbook_templates Tabelle)

# TODO Phase 3:
# - Aggregationen (COUNT, GROUP BY)
# - Verschachtelte Rezepte
# - Auto-Trigger bei DB-Aenderungen (Hook)
