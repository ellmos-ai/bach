import re
import sqlite3

from hub.task import TaskHandler

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _handler(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "bach.db"
    if not db_file.exists():
        with sqlite3.connect(db_file) as conn:
            conn.execute(
                """
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    priority TEXT DEFAULT 'P3',
                    status TEXT DEFAULT 'pending',
                    effort TEXT DEFAULT 'medium',
                    description TEXT,
                    depends_on TEXT,
                    assigned_to TEXT,
                    delegated_to TEXT,
                    delegation_note TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT,
                    created_by TEXT DEFAULT 'user',
                    completed_by TEXT,
                    notes TEXT,
                    tags TEXT,
                    project TEXT,
                    source TEXT,
                    source_file TEXT,
                    recurrence TEXT,
                    due_date TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    action TEXT,
                    field_changed TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    changed_by TEXT,
                    changed_at TEXT
                )
                """
            )
            conn.commit()
    handler = TaskHandler(base_path=tmp_path)
    assert handler.db_path == db_file
    return handler


def _connect(handler):
    conn = sqlite3.connect(str(handler.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _add_pending(handler, title, priority="P3"):
    ok, out = handler.handle("add", [title])
    assert ok, f"add failed: {out}"
    conn = _connect(handler)
    try:
        conn.execute("UPDATE tasks SET priority=?, status='pending' WHERE title=?", (priority, title))
        conn.commit()
        row = conn.execute("SELECT id FROM tasks WHERE title=?", (title,)).fetchone()
        assert row is not None, f"Task {title} nicht angelegt"
        return int(row["id"])
    finally:
        conn.close()


def _row(handler, task_id):
    conn = _connect(handler)
    try:
        return conn.execute("SELECT status, claim_id, claim_fence FROM tasks WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()


def _fence(handler, task_id):
    return int(_row(handler, task_id)["claim_fence"])


def test_take_acquires_lease(tmp_path):
    handler = _handler(tmp_path)
    tid = _add_pending(handler, "Take-Test")
    ok, out = handler.handle("take", [str(tid), "--by", "worker1@host1"])
    assert ok, out
    assert "uebernommen" in out
    assert _row(handler, tid)["claim_id"] is not None


def test_take_conflict_second_worker(tmp_path):
    handler = _handler(tmp_path)
    tid = _add_pending(handler, "Konflikt-Test")
    ok, out = handler.handle("take", [str(tid), "--by", "worker1@host1"])
    assert ok, out
    ok, out = handler.handle("take", [str(tid), "--by", "worker2@host1"])
    assert not ok
    assert "CONFLICT" in out


def test_next_hides_taken_tasks(tmp_path):
    handler = _handler(tmp_path)
    taken = _add_pending(handler, "Taken-Task")
    other = _add_pending(handler, "Other-Task")
    ok, out = handler.handle("take", [str(taken), "--by", "worker1@host1"])
    assert ok, out
    ok, out = handler.handle("next", [])
    assert ok, out
    assert "Taken-Task" not in out
    assert "Other-Task" in out


def test_next_orders_by_priority(tmp_path):
    handler = _handler(tmp_path)
    _add_pending(handler, "P3-Kandidat", "P3")
    _add_pending(handler, "P1-Kandidat", "P1")
    _add_pending(handler, "P2-Kandidat", "P2")
    ok, out = handler.handle("next", [])
    assert ok, out
    assert out.index("P1-Kandidat") < out.index("P2-Kandidat") < out.index("P3-Kandidat")


def test_take_output_has_no_lease_id(tmp_path):
    handler = _handler(tmp_path)
    tid_a = _add_pending(handler, "Alt-Lease-Task")
    ok, out = handler.handle("lease", [str(tid_a), "--by", "worker1@host1"])
    assert ok, out
    assert "Lease-Capability:" in out
    tid_b = _add_pending(handler, "Neu-Take-Task")
    ok, out = handler.handle("take", [str(tid_b), "--by", "worker1@host1"])
    assert ok, out
    assert "Lease-Capability:" not in out
    assert UUID_RE.search(out) is None


def test_renew_and_submit_without_lease(tmp_path):
    handler = _handler(tmp_path)
    tid = _add_pending(handler, "Ohne-Lease-Task")
    ok, out = handler.handle("renew", [str(tid), "--by", "worker1@host1", "--fence", "1"])
    assert not ok
    assert "kein aktives Lease" in out
    ok, out = handler.handle("submit", [str(tid), "--by", "worker1@host1", "--fence", "1", "--result", "Text"])
    assert not ok
    assert "kein aktives Lease" in out


def test_return_sets_pending(tmp_path):
    handler = _handler(tmp_path)
    tid = _add_pending(handler, "Return-Test")
    ok, out = handler.handle("take", [str(tid), "--by", "worker1@host1"])
    assert ok, out
    fence = _fence(handler, tid)
    ok, out = handler.handle("return", [str(tid), "--by", "worker1@host1", "--fence", str(fence)])
    assert ok, out
    assert _row(handler, tid)["status"] == "pending"


def test_block_lease_sets_blocked(tmp_path):
    handler = _handler(tmp_path)
    tid = _add_pending(handler, "Block-Test")
    ok, out = handler.handle("take", [str(tid), "--by", "worker1@host1"])
    assert ok, out
    fence = _fence(handler, tid)
    ok, out = handler.handle("block", [str(tid), "--lease-id", "--by", "worker1@host1", "--fence", str(fence)])
    assert ok, out
    assert _row(handler, tid)["status"] == "blocked"


def test_submit_sets_review(tmp_path):
    handler = _handler(tmp_path)
    tid = _add_pending(handler, "Submit-Test")
    ok, out = handler.handle("take", [str(tid), "--by", "worker1@host1", "--result-generation", "gen1"])
    assert ok, out
    fence = _fence(handler, tid)
    ok, out = handler.handle("submit", [str(tid), "--by", "worker1@host1", "--fence", str(fence), "--result", "Ergebnis"])
    assert ok, out
    assert _row(handler, tid)["status"] == "review"