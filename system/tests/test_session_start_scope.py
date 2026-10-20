"""Partner-scoped starts and reads must preserve other partners' sessions."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

import pytest

from hub.session import SessionHandler
from hub.startup import StartupHandler
from .test_session_handler import empty_env  # noqa: F401


@pytest.fixture
def scope_env(empty_env):  # noqa: F811
    base, path = empty_env
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
            CREATE TABLE system_activity (id INTEGER PRIMARY KEY, session_id TEXT, last_activity TEXT, updated_at TEXT);
            INSERT INTO system_activity (id) VALUES (1);
            CREATE TABLE partner_presence (id INTEGER PRIMARY KEY, partner_name TEXT,
                status TEXT, clocked_in TEXT, clocked_out TEXT, last_heartbeat TEXT,
                session_id TEXT, created_at TEXT, updated_at TEXT);
        """)
        conn.executemany(
            "INSERT INTO memory_sessions (session_id, partner_id, started_at) VALUES (?, ?, ?)",
            [("own", "codex", "2026-10-20T08:00:00"),
             ("foreign", "claude", "2026-10-20T09:00:00")],
        )
    handler = SessionHandler(base)
    handler._get_thought_prompts = lambda: []
    handler._get_task_summary = lambda: dict(open=0, blocked=0, done_today=0, high_priority=None)
    return handler, path


def snapshot(path):
    with sqlite3.connect(path) as conn:
        return {name: conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
                for name in ("memory_sessions", "partner_presence", "system_activity")}


def test_start_reuses_only_requested_partner(scope_env):
    handler, path = scope_env
    before = snapshot(path)
    ok, report = handler.handle("start", ["--partner=codex", "--json"])
    assert ok, report
    assert json.loads(report)["session_id"] == "own"
    assert snapshot(path) == before


def test_default_start_never_reuses_foreign_partner(scope_env):
    handler, _ = scope_env
    with patch.object(StartupHandler, "handle", return_value=(True, "started")) as start:
        assert handler.handle("start", []) == (True, "started")
    assert start.call_args.args[0] == "ensure"


def test_status_scopes_to_partner_without_writes(scope_env):
    handler, path = scope_env
    before = snapshot(path)
    ok, report = handler.handle("status", ["--partner", "CODEX", "--json"])
    assert ok, report
    assert json.loads(report)["session"]["session_id"] == "own"
    assert "foreign" not in report
    assert snapshot(path) == before


@pytest.mark.parametrize("operation", ["status", "check"])
@pytest.mark.parametrize("args", [[], ["--session=foreign", "--partner=codex"],
                                 ["--session=missing", "--partner=codex"],
                                 ["--session=own"], ["--partner="],
                                 ["--partner=codex", "--partner=claude"]])
def test_ambiguous_or_invalid_reads_fail_before_config_write(scope_env, operation, args):
    handler, path = scope_env
    before = snapshot(path)
    config_before = handler._load_user_config()
    ok, _ = handler.handle(operation, [*args, "--set-duration=90"])
    assert not ok
    assert snapshot(path) == before
    assert handler._load_user_config() == config_before


def test_scoped_history_does_not_leak_foreign_last_session(scope_env):
    handler, path = scope_env
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE memory_sessions SET ended_at='2026-10-20T10:00:00'")
    ok, report = handler.handle("status", ["--partner=codex"])
    assert ok, report
    assert "own" in report and "foreign" not in report


def test_registration_is_atomic_and_uses_one_identity(scope_env):
    handler, path = scope_env
    startup = StartupHandler(handler.base_path)
    before = snapshot(path)
    current, created = startup._register_session("CODEX", datetime.now())
    assert created
    after = snapshot(path)
    assert after["memory_sessions"][1] == before["memory_sessions"][1]
    assert after["memory_sessions"][0][4] is not None
    assert after["partner_presence"][-1][6] == current["session_id"]
    assert after["system_activity"][0][1] == current["session_id"]


def test_failed_presence_rolls_back_previous_close_and_new_session(scope_env):
    handler, path = scope_env
    startup = StartupHandler(handler.base_path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER deny_presence BEFORE INSERT ON partner_presence BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = snapshot(path)
    with pytest.raises(sqlite3.DatabaseError, match="injected"):
        startup._register_session("codex", datetime.now())
    assert snapshot(path) == before


def test_parallel_ensure_returns_same_identity(scope_env):
    handler, path = scope_env
    now = datetime.now()
    def ensure(_):
        startup = StartupHandler(handler.base_path)
        return startup._register_session("new-partner", now, reuse_existing=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ensure, range(2)))
    assert len({result[0]["session_id"] for result in results}) == 1
    assert sum(result[1] for result in results) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM partner_presence WHERE partner_name='new-partner'").fetchone()[0] == 1


