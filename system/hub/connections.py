# SPDX-License-Identifier: MIT
"""
Connections Handler - Verbindungen und Actors-Model
====================================================

bach --connections list        Connections aus Datenbank
bach --connections db          Alias fuer list
bach --connections db --type ai    Nur AI-Partner
bach --connections db --type mcp   Nur MCP-Server
bach --connections show <n>    Details zu einer Connection
bach --connections actors      Actors-Model (docs/help/actors.txt)
bach --connections partners    Partner-Profile (docs/help/partners.txt)

Daten in: bach.db/connections (nach Migration aus _archive/)
"""
import json
import sqlite3
from pathlib import Path
from .base import BaseHandler


class ConnectionsHandler(BaseHandler):
    """Handler fuer --connections Operationen (DB-basiert)"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.help_dir = base_path / "help"
    
    @property
    def profile_name(self) -> str:
        return "connections"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "list": "Connections aus Datenbank",
            "db": "Alias fuer list",
            "show": "Details zu einer Connection",
            "actors": "Actors-Model anzeigen",
            "partners": "Partner-Profile anzeigen"
        }
    
    def _get_db_conn(self):
        """Datenbank-Verbindung herstellen."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation in ["list", "db"]:
            return self._list_db(args)
        elif operation == "actors":
            return self._show_help("actors")
        elif operation == "partners":
            return self._show_help("partners")
        elif operation == "show" and args:
            return self._show(args[0])
        else:
            return self._list_db(args)
    
    def _show_help(self, name: str) -> tuple:
        """Help-Datei anzeigen."""
        help_file = self.help_dir / f"{name}.txt"
        
        if not help_file.exists():
            return False, f"Hilfe nicht gefunden: {name}\nNutze: bach --help {name}"
        
        try:
            content = help_file.read_text(encoding='utf-8', errors='ignore')
            return True, content
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _list_db(self, args: list) -> tuple:
        """Connections aus Datenbank auflisten."""
        results = ["REGISTRIERTE CONNECTIONS (bach.db)", "=" * 60]
        
        if not self.db_path.exists():
            return False, "Datenbank nicht gefunden"
        
        conn = self._get_db_conn()
        
        # Filter nach Typ
        type_filter = None
        if '--type' in args:
            idx = args.index('--type')
            if idx + 1 < len(args):
                type_filter = args[idx + 1]
        
        # Query
        if type_filter:
            query = "SELECT * FROM connections WHERE type = ? ORDER BY category, name"
            rows = conn.execute(query, (type_filter,)).fetchall()
        else:
            query = "SELECT * FROM connections ORDER BY type, category, name"
            rows = conn.execute(query).fetchall()
        
        if not rows:
            conn.close()
            return True, "Keine Connections in Datenbank gefunden.\nFuehre 'bach --tools migrate' aus."
        
        # Nach Typ gruppieren
        current_type = None
        for row in rows:
            if row['type'] != current_type:
                current_type = row['type']
                type_label = {
                    'mcp': 'MCP-SERVER',
                    'ai': 'AI-PARTNER',
                    'api': 'API-CONNECTIONS',
                    'service': 'SERVICES'
                }.get(current_type, current_type.upper())
                results.append(f"\n[{type_label}]")
            
            # Status-Icon
            status = "[OK]" if row['is_active'] else "[--]"
            
            # Ausgabe
            name = row['name']
            category = row['category'] or ''
            help_text = (row['help_text'] or '')[:45]
            
            results.append(f"  {status} {name:<15} {category:<15} {help_text}")
        
        # Statistik
        stats = conn.execute(
            "SELECT type, COUNT(*) as cnt FROM connections GROUP BY type"
        ).fetchall()
        
        results.append(f"\n{'=' * 60}")
        results.append("Statistik:")
        total = 0
        for stat in stats:
            results.append(f"  {stat['type']}: {stat['cnt']}")
            total += stat['cnt']
        results.append(f"  Gesamt: {total}")
        
        results.append(f"\nWeitere Infos:")
        results.append(f"  bach --connections actors    Actors-Model")
        results.append(f"  bach --connections partners  Partner-Profile")
        
        conn.close()
        return True, "\n".join(results)
    
    def _show(self, name: str) -> tuple:
        """Connection-Details aus DB anzeigen."""
        if not self.db_path.exists():
            return False, "Datenbank nicht gefunden"
        
        conn = self._get_db_conn()
        row = conn.execute(
            "SELECT * FROM connections WHERE name LIKE ?", (f"%{name}%",)
        ).fetchone()
        conn.close()
        
        if not row:
            return False, f"Connection nicht gefunden: {name}\nNutze: bach --connections list"
        
        results = [f"CONNECTION: {row['name']}", "=" * 50]
        results.append(f"Typ:        {row['type']}")
        results.append(f"Kategorie:  {row['category'] or '-'}")
        results.append(f"Status:     {'Aktiv' if row['is_active'] else 'Inaktiv'}")
        if row['endpoint']:
            results.append(f"Endpoint:   {row['endpoint']}")
        if row['help_text']:
            results.append(f"\n[BESCHREIBUNG]")
            results.append(f"  {row['help_text']}")
        if row['trigger_patterns']:
            try:
                patterns = json.loads(row['trigger_patterns'])
                results.append(f"\n[TRIGGER/TOOLS]")
                results.append(f"  {', '.join(patterns)}")
            except:
                pass
        
        return True, "\n".join(results)
