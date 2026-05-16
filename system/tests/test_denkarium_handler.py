"""Tests fuer hub/denkarium.py — DenkariumHandler."""
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest

from hub.denkarium import DenkariumHandler


SCHEMA = """
CREATE TABLE IF NOT EXISTS denkarium_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT DEFAULT 'denkarium',
    title TEXT,
    content TEXT,
    category TEXT DEFAULT 'notiz',
    source TEXT DEFAULT 'user',
    mood INTEGER,
    promoted_to TEXT,
    promoted_id INTEGER,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 3,
    assigned_to TEXT,
    dist_type INTEGER DEFAULT 0
);
"""


@pytest.fixture
def denkarium_env(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.close()
    h = DenkariumHandler(tmp_path)
    h.db_path = db_path
    return h, db_path


class TestProperties:
    def test_profile_name(self, denkarium_env):
        h, _ = denkarium_env
        assert h.profile_name == "denkarium"

    def test_target_file(self, denkarium_env):
        h, db = denkarium_env
        assert h.target_file == db

    def test_operations(self, denkarium_env):
        h, _ = denkarium_env
        ops = h.get_operations()
        assert "write" in ops
        assert "read" in ops
        assert "search" in ops
        assert "brainstorm" in ops
        assert "promote" in ops
        assert "categories" in ops
        assert "stats" in ops


class TestHelp:
    def test_empty_operation(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("", [])
        assert ok
        assert "DENKARIUM" in out

    def test_unknown_operation(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("unknown_op", [])
        assert ok
        assert "DENKARIUM" in out

    def test_write_no_args(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("write", [])
        assert ok
        assert "DENKARIUM" in out

    def test_search_no_args(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("search", [])
        assert ok
        assert "DENKARIUM" in out

    def test_promote_no_args(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("promote", [])
        assert ok
        assert "DENKARIUM" in out

    def test_promote_only_id(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("promote", ["1"])
        assert ok
        assert "DENKARIUM" in out


class TestWrite:
    def test_simple_write(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Hallo Welt"])
        assert ok
        assert "gespeichert" in out
        assert "#1" in out

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT * FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row is not None

    def test_write_with_type(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Captains Log", "--type=logbuch"])
        assert ok
        assert "Logbuch" in out

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT entry_type, title FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] == "logbuch"
        assert "Sternzeit" in row[1]

    def test_write_with_category(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Idee!", "--cat=idee"])
        assert ok
        assert "idee" in out

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT category FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] == "idee"

    def test_write_with_title(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Inhalt", "--title=Mein Titel"])
        assert ok

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT title FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] == "Mein Titel"

    def test_write_with_mood(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Guter Tag", "--mood=4"])
        assert ok

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT mood FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 4

    def test_write_invalid_mood_ignored(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Tag", "--mood=abc"])
        assert ok

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT mood FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] is None

    def test_write_logbuch_custom_title(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Eintrag", "--type=logbuch", "--title=Custom"])
        assert ok

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT title FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] == "Custom"

    def test_write_dry_run(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("write", ["Test"], dry_run=True)
        assert ok
        assert "DRY-RUN" in out

        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM denkarium_entries").fetchone()[0]
        conn.close()
        assert count == 0

    def test_write_multiple(self, denkarium_env):
        h, _ = denkarium_env
        h.handle("write", ["Erster"])
        ok, out = h.handle("write", ["Zweiter"])
        assert ok
        assert "#2" in out


class TestRead:
    def _seed(self, db, entries):
        conn = sqlite3.connect(str(db))
        for e in entries:
            conn.execute(
                "INSERT INTO denkarium_entries (entry_type, title, content, category, mood, created_at) VALUES (?,?,?,?,?,?)",
                e
            )
        conn.commit()
        conn.close()

    def test_read_empty(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("read", [])
        assert ok
        assert "Keine Eintraege" in out

    def test_read_entries(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, "Gedanke eins", "notiz", None, "2026-01-01 10:00"),
            ("denkarium", None, "Gedanke zwei", "notiz", None, "2026-01-02 10:00"),
        ])
        ok, out = h.handle("read", [])
        assert ok
        assert "Gedanke" in out
        assert "#1" in out or "#2" in out

    def test_read_type_filter(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, "Gedanke", "notiz", None, "2026-01-01 10:00"),
            ("logbuch", "Sternzeit", "Log", "notiz", None, "2026-01-02 10:00"),
        ])
        ok, out = h.handle("read", ["--type=logbuch"])
        assert ok
        assert "Log" in out
        assert "Gedanke" not in out

    def test_read_category_filter(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, "Normale Notiz", "notiz", None, "2026-01-01 10:00"),
            ("denkarium", None, "Tolle Idee", "idee", None, "2026-01-02 10:00"),
        ])
        ok, out = h.handle("read", ["--cat=idee"])
        assert ok
        assert "Tolle Idee" in out
        assert "Normale Notiz" not in out

    def test_read_limit(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, f"Eintrag {i}", "notiz", None, f"2026-01-{i+1:02d} 10:00")
            for i in range(5)
        ])
        ok, out = h.handle("read", ["--limit=2"])
        assert ok
        lines = [l for l in out.split("\n") if l.strip().startswith("[D]")]
        assert len(lines) == 2

    def test_read_mood_display(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, "Happy", "notiz", 5, "2026-01-01 10:00"),
        ])
        ok, out = h.handle("read", [])
        assert ok
        assert "5/5" in out

    def test_read_long_content_truncated(self, denkarium_env):
        h, db = denkarium_env
        long_text = "A" * 100
        self._seed(db, [
            ("denkarium", None, long_text, "notiz", None, "2026-01-01 10:00"),
        ])
        ok, out = h.handle("read", [])
        assert ok
        assert "..." in out


class TestSearch:
    def _seed(self, db, entries):
        conn = sqlite3.connect(str(db))
        for e in entries:
            conn.execute(
                "INSERT INTO denkarium_entries (entry_type, title, content, category, created_at) VALUES (?,?,?,?,?)",
                e
            )
        conn.commit()
        conn.close()

    def test_search_no_results(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("search", ["xyz"])
        assert ok
        assert "Keine Treffer" in out

    def test_search_by_content(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, "Quantencomputer sind spannend", "notiz", "2026-01-01 10:00"),
            ("denkarium", None, "Wetter ist gut", "notiz", "2026-01-02 10:00"),
        ])
        ok, out = h.handle("search", ["Quanten"])
        assert ok
        assert "1 Treffer" in out
        assert "Quantencomputer" in out

    def test_search_by_title(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", "Wichtiger Titel", "Inhalt", "notiz", "2026-01-01 10:00"),
        ])
        ok, out = h.handle("search", ["Wichtiger"])
        assert ok
        assert "1 Treffer" in out

    def test_search_by_category(self, denkarium_env):
        h, db = denkarium_env
        self._seed(db, [
            ("denkarium", None, "Inhalt", "spezial_kat", "2026-01-01 10:00"),
        ])
        ok, out = h.handle("search", ["spezial_kat"])
        assert ok
        assert "1 Treffer" in out


