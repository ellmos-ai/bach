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
extensions.py - Extensions Handler
===================================
Verwaltet externe BACH-Extensions (Desktop-Tools, Spezial-Apps).

CLI:
  bach extensions list          Alle Extensions auflisten
  bach extensions show <name>   Details zu einer Extension
  bach extensions run <name>    Extension starten (START.bat)
  bach extensions sync          Extensions in DB synchronisieren
  bach extensions search <term> Extensions durchsuchen
"""

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Tuple, List

from hub.base import BaseHandler

__version__ = "1.0.0"


class ExtensionsHandler(BaseHandler):
    """Handler fuer BACH Extensions."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.extensions_dir = self.base_path.parent / "extensions"
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "extensions"

    @property
    def target_file(self) -> Path:
        return self.extensions_dir

    def get_operations(self) -> dict:
        return {
            "list": "Alle Extensions auflisten",
            "show": "Details zu einer Extension (Name als Argument)",
            "run": "Extension starten (Name als Argument)",
            "sync": "Extensions mit Datenbank synchronisieren",
            "search": "Extensions durchsuchen (Suchbegriff als Argument)",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "list":
            return self._list_extensions()
        elif operation == "show":
            if not args:
                return False, "[FEHLER] Name angeben: bach extensions show <name>"
            return self._show_extension(args[0])
        elif operation == "run":
            if not args:
                return False, "[FEHLER] Name angeben: bach extensions run <name>"
            return self._run_extension(args[0])
        elif operation == "sync":
            return self._sync_extensions(dry_run)
        elif operation == "search":
            if not args:
                return False, "[FEHLER] Suchbegriff angeben: bach extensions search <term>"
            return self._search_extensions(args[0])
        else:
            ops = "\n".join(f"  {k:12s} {v}" for k, v in self.get_operations().items())
            return False, f"[FEHLER] Unbekannte Operation: {operation}\n\nVerfuegbar:\n{ops}"

    def _get_extensions_from_fs(self) -> list:
        """Scannt Dateisystem nach Extensions."""
        if not self.extensions_dir.exists():
            return []

        extensions = []
        for ext_dir in sorted(self.extensions_dir.iterdir()):
            if not ext_dir.is_dir() or ext_dir.name.startswith('.'):
                continue

            info = {
                "name": ext_dir.name,
                "path": str(ext_dir),
                "has_skill": (ext_dir / "SKILL.md").exists(),
                "has_start": (ext_dir / "START.bat").exists(),
                "has_readme": (ext_dir / "README.md").exists(),
                "has_requirements": (ext_dir / "requirements.txt").exists(),
            }

            # Beschreibung aus SKILL.md oder README.md lesen
            desc = ""
            if info["has_skill"]:
                try:
                    content = (ext_dir / "SKILL.md").read_text(encoding='utf-8', errors='replace')
                    for line in content.split('\n'):
                        if line.startswith('description:'):
                            desc = line.split(':', 1)[1].strip()
                            break
                except Exception:
                    pass

            if not desc and info["has_readme"]:
                try:
                    lines = (ext_dir / "README.md").read_text(encoding='utf-8', errors='replace').split('\n')
                    for line in lines[1:6]:
                        line = line.strip()
                        if line and not line.startswith('#') and not line.startswith('-'):
                            desc = line[:100]
                            break
                except Exception:
                    pass

            info["description"] = desc
            # Dateien zaehlen
            py_files = list(ext_dir.glob("*.py"))
            info["py_count"] = len(py_files)
            info["main_file"] = py_files[0].name if py_files else ""

            extensions.append(info)

        return extensions

    def _list_extensions(self) -> Tuple[bool, str]:
        """Listet alle Extensions auf."""
        extensions = self._get_extensions_from_fs()
        if not extensions:
            return True, "[EXTENSIONS] Keine Extensions gefunden."

        lines = [f"[EXTENSIONS] {len(extensions)} Extensions gefunden:\n"]
        for ext in extensions:
            flags = []
            if ext["has_skill"]:
                flags.append("SKILL")
            if ext["has_start"]:
                flags.append("START")
            flag_str = f" [{','.join(flags)}]" if flags else ""
            desc = f"  {ext['description']}" if ext["description"] else ""
            lines.append(f"  {ext['name']:30s} {ext['py_count']:2d} .py{flag_str}")
            if desc:
                lines.append(f"    {desc}")

        lines.append(f"\n  Pfad: {self.extensions_dir}")
        lines.append(f"  --> bach extensions sync  (in DB registrieren)")
        return True, "\n".join(lines)

    def _show_extension(self, name: str) -> Tuple[bool, str]:
        """Zeigt Details zu einer Extension."""
        ext_dir = self.extensions_dir / name
        if not ext_dir.exists():
            # Fuzzy-Suche
            matches = [d.name for d in self.extensions_dir.iterdir()
                       if d.is_dir() and name.lower() in d.name.lower()]
            if matches:
                return False, f"[FEHLER] '{name}' nicht gefunden. Meinten Sie:\n" + "\n".join(f"  {m}" for m in matches)
            return False, f"[FEHLER] Extension '{name}' nicht gefunden."

        lines = [f"=== EXTENSION: {name} ===\n"]
        lines.append(f"Pfad:     {ext_dir}")

        # Dateien auflisten
        files = sorted(ext_dir.iterdir())
        lines.append(f"Dateien:  {len([f for f in files if f.is_file()])}")
        lines.append("")

        for f in files:
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                lines.append(f"  {f.name:30s} {size_kb:>8.1f} KB")

        # SKILL.md Inhalt
        skill_file = ext_dir / "SKILL.md"
        if skill_file.exists():
            lines.append(f"\n--- SKILL.md ---")
            try:
                content = skill_file.read_text(encoding='utf-8', errors='replace')
                lines.append(content[:500])
            except Exception:
                pass

        return True, "\n".join(lines)

    def _run_extension(self, name: str) -> Tuple[bool, str]:
        """Startet eine Extension."""
        ext_dir = self.extensions_dir / name
        if not ext_dir.exists():
            return False, f"[FEHLER] Extension '{name}' nicht gefunden."

        if sys.platform == "win32":
            start_script = ext_dir / "START.bat"
        else:
            start_script = ext_dir / "START.sh"
            if not start_script.exists():
                start_script = ext_dir / "START.bat"

        if start_script.exists():
            try:
                if sys.platform == "win32":
                    subprocess.Popen(
                        ["cmd", "/c", "start", str(start_script)],
                        cwd=str(ext_dir),
                        creationflags=0x00000010
                    )
                elif start_script.suffix == ".sh":
                    subprocess.Popen(
                        ["bash", str(start_script)],
                        cwd=str(ext_dir),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                else:
                    return False, f"[FEHLER] {start_script.name} nur auf Windows verfuegbar."
                return True, f"[OK] Extension '{name}' gestartet ({start_script.name})"
            except Exception as e:
                return False, f"[FEHLER] Start fehlgeschlagen: {e}"

        # Fallback: Hauptdatei direkt ausfuehren
        py_files = list(ext_dir.glob("*.py"))
        main_candidates = [f for f in py_files if f.stem.lower() in ("main", "app", name.lower())]
        main_file = main_candidates[0] if main_candidates else (py_files[0] if py_files else None)

        if main_file:
            try:
                kwargs = {"cwd": str(ext_dir), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                if sys.platform == "win32":
                    kwargs["creationflags"] = 0x08000000
                else:
                    kwargs["start_new_session"] = True
                subprocess.Popen([sys.executable, str(main_file)], **kwargs)
                return True, f"[OK] Extension '{name}' gestartet ({main_file.name})"
            except Exception as e:
                return False, f"[FEHLER] Start fehlgeschlagen: {e}"

        return False, f"[FEHLER] Keine startbare Datei in '{name}' gefunden."

    def _sync_extensions(self, dry_run: bool = False) -> Tuple[bool, str]:
        """Synchronisiert Extensions mit der Datenbank."""
        extensions = self._get_extensions_from_fs()
        if not extensions:
            return True, "[EXTENSIONS] Keine Extensions zum Synchronisieren."

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM skills WHERE type = 'extension'")
            existing = set(row[0] for row in cursor.fetchall())

            added = 0
            updated = 0

            for ext in extensions:
                name = ext["name"]
                desc = ext["description"] or f"Extension: {name}"
                path = ext["path"]
                category = "extension"

                if dry_run:
                    status = "UPDATE" if name in existing else "NEU"
                    print(f"  [{status}] {name}")
                    continue

                if name in existing:
                    cursor.execute("""
                        UPDATE skills SET description = ?, path = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE name = ? AND type = 'extension'
                    """, (desc, path, name))
                    updated += 1
                else:
                    cursor.execute("""
                        INSERT INTO skills (name, type, category, path, description, is_active, version, dist_type)
                        VALUES (?, 'extension', ?, ?, ?, 1, '1.0.0', 2)
                    """, (name, category, path, desc))
                    added += 1

            if not dry_run:
                conn.commit()

            if dry_run:
                return True, f"[DRY-RUN] {len(extensions)} Extensions gefunden."
            return True, f"[EXTENSIONS] Sync: {added} neu, {updated} aktualisiert, {len(extensions)} gesamt"
        finally:
            conn.close()

    def _search_extensions(self, term: str) -> Tuple[bool, str]:
        """Durchsucht Extensions nach Begriff."""
        extensions = self._get_extensions_from_fs()
        term_lower = term.lower()

        matches = [e for e in extensions
                   if term_lower in e["name"].lower() or term_lower in e["description"].lower()]

        if not matches:
            return True, f"[EXTENSIONS] Keine Treffer fuer '{term}'."

        lines = [f"[EXTENSIONS] {len(matches)} Treffer fuer '{term}':\n"]
        for ext in matches:
            lines.append(f"  {ext['name']:30s} {ext['description'][:60]}")

        return True, "\n".join(lines)
