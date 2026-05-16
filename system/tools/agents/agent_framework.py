#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Agent Framework v1.0.0

Zentrales Framework für RecludOS Agenten.
Verbindet Agents mit Services, externen Tools und Connections.

Features:
- Agent-Loader und Registry-Verwaltung
- Service-Integration (scheduling, media, mail, etc.)
- Externe KI-Tool-Empfehlungen
- Connection-Management (MCP, APIs, CLIs)

Usage:
  python agent_framework.py list                    # Alle Agenten
  python agent_framework.py info <agent>            # Agent-Details
  python agent_framework.py tools <agent>           # Empfohlene Tools
  python agent_framework.py services <agent>        # Verknüpfte Services
  python agent_framework.py activate <agent>        # Agent aktivieren
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# Pfade
SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = Path(os.environ.get("BACH_ROOT", Path(__file__).parents[3]))
AGENTS_DIR = SCRIPT_DIR
SERVICES_DIR = BACH_ROOT / "system" / "tools" / "services"
CONNECTIONS_DIR = BACH_ROOT / "system" / "connectors"

# Registries
AGENT_REGISTRY = AGENTS_DIR / "registry.json"
SERVICE_REGISTRY = SERVICES_DIR / "registry.json"
EXTERNAL_TOOLS = CONNECTIONS_DIR / "external_ki_tools_registry.json"
CLI_TOOLS = CONNECTIONS_DIR / "connected_Tools" / "cli_tools" / "cli_tools_registry.json"


class AgentFramework:
    """Zentrales Framework für Agent-Management"""
    
    VERSION = "1.0.0"
    
    def __init__(self):
        self.agents = self._load_agents()
        self.services = self._load_services()
        self.external_tools = self._load_external_tools()
        self.cli_tools = self._load_cli_tools()
    
    def _load_json(self, path: Path) -> Dict:
        """Lädt JSON-Datei sicher"""
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _load_agents(self) -> Dict:
        return self._load_json(AGENT_REGISTRY)
    
    def _load_services(self) -> Dict:
        return self._load_json(SERVICE_REGISTRY)
    
    def _load_external_tools(self) -> Dict:
        return self._load_json(EXTERNAL_TOOLS)
    
    def _load_cli_tools(self) -> Dict:
        return self._load_json(CLI_TOOLS)
    
    def list_agents(self) -> List[Dict]:
        """Listet alle Agenten mit Status"""
        agents = []
        
        for name, data in self.agents.get("agents", {}).items():
            if isinstance(data, dict):
                agents.append({
                    "name": name,
                    "type": data.get("type", "unknown"),
                    "status": data.get("status", "unknown"),
                    "path": data.get("path", ""),
                    "description": data.get("description", "")
                })
        
        return agents
    
    def get_agent_info(self, agent_name: str) -> Optional[Dict]:
        """Holt detaillierte Agent-Informationen"""
        agents = self.agents.get("agents", {})
        
        # Direkte Suche
        if agent_name in agents:
            return agents[agent_name]
        
        # Suche in Unterstrukturen
        for top_agent, data in agents.items():
            if isinstance(data, dict):
                # Prüfe privat/beruflich Module
                for domain in ["privat", "beruflich"]:
                    if domain in data:
                        modules = data[domain].get("modules", {})
                        if agent_name in modules:
                            return modules[agent_name]
        
        return None
    
    def get_recommended_tools(self, agent_name: str) -> Dict:
        """Holt empfohlene externe Tools für Agent"""
        tools = {"external": [], "cli": [], "services": []}
        
        # Externe KI-Tools durchsuchen
        for category, tool_list in self.external_tools.get("tools", {}).items():
            for tool in tool_list:
                integrations = tool.get("agent_integrations", [])
                if agent_name in integrations or "ALL" in integrations:
                    tools["external"].append({
                        "name": tool["name"],
                        "url": tool["url"],
                        "category": category,
                        "use_cases": tool.get("use_cases", [])
                    })
        
        # CLI-Tools
        for tool_name, tool_data in self.cli_tools.get("tools", {}).items():
            tools["cli"].append({
                "name": tool_name,
                "category": tool_data.get("category", ""),
                "status": tool_data.get("status", "")
            })
        
        # Services
        for service_name, service_data in self.services.get("services", {}).items():
            tools["services"].append({
                "name": service_name,
                "description": service_data.get("description", ""),
                "status": service_data.get("status", "")
            })
        
        return tools
    
    def get_agent_services(self, agent_name: str) -> List[Dict]:
        """Holt verknüpfte Services für Agent"""
        # Mapping Agent -> Services
        agent_service_map = {
            "Research": ["prompt-manager"],
            "Entwickler": ["code-editor", "compiler", "prompt-manager"],
            # "Foerderplaner": ["scheduling", "prompt-manager"],  # USER-Experte (dist_type=0)
            "Production": ["media", "prompt-manager"],
            "Production/Musik": ["media"],
            "Production/Podcast": ["media", "mail"],
            "Production/Video": ["media"],
            "Gesundheitsmanager": ["scheduling", "mail"],
            "Alltags-und Haushaltsplaner": ["scheduling", "media"],
            "Psychologische Beratung": ["scheduling"],
            "rpg-assistent": ["media"]
        }
        
        service_names = agent_service_map.get(agent_name, [])
        services = []
        
        for name in service_names:
            if name in self.services.get("services", {}):
                services.append({
                    "name": name,
                    **self.services["services"][name]
                })
        
        return services


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent Framework v1.0.0")
    parser.add_argument("command", choices=["list", "info", "tools", "services", "activate"])
    parser.add_argument("agent", nargs="?", help="Agent-Name")
    args = parser.parse_args()
    
    framework = AgentFramework()
    
    if args.command == "list":
        print("\n🤖 BACH AGENTEN")
        print("=" * 60)
        for agent in framework.list_agents():
            status_icon = "✅" if agent["status"] == "active" else "⏳"
            print(f"  {status_icon} {agent['name']}")
            print(f"     Type: {agent['type']} | {agent['description'][:50]}...")
        print()
    
    elif args.command == "info" and args.agent:
        info = framework.get_agent_info(args.agent)
        if info:
            print(f"\n📋 AGENT: {args.agent}")
            print("=" * 60)
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            print(f"❌ Agent '{args.agent}' nicht gefunden")
    
    elif args.command == "tools" and args.agent:
        tools = framework.get_recommended_tools(args.agent)
        print(f"\n🔧 TOOLS FÜR: {args.agent}")
        print("=" * 60)
        
        print("\n  Externe KI-Tools:")
        for t in tools["external"][:10]:
            print(f"    - {t['name']} ({t['category']})")
        
        print(f"\n  CLI-Tools: {len(tools['cli'])} verfügbar")
        print(f"  Services: {len(tools['services'])} verfügbar")
    
    elif args.command == "services" and args.agent:
        services = framework.get_agent_services(args.agent)
        print(f"\n⚙️ SERVICES FÜR: {args.agent}")
        print("=" * 60)
        for s in services:
            print(f"  - {s['name']}: {s.get('description', '')}")


if __name__ == "__main__":
    main()