class TestBrainstorm:
    def test_brainstorm(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("brainstorm", ["KI-Ethik"])
        assert ok
        assert "Brainstorm" in out
        assert "KI-Ethik" in out
        assert "#1" in out

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT entry_type, title, category FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert row[0] == "denkarium"
        assert "KI-Ethik" in row[1]
        assert row[2] == "brainstorm"

    def test_brainstorm_dry_run(self, denkarium_env):
        h, db = denkarium_env
        ok, out = h.handle("brainstorm", ["Test"], dry_run=True)
        assert ok
        assert "DRY-RUN" in out

        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM denkarium_entries").fetchone()[0]
        conn.close()
        assert count == 0


class TestPromote:
    def _seed_entry(self, db):
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO denkarium_entries (entry_type, title, content, category, created_at) VALUES (?,?,?,?,?)",
            ("denkarium", "Mein Titel", "Mein Inhalt", "notiz", "2026-01-01 10:00")
        )
        conn.commit()
        conn.close()

    def test_promote_to_task(self, denkarium_env):
        h, db = denkarium_env
        self._seed_entry(db)
        ok, out = h.handle("promote", ["1", "task"])
        assert ok
        assert "Task" in out
        assert "#1" in out

        conn = sqlite3.connect(str(db))
        task = conn.execute("SELECT title, description FROM tasks WHERE id=1").fetchone()
        entry = conn.execute("SELECT promoted_to, promoted_id FROM denkarium_entries WHERE id=1").fetchone()
        conn.close()
        assert task[0] == "Mein Titel"
        assert task[1] == "Mein Inhalt"
        assert entry[0] == "task"
        assert entry[1] == 1

    def test_promote_to_wiki(self, denkarium_env):
        h, db = denkarium_env
        self._seed_entry(db)
        ok, out = h.handle("promote", ["1", "wiki"])
        assert ok
        assert "Wiki" in out

    def test_promote_invalid_id(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("promote", ["abc", "task"])
        assert not ok
        assert "Ungueltig" in out

    def test_promote_invalid_target(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("promote", ["1", "email"])
        assert not ok
        assert "task" in out or "wiki" in out

    def test_promote_not_found(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("promote", ["999", "task"])
        assert not ok
        assert "nicht gefunden" in out

    def test_promote_dry_run(self, denkarium_env):
        h, db = denkarium_env
        self._seed_entry(db)
        ok, out = h.handle("promote", ["1", "task"], dry_run=True)
        assert ok
        assert "DRY-RUN" in out

        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert count == 0

    def test_promote_entry_without_title_uses_content(self, denkarium_env):
        h, db = denkarium_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO denkarium_entries (entry_type, content, category, created_at) VALUES (?,?,?,?)",
            ("denkarium", "Langer Inhalt der als Titel dient", "notiz", "2026-01-01 10:00")
        )
        conn.commit()
        conn.close()

        ok, out = h.handle("promote", ["1", "task"])
        assert ok

        conn = sqlite3.connect(str(db))
        task = conn.execute("SELECT title FROM tasks WHERE id=1").fetchone()
        conn.close()
        assert task[0] == "Langer Inhalt der als Titel dient"


class TestCategories:
    def test_categories_empty(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("categories", [])
        assert ok
        assert "Keine Eintraege" in out

    def test_categories_with_data(self, denkarium_env):
        h, db = denkarium_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO denkarium_entries (entry_type, content, category, created_at) VALUES (?,?,?,?)",
            ("denkarium", "A", "idee", "2026-01-01")
        )
        conn.execute(
            "INSERT INTO denkarium_entries (entry_type, content, category, created_at) VALUES (?,?,?,?)",
            ("logbuch", "B", "notiz", "2026-01-02")
        )
        conn.commit()
        conn.close()

        ok, out = h.handle("categories", [])
        assert ok
        assert "idee" in out
        assert "notiz" in out
        assert "Denkarium" in out
        assert "Logbuch" in out


class TestStats:
    def test_stats_empty(self, denkarium_env):
        h, _ = denkarium_env
        ok, out = h.handle("stats", [])
        assert ok
        assert "Gesamt:    0" in out

    def test_stats_with_data(self, denkarium_env):
        h, db = denkarium_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO denkarium_entries (entry_type, content, category, created_at) VALUES (?,?,?,?)",
            ("denkarium", "A", "notiz", "2026-01-01 10:00")
        )
        conn.execute(
            "INSERT INTO denkarium_entries (entry_type, content, category, created_at, promoted_to) VALUES (?,?,?,?,?)",
            ("logbuch", "B", "notiz", "2026-01-02 10:00", "task")
        )
        conn.commit()
        conn.close()

        ok, out = h.handle("stats", [])
        assert ok
        assert "Gesamt:    2" in out
        assert "Logbuch:   1" in out
        assert "Denkarium: 1" in out
        assert "Befoerdert: 1" in out
        assert "2026-01-01" in out
        assert "2026-01-02" in out
