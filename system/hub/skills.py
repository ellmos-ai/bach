# SPDX-License-Identifier: MIT
"""
Skills Handler - Skill-Verwaltung (v2.0 Architektur)
====================================================

--skills list            Alle Skills auflisten (aus Dateisystem)
--skills show <n>        Skill-Details anzeigen
--skills search <term>   Skills durchsuchen
--skills export <name>   Skill exportieren - autarkes Paket mit allen Abhängigkeiten (v2.0)
--skills install <path>  Skill aus ZIP/Verzeichnis importieren (v1.1.44)
--skills hierarchy       Hierarchie anzeigen (aus DB, v1.1.73)
--skills hierarchy <typ> Nur Typ anzeigen (agent/expert/skill/service/workflow)
--skills version <name>  Versions-Check: Zeigt lokale und zentrale Version (v2.0)

v2.0 Export-Features:
- Skill-spezifische Tools und Workflows werden automatisch inkludiert
- Version wird aus YAML-Header extrahiert
- README.md für Standalone-Nutzung wird generiert
- Vollständig autarke Pakete ohne BACH-Abhängigkeit
"""
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
import re
try:
    import yaml
except ImportError:
    yaml = None  # Optional dependency for YAML frontmatter parsing
from pathlib import Path
from datetime import datetime
from .base import BaseHandler
from .lang import t


