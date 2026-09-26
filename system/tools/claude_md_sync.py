#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
claude_md_sync.py - CLAUDE.md Marker-System (Stufe 2 Managed)
==============================================================

BACH Memory-CMS: DB → CLAUDE.md BACH-Block
- Push: DB → CLAUDE.md (zwischen <!-- BACH:START --> und <!-- BACH:END -->)
- Pull: CLAUDE.md kann manuell um den Block herum bearbeitet werden

Teil von SQ038: Claude Code Integration & LLM-Partner-Brücke
Referenz: BACH_Dev/BACH_Memory_Architektur_Konzept.md (Stufe 2)
"""

from pathlib import Path
from datetime import datetime
from typing import Optional
import sqlite3

def _union_columns(conn, table):
    """(Sichtbarkeitsfilter, Agent-Ausdruck) fuer memory_* -- vor BACH-Migration 043
    fehlen visibility/agent_id; dann gilt alles als sichtbar und ohne Agent."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    visible = ("(visibility IS NULL OR visibility IN ('shared', 'public'))"
               if "visibility" in cols else "1=1")
    agent = "NULLIF(agent_id, 'default')" if "agent_id" in cols else "NULL"
    return visible, agent
import re


class ClaudeMdSync:
    """Partner-MD BACH-Block Generator (Stufe 2 Managed)

    Unterstützt: CLAUDE.md, GEMINI.md, OLLAMA.md, etc.
    """

    MARKER_START = "<!-- BACH:START - Automatisch generiert, nicht manuell bearbeiten -->"
    MARKER_END = "<!-- BACH:END -->"

    def __init__(self, bach_root: Path, partner_md_path: Optional[Path] = None, partner_name: str = "CLAUDE"):
        self.bach_root = Path(bach_root)
        self.partner_name = partner_name.upper()

        # Auto-Detect: Root vs. system/ Installation
        if (self.bach_root / "system").exists():
            self.system_root = self.bach_root / "system"
        else:
            self.system_root = self.bach_root
            self.bach_root = self.system_root.parent

        self.db_path = self.system_root / "data" / "bach.db"

        # Partner.md Pfad (kann überschrieben werden)
        if partner_md_path:
            self.partner_md_path = Path(partner_md_path)
        else:
            # Standard: Projekt-Root PARTNER.md
            self.partner_md_path = self.bach_root / f"{self.partner_name}.md"

        # Legacy: claude_md_path Alias (für Abwärtskompatibilität)
        self.claude_md_path = self.partner_md_path

    def push(self) -> tuple[bool, str]:
        """Aktualisiert Partner.md BACH-Block aus DB."""
        # Lade bestehenden Inhalt oder erstelle neue Datei
        if self.partner_md_path.exists():
            content = self.partner_md_path.read_text(encoding='utf-8')
        else:
            content = f"# BACH Projekt-Anweisungen ({self.partner_name})\n\n"

        # Generiere BACH-Block
        bach_block = self._generate_bach_block()

        # Füge BACH-Block ein oder aktualisiere ihn
        if self.MARKER_START in content and self.MARKER_END in content:
            # BACH-Block existiert → aktualisieren
            pattern = f"{re.escape(self.MARKER_START)}.*?{re.escape(self.MARKER_END)}"
            new_content = re.sub(pattern, bach_block, content, flags=re.DOTALL)
        else:
            # BACH-Block existiert nicht → am Ende anfügen
            new_content = content.rstrip() + "\n\n" + bach_block + "\n"

        # Schreibe aktualisierte Datei
        self.partner_md_path.write_text(new_content, encoding='utf-8')

        return True, f"✓ {self.partner_name}.md BACH-Block aktualisiert: {self.partner_md_path}"

    def _generate_bach_block(self) -> str:
        """Generiert BACH-Block aus DB."""
        conn = sqlite3.connect(self.db_path)

        # Gemeinsames Gedaechtnis memory_* (T-20260920-823767362); shared_memory_*
        # ist seit 2026-02 eingefroren. Private Zeilen bleiben draussen.
        visible, agent = _union_columns(conn, "memory_lessons")
        cursor = conn.execute(f"""
            SELECT title, solution, severity, trigger_words, {agent}
            FROM memory_lessons
            WHERE is_active = 1 AND {visible}
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                times_shown DESC
            LIMIT 10
        """)
        lessons = cursor.fetchall()

        visible, agent = _union_columns(conn, "memory_facts")
        cursor = conn.execute(f"""
            SELECT category, value, {agent}
            FROM memory_facts
            WHERE (category LIKE '%warning%' OR category LIKE '%warnung%') AND {visible}
            ORDER BY updated_at DESC
            LIMIT 5
        """)
        warnings = cursor.fetchall()

        conn.close()

        # Baue BACH-Block
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        memory_source = "Gemeinsames Gedaechtnis (memory_*)"

        block = [self.MARKER_START]
        block.append(f"\n*Generiert: {timestamp} | Quelle: {memory_source}*\n")

        # Settings (Stufe 1: Statische Injektion)
        settings_summary = self._get_settings_summary()
        if settings_summary:
            block.append("## System-Einstellungen\n")
            for category, settings in settings_summary.items():
                block.append(f"**{category.upper()}**")
                for s in settings:
                    # Kürze Wert auf 50 Zeichen
                    value = str(s['value'])[:50]
                    block.append(f"- `{s['key']}`: {value}")
                block.append("")

        # Lessons
        if lessons:
            block.append("## BACH Lessons (Top-10)\n")
            for title, solution, severity, trigger_words, agent_id in lessons:
                # Bevorzuge title, fallback auf solution
                lesson_text = title if title else solution
                if lesson_text:
                    # Kürze Lesson auf eine Zeile
                    lesson_short = lesson_text.split('\n')[0][:120]
                    severity_mark = "🔴" if severity == "critical" else "🟠" if severity == "high" else "🟡" if severity == "medium" else ""
                    # Agent-Tag nur fuer Eintraege anderer Agenten (nicht 'default')
                    agent_tag = f" `[{agent_id}]`" if agent_id else ""
                    block.append(f"- {severity_mark} {lesson_short}{agent_tag}".strip())
            block.append("")

        # Warnungen
        if warnings:
            block.append("## BACH Warnungen\n")
            for category, content, agent_id in warnings:
                if content:
                    # Agent-Tag nur fuer Eintraege anderer Agenten (nicht 'default')
                    agent_tag = f" `[{agent_id}]`" if agent_id else ""
                    block.append(f"- ⚠️ {content[:120]}{agent_tag}")
            block.append("")

        # Fußzeile
        block.append(f"{self.MARKER_END}")

        return "\n".join(block)

    def _get_settings_summary(self, top_n: int = 8) -> dict:
        """Holt Settings-Zusammenfassung direkt aus DB."""
        try:
            conn = sqlite3.connect(self.db_path)

            # Hole Settings sortiert nach Kategorie-Priorität
            category_priority = {
                'security': 1,
                'behavior': 2,
                'integration': 3,
                'limits': 4,
                'backup': 5,
            }

            rows = conn.execute("""
                SELECT key, value, category, description
                FROM system_config
                WHERE value IS NOT NULL
                ORDER BY category, key
            """).fetchall()

            conn.close()

            # Nach Priorität sortieren
            def sort_key(row):
                cat = row[2] or 'misc'
                prio = category_priority.get(cat, 99)
                return (prio, cat, row[0])

            sorted_rows = sorted(rows, key=sort_key)[:top_n]

            # Gruppieren nach Kategorie
            result = {}
            for key, value, category, description in sorted_rows:
                cat = category or 'misc'
                if cat not in result:
                    result[cat] = []

                result[cat].append({
                    'key': key,
                    'value': value,
                    'description': description
                })

            return result

        except Exception as e:
            # Graceful Degradation: Fehler nicht propagieren
            return {}

    def status(self) -> tuple[bool, str]:
        """Zeigt Partner.md Status."""
        status_lines = []

        # Datei-Existenz
        exists = "✓" if self.partner_md_path.exists() else "✗"
        status_lines.append(f"{exists} {self.partner_name}.md: {self.partner_md_path}")

        if self.partner_md_path.exists():
            content = self.partner_md_path.read_text(encoding='utf-8')

            # Prüfe ob BACH-Block existiert
            has_block = self.MARKER_START in content and self.MARKER_END in content
            block_status = "✓" if has_block else "✗"
            status_lines.append(f"{block_status} BACH-Block: {'vorhanden' if has_block else 'nicht vorhanden'}")

            # Letzter Update
            mtime = self.partner_md_path.stat().st_mtime
            last_update = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            status_lines.append(f"   Letzter Update: {last_update}")

        # DB-Status
        conn = sqlite3.connect(self.db_path)

        visible, _agent = _union_columns(conn, "memory_lessons")
        cursor = conn.execute(f"SELECT COUNT(*) FROM memory_lessons WHERE is_active=1 AND {visible}")
        shared_lesson_count = cursor.fetchone()[0]
        bach_lesson_count = 0

        conn.close()

        if shared_lesson_count > 0:
            status_lines.append(f"✓ Shared Memory Lessons: {shared_lesson_count} (Multi-Agent)")
            if bach_lesson_count > 0:
                status_lines.append(f"  Legacy BACH Lessons: {bach_lesson_count} (Fallback)")
        else:
            status_lines.append(f"✓ BACH Memory Lessons: {bach_lesson_count} (Legacy, kein Shared Memory)")


        return True, "\n".join(status_lines)


def main():
    """CLI Entry Point."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python claude_md_sync.py <push|status> [partner_md_path] [partner_name]")
        print("  partner_name: CLAUDE (default), GEMINI, OLLAMA, etc.")
        sys.exit(1)

    operation = sys.argv[1]
    partner_md_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    partner_name = sys.argv[3] if len(sys.argv) > 3 else "CLAUDE"

    # Bach-Root ermitteln
    bach_root = Path(__file__).parent.parent
    sync = ClaudeMdSync(bach_root, partner_md_path, partner_name)

    if operation == "push":
        success, msg = sync.push()
    elif operation == "status":
        success, msg = sync.status()
    else:
        print(f"Unbekannte Operation: {operation}")
        sys.exit(1)

    print(msg)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
