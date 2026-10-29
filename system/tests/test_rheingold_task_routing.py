"""Regressionstests für das Handler-first Writer-Routing zum Rheingold-Lead.

Deckt TaskHandler._propagate_to_rheingold_lead und dessen Hooks in
TaskHandler._edit, _done, _claim und _assign ab: Im Worker-Modus werden
Remote-Managed-Tasks ausschließlich über den Lead mutiert (Fail-Closed),
lokale Tasks weiterhin direkt in der Datenbank.
"""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def native_task_environment(tmp_path, monkeypatch):
    import sqlite3
    from core.hooks import hooks
    from hub.task import TaskHandler
    import bach_api
    db = tmp_path / "isolated-task.db"
    schema = Path(__file__).parents[1] / "data/schema/schema.sql"
    with sqlite3.connect(db) as conn:
        conn.executescript(schema.read_text(encoding="utf-8"))
    monkeypatch.setenv("BACH_RHEINGOLD_DISABLED", "1")
    monkeypatch.setattr(bach_api, "_resolve_db_path", lambda: db)
    monkeypatch.setattr(hooks, "emit", lambda *_args, **_kwargs: None)
    handler = TaskHandler(tmp_path)
    handler.db_path = db
    proxy = bach_api._TaskProxy("task")
    monkeypatch.setattr(
        proxy, "raw", lambda operation, *args: handler.handle(operation, list(args))
    )
    return SimpleNamespace(proxy=proxy, handler=handler, db=db)


def _add_task(env, title="Testaufgabe"):
    ok, _msg = env.proxy.raw("add", title)
    assert ok
    with sqlite3.connect(env.db) as conn:
        task_id = conn.execute("SELECT MAX(id) FROM tasks").fetchone()[0]
    return task_id


def _make_remote(env, task_id):
    with sqlite3.connect(env.db) as conn:
        conn.execute(
            "UPDATE tasks SET source='rheingold:test' WHERE id=?", (task_id,)
        )


def _fetch_task(env, task_id):
    with sqlite3.connect(env.db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,)
        ).fetchone()


def _history(env, task_id):
    with sqlite3.connect(env.db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM task_history WHERE task_id=?", (task_id,)
        ).fetchall()


def _apply_worker_mode(monkeypatch, url):
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda **_: url)


def test_remote_managed_classification():
    from hub.rheingold import task_row_is_remote_managed

    assert task_row_is_remote_managed("rheingold:abc", None)
    assert task_row_is_remote_managed("promoted:draft:xyz", None)
    assert task_row_is_remote_managed(None, "remote")
    assert not task_row_is_remote_managed(None, None)
    assert not task_row_is_remote_managed("local", "cli")


