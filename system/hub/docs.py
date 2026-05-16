# SPDX-License-Identifier: MIT
"""
Docs Handler - Hauptdokumentation (Markdown + Legacy)
======================================================

bach docs                    Zeige docs/README.md oder Liste
bach docs list               Alle Dokumentationen auflisten
bach docs <name>             Dokument anzeigen (z.B. getting-started)
bach docs guides/<name>      Guide aus guides/ anzeigen
bach docs reference/<name>   Reference aus reference/ anzeigen
bach docs search "keyword"   Dokumentation durchsuchen
bach docs sync               Sync: MD -> TXT für Legacy-Support

Neue Struktur (v2.6 Refactoring):
  docs/
    ├── README.md
    ├── getting-started.md
    ├── docs/help/              # Legacy .txt (aus docs/help/)
    ├── guides/            # Neue Markdown-Guides
    └── reference/         # API & Command Reference
"""
from pathlib import Path
import sqlite3
import re
import sys
from .base import BaseHandler
from .lang import get_lang, t


class DocsHandler(BaseHandler):
    """Handler für Hauptdokumentation (Markdown + Legacy-Support)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.docs_dir = base_path / "docs"

    @property
    def profile_name(self) -> str:
        return "docs"

    @property
    def target_file(self) -> Path:
        return self.docs_dir

    def get_operations(self) -> dict:
        return {
            "list": t("docs_list_desc", default="Alle Dokumentationen auflisten"),
            "<name>": t("docs_show_desc", default="Dokument anzeigen (z.B. getting-started)"),
            "guides/<name>": t("docs_guides_desc", default="Guide anzeigen (z.B. guides/db-sync)"),
            "reference/<name>": t("docs_ref_desc", default="Reference anzeigen"),
            "search": t("docs_search_desc", default="Dokumentation durchsuchen"),
            "sync": t("docs_sync_desc", default="MD -> TXT Sync (Legacy-Support)"),
            "migrate": t("docs_migrate_desc", default="TXT -> MD Migration"),
            "generate": t("docs_generate_desc", default="Generiere Dokumentation (SQ063) - bach docs generate <target>")
        }

    def _get_handlers_from_registry(self) -> list:
        """Lade alle Handler via File-Scan (SQ029 Fix).

        Scannt hub/*.py und extrahiert BaseHandler-Subklassen.

        Returns:
            Liste von (name, description) Tuples
        """
        handlers = []
        hub_dir = self.base_path / "hub"

        if not hub_dir.exists():
            return []

        # Scanne alle .py Dateien in hub/
        for py_file in sorted(hub_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            # Extrahiere Handler-Name (Dateiname ohne .py)
            handler_name = py_file.stem

            # Versuche Docstring aus erster Zeile zu lesen
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read(500)  # Erste 500 Zeichen

                # Suche nach "class XxxHandler(BaseHandler):"
                if 'BaseHandler' in content:
                    # Suche nach Docstring
                    lines = content.split('\n')
                    description = None
                    for i, line in enumerate(lines):
                        if 'class' in line and 'Handler' in line and 'BaseHandler' in line:
                            # Nächste Zeile könnte Docstring sein
                            if i + 1 < len(lines):
                                next_line = lines[i + 1].strip()
                                if next_line.startswith('"""') or next_line.startswith("'''"):
                                    description = next_line.strip('"\'').strip()
                            break

                    if not description:
                        description = f"{handler_name} handler"

                    handlers.append((handler_name, description))

            except Exception:
                # Fallback
                handlers.append((handler_name, f"{handler_name} handler"))

        return sorted(handlers)

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.docs_dir.exists():
            return False, f"Docs-Verzeichnis nicht gefunden: {self.docs_dir}"

        if operation == "list" or operation is None or operation == "":
            return self._list()
        elif operation == "sync":
            return self._sync_md_to_txt()
        elif operation == "migrate":
            if len(args) < 2:
                return False, "Usage: bach docs migrate <source.txt> <target.md>"
            return self._migrate_txt_to_md(args[0], args[1])
        elif operation == "search":
            if not args:
                return False, "Usage: bach docs search \"keyword\""
            return self._search(" ".join(args))
        elif operation == "generate":
            # SQ063: Dokumentations-Generator (Runde 6)
            # --lang Parameter extrahieren (TOWER_OF_BABEL v3.7.1)
            lang = None
            filtered_args = []
            i = 0
            while i < len(args):
                if args[i] == "--lang" and i + 1 < len(args):
                    lang = args[i + 1].lower()
                    i += 2
                else:
                    filtered_args.append(args[i])
                    i += 1
            target = filtered_args[0] if filtered_args else "all"
            return self._generate(target, lang=lang)
        elif operation == "show" and args:
            # API-Zugriff: docs.show("name")
            return self._show(args[0])
        else:
            return self._show(operation)

    def _list(self) -> tuple:
        """Alle Dokumentationen auflisten"""
        results = ["BACH DOKUMENTATION", "=" * 60, ""]

        # README
        readme = self.docs_dir / "README.md"
        if readme.exists():
            results.append("EINSTIEG")
            results.append("-" * 40)
            results.append("  README               bach docs README")
            results.append("")

        # Root-Level Docs (nach Kategorie)
        konzepte = []
        analysen = []
        andere = []

        for md_file in self.docs_dir.glob("*.md"):
            if md_file.name == "README.md":
                continue
            name = md_file.stem
            if 'konzept' in name.lower():
                konzepte.append(md_file)
            elif any(x in name.lower() for x in ['analyse', 'soll_ist', 'synopse']):
                analysen.append(md_file)
            else:
                andere.append(md_file)

        if konzepte:
            results.append("KONZEPTE")
            results.append("-" * 40)
            for doc in sorted(konzepte):
                results.append(f"  {doc.stem:<20} bach docs {doc.stem}")
            results.append("")

        if analysen:
            results.append("ANALYSEN")
            results.append("-" * 40)
            for doc in sorted(analysen):
                results.append(f"  {doc.stem:<20} bach docs {doc.stem}")
            results.append("")

        if andere:
            results.append("DOKUMENTATION")
            results.append("-" * 40)
            for doc in sorted(andere):
                results.append(f"  {doc.stem:<20} bach docs {doc.stem}")
            results.append("")

        # Guides
        guides_dir = self.docs_dir / "guides"
        if guides_dir.exists():
            guides = list(guides_dir.glob("*.md"))
            if guides:
                results.append("GUIDES")
                results.append("-" * 40)
                for guide in sorted(guides):
                    name = guide.stem
                    results.append(f"  {name:<20} bach docs guides/{name}")
                results.append("")

        # Reference
        ref_dir = self.docs_dir / "reference"
        if ref_dir.exists():
            refs = list(ref_dir.glob("*.md"))
            if refs:
                results.append("REFERENCE")
                results.append("-" * 40)
                for ref in sorted(refs):
                    name = ref.stem
                    results.append(f"  {name:<20} bach docs reference/{name}")
                results.append("")

        # Legacy Help (docs/help/)
        help_dir = self.docs_dir / "help"
        if help_dir.exists():
            txt_count = len(list(help_dir.rglob("*.txt")))
            if txt_count > 0:
                results.append("LEGACY HELP (.txt)")
                results.append("-" * 40)
                results.append(f"  {txt_count} Legacy-Hilfe-Dateien")
                results.append("  Zugriff: bach help <topic>")
                results.append("")

        results.append("Anzeigen: bach docs <name>")
        return True, "\n".join(results)

    def _show(self, name: str) -> tuple:
        """Dokument anzeigen (Markdown oder .txt)"""
        # Normalisieren: Backslash zu Slash
        name = name.replace("\\", "/")

        # README-Spezialfall
        if name.lower() in ("readme", "index"):
            doc_path = self.docs_dir / "README.md"
            if doc_path.exists():
                return self._render_markdown(doc_path, "README")

        # Unterordner-Pfad? (guides/db-sync, reference/cli-commands)
        if "/" in name:
            parts = name.split("/", 1)
            folder = parts[0]
            doc_name = parts[1] if len(parts) > 1 else "index"

            # Versuche .md
            doc_path = self.docs_dir / folder / f"{doc_name}.md"
            if doc_path.exists():
                return self._render_markdown(doc_path, f"{folder.upper()} / {doc_name}")

            # Versuche .txt (Legacy)
            doc_path = self.docs_dir / folder / f"{doc_name}.txt"
            if doc_path.exists():
                return self._render_text(doc_path, f"{folder.upper()} / {doc_name} (Legacy)")
        else:
            # Einfacher Name - versuche verschiedene Formate
            # 1. Root .md
            doc_path = self.docs_dir / f"{name}.md"
            if doc_path.exists():
                return self._render_markdown(doc_path, name.upper())

            # 2. guides/
            doc_path = self.docs_dir / "guides" / f"{name}.md"
            if doc_path.exists():
                return self._render_markdown(doc_path, f"GUIDE / {name}")

            # 3. reference/
            doc_path = self.docs_dir / "reference" / f"{name}.md"
            if doc_path.exists():
                return self._render_markdown(doc_path, f"REFERENCE / {name}")

            # 4. Fuzzy-Suche im Root
            for doc in self.docs_dir.glob("*.md"):
                if name.lower() in doc.stem.lower():
                    return self._render_markdown(doc, doc.stem.upper())

        return False, f"Dokument '{name}' nicht gefunden.\n\nVerfuegbar: bach docs list"

    def _render_markdown(self, path: Path, title: str) -> tuple:
        """Markdown-Datei anzeigen"""
        try:
            content = path.read_text(encoding="utf-8")
            header = f"DOCS: {title}\n{'='*60}\n\n"

            # Begrenze auf 100 Zeilen für Terminal-Ausgabe
            lines = content.splitlines()
            if len(lines) > 100:
                displayed = "\n".join(lines[:100])
                footer = f"\n\n... ({len(lines) - 100} weitere Zeilen)\nVollständig: {path}"
                return True, header + displayed + footer

            return True, header + content
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"

    def _render_text(self, path: Path, title: str) -> tuple:
        """Text-Datei anzeigen"""
        try:
            content = path.read_text(encoding="utf-8")
            header = f"DOCS: {title}\n{'='*60}\n\n"

            lines = content.splitlines()
            if len(lines) > 100:
                displayed = "\n".join(lines[:100])
                footer = f"\n\n... ({len(lines) - 100} weitere Zeilen)\nVollständig: {path}"
                return True, header + displayed + footer

            return True, header + content
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"

    def _search(self, keyword: str) -> tuple:
        """Dokumentation durchsuchen"""
        matches = []
        keyword_lower = keyword.lower()

        # Durchsuche alle .md Dateien
        for md_file in self.docs_dir.rglob("*.md"):
            match = self._search_file(md_file, keyword_lower)
            if match:
                rel_path = md_file.relative_to(self.docs_dir)
                matches.append((str(rel_path), match))

        # Durchsuche auch Legacy .txt
        help_dir = self.docs_dir / "help"
        if help_dir.exists():
            for txt_file in help_dir.rglob("*.txt"):
                if txt_file.name.startswith("_"):
                    continue
                match = self._search_file(txt_file, keyword_lower)
                if match:
                    rel_path = txt_file.relative_to(self.docs_dir)
                    matches.append((f"{rel_path} (Legacy)", match))

        if not matches:
            return True, f"Keine Treffer für: {keyword}"

        results = [f"DOCS-SUCHE: {keyword}", "=" * 60, ""]
        for name, context in matches[:20]:
            results.append(f"  {name}")
            if context:
                results.append(f"    ...{context}...")
            results.append("")

        if len(matches) > 20:
            results.append(f"... und {len(matches) - 20} weitere Treffer")

        results.append(f"{len(matches)} Treffer gesamt")
        return True, "\n".join(results)

    def _search_file(self, path: Path, keyword_lower: str) -> str:
        """Einzelne Datei durchsuchen, Kontext zurückgeben"""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            if keyword_lower in content or keyword_lower in path.stem.lower():
                idx = content.find(keyword_lower)
                if idx >= 0:
                    return content[max(0, idx-20):idx+len(keyword_lower)+30].replace("\n", " ")
                return ""
        except (OSError, UnicodeDecodeError):
            pass
        return None

    def _sync_md_to_txt(self) -> tuple:
        """Synchronisiere .md -> .txt für Legacy-Support"""
        count = 0
        errors = []

        # Durchsuche guides/ und reference/
        for subdir in ["guides", "reference"]:
            subdir_path = self.docs_dir / subdir
            if not subdir_path.exists():
                continue

            for md_file in subdir_path.glob("*.md"):
                try:
                    # MD -> TXT konvertieren
                    content = md_file.read_text(encoding="utf-8")
                    txt_content = self._markdown_to_plaintext(content)

                    # In docs/help/<subdir>/ ablegen
                    help_subdir = self.docs_dir / "help" / subdir
                    help_subdir.mkdir(parents=True, exist_ok=True)

                    txt_file = help_subdir / f"{md_file.stem}.txt"
                    txt_file.write_text(txt_content, encoding="utf-8")
                    count += 1
                except Exception as e:
                    errors.append(f"{md_file.name}: {e}")

        result = f"Sync abgeschlossen. {count} Dateien synchronisiert."
        if errors:
            result += f"\n\nFehler ({len(errors)}):\n  " + "\n  ".join(errors)

        return True, result

    def _migrate_txt_to_md(self, source: str, target: str) -> tuple:
        """Migriere .txt -> .md"""
        source_path = self.base_path / source
        target_path = self.base_path / target

        if not source_path.exists():
            return False, f"Quelle nicht gefunden: {source}"

        try:
            content = source_path.read_text(encoding="utf-8")
            # Einfache Konvertierung: Titel aus erster Zeile extrahieren
            lines = content.splitlines()
            title = source_path.stem.replace("_", " ").title()

            if lines and lines[0].strip():
                potential_title = lines[0].strip().lstrip("#-= ")
                if len(potential_title) > 2:
                    title = potential_title

            # Markdown-Header hinzufügen
            md_content = f"# {title}\n\n{content}"

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(md_content, encoding="utf-8")

            return True, f"Migration erfolgreich: {source} -> {target}"
        except Exception as e:
            return False, f"Migrations-Fehler: {e}"

    def _markdown_to_plaintext(self, md_content: str) -> str:
        """Konvertiere Markdown zu Plain Text (vereinfacht)"""
        text = md_content

        # Headers: # Title -> Title
        text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

        # Bold/Italic: **text** -> text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)

        # Links: [text](url) -> text (url)
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1 (\2)', text)

        # Code blocks: ```code``` -> code
        text = re.sub(r'```[\w]*\n(.+?)\n```', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'`(.+?)`', r'\1', text)

        # Lists: - item -> • item
        text = re.sub(r'^[-*+]\s+', '• ', text, flags=re.MULTILINE)

        return text

    def _generate(self, target: str, lang: str = None) -> tuple:
        """
        Generiere Dokumentation (SQ063 + TOWER_OF_BABEL v3.7.1).

        Args:
            target: readme|api|skills|agents|changelog|quickstart|full|all
            lang: Zielsprache ('de'/'en'), None = aktuelle System-Sprache

        Returns:
            tuple (success, message)
        """
        # Sprache bestimmen (TOWER_OF_BABEL)
        doc_lang = lang or get_lang()

        # Generatoren mit lang-Parameter (wo unterstuetzt)
        generators = {
            "readme": lambda: self._generate_readme(lang=doc_lang),
            "api": self._generate_api,
            "skills": lambda: self._generate_skills(lang=doc_lang),
            "agents": self._generate_agents,
            "changelog": self._generate_changelog,
            "quickstart": lambda: self._generate_quickstart(lang=doc_lang),
            "quickstart-pdf": self._generate_quickstart_pdf,
            "full": lambda: self._generate_full(lang=doc_lang)
        }

        if target == "all":
            # Alle Generatoren ausführen
            results = []
            for name, gen_func in generators.items():
                success, msg = gen_func()
                status = "✓" if success else "✗"
                results.append(f"{status} {name}: {msg}")
            return True, "\n".join(results)

        if target in generators:
            return generators[target]()
        else:
            return False, f"Unbekanntes Ziel: {target}\n\nVerfügbar: {', '.join(generators.keys())}, all"

    def _generate_readme(self, lang: str = None) -> tuple:
        """Generiere README.md aus DB + System-Info (TOWER_OF_BABEL: zweisprachig)."""
        try:
            doc_lang = lang or get_lang()

            # DB-Statistiken sammeln
            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            # Stats abrufen
            stats = {}
            stats['skills'] = cur.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            stats['agents'] = cur.execute("SELECT COUNT(*) FROM bach_agents").fetchone()[0]
            stats['tools'] = cur.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
            stats['lessons'] = cur.execute("SELECT COUNT(*) FROM memory_lessons").fetchone()[0]
            stats['facts'] = cur.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]

            # Workflows zaehlen
            workflows_dir = self.base_path / "skills" / "_workflows"
            stats['workflows'] = len(list(workflows_dir.rglob("*.md"))) if workflows_dir.exists() else 0

            # BACH-Version
            version = cur.execute(
                "SELECT value FROM system_config WHERE key='bach_version'"
            ).fetchone()
            version = version[0] if version else "unknown"

            conn.close()

            # README generieren
            readme_content = self._build_readme_content(stats, version, lang=doc_lang)

            # Dateiname: README.md (EN default) / README.de.md (DE)
            if doc_lang == "de":
                readme_path = self.base_path.parent / "README.de.md"
            else:
                readme_path = self.base_path.parent / "README.md"
            readme_path.write_text(readme_content, encoding="utf-8")

            return True, f"README{'.' + doc_lang if doc_lang != 'en' else ''}.md generiert: {readme_path}\n  {stats['skills']} Skills | {stats['agents']} Agents | {stats['tools']} Tools"

        except Exception as e:
            return False, f"Fehler bei README-Generierung: {e}"

    # TOWER_OF_BABEL: Zweisprachige Templates fuer Dokumentation
    _README_STRINGS = {
        'en': {
            'title': 'BACH - Text-Based Operating System for LLMs',
            'status': 'Production-Ready',
            'license': 'MIT',
            'overview_title': 'Overview',
            'overview_text': (
                'BACH is a text-based operating system that empowers Large Language Models (LLMs) '
                'to work, learn, and organize autonomously. It provides comprehensive infrastructure '
                'for task management, knowledge management, automation, and LLM orchestration.'
            ),
            'core_features': 'Core Features',
            'agents_label': 'AI Agents',
            'agents_desc': 'Specialized agents for various domains',
            'tools_label': 'Tools',
            'tools_desc': 'Extensive tool library for file processing, analysis, automation',
            'skills_label': 'Skills',
            'skills_desc': 'Reusable workflows and templates',
            'workflows_label': 'Workflows',
            'workflows_desc': 'Pre-built process protocols',
            'knowledge_label': 'Knowledge Store',
            'installation': 'Installation',
            'clone_repo': 'Clone repository',
            'install_deps': 'Install dependencies',
            'init_bach': 'Initialize BACH',
            'quick_start': 'Quick Start',
            'start_bach': 'Start BACH',
            'create_task': 'Create a task',
            'search_knowledge': 'Search knowledge',
            'stop_bach': 'Stop BACH',
            'components_title': 'Main Components',
            'comp_task_title': 'Task Management',
            'comp_task_desc': 'Complete GTD system with prioritization, deadlines, tags, and context tracking.',
            'comp_knowledge_title': 'Knowledge System',
            'comp_knowledge_desc': 'Structured memory system with facts, lessons, and automatic consolidation.',
            'comp_agents_title': 'Agent Framework',
            'comp_agents_desc': 'Boss agents orchestrate experts for complex tasks (office, health, production, etc.).',
            'comp_bridge_title': 'Bridge System',
            'comp_bridge_desc': 'Connector framework for external services (Telegram, Email, WhatsApp, etc.).',
            'comp_auto_title': 'Automation',
            'comp_auto_desc': 'Scheduler for recurring tasks and event-based workflows.',
            'docs_title': 'Documentation',
            'docs_getting_started': 'Getting Started',
            'docs_getting_started_desc': 'First steps with BACH',
            'docs_api': 'API Reference',
            'docs_api_desc': 'Complete API documentation',
            'docs_skills': 'Skills Catalog',
            'docs_skills_desc': 'All available skills',
            'docs_agents': 'Agents Catalog',
            'docs_agents_desc': 'All available agents',
            'license_title': 'License',
            'license_text': 'MIT License - see [LICENSE](LICENSE) for details.',
            'support_title': 'Support',
            'generated_with': 'Generated with',
            'lang_link': 'Deutsche Version: [README.de.md](README.de.md)',
        },
        'de': {
            'title': 'BACH - Textbasiertes Betriebssystem fuer LLMs',
            'status': 'Production-Ready',
            'license': 'MIT',
            'overview_title': 'Ueberblick',
            'overview_text': (
                'BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) '
                'befaehigt, eigenstaendig zu arbeiten, zu lernen und sich zu organisieren. '
                'Es bietet eine umfassende Infrastruktur fuer Task-Management, Wissensmanagement, '
                'Automatisierung und LLM-Orchestrierung.'
            ),
            'core_features': 'Kernfunktionen',
            'agents_label': 'KI-Agenten',
            'agents_desc': 'Spezialisierte Agenten fuer verschiedene Aufgabenbereiche',
            'tools_label': 'Tools',
            'tools_desc': 'Umfangreiche Tool-Bibliothek fuer Dateiverarbeitung, Analyse, Automation',
            'skills_label': 'Skills',
            'skills_desc': 'Wiederverwendbare Workflows und Templates',
            'workflows_label': 'Workflows',
            'workflows_desc': 'Vorgefertigte Prozess-Protokolle',
            'knowledge_label': 'Wissensspeicher',
            'installation': 'Installation',
            'clone_repo': 'Repository klonen',
            'install_deps': 'Abhaengigkeiten installieren',
            'init_bach': 'BACH initialisieren',
            'quick_start': 'Quick Start',
            'start_bach': 'BACH starten',
            'create_task': 'Task erstellen',
            'search_knowledge': 'Wissen abrufen',
            'stop_bach': 'BACH beenden',
            'components_title': 'Hauptkomponenten',
            'comp_task_title': 'Task-Management',
            'comp_task_desc': 'Vollstaendiges GTD-System mit Priorisierung, Deadlines, Tags und Context-Tracking.',
            'comp_knowledge_title': 'Wissenssystem',
            'comp_knowledge_desc': 'Strukturiertes Memory-System mit Facts, Lessons und automatischer Konsolidierung.',
            'comp_agents_title': 'Agenten-Framework',
            'comp_agents_desc': 'Boss-Agenten orchestrieren Experten fuer komplexe Aufgaben (Buero, Gesundheit, Produktion, etc.).',
            'comp_bridge_title': 'Bridge-System',
            'comp_bridge_desc': 'Connector-Framework fuer externe Services (Telegram, Email, WhatsApp, etc.).',
            'comp_auto_title': 'Automatisierung',
            'comp_auto_desc': 'Scheduler fuer wiederkehrende Tasks und Event-basierte Workflows.',
            'docs_title': 'Dokumentation',
            'docs_getting_started': 'Erste Schritte',
            'docs_getting_started_desc': 'Erste Schritte mit BACH',
            'docs_api': 'API-Referenz',
            'docs_api_desc': 'Vollstaendige API-Dokumentation',
            'docs_skills': 'Skills-Katalog',
            'docs_skills_desc': 'Alle verfuegbaren Skills',
            'docs_agents': 'Agenten-Katalog',
            'docs_agents_desc': 'Alle verfuegbaren Agenten',
            'license_title': 'Lizenz',
            'license_text': 'MIT License - siehe [LICENSE](LICENSE) fuer Details.',
            'support_title': 'Support',
            'generated_with': 'Generiert mit',
            'lang_link': 'English version: [README.md](README.md)',
        }
    }

    def _build_readme_content(self, stats: dict, version: str, lang: str = 'en') -> str:
        """Erstelle README-Inhalt (TOWER_OF_BABEL: zweisprachig)."""
        s = self._README_STRINGS.get(lang, self._README_STRINGS['en'])

        content = f"""# {s['title']}

**Version:** {version}
**Status:** {s['status']}
**{s['license_title']}:** {s['license']}

## {s['overview_title']}

{s['overview_text']}

### {s['core_features']}

- **{stats['agents']} {s['agents_label']}** - {s['agents_desc']}
- **{stats['tools']} {s['tools_label']}** - {s['tools_desc']}
- **{stats['skills']} {s['skills_label']}** - {s['skills_desc']}
- **{stats['workflows']} {s['workflows_label']}** - {s['workflows_desc']}
- **{s['knowledge_label']}** - {stats['lessons']} Lessons + {stats['facts']} Facts

## {s['installation']}

```bash
# {s['clone_repo']}
git clone https://github.com/ellmos-ai/bach.git
cd bach

# {s['install_deps']}
pip install -r requirements.txt

# {s['init_bach']}
python system/setup.py
```

## {s['quick_start']}

```bash
# {s['start_bach']}
python bach.py --startup

# {s['create_task']}
python bach.py task add "Analysiere Projektstruktur"

# {s['search_knowledge']}
python bach.py wiki search "Task Management"

# {s['stop_bach']}
python bach.py --shutdown
```

## {s['components_title']}

### 1. {s['comp_task_title']}
{s['comp_task_desc']}

### 2. {s['comp_knowledge_title']}
{s['comp_knowledge_desc']}

### 3. {s['comp_agents_title']}
{s['comp_agents_desc']}

### 4. {s['comp_bridge_title']}
{s['comp_bridge_desc']}

### 5. {s['comp_auto_title']}
{s['comp_auto_desc']}

## {s['docs_title']}

- **[{s['docs_getting_started']}](docs/getting-started.md)** - {s['docs_getting_started_desc']}
- **[{s['docs_api']}](docs/reference/)** - {s['docs_api_desc']}
- **[{s['docs_skills']}](SKILLS.md)** - {s['docs_skills_desc']}
- **[{s['docs_agents']}](AGENTS.md)** - {s['docs_agents_desc']}

## {s['license_title']}

{s['license_text']}

## {s['support_title']}

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

{s['lang_link']}

*{s['generated_with']} `bach docs generate readme --lang {lang}`*
"""
        return content

    def _generate_api(self) -> tuple:
        """Generiere API-Referenz aus HandlerRegistry + tools."""
        try:
            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            # Alle Handler abrufen (SQ029 Fix: von HandlerRegistry statt DB)
            handlers_from_registry = self._get_handlers_from_registry()
            # Format anpassen: (name, module_path, description)
            # Registry hat nur (name, description) - module_path ergänzen
            handlers = [(name, f"hub.{name}", desc) for name, desc in handlers_from_registry]

            # Alle Tools gruppiert nach Kategorie
            # SQ029 Fix: Spalte heißt "path" nicht "file_path"
            cur.execute("""
                SELECT category, name, description, path
                FROM tools
                WHERE is_available = 1
                ORDER BY category, name
            """)
            tools = cur.fetchall()

            # Gruppiere Tools nach Kategorie
            tools_by_category = {}
            for category, name, desc, path in tools:
                cat = category or "Uncategorized"
                if cat not in tools_by_category:
                    tools_by_category[cat] = []
                tools_by_category[cat].append((name, desc or "", path))

            conn.close()

            # API.md generieren
            content = self._build_api_content(handlers, tools_by_category)
            api_path = self.base_path / "docs" / "reference" / "api.md"
            api_path.parent.mkdir(parents=True, exist_ok=True)
            api_path.write_text(content, encoding="utf-8")

            total_tools = sum(len(t) for t in tools_by_category.values())
            return True, f"API-Referenz generiert: {api_path}\n  {len(handlers)} Handler | {total_tools} Tools in {len(tools_by_category)} Kategorien"

        except Exception as e:
            return False, f"Fehler bei API-Generierung: {e}"

    def _build_api_content(self, handlers: list, tools_by_category: dict) -> str:
        """Erstelle API-Referenz Inhalt."""
        total_tools = sum(len(t) for t in tools_by_category.values())

        content = f"""# BACH API-Referenz

**Generiert:** Automatisch aus der BACH-Datenbank

## Übersicht

BACH bietet zwei Hauptzugangswege zur Funktionalität:

1. **Handler** (CLI-Interface) - `bach <handler> <operation> [args]`
2. **Tools** (Programmatische API) - Wiederverwendbare Python-Module

---

## 1. Handler ({len(handlers)})

Handler sind die CLI-Schnittstelle von BACH. Jeder Handler verwaltet einen funktionalen Bereich.

### Verfügbare Handler

"""

        # Handler-Liste
        for name, module_path, desc in sorted(handlers):
            content += f"#### `bach {name}`\n"
            if desc and desc.strip():
                content += f"{desc}\n"
            content += f"\n**Modul:** `{module_path}`\n\n"

        content += f"""---

## 2. Tools ({total_tools})

Tools sind programmatische Module für spezifische Aufgaben. Sie können direkt in Python importiert und verwendet werden.

### Tools nach Kategorie

"""

        # Kategorie-Übersicht
        for category in sorted(tools_by_category.keys()):
            count = len(tools_by_category[category])
            content += f"- **{category}**: {count} Tools\n"
        content += "\n---\n\n"

        # Detaillierte Tool-Listings pro Kategorie
        for category in sorted(tools_by_category.keys()):
            tools = tools_by_category[category]
            content += f"### {category} ({len(tools)})\n\n"

            for name, desc, path in sorted(tools):
                content += f"#### `{name}`\n"
                if desc and desc.strip():
                    # Erster Satz als Kurzbeschreibung
                    short_desc = desc.split('.')[0].strip()
                    content += f"{short_desc}.\n\n"
                content += f"**Pfad:** `{path}`\n\n"

            content += "---\n\n"

        content += """
## Verwendung

### Handler via CLI

```bash
# Handler-Hilfe anzeigen
python bach.py <handler> --help

# Beispiel: Task-Management
python bach.py task add "Neue Aufgabe"
python bach.py task list
```

### Tools via Python-API

```python
from system.hub import bach_api

# Beispiel: Wiki-Suche
results = bach_api.wiki.search("Keyword")

# Beispiel: Task erstellen
bach_api.task.add(
    title="Neue Aufgabe",
    priority=1
)
```

---

*Generiert mit `bach docs generate api`*
"""
        return content

    def _generate_skills(self, lang: str = None) -> tuple:
        """Generiere Skills-Katalog aus skills-Tabelle (TOWER_OF_BABEL: zweisprachig)."""
        try:
            doc_lang = lang or get_lang()

            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            # Alle Skills gruppiert nach Typ
            cur.execute("""
                SELECT type, name, category, description
                FROM skills
                WHERE is_active = 1
                ORDER BY type, category, name
            """)
            skills = cur.fetchall()

            # Gruppiere nach Typ
            skills_by_type = {}
            for skill_type, name, category, desc in skills:
                if skill_type not in skills_by_type:
                    skills_by_type[skill_type] = []
                skills_by_type[skill_type].append((name, category, desc or ""))

            conn.close()

            # SKILLS.md generieren
            content = self._build_skills_content(skills_by_type, lang=doc_lang)
            if doc_lang == "de":
                skills_path = self.base_path.parent / "SKILLS.de.md"
            else:
                skills_path = self.base_path.parent / "SKILLS.md"
            skills_path.write_text(content, encoding="utf-8")

            total = sum(len(skills) for skills in skills_by_type.values())
            return True, f"SKILLS{'.' + doc_lang if doc_lang != 'en' else ''}.md generiert: {skills_path}\n  {total} Skills in {len(skills_by_type)} Kategorien"

        except Exception as e:
            return False, f"Fehler bei Skills-Generierung: {e}"

    def _build_skills_content(self, skills_by_type: dict, lang: str = 'en') -> str:
        """Erstelle SKILLS.md Inhalt (TOWER_OF_BABEL: zweisprachig)."""
        total = sum(len(skills) for skills in skills_by_type.values())

        if lang == 'de':
            title = "BACH Skills-Katalog"
            count_label = "Anzahl"
            generated = "Generiert"
            generated_from = "Automatisch aus der Skills-Datenbank"
            overview = "Ueberblick"
            overview_text = "Dieser Katalog listet alle verfuegbaren Skills auf, gruppiert nach Typ."
            by_type = "Skills nach Typ"
            cat_label = "Kategorie"
            generated_with = "Generiert mit"
        else:
            title = "BACH Skills Catalog"
            count_label = "Count"
            generated = "Generated"
            generated_from = "Automatically from the skills database"
            overview = "Overview"
            overview_text = "This catalog lists all available skills, grouped by type."
            by_type = "Skills by Type"
            cat_label = "Category"
            generated_with = "Generated with"

        content = f"""# {title}

**{count_label}:** {total} Skills
**{generated}:** {generated_from}

## {overview}

{overview_text}

"""

        # Typ-Uebersicht
        content += f"### {by_type}\n\n"
        for skill_type in sorted(skills_by_type.keys()):
            count = len(skills_by_type[skill_type])
            content += f"- **{skill_type}**: {count} Skills\n"
        content += "\n---\n\n"

        # Detaillierte Listings pro Typ
        for skill_type in sorted(skills_by_type.keys()):
            skills = skills_by_type[skill_type]
            content += f"## {skill_type.upper()} ({len(skills)})\n\n"

            for name, category, desc in sorted(skills):
                content += f"### `{name}`\n"
                if category:
                    content += f"**{cat_label}:** {category}  \n"
                if desc and desc.strip():
                    content += f"{desc}\n"
                content += "\n"

            content += "---\n\n"

        content += f"\n*{generated_with} `bach docs generate skills --lang {lang}`*\n"
        return content

    def _generate_agents(self) -> tuple:
        """Generiere Agenten-Katalog aus bach_agents + bach_experts."""
        try:
            # Nutze bestehenden AgentsExporter (SQ071)
            from ..tools.agents_export import AgentsExporter

            exporter = AgentsExporter(self.base_path.parent)
            success, msg = exporter.generate()

            if success:
                return True, f"AGENTS.md generiert via agents_export.py\n  {msg}"
            else:
                return False, f"Fehler bei Agenten-Generierung: {msg}"

        except Exception as e:
            return False, f"Fehler bei Agenten-Generierung: {e}"

    def _generate_changelog(self) -> tuple:
        """Generiere CHANGELOG.md aus dist_file_versions."""
        try:
            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            # Abrufen der dist_file_versions gruppiert nach Version
            cur.execute("""
                SELECT version, file_path, file_hash, created_at, dist_type
                FROM dist_file_versions
                ORDER BY created_at DESC, version DESC
                LIMIT 500
            """)
            versions = cur.fetchall()

            # BACH-Version abrufen
            bach_version = cur.execute(
                "SELECT value FROM system_config WHERE key='bach_version'"
            ).fetchone()
            bach_version = bach_version[0] if bach_version else "unknown"

            conn.close()

            # CHANGELOG generieren
            content = self._build_changelog_content(versions, bach_version)
            changelog_path = self.base_path.parent / "CHANGELOG.md"
            changelog_path.write_text(content, encoding="utf-8")

            return True, f"CHANGELOG.md generiert: {changelog_path}\n  {len(versions)} Datei-Versionen dokumentiert"

        except Exception as e:
            return False, f"Fehler bei CHANGELOG-Generierung: {e}"

    def _build_changelog_content(self, versions: list, bach_version: str) -> str:
        """Erstelle CHANGELOG-Inhalt."""
        content = f"""# BACH Changelog

**Aktuelle Version:** {bach_version}
**Generiert:** Automatisch aus dist_file_versions

## Übersicht

Dieses Changelog dokumentiert Änderungen an CORE- und TEMPLATE-Dateien über Versionen hinweg.

### Legende

- 🔴 **CORE** (dist_type=2) - Kernel-Dateien, kritisch für BACH
- 🟡 **TEMPLATE** (dist_type=1) - Anpassbare Vorlagen
- ⚪ **USER** (dist_type=0) - Benutzerdaten

---

## Versionshistorie

"""

        # Gruppiere nach Datum (YYYY-MM-DD)
        by_date = {}
        for version, file_path, file_hash, created_at, dist_type in versions:
            # Extrahiere Datum (erste 10 Zeichen: YYYY-MM-DD)
            date = created_at[:10] if created_at and len(created_at) >= 10 else "unknown"
            if date not in by_date:
                by_date[date] = []

            # Dist-Type Icon
            icon = "🔴" if dist_type == 2 else "🟡" if dist_type == 1 else "⚪"

            by_date[date].append((icon, version, file_path, file_hash[:8]))

        # Ausgabe nach Datum sortiert (neueste zuerst)
        for date in sorted(by_date.keys(), reverse=True)[:30]:  # Nur letzte 30 Tage
            entries = by_date[date]
            content += f"### {date}\n\n"
            content += f"**Geänderte Dateien:** {len(entries)}\n\n"

            # Gruppiere nach Version
            by_version = {}
            for icon, version, path, hash_short in entries:
                if version not in by_version:
                    by_version[version] = []
                by_version[version].append((icon, path, hash_short))

            # Ausgabe pro Version
            for version in sorted(by_version.keys(), reverse=True):
                files = by_version[version]
                content += f"#### Version {version} ({len(files)} Dateien)\n\n"

                # Limitiere auf 10 Dateien pro Version für Lesbarkeit
                for icon, path, hash_short in files[:10]:
                    # Kürze Pfad wenn zu lang
                    short_path = path if len(path) < 60 else "..." + path[-57:]
                    content += f"- {icon} `{short_path}` ({hash_short})\n"

                if len(files) > 10:
                    content += f"- ... und {len(files) - 10} weitere Dateien\n"

                content += "\n"

            content += "---\n\n"

        content += f"""
## Format

Jeder Eintrag zeigt:
- **Icon**: Dist-Type (CORE/TEMPLATE/USER)
- **Pfad**: Relativer Pfad der geänderten Datei
- **Hash**: Kurz-Hash (erste 8 Zeichen) zur Identifikation

## Vollständige Historie

Für vollständige Versionshistorie siehe `dist_file_versions` Tabelle in bach.db:

```bash
python bach.py db info dist_file_versions
```

---

*Generiert mit `bach docs generate changelog`*
"""
        return content

    def _generate_quickstart(self, lang: str = None) -> tuple:
        """Generiere QUICKSTART.md aus DB-Daten (TOWER_OF_BABEL: zweisprachig)."""
        try:
            doc_lang = lang or get_lang()

            db_path = self.base_path / "data" / "bach.db"
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()

            # BACH-Version abrufen
            version = cur.execute(
                "SELECT value FROM system_config WHERE key='bach_version'"
            ).fetchone()
            version = version[0] if version else "unknown"

            conn.close()

            # Top-5 Handler (SQ029 Fix: von HandlerRegistry statt DB)
            all_handlers = self._get_handlers_from_registry()
            # Filtere Top-5 wichtigste Handler
            top_5_names = {'task', 'wiki', 'mem', 'agent', 'docs'}
            handlers = [
                (name, desc) for name, desc in all_handlers
                if name in top_5_names
            ]

            # QUICKSTART.md generieren
            content = self._build_quickstart_content(version, handlers, lang=doc_lang)
            if doc_lang == "de":
                quickstart_path = self.base_path.parent / "QUICKSTART.de.md"
            else:
                quickstart_path = self.base_path.parent / "QUICKSTART.md"
            quickstart_path.write_text(content, encoding="utf-8")

            return True, f"QUICKSTART{'.' + doc_lang if doc_lang != 'en' else ''}.md generiert: {quickstart_path}"

        except Exception as e:
            return False, f"Fehler bei Quickstart-Generierung: {e}"

    def _generate_quickstart_pdf(self) -> tuple:
        """Generiere QUICKSTART.pdf aus QUICKSTART.md (SQ063)."""
        try:
            # 1. Stelle sicher dass QUICKSTART.md existiert
            quickstart_md = self.base_path.parent / "QUICKSTART.md"
            if not quickstart_md.exists():
                # Generiere QUICKSTART.md erst
                success, msg = self._generate_quickstart()
                if not success:
                    return False, f"Fehler: QUICKSTART.md konnte nicht generiert werden: {msg}"

            # 2. Importiere MD-to-PDF Converter
            sys.path.insert(0, str(self.base_path / "tools" / "converters"))
            try:
                from md_to_pdf import convert_file
            except ImportError:
                return False, "Fehler: md_to_pdf.py nicht gefunden in tools/converters/"

            # 3. Ziel-PDF-Pfad
            quickstart_pdf = self.base_path.parent / "QUICKSTART.pdf"

            # 4. Konvertiere MD -> PDF (auto-detect Engine)
            pdf_path = convert_file(
                quickstart_md,
                quickstart_pdf,
                engine="auto",
                show_page_numbers=True,
                show_footer=True,
                show_header=True,
                show_date=True
            )

            return True, f"✓ QUICKSTART.pdf generiert: {pdf_path}"

        except Exception as e:
            return False, f"Fehler bei Quickstart-PDF-Generierung: {e}"

    def _build_quickstart_content(self, version: str, handlers: list, lang: str = 'en') -> str:
        """Erstelle QUICKSTART-Inhalt (TOWER_OF_BABEL: zweisprachig)."""
        if lang == 'de':
            content = f"""# BACH Quickstart Guide

**Version:** {version}

## In 5 Minuten zu Ihrem ersten BACH-Workflow

### 1. Installation (2 Minuten)

```bash
# Repository klonen
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Abhaengigkeiten installieren
pip install -r requirements.txt

# BACH initialisieren
python system/setup.py
```

### 2. Erste Schritte (3 Minuten)

#### BACH starten

```bash
python bach.py --startup
```

#### Task erstellen und verwalten

```bash
# Neue Aufgabe anlegen
python bach.py task add "Erstes BACH-Experiment"

# Aufgaben anzeigen
python bach.py task list

# Aufgabe erledigen
python bach.py task done 1
```

#### Wissen speichern und abrufen

```bash
# Notiz ins Wiki schreiben
python bach.py wiki write "bash-tricks" "Nuetzliche Bash-Befehle sammeln"

# Wissen suchen
python bach.py wiki search "bash"
```

#### Memory-System nutzen

```bash
# Wichtigen Fakt speichern
python bach.py mem write fact "Projekt-Deadline: 2024-12-31"

# Facts abrufen
python bach.py mem read facts
```

#### BACH beenden

```bash
python bach.py --shutdown
```

---

## Wichtigste Kommandos

"""
        else:
            content = f"""# BACH Quickstart Guide

**Version:** {version}

## Your First BACH Workflow in 5 Minutes

### 1. Installation (2 Minutes)

```bash
# Clone repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies
pip install -r requirements.txt

# Initialize BACH
python system/setup.py
```

### 2. First Steps (3 Minutes)

#### Start BACH

```bash
python bach.py --startup
```

#### Create and Manage Tasks

```bash
# Create a new task
python bach.py task add "First BACH experiment"

# List tasks
python bach.py task list

# Complete a task
python bach.py task done 1
```

#### Store and Retrieve Knowledge

```bash
# Write a wiki note
python bach.py wiki write "bash-tricks" "Collecting useful bash commands"

# Search knowledge
python bach.py wiki search "bash"
```

#### Use the Memory System

```bash
# Store an important fact
python bach.py mem write fact "Project deadline: 2024-12-31"

# Retrieve facts
python bach.py mem read facts
```

#### Stop BACH

```bash
python bach.py --shutdown
```

---

## Essential Commands

"""

        # Handler-Referenz
        for name, desc in handlers:
            if desc and desc.strip():
                content += f"### `bach {name}`\n{desc}\n\n"

        if lang == 'de':
            content += """---

## Naechste Schritte

1. **Dokumentation erkunden**
   ```bash
   python bach.py docs list
   ```

2. **Agenten kennenlernen**
   ```bash
   python bach.py agent list
   ```

3. **Skills durchsuchen**
   ```bash
   cat SKILLS.md
   ```

4. **Eigenen Workflow erstellen**
   - Siehe: [Skills/_workflows/](skills/workflows/)
   - Beispiele fuer wiederkehrende Aufgaben

---

## Konfiguration

BACH passt sich automatisch an, aber Sie koennen anpassen:

- **Partner konfigurieren:** `python bach.py partner register claude`
- **Settings aendern:** `python bach.py config list`
- **Connector einrichten:** `python bach.py connector list`

---

## Weiterfuehrende Dokumentation

- **[README.md](README.md)** - Vollstaendige Uebersicht
- **[API-Referenz](docs/reference/api.md)** - Programmier-Interface
- **[Skills-Katalog](SKILLS.md)** - Alle verfuegbaren Skills
- **[Agenten-Katalog](AGENTS.md)** - Alle verfuegbaren Agenten

---

## Tipps

1. **Kontextuelles Arbeiten:** BACH merkt sich, woran Sie arbeiten
2. **Automatisierung:** Nutzen Sie Workflows fuer wiederkehrende Aufgaben
3. **Integration:** Verbinden Sie BACH mit Claude, Gemini oder Ollama
4. **Backup:** Regelmaessig `python bach.py backup create`

---

## Hilfe bekommen

```bash
# Allgemeine Hilfe
python bach.py --help

# Handler-spezifische Hilfe
python bach.py <handler> --help

# Dokumentation durchsuchen
python bach.py docs search "keyword"
```

---

English version: [QUICKSTART.md](QUICKSTART.md)

*Generiert mit `bach docs generate quickstart --lang de`*
"""
        else:
            content += """---

## Next Steps

1. **Explore documentation**
   ```bash
   python bach.py docs list
   ```

2. **Discover agents**
   ```bash
   python bach.py agent list
   ```

3. **Browse skills**
   ```bash
   cat SKILLS.md
   ```

4. **Create your own workflow**
   - See: [Skills/_workflows/](skills/workflows/)
   - Examples for recurring tasks

---

## Configuration

BACH adapts automatically, but you can customize:

- **Configure partner:** `python bach.py partner register claude`
- **Change settings:** `python bach.py config list`
- **Set up connector:** `python bach.py connector list`

---

## Further Documentation

- **[README.md](README.md)** - Complete overview
- **[API Reference](docs/reference/api.md)** - Programming interface
- **[Skills Catalog](SKILLS.md)** - All available skills
- **[Agents Catalog](AGENTS.md)** - All available agents

---

## Tips

1. **Contextual work:** BACH remembers what you're working on
2. **Automation:** Use workflows for recurring tasks
3. **Integration:** Connect BACH with Claude, Gemini, or Ollama
4. **Backup:** Regularly `python bach.py backup create`

---

## Getting Help

```bash
# General help
python bach.py --help

# Handler-specific help
python bach.py <handler> --help

# Search documentation
python bach.py docs search "keyword"
```

---

Deutsche Version: [QUICKSTART.de.md](QUICKSTART.de.md)

*Generated with `bach docs generate quickstart --lang en`*
"""
        return content

    def _generate_full(self, lang: str = None) -> tuple:
        """Generiere vollstaendige Dokumentation (alle Generatoren, TOWER_OF_BABEL: zweisprachig)."""
        try:
            doc_lang = lang or get_lang()
            results = []
            success_count = 0
            fail_count = 0

            # Reihenfolge: README -> QUICKSTART -> SKILLS -> AGENTS -> API -> CHANGELOG
            generators = [
                ("README", lambda: self._generate_readme(lang=doc_lang)),
                ("QUICKSTART", lambda: self._generate_quickstart(lang=doc_lang)),
                ("SKILLS", lambda: self._generate_skills(lang=doc_lang)),
                ("AGENTS", self._generate_agents),
                ("API", self._generate_api),
                ("CHANGELOG", self._generate_changelog)
            ]

            for name, gen_func in generators:
                try:
                    success, msg = gen_func()
                    if success:
                        status = "✓"
                        success_count += 1
                    else:
                        status = "✗"
                        fail_count += 1
                    results.append(f"{status} {name}: {msg}")
                except Exception as e:
                    status = "✗"
                    fail_count += 1
                    results.append(f"{status} {name}: Fehler - {e}")

            summary = f"\n{'='*60}\nFull-Dokumentation generiert\n"
            summary += f"Erfolgreich: {success_count} | Fehler: {fail_count}\n{'='*60}"

            return True, "\n".join(results) + summary

        except Exception as e:
            return False, f"Fehler bei Full-Dokumentations-Generierung: {e}"
