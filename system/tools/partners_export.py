#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
partners_export.py - PARTNERS.md Generator
==========================================

Generiert PARTNERS.md aus delegation_rules, partner_recognition, interaction_protocols.

Teil von SQ071: Spiegel-Dateien Auto-Export
"""

from pathlib import Path
from datetime import datetime
import sqlite3


class PartnersExporter:
    """Generiert PARTNERS.md aus DB."""

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
        self.output_path = self.bach_root / "PARTNERS.md"

    def generate(self) -> tuple[bool, str]:
        """Generiert PARTNERS.md aus DB."""
        if not self._check_tables():
            return False, "✗ Partner-Tabellen nicht gefunden"

        delegation_rules = self._get_delegation_rules()
        partner_recognition = self._get_partner_recognition()
        interaction_protocols = self._get_interaction_protocols()

        content = self._build_content(delegation_rules, partner_recognition, interaction_protocols)

        self.output_path.write_text(content, encoding='utf-8')
        return True, f"✓ PARTNERS.md generiert: {self.output_path}"

    def _check_tables(self) -> bool:
        """Prüft ob Partner-Tabellen existieren."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name IN ('delegation_rules', 'partner_recognition', 'interaction_protocols')
        """)
        count = cursor.fetchone()[0]
        conn.close()
        return count >= 1  # Mindestens eine Tabelle

    def _get_delegation_rules(self) -> list[dict]:
        """Hole Delegation-Regeln."""
        conn = sqlite3.connect(self.db_path)

        # Prüfe ob Tabelle existiert
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='delegation_rules'
        """)
        if cursor.fetchone()[0] == 0:
            conn.close()
            return []

        cursor = conn.execute("""
            SELECT rule_name, zone, preferred_partner, allowed_partners, priority, description
            FROM delegation_rules
            ORDER BY zone, priority DESC
        """)

        rules = []
        for row in cursor.fetchall():
            rules.append({
                'rule_name': row[0] or 'Unbekannt',
                'zone': row[1] or '',
                'preferred_partner': row[2] or '',
                'allowed_partners': row[3] or '[]',
                'priority': row[4] or 0,
                'description': row[5] or ''
            })

        conn.close()
        return rules

    def _get_partner_recognition(self) -> list[dict]:
        """Hole Partner-Erkennungs-Muster."""
        conn = sqlite3.connect(self.db_path)

        # Prüfe ob Tabelle existiert
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='partner_recognition'
        """)
        if cursor.fetchone()[0] == 0:
            conn.close()
            return []

        cursor = conn.execute("""
            SELECT partner_name, partner_type, capabilities, cost_tier, token_zone, priority, status
            FROM partner_recognition
            ORDER BY priority DESC, partner_name
        """)

        patterns = []
        for row in cursor.fetchall():
            patterns.append({
                'name': row[0] or 'Unbekannt',
                'type': row[1] or '',
                'capabilities': row[2] or '[]',
                'cost_tier': row[3] or 0,
                'token_zone': row[4] or '',
                'priority': row[5] or 0,
                'status': row[6] or ''
            })

        conn.close()
        return patterns

    def _get_interaction_protocols(self) -> list[dict]:
        """Hole Interaktions-Protokolle."""
        conn = sqlite3.connect(self.db_path)

        # Prüfe ob Tabelle existiert
        cursor = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='interaction_protocols'
        """)
        if cursor.fetchone()[0] == 0:
            conn.close()
            return []

        cursor = conn.execute("""
            SELECT protocol_name, protocol_type, description, request_format, response_format, applicable_partners, timeout_seconds, retry_count, priority
            FROM interaction_protocols
            ORDER BY priority DESC, protocol_name
        """)

        protocols = []
        for row in cursor.fetchall():
            protocols.append({
                'name': row[0] or 'Unbekannt',
                'type': row[1] or '',
                'description': row[2] or '',
                'request_format': row[3] or '{}',
                'response_format': row[4] or '{}',
                'applicable_partners': row[5] or '[]',
                'timeout': row[6] or 60,
                'retry_count': row[7] or 3,
                'priority': row[8] or 0
            })

        conn.close()
        return protocols

    def _build_content(self, delegation_rules: list[dict], partner_recognition: list[dict],
                       interaction_protocols: list[dict]) -> str:
        """Baut PARTNERS.md Content."""
        lines = []
        lines.append("# BACH Partners")
        lines.append("")
        lines.append("Automatisch generiert aus der Datenbank (delegation_rules, partner_recognition, interaction_protocols).")
        lines.append(f"Letzte Aktualisierung: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        # Delegation Rules
        if delegation_rules:
            lines.append("## Delegation Rules")
            lines.append("")
            lines.append(f"**Total:** {len(delegation_rules)} Regeln")
            lines.append("")

            by_zone = {}
            for rule in delegation_rules:
                z = rule['zone'] or 'Unbekannt'
                if z not in by_zone:
                    by_zone[z] = []
                by_zone[z].append(rule)

            for zone in sorted(by_zone.keys()):
                lines.append(f"### Zone: {zone}")
                lines.append("")
                for rule in by_zone[zone]:
                    prio_stars = "⭐" * min(rule['priority'] // 25, 3)
                    lines.append(f"- **{rule['rule_name']}** {prio_stars}")
                    if rule['description']:
                        lines.append(f"  - {rule['description']}")
                    if rule['preferred_partner']:
                        lines.append(f"  - Preferred: {rule['preferred_partner']}")
                lines.append("")

        # Partner Recognition
        if partner_recognition:
            lines.append("## Partner Recognition")
            lines.append("")
            lines.append(f"**Total:** {len(partner_recognition)} Partner")
            lines.append("")

            for pattern in partner_recognition:
                status_icon = "✓" if pattern['status'] == 'active' else "✗"
                cost_indicator = "$" * pattern['cost_tier']
                lines.append(f"- **{pattern['name']}** ({pattern['type']}) {status_icon}")
                lines.append(f"  - Zone: {pattern['token_zone']} | Cost: {cost_indicator} | Priority: {pattern['priority']}")
                if pattern['capabilities'] and pattern['capabilities'] != '[]':
                    lines.append(f"  - Capabilities: {pattern['capabilities']}")
                lines.append("")

        # Interaction Protocols
        if interaction_protocols:
            lines.append("## Interaction Protocols")
            lines.append("")
            lines.append(f"**Total:** {len(interaction_protocols)} Protokolle")
            lines.append("")

            by_type = {}
            for proto in interaction_protocols:
                t = proto['type'] or 'Allgemein'
                if t not in by_type:
                    by_type[t] = []
                by_type[t].append(proto)

            for ptype in sorted(by_type.keys()):
                lines.append(f"### {ptype}")
                lines.append("")
                for proto in by_type[ptype]:
                    lines.append(f"#### {proto['name']}")
                    if proto['description']:
                        lines.append("")
                        lines.append(proto['description'])
                    lines.append("")
                    lines.append(f"- **Timeout:** {proto['timeout']}s | **Retries:** {proto['retry_count']} | **Priority:** {proto['priority']}")
                    if proto['applicable_partners'] and proto['applicable_partners'] != '[]':
                        lines.append(f"- **Applicable Partners:** {proto['applicable_partners']}")
                    lines.append("")

        if not delegation_rules and not partner_recognition and not interaction_protocols:
            lines.append("Keine Partner-Daten in der Datenbank gefunden.")
            lines.append("")

        return "\n".join(lines)
