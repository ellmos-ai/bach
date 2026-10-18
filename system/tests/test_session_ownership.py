"""Session writers must never select a different partner's newest session."""
import json
import sqlite3
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hub.memory import MemoryHandler
from .test_shutdown_handler import shutdown_env  # noqa: F401


@pytest.fixture
def sessions(shutdown_env):  # noqa: F811
    shutdown, base, path = shutdown_env
    memory = MemoryHandler(base)
    memory.db_path = path
    with sqlite3.connect(path) as conn:
        for sid, owner in (("own", "codex"), ("foreign", "claude")):
            conn.execute(
                "INSERT INTO memory_sessions (session_id, partner_id, started_at, summary) "
                "VALUES (?, ?, '2026-10-16T08:00:00', ?)", (sid, owner, owner))
            conn.execute("INSERT INTO partner_presence (partner_name, status) VALUES (?, 'online')", (owner,))
    return shutdown, memory, path


def rows(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT * FROM memory_sessions ORDER BY id").fetchall()


def test_memory_explicit_session_preserves_foreign_session(sessions):
    _, memory, path = sessions
    before = rows(path)
    ok, msg = memory.handle("session", ["--session=own", "--partner=codex", "report"])
    assert ok, msg
    assert rows(path)[1] == before[1]
    assert rows(path)[0][4] is None  # report does not close the session
    assert rows(path)[0][5] == "report"


@pytest.mark.parametrize("operation", ["memory", "complete", "quick", "emergency"])
@pytest.mark.parametrize("args", [[], ["--session=foreign", "--partner=codex"], ["--session=missing", "--partner=codex"], ["--session=own"]])
def test_ambiguous_or_foreign_selection_does_not_write(sessions, operation, args):
    shutdown, memory, path = sessions
    before = rows(path)
    handler = memory if operation == "memory" else shutdown
    ok, _ = handler.handle("session" if operation == "memory" else operation, [*args, "report"])
    assert not ok
    assert rows(path) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM memory_working").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM partner_presence WHERE status='online'").fetchone()[0] == 2


