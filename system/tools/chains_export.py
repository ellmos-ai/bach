#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
chains_export.py - CHAINS.md Generator
=======================================

Generiert CHAINS.md aus toolchains Tabelle.

Teil von SQ071: Spiegel-Dateien Auto-Export
"""

from pathlib import Path
from datetime import datetime
import sqlite3


class ChainsExporter:
    """Generiert CHAINS.md aus DB."""

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
        self.output_path = self.bach_root / "CHAINS.md"

    def generate(self) -> tuple[bool, str]:
        """Generiert CHAINS.md aus DB."""
        if not self._check_table():
            return False, "✗ Tabelle toolchains nicht gefunden"

        chains = self._get_chains()
        content = self._build_content(chains)

        self.output_path.write_text(content, encoding='utf-8')
        return True, f"✓ CHAINS.md generiert: {self.output_path}"

    def _check_table(self) -> bool:
        """Prüft ob toolchains existiert."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='toolchains'
        """)
        count = cursor.fetchone()[0]
        conn.close()
        return count == 1

    def _get_chains(self) -> list[dict]:
        """Hole alle Toolchains aus DB."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT name, description, trigger_type, trigger_value, steps_json, is_active, last_run
            FROM toolchains
            ORDER BY name
        """)

        chains = []
        for row in cursor.fetchall():
            chains.append({
                'name': row[0] or 'Unbenannt',
                'description': row[1] or '',
                'trigger_type': row[2] or 'manual',
                'trigger_value': row[3] or '',
                'steps_json': row[4] or '[]',
                'is_active': row[5] or 0,
                'last_run': row[6] or ''
            })

        conn.close()
        return chains

    def _build_content(self, chains: list[dict]) -> str:
        """Baut CHAINS.md Content."""
        lines = []
        lines.append("# BACH Toolchains")
        lines.append("")
        lines.append("Automatisch generiert aus der Datenbank (toolchains).")
        lines.append(f"Letzte Aktualisierung: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(f"**Total:** {len(chains)} Toolchains")
        lines.append("")

        # Gruppiere nach Trigger-Type
        by_trigger = {}
        for chain in chains:
            tt = chain['trigger_type']
            if tt not in by_trigger:
                by_trigger[tt] = []
            by_trigger[tt].append(chain)

        # Ausgabe pro Trigger-Type
        for trigger_type in sorted(by_trigger.keys()):
            lines.append(f"## Trigger: {trigger_type}")
            lines.append("")

            for chain in by_trigger[trigger_type]:
                status = "✓" if chain['is_active'] else "○"
                lines.append(f"### {status} {chain['name']}")

                if chain['description']:
                    lines.append("")
                    lines.append(chain['description'])

                if chain['trigger_value']:
                    lines.append("")
                    lines.append(f"**Trigger Value:** {chain['trigger_value']}")

                if chain['last_run']:
                    lines.append("")
                    lines.append(f"**Last Run:** {chain['last_run']}")

                if chain['steps_json'] and chain['steps_json'] != '[]':
                    lines.append("")
                    lines.append("**Steps:**")
                    lines.append("```json")
                    lines.append(chain['steps_json'])
                    lines.append("```")

                lines.append("")

        return "\n".join(lines)
