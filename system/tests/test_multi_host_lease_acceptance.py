# SPDX-License-Identifier: MIT
"""Isolierte Mehrhost-, Ablauf- und Fencing-Abnahmesuite (BACH #1723, T793 LEASE 4/4).

Akzeptanzkriterien aus Task #1723 / Sammelaufgabe #1696 (Ticket T-20261003-793817309):
1. Kein Doppel-Claim im Mehrhost-Rennen: Parallele Clients/Threads versuchen denselben
   Task zeitgleich zu claimen; exakt einer gewinnt (LeaseAck), alle anderen werden abgewiesen.
2. Gemeinsame Fristen (issued_at/expires_at), Verlängerung nur bei erreichbarem Lead
   und Deckelung auf maximale Lebensdauer, Release/Return mit sauberer Rückabwicklung.
3. Ablauf und Reclaimability: Nach Ablauf der Frist kann ein neuer Bearbeiter den Task
   mit inkrementiertem claim_fence (Fence 2) übernehmen.
4. Stale-Fence & Write-Protection: Ein Client mit abgelaufenem oder altem Fencing-Beleg
   kann weder verlängern noch releasen noch generische Statuswechsel ausführen.
5. End-to-End Stack-Readback: Prüfung über TaskDB, TaskLeaseClient, CLI (bach task lease*),
   bach_api und Trithon-Dispatch auf rein isolierten temporären Testdatenbanken.
"""

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.task_lease import (
    LeaseConfig,
    acquire_lease,
    ensure_task_lease_schema,
    parse_ts,
    renew_lease,
)
from hub._services.task_lease_client import (
    LeaseAck,
    LeaseDeniedError,
    LeaseOfflineDeadlineExceeded,
    LeaseStaleFenceError,
    TaskLeaseClient,
)
from hub.task_audit import (
    LeaseRequired,
    apply_task_field_changes,
)

try:
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


T0 = datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc)
CFG = LeaseConfig(
    default_profile="M",
    profiles={
        "S": (300, 1800),
        "M": (600, 3600),
        "L": (1800, 14400),
        "XL": (3600, 28800),
    },
    creator_window_seconds=0,
)


