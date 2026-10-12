# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Polarstern (BACH #2121): Tabellen fuer Ressourcen-Leases (additiv, idempotent)."""

import sqlite3

from hub._services.resource_lease import ensure_resource_lease_schema


def run_migration(conn: sqlite3.Connection | None = None) -> None:
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(str(BACH_DB))

    try:
        ensure_resource_lease_schema(conn)
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()
