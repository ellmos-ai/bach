"""Regressionstests fuer Lead-first Mutation bei edit/assign/claim/done (Task #1694).

Der Rheingold-Lead wird als Fake-Server simuliert (monkeypatch auf urlopen):
- Remote verwaltete Tasks (source 'rheingold:*' bzw. 'promoted:draft:*' oder
  creation_origin 'remote') werden zuerst auf dem Lead mutiert; erst nach
  erfolgreichem Readback wird die lokale Zeile angepasst.
- Weicht der Readback ab (Kollision) oder ist der Lead nicht konfiguriert,
  schlagen die Handler fail-closed zu: keine lokale Aenderung.
- Rein lokale Tasks werden nie an den Lead geschickt (keine Bulk-Synchronisation).
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hub.rheingold  # noqa: E402
import hub.task  # noqa: E402
from hub.rheingold import (  # noqa: E402
    mutate_task_on_rheingold,
    readback_task_from_rheingold,
    task_row_is_remote_managed,
)
from hub.task import TaskHandler  # noqa: E402

try:
    import hub._services.task_result_service as _task_result_service
except Exception:  # pragma: no cover - Hook-Modul ist optional
    _task_result_service = None

LEAD_URL = "http://lead.test:8000"


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
            updated_at TEXT,
            claimed_by TEXT,
            claimed_at TEXT
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


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def getcode(self):
        return self.status

    def read(self):
        return json.dumps(self._body).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _extract_task_id(url):
    marker = "/api/tasks/"
    idx = url.rfind(marker)
    if idx < 0:
        return None
    rest = url[idx + len(marker):].split("?")[0].strip("/")
    if not rest:
        return None
    try:
        return int(rest)
    except ValueError:
        return None


class FakeLead:
    """Simuliert die Lead-API: GET /api/tasks[/<id>] und PUT /api/tasks/<id>."""

    def __init__(self, tasks, apply_put=True):
        self.tasks = {t["id"]: dict(t) for t in tasks}
        self.apply_put = apply_put
        self.calls = []

    def __call__(self, req, timeout=None):
        method = req.get_method()
        url = req.full_url
        self.calls.append((method, url))
        if method == "GET":
            if url.endswith("/api/tasks"):
                return _FakeResponse(
                    200, {"success": True, "tasks": list(self.tasks.values())}
                )
            tid = _extract_task_id(url)
            if tid is None or tid not in self.tasks:
                return _FakeResponse(404, {"success": False})
            return _FakeResponse(200, {"success": True, "task": dict(self.tasks[tid])})
        if method == "PUT":
            tid = _extract_task_id(url)
            if tid is None or tid not in self.tasks:
                return _FakeResponse(404, {"success": False})
            raw = req.data
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if self.apply_put:
                self.tasks[tid].update(payload)
            return _FakeResponse(200, {"success": True})
        return _FakeResponse(405, {"success": False})

    def put_calls(self):
        return [c for c in self.calls if c[0] == "PUT"]


class _Raiser:
    def __call__(self, req, timeout=None):
        raise OSError("boom")


def _patch_urlopen(monkeypatch, repl):
    monkeypatch.setattr("urllib.request.urlopen", repl)
    monkeypatch.setattr("hub.rheingold.urlopen", repl, raising=False)


def _allow_completion(monkeypatch):
    # _done ruft den Ergebnis-Hook; im Testkontext immer erlauben.
    targets = []
    if _task_result_service is not None and hasattr(
        _task_result_service, "assert_completion_allowed"
    ):
        targets.append(_task_result_service)
    if hasattr(hub.task, "assert_completion_allowed"):
        targets.append(hub.task)
    for target in targets:
        monkeypatch.setattr(target, "assert_completion_allowed", lambda *a, **k: None)


def _install_lead(monkeypatch, tasks=None, apply_put=True):
    monkeypatch.setenv("BACH_TEST_RHEINGOLD", "1")
    lead = FakeLead(
        tasks or [{"id": 1250, "title": "Alter Titel", "status": "pending"}],
        apply_put,
    )
    monkeypatch.setattr(
        hub.task,
        "get_lead_config",
        lambda *a, **k: {"mode": "worker", "lead_url": LEAD_URL},
    )
    monkeypatch.setattr(hub.task, "get_rheingold_url", lambda *a, **k: LEAD_URL)
    _patch_urlopen(monkeypatch, lead)
    _allow_completion(monkeypatch)
    return lead


def _setup(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, source) "
        "VALUES (1250, 'Alter Titel', 'pending', 'rheingold:123')"
    )
    conn.commit()
    conn.close()
    handler = TaskHandler(tmp_path)
    handler.db_path = db_path
    return handler, db_path


def _local_row(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def test_task_row_is_remote_managed_flags_remote_sources():
    assert task_row_is_remote_managed("rheingold:x", None) is True
    assert task_row_is_remote_managed("promoted:draft:y", None) is True
    assert task_row_is_remote_managed(None, "remote") is True
    assert task_row_is_remote_managed(None, None) is False
    assert task_row_is_remote_managed("local", None) is False


def test_mutate_and_readback_lead_semantics(monkeypatch):
    lead = FakeLead([{"id": 1250, "title": "Alter Titel", "status": "pending"}])
    _patch_urlopen(monkeypatch, lead)

    ok, body = mutate_task_on_rheingold(LEAD_URL, 1250, {"title": "Neuer Titel"})
    assert ok is True
    assert body.get("success") is True
    assert lead.put_calls()
    assert lead.tasks[1250]["title"] == "Neuer Titel"

    remote = readback_task_from_rheingold(LEAD_URL, 1250)
    assert remote is not None
    assert remote["title"] == "Neuer Titel"
    assert readback_task_from_rheingold(LEAD_URL, 9999) is None

    _patch_urlopen(monkeypatch, _Raiser())
    ok, body = mutate_task_on_rheingold(LEAD_URL, 1250, {"title": "Neuer Titel 2"})
    assert ok is False
    assert "boom" in str(body.get("error", ""))
    assert readback_task_from_rheingold(LEAD_URL, 1250) is None


def test_edit_remote_task_mutates_lead_first(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch)

    ok, msg = handler.handle("edit", ["1250", "--title", "Neuer Titel"])
    assert ok is True
    assert lead.put_calls()
    assert lead.tasks[1250]["title"] == "Neuer Titel"
    row = _local_row(db_path, "SELECT title, source FROM tasks WHERE id = 1250")
    assert row[0] == "Neuer Titel"
    assert row[1] == "rheingold:123"


def test_assign_remote_task_mutates_lead_first(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch)

    ok, msg = handler.handle("assign", ["1250", "--to", "GEMINI"])
    assert ok is True
    assert lead.put_calls()
    assert lead.tasks[1250].get("assigned_to") == "GEMINI"
    row = _local_row(db_path, "SELECT assigned_to, delegated_to FROM tasks WHERE id = 1250")
    assert row[0] == "GEMINI"
    assert row[1] == "GEMINI"
    conn = sqlite3.connect(str(db_path))
    try:
        entries = conn.execute(
            "SELECT action, field_changed, changed_by FROM task_history WHERE task_id = 1250"
        ).fetchall()
    finally:
        conn.close()
    fields = {(e[0], e[1], e[2]) for e in entries}
    assert ("field_change", "assigned_to", "cli-task") in fields
    assert ("field_change", "delegated_to", "cli-task") in fields


def test_claim_remote_task_mutates_lead_first(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch)

    ok, msg = handler.handle("claim", ["1250", "--by", "worker-1"])
    assert ok is True
    assert lead.put_calls()
    assert lead.tasks[1250].get("claimed_by") == "worker-1"
    row = _local_row(db_path, "SELECT claimed_by FROM tasks WHERE id = 1250")
    assert row[0] == "worker-1"


def test_done_remote_task_mutates_lead_first(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch)

    ok, msg = handler.handle("done", ["1250"])
    assert ok is True
    assert lead.put_calls()
    assert lead.tasks[1250]["status"] == "done"
    row = _local_row(db_path, "SELECT status FROM tasks WHERE id = 1250")
    assert row[0] == "done"


def test_edit_remote_task_fails_closed_on_readback_collision(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch, apply_put=False)

    ok, msg = handler.handle("edit", ["1250", "--title", "Neuer Titel"])
    assert ok is False
    assert "[COLLISION]" in msg
    assert lead.put_calls()
    row = _local_row(db_path, "SELECT title FROM tasks WHERE id = 1250")
    assert row[0] == "Alter Titel"


def test_edit_remote_task_fails_closed_when_lead_unconfigured(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch)
    monkeypatch.setattr(hub.task, "get_rheingold_url", lambda *a, **k: None)

    ok, msg = handler.handle("edit", ["1250", "--title", "Neuer Titel"])
    assert ok is False
    assert "[BLOCKED]" in msg
    assert lead.calls == []
    row = _local_row(db_path, "SELECT title FROM tasks WHERE id = 1250")
    assert row[0] == "Alter Titel"


def test_edit_local_task_bypasses_lead(tmp_path, monkeypatch):
    handler, db_path = _setup(tmp_path)
    lead = _install_lead(monkeypatch)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO tasks (id, title, status, source) "
        "VALUES (1251, 'Lokal', 'pending', NULL)"
    )
    conn.commit()
    conn.close()

    ok, msg = handler.handle("edit", ["1251", "--title", "Lokal neu"])
    assert ok is True
    assert lead.put_calls() == []
    row = _local_row(db_path, "SELECT title FROM tasks WHERE id = 1251")
    assert row[0] == "Lokal neu"