"""tools/migration_baseline_check.py: Klassifikation auf einer Kopie, Quelle unberuehrt."""

import sqlite3
import sys
from pathlib import Path

SYSTEM = Path(__file__).parent.parent
sys.path.insert(0, str(SYSTEM / "tools"))

from migration_baseline_check import check


def test_classifies_pending_migrations_on_a_copy(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_done.sql").write_text("SELECT 1;", encoding="utf-8")
    (migrations / "002_present.sql").write_text(
        "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY);", encoding="utf-8")
    (migrations / "003_missing.sql").write_text(
        "CREATE TABLE IF NOT EXISTS extra (id INTEGER PRIMARY KEY);", encoding="utf-8")
    (migrations / "004_dup.sql").write_text("ALTER TABLE items ADD COLUMN id INTEGER;", encoding="utf-8")
    (migrations / "005_py.py").write_text(
        "def run_migration(conn):\n    conn.execute(\"INSERT INTO items DEFAULT VALUES\")\n",
        encoding="utf-8")
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE _migrations (id INTEGER PRIMARY KEY, filename TEXT UNIQUE, applied_at TEXT)")
    conn.execute("INSERT INTO _migrations (filename, applied_at) VALUES ('001_done.sql', 'x')")
    conn.commit()
    conn.close()

    report = check(source, migrations_dir=migrations, system_root=SYSTEM)
    status = {r["migration"]: r["status"] for r in report["results"]}
    assert status == {"002_present.sql": "wirksam", "003_missing.sql": "fehlt",
                      "004_dup.sql": "fehler", "005_py.py": "fehlt"}
    assert "Spalte existiert schon" in report["results"][2]["detail"]
    assert report["source_unchanged"]
    conn = sqlite3.connect(source)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'extra'").fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    conn.close()
