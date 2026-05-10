#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
secrets_handler.py — Secrets-Management Handler (SQ076)

Verwaltet API-Keys, Passwörter und sensible Credentials.
Datei-autoritärer SYNC: ~/.bach/bach_secrets.json <-> bach.db:secrets

CLI-Befehle:
    bach secrets list                    # Alle Secrets anzeigen (Value versteckt)
    bach secrets get <key>               # Secret-Wert abrufen
    bach secrets set <key> <value>       # Secret speichern/aktualisieren
    bach secrets delete <key>            # Secret löschen
    bach secrets sync                    # Manueller SYNC (Datei -> DB)

ENT-44: Datei-Autorität
    - Wenn bach_secrets.json fehlt: alle Secrets aus DB löschen
    - Wenn bach_secrets.json existiert: DB-Inhalt mit Datei abgleichen
    - Bei secrets set: DB UND Datei aktualisieren

Autor: Sonnet Worker (Runde 9)
Datum: 2026-02-20
"""

import json
import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime

# Import Setup
SCRIPT_DIR = Path(__file__).parent
SYSTEM_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SYSTEM_DIR))

# Import mit Fallback
try:
    from core.database import get_connection as _get_connection
    GET_CONNECTION = _get_connection
except ImportError:
    # Fallback: Direkte DB-Verbindung
    def GET_CONNECTION():
        db_path = SYSTEM_DIR / "data" / "bach.db"
        return sqlite3.connect(str(db_path))

# Default-Pfad für bach_secrets.json (Override via system_config möglich)
DEFAULT_SECRETS_FILE = Path.home() / ".bach" / "bach_secrets.json"


def get_secrets_file_path():
    """
    Liest secrets_file_path aus system_config (Override).
    Falls nicht gesetzt: DEFAULT_SECRETS_FILE.

    User kann den Pfad überschreiben mit:
        bach settings set secrets_file_path=/path/to/usb/secrets.json
    """
    try:
        conn = GET_CONNECTION()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_config WHERE key = 'secrets_file_path'")
        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            # Tilde expandieren (~/.bach -> /home/user/.bach)
            path = Path(row[0]).expanduser()
            return path
    except:
        pass

    return DEFAULT_SECRETS_FILE


class SecretsHandler:
    """Handler für Secrets-Management"""

    def __init__(self, secrets_file=None):
        if secrets_file:
            self.secrets_file = Path(secrets_file)
        else:
            # Override aus system_config lesen
            self.secrets_file = get_secrets_file_path()

        self.conn = GET_CONNECTION()

    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    # ========== CLI-Methoden ==========

    def list_secrets(self):
        """Zeigt alle Secrets an (Value versteckt)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT key, description, category, source, created_at
            FROM secrets
            ORDER BY category, key
        """)
        rows = cursor.fetchall()

        if not rows:
            print("Keine Secrets vorhanden.")
            return

        print(f"\n{'Key':<30} {'Category':<12} {'Description':<40} {'Source':<10}")
        print("-" * 100)
        for key, desc, cat, src, created in rows:
            desc_short = (desc[:37] + "...") if len(desc) > 40 else desc
            print(f"{key:<30} {cat:<12} {desc_short:<40} {src:<10}")

        print(f"\nGesamt: {len(rows)} Secrets")

    def get_secret(self, key):
        """Gibt Secret-Wert zurück"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value, description FROM secrets WHERE key = ?", (key,))
        row = cursor.fetchone()

        if not row:
            print(f"✗ Secret '{key}' nicht gefunden.", file=sys.stderr)
            return None

        value, description = row
        print(f"Key: {key}")
        print(f"Description: {description}")
        print(f"Value: {value}")
        return value

    def set_secret(self, key, value, description="", category="general"):
        """Speichert oder aktualisiert Secret (DB + Datei)"""
        cursor = self.conn.cursor()

        # Prüfen ob schon vorhanden
        cursor.execute("SELECT id FROM secrets WHERE key = ?", (key,))
        exists = cursor.fetchone() is not None

        if exists:
            # Update
            cursor.execute("""
                UPDATE secrets
                SET value = ?, description = ?, category = ?, updated_at = datetime('now')
                WHERE key = ?
            """, (value, description, category, key))
            action = "aktualisiert"
        else:
            # Insert
            cursor.execute("""
                INSERT INTO secrets (key, value, description, category, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'manual', datetime('now'), datetime('now'))
            """, (key, value, description, category))
            action = "erstellt"

        self.conn.commit()

        # Datei aktualisieren (DB -> Datei)
        self._sync_to_file()

        print(f"✓ Secret '{key}' {action}.")
        return True

    def delete_secret(self, key):
        """Löscht Secret (DB + Datei)"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM secrets WHERE key = ?", (key,))
        deleted = cursor.rowcount > 0
        self.conn.commit()

        if not deleted:
            print(f"⚠ Secret '{key}' nicht gefunden.")
            return False

        # Datei aktualisieren
        self._sync_to_file()

        print(f"✓ Secret '{key}' gelöscht.")
        return True

    def sync_from_file(self, enforce_authority=True):
        """
        SYNC: Datei -> DB (Datei-autoritär)
        enforce_authority=True: Wenn Datei fehlt, DB leeren
        """
        if not self.secrets_file.exists():
            if enforce_authority:
                print(f"⚠ Datei-Autorität: {self.secrets_file} fehlt -> alle Secrets aus DB löschen")
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM secrets")
                self.conn.commit()
                print("✓ DB geleert (Datei-Autorität)")
            else:
                print(f"⚠ Secrets-Datei nicht gefunden: {self.secrets_file}")
            return

        # Datei lesen
        try:
            with open(self.secrets_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"✗ Fehler beim Lesen von {self.secrets_file}: {e}", file=sys.stderr)
            return

        secrets = data.get('secrets', {})

        # DB aktualisieren
        cursor = self.conn.cursor()

        for key, secret_data in secrets.items():
            # Beispiel-Einträge überspringen (beginnen mit "_example_")
            if key.startswith("_example_"):
                continue

            value = secret_data.get('value', '')
            description = secret_data.get('description', '')
            category = secret_data.get('category', 'general')

            # Prüfen ob schon vorhanden
            cursor.execute("SELECT id FROM secrets WHERE key = ?", (key,))
            exists = cursor.fetchone() is not None

            if exists:
                cursor.execute("""
                    UPDATE secrets
                    SET value = ?, description = ?, category = ?, source = 'file', updated_at = datetime('now')
                    WHERE key = ?
                """, (value, description, category, key))
            else:
                cursor.execute("""
                    INSERT INTO secrets (key, value, description, category, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'file', datetime('now'), datetime('now'))
                """, (key, value, description, category))

        self.conn.commit()
        print(f"✓ Secrets aus Datei geladen: {len(secrets)} Einträge")

    def _sync_to_file(self):
        """SYNC: DB -> Datei (interner Helper)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT key, value, description, category, created_at
            FROM secrets
            ORDER BY key
        """)
        rows = cursor.fetchall()

        # Datei-Struktur aufbauen
        secrets_dict = {}
        for key, value, desc, cat, created in rows:
            secrets_dict[key] = {
                "value": value,
                "description": desc,
                "category": cat,
                "created_at": created
            }

        data = {
            "meta": {
                "version": "1.0",
                "updated": datetime.now().isoformat(),
                "note": "Auto-synced from bach.db:secrets table"
            },
            "secrets": secrets_dict,
            "notes": [
                "This file is auto-generated. Manual edits will be preserved during sync.",
                "Use 'bach secrets sync' to reload from file."
            ]
        }

        # Datei schreiben
        self.secrets_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.secrets_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def handle_secrets_command(args):
    """CLI-Einstiegspunkt für `bach secrets <subcommand>`"""
    if not args or args[0] in ('-h', '--help'):
        print("""
