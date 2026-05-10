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
ApiBookHandler - Zentrale API-Dokumentation
=============================================

Operationen:
  add <name> <base_url> [--auth key|oauth|none] [--desc "..."]   API registrieren
  list                                                            Alle APIs anzeigen
  show <name>                                                     API-Details
  endpoint add <api_name> <METHOD> <path> [--desc "..."]         Endpoint hinzufuegen
  verify [<name>]                                                 API(s) testen
  search <keyword>                                                APIs durchsuchen
  remove <name>                                                   API entfernen
  help                                                            Hilfe

Nutzt: bach.db / api_book
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class ApiBookHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self._ensure_table()

    @property
    def profile_name(self) -> str:
        return "api"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def _ensure_table(self):
        """Stellt sicher dass die api_book Tabelle existiert."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_book (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    provider TEXT,
                    base_url TEXT NOT NULL,
                    auth_type TEXT DEFAULT 'none',
                    description TEXT,
                    endpoints_json TEXT DEFAULT '[]',
                    examples_json TEXT DEFAULT '[]',
                    tags TEXT,
                    last_verified TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    dist_type INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_operations(self) -> dict:
        return {
            "add": "API registrieren: add <name> <base_url> [--auth key|oauth|none] [--desc '...']",
            "list": "Alle APIs anzeigen",
            "show": "API-Details: show <name>",
            "endpoint": "Endpoint verwalten: endpoint add <api> <METHOD> <path>",
            "verify": "API(s) testen: verify [<name>]",
            "search": "APIs durchsuchen: search <keyword>",
            "remove": "API entfernen: remove <name>",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "add": self._add,
            "list": self._list,
            "show": self._show,
            "endpoint": self._endpoint,
            "verify": self._verify,
            "search": self._search,
            "remove": self._remove,
            "help": self._help,
        }
        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"
        return fn(args, dry_run)

    def _add(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, "Verwendung: api add <name> <base_url> [--auth key|oauth|none] [--desc '...'] [--provider '...'] [--tags 'a,b']"

        name = args[0]
        base_url = args[1]
        auth_type = "none"
        description = ""
        provider = ""
        tags = ""

        i = 2
        while i < len(args):
            if args[i] == "--auth" and i + 1 < len(args):
                auth_type = args[i + 1]
                i += 2
            elif args[i] == "--desc" and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif args[i] == "--provider" and i + 1 < len(args):
                provider = args[i + 1]
                i += 2
            elif args[i] == "--tags" and i + 1 < len(args):
                tags = args[i + 1]
                i += 2
            else:
                i += 1

        if dry_run:
            return True, f"[DRY] Wuerde API '{name}' registrieren ({base_url})"

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO api_book (name, provider, base_url, auth_type, description, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    base_url = excluded.base_url,
                    auth_type = excluded.auth_type,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE api_book.description END,
                    provider = CASE WHEN excluded.provider != '' THEN excluded.provider ELSE api_book.provider END,
                    tags = CASE WHEN excluded.tags != '' THEN excluded.tags ELSE api_book.tags END,
                    updated_at = excluded.updated_at
            """, (name, provider, base_url, auth_type, description, tags, now, now))
            conn.commit()
            return True, f"[OK] API '{name}' registriert ({base_url}, auth={auth_type})"
        except sqlite3.IntegrityError as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()

    def _list(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT name, base_url, auth_type, is_active, last_verified, description
                FROM api_book ORDER BY name
            """).fetchall()

            if not rows:
                return True, "Keine APIs registriert.\nHinweis: bach api add <name> <base_url>"

            lines = [f"API-Buch ({len(rows)} APIs)", "=" * 50]
            for r in rows:
                status = "aktiv" if r[3] else "inaktiv"
                verified = r[4] or "nie"
                desc = f" - {r[5][:40]}" if r[5] else ""
                lines.append(f"  [{status:>7}] {r[0]}: {r[1]} (auth={r[2]}, geprueft: {verified}){desc}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _show(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: api show <name>"

        name = args[0]
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("""
                SELECT * FROM api_book WHERE name = ?
            """, (name,)).fetchone()

            if not row:
                return False, f"API '{name}' nicht gefunden."

            # Spaltennamen holen
            cols = [desc[0] for desc in conn.execute("SELECT * FROM api_book LIMIT 0").description]
            data = dict(zip(cols, row))

            lines = [f"API: {data['name']}", "=" * 50]
            lines.append(f"  URL:          {data['base_url']}")
            lines.append(f"  Auth:         {data['auth_type']}")
            lines.append(f"  Provider:     {data.get('provider', '-')}")
            lines.append(f"  Beschreibung: {data.get('description', '-')}")
            lines.append(f"  Tags:         {data.get('tags', '-')}")
            lines.append(f"  Status:       {'aktiv' if data['is_active'] else 'inaktiv'}")
            lines.append(f"  Geprueft:     {data.get('last_verified', 'nie')}")
            lines.append(f"  Erstellt:     {data['created_at']}")

            # Endpoints
            endpoints = json.loads(data.get('endpoints_json', '[]') or '[]')
            if endpoints:
                lines.append(f"\n  Endpoints ({len(endpoints)}):")
                for ep in endpoints:
                    desc = f" - {ep.get('description', '')}" if ep.get('description') else ""
                    lines.append(f"    {ep.get('method', 'GET')} {ep.get('path', '/')}{desc}")

            # Examples
            examples = json.loads(data.get('examples_json', '[]') or '[]')
            if examples:
                lines.append(f"\n  Beispiele ({len(examples)}):")
                for ex in examples:
                    lines.append(f"    {ex}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    def _endpoint(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 4 or args[0] != "add":
            return False, "Verwendung: api endpoint add <api_name> <METHOD> <path> [--desc '...']"

        api_name = args[1]
        method = args[2].upper()
        path = args[3]
        description = ""

        i = 4
        while i < len(args):
            if args[i] == "--desc" and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            else:
                i += 1

        if dry_run:
            return True, f"[DRY] Wuerde Endpoint {method} {path} zu '{api_name}' hinzufuegen"

        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT endpoints_json FROM api_book WHERE name = ?", (api_name,)).fetchone()
            if not row:
                return False, f"API '{api_name}' nicht gefunden."

            endpoints = json.loads(row[0] or '[]')
            endpoints.append({
                "method": method,
                "path": path,
                "description": description,
            })

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                UPDATE api_book SET endpoints_json = ?, updated_at = ? WHERE name = ?
            """, (json.dumps(endpoints, ensure_ascii=False), now, api_name))
            conn.commit()
            return True, f"[OK] Endpoint {method} {path} zu '{api_name}' hinzugefuegt ({len(endpoints)} total)"
        finally:
            conn.close()

    def _verify(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        import urllib.request

        conn = sqlite3.connect(str(self.db_path))
        try:
            if args:
                rows = conn.execute("SELECT name, base_url FROM api_book WHERE name = ?", (args[0],)).fetchall()
            else:
                rows = conn.execute("SELECT name, base_url FROM api_book WHERE is_active = 1").fetchall()

            if not rows:
                return False, "Keine APIs zum Pruefen gefunden."

            if dry_run:
                return True, f"[DRY] Wuerde {len(rows)} API(s) pruefen"

            lines = [f"API-Verify ({len(rows)})", "=" * 50]
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for r in rows:
                name, url = r
                try:
                    req = urllib.request.Request(url, method='HEAD')
                    req.add_header('User-Agent', 'BACH-ApiBook/1.0')
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        status = resp.status

                    conn.execute("UPDATE api_book SET last_verified = ? WHERE name = ?", (now, name))
                    lines.append(f"  [OK]   {name}: HTTP {status}")
                except Exception as e:
                    lines.append(f"  [FAIL] {name}: {str(e)[:60]}")

            conn.commit()
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _search(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: api search <keyword>"

        keyword = "%".join(args)
        pattern = f"%{keyword}%"

        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT name, base_url, description, tags, endpoints_json
                FROM api_book
                WHERE name LIKE ? OR description LIKE ? OR tags LIKE ? OR base_url LIKE ?
                    OR endpoints_json LIKE ?
            """, (pattern, pattern, pattern, pattern, pattern)).fetchall()

            if not rows:
                return True, f"Keine APIs gefunden fuer '{' '.join(args)}'"

            lines = [f"Suchergebnisse: '{' '.join(args)}' ({len(rows)} Treffer)", "=" * 50]
            for r in rows:
                desc = f" - {r[2][:40]}" if r[2] else ""
                lines.append(f"  {r[0]}: {r[1]}{desc}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _remove(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: api remove <name>"

        name = args[0]
        if dry_run:
            return True, f"[DRY] Wuerde API '{name}' entfernen"

        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute("DELETE FROM api_book WHERE name = ?", (name,))
            conn.commit()
            if cursor.rowcount > 0:
                return True, f"[OK] API '{name}' entfernt"
            return False, f"API '{name}' nicht gefunden."
        finally:
            conn.close()

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = [
            "API-Buch (API-Dokumentation)",
            "=" * 50,
            "",
            "Zentrale Verwaltung aller genutzten APIs.",
            "",
            "APIs registrieren:",
            "  bach api add openai https://api.openai.com --auth key --desc 'OpenAI API'",
            "  bach api add github https://api.github.com --auth oauth --provider GitHub",
            "",
            "Endpoints verwalten:",
            "  bach api endpoint add openai POST /v1/chat/completions --desc 'Chat'",
            "",
            "Anzeigen & Suchen:",
            "  bach api list                 Alle APIs",
            "  bach api show openai          API-Details + Endpoints",
            "  bach api search chat          APIs durchsuchen",
            "",
            "Testen:",
            "  bach api verify               Alle aktiven APIs pruefen",
            "  bach api verify openai        Einzelne API pruefen",
            "",
            "Entfernen:",
            "  bach api remove openai        API loeschen",
        ]
        return True, "\n".join(lines)
