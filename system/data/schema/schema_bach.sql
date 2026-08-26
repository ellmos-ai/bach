-- ============================================================
-- BACH v1.0 - KONSOLIDIERTES DATENBANKSCHEMA
-- ============================================================
-- Erstellt: 2026-01-11
-- Prinzip: EIN Bereich = EINE Tabelle (max)
-- Ersetzt: 17+ JSON-Dateien aus recludOS
-- ============================================================

-- ============================================================
-- KONSOLIDIERUNGS-ÜBERSICHT
-- ============================================================
-- 
-- VORHER (recludOS): 17+ separate Registries
--   - system-registry.json
--   - skill_registry.json
--   - master_communication_registry.json
--   - master_config_registry.json
--   - agents_registry.json
--   - services_registry.json
--   - data_tools_registry.json
--   - external_tools_registry.json
--   - papierkorb_registry.json
--   - archiv_registry.json
--   - task-manager.json
--   - triggers.json
--   - micro-routines.json
--   - etc.
--
-- NACHHER (Bach): 1 SQLite DB mit 8 Kernbereichen
--   1. system      - Identität, Config, Boot
--   2. skills      - Alle Skills/Workflows
--   3. tasks       - Task-Management (CONNI)
--   4. tools       - Interne + externe Tools
--   5. connections - APIs, Services, AIs
--   6. memory      - Context, Sessions, Lessons
--   7. files       - Directory Truth, Papierkorb
--   8. automation  - Triggers, Routines, Injectors
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================================
-- 1. SYSTEM - Identität & Konfiguration
-- ============================================================
-- Ersetzt: identity.json, config.json, system-registry.json

CREATE TABLE IF NOT EXISTS system_identity (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton
    instance_id TEXT UNIQUE NOT NULL,
    instance_name TEXT,
    version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    
    -- Siegel (Integrität)
    seal_status TEXT DEFAULT 'intact',  -- 'intact', 'broken'
    kernel_hash TEXT,
    last_verified TEXT,
    
    -- Mode
    current_mode TEXT DEFAULT 'developer',  -- 'developer', 'user'
    
    -- Meta
    last_boot TEXT,
    boot_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    type TEXT DEFAULT 'string',  -- 'string', 'number', 'boolean', 'json'
    category TEXT,               -- 'boot', 'paths', 'behavior', 'limits'
    description TEXT,
    updated_at TEXT
);

-- Default-Configs einfügen
INSERT OR IGNORE INTO system_config (key, value, type, category, description) VALUES
('token_warning_threshold', '70', 'number', 'limits', 'Token-Warnung ab X%'),
('token_critical_threshold', '85', 'number', 'limits', 'Token-Kritisch ab X%'),
('auto_backup_days', '30', 'number', 'behavior', 'Backup-Intervall in Tagen'),
('default_retention_days', '30', 'number', 'behavior', 'Papierkorb-Aufbewahrung'),
('timeout_checkpoint_minutes', '10', 'number', 'behavior', 'Status-Checkpoint nach X Min');


-- ============================================================
-- 2. SKILLS - Alle Skills/Workflows zentral
-- ============================================================
-- Ersetzt: skill_registry.json, alle SKILL.md Metadaten

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Klassifizierung
    type TEXT NOT NULL,              -- 'skill', 'workflow', 'agent', 'rule'
    category TEXT,                   -- 'think', 'act', 'communicate', 'production'
    
    -- Dateipfad
    path TEXT NOT NULL,              -- Relativer Pfad zur .txt/.md Datei
    
    -- Metadaten
    version TEXT DEFAULT '1.0.0',
    description TEXT,
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    priority INTEGER DEFAULT 50,     -- 0-100, höher = wichtiger
    
    -- Trigger
    trigger_phrases TEXT,            -- JSON-Array von Trigger-Phrasen
    
    -- Timestamps
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_skills_type ON skills(type);
CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
CREATE INDEX IF NOT EXISTS idx_skills_active ON skills(is_active);


-- ============================================================
-- 3. TASKS - CONNI Task-System
-- ============================================================
-- Ersetzt: task-manager.json, queue-Ordner

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    
    -- Identifikation
    title TEXT NOT NULL,
    description TEXT,
    
    -- Klassifizierung
    category TEXT,                   -- 'system', 'user', 'delegation', 'shutdown'
    priority TEXT DEFAULT 'P3',      -- 'P1', 'P2', 'P3', 'P4'
    tags TEXT,                       -- JSON-Array
    
    -- Status
    status TEXT DEFAULT 'pending',   -- 'pending', 'in_progress', 'done', 'blocked', 'delegated'
    
    -- Zeitschätzung
    estimated_minutes INTEGER,
    actual_minutes INTEGER,
    
    -- Delegation
    delegated_to TEXT,               -- 'ollama', 'gemini', 'copilot', 'user', NULL
    delegation_status TEXT,          -- 'pending', 'processing', 'completed', 'failed'
    
    -- Quelle
    source_file TEXT,                -- Woher kam der Task (AUFGABEN.txt, etc.)
    source_line INTEGER,
    
    -- Wiederholung
    is_recurring BOOLEAN DEFAULT 0,
    recurrence_pattern TEXT,         -- 'daily', 'weekly', 'monthly', cron-like
    next_occurrence TEXT,
    due_date TEXT,                    -- ISO-Datum YYYY-MM-DD (Routinika-kompatibel)
    
    -- Ausführung
    executable_command TEXT,         -- Optional: Direkt ausführbarer Befehl

    -- Timestamps
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT,

    -- Anhänge
    image_data TEXT                  -- Base64-encoded Screenshot/Bild (optional)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);

-- Virtuelle Tabelle für Volltextsuche
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
    title, description, tags,
    content='tasks',
    content_rowid='id'
);


-- ============================================================
-- 4. TOOLS - Interne + Externe Tools
-- ============================================================
-- Ersetzt: data_tools_registry.json, external_tools_registry.json

CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Klassifizierung
    type TEXT NOT NULL,              -- 'internal', 'external', 'mcp', 'api'
    category TEXT,                   -- 'data', 'coding', 'file', 'communication'
    
    -- Ausführung
    path TEXT,                       -- Pfad zum Script (intern)
    endpoint TEXT,                   -- URL/Endpoint (extern)
    command TEXT,                    -- Aufruf-Befehl
    
    -- Metadaten
    description TEXT,
    version TEXT,
    
    -- Fähigkeiten (für Delegation-Matching)
    capabilities TEXT,               -- JSON-Array: ['json', 'encoding', 'bulk']
    use_for TEXT,                    -- Wofür geeignet: 'Prompt-Generierung, Bulk'
    
    -- Status
    is_available BOOLEAN DEFAULT 1,
    last_check TEXT,
    error_count INTEGER DEFAULT 0,
    
    -- Kosten (für Token-Entscheidungen)
    tokens_saved_percent INTEGER,    -- Wie viel % Tokens spart Delegation?
    speed TEXT,                      -- 'fast', 'medium', 'slow'
    
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tools_type ON tools(type);
CREATE INDEX IF NOT EXISTS idx_tools_available ON tools(is_available);


-- ============================================================
-- 5. CONNECTIONS - APIs, Services, AIs
-- ============================================================
-- Ersetzt: master_communication_registry.json, contacts.json

