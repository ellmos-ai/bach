#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
SearchHandler - Unified Search CLI for BACH
============================================
Implements: SQ064 (Semantische Suche) + SQ047 (Wissensindexierung)

Operationen:
  <query>                    Unified Volltextsuche (FTS5) ueber alle Quellen
  index                      Alle Quellen indexieren (wiki, memory, documents, KD)
  index knowledgedigest|kd   Nur KnowledgeDigest Skills + Wiki indexieren
  index wiki|memory|docs     Einzelne Quelle indexieren
  index <path>               Verzeichnis scannen und indexieren (ProFiler-Stil)
  status                     Index-Statistiken
  rebuild                    Index leeren und komplett neu aufbauen
  tags                       Alle Tags anzeigen
  dupes                      Duplikate finden (gleicher Hash, verschiedene Pfade)
  help                       Hilfe

Quellen (durchsucht gleichzeitig):
  - wiki_articles (413+ Artikel)
  - memory_working, memory_facts, memory_lessons
  - document_index (docs/help/ Dateien, FTS5)
  - KnowledgeDigest Skills + Wiki (766 + 413 Docs)
  - Beliebige gescannte Verzeichnisse (via 'index <path>')

Nutzt: tools/unified_search.py (UnifiedSearch Engine)
"""

import sys
from pathlib import Path
from typing import List, Tuple
from hub.base import BaseHandler


class SearchHandler(BaseHandler):
    """Unified Search Handler fuer BACH."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self._engine = None

    @property
    def profile_name(self) -> str:
        return "search"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "search": "Volltextsuche ueber alle Quellen (FTS5)",
            "index": "Quellen indexieren (alle oder Verzeichnis)",
            "status": "Index-Statistiken",
            "rebuild": "Index komplett neu aufbauen",
            "tags": "Alle Tags anzeigen",
            "dupes": "Duplikate finden",
            "help": "Hilfe anzeigen",
        }

    def _get_engine(self):
        """Lazy-Import der UnifiedSearch Engine."""
        if self._engine is None:
            tools_dir = self.base_path / "tools"
            if str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))
            from unified_search import UnifiedSearch
            self._engine = UnifiedSearch(self.db_path)
        return self._engine

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        op = (operation or "").lower().strip()

        # Default: wenn operation wie ein Suchbegriff aussieht
        if op and op not in ('index', 'status', 'rebuild', 'tags', 'dupes', 'help', 'scan'):
            # Alles was kein Keyword ist, wird als Suchquery behandelt
            query_parts = [op] + list(args)
            return self._search(query_parts)

        if op == "index":
            return self._index(args)
        elif op == "status":
            return self._status()
        elif op == "rebuild":
            return self._rebuild()
        elif op == "tags":
            return self._tags(args)
        elif op == "dupes":
            return self._dupes()
        elif op == "scan":
            return self._scan(args)
        elif op in ("", "help"):
            return self._help()
        else:
            return self._search([op] + list(args))

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------

    def _search(self, args: List[str]) -> Tuple[bool, str]:
        """Unified FTS5 search across all sources."""
        if not args:
            return False, "Usage: bach search <query> [--source wiki|memory|document|file] [--tag TAG] [--limit N]"

        # Parse args
        query_parts = []
        sources = None
        tags = None
        limit = 20

        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ('--source', '-s') and i + 1 < len(args):
                sources = [args[i + 1]]
                i += 2
            elif arg in ('--tag', '-t') and i + 1 < len(args):
                if tags is None:
                    tags = []
                tags.append(args[i + 1])
                i += 2
            elif arg in ('--limit', '-l') and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                query_parts.append(arg)
                i += 1

        query = " ".join(query_parts)
        if not query:
            return False, "Kein Suchbegriff angegeben."

        engine = self._get_engine()
        ok, results = engine.search(query, sources=sources, tags=tags, limit=limit)

        if not ok:
            return False, "Suche fehlgeschlagen."

        if not results:
            return True, f"Keine Treffer fuer: {query}"

        # Format output
        lines = [f"\n=== SUCHE: '{query}' — {len(results)} Treffer ===\n"]

        # Group by source for readability
        by_source = {}
        for r in results:
            src = r['source']
            if src not in by_source:
                by_source[src] = []
            by_source[src].append(r)

        source_labels = {
            'wiki': 'Wiki',
            'document': 'Dokumente',
            'memory_working': 'Memory (Working)',
            'memory_fact': 'Memory (Fakten)',
            'memory_lesson': 'Memory (Lessons)',
            'file': 'Dateien',
            'knowledgedigest_skill': 'KnowledgeDigest Skills',
            'knowledgedigest_wiki': 'KnowledgeDigest Wiki',
        }

        for src, items in by_source.items():
            label = source_labels.get(src, src)
            lines.append(f"── {label} ({len(items)}) ──")

            for r in items:
                tags_str = ""
                if r.get('tags'):
                    tags_str = f" [{', '.join(r['tags'][:5])}]"

                path_str = ""
                if r.get('source_path'):
                    try:
                        rel = Path(r['source_path']).relative_to(self.base_path)
                        path_str = f"  @ {rel}"
                    except (ValueError, TypeError):
                        path_str = f"  @ {r['source_path']}"

                lines.append(f"  {r['title']}{tags_str}")

                if path_str:
                    lines.append(f"  {path_str}")

                if r.get('snippet') and r['snippet'] != '(LIKE-Fallback)':
                    snippet = r['snippet'].replace('\n', ' ')[:120]
                    lines.append(f"    ...{snippet}...")

                lines.append("")

        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # INDEX
    # ------------------------------------------------------------------

    def _index(self, args: List[str]) -> Tuple[bool, str]:
        """Index all sources, a specific source, or scan a directory.

        Unterstuetzte Quellen:
          bach search index                   -- Alle Quellen indexieren
          bach search index knowledgedigest   -- Nur KnowledgeDigest indexieren
          bach search index wiki              -- Nur Wiki indexieren
          bach search index memory            -- Nur Memory indexieren
          bach search index documents         -- Nur Dokumente indexieren
          bach search index <pfad>            -- Verzeichnis scannen
        """
        engine = self._get_engine()

        if not args:
            # Index all BACH sources
            return engine.index_all()

        # Spezifische Quellen-Keywords pruefen
        source_keyword = args[0].lower().strip()
        source_methods = {
            "knowledgedigest": engine.index_knowledgedigest,
            "kd": engine.index_knowledgedigest,
            "wiki": engine.index_wiki,
            "memory": engine.index_memory,
            "documents": engine.index_documents,
            "docs": engine.index_documents,
        }

        if source_keyword in source_methods:
            return source_methods[source_keyword]()

        # Fallback: Verzeichnis scannen
        directory = args[0]
        no_tags = "--no-tags" in args
        return engine.scan_directory(directory, tags_from_path=not no_tags)

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def _status(self) -> Tuple[bool, str]:
        """Show index statistics."""
        engine = self._get_engine()
        ok, stats = engine.status()

        if not ok:
            return False, f"Status-Abfrage fehlgeschlagen: {stats.get('error', '?')}"

        lines = [
            "\n=== UNIFIED SEARCH INDEX ===",
            f"Gesamt-Eintraege:  {stats['total_items']}",
            f"Gesamt-Woerter:    {stats['total_words']:,}",
            f"Verschiedene Tags: {stats['total_tags']}",
            f"FTS5-Eintraege:    {stats['fts_entries']}",
            "",
            "Nach Quelle:",
        ]

        source_labels = {
            'wiki': 'Wiki', 'document': 'Dokumente',
            'memory_working': 'Memory Working', 'memory_fact': 'Memory Fakten',
            'memory_lesson': 'Memory Lessons', 'file': 'Dateien',
            'knowledgedigest_skill': 'KD Skills', 'knowledgedigest_wiki': 'KD Wiki',
        }

        for src, data in stats.get('by_source', {}).items():
            label = source_labels.get(src, src)
            lines.append(f"  {label:<20} {data['count']:>5} Eintraege, {data['words']:>8,} Woerter")

        if stats['total_items'] == 0:
            lines.extend([
                "",
                "Index ist leer. Zum Befuellen:",
                "  bach search index              Alle BACH-Quellen indexieren",
                "  bach search index <pfad>       Verzeichnis scannen",
            ])

        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # REBUILD
    # ------------------------------------------------------------------

    def _rebuild(self) -> Tuple[bool, str]:
        """Clear and rebuild entire index."""
        engine = self._get_engine()
        return engine.rebuild()

    # ------------------------------------------------------------------
    # TAGS
    # ------------------------------------------------------------------

    def _tags(self, args: List[str]) -> Tuple[bool, str]:
        """List all tags or search by tag."""
        engine = self._get_engine()

        # If args given, search by tag
        if args and args[0] not in ('--limit', '-l'):
            ok, results = engine.search_by_tag(args)
            if not results:
                return True, f"Keine Eintraege mit Tags: {', '.join(args)}"
            lines = [f"\n=== Eintraege mit Tags: {', '.join(args)} ===\n"]
            for r in results:
                lines.append(f"  [{r['source']}] {r['title']}")
                if r.get('source_path'):
                    lines.append(f"    @ {r['source_path']}")
                lines.append("")
            return True, "\n".join(lines)

        # List all tags
        limit = 50
        if '--limit' in args or '-l' in args:
            try:
                idx = args.index('--limit') if '--limit' in args else args.index('-l')
                limit = int(args[idx + 1])
            except (ValueError, IndexError):
                pass

        ok, tags = engine.list_tags(limit)
        if not tags:
            return True, "Keine Tags im Index."

        lines = ["\n=== Tags im Index ===\n"]
        for t in tags:
            lines.append(f"  {t['tag']:<35} ({t['count']} Eintraege)")
        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # DUPES
    # ------------------------------------------------------------------

    def _dupes(self) -> Tuple[bool, str]:
        """Find duplicate files."""
        engine = self._get_engine()
        ok, dupes = engine.find_duplicates()

        if not dupes:
            return True, "Keine Duplikate gefunden."

        lines = [f"\n=== Duplikate ({len(dupes)} Gruppen) ===\n"]
        for d in dupes:
            lines.append(f"  [{d['count']}x] Hash: {d['hash'][:16]}...")
            for p in d['paths']:
                lines.append(f"    {p}")
            lines.append("")
        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # SCAN (alias for index <path>)
    # ------------------------------------------------------------------

    def _scan(self, args: List[str]) -> Tuple[bool, str]:
        """Scan directory (alias for index <path>)."""
        if not args:
            return False, "Usage: bach search scan <verzeichnis>"
        return self._index(args)

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------

    def _help(self) -> Tuple[bool, str]:
        return True, """
=== BACH Unified Search (SQ064) ===

Befehle:
  bach search <query>              Suche ueber alle Quellen (FTS5)
  bach search <query> --source wiki  Nur in Wiki suchen
  bach search <query> --tag health   Nur Eintraege mit Tag 'health'
  bach search index                Alle BACH-Quellen indexieren
  bach search index knowledgedigest  Nur KnowledgeDigest indexieren (auch: kd)
  bach search index wiki           Nur Wiki indexieren
  bach search index memory         Nur Memory indexieren
  bach search index documents      Nur Dokumente indexieren (auch: docs)
  bach search index <pfad>         Verzeichnis scannen + indexieren
  bach search status               Index-Statistiken
  bach search rebuild              Index komplett neu aufbauen
  bach search tags                 Alle Tags anzeigen
  bach search tags health system   Eintraege mit diesen Tags finden
  bach search dupes                Duplikate finden (gleicher Hash)

Quellen (gleichzeitig durchsucht):
  wiki                    413+ Wiki-Artikel
  document                Dokumente aus document_index (docs/help/)
  memory_*                Working Memory, Fakten, Lessons Learned
  file                    Gescannte Verzeichnisse
  knowledgedigest_skill   Skills aus KnowledgeDigest
  knowledgedigest_wiki    Wiki aus KnowledgeDigest

Beispiele:
  bach search "bridge connector"
  bach search "encoding" --source memory_lesson
  bach search "entwickler" --source knowledgedigest_skill
  bach search index knowledgedigest
  bach search index C:\\Users\\YOUR_USERNAME\\Documents
  bach search tags health
"""
