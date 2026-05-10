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
ProfileHandler - User-Profil Verwaltung
========================================

Operationen:
  show              Profil anzeigen (JSON + DB kombiniert)
  edit <key> <val>  Profil-Eigenschaft aendern (DB)
  update <k> <v>    Alias fuer edit
  stats             Profil-Statistiken (Eintraege, Kategorien)
  json              profile.json anzeigen
  db                DB-Profil anzeigen (assistant_user_profile)
  export            Profil als Text exportieren

Nutzt: user/profile.json + bach.db / assistant_user_profile
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler


class ProfileHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self.profile_json = self.base_path.parent / "user" / "profile.json"

    @property
    def profile_name(self) -> str:
        return "profile"

    @property
    def target_file(self) -> Path:
        return self.profile_json

    def get_operations(self) -> dict:
        return {
            "show": "Profil anzeigen (JSON + DB)",
            "edit": "Profil-Eigenschaft aendern: edit <kategorie> <key> <value>",
            "update": "Alias fuer edit",
            "stats": "Profil-Statistiken",
            "json": "profile.json anzeigen",
            "db": "DB-Profil anzeigen",
            "export": "Profil als Text exportieren",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "show": self._show,
            "edit": self._edit,
            "update": self._edit,
            "stats": self._stats,
            "json": self._show_json,
            "db": self._show_db,
            "export": self._export,
        }

        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"

        return fn(args, dry_run)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _show(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Kombinierte Ansicht: JSON + DB-Eintraege."""
        lines = ["=== USER PROFIL ===", ""]

        # JSON-Teil
        json_data = self._load_json()
        if json_data:
            stats = json_data.get("stats", {})
            lines.append(f"  Name:     {stats.get('name', '?')}")
            lines.append(f"  Rolle:    {stats.get('role', '?')}")
            lines.append(f"  Sprache:  {stats.get('language', '?')}")
            lines.append(f"  Timezone: {stats.get('timezone', '?')}")
            lines.append(f"  OS:       {stats.get('os', '?')}")

            traits = json_data.get("traits", {})
            if traits:
                lines.append("\n  Eigenschaften:")
                for k, v in traits.items():
                    lines.append(f"    {k}: {v}")

            values = json_data.get("values", [])
            if values:
                lines.append(f"\n  Werte: {', '.join(values)}")

            goals = json_data.get("goals", {})
            if goals:
                lines.append("\n  Ziele:")
                for period, items in goals.items():
                    lines.append(f"    {period}: {', '.join(items)}")
        else:
            lines.append("  (profile.json nicht gefunden)")

        # DB-Teil
        db_entries = self._load_db_entries()
        if db_entries:
            lines.append("\n  Gelernte Praeferenzen (DB):")
            current_cat = None
            for cat, key, val, conf in db_entries:
                if cat != current_cat:
                    current_cat = cat
                    lines.append(f"\n    [{cat}]")
                conf_str = f" ({conf})" if conf != "hoch" else ""
                lines.append(f"      {key}: {val}{conf_str}")

        return True, "\n".join(lines)

    def _edit(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Profil-Eigenschaft in DB setzen/aendern."""
        if len(args) < 3:
            return False, "Verwendung: profile edit <kategorie> <key> <value>\nKategorien: praeferenz, gewohnheit, eigenheit"

        category = args[0]
        key = args[1]
        value = " ".join(args[2:])

        valid_cats = ("praeferenz", "gewohnheit", "eigenheit")
        if category not in valid_cats:
            return False, f"Ungueltige Kategorie: {category}\nErlaubt: {', '.join(valid_cats)}"

        if dry_run:
            return True, f"[DRY] Wuerde setzen: [{category}] {key} = {value}"

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from, created_at, updated_at)
                VALUES (?, ?, ?, 'hoch', 'user-input', ?, ?)
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = 'hoch',
                    learned_from = 'user-input',
                    updated_at = excluded.updated_at
            """, (category, key, value, now, now))
            conn.commit()
            return True, f"[OK] Profil aktualisiert: [{category}] {key} = {value}"
        finally:
            conn.close()

    def _stats(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Profil-Statistiken."""
        lines = ["Profil-Statistiken", "=" * 40]

        # JSON
        json_data = self._load_json()
        if json_data:
            version = json_data.get("meta", {}).get("version", "?")
            updated = json_data.get("meta", {}).get("updated", "?")
            lines.append(f"  profile.json: v{version} (aktualisiert: {updated})")
        else:
            lines.append("  profile.json: nicht gefunden")

        # DB
        conn = sqlite3.connect(str(self.db_path))
        try:
            total = conn.execute("SELECT COUNT(*) FROM assistant_user_profile").fetchone()[0]
            cats = conn.execute("""
                SELECT category, COUNT(*) as cnt
                FROM assistant_user_profile
                GROUP BY category ORDER BY category
            """).fetchall()

            lines.append(f"\n  DB-Eintraege: {total}")
            for cat, cnt in cats:
                lines.append(f"    {cat}: {cnt}")
        except Exception as e:
            lines.append(f"  DB-Fehler: {e}")
        finally:
            conn.close()

        return True, "\n".join(lines)

    def _show_json(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """profile.json anzeigen."""
        json_data = self._load_json()
        if not json_data:
            return False, "profile.json nicht gefunden."
        return True, json.dumps(json_data, indent=2, ensure_ascii=False)

    def _show_db(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """DB-Profil-Eintraege anzeigen."""
        entries = self._load_db_entries()
        if not entries:
            return True, "Keine DB-Profil-Eintraege vorhanden."

        lines = [f"DB-Profil ({len(entries)} Eintraege)", "=" * 40]
        current_cat = None
        for cat, key, val, conf in entries:
            if cat != current_cat:
                current_cat = cat
                lines.append(f"\n  [{cat}]")
            lines.append(f"    {key}: {val} (Konfidenz: {conf})")
        return True, "\n".join(lines)

    def _export(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Profil als zusammengefassten Text exportieren."""
        json_data = self._load_json() or {}
        db_entries = self._load_db_entries()

        lines = ["USER PROFILE EXPORT", "=" * 50, ""]

        stats = json_data.get("stats", {})
        if stats:
            lines.append("BASICS:")
            for k, v in stats.items():
                lines.append(f"  {k}: {v}")

        traits = json_data.get("traits", {})
        if traits:
            lines.append("\nTRAITS:")
            for k, v in traits.items():
                lines.append(f"  {k}: {v}")

        values = json_data.get("values", [])
        if values:
            lines.append(f"\nVALUES: {', '.join(values)}")

        goals = json_data.get("goals", {})
        if goals:
            lines.append("\nGOALS:")
            for period, items in goals.items():
                lines.append(f"  {period}: {', '.join(items)}")

        prefs = json_data.get("preferences", {})
        if prefs:
            lines.append("\nPREFERENCES:")
            for section, data in prefs.items():
                if isinstance(data, dict):
                    lines.append(f"  {section}:")
                    for k, v in data.items():
                        lines.append(f"    {k}: {v}")

        if db_entries:
            lines.append("\nLEARNED (DB):")
            for cat, key, val, conf in db_entries:
                lines.append(f"  [{cat}] {key}: {val}")

        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_json(self) -> dict:
        """profile.json laden."""
        if self.profile_json.exists():
            try:
                return json.loads(self.profile_json.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _load_db_entries(self) -> list:
        """DB-Profil-Eintraege laden als [(category, key, value, confidence), ...]."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT category, key, value, confidence
                FROM assistant_user_profile
                ORDER BY category, key
            """).fetchall()
            return rows
        except Exception:
            return []
        finally:
            conn.close()
