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
NewspaperHandler - Taegliche PDF-Zeitung
==========================================

Operationen:
  generate [--date YYYY-MM-DD]                    Zeitung generieren
  deliver [--channel telegram|email|desktop]      Zeitung zustellen
  config                                          Konfiguration anzeigen
  history                                         Bisherige Ausgaben
  help                                            Hilfe

Nutzt: bach.db / news_items, news_sources
Abhaengig von: NewsHandler (hub/news.py)
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, date
from typing import List, Tuple
from hub.base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class NewspaperHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self.newspaper_dir = self.base_path / "hub" / "_services" / "newspaper"

    @property
    def profile_name(self) -> str:
        return "newspaper"

    @property
    def target_file(self) -> Path:
        return self.newspaper_dir

    def get_operations(self) -> dict:
        return {
            "generate": "Zeitung generieren: generate [--date YYYY-MM-DD]",
            "deliver": "Zeitung zustellen: deliver [--channel telegram|email|desktop]",
            "config": "Konfiguration anzeigen",
            "history": "Bisherige Ausgaben anzeigen",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "generate": self._generate,
            "deliver": self._deliver,
            "config": self._config,
            "history": self._history,
            "help": self._help,
        }
        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"
        return fn(args, dry_run)

    def _load_generator(self):
        """Lazy-Import des Newspaper-Generators."""
        sys.path.insert(0, str(self.base_path))
        from hub._services.newspaper.newspaper_generator import (
            generate_newspaper, deliver_newspaper, load_config
        )
        return generate_newspaper, deliver_newspaper, load_config

    def _generate(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        target_date = None
        i = 0
        while i < len(args):
            if args[i] == "--date" and i + 1 < len(args):
                target_date = args[i + 1]
                i += 2
            else:
                i += 1

        if dry_run:
            return True, f"[DRY] Wuerde Zeitung generieren fuer {target_date or 'heute'}"

        try:
            generate_newspaper, deliver_newspaper, load_config = self._load_generator()
            config = load_config()
            result = generate_newspaper(target_date=target_date, config=config)

            if "error" in result:
                return False, result["error"]

            lines = [
                "Zeitung generiert!", "=" * 50,
                f"  Datum:       {result.get('date', '?')}",
                f"  Artikel:     {result.get('article_count', 0)}",
                f"  Kategorien:  {', '.join(result.get('categories', []))}",
                f"  HTML:        {result.get('html_path', '-')}",
                f"  PDF:         {result.get('pdf_path', 'nicht verfuegbar')}",
            ]
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Generierung fehlgeschlagen: {e}"

    def _deliver(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        channel_filter = None
        i = 0
        while i < len(args):
            if args[i] == "--channel" and i + 1 < len(args):
                channel_filter = args[i + 1]
                i += 2
            else:
                i += 1

        if dry_run:
            return True, f"[DRY] Wuerde Zeitung zustellen (Channel: {channel_filter or 'alle'})"

        try:
            generate_newspaper, deliver_newspaper, load_config = self._load_generator()
            config = load_config()

            # Neueste Zeitung finden
            output_dir = self.base_path / "user" / "newspaper"
            if not output_dir.exists():
                return False, "Keine Zeitung vorhanden. Zuerst: bach newspaper generate"

            # Neueste PDF/HTML finden
            files = sorted(output_dir.glob("newspaper_*"), reverse=True)
            if not files:
                return False, "Keine Zeitung gefunden. Zuerst: bach newspaper generate"

            # Result-Dict simulieren
            latest = files[0]
            result = {
                "html_path": str(latest) if latest.suffix == '.html' else None,
                "pdf_path": str(latest) if latest.suffix == '.pdf' else str(latest),
                "date": date.today().strftime("%Y-%m-%d"),
                "article_count": 0,
                "categories": [],
            }

            deliveries = deliver_newspaper(result, config)

            lines = ["Zustellung", "=" * 40]
            for channel, success, msg in deliveries:
                if channel_filter and channel != channel_filter:
                    continue
                status = "OK" if success else "FAIL"
                lines.append(f"  [{status}] {channel}: {msg}")

            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Zustellung fehlgeschlagen: {e}"

    def _config(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        config_file = self.newspaper_dir / "config.json"
        try:
            config = json.loads(config_file.read_text(encoding='utf-8'))
        except Exception:
            config = {}

        lines = ["Newspaper-Konfiguration", "=" * 40]
        for k, v in config.items():
            if isinstance(v, dict):
                lines.append(f"  {k}:")
                for kk, vv in v.items():
                    lines.append(f"    {kk}: {vv}")
            elif isinstance(v, list):
                lines.append(f"  {k}: {', '.join(str(x) for x in v)}")
            else:
                lines.append(f"  {k}: {v}")
        return True, "\n".join(lines)

    def _history(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        output_dir = self.base_path / "user" / "newspaper"
        if not output_dir.exists():
            return True, "Keine Ausgaben vorhanden."

        files = sorted(output_dir.glob("newspaper_*"), reverse=True)
        if not files:
            return True, "Keine Ausgaben vorhanden."

        lines = [f"Newspaper-Ausgaben ({len(files)})", "=" * 50]
        for f in files[:20]:
            size = f.stat().st_size
            lines.append(f"  {f.name} ({size // 1024}KB)")
        if len(files) > 20:
            lines.append(f"  ... und {len(files) - 20} weitere")
        return True, "\n".join(lines)

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = [
            "Taegliche PDF-Zeitung", "=" * 50, "",
            "Generiert eine Zeitung aus gesammelten News-Items.",
            "",
            "Generieren:",
            "  bach newspaper generate                Zeitung fuer heute",
            "  bach newspaper generate --date 2026-02-18  Fuer bestimmtes Datum",
            "",
            "Zustellen:",
            "  bach newspaper deliver                 Alle Kanaele",
            "  bach newspaper deliver --channel telegram  Nur Telegram",
            "",
            "Verwaltung:",
            "  bach newspaper config                  Konfiguration anzeigen",
            "  bach newspaper history                 Bisherige Ausgaben",
            "",
            "Workflow: bach news fetch -> bach newspaper generate -> bach newspaper deliver",
            "",
            "Konfiguration: hub/_services/newspaper/config.json",
            "Ausgabeverzeichnis: user/newspaper/",
        ]
        return True, "\n".join(lines)
