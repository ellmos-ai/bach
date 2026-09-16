# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""OPS-TELEM-001: Tabelle telemetry_counters (low-cardinality, privacy-first).

Speichert ausschliesslich aggregierte Zaehler (counter, validierte Labels,
UTC-Tag, Summe). Keine Payloads, Prompts, Pfade oder Nutzerdaten.
"""

import sqlite3

from core.telemetry import ensure_schema


def run_migration(conn: sqlite3.Connection | None = None) -> None:
    """Apply the additive telemetry schema, optionally using the canonical DB."""
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(str(BACH_DB))

    try:
        ensure_schema(conn=conn)
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()