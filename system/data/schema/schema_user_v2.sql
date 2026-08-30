-- ═══════════════════════════════════════════════════════════════════════════
-- DEPRECATED: Historisches Schema aus der Pre-Consolidation-Ära (user.db)
-- Die Live-DB folgt schema.sql (bach.db). Diese Datei wird NICHT mehr
-- von Code referenziert und dient nur noch als Dokumentation.
-- Siehe auch: schema_bach.sql Zeile 1654
-- ═══════════════════════════════════════════════════════════════════════════
-- BACH v1.1 - USER.DB SCHEMA (Erweitert)
-- Kombiniert: Basis-Konzept + Scanner aus _BATCH + DaemonManager
-- Erstellt: 2026-01-15
-- ═══════════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────────
-- METADATEN
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_meta (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ───────────────────────────────────────────────────────────────────────────
-- SCANNER-KONFIGURATION (aus _BATCH/config.json)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_config (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,                      -- JSON für komplexe Werte
    category TEXT,                   -- 'scan', 'daemon', 'session', 'output'
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Default-Werte
INSERT OR IGNORE INTO scan_config (key, value, category, description) VALUES
    ('base_path', '"{USER_DEV_PATH}"', 'scan', 'Basis-Pfad fuer Tool-Scans'),
    ('scan_folders', '["SINGLE", "SUITEN", "TOOLS"]', 'scan', 'Zu scannende Ordner'),
    ('task_files', '["AUFGABEN.txt", "Aufgaben.txt", "AUFGABEN.TXT", "TODO.md", "AUFGABEN.md", "ROADMAP.md", "DONE.md"]', 'scan', 'Task-Dateinamen'),
    ('test_files', '["TEST.txt", "Test.txt"]', 'scan', 'Test-Dateinamen'),
    ('feedback_files', '["TESTERGEBNIS.txt", "AENDERUNGEN.txt"]', 'scan', 'Feedback-Dateinamen'),
    ('ignore_folders', '["dist", "__pycache__", ".git", "venv", "node_modules", "_alt"]', 'scan', 'Ignorierte Ordner'),
    ('daemon_enabled', 'true', 'daemon', 'Daemon aktiviert'),
    ('daemon_interval_minutes', '60', 'daemon', 'Daemon-Intervall'),
    ('quiet_start', '"08:00"', 'daemon', 'Ruhezeit Start'),
    ('quiet_end', '"08:30"', 'daemon', 'Ruhezeit Ende'),
    ('target_duration_minutes', '13', 'session', 'Ziel-Sessiondauer'),
    ('max_tasks_per_session', '3', 'session', 'Max Tasks pro Session'),
    ('task_time_niedrig', '3', 'session', 'Geschätzte Zeit: niedrig'),
    ('task_time_mittel', '8', 'session', 'Geschätzte Zeit: mittel'),
    ('task_time_hoch', '15', 'session', 'Geschätzte Zeit: hoch');

-- ───────────────────────────────────────────────────────────────────────────
-- TOOL-REGISTRY (gescannte Software-Tools)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tool_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'aktiv' CHECK(status IN ('aktiv', 'inaktiv', 'archiviert')),
    has_aufgaben INTEGER DEFAULT 0,
    has_test INTEGER DEFAULT 0,
    has_feedback INTEGER DEFAULT 0,
    task_count INTEGER DEFAULT 0,
    last_scan TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tool_registry_status ON tool_registry(status);

-- ───────────────────────────────────────────────────────────────────────────
-- GESCANNTE AUFGABEN (aus Aufgaben-/TODO-/Roadmap-Dateien)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scanned_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id INTEGER REFERENCES tool_registry(id),
    tool_name TEXT NOT NULL,
    tool_path TEXT NOT NULL,
    task_text TEXT NOT NULL,
    aufwand TEXT DEFAULT 'mittel' CHECK(aufwand IN ('niedrig', 'mittel', 'hoch')),
    status TEXT DEFAULT 'offen' CHECK(status IN ('offen', 'in_arbeit', 'erledigt', 'blockiert')),
    priority_score REAL DEFAULT 0,
    source_file TEXT NOT NULL,       -- Pfad zur Aufgaben-Datei
    line_number INTEGER,             -- Zeile in der Datei
    file_hash TEXT,                  -- MD5 für Change-Detection
    last_modified TIMESTAMP,         -- Änderungsdatum der Datei
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_synced INTEGER DEFAULT 1,     -- 1 = in Sync, 0 = lokal geändert
    linked_task_id INTEGER REFERENCES tasks(id),
    tags TEXT,                       -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scanned_tasks_tool ON scanned_tasks(tool_name);
CREATE INDEX IF NOT EXISTS idx_scanned_tasks_status ON scanned_tasks(status);
CREATE INDEX IF NOT EXISTS idx_scanned_tasks_priority ON scanned_tasks(priority_score DESC);

-- ───────────────────────────────────────────────────────────────────────────
-- SCAN-PROTOKOLL (Scan-Läufe)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    tools_scanned INTEGER DEFAULT 0,
    tasks_found INTEGER DEFAULT 0,
    tasks_new INTEGER DEFAULT 0,
    tasks_updated INTEGER DEFAULT 0,
    tasks_removed INTEGER DEFAULT 0,
    triggered_by TEXT DEFAULT 'manual',  -- 'manual', 'daemon', 'watcher'
    errors TEXT                      -- JSON array
);

-- ───────────────────────────────────────────────────────────────────────────
-- NACHRICHTEN (MessageBox - adaptiert von inbox/)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL CHECK(direction IN ('inbox', 'outbox')),
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    body_type TEXT DEFAULT 'text' CHECK(body_type IN ('text', 'markdown', 'html', 'json')),
    priority INTEGER DEFAULT 0,      -- 0=normal, 1=hoch, 2=urgent
    status TEXT DEFAULT 'unread' CHECK(status IN ('unread', 'read', 'archived', 'deleted')),
    tags TEXT,                       -- JSON array
    parent_id INTEGER REFERENCES messages(id),
    thread_id TEXT,                  -- Für Konversations-Gruppierung (aus inbox/)
    topic TEXT,                      -- Thema (aus inbox/ THEMA-Konzept)
    attachments TEXT,                -- JSON array mit Pfaden
    metadata TEXT,                   -- Zusätzliche JSON-Daten
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    archived_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(topic);

-- ───────────────────────────────────────────────────────────────────────────
-- USER-AUFGABEN (getrennt von gescannten Tasks)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'P3' CHECK(priority IN ('P1', 'P2', 'P3', 'P4')),
    status TEXT DEFAULT 'open' CHECK(status IN ('open', 'in_progress', 'blocked', 'done', 'cancelled')),
    category TEXT,
    project TEXT,
    assignee TEXT,                   -- Agent oder 'user'
    due_date TEXT,                    -- ISO-Datum YYYY-MM-DD (Routinika-kompatibel)
    estimated_minutes INTEGER,
    actual_minutes INTEGER,
    tags TEXT,                       -- JSON array
    checklist TEXT,                  -- JSON array mit Sub-Tasks
    notes TEXT,
    source TEXT,                     -- 'user', 'scanner', 'daemon'
    source_id INTEGER,               -- ID in Quell-Tabelle
    parent_id INTEGER REFERENCES tasks(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);

-- ───────────────────────────────────────────────────────────────────────────
-- DAEMON JOBS (erweitert aus DaemonManager)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    profile_name TEXT,               -- Aus DaemonManager/profiles.json
    description TEXT,
    job_type TEXT NOT NULL CHECK(job_type IN ('cron', 'interval', 'event', 'manual')),
    schedule TEXT,                   -- Cron-Expression oder Interval
    command TEXT NOT NULL,           -- CLI-Befehl
    script_path TEXT,                -- Pfad zum Script (aus DaemonManager)
    arguments TEXT,                  -- Argumente (aus DaemonManager)
    parameters TEXT,                 -- JSON mit Parametern
    is_active INTEGER DEFAULT 0,
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    run_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    last_result TEXT,                -- 'success', 'failed', 'timeout'
    last_output TEXT,
    timeout_seconds INTEGER DEFAULT 300,
    retry_on_fail INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ───────────────────────────────────────────────────────────────────────────
-- DAEMON RUNS (Job-Ausführungen)
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES scheduler_jobs(id),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    result TEXT CHECK(result IN ('success', 'failed', 'timeout', 'cancelled')),
    output TEXT,
    error TEXT,
    triggered_by TEXT DEFAULT 'schedule'  -- 'schedule', 'manual', 'event'
);

