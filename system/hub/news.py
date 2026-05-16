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
NewsHandler - News-Aggregation fuer BACH
==========================================

Operationen:
  add <url> [--type rss|web|youtube] [--category X] [--name "..."]
  list                              Quellen anzeigen
  fetch [--source <id>]             News abrufen
  items [--unread] [--category X] [--limit N]  News anzeigen
  read <id|all>                     Als gelesen markieren
  remove <id>                       Quelle entfernen
  categories                        Kategorien anzeigen
  stats                             Statistiken
  help                              Hilfe

Nutzt: bach.db / news_sources, news_items
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


class NewsHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self._ensure_tables()

    @property
    def profile_name(self) -> str:
        return "news"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def _ensure_tables(self):
        """Stellt sicher dass die News-Tabellen existieren."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS news_sources (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        type TEXT NOT NULL CHECK(type IN ('rss','web','youtube','social')),
                        url TEXT UNIQUE NOT NULL,
                        category TEXT DEFAULT 'allgemein',
                        schedule TEXT DEFAULT 'daily',
                        is_active INTEGER DEFAULT 1,
                        last_fetched TEXT,
                        fetch_count INTEGER DEFAULT 0,
                        error_count INTEGER DEFAULT 0,
                        last_error TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        dist_type INTEGER DEFAULT 0
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS news_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_id INTEGER NOT NULL REFERENCES news_sources(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        content TEXT,
                        summary TEXT,
                        url TEXT,
                        author TEXT,
                        published_at TEXT,
                        fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        is_read INTEGER DEFAULT 0,
                        category TEXT,
                        UNIQUE(source_id, url)
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def get_operations(self) -> dict:
        return {
            "add": "Quelle hinzufuegen: add <url> [--type rss|web|youtube] [--category X] [--name '...']",
            "list": "Quellen anzeigen",
            "fetch": "News abrufen: fetch [--source <id>]",
            "items": "News anzeigen: items [--unread] [--category X] [--limit N]",
            "read": "Als gelesen markieren: read <id|all>",
            "remove": "Quelle entfernen: remove <id>",
            "categories": "Kategorien anzeigen",
            "stats": "Statistiken",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "add": self._add,
            "list": self._list,
            "fetch": self._fetch,
            "items": self._items,
            "read": self._read,
            "remove": self._remove,
            "categories": self._categories,
            "stats": self._stats,
            "help": self._help,
        }
        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"
        return fn(args, dry_run)

    def _detect_type(self, url: str) -> str:
        """Erkennt den Quellen-Typ anhand der URL."""
        url_lower = url.lower()
        if any(x in url_lower for x in ['/feed', '/rss', '.xml', '.atom', '/atom']):
            return 'rss'
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        return 'web'

    def _extract_youtube_channel_id(self, url: str) -> str:
        """Extrahiert Channel-ID aus YouTube-URL."""
        import re
        # /channel/UC...
        m = re.search(r'/channel/(UC[\w-]+)', url)
        if m:
            return m.group(1)
        # /@handle -> Wir koennen die ID nicht direkt extrahieren
        return ""

    def _add(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: news add <url> [--type rss|web|youtube] [--category X] [--name '...']"

        url = args[0]
        source_type = ""
        category = "allgemein"
        name = ""

        i = 1
        while i < len(args):
            if args[i] == "--type" and i + 1 < len(args):
                source_type = args[i + 1]
                i += 2
            elif args[i] == "--category" and i + 1 < len(args):
                category = args[i + 1]
                i += 2
            elif args[i] == "--name" and i + 1 < len(args):
                name = args[i + 1]
                i += 2
            else:
                i += 1

        if not source_type:
            source_type = self._detect_type(url)

        if not name:
            # Name aus URL ableiten
            from urllib.parse import urlparse
            parsed = urlparse(url)
            name = parsed.netloc.replace('www.', '') or url[:40]

        # YouTube: URL zu RSS-Feed konvertieren
        if source_type == 'youtube':
            channel_id = self._extract_youtube_channel_id(url)
            if channel_id:
                url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                source_type = 'rss'  # YouTube RSS ist ein normaler RSS-Feed

        if dry_run:
            return True, f"[DRY] Wuerde Quelle hinzufuegen: {name} ({source_type}, {url})"

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT INTO news_sources (name, type, url, category)
                VALUES (?, ?, ?, ?)
            """, (name, source_type, url, category))
            conn.commit()
            return True, f"[OK] Quelle hinzugefuegt: {name} (Typ: {source_type}, Kategorie: {category})"
        except sqlite3.IntegrityError:
            return False, f"URL bereits registriert: {url}"
        finally:
            conn.close()

    def _list(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, name, type, url, category, is_active, last_fetched, fetch_count, error_count
                FROM news_sources ORDER BY category, name
            """).fetchall()

            if not rows:
                return True, "Keine News-Quellen registriert.\nHinweis: bach news add <url>"

            lines = [f"News-Quellen ({len(rows)})", "=" * 60]
            current_cat = None
            for r in rows:
                if r[4] != current_cat:
                    current_cat = r[4]
                    lines.append(f"\n  [{current_cat.upper()}]")
                status = "aktiv" if r[5] else "inaktiv"
                last = r[6] or "nie"
                errors = f" ({r[8]} Fehler)" if r[8] else ""
                lines.append(f"    #{r[0]} [{status}] {r[1]} ({r[2]}) - {r[3][:50]} [fetches: {r[7]}, letzter: {last}]{errors}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _fetch(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        source_id = None
        i = 0
        while i < len(args):
            if args[i] == "--source" and i + 1 < len(args):
                source_id = int(args[i + 1])
                i += 2
            else:
                i += 1

        conn = sqlite3.connect(str(self.db_path))
        try:
            if source_id:
                sources = conn.execute(
                    "SELECT id, name, type, url FROM news_sources WHERE id = ? AND is_active = 1",
                    (source_id,)
                ).fetchall()
            else:
                sources = conn.execute(
                    "SELECT id, name, type, url FROM news_sources WHERE is_active = 1"
                ).fetchall()

            if not sources:
                return False, "Keine aktiven Quellen gefunden."

            if dry_run:
                return True, f"[DRY] Wuerde {len(sources)} Quelle(n) abrufen"

            total_new = 0
            total_errors = 0
            lines = [f"News-Fetch ({len(sources)} Quellen)", "=" * 50]

            for src in sources:
                sid, sname, stype, surl = src
                try:
                    if stype == 'rss':
                        count = self._fetch_rss(conn, sid, surl)
                    elif stype == 'web':
                        count = self._fetch_web(conn, sid, surl)
                    else:
                        count = 0

                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("""
                        UPDATE news_sources SET last_fetched = ?, fetch_count = fetch_count + 1
                        WHERE id = ?
                    """, (now, sid))
                    total_new += count
                    lines.append(f"  [OK] {sname}: {count} neue Artikel")
                except Exception as e:
                    total_errors += 1
                    error_msg = str(e)[:100]
                    conn.execute("""
                        UPDATE news_sources SET error_count = error_count + 1, last_error = ?
                        WHERE id = ?
                    """, (error_msg, sid))
                    lines.append(f"  [FAIL] {sname}: {error_msg}")

            conn.commit()
            lines.append(f"\nGesamt: {total_new} neue Artikel, {total_errors} Fehler")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _fetch_rss(self, conn, source_id: int, url: str) -> int:
        """Ruft RSS-Feed ab und speichert neue Items."""
        try:
            import feedparser
        except ImportError:
            raise RuntimeError("feedparser nicht installiert. Bitte: pip install feedparser")

        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            raise RuntimeError(f"RSS-Fehler: {feed.bozo_exception}")

        count = 0
        category = conn.execute(
            "SELECT category FROM news_sources WHERE id = ?", (source_id,)
        ).fetchone()
        cat = category[0] if category else "allgemein"

        for entry in feed.entries:
            title = entry.get('title', 'Ohne Titel')
            link = entry.get('link', '')
            summary = entry.get('summary', entry.get('description', ''))
            author = entry.get('author', '')
            published = entry.get('published', entry.get('updated', ''))

            # HTML-Tags entfernen aus Summary
            if summary:
                import re
                summary = re.sub(r'<[^>]+>', '', summary)[:500]

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO news_items
                        (source_id, title, content, summary, url, author, published_at, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (source_id, title, summary, summary[:200], link, author, published, cat))
                if conn.total_changes:
                    count += 1
            except sqlite3.IntegrityError:
                pass  # Duplikat

        return count

    def _fetch_web(self, conn, source_id: int, url: str) -> int:
        """Einfacher Web-Fetch: Titel der Seite als News-Item."""
        import urllib.request
        import re

        req = urllib.request.Request(url, headers={'User-Agent': 'BACH-News/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')[:10000]

        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else url

        category = conn.execute(
            "SELECT category FROM news_sources WHERE id = ?", (source_id,)
        ).fetchone()
        cat = category[0] if category else "allgemein"

        try:
            conn.execute("""
                INSERT OR IGNORE INTO news_items
                    (source_id, title, url, category)
                VALUES (?, ?, ?, ?)
            """, (source_id, title, url, cat))
            return 1
        except sqlite3.IntegrityError:
            return 0

    def _items(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        unread_only = False
        category = None
        limit = 20

        i = 0
        while i < len(args):
            if args[i] == "--unread":
                unread_only = True
                i += 1
            elif args[i] == "--category" and i + 1 < len(args):
                category = args[i + 1]
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            else:
                i += 1

        conn = sqlite3.connect(str(self.db_path))
        try:
            query = """
                SELECT ni.id, ni.title, ni.url, ni.published_at, ni.is_read,
                       ni.category, ns.name as source_name
                FROM news_items ni
                JOIN news_sources ns ON ni.source_id = ns.id
                WHERE 1=1
            """
            params = []
            if unread_only:
                query += " AND ni.is_read = 0"
            if category:
                query += " AND ni.category = ?"
                params.append(category)
            query += " ORDER BY ni.fetched_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "Keine News-Items gefunden."

            filter_info = []
            if unread_only:
                filter_info.append("ungelesen")
            if category:
                filter_info.append(f"Kategorie: {category}")
            filter_str = f" ({', '.join(filter_info)})" if filter_info else ""

            lines = [f"News-Items ({len(rows)}{filter_str})", "=" * 60]
            for r in rows:
                read_marker = " " if r[4] else "*"
                pub = r[3][:10] if r[3] else "?"
                lines.append(f"  {read_marker} #{r[0]} [{r[5]}] {r[1][:55]}")
                lines.append(f"       {r[6]} | {pub} | {r[2][:60] if r[2] else '-'}")

            lines.append(f"\n* = ungelesen | Markieren: bach news read <id|all>")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _read(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: news read <id|all>"

        if dry_run:
            return True, f"[DRY] Wuerde Items als gelesen markieren"

        conn = sqlite3.connect(str(self.db_path))
        try:
            if args[0].lower() == "all":
                cursor = conn.execute("UPDATE news_items SET is_read = 1 WHERE is_read = 0")
                conn.commit()
                return True, f"[OK] {cursor.rowcount} Items als gelesen markiert"
            else:
                item_id = int(args[0])
                conn.execute("UPDATE news_items SET is_read = 1 WHERE id = ?", (item_id,))
                conn.commit()
                return True, f"[OK] Item #{item_id} als gelesen markiert"
        finally:
            conn.close()

    def _remove(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: news remove <id>"

        source_id = int(args[0])
        if dry_run:
            return True, f"[DRY] Wuerde Quelle #{source_id} entfernen"

        conn = sqlite3.connect(str(self.db_path))
        try:
            # Erst Items loeschen, dann Quelle
            conn.execute("DELETE FROM news_items WHERE source_id = ?", (source_id,))
            cursor = conn.execute("DELETE FROM news_sources WHERE id = ?", (source_id,))
            conn.commit()
            if cursor.rowcount > 0:
                return True, f"[OK] Quelle #{source_id} und zugehoerige Items entfernt"
            return False, f"Quelle #{source_id} nicht gefunden."
        finally:
            conn.close()

    def _categories(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT category, COUNT(*) as cnt,
                       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active
                FROM news_sources
                GROUP BY category ORDER BY category
            """).fetchall()

            if not rows:
                return True, "Keine Kategorien vorhanden."

            lines = ["News-Kategorien", "=" * 40]
            for r in rows:
                lines.append(f"  {r[0]}: {r[1]} Quellen ({r[2]} aktiv)")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _stats(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            sources = conn.execute("SELECT COUNT(*) FROM news_sources").fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM news_sources WHERE is_active = 1").fetchone()[0]
            items = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
            unread = conn.execute("SELECT COUNT(*) FROM news_items WHERE is_read = 0").fetchone()[0]
            cats = conn.execute("SELECT COUNT(DISTINCT category) FROM news_sources").fetchone()[0]

            lines = [
                "News-Statistiken", "=" * 40,
                f"  Quellen:     {sources} ({active} aktiv)",
                f"  Kategorien:  {cats}",
                f"  Artikel:     {items} ({unread} ungelesen)",
            ]

            # Letzte Fetches
            recent = conn.execute("""
                SELECT name, last_fetched FROM news_sources
                WHERE last_fetched IS NOT NULL
                ORDER BY last_fetched DESC LIMIT 3
            """).fetchall()
            if recent:
                lines.append(f"\n  Letzte Abrufe:")
                for r in recent:
                    lines.append(f"    {r[0]}: {r[1]}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = [
            "News-Aggregation", "=" * 50, "",
            "Sammelt News aus RSS, Web und YouTube.",
            "",
            "Quellen hinzufuegen:",
            "  bach news add https://example.com/feed.xml",
            "  bach news add https://example.com --type web --category technik",
            "  bach news add https://youtube.com/channel/UC... --name 'Kanal'",
            "",
            "Typ-Erkennung: /feed, /rss, .xml -> RSS, youtube.com -> YouTube, sonst Web",
            "",
            "News abrufen:",
            "  bach news fetch                  Alle aktiven Quellen",
            "  bach news fetch --source 3       Nur Quelle #3",
            "",
            "News lesen:",
            "  bach news items                  Alle neuesten",
            "  bach news items --unread          Nur ungelesene",
            "  bach news items --category technik  Nach Kategorie",
            "  bach news read 42                 Item als gelesen markieren",
            "  bach news read all                Alle als gelesen",
            "",
            "Verwaltung:",
            "  bach news list                   Quellen anzeigen",
            "  bach news remove 3               Quelle entfernen",
            "  bach news categories             Kategorien-Uebersicht",
            "  bach news stats                  Statistiken",
        ]
        return True, "\n".join(lines)
