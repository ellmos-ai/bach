# SPDX-License-Identifier: MIT
"""
Shared Memory Handler - Multi-Agent Memory-Verwaltung (SQ043 Stufe A-2)
=========================================================================

bach shared-mem facts list              Liste shared memory facts
bach shared-mem facts add <text>        Füge Fact hinzu
bach shared-mem lessons list            Liste shared memory lessons
bach shared-mem lessons add <text>      Füge Lesson hinzu
bach shared-mem working list            Liste shared working memory
bach shared-mem working current-task <text>  Setze/aktualisiere current_task (B54)
bach shared-mem sessions list           Liste shared sessions
bach shared-mem context                 Generiere Kontext-Block (B55)
bach shared-mem changes <timestamp>     Änderungen seit Zeitstempel (B58)

Teil von SQ043: Memory-DB & Partner-Vernetzung (Stufe A-2)
Referenz: BACH_Dev/BACH_Memory_Architektur_Konzept.md

Tabellen (aus Migration 010, Runde 30):
- shared_memory_facts
- shared_memory_lessons
- shared_memory_sessions
- shared_memory_working
- shared_memory_consolidation
- shared_context_triggers

Architektur:
- Multi-Agent-fähig (agent_id, namespace)
- Visibility-Levels (private, team, global)
- Decay-Tracking für automatisches Cleanup
- dist_type für Distribution-System

Status: Basis-Implementation (CRUD für facts, lessons, working)
"""
from pathlib import Path
import sqlite3
import json
from datetime import datetime
from .base import BaseHandler


