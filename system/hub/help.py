# SPDX-License-Identifier: MIT
"""
Help Handler - Zeigt Hilfe-Texte aus .txt Dateien
=================================================

Unterstuetzt auch Unterordner:
  bach --help tools                    -> docs/help/tools.txt
  bach --help tools/python_cli_editor  -> docs/help/tools/python_cli_editor.txt
  
NEU (v1.1.38): Tool-Direktzugriff
  bach --help path_healer              -> Tool-Info aus DB
  bach --help tool_scanner             -> Tool-Info aus DB
"""
from pathlib import Path
import sqlite3
from .base import BaseHandler
from .lang import t


class HelpHandler(BaseHandler):
    """Handler fuer --help <topic>"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        # Help liegt jetzt unter docs/help/ (v2.6 Refactoring)
        self.help_dir = base_path / "docs" / "help"
    
    @property
    def profile_name(self) -> str:
        return "help"
    
    @property
    def target_file(self) -> Path:
        return self.help_dir
    
    def get_operations(self) -> dict:
        return {
            "list": "Alle verfuegbaren Hilfe-Themen anzeigen",
            "<topic>": "Hilfe zu einem bestimmten Thema anzeigen",
            "<folder>/<topic>": "Hilfe aus Unterordner (z.B. tools/python_cli_editor)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.help_dir.exists():
            return False, f"Help-Verzeichnis nicht gefunden: {self.help_dir}"

        if operation == "list" or not operation:
            return self._list_topics()
        elif operation in ("run", "show", "get") and args:
            # API-Zugriff: help.run("cli") -> operation="run", args=["cli"]
            # Das eigentliche Topic steckt im ersten Argument
            topic = args[0]
            if topic == "list":
                return self._list_topics()
            return self._show_topic(topic)
        else:
            return self._show_topic(operation)
    
    def _list_topics(self) -> tuple:
        """Listet alle verfuegbaren Hilfe-Themen auf."""
        topics = []
        
        # Hauptordner
        for txt_file in sorted(self.help_dir.glob("*.txt")):
            topic = txt_file.stem
            try:
                with open(txt_file, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line.startswith("="):
                        first_line = f.readline().strip()
                topics.append(f"  {topic:20} {first_line[:50]}")
            except (OSError, UnicodeDecodeError):
                topics.append(f"  {topic}")
        
        # Unterordner
        subdirs = []
        for subdir in sorted(self.help_dir.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith('_'):
                txt_count = len(list(subdir.glob("*.txt")))
                if txt_count > 0:
                    subdirs.append(f"  {subdir.name}/              ({txt_count} Themen)")
        
        if not topics and not subdirs:
            return False, "Keine Hilfe-Themen gefunden"
        
        result = "Verfuegbare Hilfe-Themen:\n\n"
        result += "\n".join(topics)
        
        if subdirs:
            result += "\n\nUnterordner:\n"
            result += "\n".join(subdirs)
            result += "\n\n  Abruf: --help <ordner>/<thema>"
            result += "\n  z.B.:  --help tools/python_cli_editor"
            result += "\n         --help wiki/antigravity"
        
        result += "\n\nNutzung: --help <topic>"
        return True, result
    
    def _show_topic(self, topic: str) -> tuple:
        """Zeigt Hilfe zu einem bestimmten Thema.
        
        Unterstuetzt:
          topic             -> docs/help/topic.txt
          folder/topic      -> docs/help/folder/topic.txt
          folder            -> docs/help/folder/_index.txt (falls vorhanden)
        """
        # Normalisieren: Backslash zu Slash, Leerzeichen zu Underscore
        topic = topic.lower().replace("\\", "/").replace("-", "_").replace(" ", "_")
        
        # Pfad aufbauen
        if "/" in topic:
            # Unterordner-Pfad: tools/python_cli_editor
            parts = topic.split("/", 1)
            folder = parts[0]
            subtopic = parts[1] if len(parts) > 1 else "_index"
            txt_file = self.help_dir / folder / f"{subtopic}.txt"
            
            # Fallback: Ordner-Index
            if not txt_file.exists() and len(parts) == 1:
                txt_file = self.help_dir / folder / "_index.txt"
        else:
            # Einfacher Topic-Name
            txt_file = self.help_dir / f"{topic}.txt"

            # Fallback 1: Plural-Form versuchen (task -> tasks.txt)
            if not txt_file.exists():
                plural_file = self.help_dir / f"{topic}s.txt"
                if plural_file.exists():
                    txt_file = plural_file

            # Fallback 2: Vielleicht ist es ein Ordner?
            if not txt_file.exists():
                folder_path = self.help_dir / topic
                if folder_path.is_dir():
                    index_file = folder_path / "_index.txt"
                    if index_file.exists():
                        txt_file = index_file

        if not txt_file.exists():
            # NEU v1.1.85: Alias-System fuer skills-Strukturen
            alias_result = self._check_skill_aliases(topic)
            if alias_result:
                return True, alias_result

            # NEU: Prüfe ob es ein Tool ist
            tool_help = self._get_tool_help(topic)
            if tool_help:
                return True, tool_help
            return self._suggest_topic(topic)
        
        try:
            with open(txt_file, "r", encoding="utf-8") as f:
                content = f.read()
            return True, content
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"
    
    def _get_tool_help(self, tool_name: str) -> str:
        """Holt Tool-Informationen aus der Datenbank.

        Returns:
            Tool-Hilfe als formatierter String oder None wenn nicht gefunden.
        """
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Erst exakten Match suchen (case-insensitive)
            cursor.execute("""
                SELECT name, type, category, path, description, version,
                       capabilities, use_for, command, is_available
                FROM tools
                WHERE LOWER(name) = LOWER(?)
                LIMIT 1
            """, (tool_name,))

            row = cursor.fetchone()

            # Nur bei keinem exakten Match: Wildcard-Suche
            if not row:
                cursor.execute("""
                    SELECT name, type, category, path, description, version,
                           capabilities, use_for, command, is_available
                    FROM tools
                    WHERE LOWER(name) LIKE LOWER(?)
                    LIMIT 1
                """, (f"%{tool_name}%",))
                row = cursor.fetchone()

            conn.close()
            
            if not row:
                return None
            
            # Formatierte Ausgabe
            lines = [
                f"{'=' * 60}",
                f"TOOL: {row['name']}",
                f"{'=' * 60}",
                ""
            ]
            
            if row['description']:
                lines.append(f"Beschreibung: {row['description']}")
                lines.append("")
            
            lines.append(f"Typ:          {row['type'] or '-'}")
            lines.append(f"Kategorie:    {row['category'] or '-'}")
            lines.append(f"Version:      {row['version'] or '-'}")
            lines.append(f"Status:       {'Aktiv' if row['is_available'] else 'Inaktiv'}")
            
            if row['path']:
                lines.append(f"Pfad:         {row['path']}")
            
            if row['command']:
                lines.append(f"Befehl:       {row['command']}")
            
            if row['use_for']:
                lines.append("")
                lines.append("Verwendung:")
                for use in row['use_for'].split(','):
                    lines.append(f"  • {use.strip()}")
            
            if row['capabilities']:
                lines.append("")
                lines.append("Faehigkeiten:")
                for cap in row['capabilities'].split(','):
                    lines.append(f"  • {cap.strip()}")
            
            lines.append("")
            lines.append(f"{'=' * 60}")
            lines.append("(Daten aus tools-Tabelle, bach.db)")
            
            return "\n".join(lines)
            
        except Exception as e:
            return None

    def _suggest_topic(self, topic: str) -> tuple:
        """Schlaegt aehnliche Themen vor."""
        available = []
        
        # Hauptordner
        for f in self.help_dir.glob("*.txt"):
            available.append(f.stem)
        
        # Unterordner
        for subdir in self.help_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith('_'):
                for f in subdir.glob("*.txt"):
                    if f.stem != "_index":
                        available.append(f"{subdir.name}/{f.stem}")
        
        # Matches finden
        topic_lower = topic.lower()
        matches = [t for t in available if topic_lower in t.lower() or t.lower() in topic_lower]
        
        if matches:
            suggestion = f"\n\nMeinten Sie:\n  " + "\n  ".join(matches[:5])
        else:
            # Zeige relevante Themen
            suggestion = f"\n\nVerfuegbar (Auswahl):\n  " + "\n  ".join(sorted(available)[:15])
            if len(available) > 15:
                suggestion += f"\n  ... und {len(available) - 15} weitere"
        
        return False, f"Hilfe-Thema '{topic}' nicht gefunden.{suggestion}"

    def _check_skill_aliases(self, topic: str) -> str:
        """Prueft Aliase zu skills-Strukturen (agents, workflows, experts).

        Ermoeglicht:
          --help agent/ati      -> agents/ati/ATI.md
          --help workflow/bugfix -> skills/workflows/bugfix-protokoll.md
          --help expert/steuer   -> agents/_experts/steuer/STEUER.md

        Returns:
            Dateiinhalt oder None wenn nicht gefunden.
        """
        skills_dir = self.base_path / "skills"
        if not skills_dir.exists():
            return None

        topic_lower = topic.lower().replace("-", "_").replace(" ", "_")

        # Alias-Mapping (v2.5 Restructuring)
        agents_dir = self.base_path / "agents"
        experts_dir = agents_dir / "_experts"
        protocols_dir = skills_dir / "workflows"
        services_dir = skills_dir / "_services"

        alias_paths = {
            "agent/": agents_dir,
            "agents/": agents_dir,
            "protocol/": protocols_dir,
            "protocols/": protocols_dir,
            "workflow/": protocols_dir,
            "workflows/": protocols_dir,
            "expert/": experts_dir,
            "experts/": experts_dir,
            "service/": services_dir,
            "services/": services_dir,
        }

        for prefix, base_path in alias_paths.items():
            if topic_lower.startswith(prefix):
                name = topic_lower[len(prefix):]
                if not base_path.exists():
                    continue

                # Verschiedene Patterns probieren
                patterns = [
                    base_path / name / f"{name.upper()}.md",    # _agents/ati/ATI.md
                    base_path / name / "README.md",              # _agents/ati/README.md
                    base_path / f"{name}.md",                    # _workflows/bugfix.md
                    base_path / f"{name.replace('_', '-')}.md",  # _workflows/bugfix-protokoll.md
                    base_path / name / f"{name}.txt",            # Fallback .txt
                ]

                for pattern in patterns:
                    if pattern.exists():
                        try:
                            content = pattern.read_text(encoding='utf-8')
                            header = f"[ALIAS: {topic} -> {pattern.relative_to(self.base_path)}]\n"
                            header += "=" * 60 + "\n\n"
                            return header + content
                        except (OSError, UnicodeDecodeError):
                            continue

                # Ordner-Liste zeigen wenn Name nicht gefunden
                if base_path.exists():
                    items = []
                    for item in sorted(base_path.iterdir()):
                        if item.is_dir() and not item.name.startswith('_'):
                            items.append(item.name)
                        elif item.suffix in ['.md', '.txt']:
                            items.append(item.stem)

                    if items:
                        return f"'{name}' nicht gefunden in {prefix[:-1]}.\n\nVerfuegbar:\n  " + "\n  ".join(items[:20])

        return None
