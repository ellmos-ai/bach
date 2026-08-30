-- ============================================================================
-- BACH Database Schema (Single Source of Truth)
-- ============================================================================
-- Generated from existing bach.db
-- All tables use CREATE TABLE IF NOT EXISTS for safety
--
-- Tables: 130 (SQ002a: +9 Dist-Tabellen, SQ002b: +release_manifest +known_instances, 2 VIEWs, SQ044: +bach_blobs +bach_blobs_fts +bach_blob_history, 2026-03-04)
-- ============================================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── SYSTEM ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS system_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        type TEXT DEFAULT 'string',
        category TEXT,
        description TEXT,
        updated_at TEXT,
        dist_type INTEGER DEFAULT 2  -- 2=CORE, 1=TEMPLATE, 0=USER
    );

CREATE TABLE IF NOT EXISTS system_identity (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        instance_id TEXT UNIQUE NOT NULL,
        instance_name TEXT,
        version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        seal_status TEXT DEFAULT 'intact',
        kernel_hash TEXT,
        last_verified TEXT,
        current_mode TEXT DEFAULT 'developer',
        last_boot TEXT,
        boot_count INTEGER DEFAULT 0
    );

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

CREATE TABLE IF NOT EXISTS distribution_manifest (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    dist_type INTEGER DEFAULT 2,
    template_hash TEXT,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ── SECRETS ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    description TEXT,
    source TEXT DEFAULT 'manual',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ── TASKS ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        category TEXT,
        priority TEXT DEFAULT 'P3',
        tags TEXT,
        status TEXT DEFAULT 'pending',
        estimated_minutes INTEGER,
        actual_minutes INTEGER,
        delegated_to TEXT,
        delegation_status TEXT,
        source_file TEXT,
        source_line INTEGER,
        is_recurring INTEGER DEFAULT 0,
        recurrence_pattern TEXT,
        next_occurrence TEXT,
        due_date TEXT,
        executable_command TEXT,
        created_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        updated_at TEXT
    , dist_type INTEGER DEFAULT 0, modified_by TEXT DEFAULT NULL, depends_on TEXT DEFAULT NULL, created_by TEXT DEFAULT 'user', assigned_to TEXT DEFAULT 'user', project TEXT, source TEXT, image_data TEXT);

CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT DEFAULT 'user',
    changed_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- ── MEMORY ──────────────────────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS memory_lessons (
        id INTEGER PRIMARY KEY,
        category TEXT NOT NULL,
        severity TEXT DEFAULT 'medium',
        title TEXT NOT NULL,
        problem TEXT,
        solution TEXT NOT NULL,
        related_tools TEXT,
        related_files TEXT,
        trigger_words TEXT,
        trigger_events TEXT,
        is_active INTEGER DEFAULT 1,
        times_shown INTEGER DEFAULT 0,
        last_shown TEXT,
        created_at TEXT,
        updated_at TEXT
    , dist_type INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS memory_sessions (
        id INTEGER PRIMARY KEY,
        session_id TEXT UNIQUE NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        summary TEXT,
        tasks_completed INTEGER DEFAULT 0,
        tasks_created INTEGER DEFAULT 0,
        tokens_used INTEGER,
        delegation_count INTEGER DEFAULT 0,
        continuation_context TEXT
    , dist_type INTEGER DEFAULT 0, is_compressed INTEGER DEFAULT 0, partner_id TEXT DEFAULT 'user');

CREATE TABLE IF NOT EXISTS memory_consolidation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    times_accessed INTEGER DEFAULT 0,
    last_accessed TIMESTAMP,
    weight REAL DEFAULT 0.5,
    decay_rate REAL DEFAULT 0.95,
    threshold REAL DEFAULT 0.2,
    status TEXT DEFAULT "active",
    consolidated_to INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_table, source_id)
);

CREATE TABLE IF NOT EXISTS memory_context (
        id INTEGER PRIMARY KEY,
        source_name TEXT UNIQUE NOT NULL,
        source_path TEXT,
        weight INTEGER DEFAULT 5,
        trigger_events TEXT,
        trigger_words TEXT,
        inject_on_match INTEGER DEFAULT 1,
        injection_template TEXT,
        is_active INTEGER DEFAULT 1,
        updated_at TEXT
    );

-- ── MESSAGES ────────────────────────────────────────────────────────────

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
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS comm_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL CHECK(direction IN ('inbox', 'outbox')),
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',  -- 'text', 'json', 'markdown'
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'read', 'processed', 'archived', 'failed')),
    parent_id INTEGER REFERENCES comm_messages(id),
    metadata TEXT,  -- JSON für zusätzliche Daten
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMP,
    processed_at TIMESTAMP
);

-- ── SESSIONS ────────────────────────────────────────────────────────────

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, name TEXT,
    UNIQUE(session_id, snapshot_type, created_at)
);

-- ── MONITORING ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS monitor_tokens (
        id INTEGER PRIMARY KEY,
        session_id TEXT,
        tokens_input INTEGER DEFAULT 0,
        tokens_output INTEGER DEFAULT 0,
        tokens_total INTEGER DEFAULT 0,
        budget_percent REAL,
        warning_triggered INTEGER DEFAULT 0,
        critical_triggered INTEGER DEFAULT 0,
        cost_usd REAL,
        exchange_rate REAL,
        cost_eur REAL,
        delegations_suggested INTEGER DEFAULT 0,
        delegations_accepted INTEGER DEFAULT 0,
        tokens_saved INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL
    , dist_type INTEGER DEFAULT 0, model TEXT);

CREATE TABLE IF NOT EXISTS monitor_processes (
        id INTEGER PRIMARY KEY,
        actor_type TEXT NOT NULL,
        actor_name TEXT NOT NULL,
        status TEXT DEFAULT 'idle',
        current_task_id INTEGER,
        tasks_completed INTEGER DEFAULT 0,
        last_activity TEXT,
        uptime_seconds INTEGER,
        error_count INTEGER DEFAULT 0,
        last_error TEXT,
        last_error_at TEXT,
        updated_at TEXT
    );

CREATE TABLE IF NOT EXISTS monitor_success (
        id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        entity_name TEXT,
        attempts INTEGER DEFAULT 0,
        successes INTEGER DEFAULT 0,
        failures INTEGER DEFAULT 0,
        success_rate REAL,
        avg_duration_seconds REAL,
        last_success TEXT,
        last_failure TEXT,
        user_rating INTEGER,
        notes TEXT,
        updated_at TEXT
    , dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS monitor_pricing (
        id INTEGER PRIMARY KEY,
        model TEXT NOT NULL,
        input_price REAL NOT NULL,
        output_price REAL NOT NULL,
        valid_from TEXT NOT NULL,
        valid_until TEXT,
        source TEXT,
        updated_at TEXT
    );

-- ── AUTOMATION ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS automation_triggers (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        phrases TEXT NOT NULL,
        skill_name TEXT,
        action TEXT NOT NULL,
        priority INTEGER DEFAULT 50,
        is_active INTEGER DEFAULT 1,
        updated_at TEXT,
        dist_type INTEGER DEFAULT 2  -- 2=CORE, 1=TEMPLATE, 0=USER
    );

CREATE TABLE IF NOT EXISTS automation_routines (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        condition TEXT NOT NULL,
        condition_config TEXT,
        action TEXT NOT NULL,
        action_config TEXT,
        interval TEXT,
        last_run TEXT,
        next_run TEXT,
        priority INTEGER DEFAULT 50,
        is_active INTEGER DEFAULT 1,
        updated_at TEXT
    );

CREATE TABLE IF NOT EXISTS automation_injectors (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        trigger_words TEXT,
        trigger_events TEXT,
        response_template TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        times_triggered INTEGER DEFAULT 0,
        updated_at TEXT
    );

-- ── PROMPTS ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    purpose TEXT,
    text TEXT NOT NULL,
    tags TEXT,                       -- JSON array
    category TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompt_templates(id),
    version_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    tags TEXT,                       -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(prompt_id, version_number)
);

