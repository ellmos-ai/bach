# SPDX-License-Identifier: MIT
"""
BACH-USMC Bridge - Sync zwischen BACH SharedMemory und USMC.
=============================================================

Bidirektionaler Sync von Facts, Lessons und Working Memory
zwischen BACH (bach.db shared_memory_*) und USMC (usmc_memory.db).

Mapping:
    BACH shared_memory_facts     <-> USMC usmc_facts
    BACH shared_memory_lessons   <-> USMC usmc_lessons
    BACH shared_memory_working   <-> USMC usmc_working

Verwendung:
    bridge = USMCBridge()          # DB-Pfade kommen aus der zentralen Registry
    ok, msg = bridge.sync_bidirectional()
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict

log = logging.getLogger(__name__)


# Mapping: BACH namespace -> USMC category
_NS_TO_CAT = {
    "default": "system",
    "user": "user",
    "project": "project",
    "domain": "domain",
    "usmc": "system",
}

# Mapping: USMC category -> BACH namespace
_CAT_TO_NS = {
    "system": "default",
    "user": "user",
    "project": "project",
    "domain": "domain",
}


class USMCBridge:
    """Bidirektionaler Sync zwischen BACH SharedMemory und USMC."""

    def __init__(
        self,
        bach_db_path: Optional[Path] = None,
        usmc_db_path: Optional[Path] = None,
    ):
        # Ohne Angabe kommt der Pfad aus der zentralen Registry — nicht aus dem
        # aktuellen Arbeitsverzeichnis. Ein relatives Default wie "usmc_memory.db"
        # ergibt je nach Startort eine ANDERE Datei; existiert sie dort nicht, legt
        # sqlite3.connect() sie still als leere 0-KB-Datenbank an.
        from hub.bach_paths import BACH_DB

        self.bach_db = Path(bach_db_path) if bach_db_path else BACH_DB
        self.usmc_db = (
            Path(usmc_db_path) if usmc_db_path
            else self.bach_db.parent / "usmc_memory.db"
        )
        self._last_sync_file = self.bach_db.parent / "usmc_last_sync.txt"

    # ── Sync-Timestamp ──────────────────────────────────────

    def _get_last_sync(self) -> str:
        if self._last_sync_file.exists():
            return self._last_sync_file.read_text(encoding="utf-8").strip()
        return "2000-01-01T00:00:00"

    def _set_last_sync(self):
        self._last_sync_file.write_text(
            datetime.now().isoformat(), encoding="utf-8"
        )

    # ── USMC Client ─────────────────────────────────────────

    def _get_usmc_client(self):
        """Importiert und erstellt USMCClient (lazy, damit kein harter Import-Fehler)."""
        from usmc import USMCClient
        return USMCClient(db_path=str(self.usmc_db), agent_id="bach-bridge")

    # ── BACH -> USMC ────────────────────────────────────────

    def sync_to_usmc(self) -> Tuple[bool, str]:
        """BACH shared_memory -> USMC. Synct Facts, Lessons, Working."""
        try:
            client = self._get_usmc_client()
        except ImportError:
            return False, "USMC nicht installiert. pip install usmc"

        last_sync = self._get_last_sync()
        counts = {"facts": 0, "lessons": 0, "working": 0}

        bach_conn = sqlite3.connect(str(self.bach_db))
        try:
            # --- Facts ---
            rows = bach_conn.execute(
                "SELECT key, value, visibility, agent_id, namespace, confidence "
                "FROM shared_memory_facts "
                "WHERE created_at > ? OR updated_at > ?",
                (last_sync, last_sync),
            ).fetchall()

            for key, value, visibility, agent_id, namespace, confidence in rows:
                category = _NS_TO_CAT.get(namespace or "default", "system")
                conf = confidence if confidence is not None else 0.5
                client.add_fact(category, key, value, confidence=conf)
                counts["facts"] += 1

            # --- Lessons ---
            rows = bach_conn.execute(
                "SELECT title, severity, agent_id "
                "FROM shared_memory_lessons "
                "WHERE (created_at > ? OR updated_at > ?) AND is_active = 1",
                (last_sync, last_sync),
            ).fetchall()

            for title, severity, agent_id in rows:
                sev = severity if severity in ("critical", "high", "medium", "low") else "medium"
                client.add_lesson(
                    title=title,
                    problem=title,
                    solution=title,
                    severity=sev,
                    category="general",
                )
                counts["lessons"] += 1

            # --- Working ---
            rows = bach_conn.execute(
                "SELECT type, content, priority "
                "FROM shared_memory_working "
                "WHERE (created_at > ? OR updated_at > ?) AND is_active = 1",
                (last_sync, last_sync),
            ).fetchall()

            for type_, content, priority in rows:
                wtype = type_ if type_ in ("note", "context", "scratchpad", "loop") else "note"
                client.add_working(content, type=wtype, priority=priority or 0)
                counts["working"] += 1

        finally:
            bach_conn.close()

        total = sum(counts.values())
        if total == 0:
            return True, "Keine neuen BACH-Eintraege seit letztem Sync."

        self._set_last_sync()
        return True, (
            f"BACH -> USMC: {total} Eintraege synchronisiert "
            f"(Facts: {counts['facts']}, Lessons: {counts['lessons']}, Working: {counts['working']})"
        )

    # ── USMC -> BACH ────────────────────────────────────────

    def sync_from_usmc(self) -> Tuple[bool, str]:
        """USMC -> BACH shared_memory. Synct Facts, Lessons, Working."""
        try:
            client = self._get_usmc_client()
        except ImportError:
            return False, "USMC nicht installiert."

        last_sync = self._get_last_sync()
        changes = client.get_changes_since(last_sync)
        counts = {"facts": 0, "lessons": 0, "working": 0}

        bach_conn = sqlite3.connect(str(self.bach_db))
        now = datetime.now().isoformat()

        try:
            # --- Facts ---
            for fact in changes.get("facts", []):
                namespace = _CAT_TO_NS.get(fact.get("category", "system"), "default")
                agent_id = fact.get("agent_id", "usmc")
                confidence = fact.get("confidence", 0.5)

                existing = bach_conn.execute(
                    "SELECT id, confidence FROM shared_memory_facts "
                    "WHERE key = ? AND namespace = ? "
                    "AND (agent_id = ? OR (agent_id IS NULL AND ? IS NULL)) "
                    "ORDER BY created_at DESC LIMIT 1",
                    (fact["key"], namespace, agent_id, agent_id),
                ).fetchone()

                if existing:
                    existing_id, existing_conf = existing
                    existing_conf = existing_conf or 0.0
                    if confidence >= existing_conf:
                        bach_conn.execute(
                            "UPDATE shared_memory_facts "
                            "SET value = ?, confidence = ?, updated_at = ?, "
                            "    modified_by = 'usmc-bridge' "
                            "WHERE id = ?",
                            (fact["value"], confidence, now, existing_id),
                        )
                else:
                    bach_conn.execute("""
                        INSERT INTO shared_memory_facts
                            (agent_id, namespace, key, value, visibility, confidence,
                             source, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 'global', ?, 'usmc-bridge', ?, ?)
                    """, (agent_id, namespace, fact["key"], fact["value"],
                          confidence, now, now))
                counts["facts"] += 1

            # --- Lessons ---
            for lesson in changes.get("lessons", []):
                agent_id = lesson.get("agent_id", "usmc")
                severity = lesson.get("severity", "medium")
                title = lesson.get("title", "")

                bach_conn.execute("""
                    INSERT INTO shared_memory_lessons
                        (agent_id, namespace, visibility, severity, title,
                         is_active, times_shown, confidence, source, created_at, updated_at)
                    VALUES (?, 'usmc', 'global', ?, ?, 1, 0, 1.0, 'usmc-bridge', ?, ?)
                """, (agent_id, severity, title, now, now))
                counts["lessons"] += 1

            # --- Working ---
            for note in changes.get("working", []):
                agent_id = note.get("agent_id", "usmc")
                content = note.get("content", "")
                type_ = note.get("type", "note")

                bach_conn.execute("""
                    INSERT INTO shared_memory_working
                        (agent_id, session_id, type, content, priority,
                         is_active, created_at, updated_at)
                    VALUES (?, NULL, ?, ?, 0, 1, ?, ?)
                """, (agent_id, type_, content, now, now))
                counts["working"] += 1

            bach_conn.commit()
        finally:
            bach_conn.close()

        total = sum(counts.values())
        if total == 0:
            return True, "Keine neuen USMC-Eintraege seit letztem Sync."

        self._set_last_sync()
        return True, (
            f"USMC -> BACH: {total} Eintraege synchronisiert "
            f"(Facts: {counts['facts']}, Lessons: {counts['lessons']}, Working: {counts['working']})"
        )

    # ── Bidirektional ───────────────────────────────────────

    def sync_bidirectional(self) -> Tuple[bool, str]:
        """Fuehrt Sync in beide Richtungen durch."""
        ok1, msg1 = self.sync_to_usmc()
        ok2, msg2 = self.sync_from_usmc()
        return ok1 and ok2, f"{msg1}\n{msg2}"

    # ── Status ──────────────────────────────────────────────

    def get_sync_status(self) -> Tuple[bool, str]:
        """Gibt Sync-Status zurueck."""
        last = self._get_last_sync()
        usmc_exists = self.usmc_db.exists()
        bach_exists = self.bach_db.exists()
        return True, (
            f"Letzter Sync: {last}\n"
            f"BACH DB: {self.bach_db} ({'vorhanden' if bach_exists else 'fehlt'})\n"
            f"USMC DB: {self.usmc_db} ({'vorhanden' if usmc_exists else 'fehlt'})"
        )
