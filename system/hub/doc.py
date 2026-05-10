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
DocHandler - Dokumenten-Index und Volltextsuche CLI

Operationen:
  index <path>    Ordner oder Datei indizieren (FTS5)
  search <query>  Volltextsuche (FTS5)
  status          Index-Statistiken anzeigen
  rebuild         FTS-Index neu aufbauen
  clear           Index komplett leeren
  recent [days]   Kuerzlich hinzugefuegte Dokumente (aus folder_scan)
  folders         Registrierte Scan-Ordner anzeigen
  scan <path>     Ordner scannen (folder_diff_scanner)
  help            Hilfe anzeigen

Nutzt: bach.db / document_index + document_fts (FTS5)
Delegiert FTS5-Operationen an: tools/document_indexer.py (DocumentIndexer)
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict
from hub.base import BaseHandler


class DocHandler(BaseHandler):
    """Handler fuer Dokumentensuche und FTS5-Index."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "doc"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "index": "Ordner/Datei indizieren (FTS5)",
            "search": "Volltextsuche (FTS5)",
            "status": "Index-Statistiken",
            "rebuild": "FTS-Index neu aufbauen",
            "clear": "Index leeren",
            "recent": "Kuerzlich hinzugefuegte Dokumente",
            "folders": "Registrierte Scan-Ordner anzeigen",
            "scan": "Ordner scannen (Dateiliste)",
            "dedup": "Duplikate finden (SHA256): dedup <pfad>",
            "classify": "Datenschutz-Scan: classify <pfad>",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        """Verbindung zur Datenbank."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_indexer(self):
        """Importiert DocumentIndexer bei Bedarf."""
        tools_dir = self.base_path / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        from document_indexer import DocumentIndexer
        return DocumentIndexer(self.db_path)

    def _ensure_fts_tables(self):
        """Stellt sicher, dass document_index und document_fts existieren."""
        migration_file = self.base_path / "data" / "migrations" / "doc_001_fts5.sql"
        if not migration_file.exists():
            return

        conn = sqlite3.connect(str(self.db_path))
        try:
            # Pruefen ob Tabelle bereits existiert
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='document_index'"
            ).fetchone()
            if not exists:
                sql = migration_file.read_text(encoding="utf-8")
                for statement in sql.split(";"):
                    stmt = statement.strip()
                    if stmt and not stmt.startswith("--"):
                        try:
                            conn.execute(stmt)
                        except sqlite3.OperationalError:
                            pass  # IF NOT EXISTS / bereits vorhanden
                conn.commit()
        finally:
            conn.close()

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        op = (operation or "").lower().strip()

        if op == "index":
            self._ensure_fts_tables()
            return self._index(args)
        elif op == "search":
            self._ensure_fts_tables()
            return self._search(args)
        elif op == "status":
            self._ensure_fts_tables()
            return self._status(args)
        elif op == "rebuild":
            return self._rebuild(args)
        elif op == "clear":
            return self._clear(args)
        elif op == "recent":
            return self._recent(args)
        elif op == "folders":
            return self._folders()
        elif op == "scan":
            return self._scan(args, dry_run)
        elif op == "dedup":
            return self._dedup(args)
        elif op == "classify":
            return self._classify(args)
        elif op in ("", "help"):
            return self._show_help()
        else:
            return (False, f"Unbekannte Operation: {operation}\nNutze: bach doc help")

    # ------------------------------------------------------------------
    # INDEX - Ordner/Datei indizieren (FTS5)
    # ------------------------------------------------------------------
    def _index(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach doc index <pfad> [Optionen]\n\n"
                "Optionen:\n"
                "  --no-recursive, -n  Nicht rekursiv\n\n"
                "Beispiele:\n"
                "  bach doc index .                   Aktuelles Verzeichnis\n"
                "  bach doc index C:\\Users\\Docs       Bestimmter Ordner\n"
                "  bach doc index datei.txt           Einzelne Datei"
            )

        target_path = None
        no_recursive = "--no-recursive" in args or "-n" in args

        for a in args:
            if not a.startswith("-"):
                target_path = a
                break

        if not target_path:
            return False, "Kein Pfad angegeben."

        path = Path(target_path)
        if not path.is_absolute():
            path = Path.cwd() / path

        if not path.exists():
            return False, f"Pfad nicht gefunden: {path}"

        indexer = self._get_indexer()

        if path.is_file():
            return indexer.index_file(path)
        else:
            return indexer.index_folder(path, recursive=not no_recursive)

    # ------------------------------------------------------------------
    # SEARCH - Volltextsuche (FTS5)
    # ------------------------------------------------------------------
    def _search(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach doc search <query> [--limit N]\n\n"
                "Beispiele:\n"
                "  bach doc search \"backup strategie\"\n"
                "  bach doc search config --limit 5"
            )

        query_parts = []
        limit = 20

        i = 0
        while i < len(args):
            if args[i] in ("--limit", "-l") and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
                continue
            if not args[i].startswith("-"):
                query_parts.append(args[i])
            i += 1

        if not query_parts:
            return False, "Kein Suchbegriff angegeben."

        query = " ".join(query_parts)
        indexer = self._get_indexer()
        return indexer.search(query, limit=limit)

    # ------------------------------------------------------------------
    # STATUS - Index-Statistiken (FTS5)
    # ------------------------------------------------------------------
    def _status(self, args: List[str]) -> Tuple[bool, str]:
        indexer = self._get_indexer()
        return indexer.status()

    # ------------------------------------------------------------------
    # REBUILD - FTS-Index neu aufbauen
    # ------------------------------------------------------------------
    def _rebuild(self, args: List[str]) -> Tuple[bool, str]:
        self._ensure_fts_tables()
        indexer = self._get_indexer()
        return indexer.rebuild()

    # ------------------------------------------------------------------
    # CLEAR - Index leeren
    # ------------------------------------------------------------------
    def _clear(self, args: List[str]) -> Tuple[bool, str]:
        if "--force" not in args and "-f" not in args:
            return False, (
                "WARNUNG: Dies loescht den gesamten Dokumenten-Index!\n"
                "Nutze: bach doc clear --force"
            )
        self._ensure_fts_tables()
        indexer = self._get_indexer()
        return indexer.clear()

    # ------------------------------------------------------------------
    # RECENT - Kuerzlich hinzugefuegte Dokumente (folder_scan)
    # ------------------------------------------------------------------
    def _recent(self, args: list) -> tuple:
        days = 7
        if args:
            try:
                days = int(args[0])
            except ValueError:
                pass

        try:
            conn = self._get_db()
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            rows = conn.execute("""
                SELECT folder_path, file_path, file_name, file_ext,
                       file_size, first_seen, last_modified
                FROM folder_scan_files
                WHERE status = 'active' AND first_seen >= ?
                ORDER BY first_seen DESC LIMIT 50
            """, (cutoff,)).fetchall()
            conn.close()

            if not rows:
                return (True, f"[RECENT] Keine neuen Dokumente in den letzten {days} Tagen.")

            output = [f"[RECENT] {len(rows)} neue Dokumente (letzte {days} Tage):", ""]
            for r in rows:
                size_kb = (r["file_size"] or 0) / 1024
                output.append(f"  {r['file_name']:<50} {size_kb:>8.1f} KB  {r['first_seen'][:10] if r['first_seen'] else ''}")

            return (True, "\n".join(output))

        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return (False, "[ERROR] folder_scan_files Tabelle nicht gefunden.\nTipp: bach doc scan <pfad>")
            return (False, f"[ERROR] {e}")
        except Exception as e:
            return (False, f"[ERROR] {e}")

    # ------------------------------------------------------------------
    # FOLDERS - Registrierte Scan-Ordner
    # ------------------------------------------------------------------
    def _folders(self) -> tuple:
        try:
            conn = self._get_db()
            rows = conn.execute("""
                SELECT folder_path,
                       COUNT(*) as file_count,
                       SUM(file_size) as total_size,
                       MIN(first_seen) as first_scan,
                       MAX(last_scan) as last_scan
                FROM folder_scan_files
                WHERE status = 'active'
                GROUP BY folder_path
                ORDER BY folder_path
            """).fetchall()
            conn.close()

            if not rows:
                return (True, "[FOLDERS] Keine registrierten Ordner.\nTipp: bach doc scan <pfad>")

            output = [f"[FOLDERS] {len(rows)} registrierte Ordner:", ""]
            for f in rows:
                size_mb = (f["total_size"] or 0) / (1024 * 1024)
                last_scan = f["last_scan"][:10] if f["last_scan"] else "nie"
                output.append(f"  {f['folder_path']}")
                output.append(f"    {f['file_count']} Dateien, {size_mb:.1f} MB, Letzter Scan: {last_scan}")
                output.append("")

            return (True, "\n".join(output))

        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return (False, "[ERROR] folder_scan_files Tabelle nicht gefunden.\nTipp: bach doc scan <pfad>")
            return (False, f"[ERROR] {e}")
        except Exception as e:
            return (False, f"[ERROR] {e}")

    # ------------------------------------------------------------------
    # SCAN - Ordner scannen (folder_diff_scanner)
    # ------------------------------------------------------------------
    def _scan(self, args: list, dry_run: bool) -> tuple:
        if not args:
            return (False, "Fehler: Pfad fehlt.\nBeispiel: bach doc scan ~/Documents")

        folder_path = args[0]
        if not Path(folder_path).exists():
            return (False, f"[ERROR] Ordner nicht gefunden: {folder_path}")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde scannen: {folder_path}")

        try:
            import subprocess
            scanner_path = self.base_path / "skills" / "tools" / "folder_diff_scanner.py"

            if not scanner_path.exists():
                return (False, "[ERROR] folder_diff_scanner.py nicht gefunden.")

            result = subprocess.run(
                [sys.executable, str(scanner_path), folder_path],
                capture_output=True,
                text=True,
                cwd=str(self.base_path)
            )

            if result.returncode == 0:
                return (True, f"[SCAN] Ordner gescannt:\n{result.stdout}")
            else:
                return (False, f"[ERROR] Scan fehlgeschlagen:\n{result.stderr}")

        except Exception as e:
            return (False, f"[ERROR] {e}")

    # ------------------------------------------------------------------
    # DEDUP - Duplikat-Scan (INT06)
    # ------------------------------------------------------------------
    def _dedup(self, args: list) -> tuple:
        if not args:
            return False, "Usage: bach doc dedup <pfad> [--min-size 1024] [--no-recursive]"

        scan_path = Path(args[0])
        min_size = 0
        recursive = True

        i = 1
        while i < len(args):
            if args[i] == "--min-size" and i + 1 < len(args):
                min_size = int(args[i + 1])
                i += 2
            elif args[i] in ("--no-recursive", "-n"):
                recursive = False
                i += 1
            else:
                i += 1

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dedup_scanner",
            str(self.base_path / "hub" / "_services" / "document" / "dedup_scanner.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        DedupScanner = mod.DedupScanner
        scanner = DedupScanner(min_size=min_size)
        try:
            result = scanner.scan(scan_path, recursive=recursive)
            return True, scanner.format_report(result)
        except ValueError as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # CLASSIFY - Datenschutz-Scan (INT06)
    # ------------------------------------------------------------------
    def _classify(self, args: list) -> tuple:
        if not args:
            return False, "Usage: bach doc classify <pfad> [--no-recursive]"

        scan_path = Path(args[0])
        recursive = "--no-recursive" not in args and "-n" not in args

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "privacy_classifier",
            str(self.base_path / "hub" / "_services" / "document" / "privacy_classifier.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PrivacyClassifier = mod.PrivacyClassifier
        classifier = PrivacyClassifier()

        if scan_path.is_file():
            result = classifier.classify_file(scan_path)
            if result["error"]:
                return False, f"Fehler: {result['error']}"
            lines = [f"Datei: {scan_path}", f"Ampel: {result['ampel']}"]
            for f in result["findings"]:
                lines.append(f"  {f['pattern']}: {', '.join(f['matches'][:3])}")
            if not result["findings"]:
                lines.append("  Keine sensiblen Daten erkannt.")
            return True, "\n".join(lines)
        else:
            try:
                result = classifier.scan_directory(scan_path, recursive=recursive)
                return True, classifier.format_report(result)
            except ValueError as e:
                return False, str(e)

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _show_help(self) -> tuple:
        lines = [
            "=== DOC - Dokumenten-Index & Volltextsuche ===",
            "",
            "FTS5-INDEX (Volltextsuche):",
            "  bach doc index <pfad>              Ordner rekursiv indizieren",
            "  bach doc index <datei>             Einzelne Datei indizieren",
            "  bach doc index <pfad> -n           Nicht rekursiv",
            "  bach doc search \"suchbegriff\"      Volltextsuche (FTS5)",
            "  bach doc search \"config\" --limit 5 Ergebnisse begrenzen",
            "  bach doc status                    Index-Statistiken",
            "  bach doc rebuild                   FTS-Index neu aufbauen",
            "  bach doc clear --force             Index komplett leeren",
            "",
            "DATEI-SCAN (folder_scan):",
            "  bach doc scan <pfad>               Ordner scannen (Dateiliste)",
            "  bach doc recent [tage]             Neue Dokumente (default: 7 Tage)",
            "  bach doc folders                   Registrierte Ordner anzeigen",
            "",
            "ANALYSE (INT06):",
            "  bach doc dedup <pfad>              Duplikate finden (SHA256)",
            "  bach doc dedup <pfad> --min-size 1024  Nur Dateien >1KB",
            "  bach doc classify <pfad>           Datenschutz-Scan (Ampel)",
            "  bach doc classify <datei>          Einzelne Datei pruefen",
            "",
            "UNTERSTUETZTE FORMATE (FTS5-Index):",
            "  Text:    .txt, .md, .html, .log, .cfg, .ini, .yaml, .yml",
            "  Code:    .py, .js, .json, .csv, .xml",
            "  Office:  .pdf (pypdf/pdfplumber), .docx (python-docx)",
            "",
            "DATENBANK: bach.db / document_index + document_fts (FTS5)",
        ]
        return (True, "\n".join(lines))