class SkillsHandler(BaseHandler):
    """Handler fuer --skills Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.skills_dir = base_path / "skills"
        self.base_path = base_path
    
    @property
    def profile_name(self) -> str:
        return "skills"
    
    @property
    def target_file(self) -> Path:
        return self.skills_dir
    
    def get_operations(self) -> dict:
        return {
            "list": t("skills_list_desc", default="Alle Skills auflisten"),
            "show": t("skills_show_desc", default="Skill-Details anzeigen"),
            "search": t("skills_search_desc", default="Skills durchsuchen"),
            "create": t("skills_create_desc", default="Neuen Skill erstellen (v2.1 - Self-Extension, --format anthropic fuer Anthropic-Standard)"),
            "reload": t("skills_reload_desc", default="Handler-Registry + Tools neu laden (Hot-Reload, v2.1)"),
            "export": t("skills_export_desc", default="Skill exportieren - autarkes Paket (v2.0, --format agent fuer Claude Code Agent)"),
            "export-agent": t("skills_export_agent_desc", default="Skill als Claude Code Agent exportieren (.md Datei)"),
            "install": t("skills_install_desc", default="Skill aus ZIP/Verzeichnis importieren"),
            "hierarchy": t("skills_hierarchy_desc", default="Hierarchie aus DB anzeigen (v1.1.73)"),
            "version": t("skills_version_desc", default="Versions-Check: lokal vs zentral (v2.0)")
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # dry_run aus args extrahieren falls vorhanden
        if '--dry-run' in args:
            dry_run = True
            args = [a for a in args if a != '--dry-run']

        if operation == "create" and args:
            skill_type = "expert"
            fmt = None
            for i, a in enumerate(args):
                if a == "--type" and i + 1 < len(args):
                    skill_type = args[i + 1]
                if a == "--format" and i + 1 < len(args):
                    fmt = args[i + 1]
            clean_args = [a for a in args if not a.startswith('--') and a not in ("agent", "expert", "service", "tool", "handler", "anthropic", "bach")]
            if not clean_args:
                return False, "Usage: bach skills create <name> [--type agent|expert|service|tool|handler] [--format anthropic]"
            return self._create(clean_args[0], skill_type, dry_run, fmt=fmt)
        elif operation == "reload":
            return self._reload()
        elif operation == "show" and args:
            return self._show(args[0])
        elif operation == "search" and args:
            return self._search(" ".join(args))
        elif operation == "export" and args:
            # Format-Flag extrahieren
            export_fmt = "bach"
            for i, a in enumerate(args):
                if a == "--format" and i + 1 < len(args):
                    export_fmt = args[i + 1]
            clean_args = [a for a in args if not a.startswith('--') and a not in ("bach", "anthropic", "agent")]
            output_dir = clean_args[1] if len(clean_args) > 1 else None
            return self._export(clean_args[0], output_dir, dry_run, fmt=export_fmt)
        elif operation == "export-agent" and args:
            # Kurzform: bach skills export-agent <name> [output_dir]
            clean_args = [a for a in args if not a.startswith('--')]
            output_dir = clean_args[1] if len(clean_args) > 1 else None
            return self._export(clean_args[0], output_dir, dry_run, fmt="agent")
        elif operation == "install" and args:
            return self._install(args[0], dry_run)
        elif operation == "hierarchy":
            type_filter = args[0] if args else None
            return self._hierarchy(type_filter)
        elif operation == "version" and args:
            return self._version_check(args[0])
        else:
            return self._list()
    
    def _list(self) -> tuple:
        """Alle Skills aus Dateisystem auflisten."""
        results = ["SKILLS", "=" * 50]
        
        if not self.skills_dir.exists():
            return False, t("skills_dir_not_found", default="Skills-Verzeichnis nicht gefunden")
        
        # Skills nach Kategorie gruppieren
        categories = {}
        
        for item in self.skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('__'):
                cat_name = item.name.lstrip('_')
                skills = list(item.glob("*.txt")) + list(item.glob("*.md"))
                if skills:
                    categories[cat_name] = skills
        
        # Auch Root-Level Skills
        root_skills = list(self.skills_dir.glob("*.txt")) + list(self.skills_dir.glob("*.md"))
        if root_skills:
            categories["_root"] = root_skills
        
        total = 0
        for cat, skills in sorted(categories.items()):
            if cat == "_root":
                results.append(f"\n[Root]")
            else:
                results.append(f"\n[{cat.upper()}]")
            
            for skill in sorted(skills):
                name = skill.stem
                results.append(f"  {name}")
                total += 1
        
        results.append(f"\n{'=' * 50}")
        results.append(f"{t('count', default='Gesamt')}: {total} Skills {t('skills_in_categories', default='in')} {len(categories)} {t('category', default='Kategorien')}")
        
        return True, "\n".join(results)
    
    def _show(self, name: str) -> tuple:
        """Skill-Details anzeigen."""
        found = self._find_skill(name)
        
        if not found:
            return False, f"{t('skill_not_found', default='Skill nicht gefunden')}: {name}\n{t('skills_use_list', default='Nutze')}: --skills list"
        
        results = [f"SKILL: {found.stem}", "=" * 50]
        results.append(f"Pfad: {found.relative_to(self.skills_dir)}")
        results.append(f"Groesse: {found.stat().st_size} Bytes")
        results.append("")
        
        # Inhalt anzeigen (max 50 Zeilen)
        try:
            content = found.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')[:50]
            results.extend(lines)
            if len(content.split('\n')) > 50:
                results.append(f"\n... ({len(content.split(chr(10))) - 50} weitere Zeilen)")
        except Exception as e:
            results.append(f"Fehler beim Lesen: {e}")
        
        return True, "\n".join(results)
    
    def _find_skill(self, name: str) -> Path:
        """Skill-Datei oder Verzeichnis finden."""
        name_lower = name.lower()
        
        # 1. Exakte Verzeichnis-Suche in agents/, agents/_experts, _services
        agents_dir = self.base_path / "agents"
        experts_dir = agents_dir / "_experts"

        for search_dir in [agents_dir, experts_dir, self.skills_dir / '_services']:
            skill_dir = search_dir / name
            if skill_dir.exists() and skill_dir.is_dir():
                return skill_dir
        
        # 2. Datei-Suche (.txt, .md)
        for suffix in ['.txt', '.md']:
            for skill_file in self.skills_dir.rglob(f"*{suffix}"):
                if name_lower in skill_file.stem.lower():
                    return skill_file
        
        return None
    
    def _search(self, term: str) -> tuple:
        """Skills nach Begriff durchsuchen."""
        results = [f"{t('skills_search_title', default='SKILL-SUCHE')}: '{term}'", "=" * 50]
        
        found = []
        term_lower = term.lower()
        
        for skill_file in self.skills_dir.rglob("*"):
            if skill_file.is_file() and skill_file.suffix in ['.txt', '.md']:
                # Im Namen suchen
                if term_lower in skill_file.stem.lower():
                    found.append((skill_file, "Name"))
                    continue
                
                # Im Inhalt suchen
                try:
                    content = skill_file.read_text(encoding='utf-8', errors='ignore').lower()
                    if term_lower in content:
                        found.append((skill_file, "Inhalt"))
                except:
                    pass
        
        if not found:
            results.append(f"{t('no_results', default='Keine Treffer')}: {term}")
        else:
            results.append(f"{t('search_results', default='Gefunden')}: {len(found)}\n")
            for skill, match_type in found[:20]:
                rel_path = skill.relative_to(self.skills_dir)
                results.append(f"  [{match_type}] {rel_path}")
            
            if len(found) > 20:
                results.append(f"\n  ... und {len(found) - 20} weitere")
        
        return True, "\n".join(results)
    
    def _export(self, name: str, output_dir: str = None, dry_run: bool = False, fmt: str = "bach") -> tuple:
        """
        Skill exportieren mit manifest.json.

        Args:
            name: Skill-Name (z.B. 'ati', 'steuer-agent')
            output_dir: Zielverzeichnis (optional, default: system/exports/<name>_export)
            dry_run: Nur zeigen was passieren wuerde
            fmt: Export-Format -- 'bach' (Standard), 'anthropic' oder 'agent' (Claude Code Agent)

        Returns:
            (success, message)
        """
        # Anthropic/Agent-Format: Delegiert an skill_export.py SkillExporter
        if fmt in ("anthropic", "agent"):
            try:
                from tools.skill_export import SkillExporter
                exporter = SkillExporter(self.base_path)
                return exporter.export(name, output_dir, dry_run, fmt=fmt)
            except ImportError:
                return False, "skill_export.py nicht gefunden. Pfad: tools/skill_export.py"
        results = [f"SKILL EXPORT: {name}", "=" * 50]
        
        # 1. Skill finden
        skill_path = self._find_skill(name)
        if not skill_path:
            return False, f"{t('skill_not_found', default='Skill nicht gefunden')}: {name}\n{t('skills_use_list', default='Nutze')}: --skills list"
        
        # Bestimme ob Verzeichnis oder Datei
        is_directory = skill_path.is_dir()
        
        # 2. Output-Verzeichnis bestimmen
        if output_dir:
            export_path = Path(output_dir)
        else:
            export_path = self.base_path / "exports" / f"{name}_export"
        
        results.append(f"Quelle: {skill_path}")
        results.append(f"Ziel: {export_path}")
        results.append(f"Typ: {'Verzeichnis' if is_directory else 'Datei'}")
        results.append("")
        
        # 3. Skill-Typ ermitteln
        skill_type = self._detect_skill_type(skill_path)
        results.append(f"Erkannter Typ: {skill_type}")
        
        # 4. Dateien sammeln die exportiert werden
        files_to_export = self._collect_export_files(skill_path, is_directory)
        results.append(f"Dateien: {len(files_to_export)}")
        
        # 5. Manifest generieren
        manifest = self._generate_manifest(name, skill_path, skill_type, files_to_export)
        
        results.append("")
        results.append("MANIFEST.JSON:")
        results.append("-" * 40)
        results.append(json.dumps(manifest, indent=2, ensure_ascii=False))
        results.append("-" * 40)
        
        if dry_run:
            results.append("")
            results.append("[DRY-RUN] Keine Dateien erstellt")
            results.append("Nutze ohne --dry-run zum tatsaechlichen Export")
            return True, "\n".join(results)
        
        # 6. Export durchfuehren - ZIP erstellen (v2.0 erweitert)
        try:
            # Export-Verzeichnis erstellen
            export_path.mkdir(parents=True, exist_ok=True)

            # ZIP-Dateiname
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{name}_v{manifest['version']}_{timestamp}.zip"
            zip_path = export_path / zip_filename

            results.append("")
            results.append("ZIP-ERSTELLUNG (v2.0 - autarkes Paket):")
            results.append("-" * 40)

            # README.md generieren
            readme_content = self._generate_standalone_readme(name, skill_type, manifest)

            # Skill-spezifische Tools und Workflows sammeln
            tools = self._collect_skill_specific_tools(skill_path) if is_directory else []
            workflows = self._collect_skill_specific_workflows(skill_path) if is_directory else []

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Manifest zuerst hinzufuegen
                manifest_content = json.dumps(manifest, indent=2, ensure_ascii=False)
                zipf.writestr("manifest.json", manifest_content)
                results.append("  + manifest.json")

                # README.md hinzufuegen
                zipf.writestr("README.md", readme_content)
                results.append("  + README.md (Standalone-Anleitung)")

                # Alle Skill-Dateien hinzufuegen
                for file_path in files_to_export:
                    # Relativer Pfad im ZIP
                    if is_directory:
                        # Bei Verzeichnis: relativ zum Skill-Verzeichnis
                        try:
                            arc_name = file_path.relative_to(skill_path)
                        except ValueError:
                            arc_name = file_path.name
                    else:
                        # Bei Einzeldatei: nur Dateiname
                        arc_name = file_path.name

                    # In skill/ Unterverzeichnis packen
                    arc_path = f"skill/{arc_name}"
                    zipf.write(file_path, arc_path)
                    results.append(f"  + {arc_path}")

                # Skill-spezifische Tools hinzufuegen (falls nicht schon enthalten)
                if tools:
                    results.append("")
                    results.append("  [Tools - skill-spezifisch]")
                    for tool_path, rel_name in tools:
                        arc_path = f"skill/tools/{Path(rel_name).name}"
                        # Pruefen ob nicht schon enthalten
                        if arc_path not in [n.filename for n in zipf.filelist]:
                            zipf.write(tool_path, arc_path)
                            results.append(f"  + {arc_path}")

                # Skill-spezifische Workflows hinzufuegen (falls nicht schon enthalten)
                if workflows:
                    results.append("")
                    results.append("  [Workflows - skill-spezifisch]")
                    for wf_path, rel_name in workflows:
                        arc_path = f"skill/workflows/{Path(rel_name).name}"
                        if arc_path not in [n.filename for n in zipf.filelist]:
                            zipf.write(wf_path, arc_path)
                            results.append(f"  + {arc_path}")

            # Statistik
            zip_size = zip_path.stat().st_size
            total_files = len(files_to_export) + 2 + len(tools) + len(workflows)  # +2 fuer manifest und readme
            results.append("-" * 40)
            results.append(f"ZIP erstellt: {zip_path.name}")
            results.append(f"Groesse: {zip_size / 1024:.1f} KB")
            results.append(f"Dateien: {total_files}")
            results.append("")
            results.append("[v2.0] Autarkes Paket - funktioniert ohne BACH!")
            results.append(f"[OK] Export erfolgreich: {zip_path}")

            # Auch manifest.json und README.md separat speichern fuer Referenz
            manifest_file = export_path / "manifest.json"
            manifest_file.write_text(manifest_content, encoding='utf-8')
            readme_file = export_path / "README.md"
            readme_file.write_text(readme_content, encoding='utf-8')

        except Exception as e:
            return False, f"ZIP-Erstellung fehlgeschlagen: {e}"
        
        return True, "\n".join(results)
    
    def _detect_skill_type(self, skill_path: Path) -> str:
        """Skill-Typ erkennen (agent, service, expert, skill)."""
        path_str = str(skill_path).lower()

        if '_experts' in path_str:
            return 'expert'
        elif 'agents' in path_str:
            return 'agent'
        elif '_services' in path_str:
            return 'service'
        elif 'workflows' in path_str:
            return 'protocol'
        else:
            return 'skill'
    
    def _collect_export_files(self, skill_path: Path, is_directory: bool) -> list:
        """Alle zu exportierenden Dateien sammeln (ohne pycache, hidden)."""
        files = []
        
        # Ausgeschlossene Patterns
        exclude_patterns = ['__pycache__', '.pyc', '.pyo', '.git', '.DS_Store']
        
        if is_directory:
            # Alle Dateien im Verzeichnis
            for f in skill_path.rglob("*"):
                if f.is_file() and not f.name.startswith('.'):
                    # Pruefen ob in exclude_patterns
                    skip = False
                    for pattern in exclude_patterns:
                        if pattern in str(f):
                            skip = True
                            break
                    if not skip:
                        files.append(f)
        else:
            # Einzelne Datei
            files.append(skill_path)
        
        return files
    
    def _extract_yaml_header(self, file_path: Path) -> dict:
        """
        YAML-Frontmatter aus einer Datei extrahieren.

        Sucht nach:
        ---
        key: value
        ---

        Returns:
            dict mit Header-Feldern oder leeres dict
        """
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')

            # YAML-Frontmatter Pattern (nur wenn yaml verfügbar)
            if yaml:
                yaml_pattern = r'^---\s*\n(.*?)\n---'
                match = re.search(yaml_pattern, content, re.DOTALL)

                if match:
                    yaml_content = match.group(1)
                    try:
                        return yaml.safe_load(yaml_content) or {}
                    except yaml.YAMLError:
                        pass

            # Fallback: Python __version__ suchen
            version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            if version_match:
                return {'version': version_match.group(1)}

            # Fallback: Version: X.Y.Z im Header-Kommentar
            version_comment = re.search(r'Version:\s*(\d+\.\d+\.\d+)', content[:500])
            if version_comment:
                return {'version': version_comment.group(1)}

        except Exception:
            pass

        return {}

    def _collect_skill_specific_tools(self, skill_path: Path) -> list:
        """
        Skill-spezifische Tools im Skill-Ordner finden.

        Sucht nach:
        - *.py Dateien im Skill-Root
        - tools/ Unterverzeichnis

        Returns:
            Liste von (Path, relative_name) Tupeln
        """
        tools = []

        if not skill_path.is_dir():
            return tools

        # Python-Dateien im Root (ausser __init__.py)
        for py_file in skill_path.glob("*.py"):
            if py_file.name != "__init__.py":
                tools.append((py_file, py_file.name))

        # tools/ Unterverzeichnis
        tools_dir = skill_path / "tools"
        if tools_dir.exists():
            for py_file in tools_dir.rglob("*.py"):
                if "__pycache__" not in str(py_file) and py_file.name != "__init__.py":
                    rel_path = py_file.relative_to(skill_path)
                    tools.append((py_file, str(rel_path).replace('\\', '/')))

        return tools

    def _collect_skill_specific_workflows(self, skill_path: Path) -> list:
        """
        Skill-spezifische Workflows im Skill-Ordner finden.

        Sucht nach:
        - workflow_*.md Dateien im Root
        - workflows/ Unterverzeichnis

        Returns:
            Liste von (Path, relative_name) Tupeln
        """
        workflows = []

        if not skill_path.is_dir():
            return workflows

        # Workflow-Dateien im Root
        for wf_file in skill_path.glob("workflow_*.md"):
            workflows.append((wf_file, wf_file.name))

        # workflows/ Unterverzeichnis
        workflows_dir = skill_path / "workflows"
        if workflows_dir.exists():
            for wf_file in workflows_dir.rglob("*.md"):
                rel_path = wf_file.relative_to(skill_path)
                workflows.append((wf_file, str(rel_path).replace('\\', '/')))

        return workflows

    def _generate_standalone_readme(self, name: str, skill_type: str, manifest: dict) -> str:
        """
        README.md für Standalone-Nutzung generieren.

        Enthält:
        - Beschreibung
        - Installation
        - Verwendung ohne BACH
        - Abhängigkeiten
        """
        tools = manifest.get('includes', {}).get('tools', [])
        workflows = manifest.get('includes', {}).get('workflows', [])
        packages = manifest.get('dependencies', {}).get('packages', [])

        readme = f"""# {name}

