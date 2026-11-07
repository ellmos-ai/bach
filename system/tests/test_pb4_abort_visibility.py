"""PB-4 (#3988): aborts are visible in the GUI and reach the user's inbox once.

Measured 06.11.2026: a lease return loop ran for days (~560 returns/h, task #3825
with return_count >= 65) because no screen showed returns. Data side of the GUI work:
a global return timeline, the structured "waiting for a host precondition" worker
state, and one Postfach message per repeated abort (setting default on, no Telegram).
"""
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from system.tests.test_worker_policy_settings import _auth, api, db_path  # noqa: F401 -- fixtures


def _local(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _release(conn, task_id, worker, note, at, outcome="return"):
    conn.execute(
        "INSERT INTO task_history (task_id, action, field_changed, old_value, new_value, changed_by, changed_at) "
        "VALUES (?, 'lease_release', 'lease', 'in_progress', ?, ?, ?)",
        (task_id, json.dumps({"fence": 1, "note": note, "outcome": outcome}), worker, _local(at)))


@pytest.fixture
def timeline_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hub import bach_paths
    from gui.api.task_returns import router
    from system.tests import test_task_lease_service as service
    database = tmp_path / "canonical.db"
    service._create_db(database)
    conn = service._connect(database)
    first = service._insert(conn, title="Erste Aufgabe")
    second = service._insert(conn, title="Zweite Aufgabe")
    now = datetime.now()
    _release(conn, first, "worker-aaaa@HOST", "task_scope_unavailable", now - timedelta(hours=1))
    _release(conn, first, "worker-aaaa@HOST", "task_scope_unavailable", now - timedelta(minutes=5))
    _release(conn, second, "worker-bbbb@HOST", "host_precondition:twin_status_unknown", now - timedelta(hours=30))
    _release(conn, second, "worker-bbbb@HOST", "", now - timedelta(minutes=3), outcome="review")  # a result, no return
    conn.execute("INSERT INTO task_history (task_id, action, field_changed, old_value, new_value, changed_by, changed_at) "
                 "VALUES (?, 'lease_release', 'lease', NULL, 'kein json', 'x', ?)", (first, _local(now)))
    conn.commit()
    conn.close()
    monkeypatch.setattr(bach_paths, "BACH_DB", database)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.first, client.second = first, second
    return client


def test_timeline_lists_returns_newest_first_without_results_or_garbage(timeline_client):
    body = timeline_client.get("/api/task-returns/timeline?hours=24").json()
    assert body["schema"] == "bach.task-return-timeline.v1" and body["hours"] == 24
    assert [event["reason"] for event in body["events"]] == ["task_scope_unavailable"] * 2
    event = body["events"][0]
    assert (event["task_id"], event["task_title"], event["worker"]) == (
        timeline_client.first, "Erste Aufgabe", "worker-aaaa@HOST")
    assert event["outcome"] == "return" and event["at"].startswith(str(datetime.now().year))
    assert body["total"] == 2 and body["truncated"] is False
    assert body["by_reason"] == {"task_scope_unavailable": 2}


def test_timeline_window_task_and_limit(timeline_client):
    week = timeline_client.get("/api/task-returns/timeline?hours=168").json()
    assert week["total"] == 3 and week["by_reason"]["host_precondition:twin_status_unknown"] == 1
    one = timeline_client.get(f"/api/task-returns/timeline?hours=168&task_id={timeline_client.second}").json()
    assert [e["task_id"] for e in one["events"]] == [timeline_client.second] and one["total"] == 1
    cut = timeline_client.get("/api/task-returns/timeline?hours=168&limit=1").json()
    assert len(cut["events"]) == 1 and cut["truncated"] is True and cut["total"] == 3


@pytest.mark.parametrize("query", ["hours=0", "hours=721", "hours=x", "limit=0", "limit=501", "task_id=0"])
def test_timeline_rejects_bad_parameters(timeline_client, query):
    assert timeline_client.get("/api/task-returns/timeline?" + query).status_code in {400, 422}


# --- Postfach: exactly one message per repeated abort -------------------------------------

def _inbox_db(tmp_path):
    from system.tests import test_task_lease_service as service
    database = tmp_path / "inbox.db"
    service._create_db(database)
    conn = service._connect(database)
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT NOT NULL, sender TEXT NOT NULL, "
        "recipient TEXT NOT NULL, subject TEXT, body TEXT NOT NULL, body_type TEXT DEFAULT 'text', "
        "priority INTEGER DEFAULT 0, status TEXT DEFAULT 'unread', tags TEXT, parent_id INTEGER, thread_id TEXT, "
        "topic TEXT, attachments TEXT, metadata TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "read_at TIMESTAMP, archived_at TIMESTAMP)")
    conn.commit()
    return conn