CREATE TABLE IF NOT EXISTS prompt_boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prompt_board_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES prompt_boards(id),
    prompt_id INTEGER NOT NULL REFERENCES prompt_templates(id),
    version_id INTEGER REFERENCES prompt_versions(id),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(board_id, prompt_id)
);

-- ── SCHEDULER ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    profile_name TEXT,               -- Aus SchedulerService/profiles.json
    description TEXT,
    job_type TEXT NOT NULL CHECK(job_type IN ('cron', 'interval', 'event', 'manual', 'chain')),
    schedule TEXT,                   -- Cron-Expression oder Interval
    command TEXT NOT NULL,           -- CLI-Befehl
    script_path TEXT,                -- Pfad zum Script
    arguments TEXT,                  -- Argumente
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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES scheduler_jobs(id),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    result TEXT CHECK(result IN ('success', 'failed', 'timeout', 'cancelled')),
    output TEXT,
    error TEXT,
    triggered_by TEXT DEFAULT 'schedule',  -- 'schedule', 'manual', 'event'
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS toolchains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    trigger_type TEXT CHECK(trigger_type IN ('manual', 'time', 'event', 'startup')) DEFAULT 'manual',
    trigger_value TEXT,
    steps_json TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    last_run TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS toolchain_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER,
    status TEXT,
    log TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_seconds REAL, finished_at TIMESTAMP, steps_completed INTEGER DEFAULT 0, steps_total INTEGER DEFAULT 0, output TEXT, error TEXT, triggered_by TEXT DEFAULT 'manual',
    FOREIGN KEY(chain_id) REFERENCES toolchains(id)
);

-- ── AGENTS & SKILLS ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        category TEXT,
        skill_path TEXT,
        script_path TEXT,
        config_path TEXT,
        version TEXT DEFAULT '1.0.0',
        description TEXT,
        capabilities TEXT,
        entry_command TEXT,
        requires_tools TEXT,
        is_active INTEGER DEFAULT 1,
        is_autonomous INTEGER DEFAULT 0,
        priority INTEGER DEFAULT 50,
        tasks_completed INTEGER DEFAULT 0,
        success_rate REAL,
        last_used TEXT,
        created_at TEXT,
        updated_at TEXT
    );

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
        , dashboard TEXT);

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
        , dashboard TEXT);

CREATE TABLE IF NOT EXISTS agent_expert_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES bach_agents(id),
    expert_id INTEGER NOT NULL REFERENCES bach_experts(id),
    is_primary INTEGER DEFAULT 0, dist_type INTEGER DEFAULT 2,         -- Haupt-Agent fuer diesen Experten
    UNIQUE(agent_id, expert_id)
);

CREATE TABLE IF NOT EXISTS agent_synergies (
        id INTEGER PRIMARY KEY,
        agent_a_id INTEGER NOT NULL,
        agent_b_id INTEGER NOT NULL,
        synergy_type TEXT NOT NULL,
        strength INTEGER DEFAULT 5,
        trigger_conditions TEXT,
        description TEXT,
        is_active INTEGER DEFAULT 1,
        UNIQUE(agent_a_id, agent_b_id, synergy_type)
    );

CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        category TEXT,
        path TEXT NOT NULL,
        version TEXT DEFAULT '1.0.0',
        description TEXT,
        is_active INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 50,
        trigger_phrases TEXT,
        created_at TEXT,
        updated_at TEXT
    , dist_type INTEGER DEFAULT 2, template_content TEXT, content TEXT, content_hash TEXT, operator_class TEXT);

CREATE TABLE IF NOT EXISTS tools (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        category TEXT,
        path TEXT,
        endpoint TEXT,
        command TEXT,
        description TEXT,
        version TEXT,
        capabilities TEXT,
        use_for TEXT,
        is_available INTEGER DEFAULT 1,
        last_check TEXT,
        error_count INTEGER DEFAULT 0,
        tokens_saved_percent INTEGER,
        speed TEXT,
        created_at TEXT,
        updated_at TEXT
    , dist_type INTEGER DEFAULT 2, template_content TEXT, content TEXT, content_hash TEXT);

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
, dist_type INTEGER DEFAULT 2);

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

CREATE TABLE IF NOT EXISTS user_data_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER REFERENCES bach_agents(id),
    expert_id INTEGER REFERENCES bach_experts(id),
    folder_path TEXT NOT NULL,            -- Relativer Pfad unter user/
    folder_type TEXT DEFAULT 'data' CHECK(folder_type IN ('data', 'archive', 'export', 'temp')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS hierarchy_types (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        color TEXT,
        icon TEXT,
        display_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

CREATE TABLE IF NOT EXISTS hierarchy_items (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        dashboard_url TEXT,
        status TEXT DEFAULT 'active',
        is_active INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 50,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        FOREIGN KEY (type) REFERENCES hierarchy_types(id)
    );

CREATE TABLE IF NOT EXISTS hierarchy_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id TEXT NOT NULL,
        parent_type TEXT NOT NULL,
        child_id TEXT NOT NULL,
        child_type TEXT NOT NULL,
        assignment_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(parent_id, child_id)
    );

-- ── SCANNER (ATI) ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ati_tasks (
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
, dist_type INTEGER DEFAULT 0, depends_on TEXT);

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

CREATE TABLE IF NOT EXISTS ati_scan_config (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    category TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS scan_config (
        key TEXT PRIMARY KEY,
        value TEXT,
        description TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

-- ── STEUER ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS steuer_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    name TEXT,
    beruf TEXT,
    branche TEXT,
    kategorien_json TEXT,          -- JSON: Typische Werbungskosten
    anbieter_regeln_json TEXT,     -- JSON: TEMU, Amazon etc.
    keywords_json TEXT,            -- JSON: Automatische Zuordnungen
    gemischte_defaults_json TEXT,  -- JSON: Standard-Anteile
    notizen TEXT,
    aktiv INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
, dist_type INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS steuer_dokumente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    steuerjahr INTEGER NOT NULL,
    dateiname TEXT NOT NULL,
    dateipfad TEXT,
    original_pfad TEXT,             -- Urspruenglicher Pfad vor Kopieren
    status TEXT NOT NULL,           -- ERFASST/NICHT_ERFASST/ZURUECKGESTELLT
    posten_anzahl INTEGER DEFAULT 0,
    quelle TEXT,                    -- UPLOAD/WATCHER/MANUELL
    erfasst_am TEXT,
    hochgeladen_am TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now')), anbieter TEXT, bemerkung TEXT, updated_at TEXT, dist_type INTEGER DEFAULT 0,
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, steuerjahr, dateiname)
);

CREATE TABLE IF NOT EXISTS steuer_posten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    steuerjahr INTEGER NOT NULL,
    postennr INTEGER NOT NULL,
    bezeichnung TEXT NOT NULL,
    datum TEXT,                     -- Rechnungsdatum (YYYY-MM-DD)
    typ TEXT DEFAULT 'Werbungskosten',  -- Werbungskosten/Versicherung/Nachweis
    rechnungsnr TEXT,
    rechnungssteller TEXT,
    dateiname TEXT,
    beschreibung TEXT,
    netto REAL,
    brutto REAL,
    bemerkung TEXT,
    liste TEXT NOT NULL,            -- WERBUNGSKOSTEN/GEMISCHTE/ZURUECKGESTELLT/VERWORFEN
    anteil REAL,                    -- Fuer GEMISCHTE (0.1-0.9)
    absetzbar_netto REAL,           -- Berechnet: anteil * netto
    absetzbar_brutto REAL,          -- Berechnet: anteil * brutto
    filtergrund TEXT,               -- Grund bei GEFILTERT
    dokument_id INTEGER,            -- Referenz auf steuer_dokumente
    version INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')), posten_id_str TEXT, belegnr INTEGER, dist_type INTEGER DEFAULT 0,
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    FOREIGN KEY (dokument_id) REFERENCES steuer_dokumente(id)
);