def _create_isolated_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT DEFAULT 'M',
            status TEXT DEFAULT 'open',
            category TEXT DEFAULT 'general',
            assigned_to TEXT DEFAULT 'bach',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            source TEXT,
            estimated_minutes INTEGER,
            actual_minutes INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            due_date TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE task_history (
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
    ensure_task_lease_schema(conn)
    conn.commit()
    conn.close()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_task(
    conn: sqlite3.Connection,
    title: str = "Acceptance-Task",
    status: str = "open",
    **kwargs,
) -> int:
    cols = {"title": title, "status": status, **kwargs}
    names = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO tasks ({names}) VALUES ({placeholders})", tuple(cols.values())
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture
def test_db(tmp_path, monkeypatch) -> Path:
    # Creator-Window für alle Akzeptanztests standardmässig deaktivieren (reine Worker-Rennen)
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    db_file = tmp_path / "acceptance_test.db"
    _create_isolated_db(db_file)
    return db_file


# ===========================================================================
# 1. Mehrhost-Concurrency-Rennen (Garantie: exakt 1 Gewinner)
# ===========================================================================


class TestMultiHostConcurrencyRace:
    """Weist nach, dass parallele Claim-Versuche verschiedener Hosts deterministisch
    genau einen Gewinner liefern und kein Doppel-Claim entstehen kann."""

    def test_concurrent_threads_race_exact_one_winner(self, test_db):
        """Simuliert 5 Hosts (Mac Studio, Laptop, Workstation, Mac Mini, Worker-5),
        die synchronisiert im selben Millisekunden-Fenster versuchen, denselben
        Task zu claimen."""
        with _connect(test_db) as conn:
            tid = _insert_task(conn, title="MultiHost-Race-Task")

        hosts = [
            ("opus@Mac-Studio", "Mac-Studio"),
            ("gemini@ASUS-GEI", "ASUS-GEI"),
            ("codex@WORKSTATION-LG", "WORKSTATION-LG"),
            ("kimi@Mac-Mini", "Mac-Mini"),
            ("worker5@Cloud-Host", "Cloud-Host"),
        ]
        n_workers = len(hosts)
        barrier = threading.Barrier(n_workers)

        results: list[dict[str, Any]] = []
        lock = threading.Lock()

        def worker_attempt(worker_id: str, host: str):
            client_conn = _connect(test_db)
            barrier.wait()  # Alle Worker starten exakt zeitgleich
            client = TaskLeaseClient(conn=client_conn)
            try:
                clean_worker_token = worker_id.replace("@", ".")
                req_id = f"req-{clean_worker_token}-{uuid.uuid4().hex}"
                ack = client.acquire(
                    tid,
                    worker_id=worker_id,
                    host=host,
                    ttl_profile="M",
                    request_id=req_id,
                )
                with lock:
                    results.append({"worker": worker_id, "success": True, "ack": ack})
            except LeaseDeniedError as exc:
                with lock:
                    results.append(
                        {
                            "worker": worker_id,
                            "success": False,
                            "error": str(exc),
                            "reason": exc.reason,
                        }
                    )
            finally:
                client_conn.close()

        threads = [
            threading.Thread(target=worker_attempt, args=(w, h)) for w, h in hosts
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r["success"]]
        denials = [r for r in results if not r["success"]]

        # GATE: Exakt ein Gewinner
        assert len(successes) == 1, (
            f"Erwartet exakt 1 Gewinner, erhalten: {len(successes)}"
        )
        assert len(denials) == n_workers - 1

        winner = successes[0]
        winner_ack: LeaseAck = winner["ack"]
        assert winner_ack.task_id == tid
        assert winner_ack.fence == 1

        # Alle Abgewiesenen müssen "held" oder "conflict" als Grund melden
        for d in denials:
            assert d["reason"] in ("held", "conflict")

        # Prüfung des DB-Endzustands
        with _connect(test_db) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
            assert row["status"] == "in_progress"
            assert row["claimed_by"] == winner["worker"]
            assert row["claim_fence"] == 1
            assert row["claim_id"] == winner_ack.lease_id

            # History enthält exakt einen lease_acquire
            history = conn.execute(
                "SELECT * FROM task_history WHERE task_id = ? AND action = 'lease_acquire'",
                (tid,),
            ).fetchall()
            assert len(history) == 1
            assert history[0]["changed_by"] == winner["worker"]

    @pytest.mark.skipif(
        not FASTAPI_AVAILABLE, reason="FastAPI für HTTP-Test erforderlich"
    )
    def test_concurrent_http_api_race(self, test_db, tmp_path, monkeypatch):
        """Simuliert parallele HTTP-Anfragen über das REST-Interface der Lead-API."""
        import gui.server as srv

        monkeypatch.setattr(srv, "BACH_DB", test_db)
        monkeypatch.setattr(srv, "USER_DB", test_db)
        monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(srv, "BACH_DIR", tmp_path)
        monkeypatch.setattr(srv, "GUI_DIR", tmp_path / "gui")
        monkeypatch.setattr(
            srv, "validate_token", lambda token: {"id": 1, "name": "race-device"}
        )
        monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")

        client = TestClient(
            srv.app,
            raise_server_exceptions=False,
            headers={"Authorization": "Bearer race-token"},
        )

        with _connect(test_db) as conn:
            tid = _insert_task(conn, title="HTTP-Race-Task")

        workers = [
            ("gemini@ASUS-GEI", "ASUS-GEI"),
            ("opus@Mac-Studio", "Mac-Studio"),
            ("codex@WORKSTATION-LG", "WORKSTATION-LG"),
        ]

        def post_lease(worker_id: str, host: str):
            clean_token = worker_id.replace("@", ".")
            payload = {
                "worker_id": worker_id,
                "host": host,
                "request_id": f"req-{clean_token}-{uuid.uuid4().hex}",
                "ttl_profile": "M",
            }
            return client.post(f"/api/tasks/{tid}/lease", json=payload)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(post_lease, w, h) for w, h in workers]
            responses = [f.result() for f in futures]

        statuses = [r.status_code for r in responses]
        assert statuses.count(200) == 1, (
            f"Erwartet exakt einen HTTP 200, erhalten: {statuses}"
        )
        assert statuses.count(409) == 2

        # 409-Antworten dürfen keine fremde lease_id leaken
        winner_data = next(r.json() for r in responses if r.status_code == 200)
        winner_lease_id = winner_data["lease_id"]
        for r in responses:
            if r.status_code == 409:
                assert winner_lease_id not in r.text
                assert r.json().get("reason") in ("held", "conflict")


# ===========================================================================
# 2. Lifecycle, Fristen, Verlängerungs-Deckel & Offline-Deadline
# ===========================================================================


