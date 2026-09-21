# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Add lossless source records for reversible Working Memory archival."""

import sqlite3


def run_migration(conn: sqlite3.Connection) -> None:
    """Create the archive surface and add source_record to existing databases."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_memory (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER,
            memory_type TEXT NOT NULL,
            category TEXT,
            key TEXT,
            content TEXT,
            created_at TIMESTAMP,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archive_reason TEXT,
            source_record TEXT
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(archived_memory)")}
    if "source_record" not in columns:
        conn.execute("ALTER TABLE archived_memory ADD COLUMN source_record TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_archived_memory_type "
        "ON archived_memory(memory_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_archived_memory_date "
        "ON archived_memory(archived_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS restore_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_table TEXT NOT NULL,
            archive_id INTEGER NOT NULL,
            restored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            restored_by TEXT DEFAULT 'user',
            target_db TEXT,
            target_id INTEGER,
            success INTEGER DEFAULT 1,
            notes TEXT
        )
        """
    )


if __name__ == "__main__":
    from hub.bach_paths import BACH_DB

    with sqlite3.connect(str(BACH_DB)) as connection:
        run_migration(connection)
