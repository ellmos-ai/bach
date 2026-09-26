"""memory_sync / claude_md_sync lesen das gemeinsame Gedaechtnis memory_*.

shared_memory_* ist seit 2026-02 eingefroren (T-20260920-823767362); die Leser
bevorzugten es und gaben alte Lessons aus. Nur Temp-DBs aus schema.sql.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).parent.parent
SCHEMA = SYSTEM / "data" / "schema" / "schema.sql"
sys.path.insert(0, str(SYSTEM / "tools"))

from claude_md_sync import ClaudeMdSync
from memory_sync import MemoryGenerator


def _migration():
    spec = importlib.util.spec_from_file_location(
        "memory_union_043", SYSTEM / "data" / "schema" / "migrations" / "043_memory_union.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db(path: Path, union: bool) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO memory_sessions (session_id, started_at) VALUES ('s', '2026-09-26')")
    if union:
        _migration().run_migration(conn)
    conn.execute(
        "INSERT INTO memory_lessons (category, severity, title, solution, is_active) "
        "VALUES ('g', 'high', 'Aktuelle Lesson', 'aus memory_lessons', 1)")
    if union:
        conn.execute(
            "INSERT INTO memory_lessons (category, severity, title, solution, is_active, visibility) "
            "VALUES ('g', 'critical', 'Private Lesson', 'geheim', 1, 'private')")
        conn.execute(
            "INSERT INTO memory_lessons (category, severity, title, solution, is_active, agent_id) "
            "VALUES ('g', 'medium', 'Codex-Lesson', 'fremd', 1, 'codex')")
    # Gen 2 wie nach Migration 024 (eingefroren), nicht in schema.sql.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shared_memory_lessons (id INTEGER PRIMARY KEY, category TEXT, "
        "severity TEXT, title TEXT, problem TEXT, solution TEXT, trigger_words TEXT, is_active INTEGER, "
        "visibility TEXT, agent_id TEXT, times_shown INTEGER DEFAULT 0, created_at TEXT)")
    conn.execute(
        "INSERT INTO shared_memory_lessons (category, severity, title, solution, is_active, visibility, agent_id) "
        "VALUES ('g', 'critical', 'Eingefrorene Lesson', 'alt', 1, 'shared', 'claude')")
    conn.commit()
    conn.close()
    return path


@pytest.mark.parametrize("union", [False, True])
def test_top_lessons_come_from_memory_lessons(tmp_path, union):
    titles = [row["title"] for row in MemoryGenerator(_db(tmp_path / "bach.db", union)).get_top_lessons()]
    assert "Aktuelle Lesson" in titles
    assert "Eingefrorene Lesson" not in titles
    assert "Private Lesson" not in titles


@pytest.mark.parametrize("union", [False, True])
def test_claude_md_block_uses_memory_lessons_and_tags_foreign_agents(tmp_path, union):
    sync = ClaudeMdSync(tmp_path)
    sync.db_path = _db(tmp_path / "bach.db", union)
    block = sync._generate_bach_block()
    assert "Aktuelle Lesson" in block
    assert "Eingefrorene Lesson" not in block
    assert "Private Lesson" not in block
    assert "`[default]`" not in block
    if union:
        assert "Codex-Lesson `[codex]`" in block