def test_edit_local_task_bypasses_lead(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")
    mutate_calls = []

    def fake_mutate(base, remote_id, payload, *args, **kwargs):
        mutate_calls.append((remote_id, payload))
        return True, {"success": True}

    monkeypatch.setattr("hub.task.mutate_task_on_rheingold", fake_mutate)

    ok, msg = env.proxy.raw("edit", str(task_id), "--title", "Neuer Titel")

    assert ok
    assert mutate_calls == []  # lokaler Task -> kein Lead-Kontakt
    row = _fetch_task(env, task_id)
    assert row["title"] == "Neuer Titel"


def test_edit_remote_task_offline_is_fail_closed(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, None)

    ok, msg = env.proxy.raw("edit", str(task_id), "--title", "Neuer Titel")

    assert not ok
    assert "[BLOCKED] Lead unerreichbar" in msg
    row = _fetch_task(env, task_id)
    assert row["title"] == "Testaufgabe"


def test_edit_remote_task_mutation_error(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")

    def fake_mutate(base, remote_id, payload, *args, **kwargs):
        return False, {"error": "boom"}

    monkeypatch.setattr("hub.task.mutate_task_on_rheingold", fake_mutate)

    ok, msg = env.proxy.raw("edit", str(task_id), "--title", "Neuer Titel")

    assert not ok
    assert "[ERROR]" in msg
    assert "Lead-Mutation fehlgeschlagen" in msg
    row = _fetch_task(env, task_id)
    assert row["title"] == "Testaufgabe"


def test_edit_remote_task_readback_missing(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")

    monkeypatch.setattr(
        "hub.task.mutate_task_on_rheingold",
        lambda base, remote_id, payload, *a, **k: (True, {"success": True}),
    )
    monkeypatch.setattr(
        "hub.task.readback_task_from_rheingold",
        lambda base, remote_id, *a, **k: None,
    )

    ok, msg = env.proxy.raw("edit", str(task_id), "--title", "Neuer Titel")

    assert not ok
    assert f"Task {task_id}: Lead-Readback fehlgeschlagen" in msg
    row = _fetch_task(env, task_id)
    assert row["title"] == "Testaufgabe"


def test_edit_remote_task_readback_diverges(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")

    monkeypatch.setattr(
        "hub.task.mutate_task_on_rheingold",
        lambda base, remote_id, payload, *a, **k: (True, {"success": True}),
    )

    def fake_readback(base, remote_id, *args, **kwargs):
        return {"id": remote_id, "title": "Anderer Titel"}

    monkeypatch.setattr("hub.task.readback_task_from_rheingold", fake_readback)

    ok, msg = env.proxy.raw("edit", str(task_id), "--title", "Neuer Titel")

    assert not ok
    assert f"Task {task_id}: Lead-Readback weicht ab" in msg
    assert "title" in msg
    row = _fetch_task(env, task_id)
    assert row["title"] == "Testaufgabe"


def test_edit_remote_task_success_writes_local_mirror(
    monkeypatch, native_task_environment
):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")

    monkeypatch.setattr(
        "hub.task.mutate_task_on_rheingold",
        lambda base, remote_id, payload, *a, **k: (True, {"success": True}),
    )

    def fake_readback(base, remote_id, *args, **kwargs):
        return {"id": remote_id, "title": "Neuer Titel"}

    monkeypatch.setattr("hub.task.readback_task_from_rheingold", fake_readback)

    ok, msg = env.proxy.raw("edit", str(task_id), "--title", "Neuer Titel")

    assert ok
    assert msg.startswith(f"[OK] Task {task_id} bearbeitet")
    row = _fetch_task(env, task_id)
    assert row["title"] == "Neuer Titel"
    history = _history(env, task_id)
    assert any(
        entry["field_changed"] == "title" and entry["changed_by"] == "cli-task"
        for entry in history
    )


def test_done_remote_task_offline_keeps_status(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, None)

    ok, msg = env.proxy.raw("done", str(task_id))

    assert ok  # _done liefert immer True, Fehler steht in der Meldung
    assert "[BLOCKED]" in msg
    row = _fetch_task(env, task_id)
    assert row["status"] == "pending"


def test_done_remote_task_success_marks_done(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")

    monkeypatch.setattr(
        "hub.task.mutate_task_on_rheingold",
        lambda base, remote_id, payload, *a, **k: (True, {"success": True}),
    )

    def fake_readback(base, remote_id, *args, **kwargs):
        return {"id": remote_id, "status": "done"}

    monkeypatch.setattr("hub.task.readback_task_from_rheingold", fake_readback)

    ok, msg = env.proxy.raw("done", str(task_id))

    assert ok
    assert f"[OK] Task {task_id} erledigt!" in msg
    row = _fetch_task(env, task_id)
    assert row["status"] == "done"
    history = _history(env, task_id)
    assert any(
        entry["field_changed"] == "status" and entry["changed_by"] == "cli-task"
        for entry in history
    )


def test_claim_remote_task_offline_is_fail_closed(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, None)

    ok, msg = env.proxy.raw("claim", str(task_id), "--by", "worker-a")

    assert not ok
    assert "[BLOCKED]" in msg
    row = _fetch_task(env, task_id)
    assert row["status"] == "pending"
    if "claimed_by" in row.keys():
        assert row["claimed_by"] is None


def test_assign_remote_task_offline_is_fail_closed(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, None)

    ok, msg = env.proxy.raw("assign", str(task_id), "--to", "CLAUDE")

    assert ok  # _assign liefert immer True, Fehler steht in der Meldung
    assert "[BLOCKED]" in msg
    row = _fetch_task(env, task_id)
    assert row["assigned_to"] is None
    assert row["delegated_to"] is None
    history = _history(env, task_id)
    assert not any(entry["field_changed"] == "delegated_to" for entry in history)


def test_assign_remote_task_success_delegates(monkeypatch, native_task_environment):
    env = native_task_environment
    task_id = _add_task(env)
    _make_remote(env, task_id)
    _apply_worker_mode(monkeypatch, "https://isolated.invalid")

    monkeypatch.setattr(
        "hub.task.mutate_task_on_rheingold",
        lambda base, remote_id, payload, *a, **k: (True, {"success": True}),
    )

    def fake_readback(base, remote_id, *args, **kwargs):
        return {"id": remote_id, "assigned_to": "CLAUDE"}

    monkeypatch.setattr("hub.task.readback_task_from_rheingold", fake_readback)

    ok, msg = env.proxy.raw("assign", str(task_id), "--to", "CLAUDE")

    assert ok
    assert "[BLOCKED]" not in msg
    row = _fetch_task(env, task_id)
    assert row["assigned_to"] == "CLAUDE"
    assert row["delegated_to"] == "CLAUDE"
    history = _history(env, task_id)
    assert any(
        entry["field_changed"] == "delegated_to" and entry["changed_by"] == "cli-task"
        for entry in history
    )