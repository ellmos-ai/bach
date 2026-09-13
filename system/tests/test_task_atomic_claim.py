# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests fuer atomaren Task-Claim gegen Doppelausfuehrung (T-20260913-709822598).

Verifiziert:
1. Zwei nebenlaeufige Claim-Versuche auf denselben Task: genau einer gewinnt (True),
   der andere verliert (False), Task-Status ist danach genau einmal 'in_progress'.
2. Ein abgelaufener Claim (altes claimed_at aelter als lease_seconds) ist erneut claimbar.
3. Ein aktiver, nicht abgelaufener Claim blockt andere Taktgeber.
4. Ein bereits 'done' / 'completed' / 'cancelled' / 'blocked' Task ist NICHT claimbar.
5. release_claim setzt einen in_progress-Task zurueck auf 'open' und loescht claimed_by/claimed_at,
   ruehrt aber 'done'-Tasks nicht an.
6. CLI `bach task claim` und `bach task release` ueber TaskHandler.
7. PUT /api/tasks/{id} mit status=in_progress gegen einen bereits beanspruchten Task
   liefert {"status": "claim_failed", "success": false} bei HTTP 200 via TestClient.
"""

import concurrent.futures
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.task_audit import claim_task_atomic, release_claim
from hub._services.task_schema import ensure_task_claim_columns, ensure_task_due_date

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


def _create_task_db(db_path: Path) -> sqlite3.Connection:
    """Initialisiert eine Test-Datenbank mit den noetigen Tabellen."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'open',
            category TEXT DEFAULT 'general',
            project TEXT,
            assigned_to TEXT DEFAULT 'user',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            due_date TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn


@pytest.fixture
def task_db(tmp_path):
    """Fixture fuer eine isolierte Test-Datenbankdatei."""
    db_path = tmp_path / "data" / "bach.db"
    conn = _create_task_db(db_path)
    conn.close()
    return db_path


