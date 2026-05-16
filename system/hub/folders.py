#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
BACH Folders CLI Handler
Verwaltet user_data_folders Tabelle.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime


class FoldersHandler:
    """Handler fuer bach folders CLI-Befehle."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def list_folders(self) -> list[dict]:
        """Listet alle Ordner auf."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("""
                SELECT
                    f.id,
                    f.folder_path,
                    f.folder_type,
                    a.name as agent_name,
                    e.name as expert_name,
                    f.created_at,
                    f.last_accessed
                FROM user_data_folders f
                LEFT JOIN bach_agents a ON f.agent_id = a.id
                LEFT JOIN bach_experts e ON f.expert_id = e.id
                ORDER BY f.folder_type, f.folder_path
            """)

            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def add_folder(
        self,
        folder_path: str,
        folder_type: str = "data",
        agent_name: Optional[str] = None,
        expert_name: Optional[str] = None
    ) -> int:
        """Fuegt einen Ordner hinzu."""
        if folder_type not in ("data", "archive", "export", "temp"):
            raise ValueError(f"Ungültiger folder_type: {folder_type}. Erlaubt: data, archive, export, temp")

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()

            agent_id = None
            expert_id = None

            if agent_name:
                cur.execute("SELECT id FROM bach_agents WHERE name = ?", (agent_name,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Agent nicht gefunden: {agent_name}")
                agent_id = row[0]

            if expert_name:
                cur.execute("SELECT id FROM bach_experts WHERE name = ?", (expert_name,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Expert nicht gefunden: {expert_name}")
                expert_id = row[0]

            cur.execute("""
                INSERT INTO user_data_folders (folder_path, folder_type, agent_id, expert_id, dist_type)
                VALUES (?, ?, ?, ?, 0)
            """, (folder_path, folder_type, agent_id, expert_id))

            folder_id = cur.lastrowid
            conn.commit()
            return folder_id
        finally:
            conn.close()

    def remove_folder(self, folder_id: int) -> bool:
        """Entfernt einen Ordner (nur DB-Eintrag, nicht Dateisystem)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_data_folders WHERE id = ?", (folder_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            conn.close()

    def move_folder(self, folder_id: int, new_path: str) -> bool:
        """Aendert den Pfad eines Ordners (nur DB, nicht Dateisystem)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE user_data_folders
                SET folder_path = ?, last_accessed = ?
                WHERE id = ?
            """, (new_path, datetime.now().isoformat(), folder_id))
            updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            conn.close()


def _handle_folders(db_path: Path, args: list[str]) -> int:
    """Dispatch-Funktion fuer bach folders Kommandos."""
    if not args or args[0] in ("help", "--help", "-h"):
        print("""
Verwendung: bach folders <befehl> [optionen]

Befehle:
  list                    Zeige alle Ordner-Zuordnungen
  add <pfad>              Fuege Ordner hinzu
    --type <type>         Ordner-Typ (data/archive/export/temp, default: data)
    --agent <name>        Agent-Zuordnung (optional)
    --expert <name>       Expert-Zuordnung (optional)
  remove <id>             Entferne Ordner aus DB (Dateien bleiben)
  move <id> <neuer_pfad>  Aendere Pfad in DB (Dateien nicht verschoben)

Beispiele:
  bach folders list
  bach folders add "Projekte/Software" --type data --agent devSoftAgent
  bach folders remove 42
  bach folders move 42 "Projekte/Archiv/Software"
""")
        return 0

    handler = FoldersHandler(db_path)
    cmd = args[0]

    try:
        if cmd == "list":
            folders = handler.list_folders()
            if not folders:
                print("Keine Ordner-Zuordnungen gefunden.")
                return 0

            print(f"\n{'ID':<6} {'Typ':<10} {'Agent/Expert':<20} {'Pfad'}")
            print("-" * 80)
            for f in folders:
                owner = f['agent_name'] or f['expert_name'] or "-"
                print(f"{f['id']:<6} {f['folder_type']:<10} {owner:<20} {f['folder_path']}")
            print()
            return 0

        elif cmd == "add":
            if len(args) < 2:
                print("Fehler: <pfad> erforderlich")
                return 1

            folder_path = args[1]
            folder_type = "data"
            agent_name = None
            expert_name = None

            # Parse optionale Argumente
            i = 2
            while i < len(args):
                if args[i] == "--type" and i + 1 < len(args):
                    folder_type = args[i + 1]
                    i += 2
                elif args[i] == "--agent" and i + 1 < len(args):
                    agent_name = args[i + 1]
                    i += 2
                elif args[i] == "--expert" and i + 1 < len(args):
                    expert_name = args[i + 1]
                    i += 2
                else:
                    i += 1

            folder_id = handler.add_folder(folder_path, folder_type, agent_name, expert_name)
            print(f"✓ Ordner hinzugefügt (ID: {folder_id}): {folder_path}")
            return 0

        elif cmd == "remove":
            if len(args) < 2:
                print("Fehler: <id> erforderlich")
                return 1

            folder_id = int(args[1])
            if handler.remove_folder(folder_id):
                print(f"✓ Ordner entfernt (ID: {folder_id})")
                return 0
            else:
                print(f"Fehler: Ordner nicht gefunden (ID: {folder_id})")
                return 1

        elif cmd == "move":
            if len(args) < 3:
                print("Fehler: <id> <neuer_pfad> erforderlich")
                return 1

            folder_id = int(args[1])
            new_path = args[2]

            if handler.move_folder(folder_id, new_path):
                print(f"✓ Pfad aktualisiert (ID: {folder_id}): {new_path}")
                return 0
            else:
                print(f"Fehler: Ordner nicht gefunden (ID: {folder_id})")
                return 1

        else:
            print(f"Unbekannter Befehl: {cmd}")
            print("Nutze 'bach folders help' für Hilfe")
            return 1

    except ValueError as e:
        print(f"Fehler: {e}")
        return 1
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")
        return 1
