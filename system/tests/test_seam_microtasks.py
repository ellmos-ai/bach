"""Unit tests for BACH-to-ELLMOS Seam Micro-Tasks & Pilot Adapter M1 (Ticket T-20260909-566626503)."""

from pathlib import Path
import sqlite3
import pytest

from hub._services.chat.seam_microtasks import (
    MICRO_TASK_CATALOG,
    ensure_seam_microtasks,
    run_microtask_preflight,
    claim_microtask,
    escalate_failed_microtask,
    complete_microtask,
)
from hub._services.chat.session_store import EllmosChatStoreAdapter, SQLiteChatSessionStore

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def seam_db(tmp_path):
    """Temporary database with tasks table for testing micro-tasks."""
    db_path = tmp_path / "seam_bach.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            category TEXT,
            assigned_to TEXT,
            source TEXT,
            result TEXT,
            depends_on TEXT,
            claimed_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return db_path


def test_microtask_catalog_definitions():
    assert len(MICRO_TASK_CATALOG) == 5
    codes = [m["code"] for m in MICRO_TASK_CATALOG]
    assert codes == ["M1", "M2", "M3", "M4", "M5"]

    # Verify dependency chain
    m_dict = {m["code"]: m for m in MICRO_TASK_CATALOG}
    assert m_dict["M1"]["depends_on"] is None
    assert m_dict["M2"]["depends_on"] == "M1"
    assert m_dict["M3"]["depends_on"] == "M2"
    assert m_dict["M4"]["depends_on"] == "M3"
    assert m_dict["M5"]["depends_on"] == "M4"

    # Verify acceptance commands
    for m in MICRO_TASK_CATALOG:
        assert m["acceptance_command"].startswith("pytest ")
        assert m["assigned_to"] if "assigned_to" in m else True


def test_ensure_seam_microtasks_idempotent(seam_db):
    # First seed: creates 5 tasks
    res1 = ensure_seam_microtasks(db_path=seam_db)
    assert res1["success"] is True
    assert res1["created_count"] == 5
    assert res1["existing_count"] == 0

    conn = sqlite3.connect(seam_db)
    conn.row_factory = sqlite3.Row
    tasks = conn.execute("SELECT * FROM tasks ORDER BY id ASC").fetchall()
    conn.close()

    assert len(tasks) == 5
    m1 = tasks[0]
    assert m1["title"].startswith("[Migration M1]")
    assert m1["assigned_to"] == "BUDDHA"
    assert m1["status"] == "pending"
    assert m1["category"] == "migration-seam"
    assert m1["source"] == "migration:M1"
    assert m1["priority"] == "high"

    # Second seed: must be idempotent
    res2 = ensure_seam_microtasks(db_path=seam_db)
    assert res2["success"] is True
    assert res2["created_count"] == 0
    assert res2["existing_count"] == 5

    conn = sqlite3.connect(seam_db)
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    assert count == 5


def test_run_microtask_preflight_dependency_and_lock(seam_db, tmp_path):
    ensure_seam_microtasks(db_path=seam_db)

    # Preflight M1: no dependencies -> ok
    pf_m1 = run_microtask_preflight("M1", repo_path=tmp_path, db_path=seam_db)
    assert pf_m1["ok"] is True

    # Preflight M2: depends on M1, which is still 'pending' -> must fail with dependency_unmet
    pf_m2 = run_microtask_preflight("M2", repo_path=tmp_path, db_path=seam_db)
    assert pf_m2["ok"] is False
    assert pf_m2["reason"] == "dependency_unmet"

    # Mark M1 as completed
    conn = sqlite3.connect(seam_db)
    conn.execute("UPDATE tasks SET status = 'completed' WHERE source = 'migration:M1'")
    conn.commit()
    conn.close()

    # Preflight M2 now passes
    pf_m2_retry = run_microtask_preflight("M2", repo_path=tmp_path, db_path=seam_db)
    assert pf_m2_retry["ok"] is True

    # Test lock safety: create active LOCK file in repo
    lock_file = tmp_path / "LOCK.user.active.txt"
    lock_file.write_text("Sperre aktiv", encoding="utf-8")

    pf_m2_locked = run_microtask_preflight("M2", repo_path=tmp_path, db_path=seam_db)
    assert pf_m2_locked["ok"] is False
    assert pf_m2_locked["reason"] == "lock_active"

    # Remove lock file
    lock_file.unlink()


def test_claim_and_complete_microtask(seam_db):
    res = ensure_seam_microtasks(db_path=seam_db)
    m1_id = res["tasks"]["M1"]["id"]

    # Claim task
    claimed = claim_microtask(m1_id, worker_id="buddha@macstudio", db_path=seam_db)
    assert claimed is True

    conn = sqlite3.connect(seam_db)
    conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (m1_id,)).fetchone()
    conn.close()
    assert t["claimed_by"] == "buddha@macstudio"
    assert t["status"] == "in_progress"

    # Complete task
    completed = complete_microtask(m1_id, result_summary="Tests bestanden (26/26 grün)", db_path=seam_db)
    assert completed is True

    conn = sqlite3.connect(seam_db)
    conn.row_factory = sqlite3.Row
    t2 = conn.execute("SELECT * FROM tasks WHERE id = ?", (m1_id,)).fetchone()
    conn.close()
    assert t2["status"] == "completed"
    assert "Tests bestanden" in t2["result"]


def test_escalate_failed_microtask_after_three_attempts(seam_db):
    res = ensure_seam_microtasks(db_path=seam_db)
    m1_id = res["tasks"]["M1"]["id"]

    # Attempt 1: not escalated
    e1 = escalate_failed_microtask(m1_id, error_log="AssertionError on line 42", attempt_count=1, db_path=seam_db)
    assert e1["escalated"] is False
    assert e1["status"] == "pending"

    # Attempt 2: not escalated
    e2 = escalate_failed_microtask(m1_id, error_log="SyntaxError in adapter", attempt_count=2, db_path=seam_db)
    assert e2["escalated"] is False

    # Attempt 3: reached max_attempts=3 -> escalates to CLAUDE
    e3 = escalate_failed_microtask(m1_id, error_log="ImportError: module broken", attempt_count=3, db_path=seam_db)
    assert e3["escalated"] is True
    assert e3["status"] == "delegated"
    assert e3["assigned_to"] == "CLAUDE"

    conn = sqlite3.connect(seam_db)
    conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM tasks WHERE id = ?", (m1_id,)).fetchone()
    conn.close()

    assert t["status"] == "delegated"
    assert t["assigned_to"] == "CLAUDE"
    assert "ESKALATION AN CLAUDE" in t["description"]
    assert "ImportError: module broken" in t["description"]


def test_pilot_adapter_m1_session_store_fallback(tmp_path):
    # Test that EllmosChatStoreAdapter behaves identical to SQLiteChatSessionStore
    # even when ellmos_chat is not present (fallback mode)
    db_file = tmp_path / "chat_store.db"
    db_file.write_text("", encoding="utf-8")  # empty file

    adapter = EllmosChatStoreAdapter(db_file)
    assert hasattr(adapter, "session_id")
    assert hasattr(adapter, "db_path")
    assert adapter.session_id("chat-42") == SQLiteChatSessionStore.session_id("chat-42")
    assert isinstance(adapter.is_seam_active, bool)