def _inbox(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM messages ORDER BY id")]


def test_repeated_return_block_posts_one_inbox_message(tmp_path):
    from system.tests.test_task_lease_service import _get, _insert
    from hub.task_audit import apply_task_field_changes
    conn = _inbox_db(tmp_path)
    tid = _insert(conn, title="Schleifenaufgabe")

    def block(reason):
        apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "blocked"},
                                 changed_by="worker-x", allow_reopen=True, block_reason=reason)
        conn.commit()

    block("lease_release: repeated_return:task_scope_unavailable")
    message, = _inbox(conn)
    assert (message["direction"], message["recipient"], message["status"]) == ("inbox", "user", "unread")
    assert f"#{tid}" in message["subject"] and "Schleifenaufgabe" in message["body"]
    assert "task_scope_unavailable" in message["body"] and message["priority"] == 1
    assert json.loads(message["metadata"])["notice_key"].startswith(f"repeated_return:task:{tid}:")
    apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "pending"}, changed_by="user", allow_reopen=True)
    block("lease_release: repeated_return:task_scope_unavailable")  # same open resolver, same event
    assert len(_inbox(conn)) == 1


def test_other_blocks_stay_silent(tmp_path):
    from system.tests.test_task_lease_service import _get, _insert
    from hub.task_audit import apply_task_field_changes
    conn = _inbox_db(tmp_path)
    tid = _insert(conn)
    apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "blocked"}, changed_by="cli-task",
                             allow_reopen=True, block_reason="bach task block: Test-Sperre")
    assert _inbox(conn) == []


def test_worker_resolver_posts_one_inbox_message(tmp_path):
    from hub.task_audit import ensure_worker_error_resolver
    conn = _inbox_db(tmp_path)
    assert ensure_worker_error_resolver(conn, "worker-fdb98a89", "twin_status_unknown") is not None
    assert ensure_worker_error_resolver(conn, "worker-fdb98a89", "twin_status_unknown") is None
    message, = _inbox(conn)
    assert "worker-fdb98a89" in message["subject"] and "twin_status_unknown" in message["body"]


def test_notice_without_messages_table_or_switched_off_is_silent(tmp_path):
    from system.tests.test_task_lease_service import _create_db, _connect
    from hub._services import abort_notices
    plain = tmp_path / "plain.db"
    _create_db(plain)
    conn = _connect(plain)
    assert abort_notices.post(conn, "k", "Betreff", "Text") is None  # no table: never breaks the block
    conn = _inbox_db(tmp_path)
    conn.execute("INSERT INTO system_config(key,value) VALUES (?,?)", (abort_notices.KEY, json.dumps(
        {"revision": 1, "values": {"repeated_abort": False}})))
    conn.commit()
    assert abort_notices.post(conn, "k", "Betreff", "Text") is None and _inbox(conn) == []
    assert abort_notices.stored_enabled(conn) is False


# --- switch for the notice ------------------------------------------------------------------

PATH = "/api/system/abort-notice-settings"


def test_switch_is_on_by_default_and_changes_with_cas(api):  # noqa: F811
    before = api.client.get(PATH, headers=_auth(api))
    assert before.status_code == 200
    assert (before.json()["repeated_abort"], before.json()["source"]) == (True, "system_default")
    payload = {"configuration_version": before.json()["configuration_version"], "repeated_abort": False}
    assert api.client.put(PATH, headers=_auth(api), json=payload).status_code == 200
    after = api.client.get(PATH, headers=_auth(api)).json()
    assert (after["repeated_abort"], after["source"]) == (False, "user_override")
    assert api.client.put(PATH, headers=_auth(api), json=payload).status_code == 409
    bad = {"configuration_version": after["configuration_version"], "repeated_abort": "nein"}
    assert api.client.put(PATH, headers=_auth(api), json=bad).status_code == 400
    assert api.client.get(PATH).status_code == 401


# --- worker waiting for a host precondition (structured, not parsed from text) ----------------

def test_waiting_precondition_is_projected_validated_and_bounded():
    from hub._services.chat.worker_queue_status import project_precondition_wait
    wait = {"state": "waiting_precondition", "code": "twin_status_unknown", "attempt": 3,
            "next_check_at": "2026-11-07T10:15:00+00:00"}
    assert project_precondition_wait(wait) == wait
    for bad in (None, {}, {**wait, "state": "x"}, {**wait, "code": "Twin unbekannt"}, {**wait, "attempt": 0},
                {**wait, "attempt": True}, {**wait, "next_check_at": "morgen"}, {**wait, "extra": 1}):
        assert project_precondition_wait(bad) is None


def test_host_precondition_wait_reaches_the_worker_status_and_clears():
    from hub._services.chat import telegram_chat
    control = telegram_chat._WorkerControl.__new__(telegram_chat._WorkerControl)
    control.precondition_wait = None
    telegram_chat._set_precondition_wait(control, "twin_status_unknown", 2, 120)
    wait = control.precondition_wait
    assert (wait["state"], wait["code"], wait["attempt"]) == ("waiting_precondition", "twin_status_unknown", 2)
    delta = datetime.fromisoformat(wait["next_check_at"]) - datetime.now(datetime.fromisoformat(wait["next_check_at"]).tzinfo)
    assert timedelta(seconds=100) < delta <= timedelta(seconds=121)
    telegram_chat._set_precondition_wait(control, None)
    assert control.precondition_wait is None