class TestLeaseLifecycleAndDeadlines:
    """Prüft Fristen-Konsistenz, Deckelung der Lebensdauer und Offline-Schutz."""

    def test_shared_issued_and_expires_at(self, test_db):
        """Belegt übereinstimmende Fristen zwischen Lead-DB und Client-ACK."""
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)
            now = T0
            ack = client.acquire(
                tid,
                worker_id="gemini@ASUS-GEI",
                host="ASUS-GEI",
                ttl_profile="S",
                config=CFG,
                now=now,
            )

            # DB-Zeile gegenlesen
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
            assert row["claim_issued_at"] == ack.issued_at
            assert row["claim_expires_at"] == ack.expires_at

            # Client-Prüfung
            assert ack.ttl_seconds == 300
            diff = (parse_ts(ack.expires_at) - parse_ts(ack.issued_at)).total_seconds()
            assert diff == 300

    def test_renewal_capped_at_max_lifetime(self, test_db):
        """Verlängerungen sind auf die im Profil definierte max_total begrenzt."""
        cfg_custom = LeaseConfig(
            default_profile="T",
            profiles={"T": (100, 200)},  # 100s TTL, max 200s total
            creator_window_seconds=0,
        )
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            res1 = acquire_lease(
                conn,
                tid,
                worker_id="gemini@ASUS-GEI",
                host="ASUS-GEI",
                ttl_profile="T",
                config=cfg_custom,
                now=T0,
                request_id="req-" + uuid.uuid4().hex,
            )
            assert res1.granted
            lid = res1.payload["lease_id"]

            # Erste Verlängerung nach 50s (unter 100s TTL): OK
            t1 = T0 + timedelta(seconds=50)
            res_ren1 = renew_lease(
                conn, tid, lease_id=lid, fence=1, config=cfg_custom, now=t1
            )
            assert res_ren1.granted
            # Ablauf ist jetzt t1 + 100s = T0 + 150s (unter 200s Cap)
            assert parse_ts(res_ren1.payload["expires_at"]) == T0 + timedelta(
                seconds=150
            )

            # Zweite Verlängerung nach 120s: Erreicht den Cap (T0 + 200s)
            t2 = T0 + timedelta(seconds=120)
            res_ren2 = renew_lease(
                conn, tid, lease_id=lid, fence=1, config=cfg_custom, now=t2
            )
            assert res_ren2.granted
            assert parse_ts(res_ren2.payload["expires_at"]) == T0 + timedelta(
                seconds=200
            )

            # Dritte Verlängerung nach 160s: Cap ist bereits erreicht
            t3 = T0 + timedelta(seconds=160)
            res_ren3 = renew_lease(
                conn, tid, lease_id=lid, fence=1, config=cfg_custom, now=t3
            )
            assert not res_ren3.granted
            assert res_ren3.payload["reason"] in ("max_total_reached", "expired")

    def test_offline_safety_buffer_deadline_enforcement(self, test_db):
        """Vertrag §8.1: Ein Client muss die Bearbeitung vor Ablauf der Lease
        einstellen (local_deadline), wenn der Lead offline/unerreichbar ist."""
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)
            ack = client.acquire(
                tid,
                worker_id="gemini@ASUS-GEI",
                host="ASUS-GEI",
                ttl_profile="S",
                config=CFG,
                now=T0,
            )

            # Sicherheitspuffer für Profil S (300s): mindestens 60s Puffer
            assert ack.local_deadline < parse_ts(ack.expires_at)

            # Zu Beginn: lokal gültig
            assert ack.is_valid_at(T0)

            # Bei Erreichen der lokalen Deadline: Fail-Closed Abbruch
            past_deadline = ack.local_deadline + timedelta(seconds=1)
            assert not ack.is_valid_at(past_deadline)
            with pytest.raises(LeaseOfflineDeadlineExceeded):
                ack.assert_locally_valid(now=past_deadline)

    def test_release_and_return_transitions(self, test_db):
        """Prüft saubere Rückabwicklung und Statusübergänge."""
        with _connect(test_db) as conn:
            # 1. Release mit outcome='done' -> status='done'
            t1 = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)
            ack1 = client.acquire(
                t1, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", now=T0
            )
            rel1 = client.release(
                t1,
                lease_id=ack1.lease_id,
                fence=ack1.fence,
                outcome="done",
                now=T0 + timedelta(seconds=10),
            )
            assert rel1.status == "done"
            assert rel1.released is True

            # 2. Release mit outcome='return' -> status='pending'
            t2 = _insert_task(conn)
            ack2 = client.acquire(
                t2, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", now=T0
            )
            rel2 = client.release(
                t2,
                lease_id=ack2.lease_id,
                fence=ack2.fence,
                outcome="return",
                now=T0 + timedelta(seconds=10),
            )
            assert rel2.status == "pending"

            # 3. Release mit outcome='blocked' -> status='blocked'
            t3 = _insert_task(conn)
            ack3 = client.acquire(
                t3, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", now=T0
            )
            rel3 = client.release(
                t3,
                lease_id=ack3.lease_id,
                fence=ack3.fence,
                outcome="blocked",
                now=T0 + timedelta(seconds=10),
            )
            assert rel3.status == "blocked"


