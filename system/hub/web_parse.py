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
WebParseHandler - Webseiten-Parsing (ersetzt Jina Reader MCP)
==============================================================
bach web-parse url <url>              URL laden, als Markdown ausgeben
bach web-parse clean <url>            Nur Hauptinhalt (trafilatura)
bach web-parse url <url> --offset N   Ab Zeichen N weiterlesen
bach web-parse url <url> --chunk N    Chunk-Groesse (default: 10000)
bach web-parse cache list             Gecachte Seiten anzeigen
bach web-parse cache clear            Cache leeren

Task: 994
"""
import os
import re
import sys
import hashlib
import json
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from .base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("KnowledgeDigest")
class WebParseHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.cache_dir = self.base_path / "data" / "cache" / "web"

    @property
    def profile_name(self) -> str:
        return "web-parse"

    @property
    def target_file(self) -> Path:
        return self.cache_dir

    # Cache-TTL: 24 Stunden
    CACHE_TTL_SECONDS = 24 * 60 * 60
    # Standard-Chunk-Groesse fuer Ausgabe
    DEFAULT_CHUNK_SIZE = 10000

    def get_operations(self) -> dict:
        return {
            "url": "URL laden und als Markdown: url <url> [--offset N] [--chunk N]",
            "clean": "Nur Hauptinhalt (trafilatura): clean <url> [--offset N] [--chunk N]",
            "cache": "Cache verwalten: cache list|clear",
        }

    def _parse_args_flags(self, args: List[str]) -> Tuple[str, int, int]:
        """Extrahiert URL, --offset und --chunk aus args."""
        url = ""
        offset = 0
        chunk = self.DEFAULT_CHUNK_SIZE
        i = 0
        while i < len(args):
            if args[i] == "--offset" and i + 1 < len(args):
                offset = int(args[i + 1])
                i += 2
            elif args[i] == "--chunk" and i + 1 < len(args):
                chunk = int(args[i + 1])
                i += 2
            elif not url:
                url = args[i]
                i += 1
            else:
                i += 1
        return url, offset, chunk

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation in ("url", "clean") and args:
            url, offset, chunk = self._parse_args_flags(args)
            if not url:
                return False, f"URL fehlt: bach web-parse {operation} <url>"
            if dry_run:
                return True, f"[DRY-RUN] Wuerde {url} {'clean ' if operation == 'clean' else ''}laden"
            return self._parse_url(url, clean=(operation == "clean"), offset=offset, chunk_size=chunk)
        elif operation == "cache":
            sub = args[0] if args else "list"
            if sub == "list":
                return self._cache_list()
            elif sub == "clear":
                if dry_run:
                    return True, "[DRY-RUN] Cache wuerde geleert"
                return self._cache_clear()
            return False, f"Unbekannt: cache {sub}. Nutze: list, clear"
        else:
            ops = "\n".join(f"  {k}: {v}" for k, v in self.get_operations().items())
            return False, f"Nutzung:\n{ops}"

    def _fetch(self, url: str) -> Tuple[bool, str, str]:
        """Laedt URL herunter. Returns (success, content, error)."""
        try:
            import requests
        except ImportError:
            return False, "", "requests nicht installiert: pip install requests"

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (BACH WebParse/1.0)',
                'Accept': 'text/html,application/xhtml+xml,*/*',
            }
            try:
                resp = requests.get(url, timeout=20, headers=headers, allow_redirects=True)
            except requests.exceptions.SSLError:
                # Fallback bei SSL-Zertifikatsproblemen (Windows Store Python)
                resp = requests.get(url, timeout=20, headers=headers, allow_redirects=True, verify=False)
            resp.raise_for_status()
            return True, resp.text, ""
        except Exception as e:
            return False, "", str(e)

    def _html_to_markdown(self, html: str, clean: bool = False, url: str = "") -> str:
        """Konvertiert HTML zu Markdown. Bei clean=True wird trafilatura bevorzugt."""
        # Bei clean: trafilatura fuer praezise Content-Extraktion
        if clean:
            try:
                import trafilatura
                result = trafilatura.extract(
                    html,
                    include_links=True,
                    include_tables=True,
                    include_comments=False,
                    output_format='txt',
                    url=url or None,
                )
                if result and len(result.strip()) > 100:
                    return result.strip()
                # Fallback wenn trafilatura zu wenig findet
            except ImportError:
                pass

        # html2text fuer volle Konvertierung
        try:
            import html2text
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            h.body_width = 0
            return h.handle(html).strip()
        except ImportError:
            pass

        # Fallback: Regex-basiert
        text = html
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)

        if clean:
            for tag in ['nav', 'header', 'footer', 'aside']:
                text = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.DOTALL | re.IGNORECASE)

        for i in range(1, 7):
            text = re.sub(rf'<h{i}[^>]*>(.*?)</h{i}>', lambda m: f"\n{'#' * i} {m.group(1).strip()}\n", text, flags=re.IGNORECASE)

        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.IGNORECASE)
        text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', text, flags=re.IGNORECASE)
        text = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', text, flags=re.IGNORECASE)
        text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.IGNORECASE)
        text = re.sub(r'<pre[^>]*>(.*?)</pre>', lambda m: f"\n```\n{m.group(1)}\n```\n", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&nbsp;', ' ')
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _is_cache_valid(self, cache_file: Path) -> bool:
        """Prueft ob Cache-Datei existiert und nicht aelter als TTL ist."""
        if not cache_file.exists():
            return False
        age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds()
        return age < self.CACHE_TTL_SECONDS

    def _parse_url(self, url: str, clean: bool = False, offset: int = 0, chunk_size: int = 0) -> Tuple[bool, str]:
        """Parst URL und gibt Markdown zurueck (mit Chunking-Support)."""
        if chunk_size <= 0:
            chunk_size = self.DEFAULT_CHUNK_SIZE

        # Cache pruefen (mit TTL)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        suffix = "_clean" if clean else ""
        cache_file = self.cache_dir / f"{url_hash}{suffix}.md"

        markdown = ""
        from_cache = False

        if self._is_cache_valid(cache_file):
            raw = cache_file.read_text(encoding='utf-8', errors='replace')
            # Meta-Zeile ueberspringen
            if raw.startswith("<!--"):
                idx = raw.find("-->\n")
                markdown = raw[idx + 4:].strip() if idx >= 0 else raw
            else:
                markdown = raw
            from_cache = True
        else:
            # Herunterladen
            ok, html, err = self._fetch(url)
            if not ok:
                return False, f"Fehler: {err}"

            # Konvertieren
            markdown = self._html_to_markdown(html, clean=clean, url=url)

            # Cachen
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            meta = f"<!-- URL: {url} | Parsed: {datetime.now().isoformat()} | Mode: {'clean' if clean else 'full'} -->\n\n"
            cache_file.write_text(meta + markdown, encoding='utf-8')

        # Chunking
        total_len = len(markdown)
        chunk = markdown[offset:offset + chunk_size]
        end_pos = offset + len(chunk)
        has_more = end_pos < total_len

        # Header
        source = "[CACHE] " if from_cache else ""
        lines = [
            f"{source}URL: {url}",
            f"Modus: {'clean (trafilatura)' if clean else 'full'}",
            f"Gesamt: {total_len} Zeichen | Anzeige: {offset}-{end_pos}",
        ]
        if has_more:
            lines.append(f"Weiterlesen: bach web-parse {'clean' if clean else 'url'} {url} --offset {end_pos}")
        lines.append("=" * 40)
        lines.append("")
        lines.append(chunk)

        return True, "\n".join(lines)

    def _cache_list(self) -> Tuple[bool, str]:
        """Zeigt gecachte Seiten."""
        if not self.cache_dir.exists():
            return True, "Cache leer."

        files = list(self.cache_dir.glob("*.md"))
        if not files:
            return True, "Cache leer."

        lines = [f"WEB-PARSE CACHE ({len(files)} Dateien, TTL: {self.CACHE_TTL_SECONDS // 3600}h)", "=" * 35]
        total_size = 0
        expired_count = 0
        for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            size = f.stat().st_size
            total_size += size
            # URL aus Datei extrahieren
            first_line = f.read_text(encoding='utf-8', errors='replace').split('\n')[0]
            url_match = re.search(r'URL: ([^\s|]+)', first_line)
            url = url_match.group(1) if url_match else f.name
            # TTL-Status
            age_h = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600
            expired = age_h > (self.CACHE_TTL_SECONDS / 3600)
            if expired:
                expired_count += 1
            status = "EXPIRED" if expired else f"{age_h:.1f}h"
            lines.append(f"  [{status}] {f.name} ({size // 1024}KB) - {url}")

        lines.append(f"\nGesamt: {total_size // 1024}KB | {expired_count} abgelaufen")
        return True, "\n".join(lines)

    def _cache_clear(self) -> Tuple[bool, str]:
        """Leert den Cache."""
        if not self.cache_dir.exists():
            return True, "Cache bereits leer."

        count = 0
        for f in self.cache_dir.glob("*.md"):
            f.unlink()
            count += 1

        return True, f"Cache geleert: {count} Dateien entfernt."