BACH Secrets-Management (SQ076)

Verwendung:
    bach secrets list                    Alle Secrets anzeigen (Value versteckt)
    bach secrets get <key>               Secret-Wert abrufen
    bach secrets set <key> <value> [desc] [cat]
                                         Secret speichern/aktualisieren
    bach secrets delete <key>            Secret löschen
    bach secrets sync                    Manueller SYNC (Datei -> DB)

Beispiele:
    bach secrets set telegram_api_key "12345:ABCD..." "Telegram Bot" "api"
    bach secrets get telegram_api_key
    bach secrets list
    bach secrets delete old_key
    bach secrets sync

Datei-Autorität (ENT-44):
    ~/.bach/bach_secrets.json ist autoritär.
    Wenn Datei fehlt: alle Secrets aus DB werden gelöscht.
    Override-Pfad: 'secrets_file_path' in system_config setzen.
""")
        return

    handler = SecretsHandler()
    subcommand = args[0]

    if subcommand == 'list':
        handler.list_secrets()

    elif subcommand == 'get':
        if len(args) < 2:
            print("✗ Fehler: Key fehlt. Verwendung: bach secrets get <key>", file=sys.stderr)
            return
        handler.get_secret(args[1])

    elif subcommand == 'set':
        if len(args) < 3:
            print("✗ Fehler: Key und Value fehlen. Verwendung: bach secrets set <key> <value> [--desc=TEXT] [--category=CAT]", file=sys.stderr)
            return
        key = args[1]
        value = args[2]
        description = ""
        category = "general"
        # Parse remaining args: support both positional and --flag=value
        remaining = args[3:]
        positional = []
        for arg in remaining:
            if arg.startswith("--desc="):
                description = arg[len("--desc="):]
            elif arg.startswith("--category="):
                category = arg[len("--category="):]
            else:
                positional.append(arg)
        # Fallback: positional args (desc, category) for backwards compat
        if not description and len(positional) > 0:
            description = positional[0]
        if category == "general" and len(positional) > 1:
            category = positional[1]
        handler.set_secret(key, value, description, category)

    elif subcommand == 'delete':
        if len(args) < 2:
            print("✗ Fehler: Key fehlt. Verwendung: bach secrets delete <key>", file=sys.stderr)
            return
        handler.delete_secret(args[1])

    elif subcommand == 'sync':
        handler.sync_from_file(enforce_authority=True)

    else:
        print(f"✗ Unbekannter Subcommand: {subcommand}", file=sys.stderr)
        print("Verwendung: bach secrets [list|get|set|delete|sync]")


# CLI-Einstieg (wenn direkt ausgeführt)
if __name__ == "__main__":
    handle_secrets_command(sys.argv[1:])