CREATE TABLE IF NOT EXISTS steuer_auswertung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    steuerjahr INTEGER NOT NULL,
    anzahl_posten INTEGER DEFAULT 0,
    anzahl_dokumente INTEGER DEFAULT 0,
    werbungskosten_netto REAL DEFAULT 0,
    werbungskosten_brutto REAL DEFAULT 0,
    gemischte_absetzbar_netto REAL DEFAULT 0,
    gemischte_absetzbar_brutto REAL DEFAULT 0,
    gesamt_absetzbar_netto REAL DEFAULT 0,
    gesamt_absetzbar_brutto REAL DEFAULT 0,
    letzte_aktualisierung TEXT DEFAULT (datetime('now')), dist_type INTEGER DEFAULT 0,
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, steuerjahr)
);

CREATE TABLE IF NOT EXISTS steuer_anbieter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    anbieter TEXT NOT NULL,         -- TEMU, Amazon, eBay, etc.
    besonderheit TEXT,
    workaround TEXT,
    hinweise TEXT,
    aktiv INTEGER DEFAULT 1, dist_type INTEGER DEFAULT 1,
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, anbieter)
);

CREATE TABLE IF NOT EXISTS steuer_watch_ordner (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    pfad TEXT NOT NULL,
    scan_modus TEXT DEFAULT 'bei_start',  -- bei_start/intervall/manuell
    intervall_min INTEGER,                 -- Minuten (wenn modus=intervall)
    nach_scan TEXT DEFAULT 'KOPIEREN',     -- KOPIEREN/VERSCHIEBEN/BELASSEN
    aktiv INTEGER DEFAULT 1,
    letzter_scan TEXT,
    created_at TEXT DEFAULT (datetime('now')), dist_type INTEGER DEFAULT 1,
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, pfad)
);

CREATE TABLE IF NOT EXISTS steuer_ocr_cache (
            belegnr INTEGER PRIMARY KEY,
            ocr_text TEXT,
            ocr_confidence REAL,
            ocr_timestamp TEXT,
            artikel_raw TEXT,
            gesamtsumme REAL
        , dist_type INTEGER DEFAULT 0);

