# SPDX-License-Identifier: MIT
"""
Tools Handler - Tool-Verwaltung
===============================

bach tools list              Alle Python-Tools auflisten (Dateisystem)
bach tools db                Alle Tools aus Datenbank (CLI + externe KI)
bach tools db --type cli     Nur CLI-Tools
bach tools db --type external Nur externe KI-Tools
bach tools show <name>       Tool-Details anzeigen
bach tools run <name>        Tool ausfuehren
bach tools search <term>     Tools durchsuchen
bach tools migrate           Migration der Connections starten

Hinweis: Dies verwaltet sowohl Python-Scripts (tools/) als auch
die registrierten Tools in der Datenbank (bach.db/tools).
"""
import json
import sqlite3
from pathlib import Path
import subprocess
import sys
from .base import BaseHandler
from .lang import get_lang, t


class ToolsHandler(BaseHandler):
    """Handler fuer --tools Operationen"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        # Korrigiert: tools liegt direkt unter system/tools/
        self.tools_dir = base_path / "tools"
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "tools"
    
    @property
    def target_file(self) -> Path:
        return self.tools_dir
    
    def get_operations(self) -> dict:
        return {
            "list": t("tools_list_desc", default="Python-Tools auflisten (Dateisystem)"),
            "db": t("tools_db_desc", default="Tools aus Datenbank (CLI + externe KI)"),
            "show": t("tools_show_desc", default="Tool-Details anzeigen"),
            "run": t("tools_run_desc", default="Tool ausfuehren"),
            "search": t("tools_search_desc", default="Tools durchsuchen"),
            "suggest": t("tools_suggest_desc", default="Tool-Empfehlung basierend auf Problem"),
            "migrate": t("tools_migrate_desc", default="Migration der Connections starten"),
            "docs": t("tools_docs_desc", default="Tool-Dokumentation (--generate fuer Auto-Generator)")
        }
    
    def _get_db_conn(self):
        """Datenbank-Verbindung herstellen."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "db":
            return self._list_db(args)
        elif operation == "show" and args:
            return self._show(args[0])
        elif operation == "run" and args:
            return self._run(args[0], args[1:], dry_run)
        elif operation == "search" and args:
            return self._search(" ".join(args))
        elif operation == "suggest":
            return self._suggest(" ".join(args) if args else "")
        elif operation == "migrate":
            return self._migrate(dry_run)
        elif operation == "docs":
            return self._docs(args, dry_run)
        else:
            return self._list()
    
    def _list_db(self, args: list) -> tuple:
        """Tools aus Datenbank auflisten."""
        results = [t("tools_registered", default="REGISTRIERTE TOOLS (bach.db)"), "=" * 60]

        if not self.db_path.exists():
            return False, t("db_not_found", default="Datenbank nicht gefunden")

        conn = self._get_db_conn()

        # Filter nach Typ
        type_filter = None
        if '--type' in args:
            idx = args.index('--type')
            if idx + 1 < len(args):
                type_filter = args[idx + 1]

        # TOWER_OF_BABEL: Sprach-Filter mit DE-Fallback
        lang = get_lang()
        lang_clause = "AND language = ?"

        # Query
        if type_filter:
            query = f"SELECT * FROM tools WHERE type = ? {lang_clause} ORDER BY category, name"
            rows = conn.execute(query, (type_filter, lang)).fetchall()
            if not rows and lang != 'de':
                rows = conn.execute(query, (type_filter, 'de')).fetchall()
        else:
            query = f"SELECT * FROM tools WHERE language = ? ORDER BY type, category, name"
            rows = conn.execute(query, (lang,)).fetchall()
            if not rows and lang != 'de':
                rows = conn.execute("SELECT * FROM tools WHERE language = 'de' ORDER BY type, category, name").fetchall()
        
        if not rows:
            conn.close()
            return True, t("tools_none_found", default="Keine Tools in Datenbank gefunden.") + "\n" + t("tools_run_migrate", default="Fuehre 'bach tools migrate' aus.")
        
        # Nach Typ gruppieren
        current_type = None
        for row in rows:
            if row['type'] != current_type:
                current_type = row['type']
                type_label = {
                    'cli': t("tools_type_cli", default="CLI-TOOLS (Kommandozeile)"),
                    'external': t("tools_type_external", default="EXTERNE KI-TOOLS"),
                    'internal': t("tools_type_internal", default="INTERNE TOOLS")
                }.get(current_type, current_type.upper())
                results.append(f"\n[{type_label}]")
            
            # Status-Icon
            status = "[OK]" if row['is_available'] else "[--]"
            
            # Ausgabe
            name = row['name']
            category = row['category'] or ''
            desc = (row['description'] or '')[:40]
            
            results.append(f"  {status} {name:<15} {category:<12} {desc}")
        
        # Statistik (COUNT(DISTINCT name): Sprachvarianten nicht doppelt zaehlen)
        stats = conn.execute(
            "SELECT type, COUNT(DISTINCT name) as cnt FROM tools GROUP BY type"
        ).fetchall()
        
        results.append(f"\n{'=' * 60}")
        results.append(f"{t('tools_statistics', default='Statistik')}:")
        total = 0
        for stat in stats:
            results.append(f"  {stat['type']}: {stat['cnt']}")
            total += stat['cnt']
        results.append(f"  {t('count', default='Gesamt')}: {total}")
        
        conn.close()
        return True, "\n".join(results)
    
    def _migrate(self, dry_run: bool) -> tuple:
        """Migration der Connections starten."""
        migrate_script = self.tools_dir / "migrate_connections.py"
        
        if not migrate_script.exists():
            return False, "Migration-Script nicht gefunden: tools/migrate_connections.py"
        
        args = [sys.executable, str(migrate_script)]
        if dry_run:
            args.append('--dry-run')
        
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=60,
                cwd=str(self.tools_dir.parent)
            )
            return True, result.stdout + (result.stderr if result.stderr else '')
        except Exception as e:
            return False, f"Fehler bei Migration: {e}"
    
    def _list(self) -> tuple:
        """Alle Tools aus Dateisystem auflisten."""
        results = ["BACH TOOLS (Python-Scripts)", "=" * 50]
        
        if not self.tools_dir.exists():
            return False, "Tools-Verzeichnis nicht gefunden"
        
        # Tools nach Prefix gruppieren
        categories = {
            "c_": ("Coding", []),
            "agent_": ("Agent", []),
            "backup_": ("Backup", []),
            "ollama_": ("Ollama", []),
            "steuer_": ("Steuer", []),
            "policy_": ("Policy", []),
            "migrate_": ("Migration", []),
            "_": ("Andere", [])  # Fallback
        }
        
        for tool_file in sorted(self.tools_dir.glob("*.py")):
            if tool_file.name.startswith('__'):
                continue
            
            name = tool_file.stem
            categorized = False
            
            for prefix, (cat_name, tools_list) in categories.items():
                if prefix != "_" and name.startswith(prefix):
                    tools_list.append(name)
                    categorized = True
                    break
            
            if not categorized:
                categories["_"][1].append(name)
        
        # Auch Unterordner scannen
        subdirs = []
        for subdir in self.tools_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith('__'):
                py_files = list(subdir.glob("*.py"))
                if py_files:
                    subdirs.append((subdir.name, len(py_files)))
        
        total = 0
        for prefix, (cat_name, tools) in categories.items():
            if tools:
                results.append(f"\n[{cat_name.upper()}]")
                for tool in tools:
                    results.append(f"  {tool}")
                    total += 1
        
        if subdirs:
            results.append(f"\n[UNTERORDNER]")
            for name, count in subdirs:
                results.append(f"  {name}/ ({count} Tools)")
        
        results.append(f"\n{'=' * 50}")
        results.append(f"Gesamt: {total} Python-Tools")
        results.append(f"\nDB-Tools: bach tools db")
        results.append(f"Details:  bach tools show <name>")
        
        return True, "\n".join(results)
    
    def _show(self, name: str) -> tuple:
        """Tool-Details anzeigen (Docstring oder DB)."""
        # Erst in DB suchen
        if self.db_path.exists():
            conn = self._get_db_conn()
            row = conn.execute(
                "SELECT * FROM tools WHERE name LIKE ? "
                "ORDER BY (language = ?) DESC, (language = 'de') DESC",
                (f"%{name}%", get_lang())
            ).fetchone()
            conn.close()
            
            if row:
                results = [f"TOOL: {row['name']}", "=" * 50]
                results.append(f"Typ:        {row['type']}")
                results.append(f"Kategorie:  {row['category'] or '-'}")
                results.append(f"Status:     {'Verfuegbar' if row['is_available'] else 'Nicht verfuegbar'}")
                if row['command']:
                    results.append(f"Command:    {row['command']}")
                if row['endpoint']:
                    results.append(f"Endpoint:   {row['endpoint']}")
                results.append(f"\n[BESCHREIBUNG]")
                results.append(f"  {row['description'] or 'Keine Beschreibung'}")
                if row['capabilities']:
                    try:
                        caps = json.loads(row['capabilities'])
                        results.append(f"\n[FAEHIGKEITEN]")
                        results.append(f"  {', '.join(caps)}")
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                if row['use_for']:
                    results.append(f"\n[VERWENDUNG]")
                    results.append(f"  {row['use_for']}")
                return True, "\n".join(results)
        
        # Dann im Dateisystem suchen
        found = None
        for tool_file in self.tools_dir.rglob("*.py"):
            if name.lower() in tool_file.stem.lower():
                found = tool_file
                break
        
        if not found:
            return False, f"Tool nicht gefunden: {name}\nNutze: bach tools list"
        
        results = [f"TOOL: {found.stem}", "=" * 50]
        results.append(f"Pfad: {found.relative_to(self.tools_dir)}")
        results.append(f"Groesse: {found.stat().st_size} Bytes")
        results.append("")
        
        # Docstring extrahieren
        try:
            content = found.read_text(encoding='utf-8', errors='ignore')
            
            # Triple-quoted docstring finden
            import re
            docstring_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
            if docstring_match:
                docstring = docstring_match.group(1).strip()
                results.append("[BESCHREIBUNG]")
                for line in docstring.split('\n')[:30]:
                    results.append(f"  {line}")
                if len(docstring.split('\n')) > 30:
                    results.append("  ...")
            else:
                results.append("[Kein Docstring]")
            
            # CLI-Argumente suchen (argparse)
            if 'argparse' in content or 'sys.argv' in content:
                results.append("\n[CLI-TOOL] Unterstuetzt Kommandozeilen-Argumente")
            
            # Ausfuehren-Hinweis
            results.append(f"\nAusfuehren: bach tools run {found.stem} [args]")
            
        except Exception as e:
            results.append(f"Fehler beim Lesen: {e}")
        
        return True, "\n".join(results)
    
    def _run(self, name: str, args: list, dry_run: bool) -> tuple:
        """Tool ausfuehren."""
        # Tool suchen
        found = None
        for tool_file in self.tools_dir.glob("*.py"):
            if name.lower() == tool_file.stem.lower():
                found = tool_file
                break
        
        if not found:
            # Auch mit Prefix suchen
            for tool_file in self.tools_dir.glob("*.py"):
                if name.lower() in tool_file.stem.lower():
                    found = tool_file
                    break
        
        if not found:
            return False, f"Tool nicht gefunden: {name}\nNutze: bach tools list"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde ausfuehren: python {found} {' '.join(args)}"
        
        results = [f"Fuehre aus: {found.stem}", "=" * 50]
        
        try:
            cmd = [sys.executable, str(found)] + args
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=60,
                cwd=str(self.tools_dir.parent)
            )
            
            if process.stdout:
                results.append(process.stdout)
            if process.stderr:
                results.append(f"[STDERR]\n{process.stderr}")
            
            results.append(f"\n{'=' * 50}")
            results.append(f"Exit-Code: {process.returncode}")
            
        except subprocess.TimeoutExpired:
            return False, f"Tool-Timeout nach 60s: {name}"
        except Exception as e:
            return False, f"Fehler beim Ausfuehren: {e}"
        
        return True, "\n".join(results)
    
    def _search(self, term: str) -> tuple:
        """Tools nach Begriff durchsuchen (Dateisystem + DB)."""
        results = [f"TOOL-SUCHE: '{term}'", "=" * 50]
        
        found = []
        term_lower = term.lower()
        
        # In Datenbank suchen
        if self.db_path.exists():
            conn = self._get_db_conn()
            # TOWER_OF_BABEL: Tools existieren pro Sprache (UNIQUE(name, language)).
            # GROUP BY name dedupliziert; MAX(language = ?) bevorzugt die aktive
            # Sprache und faellt sonst auf 'de' zurueck (Task 1149).
            lang = get_lang()
            db_results = conn.execute(
                """SELECT name, type, category, description,
                          MAX(language = ?) AS _lang_pref
                   FROM tools
                   WHERE (name LIKE ? OR description LIKE ? OR capabilities LIKE ?)
                     AND language IN (?, 'de')
                   GROUP BY name""",
                (lang, f"%{term}%", f"%{term}%", f"%{term}%", lang)
            ).fetchall()
            conn.close()
            
            for row in db_results:
                found.append((row['name'], f"DB/{row['type']}", row['description']))
        
        # Im Dateisystem suchen
        for tool_file in self.tools_dir.rglob("*.py"):
            if tool_file.name.startswith('__'):
                continue
            
            # Im Namen suchen
            if term_lower in tool_file.stem.lower():
                found.append((tool_file.stem, "Script", ""))
                continue
            
            # Im Inhalt suchen
            try:
                content = tool_file.read_text(encoding='utf-8', errors='ignore').lower()
                if term_lower in content:
                    found.append((tool_file.stem, "Script/Inhalt", ""))
            except (OSError, UnicodeDecodeError):
                pass
        
        if not found:
            results.append(f"Keine Tools gefunden fuer: {term}")
        else:
            results.append(f"Gefunden: {len(found)}\n")
            for name, source, desc in found[:25]:
                desc_short = (desc or '')[:35]
                results.append(f"  [{source}] {name:<20} {desc_short}")
            
            if len(found) > 25:
                results.append(f"\n  ... und {len(found) - 25} weitere")
        
        return True, "\n".join(results)
    
    def _suggest(self, problem: str) -> tuple:
        """Tool-Empfehlung basierend auf Problembeschreibung."""
        if not problem:
            return False, "Bitte Problem beschreiben.\n\nBeispiel: bach tool suggest 'encoding problem mit umlauten'"
        
        results = ["TOOL-EMPFEHLUNG", "=" * 50]
        results.append(f"Problem: {problem}\n")
        
        # tool_discovery.py verwenden
        discovery_script = self.tools_dir / "tool_discovery.py"
        
        if not discovery_script.exists():
            return False, "tool_discovery.py nicht gefunden"
        
        try:
            cmd = [sys.executable, str(discovery_script), "suggest", problem]
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.tools_dir.parent),
                encoding='utf-8', errors='replace'
            )
            
            if process.returncode == 0 and process.stdout:
                results.append(process.stdout)
            else:
                results.append("Keine passenden Tools gefunden.")
                if process.stderr:
                    results.append(f"\n[DEBUG] {process.stderr}")
        except subprocess.TimeoutExpired:
            return False, "Timeout bei Tool-Discovery"
        except Exception as e:
            return False, f"Fehler bei Tool-Discovery: {e}"
        
        results.append(f"\n{'=' * 50}")
        results.append("Tipp: bach tool search <keyword> fuer Detailsuche")
        
        return True, "\n".join(results)
    
    def _docs(self, args: list, dry_run: bool) -> tuple:
        """Tool-Dokumentation generieren oder anzeigen."""
        import re
        from datetime import datetime
        
        help_tools_dir = self.base_path / "help" / "tools"
        
        # --generate Flag pruefen
        generate = '--generate' in args
        
        if not generate:
            # Nur vorhandene Docs anzeigen
            results = ["TOOL-DOKUMENTATION", "=" * 50]
            
            if help_tools_dir.exists():
                docs = list(help_tools_dir.glob("*.txt"))
                if docs:
                    results.append(f"\nVorhandene Dokumentation ({len(docs)} Dateien):")
                    for doc in sorted(docs):
                        results.append(f"  {doc.name}")
                else:
                    results.append("\nKeine Dokumentation vorhanden.")
            else:
                results.append(f"\nOrdner existiert nicht: docs/help/tools/")
            
            results.append(f"\n{'=' * 50}")
            results.append("Generieren: bach tools docs --generate")
            return True, "\n".join(results)
        
        # Dokumentation generieren
        results = ["TOOL-DOKU AUTO-GENERATOR", "=" * 50]
        
        if dry_run:
            results.append("[DRY-RUN] Wuerde generieren:\n")
        
        # Ordner erstellen
        if not dry_run:
            help_tools_dir.mkdir(parents=True, exist_ok=True)
        
        generated = 0
        skipped = 0
        errors = []
        index_entries = []  # Fuer _index.txt
        
        # Alle Python-Tools durchgehen
        for tool_file in sorted(self.tools_dir.glob("*.py")):
            if tool_file.name.startswith('__'):
                continue
            
            tool_name = tool_file.stem
            output_file = help_tools_dir / f"{tool_name}.txt"
            
            try:
                content = tool_file.read_text(encoding='utf-8', errors='ignore')
                
                # Docstring extrahieren
                docstring = ""
                docstring_match = re.search(r'^"""(.*?)"""', content, re.DOTALL | re.MULTILINE)
                if not docstring_match:
                    docstring_match = re.search(r"^'''(.*?)'''", content, re.DOTALL | re.MULTILINE)
                
                if docstring_match:
                    docstring = docstring_match.group(1).strip()
                
                if not docstring:
                    skipped += 1
                    continue
                
                # Dokumentation erstellen
                doc_content = f"""BACH Tool: {tool_name}
{'=' * 50}
Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Quelle: tools/{tool_name}.py

BESCHREIBUNG
{'-' * 40}
{docstring}

VERWENDUNG
{'-' * 40}
python bach.py tools run {tool_name} [args]
oder direkt: python tools/{tool_name}.py [args]

HINWEISE
{'-' * 40}
- Automatisch generiert aus Docstring
- Bei Fragen: bach tools show {tool_name}
"""
                
                if dry_run:
                    results.append(f"  [GENERATE] {tool_name}.txt ({len(docstring)} chars)")
                else:
                    output_file.write_text(doc_content, encoding='utf-8')
                    results.append(f"  [OK] {tool_name}.txt")
                
                generated += 1
                
                # Index-Eintrag: erste Zeile des Docstrings als Beschreibung
                first_line = docstring.split('\n')[0].strip()[:60]
                index_entries.append((tool_name, first_line))
                
            except Exception as e:
                errors.append(f"{tool_name}: {e}")
        
        # Zusammenfassung
        results.append(f"\n{'=' * 50}")
        results.append(f"Generiert: {generated}")
        results.append(f"Uebersprungen (kein Docstring): {skipped}")
        if errors:
            results.append(f"Fehler: {len(errors)}")
            for err in errors[:5]:
                results.append(f"  - {err}")
        
        # Index generieren
        if index_entries and not dry_run:
            index_content = f"""BACH TOOLS INDEX
{'=' * 60}
Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Anzahl Tools: {len(index_entries)}

TOOL-UEBERSICHT
{'-' * 60}
"""
            for name, desc in sorted(index_entries):
                index_content += f"{name:<30} {desc}\n"
            
            index_content += f"""
{'-' * 60}
Befehle:
  bach tools list         Alle Tools anzeigen
  bach tools show <name>  Tool-Details
  bach tools docs         Dokumentation anzeigen
"""
            index_file = help_tools_dir / "_index.txt"
            index_file.write_text(index_content, encoding='utf-8')
            results.append(f"\n[INDEX] _index.txt ({len(index_entries)} Eintraege)")
        
        if not dry_run:
            results.append(f"\nDateien in: {help_tools_dir}")
        
        return True, "\n".join(results)
