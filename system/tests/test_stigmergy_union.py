"""Stigmergy legt Pheromone im gemeinsamen Gedaechtnis memory_working ab (ab
BACH-Migration 043, T-20260920-823767362); davor in der Gen-2-Tabelle."""

import importlib.util
import sqlite3
from pathlib import Path

SYSTEM = Path(__file__).parent.parent
SCHEMA = SYSTEM / "data" / "schema" / "schema.sql"

from hub._services.stigmergy.stigmergy_api import StigmergyAPI


def _db(path: Path, union: bool) -> str:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(
        "CREATE TABLE shared_memory_working (id INTEGER PRIMARY KEY, agent_id TEXT, session_id TEXT, "
        "type TEXT, content TEXT, priority INTEGER, is_active INTEGER, created_at TEXT, updated_at TEXT, "
        "tags TEXT, related_to TEXT)")
    conn.execute("INSERT INTO memory_sessions (session_id, started_at) VALUES ('s', '2026-09-26')")
    if union:
        spec = importlib.util.spec_from_file_location(
            "m043", SYSTEM / "data" / "schema" / "memory_union" / "043_memory_union.py")
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        mig.run_migration(conn)
    conn.commit()
    conn.close()
    return str(path)


def _count(db, table):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tags = '[\"stigmergy\"]'").fetchone()[0]
    finally:
        conn.close()


def test_pheromones_live_in_memory_working_after_043(tmp_path):
    db = _db(tmp_path / "bach.db", union=True)
    api = StigmergyAPI(db, agent_id="codex")
    assert api.deposit("approach_a", 0.8) and api.deposit("approach_b", 0.3)
    assert (_count(db, "memory_working"), _count(db, "shared_memory_working")) == (2, 0)
    assert api.get_best_path("approach_") == "approach_a"
    assert api.evaporate(decay_rate=0.9) >= 1


def test_legacy_table_before_043(tmp_path):
    db = _db(tmp_path / "bach.db", union=False)
    assert StigmergyAPI(db).deposit("approach_a", 0.5)
    assert (_count(db, "memory_working"), _count(db, "shared_memory_working")) == (0, 1)
