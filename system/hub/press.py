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
PressHandler - Pressemitteilungen und Positionspapiere
=======================================================

Operationen:
  create --type <type> --title "..." [--body "..."]  Dokument erstellen
  templates                                           Verfuegbare Templates
  list                                                Alle Dokumente
  show <id>                                           Dokument anzeigen
  send <id> --to <email>                              Per Email versenden
  config [--logo <path>] [--author "..."]             Konfiguration
  help                                                Hilfe

Nutzt: bach.db / press_documents, LaTeX
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


class PressHandler(BaseHandler):

    VALID_TYPES = ('pressemitteilung', 'positionspapier')

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self.press_dir = self.base_path / "agents" / "_experts" / "press"
        self._ensure_table()

    @property
    def profile_name(self) -> str:
        return "press"

    @property
    def target_file(self) -> Path:
        return self.press_dir

    def _ensure_table(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS press_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT,
                    metadata_json TEXT,
                    pdf_path TEXT,
                    status TEXT DEFAULT 'draft',
                    sent_to TEXT,
                    sent_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    dist_type INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_operations(self) -> dict:
        return {
            "create": "Dokument erstellen: create --type <type> --title '...' [--body '...']",
            "templates": "Verfuegbare Templates anzeigen",
            "list": "Alle Dokumente anzeigen",
            "show": "Dokument anzeigen: show <id>",
            "send": "Per Email senden: send <id> --to <email>",
            "config": "Konfiguration: config [--logo <path>] [--author '...']",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "create": self._create,
            "templates": self._templates,
            "list": self._list,
            "show": self._show,
            "send": self._send,
            "config": self._config,
            "help": self._help,
        }
        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"
        return fn(args, dry_run)

    def _create(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        doc_type = ""
        title = ""
        body = ""

        i = 0
        while i < len(args):
            if args[i] == "--type" and i + 1 < len(args):
                doc_type = args[i + 1]
                i += 2
            elif args[i] == "--title" and i + 1 < len(args):
                title = args[i + 1]
                i += 2
            elif args[i] == "--body" and i + 1 < len(args):
                body = args[i + 1]
                i += 2
            else:
                i += 1

        if not doc_type or not title:
            return False, f"Verwendung: press create --type <{'|'.join(self.VALID_TYPES)}> --title '...'"

        if doc_type not in self.VALID_TYPES:
            return False, f"Ungueltiger Typ: {doc_type}\nErlaubt: {', '.join(self.VALID_TYPES)}"

        if dry_run:
            return True, f"[DRY] Wuerde {doc_type} erstellen: {title}"

        # LaTeX kompilieren
        try:
            sys.path.insert(0, str(self.press_dir))
            from agents._experts.press.press_compiler import compile_document, load_config
            config = load_config()
            pdf_path = compile_document(doc_type, title, body, config=config)

            # In DB speichern
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute("""
                    INSERT INTO press_documents (doc_type, title, body, pdf_path, status)
                    VALUES (?, ?, ?, ?, 'compiled')
                """, (doc_type, title, body, pdf_path))
                conn.commit()
                doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                return True, f"[OK] {doc_type.title()} erstellt (ID: {doc_id})\nPDF: {pdf_path}"
            finally:
                conn.close()

        except FileNotFoundError as e:
            return False, f"Template-Fehler: {e}"
        except RuntimeError as e:
            # Dokument trotzdem in DB speichern (ohne PDF)
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute("""
                    INSERT INTO press_documents (doc_type, title, body, status)
                    VALUES (?, ?, ?, 'draft')
                """, (doc_type, title, body))
                conn.commit()
                doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                return False, f"LaTeX-Fehler: {e}\nDokument als Entwurf gespeichert (ID: {doc_id})"
            finally:
                conn.close()
        except Exception as e:
            return False, f"Fehler: {e}"

    def _templates(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        try:
            sys.path.insert(0, str(self.press_dir))
            from agents._experts.press.press_compiler import list_templates
            templates = list_templates()
        except Exception:
            templates = []

        if not templates:
            return True, "Keine Templates gefunden."

        lines = ["Verfuegbare Templates", "=" * 40]
        for t in templates:
            lines.append(f"  {t['name']}: {t['path']} ({t['size']} Bytes)")
        return True, "\n".join(lines)

    def _list(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, doc_type, title, status, pdf_path, created_at, sent_to
                FROM press_documents ORDER BY created_at DESC
            """).fetchall()

            if not rows:
                return True, "Keine Dokumente vorhanden.\nErstellen: bach press create --type pressemitteilung --title '...'"

            lines = [f"Press-Dokumente ({len(rows)})", "=" * 60]
            for r in rows:
                sent = f" -> {r[6]}" if r[6] else ""
                pdf = " [PDF]" if r[4] else ""
                lines.append(f"  #{r[0]} [{r[3]}] {r[1]}: {r[2][:40]}{pdf}{sent} ({r[5][:10]})")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _show(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: press show <id>"

        doc_id = int(args[0])
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("""
                SELECT id, doc_type, title, body, pdf_path, status, sent_to, sent_at, created_at
                FROM press_documents WHERE id = ?
            """, (doc_id,)).fetchone()

            if not row:
                return False, f"Dokument #{doc_id} nicht gefunden."

            lines = [
                f"Press-Dokument #{row[0]}", "=" * 50,
                f"  Typ:      {row[1]}",
                f"  Titel:    {row[2]}",
                f"  Status:   {row[5]}",
                f"  PDF:      {row[4] or '-'}",
                f"  Erstellt: {row[8]}",
            ]
            if row[6]:
                lines.append(f"  Gesendet: {row[7]} an {row[6]}")
            if row[3]:
                lines.append(f"\n  Text:\n  {row[3][:300]}{'...' if len(row[3] or '') > 300 else ''}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _send(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 3 or "--to" not in args:
            return False, "Verwendung: press send <id> --to <email>"

        doc_id = int(args[0])
        to_idx = args.index("--to")
        email = args[to_idx + 1] if to_idx + 1 < len(args) else ""

        if not email:
            return False, "Email-Adresse fehlt."

        if dry_run:
            return True, f"[DRY] Wuerde Dokument #{doc_id} an {email} senden"

        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT title, pdf_path, status FROM press_documents WHERE id = ?",
                (doc_id,)
            ).fetchone()

            if not row:
                return False, f"Dokument #{doc_id} nicht gefunden."

            if not row[1] or not Path(row[1]).exists():
                return False, f"Keine PDF vorhanden. Erstelle zuerst: bach press create ..."

            # Email via NotifyHandler
            try:
                from hub.notify import NotifyHandler
                notifier = NotifyHandler(self.base_path)
                success, msg = notifier._send(
                    ["email", f"Pressemitteilung: {row[0]} (PDF im Anhang: {row[1]})"],
                    dry_run
                )
                if success:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("""
                        UPDATE press_documents SET sent_to = ?, sent_at = ?, status = 'sent'
                        WHERE id = ?
                    """, (email, now, doc_id))
                    conn.commit()
                    return True, f"[OK] Dokument #{doc_id} an {email} gesendet"
                return False, f"Versand fehlgeschlagen: {msg}"
            except Exception as e:
                return False, f"Email-Versand fehlgeschlagen: {e}"
        finally:
            conn.close()

    def _config(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        config_file = self.press_dir / "config.json"

        # Wenn keine Args: Config anzeigen
        if not args:
            try:
                config = json.loads(config_file.read_text(encoding='utf-8'))
            except Exception:
                config = {}
            lines = ["Press-Konfiguration", "=" * 40]
            for k, v in config.items():
                lines.append(f"  {k}: {v}")
            lines.append(f"\nAendern: bach press config --author '...' --logo <pfad>")
            return True, "\n".join(lines)

        # Config aktualisieren
        if dry_run:
            return True, "[DRY] Wuerde Konfiguration aktualisieren"

        try:
            config = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
        except Exception:
            config = {}

        i = 0
        while i < len(args):
            if args[i] == "--logo" and i + 1 < len(args):
                config["logo_path"] = args[i + 1]
                i += 2
            elif args[i] == "--author" and i + 1 < len(args):
                config["author"] = args[i + 1]
                i += 2
            elif args[i] == "--email" and i + 1 < len(args):
                config["contact_email"] = args[i + 1]
                i += 2
            elif args[i] == "--org" and i + 1 < len(args):
                config["organization"] = args[i + 1]
                i += 2
            else:
                i += 1

        config_file.write_text(
            json.dumps(config, indent=4, ensure_ascii=False),
            encoding='utf-8'
        )
        return True, "[OK] Konfiguration aktualisiert"

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = [
            "Pressemitteilungen & Positionspapiere", "=" * 50, "",
            "Erstellt professionelle Dokumente via LaTeX.",
            "",
            "Erstellen:",
            "  bach press create --type pressemitteilung --title 'Titel' --body 'Text'",
            "  bach press create --type positionspapier --title 'Titel' --body 'Text'",
            "",
            "Verwalten:",
            "  bach press list                  Alle Dokumente",
            "  bach press show 1                Dokument-Details",
            "  bach press templates             Verfuegbare Templates",
            "",
            "Versenden:",
            "  bach press send 1 --to user@example.com",
            "",
            "Konfiguration:",
            "  bach press config                Aktuelle Config anzeigen",
            "  bach press config --author 'Name' --logo /pfad/logo.png",
            "",
            f"Typen: {', '.join(self.VALID_TYPES)}",
            "Voraussetzung: MiKTeX (pdflatex/xelatex)",
        ]
        return True, "\n".join(lines)