-- ── ABO & FINANZEN ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS abo_subscriptions (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    anbieter TEXT NOT NULL,
                    kategorie TEXT,
                    betrag_monatlich REAL,
                    zahlungsintervall TEXT DEFAULT 'monatlich',
                    kuendigungslink TEXT,
                    erkannt_am TEXT,
                    bestaetigt INTEGER DEFAULT 0,
                    aktiv INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                , dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS abo_payments (
                    id INTEGER PRIMARY KEY,
                    subscription_id INTEGER REFERENCES abo_subscriptions(id),
                    posten_id INTEGER,
                    betrag REAL,
                    datum TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                , dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS abo_patterns (
                    id INTEGER PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    anbieter TEXT NOT NULL,
                    kategorie TEXT,
                    kuendigungslink TEXT,
                    dist_type INTEGER DEFAULT 2
                );

CREATE TABLE IF NOT EXISTS bank_accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT,               -- Zweck: Gehalt, Sparen, etc.
    account_number TEXT,
    bank_name TEXT,
    blz TEXT,
    iban TEXT,
    bic TEXT,
    holder_name TEXT,
    account_type TEXT,          -- Giro, Spar, Tagesgeld, Depot
    is_primary INTEGER DEFAULT 0,
    balance REAL,               -- Aktueller Kontostand (optional)
    balance_date TEXT,          -- Datum des Kontostands
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS credits (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT,
    bank_name TEXT,
    account_number TEXT,
    iban TEXT,
    original_amount REAL,
    interest_rate REAL,         -- Zinssatz in %
    payment_interval TEXT,      -- monthly, yearly
    payment_amount REAL,
    remaining_amount REAL,
    paid_amount REAL,
    start_date TEXT,
    end_date TEXT,
    status TEXT DEFAULT 'active', -- active, paid_off
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS irregular_costs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,              -- Steuer, Versicherung, Mitgliedschaft, etc.
    expected_month INTEGER,     -- 1-12, wann faellig
    expected_amount REAL,
    is_recurring INTEGER DEFAULT 1,
    last_paid_date TEXT,
    last_paid_amount REAL,
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS household_finances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date DATE NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('einnahme', 'ausgabe')),
    category TEXT,
    description TEXT,
    amount DECIMAL(10,2) NOT NULL,
    payment_method TEXT,                  -- 'Bar', 'Karte', 'Ueberweisung'
    is_recurring INTEGER DEFAULT 0,
    recurrence_interval TEXT,             -- 'monthly', 'yearly'
    tags TEXT,                            -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS fin_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Grunddaten
    name TEXT NOT NULL,                    -- z.B. "Netflix", "Vodafone"
    kategorie TEXT,                        -- Streaming, Wohnen, Sport, Internet, Mobilfunk
    anbieter TEXT,                         -- Vertragspartner
    kundennummer TEXT,
    vertragsnummer TEXT,
    
    -- Kosten
    betrag REAL,
    waehrung TEXT DEFAULT 'EUR',
    intervall TEXT,                        -- monatlich, jaehrlich, quartalsweise
    naechste_zahlung DATE,
    
    -- Laufzeiten & KÃ¼ndigung
    beginn_datum DATE,
    mindestlaufzeit_monate INTEGER,
    kuendigungsfrist_tage INTEGER, 
    verlaengerung_monate INTEGER,          
    ablauf_datum DATE,                     
    kuendigungs_status TEXT DEFAULT 'aktiv', -- aktiv, gekuendigt, pausiert
    
    -- VerknÃ¼pfungen
    dokument_pfad TEXT,
    web_login_url TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS fin_insurances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anbieter TEXT NOT NULL,                -- Allianz, HUK, etc.
    tarif_name TEXT,                       -- "Komfort Plus"
    police_nr TEXT UNIQUE,
    sparte TEXT NOT NULL,                  -- Haftpflicht, BU, KFZ, Hausrat, etc.
    status TEXT DEFAULT 'aktiv',           -- aktiv, gekuendigt, beitragsfrei
    
    -- Termine
    beginn_datum DATE,
    ablauf_datum DATE,
    kuendigungsfrist_monate INTEGER DEFAULT 3,
    verlaengerung_monate INTEGER DEFAULT 12,
    naechste_kuendigung DATE,              -- Berechnet oder manuell
    
    -- Finanzen
    beitrag REAL,
    zahlweise TEXT,                       -- monatlich, quartalsweise, jaehrlich
    steuer_relevant_typ TEXT,             -- Vorsorgeaufwendungen, etc.
    
    -- VerknÃ¼pfungen
    ordner_pfad TEXT,                      -- Pfad zu Scans
    notizen TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS fin_insurance_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insurance_id INTEGER REFERENCES fin_insurances(id),
    schadensdatum DATE,
    beschreibung TEXT,
    status TEXT DEFAULT 'offen',           -- offen, reguliert, abgelehnt
    betrag_gefordert REAL,
    betrag_gezahlt REAL,
    aktenzeichen_versicherung TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS financial_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES mail_accounts(id),
    message_id TEXT UNIQUE,                -- RFC Message-ID
    provider_id TEXT NOT NULL,             -- ID aus providers.json
    provider_name TEXT NOT NULL,           -- Anzeigename
    category TEXT NOT NULL,                -- telekommunikation, versicherung, etc.

    -- E-Mail Metadaten
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    email_date TIMESTAMP,
    received_at TIMESTAMP,

    -- Erkannte Daten
    document_type TEXT,                    -- rechnung, police, kontoauszug, etc.
    steuer_relevant INTEGER DEFAULT 0,
    steuer_typ TEXT,                       -- Werbungskosten, Versicherung, etc.

    -- Status
    status TEXT DEFAULT 'neu' CHECK(status IN ('neu', 'verarbeitet', 'exportiert', 'ignoriert')),
    has_attachment INTEGER DEFAULT 0,
    attachment_path TEXT,                  -- Pfad zur gespeicherten PDF

    -- Extrahierte Werte (durch LLM oder Regex)
    extracted_data TEXT,                   -- JSON mit allen extrahierten Feldern
    betrag REAL,                           -- Hauptbetrag (Brutto)
    betrag_netto REAL,
    rechnungsnummer TEXT,
    faelligkeit TEXT,
    zeitraum TEXT,

    -- Verknuepfung zu Steuer
    steuer_posten_id INTEGER,              -- Referenz auf steuer_posten falls uebernommen

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS financial_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL UNIQUE,
    provider_name TEXT NOT NULL,
    category TEXT NOT NULL,

    -- Abo-Details
    betrag_monatlich REAL,
    betrag_jaehrlich REAL,
    zahlungsintervall TEXT,                -- monatlich, quartalsweise, jaehrlich
    naechste_zahlung TEXT,
    kuendigungslink TEXT,

    -- Tracking
    letzte_rechnung_id INTEGER REFERENCES financial_emails(id),
    letzte_zahlung TEXT,
    zahlungen_count INTEGER DEFAULT 0,

    -- Status
    aktiv INTEGER DEFAULT 1,
    bestaetigt INTEGER DEFAULT 0,          -- Manuell bestaetigt
    steuer_relevant INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS financial_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jahr INTEGER NOT NULL,
    monat INTEGER,                          -- NULL = Jahreszusammenfassung

    -- Summen nach Kategorie (JSON)
    summen_kategorie TEXT,                  -- {"telekom": 45.00, "versicherung": 120.00, ...}

    -- Totals
    total_ausgaben REAL DEFAULT 0,
    total_steuer_relevant REAL DEFAULT 0,
    total_abos REAL DEFAULT 0,

    -- Counts
    anzahl_rechnungen INTEGER DEFAULT 0,
    anzahl_abos INTEGER DEFAULT 0,

    berechnet_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP, dist_type INTEGER DEFAULT 0,

    UNIQUE(jahr, monat)
);

CREATE TABLE IF NOT EXISTS insurance_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT,              -- Personen, Sach, Vorsorge, etc.
    description TEXT,
    when_useful TEXT,           -- Wann sinnvoll?
    priority INTEGER DEFAULT 3, -- 1=Pflicht, 2=Wichtig, 3=Optional
    legal_requirement TEXT,     -- Gesetzliche Pflicht?
    typical_cost_range TEXT,    -- z.B. "20-50 EUR/Monat"
    dist_type INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ── HAUSHALT ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS household_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,                        -- 'Medikamente', 'Hygiene', 'Lebensmittel', etc.
    quantity INTEGER DEFAULT 0,
    unit TEXT DEFAULT 'Stueck',
    min_quantity INTEGER DEFAULT 1,       -- Mindestbestand fuer Warnung
    location TEXT,                        -- Lagerort
    expiry_date DATE,
    last_restocked DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS household_routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    frequency TEXT NOT NULL,              -- 'daily', 'weekly', 'monthly'
    schedule TEXT,                        -- JSON: {"days": [1,3,5], "time": "09:00"}
    category TEXT,                        -- 'Putzen', 'Waschen', etc.
    duration_minutes INTEGER,
    last_done TIMESTAMP,
    next_due TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS household_shopping_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT 'Einkaufsliste',
    status TEXT DEFAULT 'aktiv' CHECK(status IN ('aktiv', 'erledigt', 'archiviert')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS household_shopping_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES household_shopping_lists(id),
    item_name TEXT NOT NULL,
    quantity INTEGER DEFAULT 1,
    unit TEXT,
    category TEXT,
    is_checked INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

-- ── KALENDER & KONTAKTE ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    -- Basis
    name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    -- Kategorisierung
    category TEXT,              -- privat, beruflich, arzt, versicherung, bank, behoerde
    subcategory TEXT,           -- z.B. bei arzt: Fachrichtung
    -- Organisation
    organization TEXT,
    position TEXT,
    -- Kommunikation
    phone TEXT,
    phone_mobile TEXT,
    phone_work TEXT,
    email TEXT,
    email_work TEXT,
    -- Adresse
    street TEXT,
    city TEXT,
    zip_code TEXT,
    country TEXT DEFAULT 'Deutschland',
    -- Zusatz
    website TEXT,
    birthday TEXT,
    notes TEXT,
    tags TEXT,                  -- Komma-separierte Tags
    -- Meta
    is_active INTEGER DEFAULT 1,
    source TEXT,                -- health_contacts, assistant_contacts, manual
    source_id INTEGER,          -- Original-ID aus Quelltabelle
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,              -- haushalt, gesundheit, finanzen, arbeit, etc.
    -- Intervall
    interval_type TEXT,         -- daily, weekly, monthly, yearly
    interval_value INTEGER DEFAULT 1, -- alle X Tage/Wochen/etc.
    specific_day TEXT,          -- z.B. "monday" oder "15" (Tag im Monat)
    -- Tracking
    last_completed_at TEXT,
    next_due_at TEXT,
    -- Status
    is_active INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 2, -- 1=Hoch, 2=Normal, 3=Niedrig
    duration_minutes INTEGER,
    -- Quelle
    source_file TEXT,           -- z.B. Haushaltsaufgaben.docx
    source TEXT,                -- household_routines, import, manual
    source_id INTEGER,
    -- Meta
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ── GESUNDHEIT ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS health_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    institution TEXT,
    specialty TEXT,                       -- 'Hausarzt', 'Kardiologe', etc.
    phone TEXT,
    email TEXT,
    address TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS health_diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_name TEXT NOT NULL,
    icd_code TEXT,                        -- ICD-10 Code
    diagnosis_date DATE,
    status TEXT DEFAULT 'aktiv' CHECK(status IN ('aktiv', 'in_abklaerung', 'hypothese', 'widerlegt', 'geheilt')),
    severity TEXT CHECK(severity IN ('leicht', 'mittel', 'schwer')),
    doctor_id INTEGER REFERENCES health_contacts(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS health_medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active_ingredient TEXT,               -- Wirkstoff
    dosage TEXT,                          -- z.B. "100mg"
    schedule TEXT,                        -- JSON: {"morning": 1, "evening": 1}
    diagnosis_id INTEGER REFERENCES health_diagnoses(id),
    start_date DATE,
    end_date DATE,
    status TEXT DEFAULT 'aktiv' CHECK(status IN ('aktiv', 'pausiert', 'beendet')),
    notes TEXT,
    side_effects TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS health_lab_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    reference_min REAL,
    reference_max REAL,
    test_date DATE NOT NULL,
    is_abnormal INTEGER DEFAULT 0,
    doctor_id INTEGER REFERENCES health_contacts(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS health_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doctor_id INTEGER REFERENCES health_contacts(id),
    appointment_date DATETIME NOT NULL,
    duration_minutes INTEGER DEFAULT 30,
    appointment_type TEXT,                -- 'Vorsorge', 'Kontrolle', 'Akut'
    status TEXT DEFAULT 'geplant' CHECK(status IN ('geplant', 'bestaetigt', 'abgesagt', 'verschoben', 'erledigt')),
    notes TEXT,
    reminder_sent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS health_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_type TEXT CHECK(doc_type IN ('befund', 'arztbrief', 'labor', 'rezept', 'studie', 'sonstiges')),
    file_path TEXT,
    content_summary TEXT,
    document_date DATE,
    doctor_id INTEGER REFERENCES health_contacts(id),
    diagnosis_id INTEGER REFERENCES health_diagnoses(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS vorsorge_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    untersuchung TEXT NOT NULL,           -- Name der Vorsorgeuntersuchung
    turnus_monate INTEGER NOT NULL,       -- Wie oft in Monaten (12=jaehrlich, 24=alle 2 Jahre)
    zuletzt DATE,                         -- Letzter Termin
    naechster_termin DATE,                -- Naechster faelliger Termin
    doctor_id INTEGER REFERENCES health_contacts(id),
    ab_alter INTEGER,                     -- Ab welchem Alter relevant
    bis_alter INTEGER,                    -- Bis zu welchem Alter relevant
    geschlecht TEXT CHECK(geschlecht IN ('m', 'w', 'alle')),
    kategorie TEXT,                       -- z.B. 'Krebs', 'Herz', 'Zahn', 'Impfung'
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS psycho_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date DATETIME NOT NULL,
    duration_minutes INTEGER,
    main_topics TEXT,                     -- JSON array
    key_insights TEXT,
    mood_before TEXT,
    mood_after TEXT,
    interventions_used TEXT,              -- JSON array
    homework TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS psycho_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES psycho_sessions(id),
    observation_type TEXT CHECK(observation_type IN ('hypothese', 'beobachtung', 'muster', 'ressource')),
    content TEXT NOT NULL,
    confidence TEXT CHECK(confidence IN ('niedrig', 'mittel', 'hoch')),
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

-- ── PARTNER & CONNECTIONS ───────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS partner_presence (
    id INTEGER PRIMARY KEY,
    partner_name TEXT NOT NULL,
    status TEXT DEFAULT 'offline',
    clocked_in TEXT,
    clocked_out TEXT,
    last_heartbeat TEXT,
    current_task TEXT,
    working_dir TEXT,
    session_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        category TEXT,
        endpoint TEXT,
        auth_type TEXT,
        auth_config TEXT,
        trigger_patterns TEXT,
        help_text TEXT,
        is_active INTEGER DEFAULT 1,
        last_used TEXT,
        success_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        consecutive_failures INTEGER DEFAULT 0,  -- Circuit Breaker: Zaehler
        disabled_until TEXT,                      -- Circuit Breaker: Sperre bis
        created_at TEXT,
        updated_at TEXT
    );

-- ── CONNECTOR MESSAGES ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS connector_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_name TEXT NOT NULL,
    direction TEXT NOT NULL,        -- 'in' | 'out'
    sender TEXT,
    recipient TEXT,
    content TEXT,
    attachments_json TEXT,
    processed INTEGER DEFAULT 0,
    error TEXT,
    retry_count INTEGER DEFAULT 0,          -- Aktuelle Versuchsnummer
    max_retries INTEGER DEFAULT 5,          -- Max Versuche bevor Dead Letter
    next_retry_at TEXT,                     -- Naechster Versuch (ISO-Timestamp)
    status TEXT DEFAULT 'pending',          -- pending|sent|failed|dead
    updated_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cm_unprocessed
    ON connector_messages(processed, created_at);

-- ── WIKI & DOCS ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS wiki_articles (
                    path TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    category TEXT,
                    last_modified TIMESTAMP,
                    tags TEXT
                );

CREATE TABLE IF NOT EXISTS document_index (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE NOT NULL,
        file_name TEXT NOT NULL,
        file_ext TEXT,
        file_size INTEGER,
        file_hash TEXT,
        file_category TEXT,
        content_text TEXT,
        content_summary TEXT,
        word_count INTEGER DEFAULT 0,
        indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        modified_at TIMESTAMP,
        ocr_applied INTEGER DEFAULT 0,
        source TEXT DEFAULT 'filesystem'
    );

CREATE TABLE IF NOT EXISTS context_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_phrase TEXT UNIQUE NOT NULL,
            hint_text TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            confidence REAL DEFAULT 0.5,
            usage_count INTEGER DEFAULT 0,
            last_used TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        , is_protected INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS languages_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        default_language TEXT DEFAULT 'de',
        fallback_language TEXT DEFAULT 'en',
        enabled_languages TEXT DEFAULT '["de", "en"]',
        auto_translate INTEGER DEFAULT 0,
        preserve_formatting INTEGER DEFAULT 1,
        updated_at TEXT
    );

CREATE TABLE IF NOT EXISTS languages_translations (
        id INTEGER PRIMARY KEY,
        key TEXT NOT NULL,
        namespace TEXT DEFAULT 'common',
        language TEXT NOT NULL,
        value TEXT NOT NULL,
        is_verified INTEGER DEFAULT 0,
        source TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(key, namespace, language)
    );

CREATE TABLE IF NOT EXISTS languages_dictionary (
        id INTEGER PRIMARY KEY,
        term TEXT NOT NULL,
        source_lang TEXT NOT NULL,
        target_lang TEXT NOT NULL,
        translation TEXT NOT NULL,
        context TEXT,
        part_of_speech TEXT,
        alternatives TEXT,
        is_preferred INTEGER DEFAULT 1,
        usage_count INTEGER DEFAULT 0,
        created_at TEXT,
        UNIQUE(term, source_lang, target_lang, context)
    );

-- ── BACKUP & FILES ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS backup_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER,
    file_count INTEGER,
    type TEXT DEFAULT 'manual' CHECK(type IN ('manual', 'auto', 'pre-update', 'scheduled')),
    description TEXT,
    checksum TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_valid INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS files_trash (
        id INTEGER PRIMARY KEY,
        original_path TEXT NOT NULL,
        trash_path TEXT NOT NULL,
        size INTEGER,
        deleted_at TEXT NOT NULL,
        deleted_by TEXT,
        retention_days INTEGER DEFAULT 30,
        expires_at TEXT,
        status TEXT DEFAULT 'active',
        restored_at TEXT,
        purged_at TEXT
    );

CREATE TABLE IF NOT EXISTS files_truth (
        id INTEGER PRIMARY KEY,
        path TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        file_exists INTEGER DEFAULT 1,
        checksum TEXT,
        size INTEGER,
        created_at TEXT,
        modified_at TEXT,
        last_scan TEXT,
        dist_type INTEGER DEFAULT 1  -- 1=TEMPLATE (Soll-Struktur), 0=USER
    );

CREATE TABLE IF NOT EXISTS folder_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT NOT NULL,
                scan_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                files_total INTEGER DEFAULT 0,
                files_new INTEGER DEFAULT 0,
                files_modified INTEGER DEFAULT 0,
                files_deleted INTEGER DEFAULT 0,
                triggered_by TEXT DEFAULT 'manual',
                dist_type INTEGER DEFAULT 0
            );

CREATE TABLE IF NOT EXISTS folder_scan_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_ext TEXT,
                file_size INTEGER,
                file_hash TEXT,
                last_modified TIMESTAMP,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_scan TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                processed INTEGER DEFAULT 0,
                dist_type INTEGER DEFAULT 0,
                UNIQUE(folder_path, file_path)
            );

CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_table TEXT NOT NULL,
                source_type TEXT,
                source_path TEXT,
                rows_total INTEGER DEFAULT 0,
                rows_inserted INTEGER DEFAULT 0,
                rows_skipped INTEGER DEFAULT 0,
                rows_failed INTEGER DEFAULT 0,
                errors TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                triggered_by TEXT DEFAULT 'manual',
                dist_type INTEGER DEFAULT 0
            );

-- ── MAIL ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mail_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- "Hauptkonto", "Geschaeftlich"
    email TEXT NOT NULL UNIQUE,            -- E-Mail Adresse
    provider TEXT NOT NULL,                -- "gmail", "outlook", "gmx", "imap"
    imap_host TEXT,                        -- IMAP Server
    imap_port INTEGER DEFAULT 993,
    use_oauth INTEGER DEFAULT 0,           -- 1 = OAuth (Gmail), 0 = Passwort
    is_active INTEGER DEFAULT 1,
    last_sync TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS mail_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES mail_accounts(id),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    emails_processed INTEGER DEFAULT 0,
    emails_matched INTEGER DEFAULT 0,
    attachments_saved INTEGER DEFAULT 0,
    errors TEXT,                           -- JSON array
    triggered_by TEXT DEFAULT 'manual',    -- manual, daemon, startup
    status TEXT DEFAULT 'running' CHECK(status IN ('running', 'success', 'failed'))
, dist_type INTEGER DEFAULT 0);