CREATE INDEX IF NOT EXISTS idx_scheduler_runs_job ON scheduler_runs(job_id);

-- ───────────────────────────────────────────────────────────────────────────
-- STANDARD DAEMON-JOBS (migriert aus DaemonManager/profiles.json)
-- ───────────────────────────────────────────────────────────────────────────
INSERT OR IGNORE INTO scheduler_jobs (name, profile_name, description, job_type, schedule, command, script_path, arguments, is_active) VALUES
    ('scanner', 'scanner', 'Scannt Software-Ordner nach Aufgaben', 'interval', '60', 'bach scan run', NULL, NULL, 1),
    ('backup', 'backup_tool', 'Automatisches Backup', 'interval', '1440', 'bach backup create', NULL, '--to-nas', 0);

-- ───────────────────────────────────────────────────────────────────────────
-- USER PREFERENCES
-- ───────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,          -- 'dashboard', 'scanner', 'daemon', 'ui'
    key TEXT NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);

-- ───────────────────────────────────────────────────────────────────────────
-- VIEWS
-- ───────────────────────────────────────────────────────────────────────────

-- Alle offenen Tasks (User + Gescannte)
CREATE VIEW IF NOT EXISTS v_all_open_tasks AS
SELECT 
    'user' as source,
    id,
    title as task_text,
    priority,
    status,
    project as tool_name,
    NULL as source_file,
    created_at
FROM tasks WHERE status IN ('open', 'in_progress')
UNION ALL
SELECT 
    'scanner' as source,
    id,
    task_text,
    CASE aufwand 
        WHEN 'hoch' THEN 'P1'
        WHEN 'mittel' THEN 'P2'
        ELSE 'P3'
    END as priority,
    status,
    tool_name,
    source_file,
    created_at
FROM scanned_tasks WHERE status IN ('offen', 'in_arbeit')
ORDER BY priority, created_at;

-- Daemon-Status Übersicht
CREATE VIEW IF NOT EXISTS v_daemon_status AS
SELECT 
    j.id,
    j.name,
    j.is_active,
    j.last_run,
    j.last_result,
    j.run_count,
    j.success_count,
    j.fail_count,
    r.duration_seconds as last_duration
FROM scheduler_jobs j
LEFT JOIN scheduler_runs r ON r.job_id = j.id 
    AND r.started_at = j.last_run;