# ===========================================================================
# 3. Ablauf und Re-Claimability (Fence-Inkrementierung)
# ===========================================================================


class TestExpiryAndReclaimability:
    """Weist nach, dass abgelaufene Leases von einem neuen Worker übernommen werden
    können und das Fencing dabei strikt inkrementiert wird."""

    def test_expired_lease_is_reclaimable_with_incremented_fence(self, test_db):
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)

            # Worker A claimt Task um T0 (Profil S mit CFG: 300s)
            ack_a = client.acquire(
                tid,
                worker_id="opus@Mac-Studio",
                host="Mac-Studio",
                ttl_profile="S",
                config=CFG,
                now=T0,
            )
            assert ack_a.fence == 1

            # Während der Lease: Worker B wird abgewiesen
            with pytest.raises(LeaseDeniedError) as exc_b:
                client.acquire(
                    tid,
                    worker_id="gemini@ASUS-GEI",
                    host="ASUS-GEI",
                    ttl_profile="S",
                    config=CFG,
                    now=T0 + timedelta(seconds=60),
                )
            assert exc_b.value.reason == "held"

            # Nach Ablauf (expires_at + 1s): Worker B kann übernehmen!
            t_expired = parse_ts(ack_a.expires_at) + timedelta(seconds=1)
            ack_b = client.acquire(
                tid,
                worker_id="gemini@ASUS-GEI",
                host="ASUS-GEI",
                ttl_profile="S",
                config=CFG,
                now=t_expired,
            )

            # GATE: Fence wurde inkrementiert
            assert ack_b.fence == 2
            assert ack_b.worker_id == "gemini@ASUS-GEI"

            # Neuer Lease-Inhaber ist Worker B
            view = client.read(tid, config=CFG, now=t_expired)
            assert view.holder["worker_id"] == "gemini@ASUS-GEI"
            assert view.fence == 2


# ===========================================================================
# 4. Stale-Fence & Write Protection (Schutz vor veralteten Workern)
# ===========================================================================


