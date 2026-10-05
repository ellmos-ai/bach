# SPDX-License-Identifier: MIT
"""Tests für den Lead-seitigen Task-Lease-Dienst (BACH #1721).

Vertrag: docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md. Alle Zeitpunkte
werden injiziert (``now=``), damit Ablauf, Renew-Deckel und Ersteller-Vorrang
deterministisch prüfbar sind. Es wird ausschließlich gegen temporäre
SQLite-Dateien getestet, nie gegen eine produktive TaskDB.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.task_lease import (
    LeaseConfig,
    LeaseValidationError,
    TaskNotFound,
    acquire_lease,
    ensure_task_lease_schema,
    parse_ts,
    read_lease,
    release_lease,
    renew_lease,
)
from hub.task_audit import (
    LeaseRequired,
    apply_task_field_changes,
    claim_task_atomic,
    reap_stale_in_progress_tasks,
    release_claim,
)

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


T0 = datetime(2026, 10, 5, 2, 0, 0, tzinfo=timezone.utc)
CFG = LeaseConfig(creator_window_seconds=0)


def _rid() -> str:
    return "req-" + uuid.uuid4().hex


def _create_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'open',
            category TEXT DEFAULT 'general',
            assigned_to TEXT DEFAULT 'user',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            source TEXT,
            estimated_minutes INTEGER,
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
    conn.commit()
    conn.close()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _insert(conn, title="t", status="pending", **cols) -> int:
    cols = {"title": title, "status": status, **cols}
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    cur = conn.execute(f"INSERT INTO tasks ({names}) VALUES ({marks})", tuple(cols.values()))
    conn.commit()
    return cur.lastrowid


def _get(conn, task_id) -> dict:
    return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "data" / "bach.db"
    _create_db(path)
    return path


@pytest.fixture
def conn(db_path):
    c = _connect(db_path)
    yield c
    c.close()


def _acq(conn, task_id, worker="agy-opus@ASUS-GEI", now=T0, **kw):
    host = worker.rsplit("@", 1)[1]
    kw.setdefault("request_id", _rid())
    kw.setdefault("config", CFG)
    return acquire_lease(conn, task_id, worker_id=worker, host=host, now=now, **kw)


@pytest.mark.parametrize("operation", ["acquire", "renew", "release"])
def test_ack_keeps_own_transaction_after_concurrent_reassignment(db_path, monkeypatch, operation):
    """A legal replay/release/reacquire after commit must not rewrite the ACK."""
    class AfterCommit(sqlite3.Connection):
        after_commit = None
        def commit(self):
            super().commit()
            if self.after_commit:
                self.after_commit()

    first = sqlite3.connect(str(db_path), timeout=10, factory=AfterCommit)
    first.row_factory = sqlite3.Row
    second = _connect(db_path)
    task_id = _insert(first)
    request_id = _rid()
    original = None
    if operation != "acquire":
        original = _acq(first, task_id, worker="alpha@host-a", request_id=request_id).payload
    fired = False
    replacement = None

    def reassign():
        nonlocal fired, replacement
        action = first.execute("SELECT action FROM task_history ORDER BY id DESC LIMIT 1").fetchone()
        if fired or not action or action[0] != f"lease_{operation}":
            return
        fired = True
        if operation != "release":
            replay = _acq(second, task_id, worker="alpha@host-a", request_id=request_id)
            assert replay.payload["replayed"] is True
            result = release_lease(second, task_id, lease_id=replay.payload["lease_id"],
                fence=replay.payload["fence"], outcome="return", config=CFG, now=T0)
            assert result.payload["released"] is True
        replacement = _acq(second, task_id, worker="beta@host-b").payload

    first.after_commit = reassign
    try:
        if operation == "acquire":
            received = _acq(first, task_id, worker="alpha@host-a", request_id=request_id).payload
        elif operation == "renew":
            received = renew_lease(first, task_id, lease_id=original["lease_id"],
                fence=original["fence"], config=CFG, now=T0 + timedelta(seconds=1)).payload
        else:
            received = release_lease(first, task_id, lease_id=original["lease_id"],
                fence=original["fence"], outcome="return", config=CFG, now=T0).payload
        assert fired
        assert replacement["worker_id"] == "beta@host-b"
        assert replacement["fence"] == 2
        assert received["fence"] == 1
        if operation == "release":
            assert received["status"] == "pending"
        else:
            assert received["worker_id"] == "alpha@host-a"
            assert received["lease_id"] != replacement["lease_id"]
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("operation", ["renew", "release"])
def test_lease_rejects_task_content_changed_after_acquire(conn, operation):
    tid = _insert(conn)
    ack = _acq(conn, tid).payload
    apply_task_field_changes(conn, tid, _get(conn, tid), {"description": "changed by operator"})
    conn.commit()
    before = _get(conn, tid)
    kwargs = dict(lease_id=ack["lease_id"], fence=ack["fence"], config=CFG, now=T0 + timedelta(seconds=1))
    result = renew_lease(conn, tid, **kwargs) if operation == "renew" else release_lease(conn, tid, outcome="done", **kwargs)
    assert result.http_status == 409 and result.payload["reason"] == "stale_task_version"
    assert _get(conn, tid) == before


def test_task_version_is_stable_across_heartbeat(conn):
    tid = _insert(conn)
    ack = _acq(conn, tid).payload
    assert len(ack["task_version"]) == 64
    renewed = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG, now=T0 + timedelta(seconds=10))
    assert renewed.payload["task_version"] == ack["task_version"]


@pytest.mark.parametrize("close_parent", [False, True])
def test_fenced_decomposition_is_atomic_and_versioned(conn, close_parent):
    from hub._services import task_lease as service
    tid = _insert(conn, description="Original")
    ack = _acq(conn, tid).payload
    result = service.decompose_lease(
        conn, tid, lease_id=ack["lease_id"], fence=1, task_version=ack["task_version"],
        subtasks=[{"title": "first", "description": "äöü"}, {"title": "second"}],
        close_parent=close_parent, sequential=True, config=CFG, now=T0 + timedelta(seconds=1),
    )
    assert result.http_status == 200
    payload = result.payload
    assert payload["decomposed"] and payload["parent_closed"] is close_parent
    assert len(payload["created_ids"]) == 2
    assert _get(conn, payload["created_ids"][1])["depends_on"] == str(payload["created_ids"][0])
    parent = _get(conn, tid)
    assert parent["status"] == ("done" if close_parent else "in_progress")
    assert bool(parent["claim_id"]) is (not close_parent)
    assert payload["task_version"] != ack["task_version"]
    repeated = service.decompose_lease(
        conn, tid, lease_id=ack["lease_id"], fence=1, task_version=ack["task_version"],
        subtasks=[{"title": "duplicate"}], config=CFG, now=T0 + timedelta(seconds=2),
    )
    assert repeated.http_status == 409
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3


@pytest.mark.parametrize("problem", ["expired", "foreign_fence", "old_version", "invalid_subtask"])
def test_fenced_decomposition_denial_creates_nothing(conn, problem):
    from hub._services import task_lease as service
    tid = _insert(conn)
    ack = _acq(conn, tid).payload
    before = _get(conn, tid)
    kwargs = dict(lease_id=ack["lease_id"], fence=1, task_version=ack["task_version"],
                  subtasks=[{"title": "valid"}], config=CFG, now=T0 + timedelta(seconds=1))
    if problem == "expired":
        kwargs["now"] = T0 + timedelta(hours=1)
    elif problem == "foreign_fence":
        kwargs["fence"] = 2
    elif problem == "old_version":
        kwargs["task_version"] = "0" * 64
    else:
        kwargs["subtasks"] = [{"title": "valid"}, {"title": " "}]
    if problem == "invalid_subtask":
        with pytest.raises(LeaseValidationError):
            service.decompose_lease(conn, tid, **kwargs)
    else:
        assert service.decompose_lease(conn, tid, **kwargs).http_status == 409
    assert _get(conn, tid) == before
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_fenced_decomposition_rolls_back_partial_child_insert(conn):
    from hub._services.task_lease import decompose_lease
    tid = _insert(conn)
    ack = _acq(conn, tid).payload
    conn.execute("CREATE TRIGGER reject_second BEFORE INSERT ON tasks WHEN NEW.title = 'second' "
                 "BEGIN SELECT RAISE(ABORT, 'synthetic insert failure'); END")
    conn.commit()
    before = _get(conn, tid)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic"):
        decompose_lease(conn, tid, lease_id=ack["lease_id"], fence=1, task_version=ack["task_version"],
                        subtasks=[{"title": "first"}, {"title": "second"}], config=CFG, now=T0)
    assert not conn.in_transaction
    assert _get(conn, tid) == before
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_fenced_decomposition_never_acks_failed_commit(db_path):
    from hub._services.task_lease import decompose_lease

    class RefuseCommit(sqlite3.Connection):
        def commit(self):
            last = self.execute("SELECT action FROM task_history ORDER BY id DESC LIMIT 1").fetchone()
            if last and last[0] == "lease_decompose":
                raise sqlite3.OperationalError("synthetic commit failure")
            return super().commit()
    c = sqlite3.connect(str(db_path), factory=RefuseCommit)
    c.row_factory = sqlite3.Row
    try:
        tid = _insert(c)
        ack = _acq(c, tid).payload
        before = _get(c, tid)
        with pytest.raises(sqlite3.OperationalError, match="synthetic"):
            decompose_lease(c, tid, lease_id=ack["lease_id"], fence=1, task_version=ack["task_version"],
                            subtasks=[{"title": "child"}], config=CFG, now=T0)
        assert not c.in_transaction and _get(c, tid) == before
        assert c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    finally:
        c.close()


def test_parallel_fenced_decomposition_has_only_one_child_batch(db_path):
    from hub._services.task_lease import decompose_lease
    c = _connect(db_path)
    tid = _insert(c)
    ack = _acq(c, tid).payload
    c.close()
    barrier = threading.Barrier(2)
    results, errors = [], []

    def run():
        connection = _connect(db_path)
        try:
            barrier.wait(timeout=5)
            results.append(decompose_lease(
                connection, tid, lease_id=ack["lease_id"], fence=1, task_version=ack["task_version"],
                subtasks=[{"title": "child"}], close_parent=False, config=CFG, now=T0,
            ))
        except BaseException as exc:
            errors.append(exc)
        finally:
            connection.close()
    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    assert not errors
    assert sorted(result.http_status for result in results) == [200, 409]
    c = _connect(db_path)
    try:
        assert c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    finally:
        c.close()


@pytest.mark.parametrize("operation", ["acquire", "renew", "release"])
def test_failed_commit_never_returns_ack_and_rolls_back(db_path, operation):
    class RefuseCommit(sqlite3.Connection):
        refuse_action = None
        def commit(self):
            action = self.execute("SELECT action FROM task_history ORDER BY id DESC LIMIT 1").fetchone()
            if action and action[0] == self.refuse_action:
                raise sqlite3.OperationalError("commit refused")
            super().commit()

    first = sqlite3.connect(str(db_path), timeout=10, factory=RefuseCommit)
    first.row_factory = sqlite3.Row
    task_id = _insert(first)
    original = None
    if operation != "acquire":
        original = _acq(first, task_id).payload
    before = _get(first, task_id)
    first.refuse_action = f"lease_{operation}"
    try:
        with pytest.raises(sqlite3.OperationalError, match="commit refused"):
            if operation == "acquire":
                _acq(first, task_id)
            elif operation == "renew":
                renew_lease(first, task_id, lease_id=original["lease_id"], fence=original["fence"],
                            config=CFG, now=T0 + timedelta(seconds=1))
            else:
                release_lease(first, task_id, lease_id=original["lease_id"], fence=original["fence"],
                              outcome="return", config=CFG, now=T0)
        # Acquire also installs additive columns before its failing transaction.
        after = _get(first, task_id)
        assert all(after[key] == value for key, value in before.items())
        assert first.in_transaction is False
    finally:
        first.close()


# ---------------------------------------------------------------------------
# Schema und Zeit
# ---------------------------------------------------------------------------

class TestSchemaAndTime:
    def test_schema_is_additive_and_idempotent(self, conn):
        tid = _insert(conn, description="bleibt")
        ensure_task_lease_schema(conn)
        ensure_task_lease_schema(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert {"claim_id", "claim_fence", "claim_expires_at", "claim_request_id"} <= cols
        row = _get(conn, tid)
        assert row["description"] == "bleibt" and row["claim_fence"] == 0

    def test_parse_ts_rules(self):
        assert parse_ts("2026-10-05 02:00:00") == T0  # SQLite datetime('now') = UTC
        assert parse_ts("2026-10-05T02:00:00.000000Z") == T0
        local = T0.astimezone().replace(tzinfo=None).isoformat()  # naiv mit T = Ortszeit
        assert parse_ts(local) == T0
        assert parse_ts("") is None and parse_ts("kaputt") is None


# ---------------------------------------------------------------------------
# Acquire
# ---------------------------------------------------------------------------

class TestAcquire:
    def test_grant_ack_shape_and_fence(self, conn):
        tid = _insert(conn)
        res = _acq(conn, tid)
        assert res.http_status == 200 and res.granted
        p = res.payload
        assert p["fence"] == 1 and p["ttl_profile"] == "M"
        assert uuid.UUID(p["lease_id"]).version == 4
        assert parse_ts(p["expires_at"]) == T0 + timedelta(minutes=30)
        assert p["server_now"] == "2026-10-05T02:00:00.000000Z"
        row = _get(conn, tid)
        assert row["status"] == "in_progress" and row["claimed_by"] == "agy-opus@ASUS-GEI"
        assert parse_ts(row["claimed_at"]) == T0  # Kompat-Spalte in Ortszeit

    def test_history_never_contains_lease_id(self, conn):
        tid = _insert(conn)
        lease_id = _acq(conn, tid).payload["lease_id"]
        dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM task_history")])
        assert "lease_acquire" in dump and lease_id not in dump

    def test_concurrent_acquire_grants_exactly_one(self, db_path):
        with _connect(db_path) as c:
            tid = _insert(c)
        results, barrier = [], threading.Barrier(8)

        def worker(i):
            c = _connect(db_path)
            try:
                barrier.wait()
                results.append(_acq(c, tid, worker=f"w{i}@HOST{i}"))
            finally:
                c.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(r.granted for r in results) == 1
        assert {r.payload.get("reason") for r in results if not r.granted} == {"held"}

    def test_idempotent_replay_returns_same_lease(self, conn):
        tid = _insert(conn)
        first = _acq(conn, tid, request_id="req-aaaaaaaaaaaaaaaa")
        again = _acq(conn, tid, request_id="req-aaaaaaaaaaaaaaaa", now=T0 + timedelta(seconds=5))
        assert again.granted and again.payload["replayed"] is True
        assert again.payload["lease_id"] == first.payload["lease_id"]
        assert again.payload["fence"] == 1

    def test_already_held_by_caller_with_new_request(self, conn):
        tid = _insert(conn)
        _acq(conn, tid)
        res = _acq(conn, tid)
        assert res.http_status == 409 and res.payload["reason"] == "already_held_by_caller"

    def test_held_shows_holder_without_lease_id(self, conn):
        tid = _insert(conn)
        lease_id = _acq(conn, tid, intent="arbeite an X").payload["lease_id"]
        res = _acq(conn, tid, worker="codex@WORKSTATION-LG")
        assert res.payload["reason"] == "held"
        assert res.payload["holder"]["worker_id"] == "agy-opus@ASUS-GEI"
        assert res.payload["holder"]["intent"] == "arbeite an X"
        assert lease_id not in json.dumps(res.payload)

    @pytest.mark.parametrize("status", ["done", "completed", "cancelled", "blocked"])
    def test_terminal_not_claimable(self, conn, status):
        tid = _insert(conn, status=status)
        res = _acq(conn, tid)
        assert res.payload["reason"] == "not_claimable" and res.payload["status"] == status

    def test_unfinished_dependency_not_claimable(self, conn):
        dep = _insert(conn, title="dep")
        tid = _insert(conn, depends_on=str(dep))
        res = _acq(conn, tid)
        assert res.payload["reason"] == "not_claimable" and res.payload["blocked_by"]["unfinished"]

    def test_creator_priority(self, conn):
        created = (T0 - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        tid = _insert(conn, created_by="claude", created_at=created)
        cfg = LeaseConfig(creator_window_seconds=600)
        denied = _acq(conn, tid, worker="codex@WORKSTATION-LG", config=cfg)
        assert denied.payload["reason"] == "creator_priority"
        assert parse_ts(denied.payload["until"]) == T0 + timedelta(minutes=8)
        assert _acq(conn, tid, worker="claude@ASUS-GEI", config=cfg).granted
        tid2 = _insert(conn, created_by="claude", created_at=created)
        assert _acq(conn, tid2, worker="codex@WORKSTATION-LG", config=cfg,
                    now=T0 + timedelta(minutes=9)).granted

    def test_live_legacy_claim_blocks(self, conn):
        local = (T0 - timedelta(minutes=5)).astimezone().replace(tzinfo=None).isoformat()
        tid = _insert(conn, status="in_progress", claimed_by="idle-worker", claimed_at=local)
        res = _acq(conn, tid)
        assert res.payload["reason"] == "held" and res.payload["legacy"] is True

    def test_expired_legacy_claim_is_taken_over(self, conn):
        local = (T0 - timedelta(minutes=31)).astimezone().replace(tzinfo=None).isoformat()
        tid = _insert(conn, status="in_progress", claimed_by="idle-worker", claimed_at=local)
        res = _acq(conn, tid)
        assert res.granted and res.payload["fence"] == 1

    def test_expired_lease_takeover_increments_fence(self, conn):
        tid = _insert(conn)
        _acq(conn, tid)
        res = _acq(conn, tid, worker="codex@WORKSTATION-LG", now=T0 + timedelta(minutes=31))
        assert res.granted and res.payload["fence"] == 2

    def test_xl_downgrade_without_estimate(self, conn):
        tid = _insert(conn)
        assert _acq(conn, tid, ttl_profile="XL").payload["ttl_profile"] == "L"
        tid2 = _insert(conn, estimated_minutes=600)
        assert _acq(conn, tid2, ttl_profile="xl").payload["ttl_profile"] == "XL"

    def test_salt_ref_only_with_ticket_provenance(self, conn):
        tid = _insert(conn, source="ticket:T-20261003-793817309")
        _acq(conn, tid)
        assert len(_get(conn, tid)["claim_salt_ref"]) == 64
        tid2 = _insert(conn, source="gui")
        _acq(conn, tid2)
        assert _get(conn, tid2)["claim_salt_ref"] is None

    @pytest.mark.parametrize("kwargs", [
        {"worker": "ohne-host"},
        {"request_id": "kurz"},
        {"ttl_profile": "XXL"},
    ])
    def test_validation_errors(self, conn, kwargs):
        tid = _insert(conn)
        worker = kwargs.pop("worker", "agy-opus@ASUS-GEI")
        with pytest.raises(LeaseValidationError):
            if "@" not in worker:
                acquire_lease(conn, tid, worker_id=worker, host="ASUS-GEI", request_id=_rid(), config=CFG)
            else:
                _acq(conn, tid, worker=worker, **kwargs)

    def test_host_must_match_worker(self, conn):
        tid = _insert(conn)
        with pytest.raises(LeaseValidationError):
            acquire_lease(conn, tid, worker_id="a@HOST1", host="HOST2", request_id=_rid(), config=CFG)

    def test_unknown_task(self, conn):
        with pytest.raises(TaskNotFound):
            _acq(conn, 9999)


# ---------------------------------------------------------------------------
# Renew
# ---------------------------------------------------------------------------

class TestRenew:
    def test_renew_extends_and_never_shortens(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid, ttl_profile="S").payload
        r1 = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG,
                         now=T0 + timedelta(minutes=10))
        assert parse_ts(r1.payload["expires_at"]) == T0 + timedelta(minutes=25)
        r2 = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG,
                         now=T0 + timedelta(minutes=5))  # früherer Zeitpunkt verkürzt nicht
        assert parse_ts(r2.payload["expires_at"]) == T0 + timedelta(minutes=25)

    def test_renew_capped_at_max_total(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid, ttl_profile="S").payload
        cap = T0 + timedelta(hours=2)
        now = T0
        while True:
            now += timedelta(minutes=14)
            res = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG, now=now)
            assert res.granted
            expires = parse_ts(res.payload["expires_at"])
            assert expires <= cap
            if expires == cap:
                break
        res = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG,
                          now=cap - timedelta(minutes=1))
        assert res.payload["reason"] == "max_total_reached"

    def test_renew_expired(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid).payload
        res = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG,
                          now=T0 + timedelta(minutes=31))
        assert res.http_status == 409 and res.payload["reason"] == "expired"

    def test_renew_stale_fence(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid).payload
        res = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=2, config=CFG, now=T0)
        assert res.payload["reason"] == "stale_fence"
        res = renew_lease(conn, tid, lease_id=str(uuid.uuid4()), fence=1, config=CFG, now=T0)
        assert res.payload["reason"] == "stale_fence"

    def test_renew_validation(self, conn):
        tid = _insert(conn)
        with pytest.raises(LeaseValidationError):
            renew_lease(conn, tid, lease_id="nicht-uuid", fence=1, config=CFG)
        with pytest.raises(LeaseValidationError):
            renew_lease(conn, tid, lease_id=str(uuid.uuid4()), fence=0, config=CFG)


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------

class TestRelease:
    @pytest.mark.parametrize("outcome,status", [("return", "pending"), ("done", "done"),
                                                ("blocked", "blocked")])
    def test_release_outcomes_keep_fence(self, conn, outcome, status):
        tid = _insert(conn)
        ack = _acq(conn, tid).payload
        res = release_lease(conn, tid, lease_id=ack["lease_id"], fence=1, outcome=outcome,
                            result_ref="https://github.com/ellmos-ai/bach/pull/1", config=CFG,
                            now=T0 + timedelta(minutes=1))
        assert res.payload["released"] is True and res.payload["status"] == status
        row = _get(conn, tid)
        assert row["status"] == status and row["claim_fence"] == 1
        assert row["claim_id"] is None and row["claimed_by"] is None

    def test_stale_release_records_late_result_only(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid).payload
        _acq(conn, tid, worker="codex@WORKSTATION-LG", now=T0 + timedelta(minutes=31))
        res = release_lease(conn, tid, lease_id=ack["lease_id"], fence=1, outcome="done",
                            note="spät fertig", config=CFG, now=T0 + timedelta(minutes=32))
        assert res.payload["reason"] == "stale_fence" and res.payload["late_result_recorded"]
        row = _get(conn, tid)
        assert row["status"] == "in_progress" and row["claimed_by"] == "codex@WORKSTATION-LG"
        assert conn.execute("SELECT COUNT(*) FROM task_history WHERE action='late_result'").fetchone()[0] == 1

    def test_expired_release_without_result_changes_nothing(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid).payload
        res = release_lease(conn, tid, lease_id=ack["lease_id"], fence=1, outcome="return",
                            config=CFG, now=T0 + timedelta(minutes=31))
        assert res.payload["reason"] == "expired" and not res.payload["late_result_recorded"]
        assert _get(conn, tid)["status"] == "in_progress"

    def test_invalid_outcome(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid).payload
        with pytest.raises(LeaseValidationError):
            release_lease(conn, tid, lease_id=ack["lease_id"], fence=1, outcome="vielleicht", config=CFG)


# ---------------------------------------------------------------------------
# Schutz der Altpfade
# ---------------------------------------------------------------------------

class TestLegacyPathsRespectLease:
    @pytest.mark.parametrize("expires", ["2000-01-01T00:00:00.000000Z", None])
    @pytest.mark.parametrize("status", ["done", "pending"])
    def test_generic_status_change_rejects_retained_capability(self, conn, expires, status):
        tid = _insert(conn)
        _acq(conn, tid)
        conn.execute("UPDATE tasks SET claim_expires_at = ? WHERE id = ?", (expires, tid))
        conn.commit()
        before = _get(conn, tid)
        with pytest.raises(LeaseRequired):
            apply_task_field_changes(conn, tid, before, {"status": status})
        conn.rollback()
        assert _get(conn, tid) == before

    def test_generic_status_change_rejects_stale_unleased_snapshot(self, conn):
        tid = _insert(conn)
        stale = _get(conn, tid)
        _acq(conn, tid, now=datetime.now(timezone.utc))
        before = _get(conn, tid)
        with pytest.raises(LeaseRequired):
            apply_task_field_changes(conn, tid, stale, {"status": "done"})
        conn.rollback()
        assert _get(conn, tid) == before

    def test_generic_status_update_fences_acquire_after_preflight(self, db_path):
        other = _connect(db_path)
        ensure_task_lease_schema(other)
        tid = _insert(other)

        class AcquireBeforeUpdate(sqlite3.Connection):
            def execute(self, sql, parameters=(), /):
                if sql.startswith("UPDATE tasks SET"):
                    _acq(other, tid, now=datetime.now(timezone.utc))
                return super().execute(sql, parameters)

        conn = sqlite3.connect(str(db_path), factory=AcquireBeforeUpdate)
        conn.row_factory = sqlite3.Row
        try:
            stale = _get(conn, tid)
            with pytest.raises(LeaseRequired):
                apply_task_field_changes(conn, tid, stale, {"status": "done"})
            conn.rollback()
            assert _get(other, tid)["status"] == "in_progress"
            assert not other.execute("SELECT 1 FROM task_history WHERE action = 'status_change'").fetchone()
        finally:
            conn.close()
            other.close()

    def test_legacy_schema_update_serializes_first_lease_migration(self, db_path):
        other = _connect(db_path)
        other.execute("PRAGMA busy_timeout = 0")
        tid = _insert(other)
        migration_blocked = []

        class MigrateBeforeUpdate(sqlite3.Connection):
            def execute(self, sql, parameters=(), /):
                if sql.startswith("UPDATE tasks SET"):
                    try:
                        _acq(other, tid, now=datetime.now(timezone.utc))
                    except sqlite3.OperationalError as exc:
                        assert "locked" in str(exc)
                        migration_blocked.append(True)
                return super().execute(sql, parameters)

        conn = sqlite3.connect(str(db_path), factory=MigrateBeforeUpdate)
        conn.row_factory = sqlite3.Row
        try:
            assert apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "done"})
            assert migration_blocked == [True]
            conn.rollback()
            assert _acq(other, tid, now=datetime.now(timezone.utc)).payload["granted"]
        finally:
            conn.close()
            other.close()

    def test_generic_status_change_blocked_while_live(self, conn):
        tid = _insert(conn)
        _acq(conn, tid, now=datetime.now(timezone.utc))
        with pytest.raises(LeaseRequired):
            apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "done"})
        conn.rollback()
        # Nicht-Status-Felder bleiben erlaubt
        assert apply_task_field_changes(conn, tid, _get(conn, tid), {"description": "x"})
        conn.commit()

    def test_legacy_claim_cannot_take_live_lease_even_after_legacy_window(self, conn):
        tid = _insert(conn)
        now = datetime.now(timezone.utc)
        _acq(conn, tid, ttl_profile="L", now=now - timedelta(minutes=40))  # claimed_at 40 min alt
        assert claim_task_atomic(conn, tid, "idle-worker") is False
        conn.rollback()
        assert release_claim(conn, tid, "agy-opus@ASUS-GEI") is False
        conn.rollback()

    def test_legacy_claim_after_expiry_clears_capability(self, conn):
        tid = _insert(conn)
        ack = _acq(conn, tid, now=datetime.now(timezone.utc) - timedelta(hours=1)).payload
        assert claim_task_atomic(conn, tid, "idle-worker") is True
        conn.commit()
        row = _get(conn, tid)
        assert row["claim_id"] is None and row["claim_fence"] == 1
        res = renew_lease(conn, tid, lease_id=ack["lease_id"], fence=1, config=CFG)
        assert res.payload["reason"] == "stale_fence"
        held = _acq(conn, tid, worker="codex@WORKSTATION-LG", now=datetime.now(timezone.utc))
        assert held.payload["reason"] == "held" and held.payload["legacy"] is True

    def test_reaper_skips_live_and_reaps_expired_lease(self, conn):
        now = datetime.now(timezone.utc)
        live = _insert(conn, title="live")
        _acq(conn, live, ttl_profile="L", now=now - timedelta(minutes=45))
        dead = _insert(conn, title="dead")
        _acq(conn, dead, ttl_profile="S", now=now - timedelta(minutes=20))  # claimed_at < 30 min
        reaped = reap_stale_in_progress_tasks(conn)
        conn.commit()
        assert reaped == [dead]
        assert _get(conn, live)["status"] == "in_progress"
        row = _get(conn, dead)
        assert row["status"] == "pending" and row["claim_id"] is None and row["claim_fence"] == 1


# ---------------------------------------------------------------------------
# Readback-Sequenz (Vertrag §12)
# ---------------------------------------------------------------------------

def test_contract_readback_sequence(conn):
    tid = _insert(conn)
    a = _acq(conn, tid, worker="agy-opus@ASUS-GEI").payload
    seen = read_lease(conn, tid, config=CFG, now=T0 + timedelta(seconds=1)).payload
    assert seen["leased"] and seen["holder"]["worker_id"] == "agy-opus@ASUS-GEI"
    assert "lease_id" not in json.dumps(seen) or a["lease_id"] not in json.dumps(seen)
    own = read_lease(conn, tid, lease_id=a["lease_id"], config=CFG, now=T0).payload
    assert own["own"] is True
    assert _acq(conn, tid, worker="codex@WORKSTATION-LG").payload["reason"] == "held"
    assert renew_lease(conn, tid, lease_id=a["lease_id"], fence=1, config=CFG,
                       now=T0 + timedelta(minutes=20)).granted
    b = _acq(conn, tid, worker="codex@WORKSTATION-LG", now=T0 + timedelta(minutes=51)).payload
    assert b["fence"] == 2
    assert renew_lease(conn, tid, lease_id=a["lease_id"], fence=1, config=CFG,
                       now=T0 + timedelta(minutes=52)).payload["reason"] == "stale_fence"
    done = release_lease(conn, tid, lease_id=b["lease_id"], fence=2, outcome="done",
                         config=CFG, now=T0 + timedelta(minutes=53)).payload
    assert done["status"] == "done" and done["fence"] == 2
    after = read_lease(conn, tid, config=CFG, now=T0 + timedelta(minutes=54)).payload
    assert after["leased"] is False and after["fence"] == 2


def test_config_from_env():
    cfg = LeaseConfig.from_env({"BACH_TASK_LEASE_PROFILES": json.dumps({"M": [600, 3600]}),
                                "BACH_TASK_LEASE_CREATOR_WINDOW": "0"})
    assert cfg.profiles["M"] == (600, 3600) and cfg.profiles["S"] == (900, 7200)
    assert cfg.creator_window_seconds == 0
    bad = LeaseConfig.from_env({"BACH_TASK_LEASE_PROFILES": json.dumps({"M": [7200, 60]})})
    assert bad.profiles["M"] == (1800, 28800)
    assert LeaseConfig.from_env({"BACH_TASK_LEASE_PROFILES": "kein json"}).profiles["M"] == (1800, 28800)


# ---------------------------------------------------------------------------
# HTTP-API
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi nicht installiert")
class TestLeaseAPI:
    def test_fenced_decomposition_endpoint_and_safe_snapshot(self, client, db_path):
        with _connect(db_path) as c:
            tid = _insert(c, description="Auftrag äöü")
        snapshot = client.get(f"/api/tasks/{tid}").json()
        acquired = client.post(f"/api/tasks/{tid}/lease", json={**self._body(), "task_version": snapshot["task_version"]})
        assert acquired.status_code == 200, acquired.text
        ack = acquired.json()
        assert ack["task_version"] == snapshot["task_version"]
        for response in (client.get(f"/api/tasks/{tid}"), client.get("/api/tasks?status=all")):
            assert response.status_code == 200
            assert ack["lease_id"] not in response.text
            assert "claim_request_id" not in response.text
        body = {"lease_id": ack["lease_id"], "fence": ack["fence"], "task_version": ack["task_version"],
                "subtasks": [{"title": "erste"}, {"title": "zweite"}], "sequential": True}
        bad = client.post(f"/api/tasks/{tid}/lease/decompose", json={**body, "fence": True})
        assert bad.status_code == 422
        bad = client.post(f"/api/tasks/{tid}/lease/decompose", json={**body, "close_parent_typo": False})
        assert bad.status_code == 422
        bad = client.post(f"/api/tasks/{tid}/lease/decompose", json=body,
                          headers={"Authorization": "Bearer revoked-device"})
        assert bad.status_code in (401, 403)
        response = client.post(f"/api/tasks/{tid}/lease/decompose", json=body)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["created_count"] == 2 and receipt["parent_closed"]
        assert client.get(f"/api/tasks/{tid}").json()["status"] == "done"
        for child in receipt["created_ids"]:
            assert client.get(f"/api/tasks/{child}").status_code == 200
        assert client.post(f"/api/tasks/{tid}/lease/decompose", json=body).status_code == 409

    def test_acquire_rejects_stale_observed_task_version(self, client, db_path):
        with _connect(db_path) as c:
            tid = _insert(c)
        version = client.get(f"/api/tasks/{tid}").json()["task_version"]
        assert client.put(f"/api/tasks/{tid}", json={"description": "changed"}).status_code == 200
        response = client.post(f"/api/tasks/{tid}/lease", json={**self._body(), "task_version": version})
        assert response.status_code == 409 and response.json()["reason"] == "stale_task_version"

    @pytest.fixture
    def client(self, db_path, tmp_path, monkeypatch):
        import gui.server as srv
        monkeypatch.setattr(srv, "BACH_DB", db_path)
        monkeypatch.setattr(srv, "USER_DB", db_path)
        monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(srv, "BACH_DIR", tmp_path)
        monkeypatch.setattr(srv, "GUI_DIR", tmp_path / "gui")
        monkeypatch.setattr(srv, "validate_token",
                            lambda token: {"id": 1, "name": "test-device"} if token == "lease-fixture" else None)
        monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
        return TestClient(srv.app, raise_server_exceptions=False,
                          headers={"Authorization": "Bearer lease-fixture"})

    def _body(self, worker="agy-opus@ASUS-GEI"):
        return {"worker_id": worker, "host": worker.rsplit("@", 1)[1], "request_id": _rid()}

    def test_full_cycle_and_put_guard(self, client, db_path):
        with _connect(db_path) as c:
            tid = _insert(c)
        r = client.post(f"/api/tasks/{tid}/lease", json=self._body())
        assert r.status_code == 200, r.text
        ack = r.json()
        assert ack["granted"] and ack["fence"] == 1

        r = client.post(f"/api/tasks/{tid}/lease", json=self._body("codex@WORKSTATION-LG"))
        assert r.status_code == 409 and r.json()["reason"] == "held"
        assert ack["lease_id"] not in r.text

        r = client.get(f"/api/tasks/{tid}/lease")
        assert r.status_code == 200 and r.json()["leased"] and "own" not in r.json()
        r = client.get(f"/api/tasks/{tid}/lease", headers={"X-Lease-Id": ack["lease_id"]})
        assert r.json()["own"] is True

        r = client.put(f"/api/tasks/{tid}", json={"status": "done", "changed_by": "idle-worker"})
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "lease_required"

        r = client.post(f"/api/tasks/{tid}/lease/renew",
                        json={"lease_id": ack["lease_id"], "fence": 1})
        assert r.status_code == 200 and r.json()["granted"]

        r = client.post(f"/api/tasks/{tid}/lease/release",
                        json={"lease_id": ack["lease_id"], "fence": 1, "outcome": "return"})
        assert r.status_code == 200 and r.json()["status"] == "pending"

        with _connect(db_path) as c:
            dump = json.dumps([dict(x) for x in c.execute("SELECT * FROM task_history")])
        assert ack["lease_id"] not in dump and "test-device" in dump

    def test_error_mapping(self, client, db_path):
        assert client.post("/api/tasks/999/lease", json=self._body()).status_code == 404
        with _connect(db_path) as c:
            tid = _insert(c)
        bad = self._body()
        bad["request_id"] = "kurz"
        assert client.post(f"/api/tasks/{tid}/lease", json=bad).status_code == 422
        r = client.post(f"/api/tasks/{tid}/lease/renew", json={"lease_id": "x", "fence": 1})
        assert r.status_code == 422

    def test_requires_device_token(self, db_path, tmp_path, monkeypatch, client):
        import gui.server as srv
        anon = TestClient(srv.app, raise_server_exceptions=False)
        assert anon.get("/api/tasks/1/lease").status_code == 401
        assert anon.post("/api/tasks/1/lease", json=self._body()).status_code == 401
