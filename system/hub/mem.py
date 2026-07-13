# SPDX-License-Identifier: MIT
"""
Mem Handler - Memory-Verwaltung
================================

bach mem working status         Zeige Working Memory Status
bach mem working cleanup        Cleanup abgelaufener Einträge
bach mem working set-expires    Setze Expires für alte Einträge
bach mem working analyze        Analysiere und kategorisiere Einträge

bach mem decay                  Memory-Decay ausführen (Facts/Lessons/Working)
bach mem decay --facts          Nur Facts Decay
bach mem decay --lessons        Nur Lessons Decay
bach mem decay --working        Nur Working Memory Decay
bach mem decay --dry-run        Vorschau ohne DB-Änderungen

Teil von SQ043: Working Memory Cleanup + Memory Decay (Runde 30C)
Referenz: BACH_Dev/docs/MEMORY_WORKING_CLEANUP_KONZEPT.md
"""
from pathlib import Path
from .base import BaseHandler
from .memory import MemoryHandler


class MemHandler(BaseHandler):
    """Handler für Memory-Verwaltung (Working, Facts, Lessons)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "mem"

    @property
    def target_file(self) -> Path:
        return self.base_path / "tools" / "memory_working_cleanup.py"

    def get_operations(self) -> dict:
        return {
            "status": "Memory-Uebersicht (Alias fuer bach memory status)",
            "write": "Notiz schreiben (Alias fuer bach memory write)",
            "read": "Letzte Notizen lesen (Alias fuer bach memory read)",
            "fact": "Fakt speichern (Alias fuer bach memory fact)",
            "facts": "Fakten anzeigen (Alias fuer bach memory facts)",
            "search": "Memory durchsuchen (Alias fuer bach memory search)",
            "context": "Kontext generieren (Alias fuer bach memory context)",
            "session": "Session-Bericht speichern (Alias fuer bach memory session)",
            "sessions": "Letzte Sessions anzeigen (Alias fuer bach memory sessions)",
            "working": "Working Memory Management (SQ043)",
            "decay": "Memory Decay (Facts/Lessons/Working, SQ043 Runde 30C)",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        memory_aliases = {
            "",
            "status",
            "write",
            "read",
            "fact",
            "facts",
            "certain",
            "uncertain",
            "confidence",
            "search",
            "context",
            "clear",
            "session",
            "sessions",
        }

        if operation in memory_aliases:
            return MemoryHandler(self.base_path).handle(operation, args, dry_run)
        elif operation == "working":
            return self._working(args, dry_run)
        elif operation == "decay":
            return self._decay(args, dry_run)
        else:
            return False, (
                f"Unbekannte Operation: {operation}\n\n"
                "Verfuegbar: status, write, read, fact, facts, search, "
                "context, session, sessions, working, decay"
            )

    def _working(self, args: list, dry_run: bool) -> tuple:
        """Working Memory Cleanup (SQ043)."""
        try:
            # Importiere das Tool
            import sys
            tools_dir = str(self.base_path / "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            from memory_working_cleanup import WorkingMemoryCleanup

            db_path = self._canonical_db
            cleanup = WorkingMemoryCleanup(db_path)

            # Sub-Operation extrahieren
            sub_op = args[0] if args else "status"
            sub_args = args[1:] if len(args) > 1 else []

            if sub_op == "status" or sub_op == "analyze":
                # Analyze-Modus
                success, msg = cleanup.analyze(dry_run=True)
                return success, msg

            elif sub_op == "cleanup":
                # Cleanup-Modus (Soft Delete expired Eintraege)
                dry = "--dry-run" in sub_args
                success, msg = cleanup.cleanup_soft(dry_run=dry)
                return success, msg

            elif sub_op == "set-expires":
                # Set-Expires-Modus (Expires retroaktiv setzen)
                dry = "--dry-run" in sub_args
                success, msg = cleanup.set_expires_retroactive(dry_run=dry)
                return success, msg

            else:
                return False, f"Unbekannte working-Operation: {sub_op}\n\nVerfügbar: status, analyze, cleanup, set-expires"

        except Exception as e:
            return False, f"Fehler bei Working Memory Cleanup: {e}"

    def _decay(self, args: list, dry_run: bool) -> tuple:
        """Memory Decay (SQ043 Runde 30C)."""
        try:
            # Importiere das Tool
            import sys
            tools_dir = str(self.base_path / "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            from memory_decay import MemoryDecay

            db_path = self._canonical_db
            decay = MemoryDecay(db_path)

            # Parse Argumente
            dry = "--dry-run" in args or dry_run
            facts_only = "--facts" in args
            lessons_only = "--lessons" in args
            working_only = "--working" in args

            # Führe Decay aus
            report = decay.run_decay(
                facts=facts_only or not (lessons_only or working_only),
                lessons=lessons_only or not (facts_only or working_only),
                working=working_only or not (facts_only or lessons_only),
                dry_run=dry
            )

            return True, report

        except Exception as e:
            return False, f"Fehler bei Memory Decay: {e}"
