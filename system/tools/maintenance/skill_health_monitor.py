#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Skill Health Monitor v1.0.0
--------------------------------
Überwacht und validiert alle BACH-Skills und Agenten.

Funktionen:
- Skill-Verzeichnisse scannen
- SKILL.md Dateien auf Vollständigkeit prüfen
- Agent-Definitionen validieren
- Verwaiste oder fehlerhafte Skills finden
- Gesundheitsberichte erstellen

Basiert auf: RecludOS skill_health_monitor Konzept

CLI:
    python skill_health_monitor.py check           # Vollständiger Check
    python skill_health_monitor.py check --skills  # Nur Skills
    python skill_health_monitor.py check --agents  # Nur Agenten
    python skill_health_monitor.py report          # Detaillierter Report
    python skill_health_monitor.py --help          # Hilfe
"""

import os
import sys
import json
import sqlite3
import argparse
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

# BACH Root ermitteln
BACH_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = BACH_ROOT / "skills"
DATA_DIR = BACH_ROOT / "data"
DB_PATH = DATA_DIR / "bach.db"

# Erwartete Skill-Verzeichnisse (v2.5 Restructuring)
# Agents/Experts liegen jetzt unter system/agents/
EXPECTED_SKILL_DIRS = {
    "_services": "Service-Skills",
}
EXPECTED_AGENT_DIRS = {
    "agents": "Agent-Definitionen",
    "agents/_experts": "Expert-Skills",
}

# Pflichtfelder in SKILL.md (YAML-Frontmatter)
REQUIRED_SKILL_FIELDS = ["name", "version", "description"]

# Optionale aber empfohlene Felder
RECOMMENDED_SKILL_FIELDS = ["last_updated", "author", "dependencies"]

# Agent-Pflichtdateien
AGENT_REQUIRED_FILES = ["manifest.json"]  # oder AGENT.md/ATI.md
AGENT_RECOMMENDED_FILES = ["README.md", "CHANGELOG.md"]


class SkillHealthMonitor:
    """Überwacht und validiert BACH-Skills."""
    
    def __init__(self, bach_root: Path = BACH_ROOT):
        self.bach_root = bach_root
        self.skills_dir = bach_root / "skills"
        self.db_path = bach_root / "data" / "bach.db"
        self.issues: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.stats: Dict[str, Any] = {
            "skills_total": 0,
            "skills_healthy": 0,
            "agents_total": 0,
            "agents_healthy": 0,
            "experts_total": 0,
            "services_total": 0,
        }
    
    def check_all(self) -> Tuple[bool, Dict]:
        """Führt alle Checks durch."""
        self.issues = []
        self.warnings = []
        
        # 1. Skill-Verzeichnisse prüfen
        self._check_skill_directories()
        
        # 2. Skills scannen
        self._scan_skills()
        
        # 3. Agenten validieren
        self._validate_agents()
        
        # 4. DB-Konsistenz prüfen
        self._check_db_consistency()
        
        # Ergebnis zusammenstellen
        healthy = len(self.issues) == 0
        return healthy, {
            "healthy": healthy,
            "stats": self.stats,
            "issues": self.issues,
            "warnings": self.warnings,
            "timestamp": datetime.now().isoformat(),
        }
    
    def _check_skill_directories(self):
        """Prüft ob erwartete Verzeichnisse existieren."""
        for dir_name, description in EXPECTED_SKILL_DIRS.items():
            dir_path = self.skills_dir / dir_name
            if not dir_path.exists():
                self.issues.append({
                    "type": "missing_directory",
                    "path": str(dir_path),
                    "description": f"Erwartetes Verzeichnis fehlt: {description}",
                    "severity": "warning",
                })
        # Agent-Verzeichnisse (v2.5 - auf system/ Ebene)
        for dir_name, description in EXPECTED_AGENT_DIRS.items():
            dir_path = self.bach_root / dir_name
            if not dir_path.exists():
                self.issues.append({
                    "type": "missing_directory",
                    "path": str(dir_path),
                    "description": f"Erwartetes Verzeichnis fehlt: {description}",
                    "severity": "warning",
                })
    
    def _scan_skills(self):
        """Scannt alle Skills und prüft Vollständigkeit."""
        if not self.skills_dir.exists():
            self.issues.append({
                "type": "critical",
                "path": str(self.skills_dir),
                "description": "Skills-Verzeichnis existiert nicht!",
                "severity": "critical",
            })
            return
        
        # Alle SKILL.md Dateien finden
        for skill_md in self.skills_dir.rglob("SKILL.md"):
            self.stats["skills_total"] += 1
            self._validate_skill_md(skill_md)
        
        # Alle *.md Skill-Definitionen (ohne SKILL.md)
        for md_file in self.skills_dir.rglob("*.md"):
            if md_file.name == "SKILL.md":
                continue
            # Prüfen ob es eine Skill-Definition ist (hat YAML-Frontmatter)
            self._check_potential_skill(md_file)
    
    def _validate_skill_md(self, skill_path: Path):
        """Validiert eine SKILL.md Datei."""
        try:
            content = skill_path.read_text(encoding="utf-8")
        except Exception as e:
            self.issues.append({
                "type": "read_error",
                "path": str(skill_path),
                "description": f"Kann Datei nicht lesen: {e}",
                "severity": "error",
            })
            return
        
        # YAML-Frontmatter extrahieren
        frontmatter = self._extract_frontmatter(content)
        
        if not frontmatter:
            self.warnings.append({
                "type": "no_frontmatter",
                "path": str(skill_path),
                "description": "Kein YAML-Frontmatter gefunden",
                "severity": "warning",
            })
            return
        
        # Pflichtfelder prüfen
        missing_required = []
        for field in REQUIRED_SKILL_FIELDS:
            if field not in frontmatter:
                missing_required.append(field)
        
        if missing_required:
            self.issues.append({
                "type": "missing_fields",
                "path": str(skill_path),
                "description": f"Fehlende Pflichtfelder: {', '.join(missing_required)}",
                "severity": "error",
                "fields": missing_required,
            })
        else:
            self.stats["skills_healthy"] += 1
        
        # Empfohlene Felder prüfen
        missing_recommended = []
        for field in RECOMMENDED_SKILL_FIELDS:
            if field not in frontmatter:
                missing_recommended.append(field)
        
        if missing_recommended:
            self.warnings.append({
                "type": "missing_recommended",
                "path": str(skill_path),
                "description": f"Fehlende empfohlene Felder: {', '.join(missing_recommended)}",
                "severity": "info",
                "fields": missing_recommended,
            })
        
        # Alter prüfen (>60 Tage = veraltet)
        if "last_updated" in frontmatter:
            self._check_skill_age(skill_path, frontmatter["last_updated"])
    
    def _extract_frontmatter(self, content: str) -> Optional[Dict]:
        """Extrahiert YAML-Frontmatter aus Markdown."""
        # YAML zwischen --- ... ---
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not match:
            return None
        
        yaml_content = match.group(1)
        frontmatter = {}
        
        # Einfaches YAML-Parsing (key: value)
        for line in yaml_content.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value:
                    frontmatter[key] = value
        
        return frontmatter
    
    def _check_skill_age(self, skill_path: Path, last_updated: str):
        """Prüft ob ein Skill veraltet ist."""
        try:
            # Versuche Datum zu parsen (verschiedene Formate)
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"]:
                try:
                    update_date = datetime.strptime(last_updated, fmt)
                    break
                except ValueError:
                    continue
            else:
                return  # Konnte Datum nicht parsen
            
            age_days = (datetime.now() - update_date).days
            
            if age_days > 90:
                self.warnings.append({
                    "type": "outdated_skill",
                    "path": str(skill_path),
                    "description": f"Skill ist {age_days} Tage alt (kritisch)",
                    "severity": "warning",
                    "age_days": age_days,
                })
            elif age_days > 60:
                self.warnings.append({
                    "type": "aging_skill",
                    "path": str(skill_path),
                    "description": f"Skill ist {age_days} Tage alt",
                    "severity": "info",
                    "age_days": age_days,
                })
                
        except Exception:
            pass  # Datum-Parsing fehlgeschlagen, ignorieren
    
    def _check_potential_skill(self, md_path: Path):
        """Prüft ob eine MD-Datei ein Skill sein könnte."""
        # Ignoriere bekannte Nicht-Skills
        ignore_names = ["README.md", "CHANGELOG.md", "CONCEPT.md", "DESIGN.md"]
        if md_path.name in ignore_names:
            return
        
        try:
            content = md_path.read_text(encoding="utf-8")
            frontmatter = self._extract_frontmatter(content)
            
            if frontmatter and any(field in frontmatter for field in REQUIRED_SKILL_FIELDS):
                # Sieht wie ein Skill aus, ist aber nicht SKILL.md
                self.warnings.append({
                    "type": "potential_skill",
                    "path": str(md_path),
                    "description": "Sieht wie Skill-Definition aus, aber nicht SKILL.md",
                    "severity": "info",
                })
        except Exception:
            pass
    
    def _validate_agents(self):
        """Validiert alle Agenten."""
        agents_dir = self.bach_root / "agents"
        if not agents_dir.exists():
            return
        
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            
            # Ignoriere interne Ordner und Container-Verzeichnisse.
            if agent_dir.name.startswith("_") or agent_dir.name in {"personas"}:
                continue
            
            self.stats["agents_total"] += 1
            agent_healthy = True
            
            # Prüfe auf manifest.json oder Agent-Definition
            has_manifest = (agent_dir / "manifest.json").exists()
            has_agent_md = any(
                (agent_dir / f).exists()
                for f in ["SKILL.md", "AGENT.md", f"{agent_dir.name.upper()}.md", "ATI.md"]
            )
            
            if not has_manifest and not has_agent_md:
                self.issues.append({
                    "type": "missing_agent_definition",
                    "path": str(agent_dir),
                    "description": "Agent hat weder manifest.json noch Agent-Definition",
                    "severity": "error",
                })
                agent_healthy = False
            
            # manifest.json validieren wenn vorhanden
            if has_manifest:
                self._validate_agent_manifest(agent_dir / "manifest.json")
            
            if agent_healthy:
                self.stats["agents_healthy"] += 1
    
    def _validate_agent_manifest(self, manifest_path: Path):
        """Validiert ein Agent-Manifest."""
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            required_fields = ["name", "version", "description"]
            missing = [f for f in required_fields if f not in manifest]
            
            if missing:
                self.warnings.append({
                    "type": "incomplete_manifest",
                    "path": str(manifest_path),
                    "description": f"Manifest fehlen Felder: {', '.join(missing)}",
                    "severity": "warning",
                    "fields": missing,
                })
                
        except json.JSONDecodeError as e:
            self.issues.append({
                "type": "invalid_json",
                "path": str(manifest_path),
                "description": f"Ungültiges JSON: {e}",
                "severity": "error",
            })
        except Exception as e:
            self.issues.append({
                "type": "read_error",
                "path": str(manifest_path),
                "description": f"Kann Datei nicht lesen: {e}",
                "severity": "error",
            })
    
    def _check_db_consistency(self):
        """Prüft DB-Konsistenz mit Dateisystem."""
        if not self.db_path.exists():
            self.warnings.append({
                "type": "no_database",
                "path": str(self.db_path),
                "description": "Datenbank nicht gefunden",
                "severity": "warning",
            })
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Skills in DB vs. Dateisystem
            columns = {row[1] for row in cursor.execute("PRAGMA table_info(skills)").fetchall()}
            active_column = "is_active" if "is_active" in columns else "active"
            cursor.execute(f"SELECT name, path FROM skills WHERE {active_column} = 1")
            db_skills = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Prüfe ob DB-Skills noch existieren
            for name, path in db_skills.items():
                if path:
                    full_path = self.bach_root / path
                    if not full_path.exists():
                        self.warnings.append({
                            "type": "orphaned_db_entry",
                            "path": path,
                            "description": f"Skill '{name}' in DB aber nicht im Dateisystem",
                            "severity": "warning",
                        })
            
            conn.close()
            
        except sqlite3.Error as e:
            self.warnings.append({
                "type": "db_error",
                "path": str(self.db_path),
                "description": f"DB-Fehler: {e}",
                "severity": "warning",
            })
    
    def generate_report(self) -> str:
        """Generiert einen lesbaren Bericht."""
        healthy, results = self.check_all()
        
        lines = [
            "=" * 60,
            "       BACH SKILL HEALTH MONITOR REPORT",
            "=" * 60,
            f" Zeitpunkt: {results['timestamp']}",
            f" Status: {'[OK] GESUND' if healthy else '[!] PROBLEME GEFUNDEN'}",
            "=" * 60,
            "",
            "[STATISTIKEN]",
            f"  Skills gesamt: {self.stats['skills_total']}",
            f"  Skills gesund: {self.stats['skills_healthy']}",
            f"  Agenten gesamt: {self.stats['agents_total']}",
            f"  Agenten gesund: {self.stats['agents_healthy']}",
            "",
        ]
        
        if self.issues:
            lines.append("[FEHLER]")
            for issue in self.issues:
                lines.append(f"  [X] {issue['type']}: {issue['description']}")
                lines.append(f"    Pfad: {issue['path']}")
            lines.append("")
        
        if self.warnings:
            lines.append("[WARNUNGEN]")
            for warning in self.warnings:
                lines.append(f"  [!] {warning['type']}: {warning['description']}")
                if warning.get('path'):
                    lines.append(f"    Pfad: {warning['path']}")
            lines.append("")
        
        if healthy and not self.warnings:
            lines.append("[ERGEBNIS] Alle Skills und Agenten sind gesund!")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)


def main():
    """CLI-Einstiegspunkt."""
    parser = argparse.ArgumentParser(
        description="BACH Skill Health Monitor - Überwacht Skill-Gesundheit"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")
    
    # check Befehl
    check_parser = subparsers.add_parser("check", help="Führt Health-Checks durch")
    check_parser.add_argument("--skills", action="store_true", help="Nur Skills prüfen")
    check_parser.add_argument("--agents", action="store_true", help="Nur Agenten prüfen")
    check_parser.add_argument("--json", action="store_true", help="JSON-Ausgabe")
    
    # report Befehl
    subparsers.add_parser("report", help="Generiert detaillierten Bericht")
    
    args = parser.parse_args()
    
    monitor = SkillHealthMonitor()
    
    if args.command == "check":
        healthy, results = monitor.check_all()
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            status = "[OK] GESUND" if healthy else "[!] PROBLEME"
            print(f"[SKILL HEALTH] {status}")
            print(f"  Skills: {monitor.stats['skills_healthy']}/{monitor.stats['skills_total']}")
            print(f"  Agenten: {monitor.stats['agents_healthy']}/{monitor.stats['agents_total']}")
            
            if results['issues']:
                print(f"\n  {len(results['issues'])} Fehler gefunden:")
                for issue in results['issues'][:5]:
                    print(f"    - {issue['description']}")
            
            if results['warnings']:
                print(f"\n  {len(results['warnings'])} Warnungen:")
                for warning in results['warnings'][:5]:
                    print(f"    - {warning['description']}")
        
        sys.exit(0 if healthy else 1)
    
    elif args.command == "report":
        print(monitor.generate_report())
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
