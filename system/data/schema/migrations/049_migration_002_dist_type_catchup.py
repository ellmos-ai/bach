# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Nachholen der 3 fehlenden migration_002-Effekte (T-20260926-850075227).

migration_002_user_dist_type.sql sollte 32 Effekte anlegen; auf Laptop UND Mac
fehlen dieselben drei: bach_agents.dist_type, bach_experts.dist_type,
VIEW v_user_backup_tables (Mac obwohl migration_002 dort als gebucht gilt --
vermutlich brach das nicht idempotente Skript vor diesen Anweisungen ab).

Ungenutzt (git grep 2026-09-26: kein Lese-/Schreibpfad ausserhalb der
Migrationsdatei selbst), aber additiv nachgezogen statt aus dem Soll
gestrichen (Team-Lead-Entscheidung: alte Migrationsdatei bleibt unveraendert,
Drift wird per neuer additiver Migration geschlossen). Guarded, damit ein
zweiter Lauf (oder ein Host, der die 3 Effekte schon hat) ein No-op bleibt.
"""

import sqlite3


def run_migration(conn: sqlite3.Connection) -> None:
    for table in ("bach_agents", "bach_experts"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "dist_type" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN dist_type INTEGER DEFAULT 2")

    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS v_user_backup_tables AS
        SELECT 'assistant_contacts' as tbl, COUNT(*) as cnt FROM assistant_contacts WHERE dist_type = 0
        UNION ALL SELECT 'assistant_calendar', COUNT(*) FROM assistant_calendar WHERE dist_type = 0
        UNION ALL SELECT 'fin_insurances', COUNT(*) FROM fin_insurances WHERE dist_type = 0
        UNION ALL SELECT 'fin_contracts', COUNT(*) FROM fin_contracts WHERE dist_type = 0
        UNION ALL SELECT 'health_contacts', COUNT(*) FROM health_contacts WHERE dist_type = 0
        UNION ALL SELECT 'health_diagnoses', COUNT(*) FROM health_diagnoses WHERE dist_type = 0
        UNION ALL SELECT 'health_medications', COUNT(*) FROM health_medications WHERE dist_type = 0
        UNION ALL SELECT 'health_lab_values', COUNT(*) FROM health_lab_values WHERE dist_type = 0
        UNION ALL SELECT 'health_documents', COUNT(*) FROM health_documents WHERE dist_type = 0
        UNION ALL SELECT 'health_appointments', COUNT(*) FROM health_appointments WHERE dist_type = 0
        UNION ALL SELECT 'household_routines', COUNT(*) FROM household_routines WHERE dist_type = 0
        UNION ALL SELECT 'financial_emails', COUNT(*) FROM financial_emails WHERE dist_type = 0
        """
    )


if __name__ == "__main__":
    from hub.bach_paths import BACH_DB

    with sqlite3.connect(str(BACH_DB)) as connection:
        run_migration(connection)
