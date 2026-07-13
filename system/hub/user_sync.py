# SPDX-License-Identifier: MIT
"""
user_sync.py -- USER.md bidirektionale Synchronisation

Liest USER.md und schreibt Aenderungen in user_profile Tabelle zurueck.
Umgekehrt: DB -> USER.md (Regenerierung beim Shutdown).

Aufgerufen von:
- bach --startup  (Block 0.07: USER.md -> DB)
- bach --shutdown (Block 5.7: DB -> USER.md)

Hinweis: USER.md liegt im BACH-Root-Verzeichnis (eine Ebene ueber system/).
         Pfad: BACH/USER.md
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional


class UserSync:
    """
    Bidirektionale Synchronisation zwischen USER.md und user_profile (DB).

    Richtung 1 (USER.md -> DB):  sync_to_db()  -- beim Startup
    Richtung 2 (DB -> USER.md):  sync_to_file() -- beim Shutdown (regenerieren)

    USER.md liegt im BACH-Root, eine Ebene ueber dem system/-Verzeichnis:
        system/../USER.md  =>  BACH/USER.md
    """

    def __init__(self, bach_root: str, db_path: str):
        self.bach_root = Path(bach_root)
        self.db_path = db_path
        # USER.md ist eine Ebene ueber system/ (im BACH-Root-Verzeichnis)
        self.user_md_path = self.bach_root.parent / 'USER.md'

    # ── Markdown-Parser ───────────────────────────────────────────────────

    def read_user_md(self) -> dict:
        """
        Liest USER.md und parst die wichtigsten Felder.

        Erkennt Zeilen der Form:
            **Name:** Max Mustermann
            **Standort:** Berlin
            **Sprache:** Deutsch

        Returns:
            dict mit geparsten Feldern (kann leer sein)
        """
        if not self.user_md_path.exists():
            return {}

        content = self.user_md_path.read_text(encoding='utf-8', errors='ignore')
        result = {}

        field_map = {
            r'\*\*Name:\*\*': 'name',
            r'\*\*Standort:\*\*': 'location',
            r'\*\*Sprache:\*\*': 'language',
            r'\*\*Beruf:\*\*': 'occupation',
            r'\*\*GitHub:\*\*': 'github',
            r'\*\*E-Mail:\*\*': 'email',
            r'\*\*Rolle:\*\*': 'role',
        }

        for line in content.split('\n'):
            for pattern, key in field_map.items():
                m = re.match(rf'\s*{pattern}\s*(.*)', line)
                if m:
                    value = m.group(1).strip()
                    if value:
                        result[key] = value
                    break

        return result

    # ── Richtung 1: USER.md -> DB ─────────────────────────────────────────

    def sync_to_db(self, dry_run: bool = False) -> dict:
        """
        Liest USER.md und speichert Felder in user_profile Tabelle.

        Falls user_profile nicht existiert, wird der Sync uebersprungen
        (keine Fehler, nur Status-Meldung).

        Args:
            dry_run: True = nur lesen und zeigen, nicht schreiben

        Returns:
            dict mit Status und Statistiken
        """
        user_data = self.read_user_md()
        if not user_data:
            return {
                'status': 'skipped',
                'reason': 'USER.md leer oder nicht gefunden',
                'path': str(self.user_md_path),
            }

        if dry_run:
            return {
                'status': 'dry_run',
                'would_sync': list(user_data.keys()),
                'data': user_data,
            }

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                # Pruefe ob user_profile existiert
                table = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile'"
                ).fetchone()

                if not table:
                    conn.close()
                    return {
                        'status': 'skipped',
                        'reason': 'user_profile Tabelle nicht gefunden (noch nicht erstellt)',
                        'data_available': list(user_data.keys()),
                    }

                synced = 0
                now = datetime.now().isoformat()
                for key, value in user_data.items():
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO user_profile (key, value, updated_at)
                            VALUES (?, ?, ?)
                        """, (key, str(value), now))
                        synced += 1
                    except sqlite3.OperationalError:
                        # Tabelle hat andere Spalten -- try ohne updated_at
                        try:
                            conn.execute("""
                                INSERT OR REPLACE INTO user_profile (key, value)
                                VALUES (?, ?)
                            """, (key, str(value)))
                            synced += 1
                        except Exception:
                            pass

                conn.commit()
                return {'status': 'ok', 'synced': synced}

            finally:
                conn.close()

        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    # ── Richtung 2: DB -> USER.md ─────────────────────────────────────────

    def sync_to_file(self) -> dict:
        """
        Liest user_profile aus DB und aktualisiert Felder in USER.md.

        Das Template/die Struktur von USER.md bleibt erhalten -- nur
        bekannte Felder (**Name:** etc.) werden aktualisiert.

        Returns:
            dict mit Status
        """
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                table = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile'"
                ).fetchone()

                if not table:
                    return {
                        'status': 'skipped',
                        'reason': 'user_profile Tabelle nicht gefunden',
                    }

                rows = conn.execute(
                    "SELECT key, value FROM user_profile"
                ).fetchall()
            finally:
                conn.close()

            if not rows:
                return {'status': 'skipped', 'reason': 'Keine user_profile Daten in DB'}

            data = dict(rows)

            if not self.user_md_path.exists():
                return {
                    'status': 'skipped',
                    'reason': f'USER.md nicht gefunden: {self.user_md_path}',
                }

            content = self.user_md_path.read_text(encoding='utf-8', errors='ignore')

            # Feldmapping: DB-Key -> Markdown-Pattern
            replacements = {
                'name':       r'(\*\*Name:\*\*\s*)(.*)',
                'location':   r'(\*\*Standort:\*\*\s*)(.*)',
                'language':   r'(\*\*Sprache:\*\*\s*)(.*)',
                'occupation': r'(\*\*Beruf:\*\*\s*)(.*)',
                'github':     r'(\*\*GitHub:\*\*\s*)(.*)',
                'email':      r'(\*\*E-Mail:\*\*\s*)(.*)',
                'role':       r'(\*\*Rolle:\*\*\s*)(.*)',
            }

            updated = 0
            for key, pattern in replacements.items():
                if key in data and data[key]:
                    new_content = re.sub(
                        pattern,
                        lambda m, v=data[key]: m.group(1) + v,
                        content
                    )
                    if new_content != content:
                        content = new_content
                        updated += 1

            self.user_md_path.write_text(content, encoding='utf-8')
            return {'status': 'ok', 'updated_fields': updated}

        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def from_bach_root(cls, bach_root: str) -> 'UserSync':
        """
        Erstellt UserSync-Instanz aus bach_root-Pfad.

        Args:
            bach_root: Pfad zum system/-Verzeichnis von BACH

        Returns:
            UserSync-Instanz
        """
        # Den DB-Pfad zentral erfragen, nicht aus bach_root zusammenbauen:
        # bach_root/data/bach.db ist die veraltete Kopie im OneDrive-Ordner.
        from .bach_paths import BACH_DB

        return cls(bach_root, str(BACH_DB))


# ── Convenience-Funktionen fuer bach.py ──────────────────────────────────────


def sync_user_md_to_db(bach_root: str, dry_run: bool = False) -> dict:
    """
    Convenience-Funktion fuer bach.py Startup (Block 0.07).

    Liest USER.md und schreibt Felder in user_profile DB-Tabelle.

    Args:
        bach_root: Pfad zum system/-Verzeichnis
        dry_run:   True = nur pruefen, nicht schreiben

    Returns:
        dict mit Status
    """
    syncer = UserSync.from_bach_root(bach_root)
    return syncer.sync_to_db(dry_run=dry_run)


def sync_db_to_user_md(bach_root: str) -> dict:
    """
    Convenience-Funktion fuer bach.py Shutdown (Block 5.7).

    Liest user_profile aus DB und aktualisiert USER.md.

    Args:
        bach_root: Pfad zum system/-Verzeichnis

    Returns:
        dict mit Status
    """
    syncer = UserSync.from_bach_root(bach_root)
    return syncer.sync_to_file()
