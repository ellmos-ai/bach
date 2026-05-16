# -*- coding: utf-8 -*-
"""Tests for ChainHandler (hub/chain.py)."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hub.chain import ChainHandler


def _create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS toolchains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            steps_json TEXT NOT NULL DEFAULT '[]',
            trigger_type TEXT DEFAULT 'manual',
            trigger_value TEXT,
            is_active INTEGER DEFAULT 1,
            last_run TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS toolchain_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id INTEGER,
            status TEXT,
            log TEXT,
            duration_seconds REAL,
            started_at TEXT,
            finished_at TEXT,
            steps_completed INTEGER DEFAULT 0,
            steps_total INTEGER DEFAULT 0,
            output TEXT,
            error TEXT,
            triggered_by TEXT DEFAULT 'manual'
        );
    """)
    conn.commit()


@pytest.fixture
def chain_env(tmp_path):
    base = tmp_path / "bach" / "system"
    (base / "data").mkdir(parents=True)
    (base / "hub").mkdir()
    (base / "tools" / "llmauto" / "chains").mkdir(parents=True)
    (base / "tools" / "llmauto" / "state").mkdir(parents=True)

    db_path = base / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_schema(conn)
    conn.close()

    h = ChainHandler(base)
    h.db_path = db_path
    return h, base, db_path


