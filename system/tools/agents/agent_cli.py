#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Agent CLI v1.0.0
=====================

CLI-Tool zur Verwaltung von BACH Agenten und Experten.

Features:
- Agenten auflisten und aktivieren
- Experten anzeigen
- User-Ordner initialisieren
- Datenbank-Schema anwenden

Usage:
    python agent_cli.py list                    # Alle Agenten
    python agent_cli.py experts                 # Alle Experten
    python agent_cli.py info <agent>            # Agent-Details
    python agent_cli.py init <agent>            # User-Ordner erstellen
    python agent_cli.py setup-db                # Datenbank initialisieren
    python agent_cli.py status                  # System-Status

Autor: BACH System
Datum: 2026-01-20
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Encoding fix fuer Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============ PFADE ============

SCRIPT_DIR = Path(__file__).parent.resolve()
BACH_DIR = SCRIPT_DIR.parent
DATA_DIR = BACH_DIR / "data"
USER_DIR = BACH_DIR / "user"
SKILLS_DIR = BACH_DIR / "skills"
AGENTS_DIR = SKILLS_DIR / "_agents"
EXPERTS_DIR = SKILLS_DIR / "_experts"

# Datenbanken (Unified DB seit v1.1.84)
BACH_DB = DATA_DIR / "bach.db"
USER_DB = BACH_DB  # Alias fuer Rueckwaertskompatibilitaet

# Schema-Dateien
AGENTS_SCHEMA = DATA_DIR / "schema" / "schema_agents.sql"


# ============ DATENBANK ============

def get_bach_db():
    """Verbindung zur bach.db"""
    conn = sqlite3.connect(BACH_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_db():
    """Verbindung zur bach.db (Unified DB seit v1.1.84)"""
    conn = sqlite3.connect(USER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_agents_schema():
    """Initialisiert das Agenten-Schema in bach.db"""
    if not AGENTS_SCHEMA.exists():
        print(f"Schema-Datei nicht gefunden: {AGENTS_SCHEMA}")
        return False

    schema_sql = AGENTS_SCHEMA.read_text(encoding='utf-8')

    # In bach.db anwenden
    conn = get_user_db()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print("Agenten-Schema in bach.db initialisiert")
        return True
    except Exception as e:
        print(f"Fehler: {e}")
        return False
    finally:
        conn.close()


def init_bach_agents_table():
    """Initialisiert Agenten-Tabelle in bach.db (falls nicht vorhanden)"""
    conn = get_bach_db()
    cursor = conn.cursor()

    # Pruefe ob Tabelle existiert
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='bach_agents'
    """)

    if cursor.fetchone():
        print("bach_agents Tabelle existiert bereits")
        conn.close()
        return True

    # Erstelle Tabellen
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS bach_agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            type TEXT DEFAULT 'boss',
            category TEXT,
            description TEXT,
            skill_path TEXT,
            user_data_folder TEXT,
            parent_agent_id INTEGER,
            is_active INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 50,
            requires_setup INTEGER DEFAULT 0,
            setup_completed INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used TEXT,
            version TEXT DEFAULT '1.0.0',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bach_experts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            description TEXT,
            skill_path TEXT,
            user_data_folder TEXT,
            domain TEXT,
            capabilities TEXT,
            is_active INTEGER DEFAULT 1,
            requires_db INTEGER DEFAULT 0,
            requires_files INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used TEXT,
            version TEXT DEFAULT '1.0.0',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Initial-Daten
    agents_data = [
        ('persoenlicher-assistent', 'Persoenlicher Assistent', 'boss', 'privat',
         'Terminverwaltung, Recherche, Organisation',
         'agents/persoenlicher-assistent.txt', 'persoenlicher_assistent'),

        ('gesundheitsassistent', 'Gesundheitsassistent', 'boss', 'privat',
         'Medizinische Dokumentation und Gesundheitsverwaltung',
         'agents/gesundheitsassistent.txt', 'gesundheit'),

        ('bueroassistent', 'Bueroassistent', 'boss', 'beruflich',
         'Steuern, Foerderplanung, Dokumentation',
         'agents/bueroassistent.txt', 'buero'),
    ]

    for name, display, type_, cat, desc, path, folder in agents_data:
        cursor.execute("""
            INSERT OR IGNORE INTO bach_agents
            (name, display_name, type, category, description, skill_path, user_data_folder)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, display, type_, cat, desc, path, folder))

    # Experten
    experts_data = [
        ('haushaltsmanagement', 'Haushaltsmanagement', 'persoenlicher-assistent',
         'Haushaltsbuch, Inventar, Einkaufslisten', 'agents/_experts/haushaltsmanagement/', 'haushalt'),

        ('gesundheitsverwalter', 'Gesundheitsverwalter', 'gesundheitsassistent',
         'Arztberichte, Laborwerte, Medikamente', 'agents/_experts/gesundheitsverwalter/', 'gesundheit'),

        ('psycho-berater', 'Psycho-Berater', 'gesundheitsassistent',
         'Therapeutische Gespraeche, Sitzungsprotokolle', 'agents/_experts/psycho-berater/', 'psychologie'),

        ('steuer-agent', 'Steuer-Agent', 'bueroassistent',
         'Steuerbelege, Werbungskosten', 'agents/_experts/steuer/', 'finanzen'),

        # foerderplaner: USER-Experte, nicht in BACH Release v3.1.6 enthalten (dist_type=0)
    ]

    for name, display, agent_name, desc, path, domain in experts_data:
        cursor.execute("""
            INSERT OR IGNORE INTO bach_experts
            (name, display_name, agent_id, description, skill_path, domain)
            VALUES (?, ?, (SELECT id FROM bach_agents WHERE name = ?), ?, ?, ?)
        """, (name, display, agent_name, desc, path, domain))

    conn.commit()
    conn.close()
    print("bach_agents und bach_experts in bach.db initialisiert")
    return True