> BACH {skill_type.title()} - Standalone Export

**Version:** {manifest.get('version', '1.0.0')}
**Exportiert:** {manifest.get('created_at', 'N/A')}
**Anthropic-Compatible:** True

## Beschreibung

{manifest.get('description', f'BACH {skill_type}: {name}')}

## Installation (ohne BACH)

1. Entpacken Sie das ZIP-Archiv
2. Kopieren Sie den Inhalt an den gewünschten Ort
3. Installieren Sie die Abhängigkeiten (falls vorhanden)

## Verwendung

### Als Prompt-Erweiterung

Die `SKILL.md` Datei kann direkt in einen LLM-Prompt eingefügt werden:

```
# Fügen Sie den Inhalt von SKILL.md zu Ihrem System-Prompt hinzu
```

"""
        if tools:
            readme += """### Enthaltene Tools

"""
            for tool in tools:
                readme += f"- `{tool}`\n"
            readme += "\n"

        if workflows:
            readme += """### Enthaltene Workflows

"""
            for wf in workflows:
                readme += f"- `{wf}`\n"
            readme += "\n"

        if packages:
            readme += """## Abhängigkeiten

```bash
pip install """
            readme += " ".join(packages)
            readme += """
```

"""

        readme += f"""## Versions-Check

Prüfen Sie auf neuere Versionen:
- Lokale Version: {manifest.get('version', '1.0.0')}
- BACH-Befehl: `bach skills version {name}`