def _add_chain(db_path, name="test-chain", steps=None, trigger="manual", active=1):
    if steps is None:
        steps = [{"tool": "status", "args": []}]
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        INSERT INTO toolchains (name, steps_json, trigger_type, is_active)
        VALUES (?, ?, ?, ?)
    """, (name, json.dumps(steps), trigger, active))
    conn.commit()
    chain_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return chain_id


class TestInit:
    def test_profile_name(self, chain_env):
        h, _, _ = chain_env
        assert h.profile_name == "chain"

    def test_operations(self, chain_env):
        h, _, _ = chain_env
        ops = h.get_operations()
        assert "list" in ops
        assert "run" in ops
        assert "add" in ops
        assert "show" in ops
        assert "delete" in ops
        assert "create" in ops
        assert "start" in ops
        assert "stop" in ops
        assert "status" in ops

    def test_target_file(self, chain_env):
        h, _, db_path = chain_env
        assert h.target_file == db_path


class TestHandle:
    def test_unknown_operation(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("nope", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_run_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("run", [])
        assert ok is False
        assert "ID benoetigt" in msg

    def test_show_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("show", [])
        assert ok is False

    def test_delete_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("delete", [])
        assert ok is False

    def test_log_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("log", [])
        assert ok is False

    def test_start_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("start", [])
        assert ok is False

    def test_stop_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("stop", [])
        assert ok is False

    def test_pause_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("pause", [])
        assert ok is False

    def test_resume_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("resume", [])
        assert ok is False

    def test_steer_insufficient_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("steer", ["name"])
        assert ok is False
        assert "Hinweis benoetigt" in msg

    def test_reset_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("reset", [])
        assert ok is False


class TestList:
    def test_empty_list(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("list", [])
        assert ok is True
        assert "Keine Chains" in msg

    def test_list_with_toolchains(self, chain_env):
        h, _, db_path = chain_env
        _add_chain(db_path, "scan-daily")
        _add_chain(db_path, "backup-weekly")

        ok, msg = h.handle("list", [])
        assert ok is True
        assert "scan-daily" in msg
        assert "backup-weekly" in msg
        assert "TOOLCHAINS" in msg

    def test_list_with_llmauto_chains(self, chain_env):
        h, base, _ = chain_env
        chain_file = base / "tools" / "llmauto" / "chains" / "research.json"
        chain_file.write_text(json.dumps({
            "chain_name": "research",
            "mode": "loop",
            "description": "Research chain",
        }), encoding="utf-8")

        ok, msg = h.handle("list", [])
        assert ok is True
        assert "research" in msg
        assert "LLMAUTO" in msg


class TestAdd:
    def test_add_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("add", [])
        assert ok is False
        assert "Usage" in msg

    def test_add_simple(self, chain_env):
        h, _, db_path = chain_env
        steps = json.dumps([{"tool": "status", "args": []}])
        ok, msg = h.handle("add", ["my-chain", "--steps", steps])
        assert ok is True
        assert "erstellt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT name, steps_json FROM toolchains WHERE name='my-chain'").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "my-chain"

    def test_add_invalid_json(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("add", ["bad-chain", "--steps", "not-json"])
        assert ok is False
        assert "JSON" in msg

    def test_add_with_trigger(self, chain_env):
        h, _, db_path = chain_env
        steps = json.dumps([{"tool": "scan", "args": ["--quick"]}])
        ok, msg = h.handle("add", ["cron-chain", "--steps", steps, "--trigger", "cron"])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT trigger_type FROM toolchains WHERE name='cron-chain'").fetchone()
        conn.close()
        assert row[0] == "cron"


class TestShow:
    def test_show_not_found(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("show", ["999"])
        assert ok is False
        assert "Nicht gefunden" in msg

    def test_show_chain(self, chain_env):
        h, _, db_path = chain_env
        steps = [{"tool": "scan", "args": ["--quick"]}, {"tool": "status", "args": []}]
        cid = _add_chain(db_path, "my-chain", steps)

        ok, msg = h.handle("show", [str(cid)])
        assert ok is True
        assert "my-chain" in msg
        assert "scan" in msg
        assert "status" in msg

    def test_show_parallel_block(self, chain_env):
        h, _, db_path = chain_env
        steps = [{"parallel": True, "tools": [
            {"tool": "scan", "args": []},
            {"tool": "status", "args": []},
        ]}]
        cid = _add_chain(db_path, "parallel-chain", steps)

        ok, msg = h.handle("show", [str(cid)])
        assert ok is True
        assert "PARALLEL" in msg


class TestDelete:
    def test_delete_chain(self, chain_env):
        h, _, db_path = chain_env
        cid = _add_chain(db_path)

        ok, msg = h.handle("delete", [str(cid)])
        assert ok is True
        assert "geloescht" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM toolchains WHERE id=?", (cid,)).fetchone()
        conn.close()
        assert row is None


class TestRun:
    def test_run_not_found(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("run", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_run_invalid_json(self, chain_env):
        h, _, db_path = chain_env
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO toolchains (name, steps_json) VALUES (?, ?)",
                      ("bad", "not-json"))
        conn.commit()
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        ok, msg = h.handle("run", [str(cid)])
        assert ok is False
        assert "JSON" in msg

    def test_run_dry_run(self, chain_env):
        h, _, db_path = chain_env
        steps = [{"tool": "status", "args": []}]
        cid = _add_chain(db_path, "dry-chain", steps)

        ok, msg = h.handle("run", [str(cid)], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert "status" in msg

    def test_run_dry_run_parallel(self, chain_env):
        h, _, db_path = chain_env
        steps = [{"parallel": True, "tools": [
            {"tool": "scan", "args": []},
            {"tool": "status", "args": []},
        ]}]
        cid = _add_chain(db_path, "par-chain", steps)

        ok, msg = h.handle("run", [str(cid)], dry_run=True)
        assert ok is True
        assert "PARALLEL" in msg

    def test_run_executes_and_logs(self, chain_env):
        h, _, db_path = chain_env
        steps = [{"tool": "status", "args": []}]
        cid = _add_chain(db_path, "exec-chain", steps)

        mock_result = {"tool": "status", "success": True, "log": "[OK]", "output": "ok", "error": ""}
        with patch.object(h, "_run_single_tool", return_value=mock_result):
            ok, msg = h.handle("run", [str(cid)])

        assert ok is True
        assert "beendet" in msg
        assert "success" in msg

        conn = sqlite3.connect(str(db_path))
        run = conn.execute("SELECT status, steps_completed, steps_total FROM toolchain_runs WHERE chain_id=?",
                            (cid,)).fetchone()
        conn.close()
        assert run[0] == "success"
        assert run[1] == 1
        assert run[2] == 1

    def test_run_failure_aborts(self, chain_env):
        h, _, db_path = chain_env
        steps = [
            {"tool": "bad-tool", "args": []},
            {"tool": "status", "args": []},
        ]
        cid = _add_chain(db_path, "fail-chain", steps)

        mock_fail = {"tool": "bad-tool", "success": False, "log": "[FAILED]", "output": "", "error": "err"}
        with patch.object(h, "_run_single_tool", return_value=mock_fail):
            ok, msg = h.handle("run", [str(cid)])

        assert ok is True
        assert "failed" in msg


class TestLog:
    def test_log_empty(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("log", ["1"])
        assert ok is False
        assert "Keine Logs" in msg

    def test_log_shows_last_run(self, chain_env):
        h, _, db_path = chain_env
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            INSERT INTO toolchain_runs (chain_id, status, log, duration_seconds, started_at, finished_at)
            VALUES (1, 'success', 'Step 1: OK', 1.5, '2026-01-01T00:00:00', '2026-01-01T00:00:01')
        """)
        conn.commit()
        conn.close()

        ok, msg = h.handle("log", ["1"])
        assert ok is True
        assert "success" in msg
        assert "Step 1: OK" in msg