# ============ AGENTEN-VERWALTUNG ============

def list_agents(show_inactive: bool = False) -> List[Dict]:
    """Listet alle Agenten"""
    conn = get_bach_db()
    cursor = conn.cursor()

    query = "SELECT * FROM bach_agents"
    if not show_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY category, priority"

    try:
        cursor.execute(query)
        agents = [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        # Tabelle existiert noch nicht
        agents = []
    finally:
        conn.close()

    return agents


def list_experts(agent_name: Optional[str] = None) -> List[Dict]:
    """Listet alle Experten (optional gefiltert nach Agent)"""
    conn = get_bach_db()
    cursor = conn.cursor()

    if agent_name:
        query = """
            SELECT e.*, a.name as agent_name
            FROM bach_experts e
            JOIN bach_agents a ON a.id = e.agent_id
            WHERE a.name = ?
            ORDER BY e.name
        """
        params = (agent_name,)
    else:
        query = """
            SELECT e.*, a.name as agent_name
            FROM bach_experts e
            JOIN bach_agents a ON a.id = e.agent_id
            ORDER BY a.name, e.name
        """
        params = ()

    try:
        cursor.execute(query, params)
        experts = [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        experts = []
    finally:
        conn.close()

    return experts


def get_agent_info(agent_name: str) -> Optional[Dict]:
    """Holt detaillierte Agent-Informationen"""
    conn = get_bach_db()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM bach_agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if row:
            agent = dict(row)
            # Experten hinzufuegen
            cursor.execute("""
                SELECT * FROM bach_experts WHERE agent_id = ?
            """, (agent['id'],))
            agent['experts'] = [dict(r) for r in cursor.fetchall()]
            return agent
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

    return None


def init_user_folder(agent_name: str) -> bool:
    """Erstellt User-Ordner fuer Agent"""
    agent = get_agent_info(agent_name)
    if not agent:
        print(f"Agent nicht gefunden: {agent_name}")
        return False

    folder_name = agent.get('user_data_folder')
    if not folder_name:
        print(f"Kein User-Ordner definiert fuer: {agent_name}")
        return False

    base_path = USER_DIR / folder_name

    # Standard-Unterordner je nach Agent
    subfolders = {
        'persoenlicher_assistent': ['dokumente', 'briefings', 'dossiers', 'haushalt/inventar', 'haushalt/finanzen', 'haushalt/plaene'],
        'gesundheit': ['dokumente', 'wissen', 'auswertungen', 'psycho/sitzungen', 'psycho/reflexionen'],
        'buero': ['steuer', 'foerderplanung/plaene', 'foerderplanung/klienten', 'dokumente', 'export'],
    }

    folders_to_create = subfolders.get(folder_name, ['dokumente', 'export'])

    created = []
    for subfolder in folders_to_create:
        path = base_path / subfolder
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.relative_to(USER_DIR)))

    if created:
        print(f"User-Ordner erstellt fuer '{agent_name}':")
        for c in created:
            print(f"  + user/{c}")
    else:
        print(f"User-Ordner existieren bereits fuer '{agent_name}'")

    return True