class TestStaleFenceAndWriteProtection:
    """Verifiziert, dass ein Client mit altem Fence oder abgelaufener Lease
    weder Statusänderungen, noch Verlängerungen oder Releases durchsetzen kann."""

    def test_stale_worker_renewal_rejected(self, test_db):
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)

            # Worker A: Fence 1
            ack_a = client.acquire(
                tid,
                worker_id="opus@Mac-Studio",
                host="Mac-Studio",
                ttl_profile="S",
                config=CFG,
                now=T0,
            )

            # Ablauf & Übernahme durch Worker B (Fence 2)
            t_reclaim = parse_ts(ack_a.expires_at) + timedelta(seconds=10)
            ack_b = client.acquire(
                tid,
                worker_id="gemini@ASUS-GEI",
                host="ASUS-GEI",
                ttl_profile="S",
                config=CFG,
                now=t_reclaim,
            )
            assert ack_b.fence == 2

            # Alter Worker A versucht jetzt Verlängerung mit Fence 1
            with pytest.raises(LeaseStaleFenceError):
                client.renew(
                    tid,
                    lease_id=ack_a.lease_id,
                    fence=ack_a.fence,
                    config=CFG,
                    now=t_reclaim + timedelta(seconds=5),
                )

    def test_stale_worker_release_rejected_and_late_result_recorded(self, test_db):
        """Ein Release durch einen veralteten Worker ändert nicht den Status,
        zeichnet aber ein late_result für Auditierbarkeit auf."""
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)

            # Worker A: Fence 1
            ack_a = client.acquire(
                tid,
                worker_id="opus@Mac-Studio",
                host="Mac-Studio",
                ttl_profile="S",
                config=CFG,
                now=T0,
            )

            # Ablauf & Übernahme durch Worker B: Fence 2
            t_reclaim = parse_ts(ack_a.expires_at) + timedelta(seconds=10)
            ack_b = client.acquire(
                tid,
                worker_id="gemini@ASUS-GEI",
                host="ASUS-GEI",
                ttl_profile="S",
                config=CFG,
                now=t_reclaim,
            )
            assert ack_b.fence == 2

            # Worker A liefert verspätetes Ergebnis mit Fence 1 ab
            with pytest.raises(LeaseStaleFenceError) as exc:
                client.release(
                    tid,
                    lease_id=ack_a.lease_id,
                    fence=ack_a.fence,
                    outcome="done",
                    result_ref="commit:deadbeef",
                    note="Spätes Ergebnis von Worker A",
                    config=CFG,
                    now=t_reclaim + timedelta(seconds=15),
                )
            assert exc.value.reason == "stale_fence"

            # GATE: Task-Status bleibt 'in_progress' unter Worker B!
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
            assert row["status"] == "in_progress"
            assert row["claimed_by"] == "gemini@ASUS-GEI"
            assert row["claim_fence"] == 2

            # Prüfe, dass late_result im History-Audit steht
            hist = conn.execute(
                "SELECT * FROM task_history WHERE task_id = ? AND action = 'late_result'",
                (tid,),
            ).fetchone()
            assert hist is not None
            details = json.loads(hist["new_value"])
            assert details["reason"] == "stale_fence"
            assert details["result_ref"] == "commit:deadbeef"

    def test_direct_or_generic_status_update_blocked_by_lease_guard(self, test_db):
        """Generische Statuswechsel (ohne Lease-Autorisierung) werden fail-closed blockiert."""
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)
            ack = client.acquire(
                tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", now=T0
            )
            assert ack.fence == 1

            # Versuch, Status direkt über apply_task_field_changes ohne lease_authorized zu ändern
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
            with pytest.raises(LeaseRequired):
                apply_task_field_changes(
                    conn,
                    tid,
                    row,
                    {"status": "done"},
                    changed_by="unauthorized-agent",
                    lease_authorized=False,
                )

    def test_task_version_or_tamper_fails_closed(self, test_db):
        """Wird die Task-Zeile extern manipuliert (z.B. Fence manipuliert oder Status entwertet),
        wird der alte Arbeitsstand abgewiesen."""
        with _connect(test_db) as conn:
            tid = _insert_task(conn)
            client = TaskLeaseClient(conn=conn)
            ack = client.acquire(
                tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", now=T0
            )

            # Externer Eingriff verändert den Fence in der DB
            conn.execute("UPDATE tasks SET claim_fence = 99 WHERE id = ?", (tid,))
            conn.commit()

            # Worker mit Original-Ack (Fence 1) wird abgewiesen
            with pytest.raises(LeaseStaleFenceError):
                client.renew(
                    tid,
                    lease_id=ack.lease_id,
                    fence=ack.fence,
                    now=T0 + timedelta(seconds=10),
                )


# ===========================================================================
# 5. End-to-End Stack-Readback über alle Schichten
# ===========================================================================


