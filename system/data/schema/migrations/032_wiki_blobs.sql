-- Migration: Wiki-Artikel als BLOBs in bach.db (SQ044)
-- Datum: 2026-03-04
-- Runde: MILK v3.5.0
-- Ref: SQ044_BACH_IN_DB_VISION

-- Haupt-BLOB-Tabelle
CREATE TABLE IF NOT EXISTS bach_blobs (
    path TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'wiki',
    content TEXT,
    mime_type TEXT DEFAULT 'text/plain',
    size_bytes INTEGER,
    checksum TEXT,
    lang TEXT DEFAULT 'de',
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bach_blobs_category ON bach_blobs(category);
CREATE INDEX IF NOT EXISTS idx_bach_blobs_lang ON bach_blobs(lang);

-- FTS5 Virtual Table fuer Volltext-Suche
CREATE VIRTUAL TABLE IF NOT EXISTS bach_blobs_fts USING fts5(
    path,
    content,
    category,
    content=bach_blobs,
    content_rowid=rowid,
    tokenize='unicode61'
);

-- Triggers fuer FTS5 Synchronisation
CREATE TRIGGER IF NOT EXISTS bach_blobs_ai AFTER INSERT ON bach_blobs BEGIN
    INSERT INTO bach_blobs_fts(rowid, path, content, category)
    VALUES (new.rowid, new.path, new.content, new.category);
END;

CREATE TRIGGER IF NOT EXISTS bach_blobs_ad AFTER DELETE ON bach_blobs BEGIN
    INSERT INTO bach_blobs_fts(bach_blobs_fts, rowid, path, content, category)
    VALUES ('delete', old.rowid, old.path, old.content, old.category);
END;

CREATE TRIGGER IF NOT EXISTS bach_blobs_au AFTER UPDATE ON bach_blobs BEGIN
    INSERT INTO bach_blobs_fts(bach_blobs_fts, rowid, path, content, category)
    VALUES ('delete', old.rowid, old.path, old.content, old.category);
    INSERT INTO bach_blobs_fts(rowid, path, content, category)
    VALUES (new.rowid, new.path, new.content, new.category);
END;

-- History-Tabelle fuer Aenderungsverfolgung
CREATE TABLE IF NOT EXISTS bach_blob_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blob_path TEXT NOT NULL,
    action TEXT NOT NULL,
    old_checksum TEXT,
    new_checksum TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (blob_path) REFERENCES bach_blobs(path)
);

CREATE INDEX IF NOT EXISTS idx_blob_history_path ON bach_blob_history(blob_path);