## Lizenz

Dieses Skill-Paket wurde mit BACH exportiert.
Weitere Informationen: https://github.com/anthropics/skills

---
*Generiert von BACH Export v2.0*
"""
        return readme

    def _generate_manifest(self, name: str, skill_path: Path, skill_type: str, files: list) -> dict:
        """
        Export-Manifest (manifest.json) generieren - v2.0 erweitert.

        Das Manifest enthaelt:
        - Metadaten (Name, Version aus YAML-Header, Typ, Beschreibung)
        - includes: core, tools, workflows
        - dependencies: Python-Version, Packages
        - entry_points: Wie der Skill gestartet wird
        - version_check: Hinweis auf Versions-Prüfung
        - anthropic_compatible: True
        """
        # Version und Metadaten aus YAML-Header extrahieren
        header_data = {}
        skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
        if skill_md.exists():
            header_data = self._extract_yaml_header(skill_md)

        # Fallback: Aus anderen Dateien versuchen
        if not header_data.get('version'):
            for f in files:
                if f.suffix in ['.md', '.py']:
                    header_data = self._extract_yaml_header(f)
                    if header_data.get('version'):
                        break

        # Beschreibung extrahieren
        description = header_data.get('description', '')
        if not description:
            for f in files:
                if f.suffix in ['.md', '.txt']:
                    try:
                        content = f.read_text(encoding='utf-8', errors='ignore')
                        # Nach YAML-Header suchen
                        if content.startswith('---'):
                            # Überspringe YAML-Block
                            parts = content.split('---', 2)
                            if len(parts) >= 3:
                                content = parts[2]
                        first_line = content.strip().split('\n')[0].strip()
                        if first_line.startswith('#'):
                            description = first_line.lstrip('# ').strip()
                        elif first_line:
                            description = first_line[:100]
                        if description:
                            break
                    except:
                        pass

        # Relative Pfade fuer includes
        core_includes = []
        try:
            for f in files:
                rel = f.relative_to(self.skills_dir)
                core_includes.append(str(rel).replace('\\', '/'))
        except:
            core_includes = [f.name for f in files]

        # Skill-spezifische Tools und Workflows sammeln
        tools = self._collect_skill_specific_tools(skill_path) if skill_path.is_dir() else []
        workflows = self._collect_skill_specific_workflows(skill_path) if skill_path.is_dir() else []

        manifest = {
            "name": name,
            "version": header_data.get('version', '1.0.0'),
            "type": skill_type,
            "description": description or f"BACH {skill_type}: {name}",
            "author": header_data.get('author', 'BACH Team'),
            "created_at": datetime.now().isoformat(),
            "bach_version": "2.0.0",
            "anthropic_compatible": header_data.get('anthropic_compatible', True),

            "version_check": {
                "enabled": True,
                "hint": f"Prüfe auf neuere Versionen mit: bach skills version {name}"
            },

            "includes": {
                "core": core_includes,
                "tools": [t[1] for t in tools],
                "workflows": [w[1] for w in workflows]
            },

            "dependencies": {
                "python": ">=3.9",
                "packages": header_data.get('dependencies', {}).get('packages', []) if isinstance(header_data.get('dependencies'), dict) else []
            },

            "entry_points": {}
        }

        # Type-spezifische Entry-Points
        if skill_type == 'agent':
            manifest["entry_points"] = {
                "main": "SKILL.md",
                "description": f"Agenten-Definition für {name}"
            }
        elif skill_type == 'expert':
            manifest["entry_points"] = {
                "main": "SKILL.md",
                "description": f"Experten-Wissen für {name}"
            }
        elif skill_type == 'service':
            manifest["entry_points"] = {
                "main": "SKILL.md",
                "handler": f"hub/handlers/{name}.py" if (self.base_path / "hub" / "handlers" / f"{name}.py").exists() else None
            }

        return manifest
    
    def _install(self, path: str, dry_run: bool = False) -> tuple:
        """
        Skill aus Export-ZIP oder Verzeichnis importieren.
        
        Args:
            path: Pfad zur ZIP-Datei oder zum Verzeichnis mit manifest.json
            dry_run: Nur zeigen was passieren wuerde
        
        Returns:
            (success, message)
        """
        import shutil
        import tempfile
        
        results = [f"SKILL INSTALL", "=" * 50]
        source_path = Path(path)
        
        # 1. Quelle pruefen
        if not source_path.exists():
            return False, f"Pfad nicht gefunden: {path}"
        
        results.append(f"Quelle: {source_path}")
        
        temp_dir = None
        manifest_dir = None
        
        try:
            # 2. ZIP oder Verzeichnis?
            if source_path.suffix.lower() == '.zip':
                results.append("Typ: ZIP-Archiv")
                
                # ZIP in temp-Verzeichnis entpacken
                temp_dir = Path(tempfile.mkdtemp(prefix="bach_skill_"))
                results.append(f"Entpacke nach: {temp_dir}")
                
                with zipfile.ZipFile(source_path, 'r') as zipf:
                    zipf.extractall(temp_dir)
                
                manifest_dir = temp_dir
            else:
                results.append("Typ: Verzeichnis")
                manifest_dir = source_path
            
            # 3. Manifest lesen
            manifest_path = manifest_dir / "manifest.json"
            if not manifest_path.exists():
                return False, f"Keine manifest.json gefunden in: {manifest_dir}"
            
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            results.append("")
            results.append("MANIFEST:")
            results.append(f"  Name: {manifest.get('name', 'unbekannt')}")
            results.append(f"  Version: {manifest.get('version', '?')}")
            results.append(f"  Typ: {manifest.get('type', 'skill')}")
            results.append(f"  Beschreibung: {manifest.get('description', '-')[:60]}")
            
            # 4. Zielverzeichnis bestimmen
            skill_name = manifest.get('name', source_path.stem)
            skill_type = manifest.get('type', 'skill')
            
            # Typ zu Zielverzeichnis mappen (v2.5 Restructuring)
            if skill_type == 'agent':
                target_path = self.base_path / "agents" / skill_name
            elif skill_type == 'expert':
                target_path = self.base_path / "agents" / "_experts" / skill_name
            elif skill_type == 'service':
                target_path = self.skills_dir / "_services" / skill_name
            else:
                target_path = self.skills_dir / skill_name
            
            results.append("")
            results.append(f"Zielverzeichnis: {target_path}")
            
            # 5. Pruefen ob bereits existiert
            if target_path.exists():
                results.append("[!] Skill existiert bereits")
                if not dry_run:
                    # Backup erstellen
                    backup_name = f"{skill_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    backup_path = self.base_path / "exports" / "_backups" / backup_name
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target_path), str(backup_path))
                    results.append(f"    Backup erstellt: {backup_path}")
            
            # 6. Skill-Dateien finden
            skill_source = manifest_dir / "skill"
            if not skill_source.exists():
                # Fallback: Dateien direkt im manifest_dir
                skill_source = manifest_dir

            from core.capabilities import capability_manager
            scan_report = capability_manager.scan_tree(manifest_dir)
            blocking_findings, warning_findings = capability_manager.categorize_scan_findings(scan_report)

            if blocking_findings:
                quarantine_dir = capability_manager.quarantine_path(
                    source_path,
                    self.base_path,
                    "skill",
                    scan_report,
                    f"skills install blocked: {skill_name}",
                    metadata={
                        "manifest_path": str(manifest_path),
                        "scan_root": str(manifest_dir),
                        "type": skill_type,
                    },
                )
                results.append("")
                results.append("SECURITY-SCAN:")
                results.append("  [BLOCK] Install abgebrochen.")
                results.append(f"  Quarantaene: {quarantine_dir}")
                for finding in blocking_findings[:10]:
                    results.append(f"  - {finding}")
                if len(blocking_findings) > 10:
                    results.append(f"  - ... und {len(blocking_findings) - 10} weitere")
                return False, "\n".join(results)

            if warning_findings:
                results.append("")
                results.append("SECURITY-SCAN:")
                results.append(f"  [WARN] {len(warning_findings)} Hinweis(e) im Importpaket")
                for finding in warning_findings[:5]:
                    results.append(f"  - {finding}")
            
            # Dateien zaehlen
            files_to_copy = list(skill_source.rglob("*"))
            files_to_copy = [f for f in files_to_copy if f.is_file() 
                           and f.name != 'manifest.json'
                           and '__pycache__' not in str(f)]
            
            results.append(f"Dateien zu kopieren: {len(files_to_copy)}")
            
            if dry_run:
                results.append("")
                results.append("[DRY-RUN] Dateien die kopiert wuerden:")
                for f in files_to_copy[:10]:
                    try:
                        rel = f.relative_to(skill_source)
                    except ValueError:
                        rel = f.name
                    results.append(f"  - {rel}")
                if len(files_to_copy) > 10:
                    results.append(f"  ... und {len(files_to_copy) - 10} weitere")
                results.append("")
                results.append("[DRY-RUN] Keine Dateien kopiert")
                results.append("Nutze ohne --dry-run zum tatsaechlichen Import")
                return True, "\n".join(results)
            
            # 7. Kopieren
            results.append("")
            results.append("KOPIERE DATEIEN:")
            results.append("-" * 40)
            
            target_path.mkdir(parents=True, exist_ok=True)
            
            copied = 0
            for src_file in files_to_copy:
                try:
                    rel_path = src_file.relative_to(skill_source)
                except ValueError:
                    rel_path = Path(src_file.name)
                
                dest_file = target_path / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)
                results.append(f"  + {rel_path}")
                copied += 1
            
            # 8. Manifest auch kopieren
            manifest_dest = target_path / "manifest.json"
            shutil.copy2(manifest_path, manifest_dest)
            results.append("  + manifest.json")
            
            results.append("-" * 40)
            results.append(f"Kopiert: {copied + 1} Dateien")
            results.append("")
            results.append(f"[OK] Skill '{skill_name}' erfolgreich installiert!")
            results.append(f"    Pfad: {target_path}")
            
            # 9. Dependencies Info
            deps = manifest.get('dependencies', {})
            packages = deps.get('packages', [])
            if packages:
                results.append("")
                results.append("[INFO] Abhaengigkeiten:")
                for pkg in packages:
                    results.append(f"  pip install {pkg}")
            
        except json.JSONDecodeError as e:
            return False, f"Ungueltige manifest.json: {e}"
        except Exception as e:
            return False, f"Install fehlgeschlagen: {e}"
        finally:
            # Temp-Verzeichnis aufraeumen
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

        return True, "\n".join(results)

    def _create(self, name: str, skill_type: str = "expert", dry_run: bool = False, fmt: str = None) -> tuple:
        """
        Neuen Skill erstellen (v2.1 Self-Extension).

        Scaffoldet Verzeichnisstruktur + SKILL.md + manifest.json.
        Registriert in DB. Ermoeglicht autonome Erweiterung durch KI-Partner.

        Args:
            name: Skill-Name (z.B. 'voice-processor', 'email-parser')
            skill_type: agent|expert|service|tool|handler
            dry_run: Nur zeigen was passieren wuerde
            fmt: Optionales Format -- 'anthropic' nutzt skill_init.py fuer Anthropic-Standard

        Returns:
            (success, message)
        """
        # Anthropic-Format: Delegiert an skill_init.py
        if fmt and fmt.lower() == "anthropic":
            return self._create_anthropic(name, dry_run)

        results = [f"SKILL CREATE: {name}", "=" * 50]
        results.append(f"Typ: {skill_type}")

        # Tool-Typ: Einzelne Python-Datei in tools/
        if skill_type == "tool":
            tool_path = self.base_path / "tools" / f"{name}.py"
            results.append(f"Ziel: {tool_path}")

            if tool_path.exists():
                return False, f"Tool existiert bereits: {tool_path}"

            if dry_run:
                results.append("\n[DRY-RUN] Wuerde erstellen:")
                results.append(f"  tools/{name}.py")
                return True, "\n".join(results)

            tool_content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool: {name}
Version: 1.0.0
Author: BACH Self-Extension
Created: {datetime.now().strftime('%Y-%m-%d')}
Anthropic-Compatible: True

Description:
    [Beschreibung hier einfuegen]

Usage:
    python {name}.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Self-Extension"

import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


def main():
    """Hauptfunktion."""
    # TODO: Implementierung hier
    print(f"[{name}] Tool gestartet")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
'''
            tool_path.write_text(tool_content, encoding='utf-8')
            results.append(f"\n[OK] Tool erstellt: {tool_path}")
            results.append(f"\nNaechste Schritte:")
            results.append(f"  1. Implementierung in {tool_path} ergaenzen")
            results.append(f"  2. bach skills reload  (Tool registrieren)")
            return True, "\n".join(results)

        # Handler-Typ: Python-Datei in hub/
        if skill_type == "handler":
            handler_path = self.base_path / "hub" / f"{name}.py"
            results.append(f"Ziel: {handler_path}")

            if handler_path.exists():
                return False, f"Handler existiert bereits: {handler_path}"

            if dry_run:
                results.append("\n[DRY-RUN] Wuerde erstellen:")
                results.append(f"  hub/{name}.py")
                return True, "\n".join(results)

            handler_content = f'''"""
{name.title()} Handler - [Beschreibung]
{'=' * 40}

