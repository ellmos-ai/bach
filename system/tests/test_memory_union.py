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
MODULE_SHA256 = "229c53eb476517c7294b2030a8cd71de420f9fd80b1ba9995c7074c276f3c200"
CONTRACT_SHA256 = "d3b5d051924cd19b18c6e891b462d2cbfc46fd69e21feccd9e5439b348f0d851"


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
