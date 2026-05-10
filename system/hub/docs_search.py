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
DocsSearchHandler - Echtzeit-Dokumentationssuche (ersetzt Context7 MCP)
========================================================================
bach docs-search search <query>      Volltextsuche in docs/wiki/help
bach docs-search index               Suchindex aufbauen (FTS5)
bach docs-search lookup <lib> <topic> In Library-Docs suchen
bach docs-search fetch <url>         Doku-Seite herunterladen und cachen
bach docs-search stats               Index-Statistiken

Nutzt: bach.db / document_index + document_fts (FTS5)
Task: 993
"""
import os
import sys
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Tuple
from .base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class DocsSearchHandler(BaseHandler):

    SEARCH_DIRS = ['docs', 'wiki', 'docs/help']
    EXTENSIONS = {'.md', '.txt', '.rst', '.py'}

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self.cache_dir = self.base_path / "data" / "cache" / "docs"

    @property
    def profile_name(self) -> str:
        return "docs-search"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "search": "Volltextsuche: search <query>",
            "index": "Suchindex aufbauen/aktualisieren",
            "lookup": "Library-Docs: lookup <library> <topic>",
            "fetch": "Doku cachen: fetch <url>",
            "stats": "Index-Statistiken",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "search" and args:
            return self._search(" ".join(args))
        elif operation == "index":
            if dry_run:
                return True, "[DRY-RUN] Index wuerde neu aufgebaut"
            return self._build_index()
        elif operation == "lookup" and len(args) >= 2:
            return self._lookup(args[0], " ".join(args[1:]))
        elif operation == "fetch" and args:
            if dry_run:
                return True, f"[DRY-RUN] Wuerde {args[0]} cachen"
            return self._fetch(args[0])
        elif operation == "stats":
            return self._stats()
        else:
            return self._stats()

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self, conn):
        """Stellt sicher dass noetige Spalten/Tabellen existieren."""
        cursor = conn.cursor()
        # document_index existiert bereits mit anderer Struktur.
        # Fehlende Spalten ergaenzen (ALTER TABLE ist safe mit IF NOT EXISTS pattern)
        existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(document_index)").fetchall()}
        add_cols = {
            "doc_type": "TEXT DEFAULT 'local'",
            "library": "TEXT",
            "url": "TEXT",
        }
        for col, typedef in add_cols.items():
            if col not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE document_index ADD COLUMN {col} {typedef}")
                except sqlite3.OperationalError:
                    pass
        conn.commit()

    def _search(self, query: str) -> Tuple[bool, str]:
        """Volltextsuche ueber alle indexierten Dokumente."""
        conn = self._get_conn()
        self._ensure_tables(conn)
        cursor = conn.cursor()

        results = []
        # FTS5 Suche
        try:
            rows = cursor.execute("""
                SELECT d.file_path, d.file_name, d.doc_type, d.library,
                       snippet(document_fts, 1, '>>>', '<<<', '...', 40) as snippet
                FROM document_fts f
                JOIN document_index d ON d.id = f.rowid
                WHERE document_fts MATCH ?
                ORDER BY rank
                LIMIT 20
            """, (query,)).fetchall()
            for row in rows:
                lib = f" [{row['library']}]" if row['library'] else ""
                results.append(f"  {row['file_path']}{lib}\n    {row['snippet']}")
        except sqlite3.OperationalError:
            # Fallback: LIKE-Suche
            rows = cursor.execute("""
                SELECT file_path, file_name, doc_type,
                       substr(content_text, max(1, instr(lower(content_text), lower(?)) - 40), 120) as snippet
                FROM document_index
                WHERE content_text LIKE ? OR file_name LIKE ?
                LIMIT 20
            """, (query, f"%{query}%", f"%{query}%")).fetchall()
            for row in rows:
                results.append(f"  {row['file_path']}\n    ...{row['snippet']}...")

        conn.close()

        if not results:
            # Direkte Dateisuche als Fallback
            return self._search_files(query)

        header = f"Suche: '{query}' ({len(results)} Treffer)\n{'=' * 40}\n"
        return True, header + "\n\n".join(results)

    def _search_files(self, query: str) -> Tuple[bool, str]:
        """Fallback: Direkte Dateisuche wenn Index leer."""
        results = []
        query_lower = query.lower()
        for search_dir in self.SEARCH_DIRS:
            dir_path = self.base_path / search_dir
            if not dir_path.exists():
                continue
            for ext in self.EXTENSIONS:
                for f in dir_path.rglob(f"*{ext}"):
                    try:
                        content = f.read_text(encoding='utf-8', errors='replace')
                        if query_lower in content.lower():
                            # Kontext finden
                            idx = content.lower().index(query_lower)
                            start = max(0, idx - 40)
                            end = min(len(content), idx + len(query) + 80)
                            snippet = content[start:end].replace('\n', ' ')
                            rel = f.relative_to(self.base_path)
                            results.append(f"  {rel}\n    ...{snippet}...")
                    except Exception:
                        continue

        if not results:
            return False, f"Keine Treffer fuer '{query}'"

        header = f"Dateisuche: '{query}' ({len(results)} Treffer)\n{'=' * 40}\n"
        return True, header + "\n\n".join(results[:20])

    def _build_index(self) -> Tuple[bool, str]:
        """Baut den Suchindex ueber alle Dokumentationen."""
        conn = self._get_conn()
        self._ensure_tables(conn)
        cursor = conn.cursor()

        indexed = 0
        updated = 0

        for search_dir in self.SEARCH_DIRS:
            dir_path = self.base_path / search_dir
            if not dir_path.exists():
                continue
            for ext in self.EXTENSIONS:
                for f in dir_path.rglob(f"*{ext}"):
                    try:
                        content = f.read_text(encoding='utf-8', errors='replace')
                        rel_path = str(f.relative_to(self.base_path))
                        checksum = hashlib.md5(content.encode()).hexdigest()

                        # Titel extrahieren (erste Zeile ohne #)
                        title = f.stem
                        for line in content.split('\n')[:5]:
                            line = line.strip().lstrip('#').strip()
                            if line:
                                title = line[:100]
                                break

                        # Pruefen ob Update noetig
                        existing = cursor.execute(
                            "SELECT file_hash FROM document_index WHERE file_path = ?", (rel_path,)
                        ).fetchone()

                        if existing and existing['file_hash'] == checksum:
                            continue

                        cursor.execute("""
                            INSERT OR REPLACE INTO document_index
                            (file_path, file_name, file_ext, content_text, file_hash, doc_type, file_size, word_count)
                            VALUES (?, ?, ?, ?, ?, 'local', ?, ?)
                        """, (rel_path, title, f.suffix, content, checksum,
                              f.stat().st_size, len(content.split())))

                        if existing:
                            updated += 1
                        else:
                            indexed += 1
                    except Exception:
                        continue

        # FTS neu aufbauen
        try:
            cursor.execute("INSERT INTO document_fts(document_fts) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        total = cursor.execute("SELECT COUNT(*) FROM document_index").fetchone()[0]
        conn.close()

        return True, f"Index: {indexed} neu, {updated} aktualisiert, {total} gesamt"

    def _lookup(self, library: str, topic: str) -> Tuple[bool, str]:
        """Suche in Library-spezifischen Docs."""
        conn = self._get_conn()
        self._ensure_tables(conn)
        cursor = conn.cursor()

        rows = cursor.execute("""
            SELECT file_path, file_name,
                   substr(content_text, max(1, instr(lower(content_text), lower(?)) - 40), 160) as snippet
            FROM document_index
            WHERE library = ? AND (content_text LIKE ? OR file_name LIKE ?)
            LIMIT 10
        """, (topic, library, f"%{topic}%", f"%{topic}%")).fetchall()

        conn.close()

        if not rows:
            return False, f"Keine Docs fuer '{library}:{topic}'. Nutze 'fetch' um Docs herunterzuladen."

        results = [f"  {r['file_path']}\n    {r['file_name']}\n    ...{r['snippet']}..." for r in rows]
        return True, f"Library '{library}' - '{topic}' ({len(rows)} Treffer)\n" + "\n\n".join(results)

    def _fetch(self, url: str) -> Tuple[bool, str]:
        """Laedt Dokumentationsseite herunter und cached sie."""
        try:
            import requests
        except ImportError:
            return False, "requests nicht installiert: pip install requests"

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'BACH-DocsSearch/1.0'})
            resp.raise_for_status()
        except Exception as e:
            return False, f"Fehler beim Download: {e}"

        # HTML zu Text konvertieren
        content = resp.text
        try:
            import html2text
            h = html2text.HTML2Text()
            h.ignore_links = False
            content = h.handle(content)
        except ImportError:
            import re
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content)

        # Cachen
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        cache_file = self.cache_dir / f"{url_hash}.md"
        cache_file.write_text(f"# {url}\n\n{content}", encoding='utf-8')

        # In Index aufnehmen
        conn = self._get_conn()
        self._ensure_tables(conn)
        from urllib.parse import urlparse
        library = urlparse(url).netloc.replace('www.', '').split('.')[0]

        conn.execute("""
            INSERT OR REPLACE INTO document_index
            (file_path, file_name, content_text, url, library, doc_type, file_hash, file_size, word_count)
            VALUES (?, ?, ?, ?, ?, 'web', ?, ?, ?)
        """, (str(cache_file.relative_to(self.base_path)), url[:100], content[:50000], url, library,
              hashlib.md5(content.encode()).hexdigest(), len(content), len(content.split())))

        try:
            conn.execute("INSERT INTO document_fts(document_fts) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

        return True, f"Gecacht: {url}\n  Datei: {cache_file.relative_to(self.base_path)}\n  Library: {library}\n  Groesse: {len(content)} Zeichen"

    def _stats(self) -> Tuple[bool, str]:
        """Index-Statistiken."""
        conn = self._get_conn()
        self._ensure_tables(conn)
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM document_index").fetchone()[0]
        try:
            local = cursor.execute("SELECT COUNT(*) FROM document_index WHERE doc_type='local'").fetchone()[0]
            web = cursor.execute("SELECT COUNT(*) FROM document_index WHERE doc_type='web'").fetchone()[0]
        except sqlite3.OperationalError:
            local = total
            web = 0

        try:
            libs = cursor.execute(
                "SELECT library, COUNT(*) as cnt FROM document_index WHERE library IS NOT NULL GROUP BY library"
            ).fetchall()
        except sqlite3.OperationalError:
            libs = []

        conn.close()

        lines = [
            "DOCS-SEARCH INDEX",
            "=" * 30,
            f"  Gesamt: {total} Dokumente",
            f"  Lokal:  {local}",
            f"  Web:    {web}",
        ]
        if libs:
            lines.append("  Libraries:")
            for lib in libs:
                lines.append(f"    {lib['library']}: {lib['cnt']}")
        if total == 0:
            lines.append("\n  Index leer. Nutze: bach docs-search index")

        return True, "\n".join(lines)
