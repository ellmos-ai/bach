# SPDX-License-Identifier: MIT
"""
Context Handler - Kontext-Suche und Longterm-Memory
====================================================

Ermoeglicht Durchsuchen von:
- Memory-Archiv
- Chat-Historie
- Task-Beschreibungen
- System-Dateien
"""
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional
from .base import BaseHandler


class ContextHandler(BaseHandler):
    """Handler fuer --context Operationen."""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.memory_dir = base_path / "memory"
        self.logs_dir = base_path / "data" / "logs"
    
    @property
    def profile_name(self) -> str:
        return "context"
    
    @property
    def target_file(self) -> Path:
        return self.memory_dir
    
    def get_operations(self) -> dict:
        return {
            "auto": "Automatisch relevanten Kontext laden",
            "search": "Suche mit Begriffen (AND/OR/NOT)",
            "longterm": "Memory-Archiv durchsuchen",
            "recent": "Letzte N Eintraege anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> Tuple[bool, str]:
        """Verarbeitet Context-Anfragen."""
        
        if operation == "auto":
            return self._auto_context()
        
        elif operation == "search":
            if not args:
                return False, "Usage: --context search \"BEGRIFF\" [--from DATE] [--to DATE]"
            return self._search(args)
        
        elif operation == "longterm":
            return self._longterm(args)
        
        elif operation == "recent":
            count = int(args[0]) if args else 5
            return self._recent(count)
        
        else:
            return self._auto_context()  # Default
    
    def _auto_context(self) -> Tuple[bool, str]:
        """Laedt automatisch relevanten Kontext."""
        results = []
        results.append("=" * 50)
        results.append("AUTO-KONTEXT")
        results.append("=" * 50)
        
        # 1. Letzte Memory-Eintraege
        results.append("\n[LETZTE MEMORY-EINTRAEGE]")
        recent = self._get_recent_memories(3)
        for mem in recent:
            results.append(f"  - {mem['date']}: {mem['summary'][:60]}")
        
        # 2. Offene high-prio Tasks
        results.append("\n[OFFENE PRIORITAETS-TASKS]")
        tasks = self._get_priority_tasks()
        for task in tasks[:5]:
            results.append(f"  - [{task['priority']}] {task['title'][:50]}")
        
        # 3. Lessons Learned Kurzfassung
        results.append("\n[LESSONS LEARNED - TOP 5]")
        lessons = self._get_lessons_summary()
        for lesson in lessons[:5]:
            results.append(f"  - {lesson}")
        
        # 4. Aktuelle Warnungen
        warnings = self._get_warnings()
        if warnings:
            results.append("\n[AKTUELLE WARNUNGEN]")
            for warn in warnings:
                results.append(f"  ! {warn}")
        
        return True, "\n".join(results)
    
    def _search(self, args: list) -> Tuple[bool, str]:
        """Durchsucht alle Quellen mit Suchbegriff."""
        # Args parsen
        query = []
        from_date = None
        to_date = None
        scope = "all"  # all, system, longterm
        
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--from" and i + 1 < len(args):
                from_date = args[i + 1]
                i += 2
            elif arg == "--to" and i + 1 < len(args):
                to_date = args[i + 1]
                i += 2
            elif arg == "--scope" and i + 1 < len(args):
                scope = args[i + 1]
                i += 2
            else:
                query.append(arg)
                i += 1
        
        search_terms = " ".join(query)
        
        if not search_terms:
            return False, "Kein Suchbegriff angegeben"
        
        results = []
        results.append(f"Suche nach: {search_terms}")
        if from_date:
            results.append(f"Von: {from_date}")
        if to_date:
            results.append(f"Bis: {to_date}")
        results.append("-" * 40)
        
        # Suche in Memory-Archiv
        if scope in ["all", "longterm"]:
            mem_results = self._search_in_memory(search_terms, from_date, to_date)
            if mem_results:
                results.append("\n[MEMORY-ARCHIV]")
                for r in mem_results[:10]:
                    results.append(f"  {r['file']}: {r['match'][:60]}")
        
        # Suche im System
        if scope in ["all", "system"]:
            sys_results = self._search_in_system(search_terms)
            if sys_results:
                results.append("\n[SYSTEM-DATEIEN]")
                for r in sys_results[:10]:
                    results.append(f"  {r['file']}: {r['match'][:60]}")
        
        if len(results) <= 4:
            results.append("\nKeine Treffer gefunden.")
        
        return True, "\n".join(results)
    
    def _longterm(self, args: list) -> Tuple[bool, str]:
        """Zeigt Longterm-Memory."""
        # Args parsen
        from_date = None
        to_date = None
        
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--from" and i + 1 < len(args):
                from_date = args[i + 1]
                i += 2
            elif arg == "--to" and i + 1 < len(args):
                to_date = args[i + 1]
                i += 2
            else:
                i += 1
        
        results = []
        results.append("LONGTERM-MEMORY")
        results.append("=" * 40)
        
        if not self.memory_dir.exists():
            return True, "Memory-Verzeichnis nicht gefunden"
        
        # Memory-Dateien finden
        files = sorted(self.memory_dir.glob("*.md"), reverse=True)
        
        # Datum-Filter anwenden
        filtered = []
        for f in files:
            # Datum aus Dateinamen extrahieren (Bericht_20260105_1234.md)
            match = re.search(r"(\d{8})", f.name)
            if match:
                file_date = match.group(1)
                if from_date and file_date < from_date.replace("-", ""):
                    continue
                if to_date and file_date > to_date.replace("-", ""):
                    continue
            filtered.append(f)
        
        # Ausgabe
        for f in filtered[:20]:
            # Erste Zeile als Zusammenfassung
            try:
                with open(f, "r", encoding="utf-8") as file:
                    first_line = file.readline().strip()[:60]
                results.append(f"  {f.name}: {first_line}")
            except (OSError, UnicodeDecodeError):
                results.append(f"  {f.name}")

        if len(filtered) > 20:
            results.append(f"\n  ... und {len(filtered) - 20} weitere")
        
        return True, "\n".join(results)
    
    def _recent(self, count: int) -> Tuple[bool, str]:
        """Zeigt letzte N Memory-Eintraege."""
        memories = self._get_recent_memories(count)
        
        if not memories:
            return True, "Keine Memory-Eintraege gefunden"
        
        results = [f"LETZTE {count} MEMORY-EINTRAEGE", "=" * 40]
        for mem in memories:
            results.append(f"\n[{mem['date']}] {mem['file']}")
            results.append(mem['summary'][:200])
        
        return True, "\n".join(results)
    
    def _get_recent_memories(self, count: int) -> List[dict]:
        """Holt letzte Memory-Eintraege."""
        if not self.memory_dir.exists():
            return []
        
        files = sorted(self.memory_dir.glob("*.md"), reverse=True)[:count]
        
        memories = []
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as file:
                    content = file.read()
                    # Datum aus Dateiname
                    match = re.search(r"(\d{8})", f.name)
                    date = match.group(1) if match else "unknown"
                    # Zusammenfassung: erste nicht-leere Zeile nach Header
                    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]
                    summary = lines[0] if lines else "Keine Zusammenfassung"
                    
                    memories.append({
                        "file": f.name,
                        "date": date,
                        "summary": summary
                    })
            except (OSError, UnicodeDecodeError):
                pass

        return memories
    
    def _get_priority_tasks(self) -> List[dict]:
        """Holt high-prio Tasks."""
        tasks_file = self.base_path / "memory" / "tasks.json"
        
        if not tasks_file.exists():
            return []
        
        try:
            import json
            with open(tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            tasks = data.get("tasks", [])
            # Nur open + high/critical
            filtered = [t for t in tasks 
                       if t.get("status") == "open" 
                       and t.get("priority") in ["high", "critical"]]
            
            return [{"title": t.get("task", ""), "priority": t.get("priority", "")} 
                   for t in filtered]
        except (ValueError, OSError, KeyError):
            return []

    def _get_lessons_summary(self) -> List[str]:
        """Holt Kurzfassung der Lessons Learned."""
        help_file = self.base_path / "help" / "lessons.txt"
        
        if not help_file.exists():
            return []
        
        try:
            with open(help_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Zeilen mit Nummern extrahieren
            lessons = re.findall(r"^\d+\.\s+(.+)$", content, re.MULTILINE)
            return lessons[:5]
        except (OSError, UnicodeDecodeError):
            return []

    def _get_warnings(self) -> List[str]:
        """Prueft auf aktuelle Warnungen."""
        warnings = []
        
        # Memory-Groesse
        memory_file = self.base_path / "DATA" / "memory" / "current.md"
        if memory_file.exists():
            lines = len(memory_file.read_text(encoding="utf-8").splitlines())
            if lines > 80:
                warnings.append(f"Memory hat {lines} Zeilen (>80)")
        
        # Alte Tasks
        tasks_file = self.base_path / "DATA" / "tasks.json"
        if tasks_file.exists():
            try:
                import json
                with open(tasks_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                old_tasks = [t for t in data.get("tasks", []) 
                            if t.get("status") == "open" 
                            and t.get("priority") == "critical"]
                if old_tasks:
                    warnings.append(f"{len(old_tasks)} kritische Tasks offen")
            except (ValueError, OSError, KeyError):
                pass

        return warnings
    
    def _search_in_memory(self, query: str, from_date: str, to_date: str) -> List[dict]:
        """Durchsucht Memory-Archiv."""
        if not self.memory_dir.exists():
            return []
        
        results = []
        terms = query.lower().split()
        
        for f in self.memory_dir.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8").lower()
                if all(term in content for term in terms if not term.startswith("not")):
                    # Matching-Zeile finden
                    for line in content.split("\n"):
                        if any(term in line for term in terms):
                            results.append({"file": f.name, "match": line.strip()})
                            break
            except (OSError, UnicodeDecodeError):
                pass

        return results

    def _search_in_system(self, query: str) -> List[dict]:
        """Durchsucht System-Dateien."""
        results = []
        terms = query.lower().split()
        
        # Help-Dateien durchsuchen
        help_dir = self.base_path / "help"
        if help_dir.exists():
            for f in help_dir.glob("*.txt"):
                try:
                    content = f.read_text(encoding="utf-8").lower()
                    if all(term in content for term in terms):
                        for line in content.split("\n"):
                            if any(term in line for term in terms):
                                results.append({"file": f"docs/help/{f.name}", "match": line.strip()})
                                break
                except (OSError, UnicodeDecodeError):
                    pass

        return results
