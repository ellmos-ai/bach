#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer TuevHandler und UsecaseHandler"""

import sys
import json
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.tuev import TuevHandler, UsecaseHandler

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_tuev (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_path TEXT UNIQUE,
    workflow_name TEXT,
    last_tuev_date TEXT,
    tuev_valid_until TEXT,
    tuev_status TEXT DEFAULT 'pending',
    test_count INTEGER DEFAULT 0,
    pass_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    avg_score REAL DEFAULT 0.0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS usecases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    workflow_path TEXT,
    workflow_name TEXT,
    test_input TEXT,
    expected_output TEXT,
    last_tested TEXT,
    test_result TEXT,
    test_score INTEGER DEFAULT 0,
    tuev_valid_until TEXT,
    created_by TEXT DEFAULT 'user',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);
"""


@pytest.fixture
def tmp_tuev(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()

    wf_dir = system_dir / "skills" / "_workflows"
    wf_dir.mkdir(parents=True)

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

    return system_dir, db_path, wf_dir


@pytest.fixture
def tuev(tmp_tuev):
    system_dir, db_path, _ = tmp_tuev
    h = TuevHandler(system_dir)
    h.db_path = db_path
    return h


@pytest.fixture
def usecase(tmp_tuev):
    system_dir, db_path, _ = tmp_tuev
    h = UsecaseHandler(system_dir)
    h.db_path = db_path
    return h


@pytest.fixture
def seeded_tuev(tuev, tmp_tuev):
    _, db_path, _ = tmp_tuev
    now = datetime.now()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status, tuev_valid_until, avg_score) "
        "VALUES (?, ?, ?, ?, ?)",
        ("skills/_workflows/expired.md", "expired-wf", "passed",
         (now - timedelta(days=5)).isoformat(), 80.0),
    )
    conn.execute(
        "INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status, tuev_valid_until, avg_score) "
        "VALUES (?, ?, ?, ?, ?)",
        ("skills/_workflows/soon.md", "soon-wf", "passed",
         (now + timedelta(days=7)).isoformat(), 90.0),
    )
    conn.execute(
        "INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status, tuev_valid_until, avg_score) "
        "VALUES (?, ?, ?, ?, ?)",
        ("skills/_workflows/ok.md", "ok-wf", "passed",
         (now + timedelta(days=60)).isoformat(), 95.0),
    )
    conn.execute(
        "INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status) "
        "VALUES (?, ?, ?)",
        ("skills/_workflows/no-date.md", "no-date-wf", "pending"),
    )
    conn.commit()
    conn.close()
    return tuev


@pytest.fixture
def seeded_usecase(usecase, tmp_tuev):
    _, db_path, _ = tmp_tuev
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_status) "
        "VALUES (?, ?, ?)",
        ("skills/_workflows/test-wf.md", "test-wf", "pending"),
    )
    conn.execute(
        "INSERT INTO usecases (title, description, workflow_name, workflow_path, test_input, expected_output, test_result, test_score, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Login-Test", "Prueft Login-Flow", "test-wf", "skills/_workflows/test-wf.md",
         '{"user": "admin"}', '{"status": "ok"}', "pass", 90, "user"),
    )
    conn.execute(
        "INSERT INTO usecases (title, workflow_name, test_input, expected_output, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Fehltest", "test-wf", '{}', '{}', "user"),
    )
    conn.execute(
        "INSERT INTO usecases (title, workflow_name, test_result, test_score, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Anderer WF Test", "other-wf", "fail", 30, "user"),
    )
    conn.commit()
    conn.close()
    return usecase


# ================================================================
# TUEV: PROPERTIES
# ================================================================

class TestTuevProperties:
    def test_profile_name(self, tuev):
        assert tuev.profile_name == "tuev"

    def test_target_file(self, tuev):
        assert tuev.target_file == tuev.db_path

    def test_operations(self, tuev):
        ops = tuev.get_operations()
        assert "status" in ops
        assert "check" in ops
        assert "run" in ops
        assert "renew" in ops
        assert "init" in ops


# ================================================================
# TUEV: HANDLE ROUTING
# ================================================================

class TestTuevRouting:
    def test_unknown_op(self, tuev):
        ok, msg = tuev.handle("xyzfoo", [])
        assert ok is False
        assert "Unbekannte" in msg

    def test_empty_op_defaults_to_status(self, tuev):
        ok, msg = tuev.handle("", [])
        assert ok is True

    def test_check_no_args(self, tuev):
        ok, msg = tuev.handle("check", [])
        assert ok is False
        assert "Usage" in msg

    def test_renew_no_args(self, tuev):
        ok, msg = tuev.handle("renew", [])
        assert ok is False
        assert "Usage" in msg


# ================================================================
# TUEV: STATUS
# ================================================================

class TestTuevStatus:
    def test_empty(self, tuev):
        ok, msg = tuev.handle("status", [])
        assert ok is True
        assert "Keine Workflows" in msg

    def test_with_data(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("status", [])
        assert ok is True
        assert "ABGELAUFEN" in msg
        assert "expired-wf" in msg
        assert "BALD FAELLIG" in msg
        assert "soon-wf" in msg
        assert "OK" in msg
        assert "ok-wf" in msg

    def test_no_date_counts_as_expired(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("status", [])
        assert ok is True
        assert "no-date-wf" in msg
        assert "ABGELAUFEN" in msg

    def test_summary_line(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("status", [])
        assert "Gesamt: 4 Workflows" in msg


# ================================================================
# TUEV: CHECK
# ================================================================

class TestTuevCheck:
    def test_not_found(self, tuev):
        ok, msg = tuev.handle("check", ["nonexistent"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_found(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("check", ["expired-wf"])
        assert ok is True
        assert "expired-wf" in msg
        assert "Score:" in msg
        assert "Status:" in msg

    def test_found_no_usecases(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("check", ["expired-wf"])
        assert ok is True
        assert "Keine Usecases" in msg

    def test_found_with_usecases(self, seeded_usecase, tmp_tuev):
        _, db_path, _ = tmp_tuev
        h = TuevHandler(seeded_usecase.base_path)
        h.db_path = db_path
        ok, msg = h.handle("check", ["test-wf"])
        assert ok is True
        assert "Login-Test" in msg
        assert "Usecases:" in msg

    def test_check_by_path_substring(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("check", ["expired"])
        assert ok is True
        assert "expired-wf" in msg


# ================================================================
# TUEV: RUN ALL
# ================================================================

class TestTuevRunAll:
    def test_none_due(self, tuev, tmp_tuev):
        _, db_path, _ = tmp_tuev
        conn = sqlite3.connect(str(db_path))
        future = (datetime.now() + timedelta(days=60)).isoformat()
        conn.execute(
            "INSERT INTO workflow_tuev (workflow_path, workflow_name, tuev_valid_until) VALUES (?, ?, ?)",
            ("wf.md", "future-wf", future),
        )
        conn.commit()
        conn.close()
        ok, msg = tuev.handle("run", [])
        assert ok is True
        assert "Keine faelligen" in msg

    def test_due(self, seeded_tuev):
        ok, msg = seeded_tuev.handle("run", [])
        assert ok is True
        assert "expired-wf" in msg
        assert "no-date-wf" in msg
        assert "Faellige" in msg


# ================================================================
# TUEV: RENEW
# ================================================================

class TestTuevRenew:
    def test_not_found(self, tuev):
        ok, msg = tuev.handle("renew", ["nonexistent"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_success(self, seeded_tuev, tmp_tuev):
        _, db_path, _ = tmp_tuev
        ok, msg = seeded_tuev.handle("renew", ["expired-wf"])
        assert ok is True
        assert "erneuert" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM workflow_tuev WHERE workflow_name = 'expired-wf'").fetchone()
        conn.close()
        assert row["tuev_status"] == "passed"
        assert row["last_tuev_date"] is not None
        valid = datetime.fromisoformat(row["tuev_valid_until"])
        assert valid > datetime.now() + timedelta(days=80)


# ================================================================
# TUEV: INIT
# ================================================================

class TestTuevInit:
    def test_no_dir(self, tuev):
        tuev.workflows_dir = tuev.base_path / "nonexistent"
        ok, msg = tuev.handle("init", [])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_init_workflows(self, tuev, tmp_tuev):
        _, _, wf_dir = tmp_tuev
        (wf_dir / "bugfix-protokoll.md").write_text("# Bugfix", encoding="utf-8")
        (wf_dir / "feature-test.md").write_text("# Feature", encoding="utf-8")

        ok, msg = tuev.handle("init", [])
        assert ok is True
        assert "Hinzugefuegt: 2" in msg

    def test_init_skips_existing(self, tuev, tmp_tuev):
        _, db_path, wf_dir = tmp_tuev
        (wf_dir / "existing.md").write_text("# Existing", encoding="utf-8")

        tuev.handle("init", [])
        ok, msg = tuev.handle("init", [])
        assert ok is True
        assert "Uebersprungen: 1" in msg
        assert "Hinzugefuegt: 0" in msg


# ================================================================
# USECASE: PROPERTIES
# ================================================================

class TestUsecaseProperties:
    def test_profile_name(self, usecase):
        assert usecase.profile_name == "usecase"

    def test_target_file(self, usecase):
        assert usecase.target_file == usecase.db_path

    def test_operations(self, usecase):
        ops = usecase.get_operations()
        assert "add" in ops
        assert "list" in ops
        assert "run" in ops
        assert "run-all" in ops
        assert "show" in ops


# ================================================================
# USECASE: HANDLE ROUTING
# ================================================================

class TestUsecaseRouting:
    def test_unknown_op(self, usecase):
        ok, msg = usecase.handle("xyzfoo", [])
        assert ok is False
        assert "Unbekannte" in msg

    def test_empty_op_defaults_to_list(self, usecase):
        ok, msg = usecase.handle("", [])
        assert ok is True

    def test_add_no_args(self, usecase):
        ok, msg = usecase.handle("add", [])
        assert ok is False
        assert "Usage" in msg

    def test_run_no_args(self, usecase):
        ok, msg = usecase.handle("run", [])
        assert ok is False
        assert "Usage" in msg

    def test_run_all_no_args(self, usecase):
        ok, msg = usecase.handle("run-all", [])
        assert ok is True
        assert "Keine Testfaelle" in msg

    def test_show_no_args(self, usecase):
        ok, msg = usecase.handle("show", [])
        assert ok is False
        assert "Usage" in msg


# ================================================================
# USECASE: LIST
# ================================================================

class TestUsecaseList:
    def test_empty(self, usecase):
        ok, msg = usecase.handle("list", [])
        assert ok is True
        assert "Keine Testfaelle" in msg

    def test_with_data(self, seeded_usecase):
        ok, msg = seeded_usecase.handle("list", [])
        assert ok is True
        assert "Login-Test" in msg
        assert "Fehltest" in msg
        assert "Anderer WF Test" in msg
        assert "Gesamt: 3" in msg

    def test_filtered(self, seeded_usecase):
        ok, msg = seeded_usecase.handle("list", ["test-wf"])
        assert ok is True
        assert "Login-Test" in msg
        assert "Anderer WF Test" not in msg

    def test_filtered_no_results(self, seeded_usecase):
        ok, msg = seeded_usecase.handle("list", ["nonexistent-wf"])
        assert ok is True
        assert "Keine Testfaelle" in msg


# ================================================================
# USECASE: ADD
# ================================================================

class TestUsecaseAdd:
    def test_add_shows_template(self, usecase):
        ok, msg = usecase.handle("add", ["my-workflow"])
        assert ok is True
        assert "my-workflow" in msg
        assert "INSERT INTO usecases" in msg


# ================================================================
# USECASE: SHOW
# ================================================================

class TestUsecaseShow:
    def test_not_found(self, usecase):
        ok, msg = usecase.handle("show", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_found(self, seeded_usecase):
        ok, msg = seeded_usecase.handle("show", ["1"])
        assert ok is True
        assert "Login-Test" in msg
        assert "test-wf" in msg
        assert "admin" in msg
        assert "Score:" in msg


# ================================================================
# USECASE: RUN
# ================================================================

class TestUsecaseRun:
    def test_not_found(self, usecase):
        ok, msg = usecase.handle("run", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_found(self, seeded_usecase, tmp_tuev):
        _, db_path, _ = tmp_tuev
        ok, msg = seeded_usecase.handle("run", ["1"])
        assert ok is True
        assert "Login-Test" in msg
        assert "Test-Input:" in msg
        assert "Expected Output:" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT last_tested FROM usecases WHERE id = 1").fetchone()
        conn.close()
        assert row["last_tested"] is not None

    def test_dry_run_does_not_update_last_tested(self, seeded_usecase, tmp_tuev):
        _, db_path, _ = tmp_tuev
        ok, msg = seeded_usecase.handle("run", ["1"], dry_run=True)
        assert ok is True
        assert "[DRY-RUN]" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT last_tested FROM usecases WHERE id = 1").fetchone()
        conn.close()
        assert row["last_tested"] is None


# ================================================================
# USECASE: RUN ALL
# ================================================================

class TestUsecaseRunAll:
    def test_no_usecases(self, usecase):
        ok, msg = usecase.handle("run-all", ["nonexistent"])
        assert ok is True
        assert "Keine Testfaelle" in msg

    def test_with_data(self, seeded_usecase):
        ok, msg = seeded_usecase.handle("run-all", ["test-wf"])
        assert ok is True
        assert "Login-Test" in msg
        assert "Fehltest" in msg
        assert "Gesamt: 2" in msg
        assert "Mit Workflow-Datei:" in msg

    def test_without_workflow_runs_all(self, seeded_usecase):
        ok, msg = seeded_usecase.handle("run-all", [])
        assert ok is True
        assert "Sammeltest fuer alle Testfaelle" in msg
        assert "Anderer WF Test" in msg
        assert "Gesamt: 3" in msg

    def test_dry_run_does_not_update_last_tested(self, seeded_usecase, tmp_tuev):
        _, db_path, _ = tmp_tuev
        ok, msg = seeded_usecase.handle("run-all", ["test-wf"], dry_run=True)
        assert ok is True
        assert "[DRY-RUN]" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, last_tested FROM usecases WHERE workflow_name = 'test-wf' ORDER BY id"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        assert all(row["last_tested"] is None for row in rows)


# ================================================================
# HELPERS: PARSE / FORMAT PAYLOAD
# ================================================================

class TestPayloadHelpers:
    def test_parse_none(self):
        assert UsecaseHandler._parse_usecase_payload(None) == {}

    def test_parse_empty(self):
        assert UsecaseHandler._parse_usecase_payload("") == {}
        assert UsecaseHandler._parse_usecase_payload("  ") == {}

    def test_parse_valid_json(self):
        result = UsecaseHandler._parse_usecase_payload('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_invalid_json_returns_string(self):
        result = UsecaseHandler._parse_usecase_payload("just plain text")
        assert result == "just plain text"

    def test_parse_non_string(self):
        result = UsecaseHandler._parse_usecase_payload(42)
        assert result == 42

    def test_format_dict(self):
        result = UsecaseHandler._format_usecase_payload({"a": 1})
        parsed = json.loads(result)
        assert parsed == {"a": 1}

    def test_format_list(self):
        result = UsecaseHandler._format_usecase_payload([1, 2])
        assert json.loads(result) == [1, 2]

    def test_format_string(self):
        assert UsecaseHandler._format_usecase_payload("hello") == "hello"

    def test_format_number(self):
        result = UsecaseHandler._format_usecase_payload(42)
        assert result == "42"


# ================================================================
# HELPERS: WORKFLOW CANDIDATES
# ================================================================

class TestWorkflowCandidates:
    def test_resolve_existing(self, seeded_usecase, tmp_tuev):
        system_dir, db_path, wf_dir = tmp_tuev
        (wf_dir / "test-wf.md").write_text("# Test", encoding="utf-8")

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM usecases WHERE id = 1").fetchone()
        resolved, checked = seeded_usecase._resolve_workflow_path(row, conn)
        conn.close()
        assert resolved is not None
        assert resolved.exists()

    def test_resolve_prefers_markdown_file_over_existing_directory(self, seeded_usecase, tmp_tuev):
        system_dir, db_path, wf_dir = tmp_tuev
        (wf_dir / "test-wf.md").write_text("# Test", encoding="utf-8")
        data_dir = system_dir / "test-data"
        data_dir.mkdir()

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE usecases SET workflow_path = ? WHERE id = 1",
            (str(data_dir),),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM usecases WHERE id = 1").fetchone()
        resolved, checked = seeded_usecase._resolve_workflow_path(row, conn)
        conn.close()

        assert resolved == wf_dir / "test-wf.md"

    def test_resolve_missing(self, seeded_usecase, tmp_tuev):
        _, db_path, _ = tmp_tuev
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM usecases WHERE id = 1").fetchone()
        resolved, checked = seeded_usecase._resolve_workflow_path(row, conn)
        conn.close()
        assert resolved is None
        assert len(checked) > 0

    def test_candidates_generates_variants(self, seeded_usecase, tmp_tuev):
        _, db_path, _ = tmp_tuev
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM usecases WHERE id = 1").fetchone()
        candidates = seeded_usecase._workflow_candidates(row, conn)
        conn.close()
        assert len(candidates) >= 1
        paths_str = [str(c) for c in candidates]
        assert any("test-wf" in p for p in paths_str)
