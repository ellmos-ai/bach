"""Distribution-System Vereinheitlichung: Tier-System entfernen,
dist_type als einziges System (urspruenglich migrate_unify_distribution.sql,
2026-02-18).

**T-20260926-357988320:** Die urspruengliche SQL-Fassung droppte
``instance_identity`` und legte sie leer neu an ("Daten werden spaeter neu
erstellt via init_identity()") -- ein Kopie-Lauf mit
``tools/migration_baseline_check.py`` (T-20260926-598278998, bach#93) zeigte
dabei ``rows instance_identity: 1 -> 0``: die Migration LOESCHT auf jedem
Host mit Bestandsdaten die Siegel-/Instanzidentitaet, die live von
``hub/seal.py`` gelesen/geschrieben wird (``kernel_hash``, ``seal_status``).
Konvertiert nach Python (wie ``037_calendar_contract.py``), weil eine reine
``.sql``-Datei kein bedingtes Abbrechen ausdruecken kann (``RAISE()`` ist nur
innerhalb eines Triggers gueltig, empirisch verifiziert) -- das schliesst
genau die stille Fehlkonfiguration, die T-20260926-127399982 im Gardener-
Schwestermodul unabhaengig fuer ``scan_sqlite_table`` fand.

Fail-closed wie 037: Legacy-Tabellen werden nur gedroppt, wenn sie
NACHWEISLICH leer sind; bei Bestandsdaten bricht die Migration mit einer
Fehlermeldung ab, statt sie zu loeschen oder still zu ignorieren.
``instance_identity`` wird NIE gedroppt -- ihre Zeile(n) werden in die neue
(``current_mode``-freie) Spaltenform uebernommen, mit Zeilenzahlpruefung vor
dem Umschalten.

Idempotent: ein zweiter Lauf (Migration bereits vollstaendig angewandt) ist
ein No-Op -- jeder Schritt prueft zuerst den Ist-Zustand, bevor er etwas
aendert.

Vorvalidierung und Mutation laufen in einem SAVEPOINT. SQLite-DDL ist darin
transaktional; ohne explizite Transaktion beginnt Python jedoch erst bei DML
eine Transaktion. ``executescript()`` kann eine bestehende Transaktion zudem
implizit committen. Deshalb werden alle DDL-Anweisungen einzeln ausgefuehrt,
und ein Fehler rollt den gesamten Umbau zurueck. Eine bestehende Transaktion
des Aufrufers bleibt erhalten und wird hier niemals committet.
"""

# Zielschema (current_mode entfaellt -- tot, kein Aufrufer im Repo liest ihn;
# distribution.py._save_identity_to_db() schreibt bereits genau diese
# 13 Spalten in dieser Reihenfolge, das ist der lebende Vertrag).
NEW_INSTANCE_IDENTITY_COLUMNS = [
    "instance_id", "instance_name", "created", "forked_from",
    "seal_status", "seal_broken_at", "seal_broken_by", "seal_broken_reason",
    "kernel_hash", "kernel_version", "seal_last_verified",
    "base_release", "base_release_date",
]

NEW_INSTANCE_IDENTITY_DDL = """
CREATE TABLE instance_identity (
    instance_id TEXT PRIMARY KEY,
    instance_name TEXT NOT NULL,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    forked_from TEXT,
    seal_status TEXT DEFAULT 'intact',
    seal_broken_at TIMESTAMP,
    seal_broken_by TEXT,
    seal_broken_reason TEXT,
    kernel_hash TEXT,
    kernel_version TEXT,
    seal_last_verified TIMESTAMP,
    base_release TEXT,
    base_release_date TIMESTAMP
)
"""

LEGACY_VIEWS = ["v_files_with_tiers", "v_latest_versions"]

# Reihenfolge wie im Original: abhaengige Tabellen zuerst (FK-Constraints).
LEGACY_TABLES = [
    "snapshot_files", "snapshots", "release_manifest", "releases",
    "file_versions", "mode_transitions", "known_instances",
    "tier_patterns", "filesystem_entries", "tiers",
]