def test_worker_status_adapter_passes_only_a_valid_precondition_wait():
    from gui.api.worker_status_adapter import _project_worker
    wait = {"state": "waiting_precondition", "code": "project_lock", "attempt": 4,
            "next_check_at": "2026-11-07T10:15:00+00:00"}
    assert _project_worker({"id": "worker-1", "precondition_wait": wait})["precondition_wait"] == wait
    assert "precondition_wait" not in _project_worker({"id": "worker-1", "precondition_wait": {**wait, "attempt": 0}})
    assert "precondition_wait" not in _project_worker({"id": "worker-1"})


# --- R2: the inbox is capped (E1 "nur Wichtiges"): single messages per hour, then one summary ---------

def _many_tasks(conn, count):
    from system.tests.test_task_lease_service import _insert
    return [_insert(conn, title=f"Aufgabe {i}") for i in range(count)]


def _block_all(conn, ids):
    from system.tests.test_task_lease_service import _get
    from hub.task_audit import apply_task_field_changes
    for tid in ids:
        apply_task_field_changes(conn, tid, _get(conn, tid), {"status": "blocked"}, changed_by="worker-x",
                                 allow_reopen=True, block_reason="lease_release: repeated_return:task_scope_unavailable")
    conn.commit()


def test_forty_blocked_tasks_in_one_hour_make_at_most_four_messages(tmp_path):
    conn = _inbox_db(tmp_path)
    ids = _many_tasks(conn, 40)
    _block_all(conn, ids)
    messages = _inbox(conn)
    assert len(messages) == 4
    singles, summary = messages[:3], messages[3]
    assert all(json.loads(m["metadata"]).get("kind", "single") == "single" for m in singles)
    assert "37 weitere" in summary["subject"]
    assert all(f"#{tid}" in summary["body"] for tid in ids[3:])  # nothing is lost, it is listed
    assert "/tasks" in summary["body"]


def test_twenty_worker_resolvers_in_one_hour_make_at_most_four_messages(tmp_path):
    from hub.task_audit import ensure_worker_error_resolver
    conn = _inbox_db(tmp_path)
    for n in range(20):
        assert ensure_worker_error_resolver(conn, f"worker-{n:04d}", "twin_status_unknown") is not None
    assert len(_inbox(conn)) == 4


def test_summary_is_updated_not_repeated_and_unread_again(tmp_path):
    conn = _inbox_db(tmp_path)
    ids = _many_tasks(conn, 8)
    _block_all(conn, ids[:5])
    summary_id = _inbox(conn)[3]["id"]
    conn.execute("UPDATE messages SET status='read' WHERE id=?", (summary_id,))
    _block_all(conn, ids[5:])
    messages = _inbox(conn)
    assert len(messages) == 4
    assert messages[3]["id"] == summary_id and messages[3]["status"] == "unread"
    assert "5 weitere" in messages[3]["subject"]


def test_old_singles_do_not_count_against_the_hour(tmp_path):
    from hub._services import abort_notices
    conn = _inbox_db(tmp_path)
    for n in range(3):
        abort_notices.post(conn, f"old:{n}", "alt", "alt")
    conn.execute("UPDATE messages SET created_at = datetime('now', '-2 hours')")
    assert abort_notices.post(conn, "new:1", "neu", "neu") is not None
    assert [json.loads(m["metadata"]).get("kind", "single") for m in _inbox(conn)][-1] == "single"


def test_cap_is_configurable_and_zero_sends_only_the_summary(tmp_path):
    from hub._services import abort_notices
    conn = _inbox_db(tmp_path)
    conn.execute("INSERT INTO system_config(key,value) VALUES (?,?)", (abort_notices.KEY, json.dumps(
        {"revision": 1, "values": {"repeated_abort": True, "max_per_hour": 1}})))
    conn.commit()
    ids = _many_tasks(conn, 4)
    _block_all(conn, ids)
    assert len(_inbox(conn)) == 2 and "3 weitere" in _inbox(conn)[1]["subject"]
    assert abort_notices.stored_max_per_hour(conn) == 1
    conn.execute("UPDATE system_config SET value=? WHERE key=?", (json.dumps(
        {"revision": 2, "values": {"repeated_abort": True, "max_per_hour": 0}}), abort_notices.KEY))
    conn.execute("DELETE FROM messages")
    conn.commit()
    abort_notices.post(conn, "z:1", "eins", "x")
    only, = _inbox(conn)
    assert "1 weitere" in only["subject"]


def test_max_per_hour_in_the_settings_api(api):  # noqa: F811
    before = api.client.get(PATH, headers=_auth(api)).json()
    assert before["max_per_hour"] == 3
    payload = {"configuration_version": before["configuration_version"], "repeated_abort": True, "max_per_hour": 5}
    assert api.client.put(PATH, headers=_auth(api), json=payload).status_code == 200
    after = api.client.get(PATH, headers=_auth(api)).json()
    assert (after["max_per_hour"], after["repeated_abort"]) == (5, True)
    for bad in ("x", -1, 21, True):
        body = {"configuration_version": after["configuration_version"], "repeated_abort": True, "max_per_hour": bad}
        assert api.client.put(PATH, headers=_auth(api), json=body).status_code == 400
