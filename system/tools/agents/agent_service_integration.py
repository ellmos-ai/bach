#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Agent-Service-Connection Integration v2.0.0 (DB-Version)

Verknüpft Agenten mit Services, Connections und externen Tools.
Zentrale Anlaufstelle für Agent-Aktivierung und Tool-Routing.

GEÄNDERT: Liest jetzt aus bach.db statt JSON-Dateien!

Usage:
  python agent_service_integration.py matrix           # Zeige Verbindungsmatrix
  python agent_service_integration.py agent <name>     # Agent-Verbindungen
  python agent_service_integration.py recommend <task> # Tool-Empfehlung
  python agent_service_integration.py status           # Gesamtstatus
  python agent_service_integration.py tools [type]     # Tools auflisten
  python agent_service_integration.py connections      # Connections auflisten
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

SCRIPT_DIR = Path(__file__).parent
BACH_DIR = SCRIPT_DIR.parent
DB_PATH = BACH_DIR / "data" / "bach.db"


class AgentServiceIntegration:
    """Zentrale Integration von Agents, Services und Connections (DB-basiert)"""
    
    VERSION = "2.0.0"
    
    def __init__(self):
        self.db_path = DB_PATH
    
    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _query(self, sql: str, params: tuple = ()) -> List[dict]:
        with self._get_db() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
    
    def get_agents(self, active_only: bool = True) -> List[dict]:
        """Alle Agenten aus DB"""
        sql = "SELECT * FROM agents"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY priority DESC, name"
        return self._query(sql)
    
    def get_agent_by_name(self, name: str) -> Optional[dict]:
        """Agent nach Name"""
        results = self._query(
            "SELECT * FROM agents WHERE name LIKE ? OR name LIKE ?",
            (name, f"%{name}%")
        )
        return results[0] if results else None
    
    def get_connections(self, conn_type: str = None) -> List[dict]:
        """Alle Connections aus DB"""
        sql = "SELECT * FROM connections WHERE is_active = 1"
        params = ()
        if conn_type:
            sql += " AND type = ?"
            params = (conn_type,)
        sql += " ORDER BY type, name"
        return self._query(sql, params)
    
    def get_tools(self, tool_type: str = None) -> List[dict]:
        """Alle Tools aus DB"""
        sql = "SELECT * FROM tools WHERE is_available = 1"
        params = ()
        if tool_type:
            sql += " AND type = ?"
            params = (tool_type,)
        sql += " ORDER BY type, category, name"
        return self._query(sql, params)
    
    def get_agent_connections(self, agent_name: str) -> Dict:
        """Alle Verbindungen für einen Agent"""
        agent = self.get_agent_by_name(agent_name)
        if not agent:
            return {}
        
        # Capabilities aus Agent
        capabilities = json.loads(agent.get('capabilities', '[]') or '[]')
        requires_tools = json.loads(agent.get('requires_tools', '[]') or '[]')
        
        # Passende Tools finden
        tools = []
        for tool in self.get_tools():
            tool_caps = json.loads(tool.get('capabilities', '[]') or '[]')
            # Match wenn Überschneidung
            if set(capabilities) & set(tool_caps):
                tools.append(tool['name'])
        
        # Synergien
        synergies = self._query("""
            SELECT a2.name as partner, s.synergy_type, s.strength
            FROM agent_synergies s
            JOIN agents a2 ON s.agent_b_id = a2.id
            JOIN agents a1 ON s.agent_a_id = a1.id
            WHERE a1.name LIKE ?
        """, (f"%{agent_name}%",))
        
        return {
            "agent": agent['name'],
            "type": agent['type'],
            "capabilities": capabilities,
            "requires_tools": requires_tools,
            "matched_tools": tools,
            "synergies": synergies
        }
    
    def recommend_for_task(self, task_description: str) -> Dict:
        """Empfiehlt Agent und Tools für eine Aufgabe"""
        task_lower = task_description.lower()
        
        recommendations = {
            "agent": None,
            "tools": [],
            "connections": [],
            "reason": ""
        }
        
        # Keyword-basiertes Matching
        keyword_map = {
            "entwickler": ["code", "entwickl", "programm", "script", "bug", "debug", "python", "refactor"],
            "research": ["recherche", "research", "paper", "studie", "literatur", "analyse"],
            "production": ["video", "musik", "podcast", "präsentation", "content", "design"],
            # "foerderplaner": ["förder", "icf", "pädagog", "autis", "assessment"]  # USER (dist_type=0)
        }
        
        for agent_name, keywords in keyword_map.items():
            if any(k in task_lower for k in keywords):
                agent = self.get_agent_by_name(agent_name)
                if agent:
                    recommendations["agent"] = agent['name']
                    recommendations["reason"] = f"Matched keywords: {[k for k in keywords if k in task_lower]}"
                    break
        
        # Passende Tools
        tools = self.get_tools()
        for tool in tools:
            use_for = (tool.get('use_for', '') or '').lower()
            caps = json.loads(tool.get('capabilities', '[]') or '[]')
            
            if any(k in task_lower for k in [tool['name']] + caps + [use_for]):
                recommendations["tools"].append({
                    "name": tool['name'],
                    "type": tool['type'],
                    "category": tool['category']
                })
        
        # Passende Connections
        connections = self.get_connections()
        for conn in connections:
            triggers = json.loads(conn.get('trigger_patterns', '[]') or '[]')
            if any(t.lower() in task_lower for t in triggers):
                recommendations["connections"].append({
                    "name": conn['name'],
                    "type": conn['type']
                })
        
        return recommendations
    
    def get_status(self) -> Dict:
        """Gesamtstatus der Integration"""
        agents = self._query("SELECT COUNT(*) as cnt FROM agents WHERE is_active = 1")[0]['cnt']
        tools = self._query("SELECT COUNT(*) as cnt FROM tools WHERE is_available = 1")[0]['cnt']
        connections = self._query("SELECT COUNT(*) as cnt FROM connections WHERE is_active = 1")[0]['cnt']
        synergies = self._query("SELECT COUNT(*) as cnt FROM agent_synergies WHERE is_active = 1")[0]['cnt']
        
        tools_by_type = self._query("""
            SELECT type, COUNT(*) as cnt FROM tools 
            WHERE is_available = 1 GROUP BY type
        """)
        
        conn_by_type = self._query("""
            SELECT type, COUNT(*) as cnt FROM connections 
            WHERE is_active = 1 GROUP BY type
        """)
        
        return {
            "version": self.VERSION,
            "source": "bach.db",
            "agents": agents,
            "tools": {
                "total": tools,
                "by_type": {r['type']: r['cnt'] for r in tools_by_type}
            },
            "connections": {
                "total": connections,
                "by_type": {r['type']: r['cnt'] for r in conn_by_type}
            },
            "synergies": synergies
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent-Service Integration v2.0.0 (DB)")
    parser.add_argument("command", choices=["matrix", "agent", "recommend", "status", "tools", "connections"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    
    integration = AgentServiceIntegration()
    
    if args.command == "matrix":
        print("\n" + "=" * 60)
        print("  AGENTEN-MATRIX (aus bach.db)")
        print("=" * 60)
        
        for agent in integration.get_agents():
            print(f"\n  {agent['name'].upper()} ({agent['type']})")
            print(f"    {agent['description']}")
            caps = json.loads(agent.get('capabilities', '[]') or '[]')
            if caps:
                print(f"    Capabilities: {', '.join(caps)}")
    
    elif args.command == "agent" and args.name:
        data = integration.get_agent_connections(args.name)
        print(f"\n  AGENT: {args.name}")
        print("=" * 60)
        if data:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("  Agent nicht gefunden")
    
    elif args.command == "recommend" and args.name:
        rec = integration.recommend_for_task(args.name)
        print(f"\n  EMPFEHLUNG FÜR: {args.name}")
        print("=" * 60)
        print(f"  Agent: {rec['agent'] or 'Keiner spezifisch'}")
        if rec['reason']:
            print(f"  Grund: {rec['reason']}")
        if rec['tools']:
            print(f"  Tools: {len(rec['tools'])} gefunden")
            for t in rec['tools'][:5]:
                print(f"    - {t['name']} ({t['type']}/{t['category']})")
        if rec['connections']:
            print(f"  Connections: {[c['name'] for c in rec['connections']]}")
    
    elif args.command == "tools":
        tools = integration.get_tools(args.name)  # args.name = optional type filter
        print(f"\n  TOOLS ({len(tools)} verfügbar)")
        print("=" * 60)
        
        current_type = None
        for t in tools:
            if t['type'] != current_type:
                current_type = t['type']
                print(f"\n  [{current_type.upper()}]")
            print(f"    {t['name']:20} {t['category']:15} {t.get('use_for', '')[:30]}")
    
    elif args.command == "connections":
        conns = integration.get_connections()
        print(f"\n  CONNECTIONS ({len(conns)} aktiv)")
        print("=" * 60)
        
        current_type = None
        for c in conns:
            if c['type'] != current_type:
                current_type = c['type']
                print(f"\n  [{current_type.upper()}]")
            print(f"    {c['name']:20} {c['category'] or ''}")
    
    elif args.command == "status":
        status = integration.get_status()
        print("\n  INTEGRATION STATUS")
        print("=" * 60)
        print(f"  Version: {status['version']}")
        print(f"  Quelle:  {status['source']}")
        print(f"  Agents:  {status['agents']}")
        print(f"  Tools:   {status['tools']['total']}")
        for t, cnt in status['tools']['by_type'].items():
            print(f"           - {t}: {cnt}")
        print(f"  Connections: {status['connections']['total']}")
        for t, cnt in status['connections']['by_type'].items():
            print(f"           - {t}: {cnt}")
        print(f"  Synergien: {status['synergies']}")
    
    print()


if __name__ == "__main__":
    main()