def test_complete_pins_all_session_writes_and_preserves_other_rows(sessions):
    shutdown, _, path = sessions
    before = rows(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO tasks (title,status,created_at,completed_at) VALUES ('one','done','2026-10-16T09:00:00','2026-10-16T09:30:00')")
    ok, msg = shutdown.handle("complete", ["--partner", "CODEX", "--session", "own", "report"])
    assert ok, msg
    after = rows(path)
    assert after[1] == before[1]
    assert after[0][4] is not None
    assert after[0][6:8] == (1, 1)
    assert json.loads(after[0][-1])["session_summary"] == "report"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM partner_presence WHERE partner_name='claude'").fetchone()[0] == "online"


def test_quick_keeps_session_open(sessions):
    shutdown, _, path = sessions
    before = rows(path)
    ok, msg = shutdown.handle("quick", ["--session=own", "--partner=codex", "pause"])
    assert ok, msg
    assert rows(path) == before


def test_explicit_dry_run_validates_without_writing(sessions):
    shutdown, memory, path = sessions
    before = rows(path)
    for handler, op in ((shutdown, "complete"), (memory, "session")):
        ok, msg = handler.handle(op, ["--session=own", "--partner=codex", "report"], dry_run=True)
        assert ok, msg
    assert rows(path) == before


def test_typed_api_preserves_summary_and_forwards_scope():
    import bach_api
    fake = type("App", (), {"execute": lambda self, *args: (True, args)})()
    with patch.object(bach_api, "get_app", return_value=fake):
        result = bach_api.memory.session("literal --partner=claude", session_id="own", partner="codex")
        assert result == ("memory", "session", ["--session=own", "--partner=codex", "--", "literal --partner=claude"])
        result = bach_api.session.shutdown("literal --partner=claude", session_id="own", partner="codex")
        assert result == ("shutdown", "complete", ["--partner=codex", "--session=own", "--", "literal --partner=claude"])


def test_closed_session_does_not_switch_to_same_partner_successor(sessions):
    shutdown, _, path = sessions

    def replace_session(*_):
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE memory_sessions SET ended_at='closed' WHERE session_id='own'")
            conn.execute("INSERT INTO memory_sessions (session_id,partner_id,started_at,summary) VALUES ('successor','codex','2026-10-16T10:00:00','next')")

    with patch("core.hooks.hooks.emit", side_effect=replace_session):
        ok, _ = shutdown.handle("complete", ["--partner=codex", "old report"])
    assert not ok
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT ended_at,summary FROM memory_sessions WHERE session_id='successor'").fetchone() == (None, "next")


def test_write_failure_rolls_back_entire_session_and_preserves_presence(sessions):
    shutdown, _, path = sessions
    before = rows(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER deny_update BEFORE UPDATE ON memory_sessions BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    ok, message = shutdown.handle("complete", ["--partner=codex", "--session=own", "report"])
    assert not ok
    assert "injected failure" in message
    assert rows(path) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM partner_presence WHERE partner_name='codex'").fetchone()[0] == "online"


def test_clockout_failure_reports_committed_session_without_retry_error(sessions):
    shutdown, _, path = sessions
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER deny_presence BEFORE UPDATE ON partner_presence BEGIN SELECT RAISE(ABORT,'presence unavailable'); END")
    ok, message = shutdown.handle("complete", ["--partner=codex", "--session=own", "report"])
    assert ok
    assert "[WARN]" in message and "clock-out failed" in message
    assert rows(path)[0][4] is not None


def test_real_cli_saves_only_addressed_session(sessions):
    _, _, path = sessions
    before = rows(path)
    env = dict(os.environ, BACH_DB=str(path), PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "bach.py"), "mem", "session",
         "--session=own", "--partner=codex", "--", "literal --partner=claude"],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert rows(path)[1] == before[1]
    assert rows(path)[0][5] == "literal --partner=claude"


def test_mcp_forwards_explicit_scope(monkeypatch):
    from tools import mcp_server
    calls = []
    monkeypatch.setattr(mcp_server, "_execute", lambda *args: calls.append(args))
    mcp_server.session_shutdown("report", session_id="own", partner="codex")
    assert calls == [("shutdown", "complete", ["--session=own", "--partner=codex", "--", "report"])]


def test_auto_snapshot_uses_selected_session_instead_of_global_pointer(sessions, monkeypatch):
    from hub import session_checkpoint_provider

    shutdown, _, path = sessions
    captured = []

    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(id=1, session_id=kwargs["session_id"],
                               name=kwargs["name"], payload=kwargs["payload"],
                               created_at=kwargs["payload"]["created_at"])

    store = SimpleNamespace(create=create)
    monkeypatch.delenv(session_checkpoint_provider.ROLLBACK_ENV_VAR, raising=False)
    monkeypatch.setattr(session_checkpoint_provider, "get_checkpoint_store", lambda _: store)
    foreign_before = rows(path)[1]
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO system_config (key,value) VALUES ('current_session','foreign')")
        conn.execute("CREATE TABLE session_snapshots (id INTEGER PRIMARY KEY,session_id TEXT,snapshot_type TEXT,name TEXT,snapshot_data TEXT,working_memory TEXT,open_tasks TEXT,active_files TEXT,token_usage INTEGER,context_hash TEXT,notes TEXT,created_at TEXT)")
    with patch("tools.dirscan.DirectoryScanner") as scanner:
        scanner.return_value.last_change_count = 3
        scanner.return_value.shutdown_update.return_value = "3 changes"
        ok, message = shutdown.handle("complete", ["--session=own", "--partner=codex", "report"])
    assert ok, message
    with sqlite3.connect(path) as conn:
        sid, payload = conn.execute("SELECT session_id,snapshot_data FROM session_snapshots").fetchone()
        assert sid == "own" and json.loads(payload)["session_id"] == "own"
    assert rows(path)[1] == foreign_before
    assert len(captured) == 1
    assert captured[0]["session_id"] == "own"
    assert captured[0]["payload"]["session_id"] == "own"


@pytest.mark.parametrize("args", [["--partner=codex", "--partner=claude"], ["--session"], ["--partner="]])
def test_invalid_scope_does_not_write(sessions, args):
    shutdown, memory, path = sessions
    before = rows(path)
    for handler, op in ((shutdown, "complete"), (memory, "session")):
        ok, _ = handler.handle(op, [*args, "report"])
        assert not ok
    assert rows(path) == before
