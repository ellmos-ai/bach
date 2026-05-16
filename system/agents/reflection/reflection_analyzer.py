#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
Tool: reflection_analyzer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-08
Updated: 2026-02-08
Anthropic-Compatible: True

VERSIONS-HINWEIS: Pruefen auf neuere Versionen mit: bach tools version reflection_analyzer

Description:
    Selbstreflexions-Modul fuer BACH. Analysiert Session-Performance,
    Erfolgsraten und identifiziert Verbesserungspotentiale.
    Portiert aus BachForelle/skills/reflection/analyze.py.
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


class SelfReflection:
    """Meta-kognitive Selbstreflexion fuer BACH."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def log_metric(self, task: str, latency_ms: int, success: bool,
                   details: str = "") -> None:
        """Metrik loggen fuer spaetere Analyse."""
        conn = self._get_db()
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO memory_working (type, content, priority, tags, created_at, is_active)
                VALUES ('note', ?, ?, ?, ?, 1)
            """, (
                f"REFLECTION: {task} | {'OK' if success else 'FAIL'} | {latency_ms}ms | {details}",
                1 if not success else 0,
                f'["reflection", "metric", "{"success" if success else "error"}"]',
                now
            ))
            conn.commit()
        finally:
            conn.close()

    def review_performance(self, days: int = 7) -> Dict:
        """Performance der letzten N Tage analysieren."""
        conn = self._get_db()
        try:
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            # Task-Statistiken
            total_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE created_at >= ?", (since,)
            ).fetchone()[0]

            done_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'done' AND completed_at >= ?",
                (since,)
            ).fetchone()[0]

            # Session-Statistiken
            sessions = conn.execute(
                "SELECT COUNT(*) FROM memory_sessions WHERE started_at >= ?",
                (since,)
            ).fetchone()[0]

            # Reflection-Metriken aus Working Memory
            metrics = conn.execute("""
                SELECT content FROM memory_working
                WHERE type = 'note' AND content LIKE 'REFLECTION:%'
                AND created_at >= ?
            """, (since,)).fetchall()

            success_count = sum(1 for m in metrics if "| OK |" in m["content"])
            error_count = sum(1 for m in metrics if "| FAIL |" in m["content"])
            total_metrics = success_count + error_count

            # Lessons gelernt
            lessons = conn.execute(
                "SELECT COUNT(*) FROM memory_lessons WHERE created_at >= ?",
                (since,)
            ).fetchone()[0]

            success_rate = (success_count / total_metrics * 100) if total_metrics > 0 else 0
            task_rate = (done_tasks / total_tasks * 100) if total_tasks > 0 else 0

            return {
                "period_days": days,
                "total_tasks": total_tasks,
                "done_tasks": done_tasks,
                "task_completion_rate": round(task_rate, 1),
                "sessions": sessions,
                "metrics_logged": total_metrics,
                "success_count": success_count,
                "error_count": error_count,
                "success_rate": round(success_rate, 1),
                "lessons_learned": lessons,
            }
        finally:
            conn.close()

    def identify_gaps(self) -> List[str]:
        """Schwachstellen identifizieren."""
        gaps = []
        perf = self.review_performance(days=14)

        if perf["task_completion_rate"] < 50:
            gaps.append(
                f"Niedrige Task-Abschlussrate ({perf['task_completion_rate']}%). "
                f"Moeglicherweise zu viele offene Tasks oder unklare Priorisierung."
            )

        if perf["success_rate"] < 80 and perf["metrics_logged"] > 5:
            gaps.append(
                f"Erfolgsrate unter 80% ({perf['success_rate']}%). "
                f"Fehleranalyse empfohlen."
            )

        if perf["sessions"] == 0:
            gaps.append("Keine Sessions in den letzten 14 Tagen. System inaktiv?")

        if perf["lessons_learned"] == 0 and perf["sessions"] > 3:
            gaps.append(
                "Keine neuen Lessons bei mehreren Sessions. "
                "Lernprozess pruefen."
            )

        conn = self._get_db()
        try:
            # Lange offene Tasks
            old_tasks = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE status = 'pending'
                AND created_at < datetime('now', '-30 days')
            """).fetchone()[0]
            if old_tasks > 5:
                gaps.append(
                    f"{old_tasks} Tasks seit ueber 30 Tagen offen. "
                    f"Review und Bereinigung empfohlen."
                )

            # Unbenutzte Fakten
            uncertain = conn.execute("""
                SELECT COUNT(*) FROM memory_facts WHERE confidence < 0.5
            """).fetchone()[0]
            if uncertain > 10:
                gaps.append(
                    f"{uncertain} unsichere Fakten (confidence < 0.5). "
                    f"Validierung empfohlen."
                )
        finally:
            conn.close()

        if not gaps:
            gaps.append("Keine signifikanten Schwachstellen identifiziert.")

        return gaps

    def format_report(self) -> str:
        """Formatierten Performance-Bericht erstellen."""
        perf = self.review_performance()
        gaps = self.identify_gaps()

        lines = [
            "SELF-REFLECTION REPORT",
            "=" * 50,
            f"  Zeitraum: Letzte {perf['period_days']} Tage",
            "",
            "  TASKS:",
            f"    Erstellt:    {perf['total_tasks']}",
            f"    Abgeschl.:   {perf['done_tasks']}",
            f"    Rate:        {perf['task_completion_rate']}%",
            "",
            "  SESSIONS:",
            f"    Anzahl:      {perf['sessions']}",
            "",
            "  METRIKEN:",
            f"    Erfasst:     {perf['metrics_logged']}",
            f"    Erfolgreich: {perf['success_count']}",
            f"    Fehler:      {perf['error_count']}",
            f"    Erfolgsrate: {perf['success_rate']}%",
            "",
            f"  LERNEN:",
            f"    Neue Lessons: {perf['lessons_learned']}",
            "",
            "  GAPS / VERBESSERUNGEN:",
        ]

        for i, gap in enumerate(gaps, 1):
            lines.append(f"    {i}. {gap}")

        return "\n".join(lines)


def main():
    """CLI-Aufruf."""
    import sys
    try:
        from hub.bach_paths import BACH_DB
        db_path = str(BACH_DB)
    except ImportError:
        db_path = str(Path(__file__).parent.parent.parent.parent / "data" / "bach.db")
    ref = SelfReflection(db_path)

    if len(sys.argv) > 1 and sys.argv[1] == "gaps":
        for gap in ref.identify_gaps():
            print(f"  - {gap}")
    else:
        print(ref.format_report())


if __name__ == "__main__":
    main()
