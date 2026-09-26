# -*- coding: utf-8 -*-
"""
Gemeinsames Gedaechtnisschema BACH = OCEAN (Vereinigungsschema, Stufe S1)
=========================================================================

Kanonische DDL der gemeinsamen ``memory_*``-Tabellen. BACH (bach.db) und
USMC (usmc_memory.db) fuehren dieselben Tabellen mit denselben Spalten in
derselben Reihenfolge. Die erwartete PRAGMA-Form steht in
``memory_union.contract.json``; BACH vendort diese Datei byte-identisch.

Spaltenreihenfolge = BACH-Bestand + angehaengte Vereinigungsspalten, damit
eine additiv migrierte BACH-Datenbank PRAGMA-identisch zu einer frisch
angelegten ist.

Die USMC-Umstellung ist opt-in (``USMC_MEMORY_UNION=1`` oder
``apply_union(conn, ...)``). Ohne Opt-in bleibt eine Datenbank unveraendert
auf den ``usmc_*``-Tabellen. Vor dem Umbau einer Datei-DB mit Daten wird eine
Sicherungskopie geschrieben; Rollback = Kopie zuruecklegen.

Vertrag v2 (S2): Lesson-Schema v2 (Provenienz, Idempotenz, Feedback,
Zustellung) gehoert zum gemeinsamen Vertrag -- memory_lessons traegt die
v2-Spalten, dazu memory_lesson_feedback/_delivery_batches/_deliveries.
Das Modul ist bewusst eigenstaendig (keine Paket-Imports), damit BACH es
byte-identisch vendoren kann.

Nicht Teil dieses Moduls: Datenumzug zwischen Hosts, tasks.

Author: Lukas Geiger
License: MIT
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

UNION_VERSION = 2
UNION_META_KEY = "memory_union"
CONTRACT_PATH = Path(__file__).with_name("memory_union.contract.json")
DEFAULT_AGENT = "default"

WORKING_TYPES = ("scratchpad", "context", "loop", "note", "handoff", "task")
FACT_CATEGORIES = ("user", "project", "system", "domain")

UNION_TABLES = (
    "memory_sessions",
    "memory_working",
    "memory_facts",
    "memory_lessons",
    "context_triggers",
    "memory_consolidation",
    "decay_config",
    "memory_lesson_feedback",
    "memory_lesson_delivery_batches",
    "memory_lesson_deliveries",
)

_types = ", ".join(f"'{t}'" for t in WORKING_TYPES)
_cats = ", ".join(f"'{c}'" for c in FACT_CATEGORIES)

TABLE_DDL: Dict[str, str] = {
    "memory_sessions": """
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
    continuation_context TEXT,
    dist_type INTEGER DEFAULT 0,
    is_compressed INTEGER DEFAULT 0,
    partner_id TEXT DEFAULT 'user',
    agent_id TEXT NOT NULL DEFAULT 'default',
    current_task TEXT,
    handoff_notes TEXT
)""",
    "memory_working": f"""
CREATE TABLE IF NOT EXISTS memory_working (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ({_types})),
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    created_by_session_id TEXT REFERENCES memory_sessions(session_id),
    updated_by_session_id TEXT REFERENCES memory_sessions(session_id),
    agent_id TEXT NOT NULL DEFAULT 'default',
    session_id TEXT,
    related_to TEXT
)""",
    "memory_facts": f"""
CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL CHECK(category IN ({_cats})),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'text',
    confidence REAL DEFAULT 1.0 CHECK(confidence >= 0 AND confidence <= 1),
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by_session_id TEXT REFERENCES memory_sessions(session_id),
    updated_by_session_id TEXT REFERENCES memory_sessions(session_id),
    agent_id TEXT NOT NULL DEFAULT 'default',
    namespace TEXT,
    visibility TEXT,
    UNIQUE(agent_id, category, key)
)""",
    "memory_lessons": """
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
    updated_at TEXT,
    dist_type INTEGER DEFAULT 1,
    created_by_session_id TEXT REFERENCES memory_sessions(session_id),
    updated_by_session_id TEXT REFERENCES memory_sessions(session_id),
    agent_id TEXT NOT NULL DEFAULT 'default',
    confidence REAL DEFAULT 1.0,
    namespace TEXT,
    visibility TEXT,
    source_kind TEXT NOT NULL DEFAULT 'legacy',
    source_key TEXT,
    episode_key TEXT,
    source_hash TEXT,
    event_anchor TEXT,
    editorial_status TEXT NOT NULL DEFAULT 'legacy',
    evidence_class TEXT NOT NULL DEFAULT 'unknown',
    privacy_scope TEXT NOT NULL DEFAULT 'local',
    sensitive_source INTEGER NOT NULL DEFAULT 0,
    user_preference INTEGER NOT NULL DEFAULT 0,
    policy_relevant INTEGER NOT NULL DEFAULT 0,
    conflict_flag INTEGER NOT NULL DEFAULT 0,
    mutates_skill INTEGER NOT NULL DEFAULT 0,
    mutates_workflow INTEGER NOT NULL DEFAULT 0,
    ingest_payload_hash TEXT,
    ingest_payload_hash_version INTEGER,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    unhelpful_count INTEGER NOT NULL DEFAULT 0,
    independent_repeat_count INTEGER NOT NULL DEFAULT 0,
    delivery_failure_count INTEGER NOT NULL DEFAULT 0,
    last_delivered_at TEXT
)""",
    "context_triggers": """
CREATE TABLE IF NOT EXISTS context_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_phrase TEXT NOT NULL,
    hint_text TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    confidence REAL DEFAULT 0.5,
    usage_count INTEGER DEFAULT 0,
    last_used TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    is_protected INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('unknown', 'blocked', 'approved')),
    agent_id TEXT NOT NULL DEFAULT 'default',
    namespace TEXT,
    expires_at TEXT,
    UNIQUE(agent_id, trigger_phrase)
)""",
    "memory_consolidation": """
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
    agent_id TEXT NOT NULL DEFAULT 'default',
    UNIQUE(source_table, source_id)
)""",
    "decay_config": """
CREATE TABLE IF NOT EXISTS decay_config (
    agent_id TEXT PRIMARY KEY,
    fact_decay_rate REAL DEFAULT 0.01,
    lesson_decay_rate REAL DEFAULT 0.005,
    min_confidence REAL DEFAULT 0.2,
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
)""",
    "memory_lesson_feedback": """
CREATE TABLE IF NOT EXISTS memory_lesson_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL REFERENCES memory_lessons(id) ON DELETE CASCADE,
    feedback_key TEXT NOT NULL,
    helpful INTEGER CHECK(helpful IS NULL OR helpful IN (0, 1)),
    independent_repeat INTEGER NOT NULL DEFAULT 0,
    delivery_failed INTEGER NOT NULL DEFAULT 0,
    delivery_key TEXT,
    event_anchor TEXT,
    payload_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL,
    UNIQUE(feedback_key)
)""",
    "memory_lesson_delivery_batches": """
CREATE TABLE IF NOT EXISTS memory_lesson_delivery_batches (
    delivery_key TEXT PRIMARY KEY,
    session_id INTEGER REFERENCES memory_sessions(id) ON DELETE CASCADE,
    session_key TEXT NOT NULL,
    delivery_mode TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL
)""",
    "memory_lesson_deliveries": """
