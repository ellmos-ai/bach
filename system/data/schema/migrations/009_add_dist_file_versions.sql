-- Migration: dist_file_versions Tabelle hinzufuegen
-- Datum: 2026-02-21
-- Runde: 28
-- Grund: HQ6 Tests blockiert - Restore-Funktionen brauchen diese Tabelle
-- Ref: BUG-HQ5-MISSING-TABLE, SQ020

CREATE TABLE IF NOT EXISTS dist_file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    version TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    dist_type INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(file_path, version)
);

-- Initialdaten aus distribution_manifest uebernehmen (v3.1.2 = aktuelle Version)
INSERT OR IGNORE INTO dist_file_versions (file_path, version, file_hash, dist_type, created_at)
SELECT
    path,
    '3.1.2',
    '',  -- Hash wird bei naechstem Restore/Upgrade berechnet
    dist_type,
    datetime('now')
FROM distribution_manifest
WHERE dist_type IN (1, 2);  -- TEMPLATE + CORE