class TestE2ELeaseStackReadback:
    """Verifiziert das Zusammenspiel aller fünf Schichten:
    TaskDB -> TaskLeaseClient -> CLI -> bach_api -> Trithon-Dispatch."""

    def test_cli_subcommands_readback(self, test_db):
        """Prüft die CLI-Befehle: lease, lease-show, lease-renew, lease-release."""
        from hub.task import TaskHandler

        with _connect(test_db) as conn:
            tid = _insert_task(conn, title="CLI-Integration-Task")

        handler = TaskHandler(SYSTEM_ROOT)
        handler.db_path = test_db

        # 1. CLI: bach task lease <id> --by <worker>
        ok_lease, out_lease = handler.handle(
            "lease", [str(tid), "--by", "gemini@ASUS-GEI", "--ttl", "M"]
        )
        assert ok_lease is True, out_lease
        assert "geleast an gemini@ASUS-GEI" in out_lease
        assert f"Task {tid}" in out_lease

        # Aus der DB die vergebene lease_id lesen
        with _connect(test_db) as conn:
            row = conn.execute(
                "SELECT claim_id, claim_fence FROM tasks WHERE id = ?", (tid,)
            ).fetchone()
            lid = row["claim_id"]
            fence = row["claim_fence"]

        # 2. CLI: bach task lease-show <id>
        ok_show, out_show = handler.handle("lease-show", [str(tid)])
        assert ok_show is True, out_show
        assert "gemini@ASUS-GEI" in out_show
        assert "ASUS-GEI" in out_show

        # 3. CLI: bach task lease-renew <id> --lease-id ... --fence ...
        ok_ren, out_ren = handler.handle(
            "lease-renew", [str(tid), "--lease-id", lid, "--fence", str(fence)]
        )
        assert ok_ren is True, out_ren
        assert "Lease verlaengert" in out_ren

        # 4. CLI: bach task lease-release <id> --lease-id ... --fence ... --outcome done
        ok_rel, out_rel = handler.handle(
            "lease-release",
            [str(tid), "--lease-id", lid, "--fence", str(fence), "--outcome", "done"],
        )
        assert ok_rel is True, out_rel
        assert "Lease freigegeben" in out_rel
        assert "Status=done" in out_rel

        # Prüfe DB nach Release
        with _connect(test_db) as conn:
            final_row = conn.execute(
                "SELECT status, claim_id FROM tasks WHERE id = ?", (tid,)
            ).fetchone()
            assert final_row["status"] == "done"
            assert final_row["claim_id"] is None

    def test_bach_api_integration(self, test_db, monkeypatch):
        """Prüft die offiziellen Python-Schnittstellen in bach_api.task."""
        import hub.bach_paths

        import bach_api

        # Monkeypatch DB auf test_db
        monkeypatch.setattr(hub.bach_paths, "BACH_DB", test_db)
        monkeypatch.setattr(bach_api, "_resolve_db_path", lambda: test_db)

        with _connect(test_db) as conn:
            tid = _insert_task(conn, title="bach_api-Integration-Task")

        # 1. lease_acquire
        ack_data = bach_api.task.lease_acquire(
            tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", ttl_profile="M"
        )
        assert ack_data["granted"] is True
        assert ack_data["task_id"] == tid
        assert ack_data["fence"] == 1
        lid = ack_data["lease_id"]

        # 2. lease_read
        view_data = bach_api.task.lease_read(tid, lease_id=lid)
        assert view_data["leased"] is True
        assert view_data["own"] is True
        assert view_data["holder"]["worker_id"] == "gemini@ASUS-GEI"

        # 3. lease_renew
        ren_data = bach_api.task.lease_renew(tid, lease_id=lid, fence=ack_data["fence"])
        assert ren_data["granted"] is True
        assert ren_data["fence"] == 1

        # 4. lease_release
        rel_data = bach_api.task.lease_release(
            tid, lease_id=lid, fence=ack_data["fence"], outcome="done"
        )
        assert rel_data["released"] is True
        assert rel_data["status"] == "done"

    def test_trithon_dispatch_execution_with_lease_receipt(self, test_db):
        """Prüft, dass execute_intent_v1 von Trithon eine Lease erwirbt, sie im
        ExecutionReceipt belegt und nach Abschluss atomar freigibt."""
        from hub._services.chat.slots_config import initialize_slots_config
        from hub._services.trithon.routing_contract import create_pending_contract
        from hub._services.trithon_dispatch import SyntheticTicket, execute_intent_v1

        with _connect(test_db) as conn:
            tid = _insert_task(conn, title="Trithon-Lease-Dispatch-Task")

        ledger_path = test_db.parent / "ledger.jsonl"
        slots_path = test_db.parent / "slots.json"
        initialize_slots_config(str(slots_path))
        ticket_id = f"ticket-acceptance-{tid}"
        create_pending_contract(ledger_path, ticket_id)

        ticket = SyntheticTicket(
            ticket_id=ticket_id,
            ledger_path=ledger_path,
            db_path=test_db,
            slots_path=slots_path,
            task_id=tid,
            intent={"action": "noop", "payload": "acceptance verify"},
            host="ASUS-GEI",
        )
        assignment = {
            "agent_instance_id": "trithon-agent-01",
            "backend_id": "backend-local",
            "model_id": "model-noop",
            "slot_id": "buddha_always_on",
            "session_id": "session-acceptance-test",
            "initiated_by": "pytest",
        }

        result = execute_intent_v1(ticket, **assignment)

        # Belegprüfung im Result
        assert result["success"] is True, result
        assert result["status"] == "done"
        assert "lease_id" in result
        assert result["fence"] == 1

        # DB-Endstand
        with _connect(test_db) as conn:
            row = conn.execute(
                "SELECT status, claim_id, claim_fence FROM tasks WHERE id = ?", (tid,)
            ).fetchone()
            assert row["status"] == "done"
            assert row["claim_id"] is None
            assert row["claim_fence"] == 1
