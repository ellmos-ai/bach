# SPDX-License-Identifier: MIT
"""Memory GUI Bridge (Task #1447, OCEAN S9).

Bridges the GUI /memory endpoints to unified backend adapter methods, providing
structured routing and isolating SQLite database queries from gui/server.py.
Technical Debt Tag: S9-GUI-ROUTING-STUB (Full OCEAN S6/S7 contract rewrite is deferred).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Optional


class MemoryGUIBridge:
    """Bridge providing memory access for GUI endpoints.

    Acts as an intermediary between gui/server.py and the BACH memory subsystems.
    """

    def __init__(self, db_func=None, user_db_func=None):
        self._db_func = db_func
        self._user_db_func = user_db_func

    def _get_db(self):
        if self._db_func:
            return self._db_func()
        from gui.server import get_bach_db
        return get_bach_db()

    def _get_user_db(self):
        if self._user_db_func:
            return self._user_db_func()
        from gui.server import get_user_db
        return get_user_db()

    def get_overview(self) -> dict:
        """Memory-Uebersicht mit allen Kategorien."""
        result = {
            "working": [],
            "facts": [],
            "lessons": [],
            "sessions": [],
            "consolidation": [],
            "stats": {}
        }
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, content, created_at FROM memory_working
                WHERE is_active = 1
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["working"] = [dict(r) for r in rows]

            rows = conn.execute("""
                SELECT id, category, key, value, value_type, confidence, source, created_at
                FROM memory_facts
                ORDER BY created_at DESC LIMIT 30
            """).fetchall()
            result["facts"] = [dict(r) for r in rows]

            rows = conn.execute("""
                SELECT id, category, title, solution as content, created_at
                FROM memory_lessons
                WHERE is_active = 1
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["lessons"] = [dict(r) for r in rows]

            rows = conn.execute("""
                SELECT id, session_id, started_at, ended_at, summary
                FROM memory_sessions
                ORDER BY id DESC LIMIT 10
            """).fetchall()
            result["sessions"] = [dict(r) for r in rows]

            rows = conn.execute("""
                SELECT id, source_table, source_id, weight, status, created_at
                FROM memory_consolidation
                ORDER BY created_at DESC LIMIT 20
            """).fetchall()
            result["consolidation"] = [dict(r) for r in rows]

            # Best Practices
            rows = conn.execute("""
                SELECT id, category, title, solution as content, created_at
                FROM memory_lessons
                WHERE category IN ('practice', 'best_practice', 'best-practice', 'architecture', 'gotcha', 'integration')
                ORDER BY created_at DESC LIMIT 30
            """).fetchall()
            result["best_practices"] = [dict(r) for r in rows]

            # Workflows (Procedural Memory: Lessons, Skills & Experts)
            workflows = []
            try:
                lesson_wf = conn.execute("""
                    SELECT title, category, solution as content FROM memory_lessons
                    WHERE category IN ('workflow', 'routine') OR title LIKE '%workflow%'
                    ORDER BY created_at DESC LIMIT 20
                """).fetchall()
                for row in lesson_wf:
                    workflows.append({
                        "name": row["title"],
                        "filename": f"Lesson ({row['category']})",
                        "content": row["content"] or ""
                    })
            except Exception:
                pass

            try:
                skill_wf = conn.execute("""
                    SELECT name, category, description FROM skills
                    WHERE category IN ('dev', 'infrastructure', 'workflow', 'utilities') OR name LIKE '%workflow%' OR name LIKE '%pipeline%'
                    ORDER BY name ASC LIMIT 25
                """).fetchall()
                for row in skill_wf:
                    workflows.append({
                        "name": row["name"],
                        "filename": f"Skill: {row['category'] or 'general'}",
                        "content": row["description"] or ""
                    })
            except Exception:
                pass

            try:
                expert_rows = conn.execute("""
                    SELECT display_name, domain, description FROM bach_experts
                    WHERE is_active = 1
                    ORDER BY display_name ASC LIMIT 15
                """).fetchall()
                for row in expert_rows:
                    workflows.append({
                        "name": f"Expert: {row['display_name']}",
                        "filename": f"Domain: {row['domain'] or 'general'}",
                        "content": row["description"] or ""
                    })
            except Exception:
                pass

            result["workflows"] = workflows
            result["stats"]["workflows_count"] = len(workflows)
            result["stats"]["lessons_count"] = len(result["lessons"])
            result["stats"]["facts_count"] = len(result["facts"])
            result["stats"]["working_count"] = len(result["working"])

        return result

    def get_working(self, limit: int = 50) -> dict:
        """Working Memory Eintraege."""
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, content, created_at FROM memory_working
                WHERE is_active = 1
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            entries = [dict(r) for r in rows]
            return {"entries": entries, "count": len(entries)}

    def add_working(self, content: str, entry_type: str = "note") -> dict:
        """Neuen Working Memory Eintrag erstellen."""
        with self._get_db() as conn:
            conn.execute("""
                INSERT INTO memory_working (type, content, created_at, is_active)
                VALUES (?, ?, ?, 1)
            """, (entry_type, content, datetime.now().isoformat()))
            conn.commit()
            return {"status": "created", "message": "Memory-Eintrag erstellt"}

    def delete_working(self, entry_id: int) -> dict:
        """Working Memory Eintrag deaktivieren."""
        with self._get_db() as conn:
            conn.execute("UPDATE memory_working SET is_active = 0 WHERE id = ?", (entry_id,))
            conn.commit()
            return {"status": "deleted"}

    def get_lessons(self, limit: int = 50, category: Optional[str] = None) -> dict:
        """Lessons Learned."""
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute("""
                    SELECT id, category, title, solution as content, created_at
                    FROM memory_lessons
                    WHERE category = ? AND is_active = 1
                    ORDER BY created_at DESC LIMIT ?
                """, (category, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, category, title, solution as content, created_at
                    FROM memory_lessons
                    WHERE is_active = 1
                    ORDER BY created_at DESC LIMIT ?
                """, (limit,)).fetchall()
            entries = [dict(r) for r in rows]
            return {"entries": entries, "count": len(entries)}

    def add_lesson(self, content: str, category: Optional[str] = None) -> dict:
        """Neue Lesson erstellen."""
        with self._get_db() as conn:
            conn.execute("""
                INSERT INTO memory_lessons (category, title, solution, created_at, is_active)
                VALUES (?, 'Lesson', ?, ?, 1)
            """, (category or 'general', content, datetime.now().isoformat()))
            conn.commit()
            return {"status": "created", "message": "Lesson erstellt"}

    def delete_lesson(self, lesson_id: int) -> dict:
        """Lesson deaktivieren."""
        with self._get_db() as conn:
            conn.execute("UPDATE memory_lessons SET is_active = 0 WHERE id = ?", (lesson_id,))
            conn.commit()
            return {"status": "deleted"}

    def get_facts(self, limit: int = 50) -> dict:
        """Memory Facts abrufen."""
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, category, key, value, value_type, confidence, source, created_at
                FROM memory_facts
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return {"facts": [dict(r) for r in rows]}

    def add_fact(self, key: str, value: str, category: str = "") -> dict:
        """Memory Fact erstellen."""
        key = (key or "").strip()
        value = (value or "").strip()
        if not key or not value:
            return {"status": "error", "message": "Key und Value sind erforderlich"}
        with self._get_db() as conn:
            conn.execute("""
                INSERT INTO memory_facts (category, key, value, value_type, confidence, source, created_at)
                VALUES (?, ?, ?, 'text', 1.0, 'gui', ?)
            """, (category, key, value, datetime.now().isoformat()))
            conn.commit()
            return {"status": "created", "message": "Fact erstellt"}

    def delete_fact(self, fact_id: int) -> dict:
        """Memory Fact loeschen."""
        with self._get_db() as conn:
            conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
            conn.commit()
            return {"status": "deleted"}

    def get_sessions(self, limit: int = 20) -> dict:
        """Session-History."""
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, session_id, started_at, ended_at, summary
                FROM memory_sessions
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            sessions = [dict(r) for r in rows]
            return {"sessions": sessions, "count": len(sessions)}

    def get_session_by_id(self, session_id: str) -> Optional[dict]:
        """Session-Details abrufen (via ID oder session_id)."""
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            if session_id.isdigit():
                row = conn.execute("SELECT * FROM memory_sessions WHERE id = ?", (session_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM memory_sessions WHERE session_id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def add_session(self, content: str, session_id: str) -> dict:
        """Speichert Session-Memory Eintrag in user.db."""
        conn = self._get_user_db()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                "INSERT INTO session_memories (session_id, content) VALUES (?, ?)",
                (session_id, content)
            )
            conn.commit()
            return {"status": "ok", "message": "Session-Memory gespeichert"}
        finally:
            conn.close()

    def get_stats_db(self) -> dict:
        """Detaillierte DB-Statistiken fuer Memory-Tabellen."""
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [row['name'] for row in cursor.fetchall()]
            stats = []
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [c['name'] for c in cursor.fetchall()]
                last_update = None
                if 'updated_at' in columns:
                    cursor.execute(f"SELECT MAX(updated_at) FROM {table}")
                    last_update = cursor.fetchone()[0]
                elif 'created_at' in columns:
                    cursor.execute(f"SELECT MAX(created_at) FROM {table}")
                    last_update = cursor.fetchone()[0]
                stats.append({
                    "table": table,
                    "rows": count,
                    "last_update": last_update
                })
            return {"success": True, "tables": stats, "count": len(stats)}

    def maintenance_cleanup(self) -> dict:
        """System-Cleanup fuer Memory."""
        with self._get_db() as conn:
            results = {}
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM memory_consolidation 
                WHERE (source_table = 'memory_working' AND source_id NOT IN (SELECT id FROM memory_working))
                   OR (source_table = 'memory_lessons' AND source_id NOT IN (SELECT id FROM memory_lessons))
            """)
            results["orphaned_consolidations_deleted"] = cursor.rowcount

            # 2. Deaktivierte Working Memories aelter als 30 Tage bereinigen
            cursor.execute("""
                DELETE FROM memory_working 
                WHERE is_active = 0 
                  AND created_at < datetime('now', '-30 days')
            """)
            results["old_inactive_working_deleted"] = cursor.rowcount

            conn.commit()
            return {"success": True, "details": results}


_bridge_instance: Optional[MemoryGUIBridge] = None


def get_memory_bridge() -> MemoryGUIBridge:
    """Singleton getter for MemoryGUIBridge."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = MemoryGUIBridge()
    return _bridge_instance
