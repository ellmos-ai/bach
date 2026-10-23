# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit- und Integrationstests fuer Rheingold Client & Hash-to-TaskID Staging."""

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.rheingold import (
    RheingoldTaskCollision,
    generate_draft_hash,
    get_rheingold_url,
    is_rheingold_lead,
    post_task_to_rheingold,
    sync_drafts_to_rheingold,
)
from hub.task import TaskHandler


def _create_test_tasks_table(conn):
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            description TEXT DEFAULT '',
            assigned_to TEXT,
            delegated_to TEXT,
            depends_on TEXT,
            source TEXT,
            creation_origin TEXT,
            due_date TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        )
    """)
    conn.commit()


def test_is_rheingold_lead_with_env(monkeypatch):
    monkeypatch.setenv("BACH_IS_RHEINGOLD_LEAD", "1")
    assert is_rheingold_lead() is True

    monkeypatch.setenv("BACH_IS_RHEINGOLD_LEAD", "0")
    monkeypatch.setattr("socket.gethostname", lambda: "WORKSTATION-LG")
    assert is_rheingold_lead() is False


def test_unreachable_configured_lead_never_probes_another_host():
    with patch("hub.rheingold.get_lead_config", return_value={
        "mode": "worker", "lead_url": "http://lead.example:8000",
    }), patch("hub.rheingold.urllib.request.urlopen", side_effect=OSError("offline")) as request:
        assert get_rheingold_url() is None
    request.assert_called_once()
    assert request.call_args.args[0].full_url == "http://lead.example:8000/api/tasks?limit=1"


def test_reachable_configured_lead_is_returned():
    response = MagicMock()
    response.__enter__.return_value.status = 200
    with patch("hub.rheingold.get_lead_config", return_value={
        "mode": "worker", "lead_url": "http://lead.example:8000",
    }), patch("hub.rheingold.urllib.request.urlopen", return_value=response) as request:
        assert get_rheingold_url() == "http://lead.example:8000"
    request.assert_called_once()


def test_generate_draft_hash_format():
    h = generate_draft_hash("Mein lokaler Task", "feature", host="laptop")
    assert h.startswith("draft:laptop:")
    assert len(h.split(":")) == 3
    assert len(h.split(":")[2]) == 8


def test_offline_task_staging_with_negative_id(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.close()

    handler = TaskHandler(tmp_path)
    handler.db_path = db_path

    # Im Offline-Modus anlegen
    ok, msg = handler.handle("add", ["Test Offline Task", "--priority", "P2", "--offline"])
    assert ok is True
    assert "[OFFLINE]" in msg
    assert "draft:" in msg

    # Task prüfen
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT id, title, priority, source FROM tasks").fetchone()
    conn.close()

    assert row is not None
    assert row[0] < 0  # Negative Staging-ID
    assert row[1] == "Test Offline Task"
    assert row[2] == "P2"
    assert row[3].startswith("draft:")

    # Prüfen, dass list den Draft sauber anzeigt
    ok_list, list_msg = handler.handle("list", ["all"])
    assert ok_list is True
    assert "[DRAFT -1]" in list_msg
    assert "(lokaler Entwurf)" in list_msg


def test_remote_add_preserves_unrelated_local_task_on_id_collision(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir()
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, source) "
        "VALUES (1250, 'Local recurring task', 'pending', 'recurring')"
    )
    conn.commit()
    conn.close()
    handler = TaskHandler(tmp_path)
    monkeypatch.setenv("BACH_TEST_RHEINGOLD", "1")
    monkeypatch.setattr(
        "hub.task.get_lead_config",
        lambda: {"mode": "worker", "lead_url": "http://fake-rheingold:8000"},
    )
    monkeypatch.setattr(
        "hub.task.get_rheingold_url",
        lambda timeout=1.2: "http://fake-rheingold:8000",
    )
    monkeypatch.setattr(
        "hub.task.post_task_to_rheingold",
        lambda *args, **kwargs: (True, {"success": True, "id": 1250}),
    )

    ok, message = handler.handle("add", ["Different remote task"])

    assert ok is False
    assert "COLLISION" in message
    with sqlite3.connect(db_path) as check:
        row = check.execute("SELECT title, source FROM tasks WHERE id = 1250").fetchone()
    assert row == ("Local recurring task", "recurring")


def test_sync_drafts_promotes_to_official_id(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)

    # Einen Offline-Draft manuell anlegen
    conn.execute("""
        INSERT INTO tasks (id, title, priority, category, description, status, source, created_at)
        VALUES (-1, 'Gestageter Task', 'P1', 'feature', 'Wartet auf Rheingold', 'pending', 'draft:wks:12345678', datetime('now'))
    """)
    conn.execute(
        "UPDATE tasks SET creation_origin = 'recurring' WHERE id = -1"
    )
    conn.commit()

    # Mock: Rheingold vergibt ID 1250
    mock_response = (True, {"success": True, "id": 1250, "status": "created"})
    sent_payloads = []
    with patch(
        "hub.rheingold.post_task_to_rheingold",
        side_effect=lambda _url, payload: (sent_payloads.append(payload) or mock_response),
    ):
        promoted = sync_drafts_to_rheingold(conn, "http://fake-rheingold:8000")

    assert len(promoted) == 1
    assert promoted[0]["old_id"] == -1
    assert promoted[0]["new_id"] == 1250
    assert promoted[0]["draft_hash"] == "draft:wks:12345678"
    assert sent_payloads[0]["creation_origin"] == "recurring"

    # Prüfe DB-Stand
    row = conn.execute(
        "SELECT id, title, source, creation_origin FROM tasks WHERE id = 1250"
    ).fetchone()
    assert row is not None
    assert row[0] == 1250
    assert row[1] == "Gestageter Task"
    assert row[2:] == ("promoted:draft:wks:12345678", "recurring")

    # Der alte negative Eintrag darf nicht mehr existieren
    old_row = conn.execute("SELECT id FROM tasks WHERE id = -1").fetchone()
    assert old_row is None

    conn.close()


def test_sync_drafts_preserves_both_rows_on_id_collision(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, source) VALUES "
        "(-1, 'Draft', 'pending', 'draft:wks:12345678'), "
        "(1250, 'Local recurring task', 'pending', 'recurring')"
    )
    conn.commit()

    with patch(
        "hub.rheingold.post_task_to_rheingold",
        return_value=(True, {"success": True, "id": 1250, "status": "created"}),
    ):
        with pytest.raises(RheingoldTaskCollision, match="bereits"):
            sync_drafts_to_rheingold(conn, "http://fake-rheingold:8000")

    rows = conn.execute("SELECT id, title, source FROM tasks ORDER BY id").fetchall()
    assert rows[0][0:2] == (-1, "Draft")
    assert rows[0][2].startswith("collision:draft:wks:12345678:remote:1250")
    assert rows[1][0:2] == (1250, "Local recurring task")
    conn.close()


def test_lead_config_isolated_by_default(monkeypatch):
    from hub.rheingold import get_lead_config
    monkeypatch.setattr("socket.gethostname", lambda: "WORKSTATION-LG")
    cfg = get_lead_config()
    assert cfg["mode"] == "isolated"
    assert cfg["lead_url"] is None


def test_set_and_clear_lead_config(tmp_path, monkeypatch):
    from hub.rheingold import get_lead_config, set_lead_url, clear_lead_config
    cfg_file = tmp_path / "lead.json"
    monkeypatch.setattr("hub.rheingold.LEAD_CONFIG_FILE", cfg_file)
    monkeypatch.setenv("BACH_TEST_RHEINGOLD", "1")
    monkeypatch.setattr("socket.gethostname", lambda: "WORKSTATION-LG")

    p = set_lead_url("http://custom-lead:8000")
    assert p.is_file()
    cfg = get_lead_config()
    assert cfg["mode"] == "worker"
    assert cfg["lead_url"] == "http://custom-lead:8000"

    cleared = clear_lead_config()
    assert cleared is True
    assert not cfg_file.exists()
    cfg_after = get_lead_config()
    assert cfg_after["mode"] == "isolated"


def test_pull_tasks_mirrors_to_local_bachgrund(tmp_path):
    from hub.rheingold import pull_tasks_from_rheingold
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)

    mock_server_data = {
        "success": True,
        "tasks": [
            {
                "id": 101,
                "title": "Task 101",
                "status": "pending",
                "priority": "P2",
                "creation_origin": "recurring",
            },
            {"id": 102, "title": "Task 102", "status": "done", "priority": "P1"},
        ]
    }

    class MockResponse:
        status = 200
        def read(self):
            import json
            return json.dumps(mock_server_data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResponse()):
        inserted, updated = pull_tasks_from_rheingold(conn, "http://fake-rheingold:8000")

    assert inserted == 2
    assert updated == 0

    rows = conn.execute("SELECT id, title, status FROM tasks ORDER BY id ASC").fetchall()
    assert len(rows) == 2
    assert rows[0][0] == 101
    assert rows[1][0] == 102
    assert rows[1][2] == "done"
    assert conn.execute(
        "SELECT creation_origin FROM tasks WHERE id = 101"
    ).fetchone()[0] == "recurring"
    conn.close()


def test_pull_tasks_aborts_before_overwriting_local_id_collision(tmp_path):
    from hub.rheingold import pull_tasks_from_rheingold

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, source) "
        "VALUES (101, 'Local recurring task', 'pending', 'recurring')"
    )
    conn.commit()
    mock_server_data = {
        "success": True,
        "tasks": [{"id": 101, "title": "Different remote task", "status": "pending"}],
    }

    class MockResponse:
        status = 200

        def read(self):
            import json
            return json.dumps(mock_server_data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResponse()):
        with pytest.raises(RheingoldTaskCollision, match="Pull abgebrochen"):
            pull_tasks_from_rheingold(conn, "http://fake-rheingold:8000")

    row = conn.execute("SELECT title FROM tasks WHERE id = 101").fetchone()
    assert row[0] == "Local recurring task"
    conn.close()


def test_pull_tasks_allows_remote_rename_with_matching_creation_identity(tmp_path):
    from hub.rheingold import pull_tasks_from_rheingold

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, source, created_at) "
        "VALUES (101, 'Old remote title', 'pending', NULL, '2026-09-27T10:00:00')"
    )
    conn.commit()
    mock_server_data = {
        "success": True,
        "tasks": [{
            "id": 101,
            "title": "Renamed remote task",
            "status": "pending",
            "created_at": "2026-09-27T10:00:00",
        }],
    }

    class MockResponse:
        status = 200

        def read(self):
            import json
            return json.dumps(mock_server_data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResponse()):
        inserted, updated = pull_tasks_from_rheingold(
            conn, "http://fake-rheingold:8000"
        )

    assert (inserted, updated) == (0, 1)
    row = conn.execute("SELECT title FROM tasks WHERE id = 101").fetchone()
    assert row[0] == "Renamed remote task"
    conn.close()


def test_task_lead_command(tmp_path, monkeypatch):
    cfg_file = tmp_path / "lead.json"
    monkeypatch.setattr("hub.rheingold.LEAD_CONFIG_FILE", cfg_file)
    monkeypatch.setenv("BACH_TEST_RHEINGOLD", "1")
    monkeypatch.setattr("socket.gethostname", lambda: "WORKSTATION-LG")

    handler = TaskHandler(tmp_path)
    handler.db_path = tmp_path / "bach.db"

    # Show isolated
    ok, msg = handler.handle("lead", ["show"])
    assert ok is True
    assert "ISOLATED" in msg

    # Set lead
    ok_set, set_msg = handler.handle("lead", ["set", "http://test-server:8000"])
    assert ok_set is True
    assert "http://test-server:8000" in set_msg

    # Clear lead
    ok_clr, clr_msg = handler.handle("lead", ["clear"])
    assert ok_clr is True
    assert "isolierten Standalone-Modus" in clr_msg


# Task1731: native authority before any projection write.
@pytest.fixture
def worker_writer(tmp_path, monkeypatch):
    db = tmp_path / "data" / "bach.db"
    db.parent.mkdir()
    with sqlite3.connect(db) as conn:
        _create_test_tasks_table(conn)
    handler = TaskHandler(tmp_path)
    monkeypatch.setenv("BACH_TEST_RHEINGOLD", "1")
    monkeypatch.delenv("BACH_RHEINGOLD_DISABLED", raising=False)
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {
        "mode": "worker", "lead_url": "https://lead.invalid",
    })
    monkeypatch.setattr(handler, "_get_db", lambda: pytest.fail("Worker opened local projection"))
    return handler


AUTH = ["--lease-id", "own-capability", "--fence", "7", "--task-version", "a" * 64]


@pytest.mark.parametrize("operation,args,fields", [
    ("edit", ["23", "--title", "Neuer Titel"], {"title": "Neuer Titel"}),
    ("edit", ["23", "--description", "Änderung"], {"description": "Änderung"}),
    ("edit", ["23", "--required-model", "", "--assigned-slot", ""],
     {"required_model": None, "assigned_slot": None}),
    ("edit", ["23", "--result-max-chars", "none"], {"result_max_chars": None}),
    ("priority", ["23", "P2"], {"priority": "P2"}),
    ("assign", ["23", "--to", "BACH"], {"assigned_to": "BACH", "delegated_to": "BACH"}),
])
def test_worker_routes_content_before_opening_projection(worker_writer, monkeypatch, operation, args, fields):
    calls = []
    def update(url, task_id, changes, **binding):
        calls.append((url, task_id, changes, binding))
        return True, "native ACK/readback"
    monkeypatch.setattr("hub.task.patch_task_to_rheingold", update)
    assert worker_writer.handle(operation, args + AUTH) == (True, "native ACK/readback")
    assert calls == [("https://lead.invalid", 23, fields, {
        "lease_id": "own-capability", "fence": 7, "task_version": "a" * 64,
    })]


@pytest.mark.parametrize("operation,args", [
    ("edit", ["23", "--title", "Änderung"]), ("priority", ["23", "P1"]),
    ("assign", ["23", "--to", "BACH"]),
])
@pytest.mark.parametrize("authority", [[], AUTH + ["--fence=8"], AUTH[:2] + ["--fence=bad", "--task-version=" + "a"*64]])
def test_worker_missing_or_ambiguous_binding_never_writes(worker_writer, monkeypatch, operation, args, authority):
    monkeypatch.setattr("hub.task.patch_task_to_rheingold", lambda *a, **k: pytest.fail("invalid binding dispatched"))
    assert worker_writer.handle(operation, args + authority)[0] is False


@pytest.mark.parametrize("config", [
    {"mode": "worker", "lead_url": None},
    {"mode": "invalid", "lead_url": "https://lead.invalid"},
])
def test_missing_lead_or_invalid_role_never_opens_projection(worker_writer, monkeypatch, config):
    monkeypatch.setattr("hub.task.get_lead_config", lambda: config)
    assert worker_writer.handle("priority", ["23", "P1"] + AUTH)[0] is False


def test_worker_assignment_rejects_batch_before_first_effect(worker_writer, monkeypatch):
    monkeypatch.setattr("hub.task.patch_task_to_rheingold", lambda *a, **k: pytest.fail("batch dispatched"))
    assert worker_writer.handle("assign", ["23", "24", "--to", "BACH"] + AUTH)[0] is False


@pytest.mark.parametrize("option", ["--lease", "--lease=90", "--lease-seconds", "--lease-seconds=90"])
def test_remote_claim_never_silently_translates_legacy_duration(worker_writer, monkeypatch, option):
    monkeypatch.setattr(worker_writer, "_lease", lambda *a: pytest.fail("legacy duration dispatched"))
    assert worker_writer.handle("claim", ["23", "--by", "codex@host", option, "90"])[0] is False


def test_remote_claim_uses_existing_native_lease_path(worker_writer, monkeypatch):
    calls = []
    monkeypatch.setattr(worker_writer, "_lease", lambda args: (calls.append(args) or (True, "native lease")))
    args = ["23", "--by", "codex@host", "--ttl", "L", "--task-version=" + "a"*64]
    assert worker_writer.handle("claim", args) == (True, "native lease")
    assert calls == [args]


@pytest.mark.parametrize("role", ["lead", "isolated"])
def test_explicit_local_authority_stays_local(worker_writer, monkeypatch, role):
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": role, "lead_url": None})
    assert worker_writer._remote_writer_target() is None


def test_explicit_noncanonical_database_is_not_remote(worker_writer):
    worker_writer.db_path = worker_writer.db_path.parent / "isolated.db"
    assert worker_writer._remote_writer_target() is None


@pytest.mark.parametrize("failure", ["update", "readback", "conflict"])
def test_native_patch_failure_never_retries_or_claims_success(monkeypatch, failure):
    from types import SimpleNamespace

    from hub._services.task_lease_client import LeaseConnectionError
    from hub.rheingold import patch_task_to_rheingold
    calls = []
    class Client:
        mode = "remote"
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def update(self, *args, **kwargs):
            calls.append("update")
            if failure == "update":
                raise LeaseConnectionError("private secret must not escape")
            return SimpleNamespace(task_version="b"*64, fence=7)
        def task_snapshot(self, task_id):
            calls.append("readback")
            if failure == "readback":
                raise LeaseConnectionError("private secret must not escape")
            return {"id": task_id, "task_version": "b"*64, "priority": "P4"}
    monkeypatch.setattr("hub._services.task_lease_client.TaskLeaseClient", Client)
    ok, text = patch_task_to_rheingold("https://lead.invalid", 23, {"priority": "P1"},
        lease_id="cap", fence=7, task_version="a"*64)
    assert ok is False
    assert "secret" not in text
    assert calls.count("update") == 1
    assert calls == (["update"] if failure == "update" else ["update", "readback"])


def test_native_patch_preserves_guard_and_fenced_assignment_and_null_clear(tmp_path, monkeypatch):
    from hub._services.task_lease import ensure_task_lease_schema
    from hub._services.task_lease_client import TaskLeaseClient as NativeClient
    from hub.rheingold import patch_task_to_rheingold
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_test_tasks_table(conn)
    conn.execute("INSERT INTO tasks(id,title,status,created_at) VALUES(23,'Native Task','pending','2020-01-01T00:00:00')")
    conn.commit()
    ensure_task_lease_schema(conn)
    conn.execute("UPDATE tasks SET required_model='fixture-model', assigned_slot='fixture-slot' WHERE id=23")
    conn.commit()
    native = NativeClient(conn=conn)
    ack = native.acquire(23, worker_id="codex@host", host="host")
    changes = {"assigned_to": "BACH", "delegated_to": "BACH", "required_model": None, "assigned_slot": None}
    class Transport:
        mode = "remote"
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def update(self, *a, **k): return native.update(*a, **k)
        def task_snapshot(self, tid): return native.task_snapshot(tid)
    monkeypatch.setattr("hub._services.task_lease_client.TaskLeaseClient", Transport)
    ok, message = patch_task_to_rheingold("https://lead.invalid", 23, changes,
        lease_id=ack.lease_id, fence=ack.fence, task_version=ack.task_version)
    assert ok is True
    current = native.task_snapshot(23)
    assert all(current[k] == v for k, v in changes.items())
    assert current["task_version"] != ack.task_version
    assert str(ack.lease_id) not in message
    # Prior version cannot be replayed; stale-fence paths still close.
    ok, _ = patch_task_to_rheingold("https://lead.invalid", 23, {"priority": "P1"},
        lease_id=ack.lease_id, fence=ack.fence, task_version=ack.task_version)
    assert ok is False
    assert native.task_snapshot(23)["priority"] == "P3"
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE field_changed='delegated_to'").fetchone()[0] == 1
    for field in ("required_model", "assigned_slot"):
        history = conn.execute("SELECT old_value,new_value FROM task_history WHERE field_changed=?", (field,)).fetchone()
        assert history[0] == {"required_model": "fixture-model", "assigned_slot": "fixture-slot"}[field]
        assert history[1] is None
    ok, _ = patch_task_to_rheingold("https://lead.invalid", 23, {"priority": "P1"},
        lease_id=ack.lease_id, fence=ack.fence + 1, task_version=current["task_version"])
    assert ok is False
    assert native.task_snapshot(23)["priority"] == "P3"
    conn.close()


def test_remote_done_delegates_to_native_release_and_completion_guard(worker_writer, monkeypatch):
    calls = []
    def release(args):
        calls.append(args)
        return False, "completion_guard"
    monkeypatch.setattr(worker_writer, "_lease_release", release)
    args = ["23"] + AUTH + ["--ref", "result-ref"]
    assert worker_writer.handle("done", args) == (False, "completion_guard")
    assert calls == [[
        "23", "--lease-id=own-capability", "--fence=7",
        "--task-version=" + "a"*64, "--ref=result-ref", "--outcome=done",
    ]]


@pytest.mark.parametrize("args", [
    ["23"], ["23", "24"] + AUTH, ["23"] + AUTH + ["--outcome=return"],
    ["23"] + AUTH + ["--fence=8"], ["23"] + AUTH + ["--note"],
    ["23"] + AUTH + ["--ref", "A", "--result-ref", "B"],
])
def test_remote_done_rejects_unbound_batch_or_ambiguous_request(worker_writer, monkeypatch, args):
    monkeypatch.setattr(worker_writer, "_lease_release", lambda *a: pytest.fail("invalid done dispatched"))
    assert worker_writer.handle("done", args)[0] is False


@pytest.mark.parametrize("operation,args", [
    ("done", ["23"]), ("claim", ["23", "--by", "codex@host"]),
    ("priority", ["23", "P1"]), ("edit", ["23", "--title", "Änderung"]),
    ("assign", ["23", "--to", "BACH"]),
])
def test_worker_dry_run_never_dispatches(worker_writer, monkeypatch, operation, args):
    monkeypatch.setattr(worker_writer, "_remote_writer_target", lambda: pytest.fail("dry run dispatched"))
    assert worker_writer.handle(operation, args + AUTH, dry_run=True)[0] is True


@pytest.mark.parametrize("field", ["--note", "--ref", "--result-ref"])
def test_done_option_shaped_payload_cannot_replace_explicit_task_version(worker_writer, monkeypatch, field):
    from types import SimpleNamespace

    from hub._services.task_lease_client import TaskLeaseClient

    calls = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def release(self, task_id, **kwargs):
            calls.append((task_id, kwargs))
            return SimpleNamespace(outcome="done", status="done", fence=7)
    monkeypatch.setattr(TaskLeaseClient, "for_task_db", lambda *a, **k: Client())
    args = ["23", field, "--task-version=" + "b"*64] + AUTH
    assert worker_writer.handle("done", args)[0] is True
    assert calls[0][1]["task_version"] == "a"*64
    assert calls[0][1]["lease_id"] == "own-capability"
    assert calls[0][1]["fence"] == 7
    assert calls[0][1]["outcome"] == "done"
    assert calls[0][1]["note" if field == "--note" else "result_ref"] == "--task-version=" + "b"*64
