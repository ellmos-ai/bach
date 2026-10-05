-- Migration 053: Failure Trails – negatives Gedächtnis für fehlgeschlagene Werkzeugpfade (Task #1511)
-- Ocean-konformer Shadow (runtime_authority=false): protokolliert Fehler, berechnet
-- exponentielles Backoff und signalisiert Blockaden. Wird von hub/working_memory/failure_trails.py verwendet.
-- Idempotent: reines CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS working_memory_failure_trails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_path TEXT NOT NULL,
    failure_signature TEXT NOT NULL,
    context_hash TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    backoff_until TEXT NOT NULL,
    UNIQUE(tool_path, failure_signature, context_hash)
);

CREATE INDEX IF NOT EXISTS idx_working_memory_failure_trails_tool_path
    ON working_memory_failure_trails(tool_path);
