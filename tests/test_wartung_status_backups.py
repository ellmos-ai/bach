import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = ROOT / "system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


def test_wartung_status_detects_canonical_userdata_zip_backups_and_verified_daemon(monkeypatch, tmp_path):
    from gui import daemon_identity, server
    from hub import bach_paths

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE scan_runs (id INTEGER PRIMARY KEY, started_at TEXT, tasks_created INTEGER)")
    conn.execute("CREATE TABLE memory_working (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE memory_lessons (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO memory_working VALUES (1), (2)")
    conn.execute("INSERT INTO memory_lessons VALUES (1)")
    conn.commit()
    conn.close()

    def fake_get_user_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    canonical_backups = tmp_path / "canonical_backups"
    userdata_dir = canonical_backups / "userdata"
    userdata_dir.mkdir(parents=True)
    zip_file = userdata_dir / "userdata_2026-11-26_201401.zip"
    zip_file.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    fake_bach_dir = tmp_path / "bach_system"
    fake_bach_dir.mkdir(parents=True)

    monkeypatch.setattr(server, "get_user_db", fake_get_user_db)
    monkeypatch.setattr(server, "BACH_DIR", fake_bach_dir)
    monkeypatch.setattr(bach_paths, "BACKUPS_DIR", canonical_backups)
    monkeypatch.setattr(
        daemon_identity,
        "observe_identity",
        lambda *_args, **_kwargs: {"running": True, "pid": 79528, "identity": "verified"},
    )

    result = asyncio.run(server.get_wartung_status())

    assert result["backup"]["backup_count"] == 1
    assert result["backup"]["last_backup"] is not None
    assert result["daemon"]["running"] is True
    assert result["memory"]["working_count"] == 2
    assert result["memory"]["lessons_count"] == 1