bach {name} list          Alle auflisten
bach {name} add <args>    Neuen Eintrag erstellen
bach {name} show <id>     Details anzeigen
"""
from pathlib import Path
from .base import BaseHandler


class {name.title().replace('-', '').replace('_', '')}Handler(BaseHandler):
    """Handler fuer --{name}"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "{name}"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data"

    def get_operations(self) -> dict:
        return {{
            "list": "Alle auflisten",
            "add": "Neuen Eintrag erstellen",
            "show": "Details anzeigen",
        }}

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list" or not operation:
            return True, "[{name.upper()}] TODO: Implementierung"
        elif operation == "add" and args:
            return True, f"[{name.upper()}] TODO: Add {{args}}"
        elif operation == "show" and args:
            return True, f"[{name.upper()}] TODO: Show {{args[0]}}"
        else:
            ops = "\\n".join(f"  {{k}}: {{v}}" for k, v in self.get_operations().items())
            return False, f"Unbekannte Operation: {{operation}}\\n\\n{{ops}}"
'''
            handler_path.write_text(handler_content, encoding='utf-8')
            results.append(f"\n[OK] Handler erstellt: {handler_path}")
            results.append(f"\nNaechste Schritte:")
            results.append(f"  1. Implementierung in {handler_path} ergaenzen")
            results.append(f"  2. bach skills reload  (Handler registrieren)")
            results.append(f"  3. bach {name} list    (Testen)")
            return True, "\n".join(results)

        # Agent/Expert/Service: Verzeichnis mit SKILL.md (v2.5)
        if skill_type == "agent":
            skill_dir = self.base_path / "agents" / name
            subdir = "agents"
        elif skill_type == "expert":
            skill_dir = self.base_path / "agents" / "_experts" / name
            subdir = "agents/_experts"
        else:
            skill_dir = self.skills_dir / "_services" / name
            subdir = "skills/_services"
        results.append(f"Ziel: {skill_dir}")

        if skill_dir.exists():
            return False, f"Skill existiert bereits: {skill_dir}"

        if dry_run:
            results.append("\n[DRY-RUN] Wuerde erstellen:")
            results.append(f"  {subdir}/{name}/SKILL.md")
            results.append(f"  {subdir}/{name}/manifest.json")
            if skill_type == "agent":
                results.append(f"  {subdir}/{name}/tools/  (Verzeichnis)")
            return True, "\n".join(results)

        # Verzeichnis erstellen
        skill_dir.mkdir(parents=True, exist_ok=True)

        # SKILL.md generieren
        skill_md = f"""---
name: {name}
version: 1.0.0
description: [Beschreibung hier einfuegen]
last_updated: {datetime.now().strftime('%Y-%m-%d')}
author: BACH Self-Extension
anthropic_compatible: true
---

# {name.replace('-', ' ').replace('_', ' ').title()}

> [Einzeiler: Was macht dieser {skill_type.title()}?]

## Rolle

[Beschreibung der Rolle und Verantwortlichkeiten]

## Kernbefehle

| Befehl | Beschreibung |
|--------|-------------|
| TODO | Befehle definieren |

## Regeln

1. [Regel 1]
2. [Regel 2]

## Kontext

[Wann wird dieser {skill_type.title()} aktiviert?]

---

*Erstellt mit BACH Self-Extension v2.1*
"""
        (skill_dir / "SKILL.md").write_text(skill_md, encoding='utf-8')

        # manifest.json generieren
        manifest = {
            "name": name,
            "version": "1.0.0",
            "type": skill_type,
            "description": f"BACH {skill_type}: {name}",
            "author": "BACH Self-Extension",
            "created_at": datetime.now().isoformat(),
            "bach_version": "2.1.0",
            "anthropic_compatible": True,
            "entry_points": {"main": "SKILL.md"},
        }
        (skill_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8'
        )

        # Bei Agents: tools/ Unterverzeichnis
        if skill_type == "agent":
            (skill_dir / "tools").mkdir(exist_ok=True)

        # In DB registrieren
        self._register_in_db(name, skill_type, str(skill_dir))

        results.append(f"\n[OK] {skill_type.title()} erstellt:")
        results.append(f"  SKILL.md:      {skill_dir / 'SKILL.md'}")
        results.append(f"  manifest.json: {skill_dir / 'manifest.json'}")
        if skill_type == "agent":
            results.append(f"  tools/:        {skill_dir / 'tools'}")
        results.append(f"\nNaechste Schritte:")
        results.append(f"  1. SKILL.md mit Inhalt fuellen")
        results.append(f"  2. bach skills reload  (Registrierung aktualisieren)")
        results.append(f"  3. bach skills show {name}  (Pruefen)")

        # Hook: after_skill_create
        try:
            from core.hooks import hooks
            hooks.emit('after_skill_create', {
                'name': name, 'type': skill_type, 'path': str(skill_dir)
            })
        except Exception:
            pass

        return True, "\n".join(results)

    def _create_anthropic(self, name: str, dry_run: bool = False) -> tuple:
        """
        Erstellt einen Skill im Anthropic-Standard-Format via skill_init.py.

        Erzeugt: SKILL.md + scripts/ + references/ + assets/
        Kompatibel mit: Claude Code, LobeHub, Cursor, Codex CLI
        """
        results = [f"SKILL CREATE (Anthropic-Format): {name}", "=" * 50]

        # Zielverzeichnis: skills/_services/<name> (integriert in BACH)
        output_path = self.skills_dir / "_services"
        skill_dir = output_path / name

        results.append(f"Format: Anthropic (scripts/ + references/ + assets/)")
        results.append(f"Ziel: {skill_dir}")

        if skill_dir.exists():
            return False, f"Skill existiert bereits: {skill_dir}"

        if dry_run:
            results.append("\n[DRY-RUN] Wuerde erstellen:")
            results.append(f"  {name}/SKILL.md")
            results.append(f"  {name}/scripts/example.py")
            results.append(f"  {name}/references/api_reference.md")
            results.append(f"  {name}/assets/example_asset.txt")
            return True, "\n".join(results)

        # skill_init.py aufrufen
        skill_init_path = self.base_path / "tools" / "skills" / "skill_init.py"

        if not skill_init_path.exists():
            return False, f"skill_init.py nicht gefunden: {skill_init_path}"

        try:
            # skill_init.py als Modul importieren und init_skill() aufrufen
            import importlib.util
            spec = importlib.util.spec_from_file_location("skill_init", skill_init_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            result_path = mod.init_skill(name, str(output_path))

            if result_path is None:
                return False, f"skill_init.py Fehler bei Erstellung von '{name}'"

            # In DB registrieren
            self._register_in_db(name, "skill", str(skill_dir))

            results.append(f"\n[OK] Anthropic-Skill erstellt:")
            results.append(f"  SKILL.md:             {skill_dir / 'SKILL.md'}")
            results.append(f"  scripts/example.py:   {skill_dir / 'scripts' / 'example.py'}")
            results.append(f"  references/:          {skill_dir / 'references'}")
            results.append(f"  assets/:              {skill_dir / 'assets'}")
            results.append(f"\nNaechste Schritte:")
            results.append(f"  1. SKILL.md TODO-Items ausfuellen")
            results.append(f"  2. Beispieldateien anpassen oder loeschen")
            results.append(f"  3. bach skills reload  (Registrierung aktualisieren)")
            results.append(f"\nDieser Skill ist standalone-faehig und kompatibel mit:")
            results.append(f"  Claude Code, LobeHub Marketplace, Cursor, Codex CLI")

            # Hook: after_skill_create
            try:
                from core.hooks import hooks
                hooks.emit('after_skill_create', {
                    'name': name, 'type': 'skill', 'format': 'anthropic',
                    'path': str(skill_dir)
                })
            except Exception:
                pass

            return True, "\n".join(results)

        except Exception as e:
            return False, f"Fehler bei Anthropic-Skill-Erstellung: {e}"

    def _register_in_db(self, name: str, skill_type: str, path: str):
        """Registriert einen Skill in der Datenbank."""
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return

        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # In skills Tabelle einfuegen (falls existent)
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='skills'
            """)
            if cursor.fetchone():
                cursor.execute("""
                    INSERT OR REPLACE INTO skills (name, type, path, description, is_active, version, dist_type)
                    VALUES (?, ?, ?, ?, 1, '1.0.0', 0)
                """, (name, skill_type, path, f"BACH {skill_type}: {name}"))

            conn.commit()
            conn.close()
        except Exception:
            pass  # Leises Versagen - DB-Registration ist optional

    def _reload(self) -> tuple:
        """
        Hot-Reload: Handler-Registry + Tool-Auto-Discovery neu ausfuehren.

        Ermoeglicht das Hinzufuegen neuer Handler/Tools/Skills ohne Neustart.
        """
        results = ["SKILLS RELOAD (Hot-Reload)", "=" * 50]

        # 1. Handler-Registry neu laden
        results.append("\n[1/3] Handler-Registry neu laden...")
        try:
            from core.app import App
            from core.aliases import COMMAND_ALIASES
            app = App(self.base_path)
            count = app.reload_registry()
            results.append(f"  [OK] {count} Handler entdeckt")
        except Exception as e:
            results.append(f"  [WARN] Registry-Reload: {e}")

        # 2. Tool-Auto-Discovery ausfuehren
        results.append("\n[2/3] Tool-Auto-Discovery...")
        discovery_script = self.base_path / "tools" / "tool_auto_discovery.py"
        if discovery_script.exists():
            try:
                import os
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                process = subprocess.run(
                    [sys.executable, str(discovery_script)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(self.base_path),
                    env=env
                )
                if process.stdout:
                    for line in process.stdout.strip().split('\n'):
                        results.append(f"  {line}")
                if process.returncode != 0 and process.stderr:
                    results.append(f"  [WARN] {process.stderr[:200]}")
            except Exception as e:
                results.append(f"  [WARN] Auto-Discovery: {e}")
        else:
            results.append("  [SKIP] tool_auto_discovery.py nicht gefunden")

        # 3. Skills-Verzeichnis scannen und Statistik
        results.append("\n[3/3] Skills-Verzeichnis scannen...")
        skill_counts = {}
        # Scan agents/, agents/_experts, skills/_services, skills/workflows
        scan_dirs = {
            'agents': self.base_path / "agents",
            'experts': self.base_path / "agents" / "_experts",
            'services': self.skills_dir / "_services",
            'protocols': self.skills_dir / "workflows",
            'connectors': self.base_path / "connectors",
        }
        for label, subpath in scan_dirs.items():
            if subpath.exists():
                items = [d for d in subpath.iterdir()
                         if d.is_dir() and not d.name.startswith('_')]
                if not items:
                    items = [f for f in subpath.iterdir()
                             if f.is_file() and f.suffix in ('.md', '.txt')]
                skill_counts[label] = len(items)

        for cat, count in skill_counts.items():
            results.append(f"  {cat}: {count}")

        tools_count = len(list((self.base_path / "tools").glob("*.py")))
        results.append(f"  tools: {tools_count}")

        results.append(f"\n{'=' * 50}")
        results.append("[OK] Hot-Reload abgeschlossen!")
        results.append("Neue Handler/Tools sind jetzt verfuegbar.")

        # Hook: after_skill_reload
        try:
            from core.hooks import hooks
            hooks.emit('after_skill_reload', {
                'handler_count': count if 'count' in dir() else 0,
                'skill_counts': skill_counts
            })
        except Exception:
            pass

        return True, "\n".join(results)

    def _hierarchy(self, type_filter: str = None) -> tuple:
        """
        Hierarchie aus DB anzeigen (hierarchy_items Tabelle).

        Args:
            type_filter: Optional - nur diesen Typ anzeigen (agent/expert/skill/service/workflow)

        Returns:
            (success, message)
        """
        db_path = self.base_path / "data" / "bach.db"

        if not db_path.exists():
            return False, f"Datenbank nicht gefunden: {db_path}"

        results = ["SKILLS HIERARCHIE", "=" * 60]

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Pruefen ob Tabelle existiert
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='hierarchy_items'
            """)
            if not cursor.fetchone():
                return False, "hierarchy_items Tabelle nicht gefunden.\nFuehre erst Migration aus: python tools/migration/migrate_skills_hierarchy.py"

            # Typ-Statistik
            results.append("")
            cursor.execute("""
                SELECT type, COUNT(*) as cnt
                FROM hierarchy_items
                WHERE status = 'active'
                GROUP BY type
                ORDER BY type
            """)
            type_stats = cursor.fetchall()

            results.append("UEBERSICHT:")
            for t, cnt in type_stats:
                marker = " <--" if type_filter and t == type_filter else ""
                results.append(f"  {t:12} {cnt:4} Items{marker}")
            results.append("")

            # Items abfragen
            if type_filter:
                cursor.execute("""
                    SELECT id, type, name, description, status
                    FROM hierarchy_items
                    WHERE type = ? AND status = 'active'
                    ORDER BY name
                """, (type_filter,))
            else:
                cursor.execute("""
                    SELECT id, type, name, description, status
                    FROM hierarchy_items
                    WHERE status = 'active'
                    ORDER BY type, name
                """)

            items = cursor.fetchall()

            if not items:
                results.append("Keine Items gefunden.")
                conn.close()
                return True, "\n".join(results)

            # Nach Typ gruppiert ausgeben
            current_type = None
            for item_id, item_type, name, desc, status in items:
                if item_type != current_type:
                    current_type = item_type
                    results.append(f"\n[{item_type.upper()}]")
                    results.append("-" * 40)

                desc_short = (desc[:45] + "...") if desc and len(desc) > 45 else (desc or "")
                results.append(f"  {item_id:30} {desc_short}")

            # Zuweisungen anzeigen wenn kein Filter
            if not type_filter:
                results.append("")
                results.append("=" * 60)
                results.append("ZUWEISUNGEN (Agent -> Expert/Service):")
                results.append("-" * 40)

                cursor.execute("""
                    SELECT
                        ha.parent_id,
                        ha.child_id,
                        ha.child_type,
                        hi.name as child_name
                    FROM hierarchy_assignments ha
                    JOIN hierarchy_items hi ON hi.id = ha.child_id
                    ORDER BY ha.parent_id, ha.child_type
                """)

                assignments = cursor.fetchall()
                current_parent = None
                for parent_id, child_id, child_type, child_name in assignments:
                    if parent_id != current_parent:
                        current_parent = parent_id
                        results.append(f"\n  {parent_id}:")
                    results.append(f"    -> [{child_type}] {child_name}")

            results.append("")
            results.append(f"Gesamt: {len(items)} Items")

            conn.close()

        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        except Exception as e:
            return False, f"Fehler: {e}"

        return True, "\n".join(results)

    def _version_check(self, name: str) -> tuple:
        """
        Versions-Check für einen Skill (v2.0).

        Vergleicht:
        - Lokale Version (aus YAML-Header)
        - Zentrale Version (falls verfügbar)

        Prinzip: Immer die höchste Versionsnummer verwenden!

        Args:
            name: Skill-Name

        Returns:
            (success, message)
        """
        results = [f"VERSION CHECK: {name}", "=" * 50]

        # 1. Skill finden
        skill_path = self._find_skill(name)
        if not skill_path:
            return False, f"{t('skill_not_found', default='Skill nicht gefunden')}: {name}\n{t('skills_use_list', default='Nutze')}: --skills list"

        results.append(f"Pfad: {skill_path}")
        results.append("")

        # 2. Lokale Version ermitteln
        local_version = "0.0.0"
        skill_file = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path

        if skill_file.exists():
            header = self._extract_yaml_header(skill_file)
            local_version = header.get('version', '0.0.0')

        results.append(f"LOKAL:   v{local_version}")

        # 3. Zentrale Version aus skill_sources.json prüfen
        central_version = None
        sources_file = self.base_path / "data" / "skill_sources.json"

        if sources_file.exists():
            try:
                sources = json.loads(sources_file.read_text(encoding='utf-8'))
                # In trusted_sources nach dem Skill suchen
                for source_type in ['goldstandard', 'trusted_sources']:
                    for source in sources.get(source_type, []):
                        if name.lower() in source.get('name', '').lower():
                            central_version = source.get('version')
                            if central_version:
                                results.append(f"ZENTRAL: v{central_version} ({source.get('source', 'unbekannt')})")
                            break
            except:
                pass

        if not central_version:
            results.append("ZENTRAL: (nicht registriert)")

        # 4. Versionen vergleichen
        results.append("")
        results.append("-" * 40)

        def parse_version(v: str) -> tuple:
            """Version in Tupel umwandeln für Vergleich."""
            try:
                parts = v.replace('v', '').split('.')
                return tuple(int(p) for p in parts[:3])
            except:
                return (0, 0, 0)

        local_tuple = parse_version(local_version)
        central_tuple = parse_version(central_version) if central_version else (0, 0, 0)

        if central_version and central_tuple > local_tuple:
            results.append(f"[!] NEUERE VERSION VERFUEGBAR!")
            results.append(f"    Zentral: v{central_version} > Lokal: v{local_version}")
            results.append("")
            results.append("Empfehlung: Aktualisiere auf die zentrale Version")
        elif central_version and local_tuple > central_tuple:
            results.append(f"[i] Lokale Version ist neuer!")
            results.append(f"    Lokal: v{local_version} > Zentral: v{central_version}")
            results.append("")
            results.append("Hinweis: Lokale Änderungen sollten ggf. upstream gepusht werden")
        else:
            results.append(f"[OK] Version aktuell: v{local_version}")

        # 5. Zusätzliche Metadaten anzeigen
        if skill_file.exists():
            header = self._extract_yaml_header(skill_file)
            results.append("")
            results.append("METADATEN:")
            if header.get('author'):
                results.append(f"  Author: {header.get('author')}")
            if header.get('updated'):
                results.append(f"  Updated: {header.get('updated')}")
            if header.get('anthropic_compatible') is not None:
                results.append(f"  Anthropic-Compatible: {header.get('anthropic_compatible')}")

        results.append("")
        results.append("VERSIONS-HINWEIS:")
        results.append("  Verwende IMMER die höchste Versionsnummer,")
        results.append("  egal ob lokal oder zentral!")

        return True, "\n".join(results)