class TestCreate:
    def test_create_no_args(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", [])
        assert ok is False
        assert "Usage" in msg

    def test_create_name_starts_with_flag(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["--bad-name"])
        assert ok is False
        assert "Name" in msg

    def test_create_simple(self, chain_env):
        h, base, _ = chain_env
        ok, msg = h.handle("create", ["my-llm-chain", "--mode", "once", "--description", "Test chain"])
        assert ok is True
        assert "erstellt" in msg

        chain_file = base / "tools" / "llmauto" / "chains" / "my-llm-chain.json"
        assert chain_file.exists()
        data = json.loads(chain_file.read_text(encoding="utf-8"))
        assert data["chain_name"] == "my-llm-chain"
        assert data["mode"] == "once"

    def test_create_with_links(self, chain_env):
        h, base, _ = chain_env
        ok, msg = h.handle("create", [
            "linked-chain",
            "--add-link", "worker:sonnet:worker_prompt",
            "--add-link", "reviewer:opus:review_prompt",
        ])
        assert ok is True
        assert "2 Link(s)" in msg

        chain_file = base / "tools" / "llmauto" / "chains" / "linked-chain.json"
        data = json.loads(chain_file.read_text(encoding="utf-8"))
        assert len(data["links"]) == 2
        assert data["links"][0]["model"] == "claude-sonnet-4-6"
        assert data["links"][1]["model"] == "claude-opus-4-6"

    def test_create_invalid_mode(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["bad-mode", "--mode", "invalid"])
        assert ok is False
        assert "Ungueltiger Modus" in msg

    def test_create_duplicate(self, chain_env):
        h, base, _ = chain_env
        chain_file = base / "tools" / "llmauto" / "chains" / "existing.json"
        chain_file.write_text("{}", encoding="utf-8")

        ok, msg = h.handle("create", ["existing"])
        assert ok is False
        assert "existiert bereits" in msg

    def test_create_from_template(self, chain_env):
        h, base, _ = chain_env
        tpl_file = base / "tools" / "llmauto" / "chains" / "template.json"
        tpl_file.write_text(json.dumps({
            "chain_name": "template",
            "mode": "loop",
            "links": [{"name": "w1", "role": "worker"}],
        }), encoding="utf-8")

        ok, msg = h.handle("create", ["copy-chain", "--from-template", "template"])
        assert ok is True
        assert "Template" in msg

        copy = base / "tools" / "llmauto" / "chains" / "copy-chain.json"
        data = json.loads(copy.read_text(encoding="utf-8"))
        assert data["chain_name"] == "copy-chain"

    def test_create_from_missing_template(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["fail", "--from-template", "nonexistent"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_create_unknown_model(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["bad-model", "--add-link", "worker:gpt4:prompt"])
        assert ok is False
        assert "Unbekanntes Modell" in msg

    def test_create_invalid_link_format(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["bad-link", "--add-link", "only-two-parts"])
        assert ok is False
        assert "Link-Format" in msg

    def test_create_unknown_arg(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["mychain", "--unknown"])
        assert ok is False
        assert "Unbekanntes Argument" in msg

    def test_create_loop_mode(self, chain_env):
        h, base, _ = chain_env
        ok, msg = h.handle("create", ["loop-chain", "--mode", "loop", "--max-rounds", "10"])
        assert ok is True

        chain_file = base / "tools" / "llmauto" / "chains" / "loop-chain.json"
        data = json.loads(chain_file.read_text(encoding="utf-8"))
        assert data["mode"] == "loop"
        assert data["max_rounds"] == 10
        assert "max_consecutive_blocks" in data

    def test_create_invalid_max_rounds(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("create", ["bad-rounds", "--max-rounds", "abc"])
        assert ok is False
        assert "Zahl" in msg


class TestLlmautoStart:
    def test_start_missing_chain(self, chain_env):
        h, _, _ = chain_env
        ok, msg = h.handle("start", ["nonexistent"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_start_success(self, chain_env):
        h, base, _ = chain_env
        chain_file = base / "tools" / "llmauto" / "chains" / "testchain.json"
        chain_file.write_text("{}", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Started"
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = h.handle("start", ["testchain"])
        assert ok is True

    def test_start_failure(self, chain_env):
        h, base, _ = chain_env
        chain_file = base / "tools" / "llmauto" / "chains" / "failchain.json"
        chain_file.write_text("{}", encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "Error"

        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = h.handle("start", ["failchain"])
        assert ok is False


class TestLlmautoOps:
    def test_stop(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Stopped"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("stop", ["mychain"])
        assert ok is True

    def test_pause(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Paused"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("pause", ["mychain", "Mittagspause"])
        assert ok is True

    def test_resume(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Resumed"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("resume", ["mychain"])
        assert ok is True

    def test_steer(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Steered"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("steer", ["mychain", "Focus on testing"])
        assert ok is True

    def test_status(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Running"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("status", ["mychain"])
        assert ok is True

    def test_status_no_name(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "All chains status"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("status", [])
        assert ok is True

    def test_reset(self, chain_env):
        h, _, _ = chain_env
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Reset"

        with patch.object(h, "_run_llmauto", return_value=mock_proc):
            ok, msg = h.handle("reset", ["mychain"])
        assert ok is True


class TestExecuteSteps:
    def test_sequential_success(self, chain_env):
        h, _, _ = chain_env
        steps = [
            {"tool": "status", "args": []},
            {"tool": "scan", "args": ["--quick"]},
        ]
        mock_ok = {"tool": "t", "success": True, "log": "ok", "output": "out", "error": ""}

        with patch.object(h, "_run_single_tool", return_value=mock_ok):
            completed, failed, out, err = h._execute_steps(steps, [])

        assert completed == 2
        assert failed is False

    def test_failure_aborts_by_default(self, chain_env):
        h, _, _ = chain_env
        steps = [
            {"tool": "bad", "args": []},
            {"tool": "good", "args": []},
        ]
        mock_fail = {"tool": "bad", "success": False, "log": "fail", "output": "", "error": "err"}

        with patch.object(h, "_run_single_tool", return_value=mock_fail):
            completed, failed, out, err = h._execute_steps(steps, [])

        assert completed == 0
        assert failed is True

    def test_failure_continue_action(self, chain_env):
        h, _, _ = chain_env
        steps = [
            {"tool": "bad", "args": [], "on_failure": {"action": "continue", "message": "Ignoriert"}},
            {"tool": "good", "args": []},
        ]
        results = [
            {"tool": "bad", "success": False, "log": "fail", "output": "", "error": "err"},
            {"tool": "good", "success": True, "log": "ok", "output": "out", "error": ""},
        ]

        with patch.object(h, "_run_single_tool", side_effect=results):
            completed, failed, out, err = h._execute_steps(steps, [])

        assert completed == 1

    def test_parallel_block(self, chain_env):
        h, _, _ = chain_env
        steps = [{"parallel": True, "tools": [
            {"tool": "a", "args": []},
            {"tool": "b", "args": []},
        ]}]
        mock_ok = {"tool": "t", "success": True, "log": "ok", "output": "out", "error": ""}

        with patch.object(h, "_run_single_tool", return_value=mock_ok):
            completed, failed, out, err = h._execute_steps(steps, [])

        assert completed == 1
        assert failed is False
