-- ============================================================
-- MIGRATION: Distribution-System Vereinheitlichung
-- ============================================================
-- Datum: 2026-02-18
-- Zweck: Tier-System entfernen, dist_type als einziges System
-- Vorbedingung: Backup von bach.db erstellt
-- FIX Task #1419 (2026-09-27): instance_identity wird per RENAME+INSERT
--   migriert statt gedroppt (Siegel-/Instanzidentitaet bleibt erhalten);
--   distribution_manifest wird vorsorglich angelegt, falls es fehlt
--   (FK-Ziel fuer distribution_snapshot_files/file_versions und
--   Quelle fuer v_distribution_stats).
-- Hinweis: ALTER RENAME setzt eine existierende instance_identity voraus
--   (Standard auf allen BACH-Instanzen); SQLite kennt kein ALTER IF EXISTS.
-- ============================================================

-- ============================================================
-- PHASE 1: Alte Tier-System Views entfernen
-- ============================================================

DROP VIEW IF EXISTS v_files_with_tiers;
DROP VIEW IF EXISTS v_latest_versions;

-- ============================================================
-- PHASE 2: Alte Tier-System Tabellen entfernen
-- Reihenfolge: Abhaengige Tabellen zuerst (wegen FK-Constraints)
-- ============================================================

DROP TABLE IF EXISTS snapshot_files;
DROP TABLE IF EXISTS snapshots;
DROP TABLE IF EXISTS release_manifest;
DROP TABLE IF EXISTS releases;
DROP TABLE IF EXISTS file_versions;
DROP TABLE IF EXISTS mode_transitions;
DROP TABLE IF EXISTS known_instances;
DROP TABLE IF EXISTS tier_patterns;
DROP TABLE IF EXISTS filesystem_entries;
DROP TABLE IF EXISTS tiers;

-- instance_identity NICHT droppen: Siegel-/Instanzidentitaet wird erhalten
-- (Migration in neue Struktur erfolgt in Phase 3, ohne current_mode)

-- ============================================================
-- PHASE 3: Neue Tabellen erstellen (dist_type-basiert)
-- ============================================================

-- Alte Tabelle (inkl. current_mode) beiseite legen, NICHT droppen
ALTER TABLE instance_identity RENAME TO instance_identity_old;

CREATE TABLE IF NOT EXISTS instance_identity (
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
);

-- Gespeicherte Identitaet/Siegel (instance_id, seal_status, kernel_hash,
-- ...) in neue Struktur uebernehmen; nur current_mode entfaellt.
INSERT INTO instance_identity (
    instance_id, instance_name, created, forked_from,
    seal_status, seal_broken_at, seal_broken_by, seal_broken_reason,
    kernel_hash, kernel_version, seal_last_verified,
    base_release, base_release_date
) SELECT
    instance_id, instance_name, created, forked_from,
    seal_status, seal_broken_at, seal_broken_by, seal_broken_reason,
    kernel_hash, kernel_version, seal_last_verified,
    base_release, base_release_date
FROM instance_identity_old;

DROP TABLE instance_identity_old;

-- distribution_manifest anlegen, falls noch nicht vorhanden
-- (FK-Ziel fuer snapshot_files/file_versions, Quelle fuer v_distribution_stats)
CREATE TABLE IF NOT EXISTS distribution_manifest (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    dist_type INTEGER DEFAULT 2,
    template_hash TEXT,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

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

-- ============================================================
-- PHASE 4: Stats-View neu erstellen (erweitert um manifest)
-- ============================================================

DROP VIEW IF EXISTS v_distribution_stats;

CREATE VIEW IF NOT EXISTS v_distribution_stats AS
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
FROM distribution_manifest;

-- ============================================================
-- DONE: Verifizierung
-- ============================================================
-- Nach Ausfuehrung pruefen:
--   SELECT name FROM sqlite_master WHERE type='table' AND name IN
--     ('tiers','tier_patterns','filesystem_entries','file_versions',
--      'snapshots','snapshot_files','releases','release_manifest',
--      'mode_transitions','known_instances');
-- Erwartet: Keine Ergebnisse (alle geloescht)
--
--   SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'distribution_%';
-- Erwartet: distribution_manifest, distribution_snapshots,
--           distribution_snapshot_files, distribution_releases,
--           distribution_file_versions