-- ── WORKFLOW TUEV ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS workflow_tuev (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_path TEXT UNIQUE NOT NULL,
    workflow_name TEXT,
    last_tuev_date TEXT,
    tuev_valid_until TEXT,
    tuev_status TEXT DEFAULT 'pending',
    test_count INTEGER DEFAULT 0,
    pass_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    avg_score REAL DEFAULT 0.0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS usecases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    workflow_path TEXT,
    workflow_name TEXT,
    test_input TEXT,
    expected_output TEXT,
    last_tested TEXT,
    test_result TEXT,
    test_score INTEGER DEFAULT 0,
    tuev_valid_until TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

-- ── ASSISTENT ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS assistant_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    event_type TEXT,                      -- 'termin', 'aufgabe', 'erinnerung'
    start_datetime DATETIME,
    end_datetime DATETIME,
    location TEXT,
    description TEXT,
    attendees TEXT,                       -- JSON array of contact_ids
    status TEXT DEFAULT 'geplant' CHECK(status IN ('geplant', 'bestaetigt', 'abgesagt', 'erledigt')),
    reminder_minutes INTEGER,
    is_recurring INTEGER DEFAULT 0,
    recurrence_rule TEXT,                 -- iCal RRULE format
    external_id TEXT,                     -- Google Calendar ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

-- Read-only compatibility for legacy consumers. The canonical storage is
-- assistant_calendar; migration 037 refuses to discard non-empty legacy data.
CREATE VIEW IF NOT EXISTS calendar_events AS
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
FROM assistant_calendar;

CREATE TABLE IF NOT EXISTS assistant_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    context TEXT,                         -- 'privat', 'beruflich'
    email TEXT,
    phone TEXT,
    mobile TEXT,
    address TEXT,
    birthday DATE,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0, company TEXT, position TEXT, tags TEXT);