CREATE TABLE IF NOT EXISTS connections (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Klassifizierung
    type TEXT NOT NULL,              -- 'api', 'service', 'ai', 'mcp', 'local'
    category TEXT,                   -- 'search', 'storage', 'communication', 'ai'
    
    -- Verbindung
    endpoint TEXT,
    auth_type TEXT,                  -- 'none', 'api_key', 'oauth', 'token'
    auth_config TEXT,                -- JSON mit Auth-Details (verschlüsselt)
    
    -- Erkennung (für automatisches Matching)
    trigger_patterns TEXT,           -- JSON-Array: ['excel', 'spreadsheet']
    help_text TEXT,                  -- Was zeigen bei Match
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    last_used TEXT,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_connections_type ON connections(type);
CREATE INDEX IF NOT EXISTS idx_connections_active ON connections(is_active);


-- ============================================================
-- 6. MEMORY - Context, Sessions, Lessons
-- ============================================================
-- Ersetzt: lessons-learned.json, session files, context sources

CREATE TABLE IF NOT EXISTS memory_lessons (
    id INTEGER PRIMARY KEY,
    
    -- Klassifizierung
    category TEXT NOT NULL,          -- 'bug', 'workaround', 'best_practice', 'gotcha'
    severity TEXT DEFAULT 'medium',  -- 'critical', 'high', 'medium', 'low'
    
    -- Inhalt
    title TEXT NOT NULL,
    problem TEXT,
    solution TEXT NOT NULL,
    
    -- Kontext
    related_tools TEXT,              -- JSON-Array
    related_files TEXT,              -- JSON-Array
    
    -- Trigger (wann zeigen)
    trigger_words TEXT,              -- JSON-Array: ['encoding', 'json', 'crash']
    trigger_events TEXT,             -- JSON-Array: ['startup', 'error']
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    times_shown INTEGER DEFAULT 0,
    last_shown TEXT,
    
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_context (
    id INTEGER PRIMARY KEY,
    
    -- Source (wie _CHIAH context_sources)
    source_name TEXT UNIQUE NOT NULL,  -- 'lessons', 'strategies', 'best_practices'
    source_path TEXT,
    
    -- Gewichtung
    weight INTEGER DEFAULT 5,        -- 1-10, höher = wichtiger
    
    -- Trigger
    trigger_events TEXT,             -- JSON: ['startup', 'error', 'shutdown']
    trigger_words TEXT,              -- JSON: ['fehler', 'bug', 'problem']
    
    -- Injection
    inject_on_match BOOLEAN DEFAULT 1,
    injection_template TEXT,
    
    is_active BOOLEAN DEFAULT 1,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS memory_sessions (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    
    started_at TEXT NOT NULL,
    ended_at TEXT,
    
    -- Zusammenfassung
    summary TEXT,
    tasks_completed INTEGER DEFAULT 0,
    tasks_created INTEGER DEFAULT 0,
    
    -- Token-Tracking
    tokens_used INTEGER,
    delegation_count INTEGER DEFAULT 0,
    
    -- Kontext für nächste Session
    continuation_context TEXT        -- Was wurde angefangen, wo weitermachen
);


-- ============================================================
-- 7. FILES - Directory Truth, Papierkorb, Archiv
-- ============================================================
-- Ersetzt: directory_watcher, papierkorb_registry, archiv_registry

CREATE TABLE IF NOT EXISTS files_truth (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    
    -- Typ
    type TEXT NOT NULL,              -- 'file', 'directory'
    
    -- Status
    exists BOOLEAN DEFAULT 1,
    
    -- Checksumme (für Änderungserkennung)
    checksum TEXT,
    size INTEGER,
    
    -- Timestamps
    created_at TEXT,
    modified_at TEXT,
    last_scan TEXT
);

CREATE TABLE IF NOT EXISTS files_trash (
    id INTEGER PRIMARY KEY,
    
    original_path TEXT NOT NULL,
    trash_path TEXT NOT NULL,
    
    -- Metadaten
    size INTEGER,
    deleted_at TEXT NOT NULL,
    deleted_by TEXT,                 -- 'user', 'system', 'cleanup'
    
    -- Retention
    retention_days INTEGER DEFAULT 30,
    expires_at TEXT,
    
    -- Status
    status TEXT DEFAULT 'active',    -- 'active', 'expired', 'restored', 'purged'
    restored_at TEXT,
    purged_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_trash_expires ON files_trash(expires_at);
CREATE INDEX IF NOT EXISTS idx_trash_status ON files_trash(status);


-- ============================================================
-- 8. AUTOMATION - Triggers, Routines, Injectors
-- ============================================================
-- Ersetzt: triggers.json, micro-routines.json, injectors

CREATE TABLE IF NOT EXISTS automation_triggers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Trigger-Phrasen
    phrases TEXT NOT NULL,           -- JSON-Array
    
    -- Aktion
    skill_name TEXT,                 -- FK zu skills.name
    action TEXT NOT NULL,
    
    -- Optionen
    priority INTEGER DEFAULT 50,
    is_active BOOLEAN DEFAULT 1,
    
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS automation_routines (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Typ
    type TEXT NOT NULL,              -- 'pre_prompt', 'post_response', 'periodic'
    
    -- Bedingung
    condition TEXT NOT NULL,         -- 'always', 'if_exists', 'time_based', 'date_changed'
    condition_config TEXT,           -- JSON mit Details
    
    -- Aktion
    action TEXT NOT NULL,
    action_config TEXT,              -- JSON mit Details
    
    -- Zeitsteuerung (für periodic)
    interval TEXT,                   -- 'daily', 'weekly', 'monthly', '10min'
    last_run TEXT,
    next_run TEXT,
    
    -- Status
    priority INTEGER DEFAULT 50,
    is_active BOOLEAN DEFAULT 1,
    
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS automation_injectors (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Typ (wie _CHIAH)
    type TEXT NOT NULL,              -- 'strategy', 'between', 'context', 'time'
    
    -- Trigger
    trigger_words TEXT,              -- JSON-Array
    trigger_events TEXT,             -- JSON-Array
    
    -- Response
    response_template TEXT NOT NULL,
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    times_triggered INTEGER DEFAULT 0,
    
    updated_at TEXT
);


-- ============================================================
-- 9. MONITORING - Token-Watcher, Success-Watcher, Process-Watcher
-- ============================================================
-- Ersetzt: token-watcher/data/, success-watcher/data/, process-watcher/data/

CREATE TABLE IF NOT EXISTS monitor_tokens (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    
    -- Verbrauch
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    tokens_total INTEGER DEFAULT 0,
    
    -- Budget
    budget_percent REAL,             -- Aktuelle Auslastung in %
    warning_triggered BOOLEAN DEFAULT 0,
    critical_triggered BOOLEAN DEFAULT 0,
    
    -- Kosten (optional)
    cost_usd REAL,
    exchange_rate REAL,              -- EUR/USD
    cost_eur REAL,
    
    -- Delegation-Entscheidungen
    delegations_suggested INTEGER DEFAULT 0,
    delegations_accepted INTEGER DEFAULT 0,
    tokens_saved INTEGER DEFAULT 0,
    
    timestamp TEXT NOT NULL,
    
    FOREIGN KEY (session_id) REFERENCES memory_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS monitor_success (
    id INTEGER PRIMARY KEY,
    
    -- Was wurde gemessen
    entity_type TEXT NOT NULL,       -- 'task', 'tool', 'skill', 'delegation'
    entity_id TEXT NOT NULL,
    entity_name TEXT,
    
    -- Metriken
    attempts INTEGER DEFAULT 0,
    successes INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0,
    success_rate REAL,               -- 0.0 - 1.0
    
    -- Zeitmetriken
    avg_duration_seconds REAL,
    last_success TEXT,
    last_failure TEXT,
    
    -- Feedback
    user_rating INTEGER,             -- 1-5 Sterne
    notes TEXT,
    
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_success_entity ON monitor_success(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_success_rate ON monitor_success(success_rate);

CREATE TABLE IF NOT EXISTS monitor_processes (
    id INTEGER PRIMARY KEY,
    
    -- Akteur-Status (6-Kategorien-Modell)
    actor_type TEXT NOT NULL,        -- 'online_tool', 'integrated_tool', 'os', 'operating_ai', 'other_ai', 'user'
    actor_name TEXT NOT NULL,
    
    -- Status
    status TEXT DEFAULT 'idle',      -- 'idle', 'active', 'waiting', 'error'
    current_task_id INTEGER,
    
    -- Metriken
    tasks_completed INTEGER DEFAULT 0,
    last_activity TEXT,
    uptime_seconds INTEGER,
    
    -- Health
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_error_at TEXT,
    
    updated_at TEXT,
    
    FOREIGN KEY (current_task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS monitor_pricing (
    id INTEGER PRIMARY KEY,
    
    model TEXT NOT NULL,             -- 'opus-4', 'sonnet-4', 'haiku-4'
    
    -- Preise pro 1M Tokens (USD)
    input_price REAL NOT NULL,
    output_price REAL NOT NULL,
    
    -- Gültig ab
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    
    -- Meta
    source TEXT,                     -- 'anthropic', 'manual'
    updated_at TEXT
);

-- Default-Preise einfügen (Stand 2026-02)
INSERT OR IGNORE INTO monitor_pricing (model, input_price, output_price, valid_from, source) VALUES
('claude-opus-4', 15.00, 75.00, '2026-01-01', 'anthropic'),
('claude-opus-4.6', 15.00, 75.00, '2026-02-01', 'anthropic'),
('claude-sonnet-4', 3.00, 15.00, '2026-01-01', 'anthropic'),
('claude-haiku-4', 0.25, 1.25, '2026-01-01', 'anthropic');


-- ============================================================
-- 10. AGENTS - Agenten-Registry mit Synergien
-- ============================================================
-- Ersetzt: agents/registry.json, agents/synergy_map.json

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    
    -- Klassifizierung
    type TEXT NOT NULL,              -- 'developer', 'research', 'production', 'assistant', 'custom'
    category TEXT,                   -- 'beruflich', 'privat', 'system'
    
    -- Dateipfade
    skill_path TEXT,                 -- Pfad zur SKILL.md/.txt
    script_path TEXT,                -- Pfad zum Python-Script (agent.py)
    config_path TEXT,                -- Pfad zur config.json
    
    -- Metadaten
    version TEXT DEFAULT '1.0.0',
    description TEXT,
    capabilities TEXT,               -- JSON-Array: ['code_analysis', 'generation', 'review']
    
    -- Ausführung
    entry_command TEXT,              -- z.B. 'python agent.py'
    requires_tools TEXT,             -- JSON-Array benötigter Tools
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    is_autonomous BOOLEAN DEFAULT 0, -- Kann selbstständig arbeiten?
    priority INTEGER DEFAULT 50,
    
    -- Metriken
    tasks_completed INTEGER DEFAULT 0,
    success_rate REAL,
    last_used TEXT,
    
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(type);
CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active);

CREATE TABLE IF NOT EXISTS agent_synergies (
    id INTEGER PRIMARY KEY,
    
    -- Beziehung
    agent_a_id INTEGER NOT NULL,
    agent_b_id INTEGER NOT NULL,
    
    -- Synergie-Details
    synergy_type TEXT NOT NULL,      -- 'supports', 'extends', 'delegates_to', 'receives_from'
    strength INTEGER DEFAULT 5,       -- 1-10, wie stark die Synergie
    
    -- Wann aktivieren
    trigger_conditions TEXT,          -- JSON: Bedingungen für automatische Zusammenarbeit
    
    -- Beschreibung
    description TEXT,
    
    is_active BOOLEAN DEFAULT 1,
    
    FOREIGN KEY (agent_a_id) REFERENCES agents(id),
    FOREIGN KEY (agent_b_id) REFERENCES agents(id),
    UNIQUE(agent_a_id, agent_b_id, synergy_type)
);

-- Default-Agenten einfügen
INSERT OR IGNORE INTO agents (name, type, category, description, capabilities, is_active) VALUES
('entwickler', 'developer', 'system', 'Code-Analyse, Generierung, Review', 
 '["code_analysis", "code_generation", "code_review", "refactoring"]', 1),
('research', 'research', 'system', 'Recherche, Literatur-Review, Analyse',
 '["web_search", "literature_review", "data_analysis", "summarization"]', 1),
('production', 'production', 'system', 'Content-Erstellung: Text, Musik, Video',
 '["text_generation", "music_production", "video_scripting", "podcast"]', 1),
('foerderplaner', 'assistant', 'beruflich', 'Förderplanung für Autismus-Bereich',
 '["assessment", "goal_setting", "progress_tracking"]', 1);


-- ============================================================
-- 11. LANGUAGES - Übersetzungen und Lokalisierung
-- ============================================================
-- Ersetzt: languages/dictionary.json, languages/locales/

CREATE TABLE IF NOT EXISTS languages_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton
    
    default_language TEXT DEFAULT 'de',
    fallback_language TEXT DEFAULT 'en',
    
    -- Aktive Sprachen
    enabled_languages TEXT DEFAULT '["de", "en"]',  -- JSON-Array
    
    -- Einstellungen
    auto_translate BOOLEAN DEFAULT 0,
    preserve_formatting BOOLEAN DEFAULT 1,
    
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS languages_translations (
    id INTEGER PRIMARY KEY,
    
    -- Schlüssel
    key TEXT NOT NULL,               -- z.B. 'ui.button.save', 'msg.error.not_found'
    namespace TEXT DEFAULT 'common', -- 'ui', 'msg', 'help', 'skill', 'error'
    
    -- Übersetzungen (eine Zeile pro Sprache)
    language TEXT NOT NULL,          -- 'de', 'en', 'fr', etc.
    value TEXT NOT NULL,             -- Die Übersetzung
    
    -- Meta
    is_verified BOOLEAN DEFAULT 0,   -- Wurde manuell geprüft?
    source TEXT,                     -- 'manual', 'auto', 'import'
    
    created_at TEXT,
    updated_at TEXT,
    
    UNIQUE(key, namespace, language)
);

CREATE INDEX IF NOT EXISTS idx_translations_key ON languages_translations(key);
CREATE INDEX IF NOT EXISTS idx_translations_lang ON languages_translations(language);
CREATE INDEX IF NOT EXISTS idx_translations_ns ON languages_translations(namespace);

CREATE TABLE IF NOT EXISTS languages_dictionary (
    id INTEGER PRIMARY KEY,
    
    -- Wort/Begriff
    term TEXT NOT NULL,
    
    -- Sprache und Übersetzung
    source_lang TEXT NOT NULL,       -- 'de'
    target_lang TEXT NOT NULL,       -- 'en'
    translation TEXT NOT NULL,
    
    -- Kontext
    context TEXT,                    -- Fachgebiet: 'tech', 'medical', 'legal'
    part_of_speech TEXT,             -- 'noun', 'verb', 'adj'
    
    -- Alternativen
    alternatives TEXT,               -- JSON-Array alternativer Übersetzungen
    
    -- Status
    is_preferred BOOLEAN DEFAULT 1,
    usage_count INTEGER DEFAULT 0,
    
    created_at TEXT,
    
    UNIQUE(term, source_lang, target_lang, context)
);

CREATE INDEX IF NOT EXISTS idx_dict_term ON languages_dictionary(term);
CREATE INDEX IF NOT EXISTS idx_dict_langs ON languages_dictionary(source_lang, target_lang);

-- Default Language Config
INSERT OR IGNORE INTO languages_config (id, default_language, fallback_language, enabled_languages)
VALUES (1, 'de', 'en', '["de", "en"]');

-- Beispiel-Übersetzungen (System-UI)
INSERT OR IGNORE INTO languages_translations (key, namespace, language, value, source) VALUES
('startup.welcome', 'ui', 'de', 'Willkommen bei Bach!', 'manual'),
('startup.welcome', 'ui', 'en', 'Welcome to Bach!', 'manual'),
('task.created', 'msg', 'de', 'Aufgabe erstellt', 'manual'),
('task.created', 'msg', 'en', 'Task created', 'manual'),
('task.completed', 'msg', 'de', 'Aufgabe erledigt', 'manual'),
('task.completed', 'msg', 'en', 'Task completed', 'manual'),
('error.not_found', 'error', 'de', 'Nicht gefunden', 'manual'),
('error.not_found', 'error', 'en', 'Not found', 'manual'),
('help.available', 'help', 'de', 'Verfügbare Hilfe-Themen:', 'manual'),
('help.available', 'help', 'en', 'Available help topics:', 'manual');


-- ============================================================
-- VIEWS für einfachen Zugriff
-- ============================================================

-- Aktive Agenten
CREATE VIEW IF NOT EXISTS v_active_agents AS
SELECT name, type, category, description, capabilities, success_rate, last_used
FROM agents
WHERE is_active = 1
ORDER BY priority DESC, name;

-- Agenten-Synergien (lesbar)
CREATE VIEW IF NOT EXISTS v_agent_synergies AS
SELECT 
    a1.name as agent_from,
    a2.name as agent_to,
    s.synergy_type,
    s.strength,
    s.description
FROM agent_synergies s
JOIN agents a1 ON s.agent_a_id = a1.id
JOIN agents a2 ON s.agent_b_id = a2.id
WHERE s.is_active = 1
ORDER BY s.strength DESC;

-- Übersetzungen für eine Sprache
CREATE VIEW IF NOT EXISTS v_translations_de AS
SELECT key, namespace, value
FROM languages_translations
WHERE language = 'de'
ORDER BY namespace, key;

-- Aktive Skills nach Kategorie
CREATE VIEW IF NOT EXISTS v_active_skills AS
SELECT name, type, category, path, trigger_phrases
FROM skills
WHERE is_active = 1
ORDER BY priority DESC, name;

-- Offene Tasks nach Priorität
CREATE VIEW IF NOT EXISTS v_pending_tasks AS
SELECT id, title, priority, category, estimated_minutes, created_at
FROM tasks
WHERE status = 'pending'
ORDER BY 
    CASE priority 
        WHEN 'P1' THEN 1 
        WHEN 'P2' THEN 2 
        WHEN 'P3' THEN 3 
        ELSE 4 
    END,
    created_at;

-- Delegierbare Tasks
CREATE VIEW IF NOT EXISTS v_delegatable_tasks AS
SELECT t.*, 
       CASE 
           WHEN t.title LIKE '%prompt%' OR t.title LIKE '%text%' THEN 'ollama'
           WHEN t.title LIKE '%research%' OR t.title LIKE '%analyse%' THEN 'gemini'
           WHEN t.title LIKE '%excel%' OR t.title LIKE '%word%' THEN 'copilot'
           ELSE NULL
       END as suggested_delegate
FROM tasks t
WHERE t.status = 'pending' 
  AND t.delegated_to IS NULL;

-- Verfügbare Tools nach Typ
CREATE VIEW IF NOT EXISTS v_available_tools AS
SELECT name, type, category, capabilities, use_for
FROM tools
WHERE is_available = 1
ORDER BY type, name;

-- Aktive Lessons nach Severity
CREATE VIEW IF NOT EXISTS v_active_lessons AS
SELECT category, severity, title, solution, trigger_words
FROM memory_lessons
WHERE is_active = 1
ORDER BY 
    CASE severity 
        WHEN 'critical' THEN 1 
        WHEN 'high' THEN 2 
        WHEN 'medium' THEN 3 
        ELSE 4 
    END;

-- Papierkorb mit Ablaufdatum
CREATE VIEW IF NOT EXISTS v_trash_expiring AS
SELECT original_path, deleted_at, expires_at,
       julianday(expires_at) - julianday('now') as days_remaining
FROM files_trash
WHERE status = 'active'
ORDER BY expires_at;


-- ============================================================
-- MIGRATION: Initiale Daten
-- ============================================================

-- System-Identität
INSERT OR IGNORE INTO system_identity (id, instance_id, instance_name, version, created_at)
VALUES (1, 'bach-' || strftime('%Y%m%d', 'now'), 'Bach v1.0', '1.0.0', datetime('now'));

-- Context Sources (aus _CHIAH)
INSERT OR IGNORE INTO memory_context (source_name, weight, trigger_events, trigger_words, is_active) VALUES
('problems', 10, '["startup", "error"]', '["fehler", "error", "bug", "crash"]', 1),
('lessons_learned', 8, '["startup", "error"]', '["fehler", "bug", "problem"]', 1),
('strategies', 7, '[]', '["blockiert", "komplex", "schwierig", "unsicher"]', 1),
('best_practices', 6, '["startup"]', '[]', 1),
('meta_cognitive', 5, '[]', '["stress", "druck", "panik", "überfordert"]', 1);

-- Standard-Injectors (aus _CHIAH)
INSERT OR IGNORE INTO automation_injectors (name, type, trigger_words, response_template, is_active) VALUES
('strategy_error', 'strategy', '["fehler", "error", "bug"]', 
 'Fehler sind wertvolle Informationen, nicht Versagen.', 1),
('strategy_complex', 'strategy', '["komplex", "kompliziert"]', 
 'In kleine Schritte zerlegen (~5 Min pro Schritt).', 1),
('strategy_blocked', 'strategy', '["blockiert", "stuck"]', 
 'Überspringen und später zurückkommen ist OK.', 1),
('strategy_done', 'strategy', '["fertig", "geschafft", "done"]', 
 'Gut gemacht! Between-Tasks Check nicht vergessen.', 1),
('between_task', 'between', '["erledigt", "abgeschlossen"]', 
 '1. Zeit-Check: Noch im Limit?\n2. Memory OK?\n3. Nächste Aufgabe oder Shutdown?', 1);


-- ============================================================
-- ZUSAMMENFASSUNG
-- ============================================================
--
-- 11 BEREICHE, 23 TABELLEN statt 20+ JSON-Dateien:
--
-- | #  | Bereich      | Tabellen                              | Ersetzt                       |
-- |----|--------------|---------------------------------------|-------------------------------|
-- | 1  | system       | system_identity, system_config        | identity.json, configs        |
-- | 2  | skills       | skills                                | skill_registry + SKILL.md     |
-- | 3  | tasks        | tasks, tasks_fts                      | task-manager.json, queues     |
-- | 4  | tools        | tools                                 | data_tools, external_tools    |
-- | 5  | connections  | connections                           | communication_registry        |
-- | 6  | memory       | memory_lessons, _context, _sessions   | lessons, sources, sessions    |
-- | 7  | files        | files_truth, files_trash              | directory_watcher, papierkorb |
-- | 8  | automation   | automation_triggers, _routines, _inj  | triggers, micro-routines      |
-- | 9  | monitoring   | monitor_tokens, _success, _processes  | token-watcher, success-watcher|
-- | 10 | agents       | agents, agent_synergies               | agents/registry, synergy_map  |
-- | 11 | languages    | languages_config, _translations, _dict| dictionary.json, locales/     |
--
-- VIEWS (12 Stück):
-- | View                    | Zweck                                    |
-- |-------------------------|------------------------------------------|
-- | v_active_skills         | Aktive Skills nach Kategorie             |
-- | v_pending_tasks         | Offene Tasks nach Priorität              |
-- | v_delegatable_tasks     | Tasks mit Delegations-Empfehlung         |
-- | v_available_tools       | Verfügbare Tools nach Typ                |
-- | v_active_lessons        | Aktive Lessons nach Severity             |
-- | v_trash_expiring        | Papierkorb mit Ablaufdatum               |
-- | v_token_usage_week      | Token-Verbrauch letzte 7 Tage            |
-- | v_success_overview      | Erfolgsraten nach Entity-Typ             |
-- | v_actor_status          | 6-Kategorien Akteure-Status              |
-- | v_active_agents         | Aktive Agenten                           |
-- | v_agent_synergies       | Agenten-Synergien (lesbar)               |
-- | v_translations_de       | Deutsche Übersetzungen                   |
--
-- VORTEILE:
-- - Ein Ort für alles (bach.db)
-- - SQL-Abfragen statt JSON-Parsing
-- - Referenzielle Integrität
-- - Volltextsuche (FTS5)
-- - Views für häufige Abfragen
-- - Transaktionen für Konsistenz
-- - Token-Tracking mit Kostenberechnung
-- - Erfolgs-Metriken für alle Entities
-- - 6-Kategorien Akteure-Modell integriert
-- - Agenten mit Synergien
-- - Mehrsprachigkeit eingebaut
--
-- CLI-ZUGRIFF:
--   python bach.py --db status
--   python bach.py --db query "SELECT * FROM v_pending_tasks"
--   python bach.py --tasks list
--   python bach.py --tokens status
--   python bach.py --agents list
--   python bach.py --translate "Hello" --to de
--
-- ============================================================

-- Token-Übersicht letzte 7 Tage
CREATE VIEW IF NOT EXISTS v_token_usage_week AS
SELECT 
    date(timestamp) as day,
    SUM(tokens_total) as total_tokens,
    SUM(cost_eur) as total_cost_eur,
    SUM(delegations_accepted) as delegations,
    SUM(tokens_saved) as saved
FROM monitor_tokens
WHERE timestamp >= date('now', '-7 days')
GROUP BY date(timestamp)
ORDER BY day DESC;

-- Erfolgsraten nach Entity
CREATE VIEW IF NOT EXISTS v_success_overview AS
SELECT 
    entity_type,
    COUNT(*) as count,
    AVG(success_rate) as avg_success_rate,
    SUM(successes) as total_successes,
    SUM(failures) as total_failures
FROM monitor_success
GROUP BY entity_type
ORDER BY avg_success_rate DESC;

-- Akteure-Status (6-Kategorien-Modell)
CREATE VIEW IF NOT EXISTS v_actor_status AS
SELECT 
    actor_type,
    actor_name,
    status,
    tasks_completed,
    error_count,
    last_activity
FROM monitor_processes
ORDER BY 
    CASE actor_type
        WHEN 'operating_ai' THEN 1
        WHEN 'user' THEN 2
        WHEN 'integrated_tool' THEN 3
        WHEN 'online_tool' THEN 4
        WHEN 'other_ai' THEN 5
        WHEN 'os' THEN 6
    END;



-- ============================================================
-- 12. DISTRIBUTION - Tiers, Releases, Snapshots
-- ============================================================
-- Basiert auf: user/IDENTITY.md, tools/TRANSFER/distribution_system.py
-- Ermöglicht: System vs. User-Content Unterscheidung, Siegel-System,
--             offizielle Releases, Forks, Point-in-Time Recovery

-- Tier-Klassifizierung (4 Stufen)
CREATE TABLE IF NOT EXISTS tiers (
    id INTEGER PRIMARY KEY,           -- 0, 1, 2, 3
    name TEXT UNIQUE NOT NULL,        -- 'kernel', 'core', 'extension', 'userdata'
    description TEXT,
    
    -- Schutz-Level
    protection_level TEXT DEFAULT 'medium',  -- 'critical', 'high', 'medium', 'low'
    
    -- Berechtigungen nach Modus
    developer_can_modify BOOLEAN DEFAULT 1,
    user_can_modify BOOLEAN DEFAULT 0,
    learn_can_modify BOOLEAN DEFAULT 0,
    
    -- Release-Einstellungen
    include_in_standard BOOLEAN DEFAULT 1,    -- Standard-Installation
    include_in_minimal BOOLEAN DEFAULT 0,    -- Minimal-Installation
    include_in_snapshot BOOLEAN DEFAULT 1    -- Bei Snapshots
);

-- 4-Tier System einfügen
INSERT OR IGNORE INTO tiers (id, name, description, protection_level, 
                             developer_can_modify, user_can_modify, learn_can_modify,
                             include_in_standard, include_in_minimal, include_in_snapshot) VALUES
(0, 'kernel', 'Minimaler Kern - ohne das läuft nichts', 'critical', 1, 0, 0, 1, 1, 1),
(1, 'core', 'Standard-Komponenten für volle Funktionalität', 'high', 1, 0, 1, 1, 0, 1),
(2, 'extension', 'Optionale Zusatzfunktionen', 'medium', 1, 1, 1, 0, 0, 1),
(3, 'userdata', 'Benutzer-spezifische Daten', 'low', 1, 1, 1, 0, 0, 0);


-- Releases für Distribution und Versionierung
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    
    -- Version
    version TEXT NOT NULL,               -- 'X.Y.Z' oder 'X.Y.Z-source.N'
    version_major INTEGER,
    version_minor INTEGER,
    version_patch INTEGER,
    
    -- Typ
    type TEXT NOT NULL,                  -- 'standard', 'minimal', 'full', 'snapshot', 'fork'
    name TEXT,                           -- Optionaler Name ('BACH-Bioinformatik')
    
    -- Quelle (für Versionssuffix)
    source TEXT DEFAULT 'release',       -- 'release', 'dev', 'learn', 'evo', 'user', 'fork'
    source_sequence INTEGER DEFAULT 0,   -- Laufende Nummer innerhalb source
    
    -- Integrität
    kernel_hash TEXT,                    -- SHA256 über Tier-0-Dateien
    total_hash TEXT,                     -- SHA256 über alle enthaltenen Dateien
    
    -- Manifest
    manifest TEXT,                       -- JSON: {skills:[], tools:[], files:[]}
    file_count INTEGER,
    total_size_bytes INTEGER,
    
    -- Status
    is_current BOOLEAN DEFAULT 0,        -- Aktuelle installierte Version
    is_stable BOOLEAN DEFAULT 0,         -- Als stabil markiert
    
    -- Meta
    created_at TEXT NOT NULL,
    created_by TEXT,                     -- 'developer', 'system', 'learn'
    notes TEXT,
    changelog TEXT                       -- Was hat sich geändert
);

CREATE INDEX IF NOT EXISTS idx_releases_version ON releases(version);
CREATE INDEX IF NOT EXISTS idx_releases_current ON releases(is_current);


-- Snapshots für Point-in-Time Recovery
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    
    -- Identifikation
    name TEXT NOT NULL,
    description TEXT,
    
    -- Speicherort
    path TEXT NOT NULL,                  -- Pfad zum Snapshot (lokal oder NAS)
    format TEXT DEFAULT 'zip',           -- 'zip', 'tar.gz', 'directory'
    
    -- Inhalt
    includes_tiers TEXT DEFAULT '[0,1,2]',  -- JSON: welche Tiers enthalten
    includes_userdata BOOLEAN DEFAULT 0,
    
    -- Größe
    size_bytes INTEGER,
    file_count INTEGER,
    
    -- Integrität
    kernel_hash TEXT,
    checksum TEXT,                       -- SHA256 des gesamten Snapshots
    
    -- Timestamps
    created_at TEXT NOT NULL,
    source_version TEXT,                 -- Version zum Zeitpunkt des Snapshots
    
    -- Retention
    retention_days INTEGER DEFAULT 90,
    expires_at TEXT,
    
    -- Status
    status TEXT DEFAULT 'active',        -- 'active', 'archived', 'restoring', 'deleted'
    restored_at TEXT,
    restored_count INTEGER DEFAULT 0,
    
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status);
CREATE INDEX IF NOT EXISTS idx_snapshots_expires ON snapshots(expires_at);


-- ============================================================
-- 13. MEMORY ERWEITERT - Working Memory, Facts, Communication
-- ============================================================
-- Basiert auf: Generator os_generator_v3.py _memory/ Struktur
-- Schließt die Lücken im Memory-System

-- Working Memory (Scratchpad, Active Context, Open Loops)
-- Singleton-Tabelle für aktuelle Session
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton
    
    -- Scratchpad (temporäre Notizen während Session)
    scratchpad TEXT,                     -- Freitext-Notizen
    scratchpad_updated_at TEXT,
    
    -- Active Context (was ist gerade relevant)
    active_context TEXT,                 -- JSON: {project: '', task: '', focus: ''}
    context_started_at TEXT,
    
    -- Open Loops (angefangene aber nicht abgeschlossene Dinge)
    open_loops TEXT,                     -- JSON-Array: [{task: '', status: '', notes: ''}]
    
    -- Current Intent (was will der User gerade erreichen)
    current_intent TEXT,
    intent_confidence REAL,              -- 0.0 - 1.0
    
    -- Session-Kontext
    session_id TEXT,
    session_started_at TEXT,
    last_activity_at TEXT,
    
    -- Für Continuation nach Unterbrechung
    continuation_point TEXT,             -- Wo weitermachen nach Timeout/Crash
    continuation_context TEXT,           -- JSON mit relevantem Kontext
    
    updated_at TEXT
);

-- Singleton initialisieren
INSERT OR IGNORE INTO memory_working (id, updated_at) VALUES (1, datetime('now'));


-- Semantic Facts (Wissen über User, Projekte, System)
CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY,
    
    -- Klassifizierung
    category TEXT NOT NULL,              -- 'user', 'project', 'system', 'external'
    subcategory TEXT,                    -- 'preference', 'constraint', 'capability', 'history'
    
    -- Der Fakt selbst
    fact TEXT NOT NULL,                  -- Die Information
    fact_key TEXT,                       -- Optionaler Schlüssel für schnellen Zugriff
    
    -- Metadaten
    confidence REAL DEFAULT 1.0,         -- 0.0 - 1.0, wie sicher ist der Fakt
    source TEXT,                         -- Woher stammt die Info: 'user_stated', 'inferred', 'observed'
    source_session TEXT,                 -- Session-ID wo der Fakt entstand
    
    -- Beziehungen
    related_entities TEXT,               -- JSON-Array: ['project_x', 'tool_y']
    related_facts TEXT,                  -- JSON-Array von IDs verwandter Fakten
    
    -- Trigger (wann den Fakt einblenden)
    trigger_words TEXT,                  -- JSON-Array
    trigger_contexts TEXT,               -- JSON-Array: ['coding', 'writing', 'research']
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    is_verified BOOLEAN DEFAULT 0,       -- Vom User bestätigt
    times_used INTEGER DEFAULT 0,
    
    -- Timestamps
    created_at TEXT,
    verified_at TEXT,
    last_used_at TEXT,
    expires_at TEXT                      -- Optional: Fakten können verfallen
);

CREATE INDEX IF NOT EXISTS idx_facts_category ON memory_facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_key ON memory_facts(fact_key);
CREATE INDEX IF NOT EXISTS idx_facts_active ON memory_facts(is_active);

-- Beispiel-Fakten einfügen
INSERT OR IGNORE INTO memory_facts (category, subcategory, fact, fact_key, confidence, source, is_verified) VALUES
('user', 'preference', 'Bevorzugt direkte Dateispeicherung auf PC statt Container', 'file_preference', 1.0, 'user_stated', 1),
('user', 'work', 'Arbeitet in Autismus-Förderung', 'profession', 1.0, 'user_stated', 1),
('user', 'work', 'Erstellt ICF-basierte Gutachten', 'job_task', 1.0, 'user_stated', 1),
('system', 'constraint', 'NAS (NAS-HOST) nur im Heimnetzwerk erreichbar', 'nas_availability', 1.0, 'user_stated', 1),
('system', 'path', 'Software-Projekte: <lokaler Software-Pfad>', 'dev_path', 1.0, 'user_stated', 1);


-- Async Communication (Inbox/Outbox für Delegation und Multi-AI)
CREATE TABLE IF NOT EXISTS comm_messages (
    id INTEGER PRIMARY KEY,
    
    -- Richtung
    direction TEXT NOT NULL,             -- 'inbox', 'outbox', 'internal'
    
    -- Absender/Empfänger (6-Kategorien-Modell)
    sender_type TEXT NOT NULL,           -- 'operating_ai', 'other_ai', 'user', 'tool', 'system'
    sender_name TEXT NOT NULL,
    recipient_type TEXT NOT NULL,
    recipient_name TEXT NOT NULL,
    
    -- Nachricht
    subject TEXT,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',    -- 'text', 'json', 'markdown', 'command'
    
    -- Kontext
    related_task_id INTEGER,             -- FK zu tasks
    related_session_id TEXT,
    thread_id TEXT,                      -- Für Konversations-Threads
    reply_to_id INTEGER,                 -- FK für Antworten
    
    -- Priorität und Status
    priority TEXT DEFAULT 'normal',      -- 'urgent', 'high', 'normal', 'low'
    status TEXT DEFAULT 'pending',       -- 'pending', 'read', 'processing', 'completed', 'failed', 'archived'
    
    -- Timestamps
    created_at TEXT NOT NULL,
    read_at TEXT,
    processed_at TEXT,
    
    -- Ergebnis (für Delegationen)
    result TEXT,
    result_status TEXT,                  -- 'success', 'partial', 'failed'
    
    -- Metadaten
    metadata TEXT,                       -- JSON für zusätzliche Infos
    
    FOREIGN KEY (related_task_id) REFERENCES tasks(id),
    FOREIGN KEY (reply_to_id) REFERENCES comm_messages(id)
);

CREATE INDEX IF NOT EXISTS idx_comm_direction ON comm_messages(direction);
CREATE INDEX IF NOT EXISTS idx_comm_status ON comm_messages(status);
CREATE INDEX IF NOT EXISTS idx_comm_thread ON comm_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_comm_priority ON comm_messages(priority);


-- Memory Consolidation (für spätere Merge/Cleanup-Funktionen)
CREATE TABLE IF NOT EXISTS memory_consolidation (
    id INTEGER PRIMARY KEY,
    
    -- Was konsolidieren
    source_type TEXT NOT NULL,           -- 'fact', 'lesson', 'session'
    source_ids TEXT NOT NULL,            -- JSON-Array der zu konsolidierenden IDs
    
    -- Status
    status TEXT DEFAULT 'pending',       -- 'pending', 'processing', 'completed', 'failed'
    
    -- Ergebnis
    result_type TEXT,                    -- 'merged', 'deduplicated', 'archived'
    result_id INTEGER,                   -- ID des Ergebnis-Eintrags
    
    -- Meta
    created_at TEXT NOT NULL,
    processed_at TEXT,
    notes TEXT
);


-- ============================================================
-- 14. SCHEMA-ERWEITERUNGEN für bestehende Tabellen
-- ============================================================
-- Hinweis: SQLite ALTER TABLE ist eingeschränkt.
-- Bei bestehenden DBs müssen diese Spalten manuell hinzugefügt werden.
-- Bei neuen DBs werden sie direkt erstellt.

-- Für skills: tier_id und is_system hinzufügen
-- ALTER TABLE skills ADD COLUMN tier_id INTEGER DEFAULT 1 REFERENCES tiers(id);
-- ALTER TABLE skills ADD COLUMN is_system BOOLEAN DEFAULT 0;

-- Für tools: tier_id und is_system hinzufügen
-- ALTER TABLE tools ADD COLUMN tier_id INTEGER DEFAULT 1 REFERENCES tiers(id);
-- ALTER TABLE tools ADD COLUMN is_system BOOLEAN DEFAULT 0;

-- Für files_truth: tier_id hinzufügen
-- ALTER TABLE files_truth ADD COLUMN tier_id INTEGER REFERENCES tiers(id);

-- Für automation_triggers: tier_id hinzufügen (Kernel-Level)
-- ALTER TABLE automation_triggers ADD COLUMN tier_id INTEGER DEFAULT 0 REFERENCES tiers(id);

-- Für automation_routines: tier_id hinzufügen (Kernel-Level)
-- ALTER TABLE automation_routines ADD COLUMN tier_id INTEGER DEFAULT 0 REFERENCES tiers(id);


-- ============================================================
-- NEUE VIEWS für erweiterte Bereiche
-- ============================================================

-- Skills mit Tier-Info
CREATE VIEW IF NOT EXISTS v_skills_by_tier AS
SELECT s.*, t.name as tier_name, t.protection_level
FROM skills s
LEFT JOIN tiers t ON s.tier_id = t.id
ORDER BY COALESCE(s.tier_id, 1), s.name;

-- System vs. User Content Übersicht
CREATE VIEW IF NOT EXISTS v_system_content AS
SELECT 'skill' as entity_type, name, tier_id, is_system, is_active
FROM skills WHERE COALESCE(tier_id, 1) <= 1 OR COALESCE(is_system, 0) = 1
UNION ALL
SELECT 'tool', name, tier_id, is_system, is_available
FROM tools WHERE COALESCE(tier_id, 1) <= 1 OR COALESCE(is_system, 0) = 1
ORDER BY tier_id, entity_type, name;

-- Aktuelle Working Memory
CREATE VIEW IF NOT EXISTS v_working_memory AS
SELECT 
    scratchpad,
    active_context,
    open_loops,
    current_intent,
    session_id,
    continuation_point,
    updated_at
FROM memory_working
WHERE id = 1;

-- Aktive Fakten nach Kategorie
CREATE VIEW IF NOT EXISTS v_active_facts AS
SELECT category, subcategory, fact, fact_key, confidence, source
FROM memory_facts
WHERE is_active = 1
ORDER BY category, confidence DESC;

-- User-Fakten (für Personalisierung)
CREATE VIEW IF NOT EXISTS v_user_facts AS
SELECT fact_key, fact, confidence, is_verified
FROM memory_facts
WHERE category = 'user' AND is_active = 1
ORDER BY confidence DESC;

-- Offene Kommunikation (Inbox)
CREATE VIEW IF NOT EXISTS v_inbox_pending AS
SELECT id, sender_name, subject, priority, created_at
FROM comm_messages
WHERE direction = 'inbox' AND status = 'pending'
ORDER BY 
    CASE priority 
        WHEN 'urgent' THEN 1 
        WHEN 'high' THEN 2 
        WHEN 'normal' THEN 3 
        ELSE 4 
    END,
    created_at;

-- Delegations-Queue (wartende Antworten)
CREATE VIEW IF NOT EXISTS v_delegation_queue AS
SELECT 
    cm.id,
    cm.recipient_name as delegated_to,
    cm.subject,
    cm.status,
    cm.created_at,
    t.title as task_title
FROM comm_messages cm
LEFT JOIN tasks t ON cm.related_task_id = t.id
WHERE cm.direction = 'outbox' 
  AND cm.status IN ('pending', 'processing')
ORDER BY cm.created_at;

-- Snapshots mit Ablauf
CREATE VIEW IF NOT EXISTS v_snapshots_expiring AS
SELECT 
    name, 
    path, 
    created_at, 
    expires_at,
    julianday(expires_at) - julianday('now') as days_remaining,
    size_bytes,
    status
FROM snapshots
WHERE status = 'active' AND expires_at IS NOT NULL
ORDER BY expires_at;

-- Release-Historie
CREATE VIEW IF NOT EXISTS v_release_history AS
SELECT 
    version,
    type,
    name,
    source,
    is_current,
    is_stable,
    created_at,
    notes
FROM releases
ORDER BY created_at DESC;

-- Tier-Statistik
CREATE VIEW IF NOT EXISTS v_tier_statistics AS
SELECT 
    t.id as tier_id,
    t.name as tier_name,
    t.protection_level,
    COUNT(DISTINCT s.id) as skill_count,
    COUNT(DISTINCT tl.id) as tool_count
FROM tiers t
LEFT JOIN skills s ON s.tier_id = t.id
LEFT JOIN tools tl ON tl.tier_id = t.id
GROUP BY t.id, t.name, t.protection_level
ORDER BY t.id;


-- ============================================================
-- AKTUALISIERTE ZUSAMMENFASSUNG
-- ============================================================
--
-- 14 BEREICHE, 30 TABELLEN:
--
-- | #  | Bereich        | Tabellen                                | Neu in v1.1             |
-- |----|----------------|-----------------------------------------|-------------------------|
-- | 1  | system         | system_identity, system_config          |                         |
-- | 2  | skills         | skills                                  | +tier_id, +is_system    |
-- | 3  | tasks          | tasks, tasks_fts                        |                         |
-- | 4  | tools          | tools                                   | +tier_id, +is_system    |
-- | 5  | connections    | connections                             |                         |
-- | 6  | memory         | memory_lessons, _context, _sessions     |                         |
-- | 7  | files          | files_truth, files_trash                | +tier_id                |
-- | 8  | automation     | automation_triggers, _routines, _inj    | +tier_id                |
-- | 9  | monitoring     | monitor_tokens, _success, _processes    |                         |
-- | 10 | agents         | agents, agent_synergies                 |                         |
-- | 11 | languages      | languages_config, _translations, _dict  |                         |
-- | 12 | distribution   | tiers, releases, snapshots              | ✅ NEU                  |
-- | 13 | memory_ext     | memory_working, memory_facts            | ✅ NEU                  |
-- | 14 | communication  | comm_messages, memory_consolidation     | ✅ NEU                  |
--
-- NEUE VIEWS (10 Stück):
-- | View                    | Zweck                                    |
-- |-------------------------|------------------------------------------|
-- | v_skills_by_tier        | Skills mit Tier-Klassifizierung          |
-- | v_system_content        | System vs. User Content                  |
-- | v_working_memory        | Aktuelle Session-Kontext                 |
-- | v_active_facts          | Aktive semantische Fakten                |
-- | v_user_facts            | User-bezogene Fakten                     |
-- | v_inbox_pending         | Offene Nachrichten                       |
-- | v_delegation_queue      | Wartende Delegationen                    |
-- | v_snapshots_expiring    | Snapshots mit Ablaufdatum                |
-- | v_release_history       | Release-Historie                         |
-- | v_tier_statistics       | Statistik pro Tier                       |
--
-- NEUE FEATURES:
-- ✅ 4-Tier System (Kernel, Core, Extension, UserData)
-- ✅ Siegel-System (bereits in system_identity)
-- ✅ Release-Management mit Versionierung
-- ✅ Snapshots für Point-in-Time Recovery
-- ✅ Working Memory (Scratchpad, Active Context, Open Loops)
-- ✅ Semantic Facts (Wissen über User, Projekte, System)
-- ✅ Async Communication (Inbox/Outbox für Delegation)
-- ✅ Memory Consolidation (für spätere Merge-Funktionen)
--
-- CLI-ZUGRIFF (geplant):
--   bach --dist status        # Siegel, Version, Tier-Statistik
--   bach --dist verify        # Siegel prüfen
--   bach --dist release       # Release erstellen
--   bach --dist snapshot      # Snapshot erstellen
--   bach --memory working     # Working Memory anzeigen
--   bach --memory facts       # Fakten auflisten
--   bach --comm inbox         # Inbox anzeigen
--   bach --comm send          # Nachricht senden
--
-- ============================================================

-- ============================================================
-- 12. ERWEITERUNGEN (INTEG_004) - Fehlende Tabellen
-- ============================================================
-- Erstellt: 2026-01-23
-- Task: #267 - DB-Schema erweitern
-- ============================================================

-- TABLE: boot_checks
CREATE TABLE IF NOT EXISTS boot_checks (
    id INTEGER PRIMARY KEY,
    check_name TEXT NOT NULL,
    check_type TEXT,
    priority INTEGER DEFAULT 50,
    enabled INTEGER DEFAULT 1,
    last_run TIMESTAMP,
    last_result TEXT,
    config JSON
);

-- TABLE: partner_recognition
CREATE TABLE IF NOT EXISTS partner_recognition (
    id INTEGER PRIMARY KEY,
    partner_name TEXT NOT NULL UNIQUE,
    partner_type TEXT NOT NULL,         -- 'api', 'local', 'human'
    api_endpoint TEXT,                  -- URL oder Pfad
    capabilities JSON,                  -- Was kann der Partner?
    cost_tier INTEGER DEFAULT 2,        -- 1=kostenlos, 2=guenstig, 3=teuer
    token_zone TEXT DEFAULT 'zone_1',   -- zone_1 bis zone_4
    priority INTEGER DEFAULT 50,        -- Hoeher = bevorzugt
    status TEXT DEFAULT 'active',       -- 'active', 'inactive', 'unavailable'
    last_used TIMESTAMP,
    success_rate REAL DEFAULT 1.0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TABLE: interaction_protocols
CREATE TABLE IF NOT EXISTS interaction_protocols (
    id INTEGER PRIMARY KEY,
    protocol_name TEXT NOT NULL UNIQUE,
    protocol_type TEXT NOT NULL,        -- 'delegation', 'query', 'sync', 'escalation', 'feedback'
    description TEXT,
    request_format JSON,                -- Schema fuer Anfragen
    response_format JSON,               -- Schema fuer Antworten
    timeout_seconds INTEGER DEFAULT 60,
    retry_count INTEGER DEFAULT 3,
    applicable_partners JSON,           -- Welche Partner unterstuetzen dieses Protokoll
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TABLE: delegation_rules
CREATE TABLE IF NOT EXISTS delegation_rules (
    id INTEGER PRIMARY KEY,
    rule_name TEXT NOT NULL UNIQUE,
    zone TEXT NOT NULL,                -- 'zone_1', 'zone_2', 'zone_3', 'zone_4'
    token_range_start INTEGER,         -- Prozent Token verbraucht (Start)
    token_range_end INTEGER,           -- Prozent Token verbraucht (Ende)
    allowed_partners JSON,             -- Partner in dieser Zone erlaubt
    preferred_partner TEXT,            -- Bevorzugter Partner
    delegation_strategy TEXT,          -- 'all', 'local_only', 'cheap_only', 'emergency'
    max_delegations INTEGER,           -- Max Delegationen pro Session
    description TEXT,
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TABLE: session_snapshots
CREATE TABLE IF NOT EXISTS session_snapshots (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    snapshot_data JSON,
    working_memory JSON,
    open_tasks JSON,
    active_files JSON,
    token_usage INTEGER,
    context_hash TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
    name TEXT,
    UNIQUE(session_id, snapshot_type, created_at)
);

-- TABLE: tool_patterns
CREATE TABLE IF NOT EXISTS tool_patterns (
    id INTEGER PRIMARY KEY,
    pattern_name TEXT NOT NULL UNIQUE,
    pattern_type TEXT NOT NULL,         
    keywords JSON,                       
    problem_patterns JSON,               
    suggested_tools JSON,                
    confidence_threshold REAL DEFAULT 0.7,
    priority INTEGER DEFAULT 50,
    usage_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TABLE: memory_working
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('scratchpad', 'context', 'loop', 'note')),
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    tags TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- TABLE: memory_facts
CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK(category IN ('user', 'project', 'system', 'domain')),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'text',  -- 'text', 'json', 'number', 'date'
    confidence REAL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);

-- TABLE: bach_agents (Advanced Agent Model)
CREATE TABLE IF NOT EXISTS bach_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    type TEXT DEFAULT 'boss',
    category TEXT,
    description TEXT,
    skill_path TEXT,
    user_data_folder TEXT,
    parent_agent_id INTEGER,
    is_active INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 50,
    requires_setup INTEGER DEFAULT 0,
    setup_completed INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    last_used TEXT,
    version TEXT DEFAULT '1.0.0',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- TABLE: bach_experts (Expert Skills)
CREATE TABLE IF NOT EXISTS bach_experts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    description TEXT,
    skill_path TEXT,
    user_data_folder TEXT,
    domain TEXT,
    capabilities TEXT,
    is_active INTEGER DEFAULT 1,
    requires_db INTEGER DEFAULT 0,
    requires_files INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    last_used TEXT,
    version TEXT DEFAULT '1.0.0',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 15. ATI SCANNER - Tool Registry und Tasks
-- ============================================================
-- Migriert von: schema_user_v2.sql (user.db)
-- Zweck: Externe Software-Projekte scannen und Tasks verwalten
-- ============================================================

-- Tool-Registry (externe Software-Projekte)
CREATE TABLE IF NOT EXISTS ati_tool_registry (
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

CREATE INDEX IF NOT EXISTS idx_ati_tool_registry_status ON ati_tool_registry(status);
CREATE INDEX IF NOT EXISTS idx_ati_tool_registry_name ON ati_tool_registry(name);

-- ATI Tasks (gescannte Aufgaben aus AUFGABEN.txt)
CREATE TABLE IF NOT EXISTS ati_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    tool_path TEXT NOT NULL,
    task_text TEXT NOT NULL,
    aufwand TEXT DEFAULT 'mittel' CHECK(aufwand IN ('niedrig', 'mittel', 'hoch')),
    status TEXT DEFAULT 'offen' CHECK(status IN ('offen', 'in_arbeit', 'erledigt', 'blockiert')),
    priority_score REAL DEFAULT 0,
    source_file TEXT NOT NULL,
    line_number INTEGER,
    file_hash TEXT,
    last_modified TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_synced INTEGER DEFAULT 1,
    tags TEXT,
    depends_on TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ati_tasks_tool ON ati_tasks(tool_name);
CREATE INDEX IF NOT EXISTS idx_ati_tasks_status ON ati_tasks(status);
CREATE INDEX IF NOT EXISTS idx_ati_tasks_priority ON ati_tasks(priority_score DESC);

-- Scan-Konfiguration
CREATE TABLE IF NOT EXISTS ati_scan_config (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    category TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scan-Protokoll
CREATE TABLE IF NOT EXISTS ati_scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    tools_scanned INTEGER DEFAULT 0,
    tasks_found INTEGER DEFAULT 0,
    tasks_new INTEGER DEFAULT 0,
    tasks_updated INTEGER DEFAULT 0,
    tasks_removed INTEGER DEFAULT 0,
    triggered_by TEXT DEFAULT 'manual',
    errors TEXT
);

-- Default Scan-Konfiguration
INSERT OR IGNORE INTO ati_scan_config (key, value, category, description) VALUES
    ('base_path', '"{USER_DEV_PATH}"', 'scan', 'Basis-Pfad fuer Tool-Scans'),
    ('scan_folders', '["SINGLE", "SUITEN", "TOOLS"]', 'scan', 'Zu scannende Unterordner'),
    ('task_files', '["AUFGABEN.txt", "Aufgaben.txt", "AUFGABEN.TXT", "TODO.md", "AUFGABEN.md", "ROADMAP.md", "DONE.md"]', 'scan', 'Task-Dateinamen'),
    ('test_files', '["TEST.txt", "Test.txt"]', 'scan', 'Test-Dateinamen'),
    ('feedback_files', '["TESTERGEBNIS.txt", "AENDERUNGEN.txt"]', 'scan', 'Feedback-Dateinamen'),
    ('ignore_folders', '["dist", "__pycache__", ".git", "venv", "node_modules", "_alt", "_archive"]', 'scan', 'Ignorierte Ordner');

-- View: Offene ATI-Tasks nach Prioritaet
CREATE VIEW IF NOT EXISTS v_ati_open_tasks AS
SELECT
    t.id,
    t.tool_name,
    t.task_text,
    t.aufwand,
    t.priority_score,
    t.status,
    r.path as tool_path
FROM ati_tasks t
LEFT JOIN ati_tool_registry r ON t.tool_name = r.name
WHERE t.status IN ('offen', 'in_arbeit')
ORDER BY t.priority_score DESC;

-- View: Tool-Uebersicht mit Task-Statistik
CREATE VIEW IF NOT EXISTS v_ati_tool_overview AS
SELECT
    r.name,
    r.path,
    r.status,
    r.task_count,
    r.last_scan,
    (SELECT COUNT(*) FROM ati_tasks t WHERE t.tool_name = r.name AND t.status = 'offen') as open_tasks
FROM ati_tool_registry r
WHERE r.status = 'aktiv'
ORDER BY r.task_count DESC;
