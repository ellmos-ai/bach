"""Konsolidiert den Kalendervertrag auf ``assistant_calendar``.

``calendar_events`` war eine zweite, inkompatible Tabelle. Die vom User
freigegebene Konsolidierung basiert auf dem belegten Leerstand dieser
Legacy-Tabelle. Bei vorhandenen Legacy-Daten bricht die Migration deshalb
fail-closed ab; eine stillschweigende, potenziell verlustbehaftete Abbildung
ist ausdrücklich unerwünscht.
"""


COMPATIBILITY_VIEW_SQL = """
CREATE VIEW calendar_events AS
SELECT
    id,
    title,
    description,
    DATE(start_datetime) AS event_date,
    TIME(start_datetime) AS event_time,
    DATE(end_datetime) AS end_date,
    TIME(end_datetime) AS end_time,
    0 AS all_day,
    location,
    is_recurring,
    recurrence_rule AS recurrence_pattern,
    NULL AS recurrence_end,
    reminder_minutes,
    event_type AS category,
    status,
    external_id,
    NULL AS notes,
    dist_type,
    created_at,
    updated_at
FROM assistant_calendar
"""


def run_migration(conn):
    canonical = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'assistant_calendar'"
    ).fetchone()
    if not canonical or canonical[0] != "table":
        raise RuntimeError(
            "Kalender-Migration abgebrochen: assistant_calendar fehlt."
        )

    legacy = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'calendar_events'"
    ).fetchone()
    if legacy and legacy[0] == "table":
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM calendar_events"
        ).fetchone()[0]
        if legacy_count:
            raise RuntimeError(
                "Kalender-Migration abgebrochen: calendar_events enthält "
                f"{legacy_count} Legacy-Einträge. Vor der Konsolidierung "
                "ist eine manuell geprüfte Datenabbildung erforderlich."
            )
        conn.execute("DROP TABLE calendar_events")
    elif legacy and legacy[0] == "view":
        conn.execute("DROP VIEW calendar_events")

    conn.execute(COMPATIBILITY_VIEW_SQL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assistant_calendar_start "
        "ON assistant_calendar(start_datetime)"
    )
