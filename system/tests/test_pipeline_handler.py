# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for PipelineHandler.

Tests list_available, list_installed, and get_status with a temporary DB.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


@pytest.fixture
def setup(tmp_path):
    """Create temp DB and pipelines directory for PipelineHandler."""
    db_path = tmp_path / "test_bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE pipeline_configs (
            pipeline_id TEXT PRIMARY KEY,
            name TEXT,
            version TEXT,
            type TEXT,
            schedule TEXT,
            installed_at TEXT,
            last_run TEXT,
            status TEXT DEFAULT 'active',
            config_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT,
            result TEXT
        )
    """)
    conn.commit()
    conn.close()

    pipelines_dir = tmp_path / "pipelines"
    pipelines_dir.mkdir()

    return db_path, pipelines_dir


@pytest.fixture
def handler(setup):
    from hub.pipeline import PipelineHandler
    db_path, pipelines_dir = setup
    return PipelineHandler(str(db_path), str(pipelines_dir))


class TestListAvailable:
    def test_empty_dir(self, handler):
        result = handler.list_available()
        assert result == []

    def test_valid_pipeline_definition(self, handler, setup):
        _, pipelines_dir = setup
        definition = {
            "id": "test_pipe",
            "name": "Test Pipeline",
            "version": "1.0",
            "type": "automation",
            "description": "A test pipeline",
            "schedule": "daily"
        }
        (pipelines_dir / "test_pipe.json").write_text(
            json.dumps(definition), encoding="utf-8"
        )

        result = handler.list_available()
        assert len(result) == 1
        assert result[0]["id"] == "test_pipe"
        assert result[0]["name"] == "Test Pipeline"
        assert result[0]["type"] == "automation"

    def test_malformed_json_skipped(self, handler, setup):
        _, pipelines_dir = setup
        (pipelines_dir / "broken.json").write_text("not json{{{", encoding="utf-8")
        result = handler.list_available()
        assert result == []

    def test_multiple_definitions_sorted(self, handler, setup):
        _, pipelines_dir = setup
        for i, name in enumerate(["zeta", "alpha", "mid"]):
            definition = {"id": name, "name": name.title(), "version": "1.0",
                          "type": "auto", "description": f"Pipeline {name}"}
            (pipelines_dir / f"{name}.json").write_text(
                json.dumps(definition), encoding="utf-8"
            )

        result = handler.list_available()
        ids = [r["id"] for r in result]
        assert ids == sorted(ids)


class TestListInstalled:
    def test_empty_db(self, handler):
        result = handler.list_installed()
        assert result == []

    def test_installed_pipeline_shows(self, handler, setup):
        db_path, _ = setup
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            INSERT INTO pipeline_configs (pipeline_id, name, version, type, schedule, installed_at, status)
            VALUES ('test', 'Test', '1.0', 'auto', 'daily', '2026-01-01T00:00:00', 'active')
        """)
        conn.commit()
        conn.close()

        result = handler.list_installed()
        assert len(result) == 1
        assert result[0]["pipeline_id"] == "test"
        assert result[0]["status"] == "active"


class TestGetStatus:
    def test_nonexistent_pipeline(self, handler):
        result = handler.get_status("nonexistent_xyz")
        assert result is None

    def test_existing_pipeline_status(self, handler, setup):
        db_path, _ = setup
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            INSERT INTO pipeline_configs (pipeline_id, name, version, type, schedule, installed_at, status)
            VALUES ('myp', 'My Pipeline', '2.0', 'chain', 'hourly', '2026-01-01', 'active')
        """)
        conn.execute("""
            INSERT INTO pipeline_runs (pipeline_id, started_at, finished_at, status, result)
            VALUES ('myp', '2026-01-01T10:00:00', '2026-01-01T10:05:00', 'success', 'ok')
        """)
        conn.commit()
        conn.close()

        result = handler.get_status("myp")
        assert result is not None
        assert result["config"]["pipeline_id"] == "myp"
        assert result["config"]["status"] == "active"
        assert len(result["runs"]) == 1
        assert result["runs"][0]["status"] == "success"