NEW_DISTRIBUTION_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS distribution_snapshots (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    snapshot_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    snapshot_type TEXT DEFAULT 'manual',
    file_count INTEGER DEFAULT 0,
    total_size INTEGER DEFAULT 0,
    is_valid INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS distribution_snapshot_files (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES distribution_snapshots(id) ON DELETE CASCADE,
    manifest_id INTEGER NOT NULL REFERENCES distribution_manifest(id),
    file_checksum TEXT,
    file_size INTEGER
);

CREATE TABLE IF NOT EXISTS distribution_releases (
    id INTEGER PRIMARY KEY,
    version TEXT UNIQUE NOT NULL,
    release_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    changelog TEXT,
    kernel_hash TEXT,
    snapshot_id INTEGER REFERENCES distribution_snapshots(id),
    status TEXT DEFAULT 'draft',
    is_stable INTEGER DEFAULT 0,
    dist_zip_path TEXT
);

CREATE TABLE IF NOT EXISTS distribution_file_versions (
    id INTEGER PRIMARY KEY,
    manifest_id INTEGER NOT NULL REFERENCES distribution_manifest(id),
    checksum TEXT,
    size INTEGER,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'system',
    change_type TEXT,
    change_description TEXT
);
"""

DISTRIBUTION_STATS_VIEW_SQL = """
CREATE VIEW v_distribution_stats AS
SELECT
    'skills' as table_name,
    COUNT(*) as total,
    SUM(CASE WHEN dist_type = 2 THEN 1 ELSE 0 END) as core,
    SUM(CASE WHEN dist_type = 1 THEN 1 ELSE 0 END) as template,
    SUM(CASE WHEN dist_type = 0 THEN 1 ELSE 0 END) as user_data
FROM skills
UNION ALL
SELECT
    'tools' as table_name,
    COUNT(*) as total,
    SUM(CASE WHEN dist_type = 2 THEN 1 ELSE 0 END) as core,
    SUM(CASE WHEN dist_type = 1 THEN 1 ELSE 0 END) as template,
    SUM(CASE WHEN dist_type = 0 THEN 1 ELSE 0 END) as user_data
FROM tools
UNION ALL
SELECT
    'tasks' as table_name,
    COUNT(*) as total,
    SUM(CASE WHEN dist_type = 2 THEN 1 ELSE 0 END) as core,
    SUM(CASE WHEN dist_type = 1 THEN 1 ELSE 0 END) as template,
    SUM(CASE WHEN dist_type = 0 THEN 1 ELSE 0 END) as user_data
FROM tasks
UNION ALL
SELECT
    'manifest' as table_name,
    COUNT(*) as total,
    SUM(CASE WHEN dist_type = 2 THEN 1 ELSE 0 END) as core,
    SUM(CASE WHEN dist_type = 1 THEN 1 ELSE 0 END) as template,
    SUM(CASE WHEN dist_type = 0 THEN 1 ELSE 0 END) as user_data
FROM distribution_manifest
"""


def _object_type(conn, name):
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?", (name,)
    ).fetchone()
    return row[0] if row else None


def _table_columns(conn, name):
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')]


def _validate_before_any_mutation(conn):
    """Prueft bekannte Konflikte vor der ersten DDL-Anweisung."""
    kind = _object_type(conn, "instance_identity")
    if kind is not None and kind != "table":
        raise RuntimeError(
            "migrate_unify_distribution abgebrochen: instance_identity "
            f"existiert als {kind!r}, nicht als Tabelle -- Abbruch statt "
            "Ueberschreiben."
        )

    if kind == "table":
        columns = set(_table_columns(conn, "instance_identity"))
        missing = {"instance_id", "instance_name"} - columns
        unexpected = columns - set(NEW_INSTANCE_IDENTITY_COLUMNS) - {"current_mode"}
        if missing or unexpected:
            raise RuntimeError(
                "migrate_unify_distribution abgebrochen: instance_identity "
                f"hat fehlende Pflichtspalten {sorted(missing)} oder unbekannte "
                f"Spalten {sorted(unexpected)}. Manuelle Schema-Pruefung erforderlich."
            )

    if _object_type(conn, "instance_identity_pre_unify") is not None:
        raise RuntimeError(
            "migrate_unify_distribution abgebrochen: instance_identity_pre_unify "
            "existiert bereits. Vorhandenen Bestand zuerst manuell pruefen."
        )

    for name, expected in [
        *((name, "view") for name in LEGACY_VIEWS),
        ("v_distribution_stats", "view"),
        ("distribution_snapshots", "table"),
        ("distribution_snapshot_files", "table"),
        ("distribution_releases", "table"),
        ("distribution_file_versions", "table"),
    ]:
        kind = _object_type(conn, name)
        if kind is not None and kind != expected:
            raise RuntimeError(
                f"migrate_unify_distribution abgebrochen: {name!r} existiert "
                f"als {kind!r}, erwartet {expected!r} oder gar nichts."
            )

    for table in LEGACY_TABLES:
        kind = _object_type(conn, table)
        if kind is None:
            continue  # bereits weg -- kein Problem
        if kind != "table":
            raise RuntimeError(
                f"migrate_unify_distribution abgebrochen: {table!r} existiert "
                f"als {kind!r}, erwartet Tabelle oder gar nichts."
            )
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if count:
            raise RuntimeError(
                "migrate_unify_distribution abgebrochen: Legacy-Tabelle "
                f"{table!r} enthaelt noch {count} Zeile(n). Manuelle Pruefung/"
                "Migration erforderlich, bevor sie geloescht werden darf. "
                "Nichts wurde veraendert."
            )


def _migrate_instance_identity(conn):
    """Uebernimmt instance_identity in die neue Spaltenform, OHNE die Zeile(n)
    zu verlieren. Nie DROP+CREATE-leer (das war der Bug)."""
    kind = _object_type(conn, "instance_identity")
    if kind is None:
        # Kein Bestand -- frisch anlegen (nichts zu migrieren).
        conn.execute(NEW_INSTANCE_IDENTITY_DDL)
        return
    if kind != "table":
        raise RuntimeError(
            "migrate_unify_distribution abgebrochen: instance_identity "
            f"existiert als {kind!r}, nicht als Tabelle -- Abbruch statt "
            "Ueberschreiben."
        )

    current_columns = _table_columns(conn, "instance_identity")
    if current_columns == NEW_INSTANCE_IDENTITY_COLUMNS:
        return  # Bereits migriert -- idempotenter No-Op.

    before_count = conn.execute(
        "SELECT COUNT(*) FROM instance_identity"
    ).fetchone()[0]

    conn.execute("ALTER TABLE instance_identity RENAME TO instance_identity_pre_unify")
    conn.execute(NEW_INSTANCE_IDENTITY_DDL)

    # Nur Spalten uebernehmen, die es in der alten Form auch gab (current_mode
    # existierte dort und entfaellt bewusst -- alles andere in der Zielform
    # ist bereits in der alten Form vorhanden, siehe schema.sql).
    copyable = [c for c in NEW_INSTANCE_IDENTITY_COLUMNS if c in current_columns]
    cols_sql = ", ".join(f'"{c}"' for c in copyable)
    conn.execute(
        f"INSERT INTO instance_identity ({cols_sql}) "
        f"SELECT {cols_sql} FROM instance_identity_pre_unify"
    )

    after_count = conn.execute(
        "SELECT COUNT(*) FROM instance_identity"
    ).fetchone()[0]
    if after_count != before_count:
        raise RuntimeError(
            "migrate_unify_distribution abgebrochen: instance_identity-"
            f"Zeilenzahl aenderte sich waehrend der Migration ({before_count} -> {after_count}) -- "
            "Siegel-/Instanzidentitaet waere sonst verloren gegangen."
        )
    conn.execute("DROP TABLE instance_identity_pre_unify")


def run_migration(conn):
    conn.execute("SAVEPOINT unify_distribution")
    try:
        _validate_before_any_mutation(conn)
        _migrate_instance_identity(conn)

        for view in LEGACY_VIEWS:
            conn.execute(f'DROP VIEW IF EXISTS "{view}"')

        for table in LEGACY_TABLES:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')

        # This fixed DDL contains no semicolons inside literals or comments.
        # executescript would commit the savepoint before running the script.
        for statement in NEW_DISTRIBUTION_TABLES_DDL.split(";"):
            if statement.strip():
                conn.execute(statement)

        conn.execute("DROP VIEW IF EXISTS v_distribution_stats")
        conn.execute(DISTRIBUTION_STATS_VIEW_SQL)
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT unify_distribution")
        conn.execute("RELEASE SAVEPOINT unify_distribution")
        raise
    else:
        conn.execute("RELEASE SAVEPOINT unify_distribution")
