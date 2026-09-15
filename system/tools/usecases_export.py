#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
usecases_export.py - USECASES.md Generator
==========================================

Generiert USECASES.md aus usecases Tabelle.

Teil von SQ071: Spiegel-Dateien Auto-Export
"""

from pathlib import Path
from datetime import datetime
import sqlite3


class UsecasesExporter:
    """Generiert USECASES.md aus DB."""

    def __init__(self, bach_root: Path, *, db_path: Path | None = None):
        self.bach_root = Path(bach_root)

        # Auto-Detect: Root vs. system/ Installation
        if (self.bach_root / "system").exists():
            self.system_root = self.bach_root / "system"
        else:
            self.system_root = self.bach_root
            self.bach_root = self.system_root.parent

        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            from hub.bach_paths import BACH_DB

            self.db_path = Path(BACH_DB)
        self.output_path = self.bach_root / "USECASES.md"

    def generate(self) -> tuple[bool, str]:
        """Generiert USECASES.md aus DB."""
        if not self._check_table():
            return False, "✗ Tabelle usecases nicht gefunden"

        usecases = self._get_usecases()
        content = self._build_content(usecases)

        self.output_path.write_text(content, encoding='utf-8')
        return True, f"✓ USECASES.md generiert: {self.output_path}"

    def _check_table(self) -> bool:
        """Prüft ob usecases existiert."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='usecases'
        """)
        count = cursor.fetchone()[0]
        conn.close()
        return count == 1

    def _get_usecases(self) -> list[dict]:
        """Hole alle Usecases aus DB."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT title, description, workflow_path, workflow_name, test_result, test_score, last_tested
            FROM usecases
            ORDER BY test_score DESC, title
        """)

        usecases = []
        for row in cursor.fetchall():
            usecases.append({
                'title': row[0] or 'Unbenannt',
                'description': row[1] or '',
                'workflow_path': row[2] or '',
                'workflow_name': row[3] or '',
                'test_result': row[4] or '',
                'test_score': row[5] or 0,
                'last_tested': row[6] or ''
            })

        conn.close()
        return usecases

    def _build_content(self, usecases: list[dict]) -> str:
        """Baut USECASES.md Content."""
        lines = []
        lines.append("# BACH Usecases")
        lines.append("")
        lines.append("Automatisch generiert aus der Datenbank (usecases).")
        lines.append(f"Letzte Aktualisierung: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(f"**Total:** {len(usecases)} Usecases")
        lines.append("")

        # Gruppiere nach Workflow (wenn vorhanden)
        by_workflow = {}
        no_workflow = []

        for uc in usecases:
            wf = uc['workflow_name'] or uc['workflow_path']
            if wf:
                if wf not in by_workflow:
                    by_workflow[wf] = []
                by_workflow[wf].append(uc)
            else:
                no_workflow.append(uc)

        # Ausgabe pro Workflow
        for workflow in sorted(by_workflow.keys()):
            lines.append(f"## {workflow}")
            lines.append("")

            for uc in by_workflow[workflow]:
                status = "✓" if uc['test_result'] == 'passed' else ("✗" if uc['test_result'] == 'failed' else "○")
                score_stars = "⭐" * min(uc['test_score'] // 20, 5)

                lines.append(f"### {status} {uc['title']} {score_stars}")
                if uc['description']:
                    lines.append("")
                    lines.append(uc['description'])

                if uc['last_tested']:
                    lines.append("")
                    lines.append(f"**Letzter Test:** {uc['last_tested']} | **Score:** {uc['test_score']}/100")

                lines.append("")

        # Usecases ohne Workflow
        if no_workflow:
            lines.append("## Weitere Usecases")
            lines.append("")

            for uc in no_workflow:
                status = "✓" if uc['test_result'] == 'passed' else ("✗" if uc['test_result'] == 'failed' else "○")
                score_stars = "⭐" * min(uc['test_score'] // 20, 5)

                lines.append(f"### {status} {uc['title']} {score_stars}")
                if uc['description']:
                    lines.append("")
                    lines.append(uc['description'])

                if uc['last_tested']:
                    lines.append("")
                    lines.append(f"**Letzter Test:** {uc['last_tested']} | **Score:** {uc['test_score']}/100")

                lines.append("")

        return "\n".join(lines)