CREATE TABLE IF NOT EXISTS memory_lesson_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id INTEGER NOT NULL REFERENCES memory_lessons(id) ON DELETE CASCADE,
    delivery_key TEXT NOT NULL,
    session_key TEXT NOT NULL,
    delivery_mode TEXT NOT NULL,
    context TEXT,
    feedback_prompt TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL,
    UNIQUE(lesson_id, delivery_key)
)""",
}

INDEX_DDL = tuple(line for line in """
CREATE INDEX IF NOT EXISTS idx_memory_working_active ON memory_working(is_active);
CREATE INDEX IF NOT EXISTS idx_memory_working_type ON memory_working(type);
CREATE INDEX IF NOT EXISTS idx_memory_working_created_by_session ON memory_working(created_by_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_working_agent ON memory_working(agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_facts_category ON memory_facts(category);
CREATE INDEX IF NOT EXISTS idx_memory_facts_key ON memory_facts(key);
CREATE INDEX IF NOT EXISTS idx_memory_facts_created_by_session ON memory_facts(created_by_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_facts_agent ON memory_facts(agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_lessons_created_by_session ON memory_lessons(created_by_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_lessons_agent ON memory_lessons(agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_sessions_agent ON memory_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_context_triggers_agent ON context_triggers(agent_id);
CREATE INDEX IF NOT EXISTS idx_context_triggers_status ON context_triggers(status);
CREATE INDEX IF NOT EXISTS idx_consolidation_source ON memory_consolidation(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_consolidation_status ON memory_consolidation(status);
CREATE INDEX IF NOT EXISTS idx_consolidation_weight ON memory_consolidation(weight);
CREATE INDEX IF NOT EXISTS idx_consolidation_agent ON memory_consolidation(agent_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_lessons_source_episode ON memory_lessons(source_key, episode_key) WHERE source_key IS NOT NULL AND episode_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_lessons_delivery_selection ON memory_lessons(is_active, editorial_status, privacy_scope);
CREATE INDEX IF NOT EXISTS idx_memory_lesson_feedback_lesson ON memory_lesson_feedback(lesson_id);
CREATE INDEX IF NOT EXISTS idx_memory_lesson_deliveries_lesson ON memory_lesson_deliveries(lesson_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_lesson_deliveries_batch_order ON memory_lesson_deliveries(delivery_key, id)
""".strip().replace(";", "").splitlines())

# Provenienz-Trigger aus BACH-Migration 039 (unveraendert uebernommen).
_ACTIVE_SESSION = (
    "SELECT session_id FROM memory_sessions "
    "WHERE ended_at IS NULL ORDER BY started_at DESC, id DESC LIMIT 1"
)
PROVENANCE_TABLES = ("memory_working", "memory_facts", "memory_lessons")


def provenance_trigger_sql(table: str):
    """Die beiden Trigger als Einzelanweisungen (kein executescript: das
    wuerde eine laufende Transaktion implizit committen)."""
    return (f"""
CREATE TRIGGER IF NOT EXISTS trg_{table}_session_provenance_insert
AFTER INSERT ON {table}
WHEN NEW.created_by_session_id IS NULL
BEGIN
    UPDATE {table}
    SET created_by_session_id = ({_ACTIVE_SESSION}),
        updated_by_session_id = ({_ACTIVE_SESSION})
    WHERE id = NEW.id;
END""", f"""
CREATE TRIGGER IF NOT EXISTS trg_{table}_session_provenance_update
AFTER UPDATE ON {table}
WHEN NEW.updated_by_session_id IS OLD.updated_by_session_id
BEGIN
    UPDATE {table}
    SET updated_by_session_id = ({_ACTIVE_SESSION})
    WHERE id = NEW.id
      AND EXISTS (SELECT 1 FROM memory_sessions WHERE ended_at IS NULL);
END""")


# Lese-Kompatibilitaet fuer bestehende usmc_*-Leser (gardener, memoryhooker).
COMPAT_VIEWS = {
    "usmc_facts": (
        "SELECT id, category, key, value, confidence, source, agent_id, "
        "created_at, updated_at FROM memory_facts"
    ),
    "usmc_working": (
        "SELECT id, type, content, priority, tags, agent_id, is_active, "
        "created_at, updated_at FROM memory_working"
    ),
    "usmc_lessons": (
        "SELECT id, category, severity, title, problem, solution, agent_id, "
        "is_active, confidence, times_shown, created_at, updated_at FROM memory_lessons"
    ),
    "usmc_sessions": (
        "SELECT id, agent_id, started_at, ended_at, current_task, handoff_notes "
        "FROM memory_sessions"
    ),
}

_LESSON_V2_COLUMN_NAMES = (
    "source_kind", "source_key", "episode_key", "source_hash", "event_anchor",
    "editorial_status", "evidence_class", "privacy_scope", "sensitive_source",
    "user_preference", "policy_relevant", "conflict_flag", "mutates_skill",
    "mutates_workflow", "ingest_payload_hash", "ingest_payload_hash_version",
    "helpful_count", "unhelpful_count", "independent_repeat_count",
    "delivery_failure_count", "last_delivered_at",
)

# usmc_*-Spalten -> gleichnamige memory_*-Spalten. Jede andere Spalte bricht
# den Umzug ab. Reihenfolge = Kopierreihenfolge (Eltern vor Kindern).
_LEGACY_COLUMNS = {
    "usmc_facts": ("id", "category", "key", "value", "confidence", "source",
                   "agent_id", "created_at", "updated_at"),
    "usmc_working": ("id", "type", "content", "priority", "tags", "agent_id",
                     "is_active", "created_at", "updated_at"),
    "usmc_lessons": ("id", "category", "severity", "title", "problem", "solution",
                     "agent_id", "is_active", "confidence", "times_shown",
                     "created_at", "updated_at", *_LESSON_V2_COLUMN_NAMES),
    "usmc_sessions": ("id", "agent_id", "started_at", "ended_at", "current_task",
                      "handoff_notes"),
    "usmc_lesson_feedback": ("id", "lesson_id", "feedback_key", "helpful",
                             "independent_repeat", "delivery_failed", "delivery_key",
                             "event_anchor", "payload_hash", "agent_id", "created_at"),
    "usmc_lesson_delivery_batches": ("delivery_key", "session_id", "session_key",
                                     "delivery_mode", "request_hash", "agent_id",
                                     "created_at"),
    "usmc_lesson_deliveries": ("id", "lesson_id", "delivery_key", "session_key",
                               "delivery_mode", "context", "feedback_prompt",
                               "payload_hash", "agent_id", "created_at"),
}
_TARGET = {legacy: "memory_" + legacy[len("usmc_"):] for legacy in _LEGACY_COLUMNS}


class UnionMigrationError(RuntimeError):
    """Umzug abgebrochen, Datenbank unveraendert."""


def create_union_schema(conn: sqlite3.Connection, *, triggers: bool = True) -> None:
    """Legt alle Vereinigungstabellen, Indizes und Trigger idempotent an."""
    for table in UNION_TABLES:
        conn.execute(TABLE_DDL[table])
    for statement in INDEX_DDL:
        conn.execute(statement)
    if triggers:
        install_provenance_triggers(conn)


def install_provenance_triggers(conn: sqlite3.Connection) -> None:
    for table in PROVENANCE_TABLES:
        for statement in provenance_trigger_sql(table):
            conn.execute(statement)


def _object_type(conn: sqlite3.Connection, name: str) -> Optional[str]:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?", (name,)
    ).fetchone()
    return row[0] if row else None


def _columns(conn: sqlite3.Connection, table: str):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def union_version(conn: sqlite3.Connection) -> int:
    """0 = nicht vereinigt, sonst die Vertragsversion der Datenbank."""
    try:
        row = conn.execute(
            "SELECT value FROM usmc_meta WHERE key = ?", (UNION_META_KEY,)
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row and str(row[0]).isdigit() else 0


def is_union(conn: sqlite3.Connection) -> bool:
    return union_version(conn) > 0


def backup_database(db_path: Path) -> Path:
    """Konsistente Sicherungskopie per SQLite-Backup-API neben der DB."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.name}.pre-memory-union-{stamp}.bak")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def apply_union(conn: sqlite3.Connection) -> Dict[str, int]:
    """Stellt eine USMC-Datenbank auf das Vereinigungsschema um.

    Kopiert usmc_*-Zeilen mit unveraenderten IDs nach memory_*, ersetzt die
    Stammtabellen durch Lese-Views, loescht die Lesson-Nebentabellen und
    setzt ``usmc_meta.memory_union``. Alles in einer Transaktion; bei jeder
    Abweichung Abbruch ohne Mutation. Unbekannte Spalten brechen ab, statt
    still verloren zu gehen.

    Eine Datenbank auf Vertrag v1 (usmc_lessons samt Nebentabellen blieb dort
    real liegen) wird auf v2 hochgezogen: die Lesson-Tabellen wandern nach.
    Liegen schon Zeilen im Ziel UND in der Quelle, wird abgebrochen.
    """
    if union_version(conn) >= UNION_VERSION:
        return {}
    if conn.in_transaction:
        raise UnionMigrationError("offene Transaktion")
    copied: Dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS usmc_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        # Trigger erst nach dem Kopieren: Altzeilen behalten NULL-Provenienz.
        # v2-Spalten vor den Indizes nachziehen (v1-memory_lessons kennt sie nicht).
        for table in UNION_TABLES:
            conn.execute(TABLE_DDL[table])
        for statement in list(_missing_lesson_v2_columns(conn)):
            conn.execute(statement)
        for statement in INDEX_DDL:
            conn.execute(statement)
        for legacy, target in _TARGET.items():
            if _object_type(conn, legacy) != "table":
                continue
            extra = set(_columns(conn, legacy)) - set(_LEGACY_COLUMNS[legacy])
            if extra:
                raise UnionMigrationError(
                    f"unmapped-columns {legacy}: {', '.join(sorted(extra))}"
                )
            before = conn.execute(f"SELECT COUNT(*) FROM {legacy}").fetchone()[0]
            existing = conn.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0]
            if before and existing:
                raise UnionMigrationError(f"target-not-empty {target}")
            cols = [c for c in _LEGACY_COLUMNS[legacy] if c in _columns(conn, legacy)]
            col_sql = ", ".join(cols)
            if legacy == "usmc_sessions":
                conn.execute(
                    f"INSERT INTO memory_sessions (session_id, {col_sql}) "
                    f"SELECT 'usmc-' || id, {col_sql} FROM usmc_sessions"
                )
            else:
                conn.execute(
                    f"INSERT INTO {target} ({col_sql}) SELECT {col_sql} FROM {legacy}"
                )
            after = conn.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0]
            if existing + before != after:
                raise UnionMigrationError(f"row-count {legacy}: {before} != {after - existing}")
            copied[legacy] = before
        # Kinder vor Eltern loeschen (Fremdschluessel der Lesson-Nebentabellen).
        for legacy in reversed(tuple(_TARGET)):
            if _object_type(conn, legacy) == "table":
                conn.execute(f"DROP TABLE {legacy}")
        install_provenance_triggers(conn)
        for view, select in COMPAT_VIEWS.items():
            if _object_type(conn, view) is None:
                conn.execute(f"CREATE VIEW {view} AS {select}")
        conn.execute(
            "INSERT OR REPLACE INTO usmc_meta (key, value) VALUES (?, ?)",
            (UNION_META_KEY, str(UNION_VERSION)),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return copied


def _missing_lesson_v2_columns(conn: sqlite3.Connection):
    """ALTER-Anweisungen fuer ein memory_lessons, das noch auf Vertrag v1 steht."""
    have = set(_columns(conn, "memory_lessons"))
    body = TABLE_DDL["memory_lessons"]
    for line in body[body.index("(") + 1:body.rindex(")")].splitlines():
        line = line.strip().rstrip(",")
        name = line.split()[0] if line else ""
        if name in _LESSON_V2_COLUMN_NAMES and name not in have:
            yield f"ALTER TABLE memory_lessons ADD COLUMN {line}"


def new_session_key() -> str:
    """session_id fuer memory_sessions aus USMC-Sicht (BACH vergibt eigene)."""
    return f"usmc-{uuid.uuid4().hex}"


def _check_clauses(sql: str):
    """Alle CHECK(...)-Ausdruecke, whitespace-normalisiert und sortiert."""
    clauses = []
    upper = sql.upper()
    start = upper.find("CHECK")
    while start != -1:
        i = sql.index("(", start)
        depth = 0
        for j in range(i, len(sql)):
            depth += {"(": 1, ")": -1}.get(sql[j], 0)
            if depth == 0:
                clauses.append(" ".join(sql[i + 1:j].split()))
                break
        start = upper.find("CHECK", j)
    return sorted(clauses)


def describe_table(conn: sqlite3.Connection, table: str) -> Dict:
    """PRAGMA-Form einer Tabelle; Autoindex-Namen normalisiert."""
    columns = [
        [r[1], r[2], r[3], r[4], r[5]]
        for r in conn.execute(f"PRAGMA table_info({table})")
    ]
    indexes = []
    for r in conn.execute(f"PRAGMA index_list({table})"):
        name = r[1]
        cols = [c[2] for c in conn.execute(f"PRAGMA index_info('{name}')")]
        label = "<auto>" if name.startswith("sqlite_autoindex_") else name
        indexes.append([label, r[2], cols])
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return {
        "columns": columns,
        "indexes": sorted(indexes),
        "checks": _check_clauses(row[0]) if row else [],
    }


def describe_schema(conn: sqlite3.Connection) -> Dict:
    """PRAGMA-Form aller Vereinigungstabellen plus Provenienz-Trigger."""
    result: Dict = {table: describe_table(conn, table) for table in UNION_TABLES}
    result["triggers"] = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name LIKE 'trg_memory_%_session_provenance_%'"
        )
    )
    return result


def load_contract() -> Dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