def get_system_status() -> Dict:
    """Holt System-Status"""
    status = {
        'bach_db_exists': BACH_DB.exists(),
        'agents_schema_exists': AGENTS_SCHEMA.exists(),
        'agents_dir_exists': AGENTS_DIR.exists(),
        'experts_dir_exists': EXPERTS_DIR.exists(),
        'user_dir_exists': USER_DIR.exists(),
        'agents': [],
        'experts': [],
    }

    if status['bach_db_exists']:
        status['agents'] = list_agents()
        status['experts'] = list_experts()

    return status


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="BACH Agent CLI v1.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
    %(prog)s list                    Alle Agenten anzeigen
    %(prog)s experts                 Alle Experten anzeigen
    %(prog)s info gesundheitsassistent    Agent-Details
    %(prog)s init bueroassistent     User-Ordner erstellen
    %(prog)s setup-db                Datenbank initialisieren
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Befehl')

    # list
    list_parser = subparsers.add_parser('list', help='Agenten auflisten')
    list_parser.add_argument('--all', '-a', action='store_true', help='Auch inaktive anzeigen')

    # experts
    experts_parser = subparsers.add_parser('experts', help='Experten auflisten')
    experts_parser.add_argument('--agent', '-a', help='Nach Agent filtern')

    # info
    info_parser = subparsers.add_parser('info', help='Agent-Details')
    info_parser.add_argument('agent', help='Agent-Name')

    # init
    init_parser = subparsers.add_parser('init', help='User-Ordner erstellen')
    init_parser.add_argument('agent', help='Agent-Name (oder "all" fuer alle)')

    # setup-db
    subparsers.add_parser('setup-db', help='Datenbank-Schema anwenden')

    # status
    subparsers.add_parser('status', help='System-Status anzeigen')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Befehle ausfuehren
    if args.command == 'list':
        agents = list_agents(show_inactive=args.all)
        if not agents:
            print("Keine Agenten gefunden. Fuehre 'setup-db' aus.")
            return

        print("\n=== BACH AGENTEN ===\n")
        current_cat = None
        for a in agents:
            if a['category'] != current_cat:
                current_cat = a['category']
                print(f"[{current_cat.upper()}]")

            status = "aktiv" if a['is_active'] else "inaktiv"
            experts = list_experts(a['name'])
            expert_count = len(experts)

            print(f"  {a['display_name']}")
            print(f"    Name: {a['name']} | Status: {status}")
            print(f"    Experten: {expert_count} | Nutzungen: {a['usage_count']}")
            print()

    elif args.command == 'experts':
        experts = list_experts(args.agent)
        if not experts:
            print("Keine Experten gefunden.")
            return

        print("\n=== BACH EXPERTEN ===\n")
        current_agent = None
        for e in experts:
            if e['agent_name'] != current_agent:
                current_agent = e['agent_name']
                print(f"[{current_agent}]")

            print(f"  {e['display_name']}")
            print(f"    Domain: {e['domain']} | Pfad: {e['skill_path']}")
            print()

    elif args.command == 'info':
        agent = get_agent_info(args.agent)
        if not agent:
            print(f"Agent nicht gefunden: {args.agent}")
            return

        print(f"\n=== {agent['display_name'].upper()} ===\n")
        print(f"Name:       {agent['name']}")
        print(f"Typ:        {agent['type']}")
        print(f"Kategorie:  {agent['category']}")
        print(f"Status:     {'aktiv' if agent['is_active'] else 'inaktiv'}")
        print(f"Version:    {agent['version']}")
        print(f"Skill-Pfad: {agent['skill_path']}")
        print(f"User-Ordner: user/{agent['user_data_folder']}/")
        print(f"\nBeschreibung:\n  {agent['description']}")

        if agent['experts']:
            print(f"\nExperten ({len(agent['experts'])}):")
            for e in agent['experts']:
                print(f"  - {e['display_name']} ({e['domain']})")

        print(f"\nStatistiken:")
        print(f"  Nutzungen: {agent['usage_count']}")
        print(f"  Zuletzt:   {agent['last_used'] or 'nie'}")

    elif args.command == 'init':
        if args.agent.lower() == 'all':
            agents = list_agents()
            for a in agents:
                init_user_folder(a['name'])
        else:
            init_user_folder(args.agent)

    elif args.command == 'setup-db':
        print("Initialisiere Datenbank-Schemas...")
        init_bach_agents_table()
        init_agents_schema()
        print("\nFertig! Fuehre 'bach agent list' aus um Agenten zu sehen.")

    elif args.command == 'status':
        status = get_system_status()

        print("\n=== BACH SYSTEM STATUS ===\n")
        print("Datenbanken:")
        print(f"  bach.db:         {'vorhanden' if status['bach_db_exists'] else 'FEHLT'}")
        print(f"  agents_schema:   {'vorhanden' if status['agents_schema_exists'] else 'FEHLT'}")

        print("\nVerzeichnisse:")
        print(f"  _agents/:        {'vorhanden' if status['agents_dir_exists'] else 'FEHLT'}")
        print(f"  _experts/:       {'vorhanden' if status['experts_dir_exists'] else 'FEHLT'}")
        print(f"  user/:           {'vorhanden' if status['user_dir_exists'] else 'FEHLT'}")

        print(f"\nRegistriert:")
        print(f"  Agenten:         {len(status['agents'])}")
        print(f"  Experten:        {len(status['experts'])}")

        if not status['agents']:
            print("\nHinweis: Fuehre 'python agent_cli.py setup-db' aus um Agenten zu registrieren.")


if __name__ == "__main__":
    main()
