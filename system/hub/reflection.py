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
ReflectionHandler - Selbstreflexion und Performance-Analyse
============================================================

Operationen:
  status            Performance-Bericht anzeigen
  review [days]     Performance der letzten N Tage
  gaps              Schwachstellen identifizieren
  log               Reflection-Metriken anzeigen

Nutzt: bach.db / tasks, memory_working, memory_sessions, memory_lessons, memory_facts
"""

import sys
from pathlib import Path
from typing import List, Tuple
from hub.base import BaseHandler

sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "reflection"))


class ReflectionHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "reflection"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "Performance-Bericht",
            "review": "Performance analysieren: review [days]",
            "gaps": "Schwachstellen identifizieren",
            "log": "Reflection-Metriken anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "status": self._status,
            "review": self._review,
            "gaps": self._gaps,
            "log": self._log,
        }

        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"

        return fn(args, dry_run)

    def _get_analyzer(self):
        from reflection_analyzer import SelfReflection
        return SelfReflection(str(self.db_path))

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        ref = self._get_analyzer()
        return True, ref.format_report()

    def _review(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        days = int(args[0]) if args else 7
        ref = self._get_analyzer()
        perf = ref.review_performance(days=days)

        lines = [f"Performance Review ({days} Tage)", "=" * 40]
        for k, v in perf.items():
            label = k.replace("_", " ").title()
            lines.append(f"  {label}: {v}")
        return True, "\n".join(lines)

    def _gaps(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        ref = self._get_analyzer()
        gaps = ref.identify_gaps()

        lines = ["Identifizierte Schwachstellen", "=" * 40]
        for i, gap in enumerate(gaps, 1):
            lines.append(f"  {i}. {gap}")
        return True, "\n".join(lines)

    def _log(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT content, created_at FROM memory_working
                WHERE type = 'note' AND content LIKE 'REFLECTION:%'
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()

            if not rows:
                return True, "Keine Reflection-Metriken vorhanden."

            lines = [f"Reflection-Metriken ({len(rows)})", "=" * 40]
            for content, ts in rows:
                lines.append(f"  {ts} {content[12:]}")
            return True, "\n".join(lines)
        finally:
            conn.close()