CREATE TABLE IF NOT EXISTS assistant_briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    briefing_type TEXT CHECK(briefing_type IN ('sachverhalt', 'person', 'location', 'reise')),
    content TEXT,
    file_path TEXT,
    related_event_id INTEGER REFERENCES assistant_calendar(id),
    sources TEXT,                         -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS assistant_user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,               -- 'praeferenz', 'gewohnheit', 'eigenheit'
    key TEXT NOT NULL,
    value TEXT,
    confidence TEXT DEFAULT 'mittel' CHECK(confidence IN ('niedrig', 'mittel', 'hoch')),
    learned_from TEXT,                    -- Quelle der Information
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, dist_type INTEGER DEFAULT 0,
    UNIQUE(category, key)
);

-- ── SELBSTMANAGEMENT ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS selfmgmt_life_circles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_date DATE NOT NULL,
                health INTEGER CHECK(health BETWEEN 1 AND 10),
                relationships INTEGER CHECK(relationships BETWEEN 1 AND 10),
                career INTEGER CHECK(career BETWEEN 1 AND 10),
                finances INTEGER CHECK(finances BETWEEN 1 AND 10),
                personal_growth INTEGER CHECK(personal_growth BETWEEN 1 AND 10),
                leisure INTEGER CHECK(leisure BETWEEN 1 AND 10),
                environment INTEGER CHECK(environment BETWEEN 1 AND 10),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE IF NOT EXISTS selfmgmt_career_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                target_date DATE,
                status TEXT DEFAULT 'active',
                progress INTEGER DEFAULT 0,
                resources TEXT,
                blockers TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            );

CREATE TABLE IF NOT EXISTS selfmgmt_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER REFERENCES selfmgmt_career_goals(id),
                title TEXT NOT NULL,
                due_date DATE,
                completed_at DATE,
                notes TEXT
            );

CREATE TABLE IF NOT EXISTS selfmgmt_adhd_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                when_to_use TEXT,
                steps TEXT,
                effectiveness INTEGER DEFAULT 3,
                personal_notes TEXT,
                times_used INTEGER DEFAULT 0,
                last_used DATE
            );

-- ── ZEIT ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS between_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    message TEXT NOT NULL,
                    trigger_on TEXT,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

-- ── USER ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,          -- 'dashboard', 'scanner', 'daemon', 'ui'
    key TEXT NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, dist_type INTEGER DEFAULT 1,
    UNIQUE(category, key)
);

CREATE TABLE IF NOT EXISTS user_meta (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, dist_type INTEGER DEFAULT 0);

-- ── DISTRIBUTION SYSTEM ─────────────────────────────────────────────
-- Basiert auf: tools/generators/DISTRIBUTION_SCHEMA.sql
-- Wird durch distribution_system.py._init_schema() angelegt
-- SQ002a: Integration in schema.sql (2026-02-17)

CREATE TABLE IF NOT EXISTS tiers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    dev_write INTEGER DEFAULT 1,
    user_write INTEGER DEFAULT 0,
    learn_write INTEGER DEFAULT 0,
    export_default INTEGER DEFAULT 1,
    protection_level TEXT DEFAULT 'medium',
    developer_can_modify INTEGER DEFAULT 1,
    user_can_modify INTEGER DEFAULT 0,
    learn_can_modify INTEGER DEFAULT 0,
    include_in_standard INTEGER DEFAULT 1,
    include_in_minimal INTEGER DEFAULT 0,
    include_in_snapshot INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tier_patterns (
    id INTEGER PRIMARY KEY,
    path_pattern TEXT UNIQUE NOT NULL,
    tier_id INTEGER NOT NULL REFERENCES tiers(id),
    priority INTEGER DEFAULT 50,
    description TEXT
);

