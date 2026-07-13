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
Newspaper Generator - Taegliche PDF-Zeitung aus News-Items
============================================================
Liest ungelesene news_items aus der DB, gruppiert nach Kategorie,
generiert HTML und konvertiert zu PDF via Edge Headless.
"""

import os
import sys
import json
import sqlite3
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, date

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

NEWSPAPER_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = NEWSPAPER_DIR / "templates"
CONFIG_FILE = NEWSPAPER_DIR / "config.json"

# BACH-Pfade
SERVICES_DIR = NEWSPAPER_DIR.parent
HUB_DIR = SERVICES_DIR.parent
BACH_DIR = HUB_DIR.parent


def load_config() -> dict:
    """Laedt Newspaper-Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "title": "BACH Daily News",
        "categories": ["politik", "technik", "wissenschaft", "allgemein"],
        "max_items_per_category": 10,
        "delivery": {
            "desktop_copy": True,
            "desktop_path": str(Path.home() / "Desktop"),
            "email": False,
            "telegram": True,
        }
    }


def generate_newspaper(target_date: str = None, config: dict = None) -> dict:
    """Generiert eine Zeitung aus News-Items.

    Args:
        target_date: Datum im Format YYYY-MM-DD (Default: heute)
        config: Optionale Konfiguration

    Returns:
        dict mit 'html_path', 'pdf_path', 'article_count', 'categories'
    """
    if config is None:
        config = load_config()

    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    db_path = Path.home() / ".bach" / "bach.db"
    if not db_path.exists():
        db_path = BACH_DB
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # News-Items nach Kategorie gruppiert laden
        items = conn.execute("""
            SELECT ni.id, ni.title, ni.summary, ni.url, ni.author,
                   ni.published_at, ni.category, ns.name as source_name
            FROM news_items ni
            JOIN news_sources ns ON ni.source_id = ns.id
            WHERE ni.is_read = 0
            ORDER BY ni.category, ni.fetched_at DESC
        """).fetchall()

        if not items:
            return {"error": "Keine ungelesenen News-Items vorhanden."}

        # Nach Kategorie gruppieren
        max_per_cat = config.get("max_items_per_category", 10)
        categories = {}
        for item in items:
            cat = item["category"] or "allgemein"
            if cat not in categories:
                categories[cat] = []
            if len(categories[cat]) < max_per_cat:
                categories[cat].append(dict(item))

        # HTML generieren
        html_content = _render_html(categories, target_date, config)

        # Dateien speichern
        output_dir = BACH_DIR / "user" / "newspaper"
        output_dir.mkdir(parents=True, exist_ok=True)

        html_filename = f"newspaper_{target_date}.html"
        html_path = output_dir / html_filename
        html_path.write_text(html_content, encoding='utf-8')

        # PDF generieren via Edge Headless
        pdf_path = output_dir / f"newspaper_{target_date}.pdf"
        pdf_success = _html_to_pdf(str(html_path), str(pdf_path))

        total_articles = sum(len(v) for v in categories.values())

        result = {
            "html_path": str(html_path),
            "pdf_path": str(pdf_path) if pdf_success else None,
            "article_count": total_articles,
            "categories": list(categories.keys()),
            "date": target_date,
        }

        return result

    finally:
        conn.close()


def deliver_newspaper(result: dict, config: dict = None) -> list:
    """Liefert die Zeitung ueber konfigurierte Kanaele aus.

    Returns:
        Liste von (channel, success, message) Tupeln
    """
    if config is None:
        config = load_config()

    delivery_config = config.get("delivery", {})
    deliveries = []

    # Desktop-Kopie
    if delivery_config.get("desktop_copy", True):
        desktop_path = delivery_config.get("desktop_path", str(Path.home() / "Desktop"))
        pdf_path = result.get("pdf_path") or result.get("html_path")
        if pdf_path and Path(pdf_path).exists():
            try:
                dest = Path(desktop_path) / Path(pdf_path).name
                shutil.copy2(pdf_path, str(dest))
                deliveries.append(("desktop", True, f"Kopiert nach {dest}"))
            except Exception as e:
                deliveries.append(("desktop", False, str(e)))

    # Telegram
    if delivery_config.get("telegram", False):
        try:
            sys.path.insert(0, str(BACH_DIR))
            from hub.notify import NotifyHandler
            notifier = NotifyHandler(BACH_DIR)
            title = config.get("title", "BACH Daily News")
            count = result.get("article_count", 0)
            cats = ", ".join(result.get("categories", []))
            msg = f"{title} ({result.get('date', 'heute')})\n{count} Artikel in: {cats}"
            success, response = notifier._send(["telegram", msg], False)
            deliveries.append(("telegram", success, response))
        except Exception as e:
            deliveries.append(("telegram", False, str(e)))

    return deliveries