class TestAtomicClaimCore:
    """Core-Tests fuer claim_task_atomic und release_claim."""

    def test_concurrent_claims_only_one_wins(self, task_db):
        """Zwei nebenlaeufige Threads versuchen denselben Task zu claimen -- genau einer gewinnt."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute("INSERT INTO tasks (title, status) VALUES ('Race Task', 'open')")
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        def try_claim(worker_id: str) -> bool:
            c = sqlite3.connect(str(task_db), timeout=15.0)
            try:
                ok = claim_task_atomic(c, task_id, worker_id, lease_seconds=1800)
                if ok:
                    c.commit()
                return ok
            finally:
                c.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(try_claim, "worker-alpha")
            f2 = executor.submit(try_claim, "worker-beta")
            results = [f1.result(), f2.result()]

        # Genau einer gewinnt, der andere verliert
        assert sorted(results) == [False, True]

        # Task in DB pruefen: genau einmal in_progress, claimed_by gesetzt
        check_conn = sqlite3.connect(str(task_db))
        row = check_conn.execute("SELECT status, claimed_by, claimed_at, started_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        check_conn.close()

        assert row[0] == "in_progress"
        assert row[1] in ("worker-alpha", "worker-beta")
        assert row[2] is not None
        assert row[3] is not None

    def test_expired_lease_is_reclaimable(self, task_db):
        """Ein abgelaufener Claim (aelter als lease_seconds) kann von neuem Worker uebernommen werden."""
        conn = sqlite3.connect(str(task_db))
        old_time = (datetime.now() - timedelta(seconds=3600)).isoformat()
        cursor = conn.execute(
            """INSERT INTO tasks (title, status, claimed_by, claimed_at)
               VALUES ('Expired Task', 'in_progress', 'worker-old', ?)""",
            (old_time,),
        )
        task_id = cursor.lastrowid
        conn.commit()

        # Neuer Claim mit 1800s Lease
        ok = claim_task_atomic(conn, task_id, "worker-new", lease_seconds=1800)
        conn.commit()
        assert ok is True

        row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row[0] == "in_progress"
        assert row[1] == "worker-new"
        conn.close()

    def test_unexpired_lease_blocks_other_worker(self, task_db):
        """Ein noch aktiver Claim blockiert andere Worker."""
        conn = sqlite3.connect(str(task_db))
        now_str = datetime.now().isoformat()
        cursor = conn.execute(
            """INSERT INTO tasks (title, status, claimed_by, claimed_at)
               VALUES ('Active Task', 'in_progress', 'worker-active', ?)""",
            (now_str,),
        )
        task_id = cursor.lastrowid
        conn.commit()

        ok = claim_task_atomic(conn, task_id, "worker-intruder", lease_seconds=1800)
        assert ok is False

        row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row[0] == "in_progress"
        assert row[1] == "worker-active"
        conn.close()

    @pytest.mark.parametrize("terminal_status", ["done", "completed", "cancelled", "blocked"])
    def test_terminal_and_blocked_tasks_not_claimable(self, task_db, terminal_status):
        """Bereits erledigte, abgebrochene oder blockierte Tasks duerfen nicht geclaimt werden."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute(
            "INSERT INTO tasks (title, status) VALUES ('Non-claimable', ?)",
            (terminal_status,),
        )
        task_id = cursor.lastrowid
        conn.commit()

        ok = claim_task_atomic(conn, task_id, "worker-greedy")
        assert ok is False

        row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row[0] == terminal_status
        assert row[1] is None
        conn.close()

    def test_release_claim_resets_in_progress_to_open(self, task_db):
        """release_claim setzt 'in_progress'-Tasks auf 'open' zurueck und loescht claimed_by/at."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute(
            """INSERT INTO tasks (title, status, claimed_by, claimed_at)
               VALUES ('To Release', 'in_progress', 'worker-busy', datetime('now'))"""
        )
        task_id = cursor.lastrowid
        conn.commit()

        ok = release_claim(conn, task_id, "worker-busy")
        conn.commit()
        assert ok is True

        row = conn.execute(
            "SELECT status, claimed_by, claimed_at FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        assert row[0] == "open"
        assert row[1] is None
        assert row[2] is None
        conn.close()

    def test_release_claim_does_not_affect_done_tasks(self, task_db):
        """release_claim auf erledigten Task aendert nichts und gibt False zurueck."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute(
            "INSERT INTO tasks (title, status, completed_at) VALUES ('Done Task', 'done', datetime('now'))"
        )
        task_id = cursor.lastrowid
        conn.commit()

        ok = release_claim(conn, task_id, "worker-busy")
        assert ok is False

        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row[0] == "done"
        conn.close()

    def test_stale_release_rejected_for_wrong_owner(self, task_db):
        """Befund 2: Stale Release von Worker A darf einen von Worker B neu geclaimten Task nicht freigeben."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute(
            """INSERT INTO tasks (title, status, claimed_by, claimed_at)
               VALUES ('Contested Task', 'in_progress', 'worker-B', datetime('now'))"""
        )
        task_id = cursor.lastrowid
        conn.commit()

        # Worker A versucht verspaetet freizugeben -> abgelehnt!
        ok = release_claim(conn, task_id, "worker-A")
        assert ok is False

        # Task bleibt in_progress bei Worker B
        row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row[0] == "in_progress"
        assert row[1] == "worker-B"

        # Worker B darf freigeben
        ok_b = release_claim(conn, task_id, "worker-B")
        assert ok_b is True
        row_b = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row_b[0] == "open"
        assert row_b[1] is None
        conn.close()

    def test_claim_zero_microsecond_consistency_and_lease_cutoff(self, task_db):
        """Befund 1+3: Konsistente Zeitvergleiche auch bei Mikrosekunden = 0 vs > 0."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute("INSERT INTO tasks (title, status) VALUES ('Microsecond Task', 'open')")
        task_id = cursor.lastrowid
        conn.commit()

        # 1. Claim mit Zeitstempel ohne Mikrosekunden (.000000)
        t_base = "2026-09-13T20:50:00"
        ok1 = claim_task_atomic(conn, task_id, "worker-1", now=t_base, lease_seconds=1800)
        conn.commit()
        assert ok1 is True

        # In DB muss der Zeitstempel auf volle Mikrosekunden normalisiert sein (.000000)
        row1 = conn.execute("SELECT claimed_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row1[0] == "2026-09-13T20:50:00.000000"

        # 2. Zweiter Claim-Versuch wenige Millisekunden spaeter in derselben Sekunde:
        # Muss False liefern (Claim ist noch frisch, NICHT abgelaufen)
        t_shortly_after = "2026-09-13T20:50:00.005000"
        ok2 = claim_task_atomic(conn, task_id, "worker-2", now=t_shortly_after, lease_seconds=1800)
        assert ok2 is False

        # 3. Kuenstlich in die Vergangenheit gesetzter claimed_at (1801s her -> abgelaufen)
        t_expired = "2026-09-13T20:19:59.000000"
        conn.execute("UPDATE tasks SET claimed_at = ? WHERE id = ?", (t_expired, task_id))
        conn.commit()

        # Jetzt muss ein neuer Claim mit now=t_base erfolgreich sein (True)
        ok3 = claim_task_atomic(conn, task_id, "worker-3", now=t_base, lease_seconds=1800)
        conn.commit()
        assert ok3 is True
        row3 = conn.execute("SELECT claimed_by, claimed_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row3[0] == "worker-3"
        assert row3[1] == "2026-09-13T20:50:00.000000"
        conn.close()


class TestTaskCLIClaim:
    """CLI-Tests fuer `bach task claim` und `bach task release`."""

    def test_cli_claim_and_release(self, task_db, tmp_path):
        from hub.task import TaskHandler

        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute("INSERT INTO tasks (title, status) VALUES ('CLI Task', 'open')")
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        handler = TaskHandler(tmp_path)
        handler.db_path = task_db

        # 1. Erfolgreicher Claim
        ok, msg = handler.handle("claim", [str(task_id), "--by", "worker:test"])
        assert ok is True
        assert "[OK]" in msg
        assert f"Task {task_id} beansprucht von worker:test" in msg

        # 2. Zweiter Claim scheitert mit CONFLICT
        ok2, msg2 = handler.handle("claim", [str(task_id), "--by", "worker:other"])
        assert ok2 is False
        assert "[CONFLICT]" in msg2

        # 3. Claim ohne --by ist Usage-Fehler
        ok3, msg3 = handler.handle("claim", [str(task_id)])
        assert ok3 is False
        assert "Usage-Fehler" in msg3 or "Usage" in msg3

        # 4. Release ohne --by ist Usage-Fehler
        ok_rel_err, msg_rel_err = handler.handle("release", [str(task_id)])
        assert ok_rel_err is False
        assert "Usage-Fehler" in msg_rel_err or "Usage" in msg_rel_err

        # 5. Release mit falschem --by scheitert
        ok_rel_wrong, msg_rel_wrong = handler.handle("release", [str(task_id), "--by", "worker:wrong"])
        assert ok_rel_wrong is False
        assert "[WARN]" in msg_rel_wrong

        # 6. Release mit korrektem --by gibt Task frei
        ok_rel, msg_rel = handler.handle("release", [str(task_id), "--by", "worker:test"])
        assert ok_rel is True
        assert "[OK]" in msg_rel

        # 7. Danach kann worker:other claimen
        ok4, msg4 = handler.handle("claim", [str(task_id), "--by", "worker:other"])
        assert ok4 is True
        assert "[OK]" in msg4


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestServerTaskClaimAPI:
    """FastAPI TestClient-Tests fuer PUT /api/tasks/{task_id} Claim-Verhalten."""

    @pytest.fixture
    def client(self, task_db, tmp_path, monkeypatch):
        import gui.server as srv
        monkeypatch.setattr(srv, "BACH_DB", task_db)
        monkeypatch.setattr(srv, "USER_DB", task_db)
        monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(srv, "BACH_DIR", tmp_path)
        monkeypatch.setattr(srv, "GUI_DIR", tmp_path / "gui")

        return TestClient(srv.app, raise_server_exceptions=False)

    def test_put_api_claim_conflict_returns_claim_failed_http_200(self, client, task_db):
        """PUT /api/tasks/{id} mit status=in_progress gegen beanspruchten Task liefert claim_failed bei HTTP 200."""
        # Task in DB anlegen
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute("INSERT INTO tasks (title, status) VALUES ('API Race Task', 'open')")
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Erster Claim gewinnt
        resp1 = client.put(f"/api/tasks/{task_id}", json={"status": "in_progress", "changed_by": "worker-winner"})
        assert resp1.status_code == 200
        assert resp1.json().get("status") == "updated"

        # Zweiter Claim gegen denselben Task verliert mit HTTP 200 und status='claim_failed'
        resp2 = client.put(f"/api/tasks/{task_id}", json={"status": "in_progress", "changed_by": "idle-worker"})
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2.get("status") == "claim_failed"
        assert data2.get("success") is False

        # Pruefen, dass Task weiterhin worker-winner gehoert
        conn = sqlite3.connect(str(task_db))
        row = conn.execute("SELECT claimed_by, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        assert row[0] == "worker-winner"
        assert row[1] == "in_progress"

    def test_put_api_owner_can_update_fields_while_in_progress(self, client, task_db):
        """Der eigentliche Claim-Owner kann andere Felder aktualisieren, waehrend der Task in_progress ist."""
        conn = sqlite3.connect(str(task_db))
        cursor = conn.execute("INSERT INTO tasks (title, status) VALUES ('Owner Edit Task', 'open')")
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Claimen durch worker-1
        client.put(f"/api/tasks/{task_id}", json={"status": "in_progress", "changed_by": "worker-1"})

        # worker-1 editiert Beschreibung und Prioritaet
        resp = client.put(
            f"/api/tasks/{task_id}",
            json={"priority": "P1", "description": "Neu", "status": "in_progress", "changed_by": "worker-1"},
        )
        assert resp.status_code == 200
        assert resp.json().get("status") == "updated"

        conn = sqlite3.connect(str(task_db))
        row = conn.execute("SELECT priority, description, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        assert row[0] == "P1"
        assert row[1] == "Neu"
        assert row[2] == "worker-1"