CREATE TABLE IF NOT EXISTS filesystem_entries (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    tier_id INTEGER DEFAULT 1 REFERENCES tiers(id),
    component TEXT,
    is_active INTEGER DEFAULT 1,
    can_disable INTEGER DEFAULT 0,
    current_version_id INTEGER,
    mutability TEXT DEFAULT 'immutable',
    merge_strategy TEXT DEFAULT 'replace',
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES filesystem_entries(id),
    version_major INTEGER DEFAULT 1,
    version_minor INTEGER DEFAULT 0,
    version_patch INTEGER DEFAULT 0,
    source TEXT DEFAULT 'dev',
    source_sequence INTEGER DEFAULT 1,
    checksum TEXT,
    size INTEGER,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'system',
    change_type TEXT,
    change_description TEXT,
    previous_version_id INTEGER REFERENCES file_versions(id)
);

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
    current_mode TEXT DEFAULT 'developer',
    base_release TEXT,
    base_release_date TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mode_transitions (
    id INTEGER PRIMARY KEY,
    instance_id TEXT NOT NULL,
    from_mode TEXT,
    to_mode TEXT NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_by TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    snapshot_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    snapshot_type TEXT DEFAULT 'manual',
    file_count INTEGER DEFAULT 0,
    total_size INTEGER DEFAULT 0,
    is_valid INTEGER DEFAULT 1,
    path TEXT,
    format TEXT DEFAULT 'zip',
    includes_tiers TEXT DEFAULT '[0,1,2]',
    includes_userdata INTEGER DEFAULT 0,
    size_bytes INTEGER,
    kernel_hash TEXT,
    checksum TEXT,
    created_at TEXT,
    source_version TEXT,
    retention_days INTEGER DEFAULT 90,
    expires_at TEXT,
    status TEXT DEFAULT 'active',
    restored_at TEXT,
    restored_count INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS snapshot_files (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    entry_id INTEGER NOT NULL REFERENCES filesystem_entries(id),
    version_id INTEGER REFERENCES file_versions(id),
    file_checksum TEXT,
    file_size INTEGER
);

CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    version TEXT UNIQUE NOT NULL,
    release_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    changelog TEXT,
    kernel_hash TEXT,
    snapshot_id INTEGER REFERENCES snapshots(id),
    status TEXT DEFAULT 'draft',
    is_stable INTEGER DEFAULT 0,
    download_url TEXT,
    version_major INTEGER,
    version_minor INTEGER,
    version_patch INTEGER,
    type TEXT,
    name TEXT,
    source TEXT DEFAULT 'release',
    source_sequence INTEGER DEFAULT 0,
    total_hash TEXT,
    manifest TEXT,
    file_count INTEGER,
    total_size_bytes INTEGER,
    is_current INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS release_manifest (
    id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL REFERENCES releases(id),
    entry_id INTEGER NOT NULL REFERENCES filesystem_entries(id),
    version_id INTEGER REFERENCES file_versions(id),
    tier_id INTEGER REFERENCES tiers(id)
);

CREATE TABLE IF NOT EXISTS known_instances (
    instance_id TEXT PRIMARY KEY,
    instance_name TEXT,
    path TEXT,
    last_seen TIMESTAMP,
    version TEXT,
    seal_status TEXT
);

-- Distribution VIEWs (aus DISTRIBUTION_SCHEMA.sql)
CREATE VIEW IF NOT EXISTS v_files_with_tiers AS
SELECT
    fe.id,
    fe.path,
    t.name as tier_name,
    t.id as tier_id,
    fe.is_active,
    fe.mutability,
    fv.checksum,
    fv.size,
    fv.created as version_date
FROM filesystem_entries fe
LEFT JOIN tiers t ON fe.tier_id = t.id
LEFT JOIN file_versions fv ON fe.current_version_id = fv.id;

CREATE VIEW IF NOT EXISTS v_latest_versions AS
SELECT
    fe.path,
    fv.version_major || '.' || fv.version_minor || '.' || fv.version_patch || '-' || fv.source || '.' || fv.source_sequence as version_string,
    fv.checksum,
    fv.size,
    fv.created,
    fv.change_type,
    fv.change_description
FROM filesystem_entries fe
JOIN file_versions fv ON fe.current_version_id = fv.id;

-- ── INDEXES ──────────────────────────────────────────────────────────

-- Distribution System Indexes
CREATE INDEX IF NOT EXISTS idx_filesystem_entries_tier ON filesystem_entries(tier_id);
CREATE INDEX IF NOT EXISTS idx_filesystem_entries_active ON filesystem_entries(is_active);
CREATE INDEX IF NOT EXISTS idx_file_versions_entry ON file_versions(entry_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_created ON file_versions(created);
CREATE INDEX IF NOT EXISTS idx_snapshot_files_snapshot ON snapshot_files(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_releases_version ON releases(version);
CREATE INDEX IF NOT EXISTS idx_releases_current ON releases(is_current);
CREATE INDEX IF NOT EXISTS idx_tier_patterns_tier ON tier_patterns(tier_id);
CREATE INDEX IF NOT EXISTS idx_release_manifest_release ON release_manifest(release_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status);
CREATE INDEX IF NOT EXISTS idx_snapshots_expires ON snapshots(expires_at);

CREATE INDEX IF NOT EXISTS idx_ati_tasks_priority ON ati_tasks(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_ati_tasks_status ON ati_tasks(status);
CREATE INDEX IF NOT EXISTS idx_ati_tasks_tool ON ati_tasks(tool_name);
CREATE INDEX IF NOT EXISTS idx_ati_tool_registry_name ON ati_tool_registry(name);
CREATE INDEX IF NOT EXISTS idx_ati_tool_registry_status ON ati_tool_registry(status);
CREATE INDEX IF NOT EXISTS idx_backup_snapshots_created ON backup_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_backup_snapshots_type ON backup_snapshots(type);
CREATE INDEX IF NOT EXISTS idx_comm_messages_direction ON comm_messages(direction);
CREATE INDEX IF NOT EXISTS idx_comm_messages_recipient ON comm_messages(recipient);
CREATE INDEX IF NOT EXISTS idx_comm_messages_status ON comm_messages(status);
CREATE INDEX IF NOT EXISTS idx_consolidation_source ON memory_consolidation(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_consolidation_status ON memory_consolidation(status);
CREATE INDEX IF NOT EXISTS idx_consolidation_weight ON memory_consolidation(weight);
CREATE INDEX IF NOT EXISTS idx_hierarchy_assignments_child ON hierarchy_assignments(child_id);
CREATE INDEX IF NOT EXISTS idx_hierarchy_assignments_parent ON hierarchy_assignments(parent_id);
CREATE INDEX IF NOT EXISTS idx_hierarchy_items_status ON hierarchy_items(status);
CREATE INDEX IF NOT EXISTS idx_hierarchy_items_type ON hierarchy_items(type);
CREATE INDEX IF NOT EXISTS idx_memory_facts_category ON memory_facts(category);
CREATE INDEX IF NOT EXISTS idx_memory_facts_key ON memory_facts(key);
CREATE INDEX IF NOT EXISTS idx_memory_working_active ON memory_working(is_active);
CREATE INDEX IF NOT EXISTS idx_memory_working_type ON memory_working(type);
CREATE INDEX IF NOT EXISTS idx_presence_partner ON partner_presence(partner_name);
CREATE INDEX IF NOT EXISTS idx_presence_status ON partner_presence(status);
CREATE INDEX IF NOT EXISTS idx_snapshots_session ON session_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_type ON session_snapshots(snapshot_type);
CREATE INDEX IF NOT EXISTS idx_task_history_action ON task_history(action);
CREATE INDEX IF NOT EXISTS idx_task_history_task_id ON task_history(task_id);

-- ── INJECTORS ─────────────────────────────────────────────────────────

-- SQ040: Reminder Injector
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_condition TEXT NOT NULL DEFAULT 'always',
    trigger_value TEXT,
    message TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 5,
    last_triggered TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- SQ042: Meta-Feedback Injector
CREATE TABLE IF NOT EXISTS meta_feedback_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    pattern_type TEXT NOT NULL DEFAULT 'substring',
    correction TEXT NOT NULL,
    frequency INTEGER NOT NULL DEFAULT 0,
    max_inactive_count INTEGER NOT NULL DEFAULT 10,
    inactive_count INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reminders_active ON reminders(active);
CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders(trigger_condition);
CREATE INDEX IF NOT EXISTS idx_meta_feedback_active ON meta_feedback_patterns(active);

-- SQ048: Session Context / 24h-Agent
CREATE TABLE IF NOT EXISTS session_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT,
    handover_notes TEXT,
    work_mode TEXT NOT NULL DEFAULT 'assistant',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(date)
);

-- ── BLOBS (SQ044: Wiki-in-Database) ──────────────────────────────────

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

CREATE VIRTUAL TABLE IF NOT EXISTS bach_blobs_fts USING fts5(
    path,
    content,
    category,
    content=bach_blobs,
    content_rowid=rowid,
    tokenize='unicode61'
);

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

-- ── FULL TEXT SEARCH ──────────────────────────────────────────────────

-- FTS table (requires special handling, cannot use IF NOT EXISTS)
-- CREATE VIRTUAL TABLE document_fts USING fts5(
--         file_name,
--         content_text,
--         content_summary,
--         content='document_index',
--         content_rowid='id'
--     );


-- =============================================================
-- Fehlende Tabellen (aus DB extrahiert, 2026-03-04)
-- Ergaenzt durch Help-Expert-Review
-- =============================================================

CREATE TABLE claude_bridge_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE claude_bridge_workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_description TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    permission_mode TEXT,
    pid INTEGER,
    result_summary TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    cost_estimate_usd REAL DEFAULT 0.0
);

CREATE TABLE cookbook_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    recipe_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE daemon_jobs (
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
, dist_type INTEGER DEFAULT 1);

CREATE TABLE daemon_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES daemon_jobs(id),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    result TEXT CHECK(result IN ('success', 'failed', 'timeout', 'cancelled')),
    output TEXT,
    error TEXT,
    triggered_by TEXT DEFAULT 'schedule'  -- 'schedule', 'manual', 'event'
, dist_type INTEGER DEFAULT 0);

CREATE TABLE dist_file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    version TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    dist_type INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(file_path, version)
);

CREATE TABLE dist_type_defaults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    dist_type INTEGER NOT NULL DEFAULT 1,
    is_file INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_index_id INTEGER NOT NULL,  -- FK zu search_index
    chunk_number INTEGER NOT NULL,     -- 0-basiert
    chunk_text TEXT NOT NULL,          -- Chunk-Inhalt (400 Tokens)
    chunk_tokens INTEGER DEFAULT 0,    -- Token-Anzahl (Approximation)
    summary TEXT,                      -- LLM-Zusammenfassung (Stufe 3, NULL bis generiert)
    embedding BLOB,                    -- Optionales Embedding (sqlite-vec, SQ064)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    summarized_at TIMESTAMP,           -- Wann wurde Summary generiert?
    FOREIGN KEY (search_index_id) REFERENCES search_index(id) ON DELETE CASCADE
);

