# -*- coding: utf-8 -*-
"""Gemeinsames Gedaechtnisschema BACH = OCEAN (S1, T-20260920-823767362).

Nur In-Memory-DBs aus schema.sql; keine Bestands-DB wird geoeffnet.
"""

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCHEMA_DIR = Path(__file__).parent.parent / "data" / "schema"
UNION_DIR = SCHEMA_DIR / "memory_union"

# Pins identisch zu ellmos-ai/usmc (usmc/memory_union.py + .contract.json).
MODULE_SHA256 = "59f8282274985c5697e03017911a9c898dbee88d888a65be192edd280c489c72"
CONTRACT_SHA256 = "9eab5303103de3fbd2cdc8eb39e4d246dd50d19ded949764a88a952a75f06739"


def _sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _migration():
    spec = importlib.util.spec_from_file_location("memory_union_043", UNION_DIR / "043_memory_union.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mig():
    return _migration()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((SCHEMA_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript(
        """
        INSERT INTO memory_sessions (id, session_id, started_at, ended_at)
        VALUES (5, 's-alt', '2026-09-01', '2026-09-01'), (6, 's-offen', '2026-09-02', NULL);
        INSERT INTO memory_working (id, type, content) VALUES (40, 'note', 'alt');
        INSERT INTO memory_facts (id, category, key, value) VALUES (70, 'system', 'k', 'v');
        INSERT INTO memory_lessons (id, category, title, solution) VALUES (90, 'g', 'T', 'S');
        INSERT INTO context_triggers (id, trigger_phrase, hint_text) VALUES (15, 'fehler', 'Hinweis');
        INSERT INTO partner_memory_config (partner_id, max_facts) VALUES ('claude', 42);
        DELETE FROM memory_working WHERE id = 40;
        INSERT INTO memory_working (id, type, content) VALUES (30, 'loop', 'bleibt');
        CREATE VIEW v_facts AS SELECT key, value FROM memory_facts;
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_vendored_files_match_usmc_pins():
    assert _sha(UNION_DIR / "memory_union.py") == MODULE_SHA256
    assert _sha(UNION_DIR / "memory_union.contract.json") == CONTRACT_SHA256


def test_not_yet_in_auto_migrations():
    # Der Runner fuehrt migrations/ auf Bestands-DBs automatisch aus; die
    # Aktivierung ist bewusst ein eigener Schritt (S2).
    assert not list((SCHEMA_DIR / "migrations").glob("*memory_union*"))


def test_schema_sql_db_reaches_contract_and_keeps_rows(db, mig):
    mig.run_migration(db)
    assert mig.mu.describe_schema(db) == mig.mu.load_contract()["schema"]
    assert db.execute("SELECT id, content, agent_id FROM memory_working").fetchall() == [(30, "bleibt", "default")]
    assert db.execute("SELECT value FROM v_facts").fetchall() == [("v",)]
    assert db.execute("SELECT status FROM context_triggers WHERE id = 15").fetchone() == ("unknown",)
    assert db.execute("SELECT agent_id, max_facts FROM decay_config").fetchall() == [("claude", 42)]
    # AUTOINCREMENT vergibt die geloeschte ID 40 nicht erneut.
    db.execute("INSERT INTO memory_working (type, content) VALUES ('handoff', 'neu')")
    assert db.execute("SELECT MAX(id) FROM memory_working").fetchone()[0] > 40
    assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_bach_write_paths_keep_their_semantics(db, mig):
    mig.run_migration(db)
    db.execute("INSERT OR REPLACE INTO memory_facts (category, key, value) VALUES ('system', 'k', 'v2')")
    db.execute("INSERT OR IGNORE INTO context_triggers (trigger_phrase, hint_text) VALUES ('fehler', 'x')")
    assert db.execute("SELECT COUNT(*), MAX(value) FROM memory_facts").fetchone() == (1, "v2")
    assert db.execute("SELECT COUNT(*) FROM context_triggers").fetchone() == (1,)
    # Ein anderer Agent darf denselben Schluessel eigenstaendig fuehren.
    db.execute("INSERT INTO memory_facts (category, key, value, agent_id) VALUES ('system', 'k', 'x', 'codex')")
    assert db.execute("SELECT COUNT(*) FROM memory_facts").fetchone() == (2,)


def test_provenance_triggers_survive_rebuild(db, mig):
    stamp = "SELECT created_by_session_id, updated_by_session_id FROM memory_facts WHERE id = 70"
    before = db.execute(stamp).fetchone()
    mig.run_migration(db)
    assert db.execute(stamp).fetchone() == before
    db.execute("INSERT INTO memory_facts (category, key, value) VALUES ('user', 'neu', 'x')")
    assert db.execute("SELECT created_by_session_id FROM memory_facts WHERE key = 'neu'").fetchone() == ("s-offen",)


def test_lessons_gain_v2_contract_and_side_tables(db, mig):
    mig.run_migration(db)
    assert db.execute(
        "SELECT title, source_kind, editorial_status, helpful_count FROM memory_lessons WHERE id = 90"
    ).fetchone() == ("T", "legacy", "legacy", 0)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        "INSERT INTO memory_lesson_feedback (lesson_id, feedback_key, helpful, payload_hash, created_at) "
        "VALUES (90, 'f-1', 1, 'h', 't0')"
    )
    db.execute(
        "INSERT INTO memory_lesson_delivery_batches VALUES ('d-1', 6, 's-offen', 'explicit', 'h', 'default', 't0')"
    )
    db.execute(
        "INSERT INTO memory_lesson_deliveries (lesson_id, delivery_key, session_key, delivery_mode, "
        "feedback_prompt, payload_hash, created_at) VALUES (90, 'd-1', 's-offen', 'explicit', 'p', 'h', 't0')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO memory_lesson_feedback (lesson_id, feedback_key, payload_hash, created_at) "
            "VALUES (999, 'f-2', 'h', 't0')"
        )
    # Idempotenter Lesson-Schluessel wie in USMC.
    db.execute("UPDATE memory_lessons SET source_key = 'src', episode_key = 'ep' WHERE id = 90")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO memory_lessons (category, title, solution, source_key, episode_key) "
            "VALUES ('g', 'T2', 'S2', 'src', 'ep')"
        )


def test_idempotent(db, mig):
    mig.run_migration(db)
    mig.run_migration(db)
    assert mig.mu.describe_schema(db) == mig.mu.load_contract()["schema"]


def test_unknown_column_rolls_back_everything(db, mig):
    db.execute("ALTER TABLE memory_facts ADD COLUMN fremd TEXT")
    db.commit()
    before = db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    fk = db.execute("PRAGMA foreign_keys").fetchone()
    with pytest.raises(mig.MemoryUnionError, match="fremd"):
        mig.run_migration(db)
    assert db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == before
    assert db.execute("PRAGMA foreign_keys").fetchone() == fk