def _render_html(categories: dict, target_date: str, config: dict) -> str:
    """Rendert HTML aus Template und News-Items."""
    template_file = TEMPLATES_DIR / "newspaper.html"
    if not template_file.exists():
        # Fallback: Einfaches HTML
        return _render_simple_html(categories, target_date, config)

    template = template_file.read_text(encoding='utf-8')

    # Content-Bloecke generieren
    content_parts = []
    for cat_name, items in categories.items():
        section = f'<div class="category">\n'
        section += f'    <h2>{cat_name.upper()}</h2>\n'
        for item in items:
            title = _html_escape(item.get("title", "Ohne Titel"))
            summary = _html_escape(item.get("summary", ""))[:300]
            source = _html_escape(item.get("source_name", ""))
            author = _html_escape(item.get("author", ""))
            published = item.get("published_at", "")[:10] if item.get("published_at") else ""
            url = item.get("url", "")

            meta_parts = []
            if source:
                meta_parts.append(source)
            if author:
                meta_parts.append(author)
            if published:
                meta_parts.append(published)
            meta_str = " | ".join(meta_parts)

            section += f'    <div class="article">\n'
            section += f'        <h3>{title}</h3>\n'
            if meta_str:
                section += f'        <div class="meta">{meta_str}</div>\n'
            if summary:
                section += f'        <div class="summary">{summary}</div>\n'
            if url:
                section += f'        <a href="{url}">Weiterlesen &rarr;</a>\n'
            section += f'    </div>\n'
        section += f'</div>\n'
        content_parts.append(section)

    content = "\n".join(content_parts)

    # Platzhalter ersetzen
    now = datetime.now()
    try:
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        date_long = date_obj.strftime("%d. %B %Y")
    except Exception:
        date_long = target_date

    total_articles = sum(len(v) for v in categories.values())

    replacements = {
        "{{TITLE}}": config.get("title", "BACH Daily News"),
        "{{DATE}}": target_date,
        "{{DATE_LONG}}": date_long,
        "{{EDITION}}": target_date.replace("-", ""),
        "{{ARTICLE_COUNT}}": str(total_articles),
        "{{CATEGORY_COUNT}}": str(len(categories)),
        "{{CONTENT}}": content,
        "{{GENERATED_AT}}": now.strftime("%H:%M Uhr"),
        "{{YEAR}}": str(now.year),
    }

    html = template
    for key, value in replacements.items():
        html = html.replace(key, value)

    return html


def _render_simple_html(categories: dict, target_date: str, config: dict) -> str:
    """Fallback: Einfaches HTML ohne Template."""
    title = config.get("title", "BACH Daily News")
    parts = [f"<html><head><title>{title}</title></head><body>"]
    parts.append(f"<h1>{title} - {target_date}</h1>")

    for cat_name, items in categories.items():
        parts.append(f"<h2>{cat_name}</h2>")
        for item in items:
            parts.append(f"<p><b>{_html_escape(item.get('title', ''))}</b><br>")
            if item.get("summary"):
                parts.append(f"{_html_escape(item['summary'][:200])}<br>")
            if item.get("url"):
                parts.append(f'<a href="{item["url"]}">Link</a>')
            parts.append("</p>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _html_escape(text: str) -> str:
    """Einfaches HTML-Escaping."""
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _html_to_pdf(html_path: str, pdf_path: str) -> bool:
    """Konvertiert HTML zu PDF via Edge Headless."""
    # Edge-Pfade
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge = None
    for p in edge_paths:
        if Path(p).exists():
            edge = p
            break

    if not edge:
        return False

    creation_flags = 0x08000000 if sys.platform == 'win32' else 0

    try:
        result = subprocess.run(
            [edge, "--headless", "--disable-gpu",
             f"--print-to-pdf={pdf_path}",
             f"file:///{html_path.replace(os.sep, '/')}"],
            capture_output=True, timeout=30,
            creationflags=creation_flags,
        )
        return Path(pdf_path).exists()
    except Exception:
        return False
