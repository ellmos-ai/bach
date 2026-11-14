# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Standalone Memory Module
Autarker Speicher für Notizen, Facts, Sessions und Working Memory.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


class MemoryStore:
    """Autarke Memory-Engine mit SQLite-Persistenz oder In-Memory-Modus."""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self.db_path = str(db_path) if db_path else ":memory:"
        self._persistent_conn = sqlite3.connect(self.db_path)
        self._persistent_conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            return self._persistent_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    namespace TEXT NOT NULL DEFAULT 'general',
                    category TEXT NOT NULL DEFAULT 'note',
                    tags TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                );
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    tags TEXT DEFAULT '[]',
                    namespace TEXT NOT NULL DEFAULT 'facts',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    report TEXT NOT NULL,
                    duration_sec REAL DEFAULT 0,
                    partner TEXT DEFAULT 'bach',
                    created_at TEXT NOT NULL
                );
            """)

    def write_note(
        self,
        content: str,
        namespace: str = "general",
        tags: Optional[list[str]] = None,
        category: str = "note",
        confidence: float = 1.0,
        ttl_seconds: Optional[int] = None,
    ) -> int:
        """Schreibt eine Notiz/Working Memory Eintrag."""
        now = datetime.now()
        created_at = now.isoformat()
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat() if ttl_seconds else None
        tags_json = json.dumps(tags or [])

        conn = self._get_conn()
        cur = conn.execute(
            """
            INSERT INTO notes (content, namespace, category, tags, confidence, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (content, namespace, category, tags_json, confidence, created_at, expires_at),
        )
        conn.commit()
        return cur.lastrowid

    def read_notes(
        self,
        namespace: Optional[str] = "general",
        limit: int = 20,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Liest aktuelle Notizen."""
        query = "SELECT * FROM notes WHERE 1=1"
        params: list[Any] = []
        if namespace:
            query += " AND namespace = ?"
            params.append(namespace)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        conn = self._get_conn()
        rows = conn.execute(query, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            out.append(d)
        return out

    def store_fact(
        self,
        key: str,
        value: str,
        confidence: float = 1.0,
        tags: Optional[list[str]] = None,
        namespace: str = "facts",
    ) -> bool:
        """Speichert oder aktualisiert einen Fakt."""
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags or [])
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO facts (key, value, confidence, tags, namespace, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                tags = excluded.tags,
                namespace = excluded.namespace,
                updated_at = excluded.updated_at
            """,
            (key, value, confidence, tags_json, namespace, now, now),
        )
        conn.commit()
        return True

    def get_fact(self, key: str) -> Optional[dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        return d

    def list_facts(self, namespace: Optional[str] = None, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        query = "SELECT * FROM facts WHERE confidence >= ?"
        params: list[Any] = [min_confidence]
        if namespace:
            query += " AND namespace = ?"
            params.append(namespace)
        query += " ORDER BY key ASC"

        conn = self._get_conn()
        rows = conn.execute(query, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            out.append(d)
        return out

    def store_session(
        self,
        session_id: str,
        report: str,
        duration_sec: float = 0.0,
        partner: str = "bach",
    ) -> bool:
        """Speichert einen Session-Bericht."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions (session_id, report, duration_sec, partner, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, report, duration_sec, partner, now),
        )
        conn.commit()
        return True

    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, namespace: Optional[str] = None) -> list[dict[str, Any]]:
        """Sucht über Notes und Facts nach Stichwörtern."""
        term = f"%{query}%"
        results: list[dict[str, Any]] = []
        conn = self._get_conn()
        # Notes
        n_query = "SELECT 'note' as type, id, content as text, namespace, created_at FROM notes WHERE content LIKE ?"
        n_params: list[Any] = [term]
        if namespace:
            n_query += " AND namespace = ?"
            n_params.append(namespace)
        for r in conn.execute(n_query, n_params).fetchall():
            results.append(dict(r))

        # Facts
        f_query = "SELECT 'fact' as type, key as id, (key || ': ' || value) as text, namespace, created_at FROM facts WHERE key LIKE ? OR value LIKE ?"
        f_params: list[Any] = [term, term]
        if namespace:
            f_query += " AND namespace = ?"
            f_params.append(namespace)
        for r in conn.execute(f_query, f_params).fetchall():
            results.append(dict(r))

        return results

    def cleanup_expired(self) -> int:
        """Entfernt abgelaufene Working Memory Notizen (Decay)."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM notes WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
        conn.commit()
        return cur.rowcount

    def status(self) -> dict[str, Any]:
        conn = self._get_conn()
        notes_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        facts_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        sessions_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        return {
            "schema": "bach.memory-status.v1",
            "notes_count": notes_count,
            "facts_count": facts_count,
            "sessions_count": sessions_count,
            "db_mode": "memory" if self.db_path == ":memory:" else "file",
        }

    def export_data(self) -> dict[str, Any]:
        return {
            "schema": "bach.memory-export.v1",
            "notes": self.read_notes(namespace=None, limit=1000),
            "facts": self.list_facts(),
            "sessions": self.list_sessions(limit=100),
        }

    def import_data(self, data: dict[str, Any]) -> int:
        count = 0
        for n in data.get("notes", []):
            self.write_note(
                content=n["content"],
                namespace=n.get("namespace", "general"),
                tags=n.get("tags", []),
                category=n.get("category", "note"),
                confidence=n.get("confidence", 1.0),
            )
            count += 1
        for f in data.get("facts", []):
            self.store_fact(
                key=f["key"],
                value=f["value"],
                confidence=f.get("confidence", 1.0),
                tags=f.get("tags", []),
                namespace=f.get("namespace", "facts"),
            )
            count += 1
        for s in data.get("sessions", []):
            self.store_session(
                session_id=s["session_id"],
                report=s["report"],
                duration_sec=s.get("duration_sec", 0.0),
                partner=s.get("partner", "bach"),
            )
            count += 1
        return count


_global_memory = MemoryStore()


def get_memory_store(db_path: Optional[str | Path] = None) -> MemoryStore:
    if db_path:
        return MemoryStore(db_path)
    return _global_memory


memory = _global_memory