def test_same_second_different_partners_get_distinct_ids(scope_env):
    handler, _ = scope_env
    startup = StartupHandler(handler.base_path)
    now = datetime.now()
    one, _ = startup._register_session("one", now)
    two, _ = startup._register_session("two", now)
    assert one["session_id"] != two["session_id"]


def test_typed_api_exposes_exact_start_identity_and_read_scope():
    import bach_api
    calls = []
    class App:
        def execute(self, *args):
            calls.append(args)
            return True, json.dumps({"session_id": "own", "session": {"session_id": "own"}})
    with patch.object(bach_api, "get_app", return_value=App()):
        assert bach_api.session.startup(partner="codex", structured=True)["session_id"] == "own"
        assert bach_api.session.current("codex", session_id="own")["session_id"] == "own"
    assert "--json" in calls[0][2]
    assert calls[1] == ("session", "status", ["--partner=codex", "--session=own", "--json"])


def test_typed_startup_failure_is_not_success():
    import bach_api
    fake = type("App", (), {"execute": lambda *args: (False, "registration failed")})()
    with patch.object(bach_api, "get_app", return_value=fake):
        with pytest.raises(bach_api.BachAPIError, match="registration failed"):
            bach_api.session.startup(partner="codex")


def test_mcp_startup_forwards_partner_and_structured_mode(monkeypatch):
    from tools import mcp_server
    calls = []
    monkeypatch.setattr(mcp_server, "_execute", lambda *args: calls.append(args))
    mcp_server.session_startup(partner="codex", mode="silent", structured=True, quick=True)
    assert calls == [("startup", "quick", ["--partner=codex", "--mode=silent", "--json"])]


def test_real_cli_status_is_scoped_json(scope_env):
    import os
    import subprocess
    import sys
    from pathlib import Path
    _, path = scope_env
    before = snapshot(path)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "bach.py"), "session", "status",
         "--partner=codex", "--session=own", "--json"],
        env=dict(os.environ, BACH_DB=str(path), PYTHONIOENCODING="utf-8"),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "nicht gebuchte" in result.stderr
    assert json.loads(result.stdout)["session"]["session_id"] == "own"
    assert snapshot(path) == before


def test_startup_reports_committed_identity_even_after_successor(scope_env, monkeypatch):
    handler, path = scope_env
    startup = StartupHandler(handler.base_path)
    def hook(event, data):
        if event == "after_startup":
            startup._register_session("codex", datetime.now())
    monkeypatch.setattr("core.hooks.hooks.emit", hook)
    ok, raw = startup.handle("quick", ["--partner=codex", "--mode=silent", "--json"])
    assert ok, raw
    result = json.loads(raw)
    with sqlite3.connect(path) as conn:
        started = conn.execute("SELECT ended_at FROM memory_sessions WHERE session_id=?", (result["session_id"],)).fetchone()
        newest = conn.execute("SELECT session_id FROM memory_sessions ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert started is not None and started[0] is not None
    assert result["session_id"] != newest


def test_startup_dry_run_has_no_identity_or_mutations(scope_env):
    handler, path = scope_env
    before = snapshot(path)
    ok, raw = StartupHandler(handler.base_path).handle("quick", ["--partner=codex", "--mode=silent", "--json"], dry_run=True)
    assert ok, raw
    result = json.loads(raw)
    assert result["session_id"] is None and result["created"] is False
    assert snapshot(path) == before


def test_registration_creates_missing_activity_singleton(scope_env):
    handler, path = scope_env
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM system_activity")
    current, _ = StartupHandler(handler.base_path)._register_session("codex", datetime.now())
    assert snapshot(path)["system_activity"][0][1] == current["session_id"]


def test_startup_registration_failure_returns_no_success_identity(scope_env):
    handler, path = scope_env
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER deny_start BEFORE INSERT ON memory_sessions BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = snapshot(path)
    ok, raw = StartupHandler(handler.base_path).handle("quick", ["--partner=codex", "--json"])
    assert not ok
    assert json.loads(raw)["session_id"] is None
    assert snapshot(path) == before