class SharedMemoryHandler(BaseHandler):
    """Handler für Shared Memory (Multi-Agent Memory)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "shared-mem"

    @property
    def target_file(self) -> Path:
        # Kein dediziertes Tool - direkt im Handler
        return self.base_path / "hub" / "shared_memory.py"

    def get_operations(self) -> dict:
        return {
            "facts": "Shared Memory Facts (Multi-Agent)",
            "lessons": "Shared Memory Lessons (Multi-Agent)",
            "working": "Shared Working Memory (Multi-Agent)",
            "sessions": "Shared Sessions (Multi-Agent)",
            "consolidation": "Shared Consolidation (Multi-Agent)",
            "triggers": "Shared Context Triggers (Multi-Agent)",
            "context": "Generiere Kontext-Block (B55)",
            "changes": "Änderungen seit Zeitstempel (B58)",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        """Haupthandler für Shared Memory Operationen."""
        if operation == "facts":
            return self._facts(args, dry_run)
        elif operation == "lessons":
            return self._lessons(args, dry_run)
        elif operation == "working":
            return self._working(args, dry_run)
        elif operation == "sessions":
            return self._sessions(args, dry_run)
        elif operation == "consolidation":
            return self._consolidation(args, dry_run)
        elif operation == "triggers":
            return self._triggers(args, dry_run)
        elif operation == "context":
            return self._generate_context(args)
        elif operation == "changes":
            return self._get_changes(args)
        else:
            ops = ", ".join(self.get_operations().keys())
            return False, f"Unbekannte Operation: {operation}\n\nVerfügbar: {ops}"

    # === FACTS ===
    def _facts(self, args: list, dry_run: bool) -> tuple:
        """Shared Memory Facts Management."""
        sub_op = args[0] if args else "list"

        if sub_op == "list":
            return self._facts_list(args[1:])
        elif sub_op == "add":
            return self._facts_add(args[1:], dry_run)
        elif sub_op == "get":
            return self._facts_get(args[1:])
        elif sub_op == "delete":
            return self._facts_delete(args[1:], dry_run)
        else:
            return False, f"Unbekannte facts-Operation: {sub_op}\n\nVerfügbar: list, add, get, delete"

    def _facts_list(self, args: list) -> tuple:
        """Liste alle shared memory facts."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, agent_id, namespace, key, value, visibility, created_at
                    FROM shared_memory_facts
                    ORDER BY created_at DESC
                    LIMIT 50
                """)
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Keine shared memory facts gefunden."

            output = f"=== Shared Memory Facts ({len(rows)}) ===\n\n"
            for row in rows:
                fact_id, agent_id, namespace, key, value, visibility, created_at = row
                output += f"[{fact_id}] {key}\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Namespace: {namespace or 'default'} | Visibility: {visibility}\n"
                output += f"  Value: {value[:100]}{'...' if len(value) > 100 else ''}\n"
                output += f"  Created: {created_at}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei facts list: {e}"
        except Exception as e:
            return False, f"Fehler bei facts list: {e}"

    def _facts_add(self, args: list, dry_run: bool) -> tuple:
        """Füge neuen shared memory fact hinzu (B56: Conflict Resolution via confidence)."""
        if not args:
            return False, "Verwendung: bach shared-mem facts add <key> <value> [--agent <id>] [--namespace <ns>] [--visibility <level>] [--confidence <0.0-1.0>]"

        # Parse Arguments
        key = args[0] if args else None
        value = args[1] if len(args) > 1 else None

        if not key or not value:
            return False, "Key und Value sind erforderlich."

        agent_id = None
        namespace = "default"
        visibility = "global"  # default: global
        confidence = 0.5  # B56: default confidence

        # Parse Flags
        i = 2
        while i < len(args):
            if args[i] == "--agent" and i + 1 < len(args):
                agent_id = args[i + 1]
                i += 2
            elif args[i] == "--namespace" and i + 1 < len(args):
                namespace = args[i + 1]
                i += 2
            elif args[i] == "--visibility" and i + 1 < len(args):
                visibility = args[i + 1]
                i += 2
            elif args[i] == "--confidence" and i + 1 < len(args):
                try:
                    confidence = float(args[i + 1])
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    pass
                i += 2
            else:
                i += 1

        if dry_run:
            return True, f"[DRY-RUN] Wuerde Fact hinzufuegen: {key} = {value} (Agent: {agent_id or 'GLOBAL'}, Namespace: {namespace}, Visibility: {visibility}, Confidence: {confidence})"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                now = datetime.now().isoformat()

                # B56: Conflict Resolution -- pruefe ob Key bereits existiert
                cursor = conn.execute("""
                    SELECT id, confidence FROM shared_memory_facts
                    WHERE key = ? AND namespace = ?
                    AND (agent_id = ? OR (agent_id IS NULL AND ? IS NULL))
                    ORDER BY created_at DESC LIMIT 1
                """, (key, namespace, agent_id, agent_id))
                existing = cursor.fetchone()

                if existing:
                    existing_id, existing_confidence = existing
                    existing_confidence = existing_confidence or 0.0

                    if confidence >= existing_confidence:
                        # Update bestehenden Eintrag
                        conn.execute("""
                            UPDATE shared_memory_facts
                            SET value = ?, confidence = ?, visibility = ?, updated_at = ?, modified_by = 'conflict_resolution'
                            WHERE id = ?
                        """, (value, confidence, visibility, now, existing_id))
                        conn.commit()
                        return True, (
                            f"Fact aktualisiert (Conflict Resolution, ID: {existing_id})\n"
                            f"  Key: {key}\n"
                            f"  Neuer Value: {value}\n"
                            f"  Confidence: {existing_confidence} -> {confidence}"
                        )
                    else:
                        return True, (
                            f"Fact NICHT aktualisiert (bestehender Confidence hoeher)\n"
                            f"  Key: {key} (ID: {existing_id})\n"
                            f"  Bestehender Confidence: {existing_confidence} > Neuer: {confidence}"
                        )

                # Kein bestehender Eintrag -- neu anlegen
                cursor = conn.execute("""
                    INSERT INTO shared_memory_facts (agent_id, namespace, key, value, visibility, confidence, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, namespace, key, value, visibility, confidence, now, now))
                conn.commit()
                fact_id = cursor.lastrowid
            finally:
                conn.close()

            return True, f"Shared Memory Fact hinzugefuegt (ID: {fact_id})\n  Key: {key}\n  Agent: {agent_id or 'GLOBAL'}\n  Namespace: {namespace}\n  Visibility: {visibility}\n  Confidence: {confidence}"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei facts add: {e}"

    def _facts_get(self, args: list) -> tuple:
        """Hole einen bestimmten Fact."""
        if not args:
            return False, "Verwendung: bach shared-mem facts get <id>"

        fact_id = args[0]

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, agent_id, namespace, key, value, visibility, created_at
                    FROM shared_memory_facts
                    WHERE id = ?
                """, (fact_id,))
                row = cursor.fetchone()
            finally:
                conn.close()

            if not row:
                return False, f"Fact mit ID {fact_id} nicht gefunden."

            fact_id, agent_id, namespace, key, value, visibility, created_at = row
            output = f"=== Shared Memory Fact {fact_id} ===\n\n"
            output += f"Key: {key}\n"
            output += f"Value: {value}\n"
            output += f"Agent: {agent_id or 'GLOBAL'}\n"
            output += f"Namespace: {namespace}\n"
            output += f"Visibility: {visibility}\n"
            output += f"Created: {created_at}\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei facts get: {e}"

    def _facts_delete(self, args: list, dry_run: bool) -> tuple:
        """Lösche einen Fact."""
        if not args:
            return False, "Verwendung: bach shared-mem facts delete <id>"

        fact_id = args[0]

        if dry_run:
            return True, f"[DRY-RUN] Würde Fact {fact_id} löschen"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("DELETE FROM shared_memory_facts WHERE id = ?", (fact_id,))
                conn.commit()
                deleted = cursor.rowcount
            finally:
                conn.close()

            if deleted == 0:
                return False, f"Fact mit ID {fact_id} nicht gefunden."

            return True, f"✓ Fact {fact_id} gelöscht"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei facts delete: {e}"

    # === LESSONS ===
    def _lessons(self, args: list, dry_run: bool) -> tuple:
        """Shared Memory Lessons Management."""
        sub_op = args[0] if args else "list"

        if sub_op == "list":
            return self._lessons_list(args[1:])
        elif sub_op == "add":
            return self._lessons_add(args[1:], dry_run)
        elif sub_op == "activate":
            return self._lessons_activate(args[1:], dry_run)
        elif sub_op == "deactivate":
            return self._lessons_deactivate(args[1:], dry_run)
        else:
            return False, f"Unbekannte lessons-Operation: {sub_op}\n\nVerfügbar: list, add, activate, deactivate"

    def _lessons_list(self, args: list) -> tuple:
        """Liste alle shared memory lessons."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, agent_id, namespace, title, severity, is_active, times_shown, created_at
                    FROM shared_memory_lessons
                    ORDER BY severity DESC, created_at DESC
                    LIMIT 50
                """)
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Keine shared memory lessons gefunden."

            output = f"=== Shared Memory Lessons ({len(rows)}) ===\n\n"
            for row in rows:
                lesson_id, agent_id, namespace, title, severity, is_active, times_shown, created_at = row
                status = "✓" if is_active else "✗"
                output += f"[{lesson_id}] {status} {severity or 'info'}: {title}\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Namespace: {namespace or 'default'} | Shown: {times_shown}x\n"
                output += f"  Created: {created_at}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei lessons list: {e}"

    def _lessons_add(self, args: list, dry_run: bool) -> tuple:
        """Füge neue lesson hinzu."""
        if not args:
            return False, "Verwendung: bach shared-mem lessons add <title> [--severity <level>] [--agent <id>]"

        title = " ".join([a for a in args if not a.startswith("--")])

        severity = "info"
        agent_id = None
        namespace = "default"

        # Parse Flags
        for i, arg in enumerate(args):
            if arg == "--severity" and i + 1 < len(args):
                severity = args[i + 1]
            elif arg == "--agent" and i + 1 < len(args):
                agent_id = args[i + 1]
            elif arg == "--namespace" and i + 1 < len(args):
                namespace = args[i + 1]

        if dry_run:
            return True, f"[DRY-RUN] Würde Lesson hinzufügen: {title} (Severity: {severity})"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    INSERT INTO shared_memory_lessons
                    (agent_id, namespace, visibility, severity, title, is_active, times_shown, confidence, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, namespace, "global", severity, title, 1, 0, 1.0, "cli",
                      datetime.now().isoformat(), datetime.now().isoformat()))
                conn.commit()
                lesson_id = cursor.lastrowid
            finally:
                conn.close()

            return True, f"✓ Lesson hinzugefügt (ID: {lesson_id}): {title}"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei lessons add: {e}"

    def _lessons_activate(self, args: list, dry_run: bool) -> tuple:
        """Aktiviere eine Lesson."""
        if not args:
            return False, "Verwendung: bach shared-mem lessons activate <id>"

        lesson_id = args[0]

        if dry_run:
            return True, f"[DRY-RUN] Würde Lesson {lesson_id} aktivieren"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("UPDATE shared_memory_lessons SET is_active = 1 WHERE id = ?", (lesson_id,))
                conn.commit()
                updated = cursor.rowcount
            finally:
                conn.close()

            if updated == 0:
                return False, f"Lesson mit ID {lesson_id} nicht gefunden."

            return True, f"✓ Lesson {lesson_id} aktiviert"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei lessons activate: {e}"

    def _lessons_deactivate(self, args: list, dry_run: bool) -> tuple:
        """Deaktiviere eine Lesson."""
        if not args:
            return False, "Verwendung: bach shared-mem lessons deactivate <id>"

        lesson_id = args[0]

        if dry_run:
            return True, f"[DRY-RUN] Würde Lesson {lesson_id} deaktivieren"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("UPDATE shared_memory_lessons SET is_active = 0 WHERE id = ?", (lesson_id,))
                conn.commit()
                updated = cursor.rowcount
            finally:
                conn.close()

            if updated == 0:
                return False, f"Lesson mit ID {lesson_id} nicht gefunden."

            return True, f"✓ Lesson {lesson_id} deaktiviert"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei lessons deactivate: {e}"

    # === WORKING ===
    def _working(self, args: list, dry_run: bool) -> tuple:
        """Shared Working Memory."""
        sub_op = args[0] if args else "list"

        if sub_op == "list":
            return self._working_list(args[1:])
        elif sub_op == "add":
            return self._working_add(args[1:], dry_run)
        elif sub_op == "cleanup":
            return self._working_cleanup(args[1:], dry_run)
        elif sub_op == "current-task":
            return self._working_current_task(args[1:], dry_run)
        else:
            return False, f"Unbekannte working-Operation: {sub_op}\n\nVerfügbar: list, add, cleanup, current-task"

    def _working_list(self, args: list) -> tuple:
        """Liste shared working memory."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, agent_id, session_id, type, content, priority, is_active, created_at
                    FROM shared_memory_working
                    WHERE is_active = 1
                    ORDER BY priority DESC, created_at DESC
                    LIMIT 50
                """)
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Shared Working Memory ist leer."

            output = f"=== Shared Working Memory ({len(rows)}) ===\n\n"
            for row in rows:
                wid, agent_id, session_id, type_, content, priority, is_active, created_at = row
                content_short = content[:80] + "..." if len(content) > 80 else content
                output += f"[{wid}] P{priority} {type_ or 'note'}: {content_short}\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Session: {session_id or '-'}\n"
                output += f"  Created: {created_at}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei working list: {e}"

    def _working_add(self, args: list, dry_run: bool) -> tuple:
        """Füge Working Memory Entry hinzu."""
        if not args:
            return False, "Verwendung: bach shared-mem working add <content> [--type <type>] [--priority <0-9>]"

        content = " ".join([a for a in args if not a.startswith("--")])

        type_ = "note"
        priority = 0
        agent_id = None

        # Parse Flags
        for i, arg in enumerate(args):
            if arg == "--type" and i + 1 < len(args):
                type_ = args[i + 1]
            elif arg == "--priority" and i + 1 < len(args):
                priority = int(args[i + 1])
            elif arg == "--agent" and i + 1 < len(args):
                agent_id = args[i + 1]

        if dry_run:
            return True, f"[DRY-RUN] Würde Working Entry hinzufügen: {content} (P{priority}, {type_})"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    INSERT INTO shared_memory_working
                    (agent_id, session_id, type, content, priority, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, None, type_, content, priority, 1,
                      datetime.now().isoformat(), datetime.now().isoformat()))
                conn.commit()
                entry_id = cursor.lastrowid
            finally:
                conn.close()

            return True, f"✓ Working Entry hinzugefügt (ID: {entry_id})"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei working add: {e}"

    def _working_cleanup(self, args: list, dry_run: bool) -> tuple:
        """Cleanup abgelaufener Working Memory Entries."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                # Zähle abgelaufene Einträge
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM shared_memory_working
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                """, (datetime.now().isoformat(),))
                expired_count = cursor.fetchone()[0]

                if dry_run:
                    return True, f"[DRY-RUN] Würde {expired_count} abgelaufene Entries löschen"

                # Lösche abgelaufene
                conn.execute("""
                    DELETE FROM shared_memory_working
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                """, (datetime.now().isoformat(),))
                conn.commit()
            finally:
                conn.close()

            return True, f"✓ {expired_count} abgelaufene Entries gelöscht"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei working cleanup: {e}"

    def _working_current_task(self, args: list, dry_run: bool) -> tuple:
        """B54: Session-Anker -- setze/aktualisiere current_task (max. 1 pro Agent)."""
        if not args:
            return False, "Verwendung: bach shared-mem working current-task <beschreibung> [--agent <id>]"

        agent_id = None
        text_parts = []

        # Parse Flags
        i = 0
        while i < len(args):
            if args[i] == "--agent" and i + 1 < len(args):
                agent_id = args[i + 1]
                i += 2
            else:
                text_parts.append(args[i])
                i += 1

        content = " ".join(text_parts)
        if not content:
            return False, "Beschreibung ist erforderlich."

        if dry_run:
            return True, f"[DRY-RUN] Wuerde current_task setzen: {content} (Agent: {agent_id or 'GLOBAL'})"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                now = datetime.now().isoformat()

                # Upsert: bestehenden current_task fuer diesen Agent deaktivieren
                conn.execute("""
                    UPDATE shared_memory_working
                    SET is_active = 0, updated_at = ?
                    WHERE type = 'current_task' AND is_active = 1
                    AND (agent_id = ? OR (agent_id IS NULL AND ? IS NULL))
                """, (now, agent_id, agent_id))

                # Neuen current_task anlegen
                cursor = conn.execute("""
                    INSERT INTO shared_memory_working
                    (agent_id, session_id, type, content, priority, is_active, created_at, updated_at)
                    VALUES (?, ?, 'current_task', ?, 9, 1, ?, ?)
                """, (agent_id, None, content, now, now))
                conn.commit()
                entry_id = cursor.lastrowid
            finally:
                conn.close()

            return True, f"Current Task gesetzt (ID: {entry_id})\n  Agent: {agent_id or 'GLOBAL'}\n  Task: {content}"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei working current-task: {e}"

    # === SESSIONS ===
    def _sessions(self, args: list, dry_run: bool) -> tuple:
        """Shared Sessions."""
        sub_op = args[0] if args else "list"

        if sub_op == "list":
            return self._sessions_list(args[1:])
        elif sub_op == "current":
            return self._sessions_current(args[1:])
        elif sub_op == "archive":
            return self._sessions_archive(args[1:], dry_run)
        else:
            return False, f"Unbekannte sessions-Operation: {sub_op}\n\nVerfügbar: list, current, archive"

    def _sessions_list(self, args: list) -> tuple:
        """Liste alle Sessions."""
        try:
            limit = int(args[0]) if args and args[0].isdigit() else 20

            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, session_id, agent_id, started_at, ended_at, tasks_completed, is_archived
                    FROM shared_memory_sessions
                    ORDER BY started_at DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Keine Sessions gefunden."

            output = f"=== Shared Memory Sessions (Top {limit}) ===\n\n"
            for row in rows:
                sid_db, session_id, agent_id, started, ended, tasks, archived = row
                status = "ENDED" if ended else "ACTIVE"
                archive_flag = "📦" if archived else ""
                output += f"[{sid_db}] {status} {archive_flag} {session_id[:16]}...\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Tasks: {tasks or 0}\n"
                output += f"  Started: {started} | Ended: {ended or '-'}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei sessions list: {e}"

    def _sessions_current(self, args: list) -> tuple:
        """Zeige aktuelle (laufende) Sessions."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, session_id, agent_id, started_at, tasks_completed
                    FROM shared_memory_sessions
                    WHERE ended_at IS NULL
                    ORDER BY started_at DESC
                """)
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Keine aktiven Sessions."

            output = f"=== Aktive Sessions ({len(rows)}) ===\n\n"
            for row in rows:
                sid_db, session_id, agent_id, started, tasks = row
                output += f"[{sid_db}] {session_id[:16]}...\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Tasks: {tasks or 0}\n"
                output += f"  Started: {started}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei sessions current: {e}"

    def _sessions_archive(self, args: list, dry_run: bool) -> tuple:
        """Archiviere alte Sessions."""
        if not args or not args[0].isdigit():
            return False, "Verwendung: bach shared-mem sessions archive <days> (Archive Sessions älter als N Tage)"

        days = int(args[0])

        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            conn = sqlite3.connect(self.db_path)
            try:
                # Zähle Sessions
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM shared_memory_sessions
                    WHERE ended_at IS NOT NULL AND ended_at < ? AND is_archived = 0
                """, (cutoff,))
                count = cursor.fetchone()[0]

                if dry_run:
                    return True, f"[DRY-RUN] Würde {count} Sessions archivieren (älter als {days} Tage)"

                # Archiviere
                conn.execute("""
                    UPDATE shared_memory_sessions
                    SET is_archived = 1
                    WHERE ended_at IS NOT NULL AND ended_at < ? AND is_archived = 0
                """, (cutoff,))
                conn.commit()
            finally:
                conn.close()

            return True, f"✓ {count} Sessions archiviert (älter als {days} Tage)"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei sessions archive: {e}"

    # === CONSOLIDATION ===
    def _consolidation(self, args: list, dry_run: bool) -> tuple:
        """Shared Consolidation Management."""
        sub_op = args[0] if args else "list"

        if sub_op == "list":
            return self._consolidation_list(args[1:])
        elif sub_op == "stats":
            return self._consolidation_stats(args[1:])
        elif sub_op == "add":
            return self._consolidation_add(args[1:], dry_run)
        elif sub_op == "consolidate":
            return self._consolidation_consolidate(args[1:], dry_run)
        elif sub_op == "run":
            return self._consolidation_run_decay(args[1:], dry_run)
        else:
            return False, f"Unbekannte consolidation-Operation: {sub_op}\n\nVerfügbar: list, stats, add, consolidate, run"

    def _consolidation_list(self, args: list) -> tuple:
        """Liste Consolidation-Einträge."""
        try:
            limit = int(args[0]) if args and args[0].isdigit() else 50

            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, source_table, source_id, agent_id, times_accessed, weight, status, last_accessed
                    FROM shared_memory_consolidation
                    ORDER BY weight DESC, times_accessed DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Keine Consolidation-Einträge gefunden."

            output = f"=== Shared Memory Consolidation (Top {limit}) ===\n\n"
            for row in rows:
                cid, source_table, source_id, agent_id, times_accessed, weight, status, last_accessed = row
                output += f"[{cid}] {status} {source_table}:{source_id}\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Weight: {weight:.3f} | Accessed: {times_accessed}x\n"
                output += f"  Last: {last_accessed or '-'}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei consolidation list: {e}"

    def _consolidation_stats(self, args: list) -> tuple:
        """Zeige Consolidation-Statistiken."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                # Gesamt-Stats
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN status='active' THEN 1 END) as active,
                        COUNT(CASE WHEN status='consolidated' THEN 1 END) as consolidated,
                        AVG(weight) as avg_weight,
                        AVG(times_accessed) as avg_access
                    FROM shared_memory_consolidation
                """)
                total, active, consolidated, avg_weight, avg_access = cursor.fetchone()

                # Pro Source-Tabelle
                cursor = conn.execute("""
                    SELECT source_table, COUNT(*) as count
                    FROM shared_memory_consolidation
                    GROUP BY source_table
                    ORDER BY count DESC
                """)
                by_source = cursor.fetchall()
            finally:
                conn.close()

            output = "=== Consolidation Statistics ===\n\n"
            output += f"Total Entries: {total}\n"
            output += f"  Active: {active}\n"
            output += f"  Consolidated: {consolidated}\n"
            output += f"Avg Weight: {avg_weight:.3f}\n" if avg_weight else "Avg Weight: -\n"
            output += f"Avg Access: {avg_access:.1f}\n" if avg_access else "Avg Access: -\n"

            if by_source:
                output += "\nBy Source Table:\n"
                for source_table, count in by_source:
                    output += f"  {source_table}: {count}\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei consolidation stats: {e}"

    def _consolidation_add(self, args: list, dry_run: bool) -> tuple:
        """Füge Consolidation-Eintrag manuell hinzu."""
        if len(args) < 2:
            return False, "Verwendung: bach shared-mem consolidation add <source_table> <source_id> [--agent <id>]"

        source_table = args[0]
        source_id = args[1]
        agent_id = None

        # Parse Flags
        for i, arg in enumerate(args):
            if arg == "--agent" and i + 1 < len(args):
                agent_id = args[i + 1]

        if dry_run:
            return True, f"[DRY-RUN] Würde Consolidation-Eintrag hinzufügen: {source_table}:{source_id}"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    INSERT INTO shared_memory_consolidation
                    (source_table, source_id, agent_id, times_accessed, weight, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (source_table, source_id, agent_id, 0, 0.5, 'active',
                      datetime.now().isoformat(), datetime.now().isoformat()))
                conn.commit()
                cid = cursor.lastrowid
            finally:
                conn.close()

            return True, f"✓ Consolidation-Eintrag hinzugefügt (ID: {cid})"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei consolidation add: {e}"

    def _consolidation_consolidate(self, args: list, dry_run: bool) -> tuple:
        """Triggere Konsolidierung (merke duplizierte/ähnliche Einträge)."""
        # Basis-Implementation: Finde Einträge mit weight < threshold und markiere als "consolidated"
        try:
            threshold = float(args[0]) if args and args[0].replace('.','').isdigit() else 0.2

            conn = sqlite3.connect(self.db_path)
            try:
                # Zähle Einträge unter threshold
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM shared_memory_consolidation
                    WHERE status='active' AND weight < ?
                """, (threshold,))
                count = cursor.fetchone()[0]

                if dry_run:
                    return True, f"[DRY-RUN] Würde {count} Einträge konsolidieren (weight < {threshold})"

                # Markiere als consolidated
                conn.execute("""
                    UPDATE shared_memory_consolidation
                    SET status = 'consolidated', updated_at = ?
                    WHERE status='active' AND weight < ?
                """, (datetime.now().isoformat(), threshold))
                conn.commit()
            finally:
                conn.close()

            return True, f"✓ {count} Einträge konsolidiert (weight < {threshold})"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei consolidation consolidate: {e}"

    def _consolidation_run_decay(self, args: list, dry_run: bool) -> tuple:
        """B57: Decay-Logik -- weight *= decay_rate, archiviere unter threshold."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                now = datetime.now().isoformat()

                # Hole alle aktiven Eintraege mit decay_rate und threshold
                cursor = conn.execute("""
                    SELECT id, weight, decay_rate, threshold
                    FROM shared_memory_consolidation
                    WHERE status = 'active'
                """)
                rows = cursor.fetchall()

                if not rows:
                    return True, "Keine aktiven Consolidation-Eintraege zum Decay."

                decayed_count = 0
                archived_count = 0

                for row in rows:
                    cid, weight, decay_rate, threshold = row
                    weight = weight or 1.0
                    decay_rate = decay_rate or 0.95  # Default: 5% Decay
                    threshold = threshold or 0.1     # Default: Archivierung unter 0.1

                    new_weight = weight * decay_rate
                    decayed_count += 1

                    if new_weight < threshold:
                        if not dry_run:
                            conn.execute("""
                                UPDATE shared_memory_consolidation
                                SET weight = ?, status = 'archived', updated_at = ?
                                WHERE id = ?
                            """, (new_weight, now, cid))
                        archived_count += 1
                    else:
                        if not dry_run:
                            conn.execute("""
                                UPDATE shared_memory_consolidation
                                SET weight = ?, updated_at = ?
                                WHERE id = ?
                            """, (new_weight, now, cid))

                if not dry_run:
                    conn.commit()
            finally:
                conn.close()

            prefix = "[DRY-RUN] " if dry_run else ""
            return True, f"{prefix}Decay ausgefuehrt: {decayed_count} Eintraege decayed, {archived_count} archiviert"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei consolidation run: {e}"

    # === CONTEXT (B55) ===
    def _generate_context(self, args: list) -> tuple:
        """B55: Generiere Kontext-Block (Top-10 Facts, aktive Lessons, current_task)."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                output = "## Shared Memory Context\n\n"

                # 1. Current Task(s)
                cursor = conn.execute("""
                    SELECT agent_id, content, created_at
                    FROM shared_memory_working
                    WHERE type = 'current_task' AND is_active = 1
                    ORDER BY created_at DESC
                """)
                tasks = cursor.fetchall()

                if tasks:
                    output += "### Current Tasks\n"
                    for agent_id, content, created_at in tasks:
                        output += f"- **{agent_id or 'GLOBAL'}**: {content} (seit {created_at})\n"
                    output += "\n"
                else:
                    output += "### Current Tasks\n- Kein aktiver Task\n\n"

                # 2. Top-10 Facts (nach confidence absteigend)
                cursor = conn.execute("""
                    SELECT key, value, confidence, agent_id
                    FROM shared_memory_facts
                    ORDER BY confidence DESC, created_at DESC
                    LIMIT 10
                """)
                facts = cursor.fetchall()

                if facts:
                    output += "### Top Facts\n"
                    for key, value, confidence, agent_id in facts:
                        conf_str = f" [{confidence:.1f}]" if confidence else ""
                        value_short = value[:100] + "..." if len(value) > 100 else value
                        output += f"- **{key}**{conf_str}: {value_short}\n"
                    output += "\n"
                else:
                    output += "### Top Facts\n- Keine Facts vorhanden\n\n"

                # 3. Aktive Lessons
                cursor = conn.execute("""
                    SELECT severity, title
                    FROM shared_memory_lessons
                    WHERE is_active = 1
                    ORDER BY severity DESC, created_at DESC
                    LIMIT 10
                """)
                lessons = cursor.fetchall()

                if lessons:
                    output += "### Aktive Lessons\n"
                    for severity, title in lessons:
                        output += f"- [{severity or 'info'}] {title}\n"
                    output += "\n"
                else:
                    output += "### Aktive Lessons\n- Keine aktiven Lessons\n\n"
            finally:
                conn.close()

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei context: {e}"

    # === CHANGES (B58) ===
    def _get_changes(self, args: list) -> tuple:
        """B58: Aenderungen seit einem Zeitstempel."""
        if not args:
            return False, "Verwendung: bach shared-mem changes <ISO-timestamp>\n  Beispiel: bach shared-mem changes 2026-02-28T10:00:00"

        since = args[0]

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                output = f"## Aenderungen seit {since}\n\n"
                total_changes = 0

                # Facts
                cursor = conn.execute("""
                    SELECT id, key, value, created_at, updated_at
                    FROM shared_memory_facts
                    WHERE created_at > ? OR updated_at > ?
                    ORDER BY COALESCE(updated_at, created_at) DESC
                """, (since, since))
                facts = cursor.fetchall()

                if facts:
                    output += f"### Facts ({len(facts)})\n"
                    for fid, key, value, created_at, updated_at in facts:
                        value_short = value[:80] + "..." if len(value) > 80 else value
                        ts = updated_at or created_at
                        output += f"- [{fid}] **{key}**: {value_short} ({ts})\n"
                    output += "\n"
                    total_changes += len(facts)

                # Lessons
                cursor = conn.execute("""
                    SELECT id, title, severity, created_at, updated_at
                    FROM shared_memory_lessons
                    WHERE created_at > ? OR updated_at > ?
                    ORDER BY COALESCE(updated_at, created_at) DESC
                """, (since, since))
                lessons = cursor.fetchall()

                if lessons:
                    output += f"### Lessons ({len(lessons)})\n"
                    for lid, title, severity, created_at, updated_at in lessons:
                        ts = updated_at or created_at
                        output += f"- [{lid}] [{severity or 'info'}] {title} ({ts})\n"
                    output += "\n"
                    total_changes += len(lessons)

                # Working Memory
                cursor = conn.execute("""
                    SELECT id, type, content, created_at, updated_at
                    FROM shared_memory_working
                    WHERE created_at > ? OR updated_at > ?
                    ORDER BY COALESCE(updated_at, created_at) DESC
                """, (since, since))
                working = cursor.fetchall()

                if working:
                    output += f"### Working Memory ({len(working)})\n"
                    for wid, type_, content, created_at, updated_at in working:
                        content_short = content[:80] + "..." if len(content) > 80 else content
                        ts = updated_at or created_at
                        output += f"- [{wid}] {type_ or 'note'}: {content_short} ({ts})\n"
                    output += "\n"
                    total_changes += len(working)
            finally:
                conn.close()

            if total_changes == 0:
                return True, f"Keine Aenderungen seit {since}."

            output += f"---\nGesamt: {total_changes} Aenderungen\n"
            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei changes: {e}"

    # === TRIGGERS ===
    def _triggers(self, args: list, dry_run: bool) -> tuple:
        """Shared Context Triggers Management."""
        sub_op = args[0] if args else "list"

        if sub_op == "list":
            return self._triggers_list(args[1:])
        elif sub_op == "add":
            return self._triggers_add(args[1:], dry_run)
        elif sub_op == "activate":
            return self._triggers_activate(args[1:], dry_run)
        elif sub_op == "deactivate":
            return self._triggers_deactivate(args[1:], dry_run)
        elif sub_op == "delete":
            return self._triggers_delete(args[1:], dry_run)
        else:
            return False, f"Unbekannte triggers-Operation: {sub_op}\n\nVerfügbar: list, add, activate, deactivate, delete"

    def _triggers_list(self, args: list) -> tuple:
        """Liste Context Triggers."""
        try:
            limit = int(args[0]) if args and args[0].isdigit() else 50

            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, agent_id, trigger_phrase, hint_text, is_active, usage_count, status
                    FROM shared_context_triggers
                    WHERE is_active = 1 OR ? = 1
                    ORDER BY usage_count DESC, created_at DESC
                    LIMIT ?
                """, (1 if "--all" in args else 0, limit))
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return True, "Keine Context Triggers gefunden."

            output = f"=== Shared Context Triggers ({len(rows)}) ===\n\n"
            for row in rows:
                tid, agent_id, phrase, hint, is_active, usage_count, status = row
                active_flag = "✓" if is_active else "✗"
                output += f"[{tid}] {active_flag} {phrase[:50]}{'...' if len(phrase) > 50 else ''}\n"
                output += f"  Agent: {agent_id or 'GLOBAL'} | Status: {status or 'approved'} | Used: {usage_count or 0}x\n"
                output += f"  Hint: {hint[:80]}{'...' if len(hint) > 80 else ''}\n\n"

            return True, output

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei triggers list: {e}"

    def _triggers_add(self, args: list, dry_run: bool) -> tuple:
        """Füge Context Trigger hinzu."""
        if len(args) < 2:
            return False, "Verwendung: bach shared-mem triggers add <phrase> <hint> [--agent <id>]"

        # Parse phrase und hint (kann mehrere Wörter sein)
        agent_flag_idx = next((i for i, a in enumerate(args) if a == "--agent"), None)

        if agent_flag_idx:
            phrase = " ".join(args[:agent_flag_idx])
            hint = ""  # Hint kommt nach --agent
        else:
            # Einfacher Fall: phrase ist erstes Wort, Rest ist hint
            phrase = args[0]
            hint = " ".join(args[1:]) if len(args) > 1 else ""

        agent_id = None
        if agent_flag_idx and agent_flag_idx + 1 < len(args):
            agent_id = args[agent_flag_idx + 1]

        if not phrase or not hint:
            return False, "Phrase und Hint sind erforderlich."

        if dry_run:
            return True, f"[DRY-RUN] Würde Trigger hinzufügen: {phrase} → {hint}"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    INSERT INTO shared_context_triggers
                    (agent_id, namespace, trigger_phrase, hint_text, is_active, status, usage_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, "default", phrase, hint, 1, "approved", 0,
                      datetime.now().isoformat(), datetime.now().isoformat()))
                conn.commit()
                tid = cursor.lastrowid
            finally:
                conn.close()

            return True, f"✓ Context Trigger hinzugefügt (ID: {tid})"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei triggers add: {e}"

    def _triggers_activate(self, args: list, dry_run: bool) -> tuple:
        """Aktiviere Trigger."""
        if not args:
            return False, "Verwendung: bach shared-mem triggers activate <id>"

        trigger_id = args[0]

        if dry_run:
            return True, f"[DRY-RUN] Würde Trigger {trigger_id} aktivieren"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    UPDATE shared_context_triggers SET is_active = 1, updated_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), trigger_id))
                conn.commit()
                updated = cursor.rowcount
            finally:
                conn.close()

            if updated == 0:
                return False, f"Trigger {trigger_id} nicht gefunden."

            return True, f"✓ Trigger {trigger_id} aktiviert"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei triggers activate: {e}"

    def _triggers_deactivate(self, args: list, dry_run: bool) -> tuple:
        """Deaktiviere Trigger."""
        if not args:
            return False, "Verwendung: bach shared-mem triggers deactivate <id>"

        trigger_id = args[0]

        if dry_run:
            return True, f"[DRY-RUN] Würde Trigger {trigger_id} deaktivieren"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    UPDATE shared_context_triggers SET is_active = 0, updated_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), trigger_id))
                conn.commit()
                updated = cursor.rowcount
            finally:
                conn.close()

            if updated == 0:
                return False, f"Trigger {trigger_id} nicht gefunden."

            return True, f"✓ Trigger {trigger_id} deaktiviert"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei triggers deactivate: {e}"

    def _triggers_delete(self, args: list, dry_run: bool) -> tuple:
        """Lösche Trigger."""
        if not args:
            return False, "Verwendung: bach shared-mem triggers delete <id>"

        trigger_id = args[0]

        if dry_run:
            return True, f"[DRY-RUN] Würde Trigger {trigger_id} löschen"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("DELETE FROM shared_context_triggers WHERE id = ?", (trigger_id,))
                conn.commit()
                deleted = cursor.rowcount
            finally:
                conn.close()

            if deleted == 0:
                return False, f"Trigger {trigger_id} nicht gefunden."

            return True, f"✓ Trigger {trigger_id} gelöscht"

        except sqlite3.Error as e:
            return False, f"Datenbankfehler bei triggers delete: {e}"
