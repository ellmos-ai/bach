-- ═══════════════════════════════════════════════════════════════════════════
-- BACH v1.1 - ARCHIVE.DB SCHEMA
-- Separate Datenbank für archivierte/gelöschte Einträge
-- Ermöglicht Wiederherstellung bei Bedarf
-- Erstellt: 2026-01-30
-- ═══════════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────────
-- METADATEN
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS archive_meta (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO archive_meta (key, value) VALUES
    ('schema_version', '1.0'),
    ('created_at', datetime('now')),
    ('description', 'BACH Archive Database - Gelöschte/archivierte Einträge');

-- ───────────────────────────────────────────────────────────────────────────
-- ARCHIVIERTE TASKS
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS archived_tasks (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT,
    status TEXT,
    category TEXT,
    assigned_to TEXT,
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    -- Archive-Metadaten
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_by TEXT DEFAULT 'system',
    archive_reason TEXT,  -- 'completed', 'deleted', 'consolidated', 'cleanup'
    source_db TEXT DEFAULT 'bach.db'
);

CREATE INDEX IF NOT EXISTS idx_archived_tasks_original ON archived_tasks(original_id);
CREATE INDEX IF NOT EXISTS idx_archived_tasks_date ON archived_tasks(archived_at);

-- ───────────────────────────────────────────────────────────────────────────
-- ARCHIVIERTE SESSIONS
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS archived_sessions (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER,
    session_id TEXT NOT NULL,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT,
    tasks_created INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    partner_id TEXT,
    -- Archive-Metadaten
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archive_reason TEXT,  -- 'compressed', 'old', 'cleanup'
    compressed_to TEXT    -- Verweis auf komprimierte Session falls applicable
);

CREATE INDEX IF NOT EXISTS idx_archived_sessions_date ON archived_sessions(archived_at);

-- ───────────────────────────────────────────────────────────────────────────
-- ARCHIVIERTE MEMORY-EINTRÄGE
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS archived_memory (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER,
    memory_type TEXT NOT NULL,  -- 'working', 'fact', 'lesson'
    category TEXT,
    key TEXT,
    content TEXT,
    created_at TIMESTAMP,
    -- Archive-Metadaten
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archive_reason TEXT,  -- 'decay', 'duplicate', 'obsolete', 'consolidated'
    -- Vollstaendiger Quelldatensatz fuer verlustfreien Working-Memory-Restore
    source_record TEXT
);

CREATE INDEX IF NOT EXISTS idx_archived_memory_type ON archived_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_archived_memory_date ON archived_memory(archived_at);

-- ───────────────────────────────────────────────────────────────────────────
-- ARCHIVIERTE DATEIEN (Referenzen)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS archived_files (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_path TEXT NOT NULL,
    file_type TEXT,  -- 'help', 'workflow', 'skill', 'tool', 'doc'
    content_hash TEXT,
    file_size INTEGER,
    -- Archive-Metadaten
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archive_reason TEXT,  -- 'renamed', 'deleted', 'moved', 'replaced'
    new_path TEXT,  -- Falls umbenannt/verschoben
    backup_path TEXT  -- Falls Inhalt gesichert wurde
);

CREATE INDEX IF NOT EXISTS idx_archived_files_path ON archived_files(original_path);

-- ───────────────────────────────────────────────────────────────────────────
-- RESTORE-LOG (Wiederherstellungs-Protokoll)
-- ───────────────────────────────────────────────────────────────────────────
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
);

-- ───────────────────────────────────────────────────────────────────────────
-- VIEWS FÜR EINFACHEN ZUGRIFF
-- ───────────────────────────────────────────────────────────────────────────

-- Übersicht aller archivierten Einträge
CREATE VIEW IF NOT EXISTS v_archive_overview AS
SELECT 'task' as type, archive_id, title as name, archived_at, archive_reason
FROM archived_tasks
UNION ALL
SELECT 'session' as type, archive_id, session_id as name, archived_at, archive_reason
FROM archived_sessions
UNION ALL
SELECT 'memory' as type, archive_id, key as name, archived_at, archive_reason
FROM archived_memory
UNION ALL
SELECT 'file' as type, archive_id, original_path as name, archived_at, archive_reason
FROM archived_files
ORDER BY archived_at DESC;

-- Statistik nach Typ und Grund
CREATE VIEW IF NOT EXISTS v_archive_stats AS
SELECT
    'tasks' as category,
    COUNT(*) as total,
    SUM(CASE WHEN archive_reason = 'completed' THEN 1 ELSE 0 END) as completed,
    SUM(CASE WHEN archive_reason = 'deleted' THEN 1 ELSE 0 END) as deleted
FROM archived_tasks
UNION ALL
SELECT
    'sessions' as category,
    COUNT(*) as total,
    SUM(CASE WHEN archive_reason = 'compressed' THEN 1 ELSE 0 END) as compressed,
    SUM(CASE WHEN archive_reason = 'old' THEN 1 ELSE 0 END) as old
FROM archived_sessions
UNION ALL
SELECT
    'memory' as category,
    COUNT(*) as total,
    SUM(CASE WHEN archive_reason = 'decay' THEN 1 ELSE 0 END) as decayed,
    SUM(CASE WHEN archive_reason = 'consolidated' THEN 1 ELSE 0 END) as consolidated
FROM archived_memory;
