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
ObsidianHandler - Obsidian Vault Synchronisation
==================================================

Operationen:
  status              Sync-Status anzeigen
  sync                Vault synchronisieren (Daily Notes, Wiki, Tasks)
  config [path]       Vault-Pfad konfigurieren
  daily               Heutige Daily Note anzeigen/erstellen
  tasks               Tasks aus/nach Obsidian synchronisieren
  wiki                Wiki-Sync (BACH Wiki -> Obsidian)

Nutzt: bach.db / wiki_articles, tasks, memory_working
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler


class ObsidianHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self._vault_path = None

    @property
    def profile_name(self) -> str:
        return "obsidian"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "Sync-Status anzeigen",
            "sync": "Vault synchronisieren",
            "config": "Vault-Pfad konfigurieren: config <path>",
            "daily": "Daily Note anzeigen/erstellen",
            "tasks": "Task-Sync (BACH <-> Obsidian)",
            "wiki": "Wiki-Sync (BACH -> Obsidian)",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "status": self._status,
            "sync": self._sync,
            "config": self._config,
            "daily": self._daily,
            "tasks": self._tasks,
            "wiki": self._wiki,
        }
        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"
        return fn(args, dry_run)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _get_vault_path(self) -> Path:
        if self._vault_path:
            return self._vault_path

        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT value FROM memory_facts WHERE category = 'system' AND key = 'obsidian_vault_path'"
            ).fetchone()
            if row:
                self._vault_path = Path(row[0])
                return self._vault_path
        finally:
            conn.close()
        return None

    def _config(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            vault = self._get_vault_path()
            if vault:
                return True, f"Aktueller Vault-Pfad: {vault}"
            return False, "Kein Vault konfiguriert.\nVerwendung: bach obsidian config <pfad-zum-vault>"

        vault_path = Path(args[0])
        if not vault_path.exists():
            return False, f"Pfad existiert nicht: {vault_path}"

        if dry_run:
            return True, f"[DRY] Wuerde Vault-Pfad setzen: {vault_path}"

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO memory_facts (category, key, value, source, confidence, created_at, updated_at)
                VALUES ('system', 'obsidian_vault_path', ?, 'user-input', 1.0, ?, ?)
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value, updated_at = excluded.updated_at
            """, (str(vault_path), now, now))
            conn.commit()
            self._vault_path = vault_path
            return True, f"[OK] Vault-Pfad gesetzt: {vault_path}"
        finally:
            conn.close()

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        vault = self._get_vault_path()
        lines = ["Obsidian Sync Status", "=" * 40]

        if not vault:
            lines.append("  Vault: nicht konfiguriert")
            lines.append("  Hinweis: bach obsidian config <pfad>")
            return True, "\n".join(lines)

        lines.append(f"  Vault: {vault}")
        lines.append(f"  Existiert: {'ja' if vault.exists() else 'NEIN'}")

        if vault.exists():
            daily_dir = vault / "Daily Notes"
            wiki_dir = vault / "BACH Wiki"
            tasks_file = vault / "BACH Tasks.md"

            lines.append(f"  Daily Notes: {'ja' if daily_dir.exists() else 'nein'}")
            lines.append(f"  BACH Wiki: {'ja' if wiki_dir.exists() else 'nein'}")
            lines.append(f"  Tasks-File: {'ja' if tasks_file.exists() else 'nein'}")

        return True, "\n".join(lines)

    def _sync(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        vault = self._get_vault_path()
        if not vault or not vault.exists():
            return False, "Vault nicht konfiguriert oder nicht vorhanden."

        lines = ["Obsidian Sync", "=" * 40]

        # Daily Note
        ok, msg = self._sync_daily(vault, dry_run)
        lines.append(f"  Daily Note: {msg}")

        # Tasks
        ok, msg = self._sync_tasks(vault, dry_run)
        lines.append(f"  Tasks: {msg}")

        # Wiki
        ok, msg = self._sync_wiki(vault, dry_run)
        lines.append(f"  Wiki: {msg}")

        return True, "\n".join(lines)

    def _daily(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        vault = self._get_vault_path()
        if not vault or not vault.exists():
            return False, "Vault nicht konfiguriert."

        ok, msg = self._sync_daily(vault, dry_run)
        return ok, msg

    def _tasks(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        vault = self._get_vault_path()
        if not vault or not vault.exists():
            return False, "Vault nicht konfiguriert."

        ok, msg = self._sync_tasks(vault, dry_run)
        return ok, msg

    def _wiki(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        vault = self._get_vault_path()
        if not vault or not vault.exists():
            return False, "Vault nicht konfiguriert."

        ok, msg = self._sync_wiki(vault, dry_run)
        return ok, msg

    # ------------------------------------------------------------------
    # Sync-Logik
    # ------------------------------------------------------------------

    def _sync_daily(self, vault: Path, dry_run: bool) -> Tuple[bool, str]:
        daily_dir = vault / "Daily Notes"
        daily_dir.mkdir(exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = daily_dir / f"{today}.md"

        if daily_file.exists():
            return True, f"Bereits vorhanden: {today}.md"

        # Daily Note mit BACH-Kontext erstellen
        conn = sqlite3.connect(str(self.db_path))
        try:
            pending = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
            ).fetchone()[0]

            recent = conn.execute("""
                SELECT content FROM memory_working
                WHERE is_active = 1 ORDER BY created_at DESC LIMIT 3
            """).fetchall()

            content = f"# {today}\n\n"
            content += f"## BACH Status\n- Offene Tasks: {pending}\n\n"
            if recent:
                content += "## Letzte Notizen\n"
                for r in recent:
                    content += f"- {r[0][:100]}\n"
                content += "\n"
            content += "## Notizen\n\n\n## TODO\n- [ ] \n"

            if not dry_run:
                daily_file.write_text(content, encoding="utf-8")
            return True, f"Erstellt: {today}.md"
        finally:
            conn.close()

    def _sync_tasks(self, vault: Path, dry_run: bool) -> Tuple[bool, str]:
        tasks_file = vault / "BACH Tasks.md"
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, title, priority, status, assigned_to
                FROM tasks WHERE status IN ('pending', 'in_progress')
                ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2
                                       WHEN 'P3' THEN 3 ELSE 4 END, id
            """).fetchall()

            content = f"# BACH Tasks\n\n*Zuletzt synchronisiert: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"

            current_prio = None
            for r in rows:
                prio = r[2] or "P3"
                if prio != current_prio:
                    current_prio = prio
                    content += f"\n## {prio}\n\n"
                checkbox = "- [x]" if r[3] == "done" else "- [ ]"
                assigned = f" @{r[4]}" if r[4] else ""
                content += f"{checkbox} [{r[0]}] {r[1]}{assigned}\n"

            if not dry_run:
                tasks_file.write_text(content, encoding="utf-8")
            return True, f"{len(rows)} Tasks synchronisiert"
        finally:
            conn.close()

    def _sync_wiki(self, vault: Path, dry_run: bool) -> Tuple[bool, str]:
        wiki_dir = vault / "BACH Wiki"
        wiki_dir.mkdir(exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT path, title, content FROM wiki_articles"
            ).fetchall()

            synced = 0
            for r in rows:
                title = r[1] or Path(r[0]).stem
                safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
                wiki_file = wiki_dir / f"{safe_title}.md"

                if not dry_run:
                    wiki_file.write_text(f"# {title}\n\n{r[2] or ''}", encoding="utf-8")
                synced += 1

            return True, f"{synced} Wiki-Artikel synchronisiert"
        finally:
            conn.close()