CREATE TABLE email_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient TEXT NOT NULL,
                cc TEXT,
                bcc TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                body_html TEXT,
                account_id INTEGER DEFAULT 3,
                sender_email TEXT DEFAULT 'lukasgeiger@googlemail.com',
                status TEXT DEFAULT 'draft'
                    CHECK(status IN ('draft', 'sent', 'cancelled', 'failed')),
                error_message TEXT,
                gmail_message_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                confirmed_by TEXT,
                cancelled_at TIMESTAMP
            );

CREATE TABLE chunk_indexing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    chunk_size INTEGER DEFAULT 400,    -- Token pro Chunk
    overlap INTEGER DEFAULT 80,        -- Overlap-Tokens
    llm_model TEXT,                    -- z.B. "haiku-3.5", "sonnet-3.5"
    llm_cost_usd REAL DEFAULT 0.0,     -- Geschätzte LLM-Kosten
    documents_indexed INTEGER DEFAULT 0,
    chunks_created INTEGER DEFAULT 0,
    chunks_summarized INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    log TEXT,                          -- Fehler-Log, Warnings
    status TEXT DEFAULT 'running'      -- running, completed, failed
);

CREATE TABLE health_symptoms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symptom TEXT NOT NULL,
    body_part TEXT,
    severity INTEGER CHECK(severity BETWEEN 1 AND 10),
    onset TEXT NOT NULL,
    resolution TEXT,
    status TEXT DEFAULT 'active',
    linked_diagnosis_id INTEGER,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (linked_diagnosis_id) REFERENCES health_diagnoses(id)
);

CREATE TABLE partner_memory_config (
    partner_id TEXT PRIMARY KEY,
    fact_decay_rate REAL DEFAULT 0.01,          -- Pro Tag ohne Zugriff
    lesson_decay_rate REAL DEFAULT 0.005,       -- Lessons decayen langsamer
    min_confidence REAL DEFAULT 0.2,            -- Unter diesem Wert löschen?
    max_facts INTEGER DEFAULT 1000,
    max_lessons INTEGER DEFAULT 200,
    max_sessions INTEGER DEFAULT 500,
    memory_md_top_facts INTEGER DEFAULT 10,
    memory_md_top_lessons INTEGER DEFAULT 10,
    auto_cleanup_enabled INTEGER DEFAULT 1,
    cleanup_interval_days INTEGER DEFAULT 7,
    last_cleanup_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE partner_memory_decay (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL CHECK(item_type IN ('fact', 'lesson')),
    item_id INTEGER NOT NULL,
    partner_id TEXT NOT NULL,
    original_confidence REAL NOT NULL,
    current_confidence REAL NOT NULL,
    decay_applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT CHECK(event_type IN ('decay', 'boost', 'reset')),
    event_reason TEXT,                   -- Warum wurde geboostet/decayed?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_type, item_id, decay_applied_at)
);

CREATE TABLE partner_memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_id TEXT NOT NULL,           -- 'claude', 'gemini', 'ollama', 'gpt4'
    category TEXT NOT NULL CHECK(category IN ('user', 'project', 'system', 'domain')),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'text' CHECK(value_type IN ('text', 'json', 'number', 'date')),
    confidence REAL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    decay_rate REAL DEFAULT 0.01,       -- Pro Tag ohne Zugriff
    source TEXT,                         -- Welcher Agent/Kontext hat es erstellt
    related_trigger TEXT,                -- Optional: Trigger der es ausgelöst hat
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(partner_id, category, key)
);

CREATE TABLE partner_memory_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_id TEXT NOT NULL,           -- 'claude', 'gemini', 'ollama', 'gpt4'
    category TEXT NOT NULL,              -- 'code', 'system', 'workflow', 'communication'
    severity TEXT DEFAULT 'medium' CHECK(severity IN ('low', 'medium', 'high', 'critical')),
    title TEXT NOT NULL,
    problem TEXT NOT NULL,               -- Was war das Problem?
    solution TEXT NOT NULL,              -- Wie wurde es gelöst?
    context TEXT,                        -- Zusätzlicher Kontext
    related_tools TEXT,                  -- Komma-separiert: 'git, npm, python'
    related_files TEXT,                  -- Komma-separiert: 'hub/*.py, tests/*'
    trigger_words TEXT,                  -- Trigger-Keywords für Auto-Injection
    trigger_events TEXT,                 -- Events die Lesson aktivieren
    is_active INTEGER DEFAULT 1,
    times_shown INTEGER DEFAULT 0,
    last_shown TIMESTAMP,
    effectiveness REAL DEFAULT 0.5,      -- 0.0-1.0, wie hilfreich war die Lesson?
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE partner_memory_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    partner_id TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,    -- UUID oder Hash
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    project TEXT,                        -- Projekt-Name oder Pfad
    summary TEXT,                        -- Session-Zusammenfassung
    key_topics TEXT,                     -- Hauptthemen (komma-separiert)
    continuation_context TEXT,           -- Was wurde für nächste Session notiert?
    next_steps TEXT,                     -- Geplante nächste Schritte
    facts_added INTEGER DEFAULT 0,
    lessons_added INTEGER DEFAULT 0,
    tools_used TEXT,                     -- Genutzte Tools (komma-separiert)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE search_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,          -- 'document', 'wiki', 'memory_working', 'memory_fact', 'memory_lesson', 'file'
    source_id TEXT NOT NULL,       -- ID/key in source table
    source_path TEXT,              -- file path or DB reference
    title TEXT NOT NULL,           -- display title
    content TEXT,                  -- full text content (truncated to 100k)
    category TEXT,                 -- file category or content type
    content_hash TEXT,             -- SHA256 for dedup
    word_count INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_id)
);

CREATE TABLE search_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES search_index(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    UNIQUE(search_id, tag)
);

CREATE TABLE system_activity (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton-Tabelle (nur 1 Zeile)
    last_activity TEXT NOT NULL,             -- ISO Timestamp der letzten Aktivität
    session_id TEXT,                         -- Aktuelle Session (aus memory_sessions)
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
, eod_finalized_today INTEGER DEFAULT 0, last_eod_finalize TEXT);

CREATE TABLE watcher_event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        event_type TEXT NOT NULL,
        sender TEXT DEFAULT '',
        content_preview TEXT DEFAULT '',
        action TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        reasoning TEXT DEFAULT '',
        response_sent TEXT DEFAULT '',
        escalation_profile TEXT DEFAULT '',
        processing_time_ms INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
