#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Tool: skill_help_gen
Version: 1.0.0
Author: BACH Team
Created: 2026-02-08
Updated: 2026-02-08
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version skill_help_gen

skill_help_gen.py - Auto-Help-Generierung fuer Skills
======================================================

Liest SKILL.md Dateien und generiert passende docs/help/*.txt Eintraege
im BACH-Help-Format.

Usage:
    python skill_help_gen.py --skill <name>          Einzelnen Skill
    python skill_help_gen.py --all                   Alle Skills
    python skill_help_gen.py --dry-run               Nur anzeigen

    Oder via BACH CLI:
    bach --maintain skill-help [name|--all] [--dry-run]

Help-Datei-Format (BACH Standard):
    Zeile 1-5:   Metadaten-Kommentare (Portabilitaet, Version, etc.)
    Titel:       NAME IN GROSSBUCHSTABEN
    Abschnitte:  UEBERSICHT, BEFEHLE, BEISPIELE, SIEHE AUCH
"""

import sys
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

# Pfade
SCRIPT_DIR = Path(__file__).parent
SYSTEM_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = SYSTEM_ROOT / "skills"
HELP_DIR = SYSTEM_ROOT / "help"


class HelpGenerator:
    """Generiert Help-Dateien aus SKILL.md."""

    def __init__(self, system_root: Path):
        self.system_root = system_root
        self.skills_dir = system_root / "skills"
        self.help_dir = system_root / "help"

    def generate_for_skill(self, name: str, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Generiert eine Help-Datei fuer einen einzelnen Skill.

        Args:
            name: Skill-Name
            dry_run: Nur anzeigen, nicht schreiben

        Returns:
            (success, message)
        """
        lines = []

        # Skill finden
        skill_path = self._find_skill(name)
        if not skill_path:
            return False, f"Skill nicht gefunden: {name}"

        skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
        if not skill_md.exists():
            return False, f"Keine SKILL.md gefunden in: {skill_path}"

        # SKILL.md lesen und parsen
        try:
            content = skill_md.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"

        # Metadaten extrahieren
        meta = self._extract_metadata(content)
        skill_type = self._detect_type(skill_path)

        # Help-Text generieren
        help_text = self._format_help(name, meta, content, skill_type)

        # Zieldatei bestimmen
        help_file = self.help_dir / f"{name}.txt"

        lines.append(f"Skill: {name}")
        lines.append(f"Typ: {skill_type}")
        lines.append(f"Quelle: {skill_md.relative_to(self.system_root)}")
        lines.append(f"Ziel: {help_file.relative_to(self.system_root)}")
        lines.append(f"Version: {meta.get('version', '?')}")

        if dry_run:
            lines.append("")
            lines.append("[DRY-RUN] Generierter Help-Text:")
            lines.append("-" * 40)
            lines.append(help_text)
            lines.append("-" * 40)
            lines.append("[DRY-RUN] Datei nicht geschrieben")
            return True, "\n".join(lines)

        # Bestehende Datei pruefen
        if help_file.exists():
            lines.append(f"[!] Bestehende Help-Datei wird ueberschrieben")

        # Schreiben
        try:
            self.help_dir.mkdir(parents=True, exist_ok=True)
            help_file.write_text(help_text, encoding='utf-8')
            lines.append(f"[OK] Help-Datei erstellt: {help_file.name}")
        except Exception as e:
            return False, f"Fehler beim Schreiben: {e}"

        return True, "\n".join(lines)

    def generate_all(self, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Generiert Help-Dateien fuer alle Skills mit SKILL.md.

        Returns:
            (success, message)
        """
        lines = ["SKILL HELP GENERATOR - Alle Skills", "=" * 50, ""]

        generated = 0
        skipped = 0
        errors = 0

        # Alle SKILL.md Dateien finden
        for skill_md in self.skills_dir.rglob("SKILL.md"):
            # Verzeichnisname = Skill-Name
            skill_dir = skill_md.parent
            name = skill_dir.name

            # _archive ueberspringen
            if '_archive' in str(skill_dir):
                continue

            success, msg = self.generate_for_skill(name, dry_run=dry_run)
            if success:
                generated += 1
                lines.append(f"  [OK] {name}")
            else:
                if "nicht gefunden" in msg:
                    skipped += 1
                    lines.append(f"  [--] {name}: {msg}")
                else:
                    errors += 1
                    lines.append(f"  [!!] {name}: {msg}")

        lines.append("")
        lines.append(f"Ergebnis: {generated} generiert, {skipped} uebersprungen, {errors} Fehler")
        if dry_run:
            lines.append("[DRY-RUN] Keine Dateien geschrieben")

        return errors == 0, "\n".join(lines)

    def _find_skill(self, name: str) -> Optional[Path]:
        """Findet einen Skill nach Name."""
        name_lower = name.lower()

        for subdir in ['_agents', '_experts', '_services']:
            skill_dir = self.skills_dir / subdir / name
            if skill_dir.exists() and skill_dir.is_dir():
                return skill_dir

        # Fuzzy-Match
        for subdir in ['_agents', '_experts', '_services']:
            parent = self.skills_dir / subdir
            if parent.exists():
                for item in parent.iterdir():
                    if item.is_dir() and name_lower == item.name.lower():
                        return item

        return None

    def _detect_type(self, skill_path: Path) -> str:
        """Erkennt Skill-Typ."""
        path_str = str(skill_path).lower()
        if '_agents' in path_str:
            return 'agent'
        elif '_experts' in path_str:
            return 'expert'
        elif '_services' in path_str:
            return 'service'
        return 'skill'

    def _extract_metadata(self, content: str) -> dict:
        """Extrahiert Metadaten aus YAML-Header und Markdown."""
        meta = {
            'name': '',
            'version': '1.0.0',
            'type': 'skill',
            'description': '',
            'author': '',
            'dependencies': {'tools': [], 'services': [], 'workflows': []},
            'commands': [],
            'features': [],
        }

        # YAML-Frontmatter parsen
        yaml_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if yaml_match:
            yaml_text = yaml_match.group(1)

            for key in ['name', 'version', 'type', 'author']:
                match = re.search(rf'{key}:\s*(.+)', yaml_text)
                if match:
                    meta[key] = match.group(1).strip().strip('"\'')

            # Description (kann mehrzeilig sein mit >)
            desc_match = re.search(r'description:\s*>?\s*\n?\s*(.+?)(?:\n\S|\n---|\Z)', yaml_text, re.DOTALL)
            if desc_match:
                meta['description'] = ' '.join(desc_match.group(1).strip().split())

        # Befehle aus dem Markdown-Body extrahieren
        # Suche nach bash-Codeblocks die bach-Befehle enthalten
        for m in re.finditer(r'```(?:bash)?\s*\n(.*?)```', content, re.DOTALL):
            block = m.group(1)
            for line in block.split('\n'):
                line = line.strip()
                if line.startswith('bach ') or line.startswith('python '):
                    meta['commands'].append(line)

        # Features aus Bullet-Listen extrahieren
        # Suche nach "## Features" oder "## FEATURES" Abschnitt
        feat_match = re.search(
            r'##\s*(?:FEATURES|Features|Funktionen|KERNFUNKTIONEN)\s*\n(.*?)(?:\n##|\Z)',
            content, re.DOTALL | re.IGNORECASE
        )
        if feat_match:
            for line in feat_match.group(1).split('\n'):
                line = line.strip()
                if line.startswith('- ') or line.startswith('* '):
                    feature = line.lstrip('-* ').strip()
                    if feature:
                        meta['features'].append(feature)

        return meta

    def _format_help(self, name: str, meta: dict, content: str, skill_type: str) -> str:
        """
        Generiert formatierten Help-Text im BACH-Standard.

        Format orientiert sich an bestehenden docs/help/*.txt Dateien:
        - Metadaten-Kommentare oben
        - Titel in Grossbuchstaben
        - Abschnitte: UEBERSICHT, BEFEHLE, BEISPIELE, SIEHE AUCH
        """
        today = datetime.now().strftime("%Y-%m-%d")
        version = meta.get('version', '1.0.0')
        title = name.upper().replace('-', ' ').replace('_', ' ')
        description = meta.get('description', f'BACH {skill_type.title()}: {name}')

        lines = []

        # Header-Kommentare (wie in bestehenden docs/help/*.txt)
        lines.append(f"# Portabilitaet: UNIVERSAL")
        lines.append(f"# Version: {version}")
        lines.append(f"# Zuletzt validiert: {today} (Auto-Generated)")
        lines.append(f"# Naechste Pruefung: (manuell)")
        lines.append(f"# Quelle: skills/{'_agents' if skill_type == 'agent' else '_experts' if skill_type == 'expert' else '_services'}/{name}/SKILL.md")
        lines.append(f"")
        lines.append(f"{title}")
        lines.append(f"{'=' * len(title)}")
        lines.append(f"")

        # Uebersicht
        lines.append(f"UEBERSICHT")
        lines.append(f"----------")
        lines.append(f"Typ: {skill_type.title()}")
        lines.append(f"Version: {version}")
        if meta.get('author'):
            lines.append(f"Author: {meta['author']}")
        lines.append(f"")
        # Description (umgebrochen bei 70 Zeichen)
        if description:
            desc_words = description.split()
            current_line = ""
            for word in desc_words:
                if len(current_line) + len(word) + 1 > 70:
                    lines.append(current_line)
                    current_line = word
                else:
                    current_line = f"{current_line} {word}" if current_line else word
            if current_line:
                lines.append(current_line)
        lines.append(f"")

        # Features (falls vorhanden)
        if meta.get('features'):
            lines.append(f"FEATURES")
            lines.append(f"--------")
            for feat in meta['features'][:10]:
                lines.append(f"  - {feat}")
            lines.append(f"")

        # Befehle (falls vorhanden)
        if meta.get('commands'):
            lines.append(f"BEFEHLE")
            lines.append(f"-------")
            seen = set()
            for cmd in meta['commands'][:15]:
                if cmd not in seen:
                    lines.append(f"  {cmd}")
                    seen.add(cmd)
            lines.append(f"")

        # Dependencies
        deps = meta.get('dependencies', {})
        has_deps = any(deps.get(k) for k in ['tools', 'services', 'workflows'])
        if has_deps:
            lines.append(f"ABHAENGIGKEITEN")
            lines.append(f"---------------")
            for key in ['tools', 'services', 'workflows']:
                items = deps.get(key, [])
                if items:
                    lines.append(f"  {key.title()}: {', '.join(str(i) for i in items)}")
            lines.append(f"")

        # Pfad-Info
        lines.append(f"DATEIEN")
        lines.append(f"-------")
        lines.append(f"  SKILL.md: skills/{'_agents' if skill_type == 'agent' else '_experts' if skill_type == 'expert' else '_services'}/{name}/SKILL.md")
        lines.append(f"")

        # Siehe auch
        lines.append(f"SIEHE AUCH")
        lines.append(f"----------")
        lines.append(f"  bach --skills show {name}      Skill-Details anzeigen")
        lines.append(f"  bach --skills export {name}    Skill exportieren")
        lines.append(f"  bach --help skills              Skills-System Uebersicht")
        lines.append(f"")

        return "\n".join(lines)


class WorkflowValidator:
    """Validiert Workflow-Dateien auf konsistentes Format."""

    # Erwartete Abschnitte in einem Workflow
    EXPECTED_SECTIONS = {
        'title': True,       # Pflicht: # Titel als H1
        'description': True, # Pflicht: Kurzbeschreibung
        'trigger': False,    # Optional: Wann wird der Workflow ausgeloest
        'steps': True,       # Pflicht: Schritte/Ablauf
    }

    def __init__(self, system_root: Path):
        self.system_root = system_root
        current_dir = system_root / "skills" / "workflows"
        legacy_dir = system_root / "skills" / "_workflows"
        self.workflows_dir = current_dir if current_dir.exists() else legacy_dir

    def validate_all(self) -> Tuple[bool, str]:
        """
        Validiert alle Workflow-Dateien.

        Returns:
            (success, message)
        """
        lines = ["WORKFLOW FORMAT-VALIDIERUNG", "=" * 50, ""]

        if not self.workflows_dir.exists():
            return False, "Workflows-Verzeichnis nicht gefunden"

        total = 0
        valid = 0
        issues_total = 0
        results = []

        workflow_files = sorted(self.workflows_dir.glob("*.md"))
        seen_names = {wf.name for wf in workflow_files}
        for wf_file in sorted(self.workflows_dir.rglob("*.md")):
            if "_archive" in wf_file.parts:
                continue
            if wf_file.parent == self.workflows_dir:
                continue
            if wf_file.name in seen_names:
                continue
            workflow_files.append(wf_file)
            seen_names.add(wf_file.name)

        for wf_file in sorted(workflow_files):
            total += 1
            issues = self._validate_single(wf_file)

            if not issues:
                valid += 1
                results.append((wf_file.name, "OK", []))
            else:
                issues_total += len(issues)
                results.append((wf_file.name, "ISSUES", issues))

        # Ergebnisse ausgeben
        for filename, status, issues in results:
            if status == "OK":
                lines.append(f"  [OK] {filename}")
            else:
                lines.append(f"  [!!] {filename}")
                for issue in issues:
                    lines.append(f"       - {issue}")

        lines.append("")
        lines.append("-" * 50)
        lines.append(f"Gesamt: {total} Workflows")
        lines.append(f"Valide: {valid}/{total}")
        lines.append(f"Issues: {issues_total}")

        if issues_total > 0:
            lines.append("")
            lines.append("EMPFOHLENES FORMAT:")
            lines.append("-" * 40)
            lines.append("  # Workflow-Titel")
            lines.append("  ")
            lines.append("  > Kurzbeschreibung oder **Zweck:**")
            lines.append("  ")
            lines.append("  ## Trigger (oder: Wann ausfuehren)")
            lines.append("  - Ausloeser 1")
            lines.append("  ")
            lines.append("  ## Ablauf (oder: Schritte)")
            lines.append("  ### 1. Erster Schritt")
            lines.append("  ### 2. Zweiter Schritt")

        return issues_total == 0, "\n".join(lines)

    def _validate_single(self, wf_file: Path) -> List[str]:
        """
        Validiert eine einzelne Workflow-Datei.

        Returns:
            Liste von Issue-Beschreibungen (leer = OK)
        """
        issues = []

        try:
            content = wf_file.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            return [f"Lesefehler: {e}"]

        lines_list = content.strip().split('\n')

        if not lines_list:
            return ["Datei ist leer"]

        # 1. Titel pruefen (# H1 in erster Zeile)
        has_title = False
        for line in lines_list[:5]:
            if line.strip().startswith('# ') and not line.strip().startswith('## '):
                has_title = True
                break
        if not has_title:
            issues.append("Kein H1-Titel (# ...) in den ersten 5 Zeilen")

        # 2. Beschreibung pruefen (> Blockquote oder **Zweck:** oder ## Zweck/Uebersicht)
        has_desc = False
        desc_patterns = [
            r'>\s*.+',                           # Blockquote
            r'\*\*(?:Zweck|Ziel|Beschreibung)\b',  # Bold keyword
            r'##\s*(?:Zweck|Uebersicht|Ueber\b)',  # Section
        ]
        for line in lines_list[:15]:
            for pat in desc_patterns:
                if re.search(pat, line.strip(), re.IGNORECASE):
                    has_desc = True
                    break
            if has_desc:
                break
        if not has_desc:
            issues.append("Keine Beschreibung (> Blockquote, **Zweck:**, oder ## Uebersicht)")

        # 3. Schritte pruefen (nummerierte Abschnitte oder ## Schritt/Phase/Ablauf)
        has_steps = False
        step_patterns = [
            r'##\s*(?:Phase|Schritt|Step|Ablauf|\d+\.)',
            r'###\s*\d+[\.\)]',                # ### 1. oder ### 1)
            r'##\s*\d+\.',                       # ## 1.
        ]
        for line in lines_list:
            for pat in step_patterns:
                if re.search(pat, line.strip(), re.IGNORECASE):
                    has_steps = True
                    break
            if has_steps:
                break
        if not has_steps:
            issues.append("Keine Schritt-Struktur (## Phase/Schritt/Ablauf oder ### 1.)")

        # 4. Optionale Pruefungen
        # YAML-Frontmatter vorhanden?
        has_yaml = content.strip().startswith('---')
        # Version vorhanden?
        has_version = bool(re.search(r'\*\*Version:\*\*|version:', content[:500], re.IGNORECASE))

        # Keine harte Anforderung, aber Info
        if not has_yaml and not has_version:
            issues.append("Kein YAML-Frontmatter und keine Versions-Angabe (empfohlen)")

        # 5. Mindestlaenge
        if len(content.strip()) < 100:
            issues.append(f"Sehr kurzer Inhalt ({len(content.strip())} Zeichen)")

        return issues


def main():
    """CLI-Einstiegspunkt."""
    parser = argparse.ArgumentParser(
        description="BACH Skill Help Generator & Workflow Validator"
    )

    subparsers = parser.add_subparsers(dest='command', help='Verfuegbare Befehle')

    # Help-Generator
    help_parser = subparsers.add_parser('help', help='Help-Dateien generieren')
    help_parser.add_argument('--skill', '-s', help='Einzelner Skill-Name')
    help_parser.add_argument('--all', '-a', action='store_true', help='Alle Skills')
    help_parser.add_argument('--dry-run', '-n', action='store_true', help='Nur anzeigen')

    # Workflow-Validator
    wf_parser = subparsers.add_parser('workflows', help='Workflows validieren')
    wf_parser.add_argument('--dry-run', '-n', action='store_true', help='Nur anzeigen')

    args = parser.parse_args()

    if args.command == 'help':
        gen = HelpGenerator(SYSTEM_ROOT)
        if args.all:
            success, msg = gen.generate_all(dry_run=args.dry_run)
        elif args.skill:
            success, msg = gen.generate_for_skill(args.skill, dry_run=args.dry_run)
        else:
            print("Bitte --skill <name> oder --all angeben")
            return 1
        print(msg)
        return 0 if success else 1

    elif args.command == 'workflows':
        validator = WorkflowValidator(SYSTEM_ROOT)
        success, msg = validator.validate_all()
        print(msg)
        return 0 if success else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
