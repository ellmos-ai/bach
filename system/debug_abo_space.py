import json
import sqlite3
import tempfile
from pathlib import Path
import sys

# Replicate test setup minimally
sys.path.insert(0, str(Path(__file__).resolve().parent / "system"))

from hub.abo import AboHandler
from gui.daemon_service import DaemonService

# Find SYSTEM_ROOT from conftest or test file
from tests.test_abo_handler import SYSTEM_ROOT

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    db_path = tmp_path / "bach.db"
    # create minimal db via init
    handler = AboHandler(SYSTEM_ROOT)
    handler.user_db = db_path
    handler._init_db(dry_run=False)

    # also create scheduler tables as AboHandler._init_db only builds abo_* tables
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            profile_name TEXT,
            description TEXT,
            job_type TEXT NOT NULL,
            schedule TEXT,
            command TEXT NOT NULL,
            script_path TEXT,
            arguments TEXT,
            is_active INTEGER DEFAULT 0,
            timeout_seconds INTEGER DEFAULT 300,
            retry_on_fail INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            started_at TEXT,
            finished_at TEXT,
            duration_seconds REAL,
            result TEXT,
            output TEXT,
            error TEXT,
            triggered_by TEXT
        )
    """)
    conn.commit()
    conn.close()

    source_dir = tmp_path / "Export mit Leerzeichen"
    source_dir.mkdir()
    source = source_dir / "abos.json"
    source.write_text(json.dumps({
        "schema_version": 1,
        "schema": "abotracker-export-v1",
        "items": [
            {
                "name": "Netflix Standard",
                "anbieter": "Netflix",
                "kategorie": "Streaming",
                "betrag_monatlich": 12.99,
                "zahlungsintervall": "monatlich",
                "aktiv": True,
                "erkannt_am": "2026-01-01",
            }
        ]
    }), encoding="utf-8")
    handler.base_path = SYSTEM_ROOT

    import os
    os.environ["BACH_DB"] = str(db_path)

    ok, msg = handler.handle("schedule-import", [str(source), "--interval", "24h"])
    print("schedule ok:", ok, msg)

    service = DaemonService(db_path)
    service.load_jobs()
    job = next(iter(service.jobs))
    print("job:", job)
    print("script_path:", job.script_path)
    print("arguments:", job.arguments)
    result = service.run_job(job, triggered_by="test")
    print("RESULT:")
    print(json.dumps(result, indent=2, default=str))
