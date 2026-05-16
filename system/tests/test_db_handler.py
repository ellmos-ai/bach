# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for DbHandler — database operations (status, tables, info, query, schema, count, export, insert, backup)."""

import csv
import io
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.db import DbHandler


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def handler(tmp_path):
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE test_items ("
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, value REAL, dist_type INTEGER DEFAULT 0)"
    )
    conn.execute("INSERT INTO test_items (name, value, dist_type) VALUES ('alpha', 1.5, 0)")
    conn.execute("INSERT INTO test_items (name, value, dist_type) VALUES ('beta', 2.7, 1)")
    conn.execute("INSERT INTO test_items (name, value, dist_type) VALUES ('gamma', 3.9, 2)")
    conn.execute(
        "CREATE TABLE system_identity ("
        "id INTEGER PRIMARY KEY, instance_name TEXT, version TEXT)"
    )
    conn.execute("INSERT INTO system_identity VALUES (1, 'TestBach', '9.9.9')")
    conn.execute("CREATE TABLE empty_table (id INTEGER PRIMARY KEY, label TEXT)")
    conn.execute("CREATE INDEX idx_test_name ON test_items(name)")
    conn.execute("CREATE VIEW test_view AS SELECT name FROM test_items")
    conn.commit()
    conn.close()

    h = DbHandler(tmp_path)
    h.db_path = db_path
    return h


@pytest.fixture
def handler_no_db(tmp_path):
    h = DbHandler(tmp_path)
    h.db_path = tmp_path / "nonexistent.db"
    return h


# ── handle() dispatch ────────────────────────────────────────────────

class TestHandleDispatch:

    def test_db_not_found(self, handler_no_db):
        ok, msg = handler_no_db.handle("status", [])
        assert not ok
        assert "nicht gefunden" in msg

    def test_empty_operation_falls_back_to_status(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "BACH DATABASE" in msg

    def test_unknown_operation_falls_back_to_status(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok
        assert "BACH DATABASE" in msg

    def test_query_dry_run(self, handler):
        ok, msg = handler.handle("query", ["SELECT 1"], dry_run=True)
        assert ok
        assert "[DRY-RUN]" in msg
        assert "SELECT 1" in msg

    def test_export_dry_run(self, handler):
        ok, msg = handler.handle("export", ["test_items"], dry_run=True)
        assert ok
        assert "[DRY-RUN]" in msg

    def test_insert_dry_run(self, handler):
        ok, msg = handler.handle("insert", ["test_items", '{"name":"x"}'], dry_run=True)
        assert ok
        assert "[DRY-RUN]" in msg

    def test_backup_dry_run(self, handler):
        ok, msg = handler.handle("backup", [], dry_run=True)
        assert ok
        assert "[DRY-RUN]" in msg

    def test_export_format_flag(self, handler):
        ok, msg = handler.handle("export", ["test_items", "--format=json"])
        assert ok
        assert "json" in msg.lower()

    def test_export_format_positional(self, handler):
        ok, msg = handler.handle("export", ["test_items", "json"])
        assert ok
        assert "json" in msg.lower()


# ── profile / operations ─────────────────────────────────────────────

class TestProperties:

    def test_profile_name(self, handler):
        assert handler.profile_name == "db"

    def test_target_file(self, handler):
        assert handler.target_file == handler.db_path

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert "status" in ops
        assert "tables" in ops
        assert "query" in ops
        assert "backup" in ops


# ── _status() ────────────────────────────────────────────────────────

class TestStatus:

    def test_status_returns_table_count(self, handler):
        ok, msg = handler._status()
        assert ok
        assert "Tabellen:" in msg

    def test_status_shows_size(self, handler):
        ok, msg = handler._status()
        assert ok
        assert "Groesse:" in msg

    def test_status_shows_instance(self, handler):
        ok, msg = handler._status()
        assert ok
        assert "Instance: TestBach v9.9.9" in msg

    def test_status_shows_views(self, handler):
        ok, msg = handler._status()
        assert ok
        assert "Views:" in msg

    def test_status_shows_indices(self, handler):
        ok, msg = handler._status()
        assert ok
        assert "Indices:" in msg

    def test_status_without_system_identity(self, tmp_path):
        db_path = tmp_path / "data" / "bach.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.commit()
        conn.close()
        h = DbHandler(tmp_path)
        h.db_path = db_path
        ok, msg = h._status()
        assert ok
        assert "Instance:" not in msg


# ── _tables() ────────────────────────────────────────────────────────

class TestTables:

    def test_tables_lists_all(self, handler):
        ok, msg = handler._tables()
        assert ok
        assert "test_items" in msg
        assert "empty_table" in msg
        assert "system_identity" in msg

    def test_tables_shows_counts(self, handler):
        ok, msg = handler._tables()
        assert ok
        assert "3" in msg  # test_items has 3 rows


# ── _info() ──────────────────────────────────────────────────────────

class TestInfo:

    def test_info_existing_table(self, handler):
        ok, msg = handler._info("test_items")
        assert ok
        assert "TABELLE: test_items" in msg
        assert "Zeilen: 3" in msg

    def test_info_shows_columns(self, handler):
        ok, msg = handler._info("test_items")
        assert ok
        assert "SPALTEN:" in msg
        assert "name" in msg
        assert "value" in msg

    def test_info_shows_dist_type_distribution(self, handler):
        ok, msg = handler._info("test_items")
        assert ok
        assert "DIST_TYPE" in msg
        assert "USER" in msg
        assert "TEMPLATE" in msg
        assert "CORE" in msg

    def test_info_shows_indices(self, handler):
        ok, msg = handler._info("test_items")
        assert ok
        assert "INDICES" in msg
        assert "idx_test_name" in msg

    def test_info_shows_sample_data(self, handler):
        ok, msg = handler._info("test_items")
        assert ok
        assert "BEISPIELDATEN" in msg
        assert "alpha" in msg

    def test_info_nonexistent_table(self, handler):
        ok, msg = handler._info("no_such_table")
        assert not ok
        assert "nicht gefunden" in msg

    def test_info_empty_table(self, handler):
        ok, msg = handler._info("empty_table")
        assert ok
        assert "Zeilen: 0" in msg
        assert "BEISPIELDATEN" not in msg


# ── _query() ─────────────────────────────────────────────────────────

class TestQuery:

    def test_select_returns_rows(self, handler):
        ok, msg = handler._query("SELECT name, value FROM test_items ORDER BY id")
        assert ok
        assert "alpha" in msg
        assert "beta" in msg
        assert "gamma" in msg

    def test_select_no_results(self, handler):
        ok, msg = handler._query("SELECT * FROM test_items WHERE id = 999")
        assert ok
        assert "Keine Ergebnisse" in msg

    def test_update_statement(self, handler):
        ok, msg = handler._query("UPDATE test_items SET value = 99.0 WHERE name = 'alpha'")
        assert ok
        assert "[OK]" in msg
        assert "1" in msg

    def test_invalid_sql(self, handler):
        ok, msg = handler._query("SELECT * FROM nonexistent_table_xyz")
        assert ok
        assert "[FEHLER]" in msg

    def test_select_truncates_at_50(self, handler):
        conn = sqlite3.connect(str(handler.db_path))
        for i in range(60):
            conn.execute("INSERT INTO test_items (name, value) VALUES (?, ?)", (f"row_{i}", float(i)))
        conn.commit()
        conn.close()
        ok, msg = handler._query("SELECT * FROM test_items")
        assert ok
        assert "weitere" in msg


# ── _schema() ────────────────────────────────────────────────────────

class TestSchema:

    def test_schema_returns_create_statement(self, handler):
        ok, msg = handler._schema("test_items")
        assert ok
        assert "CREATE TABLE" in msg
        assert "test_items" in msg
        assert msg.endswith(";")

    def test_schema_includes_indices(self, handler):
        ok, msg = handler._schema("test_items")
        assert ok
        assert "idx_test_name" in msg

    def test_schema_nonexistent_table(self, handler):
        ok, msg = handler._schema("no_such_table")
        assert not ok
        assert "nicht gefunden" in msg


# ── _count() ─────────────────────────────────────────────────────────

class TestCount:

    def test_count_returns_number(self, handler):
        ok, msg = handler._count("test_items")
        assert ok
        assert "3" in msg
        assert "Eintraege" in msg

    def test_count_empty_table(self, handler):
        ok, msg = handler._count("empty_table")
        assert ok
        assert "0" in msg

    def test_count_nonexistent_table(self, handler):
        ok, msg = handler._count("no_such_table")
        assert not ok
        assert "Fehler" in msg


# ── _export() ────────────────────────────────────────────────────────

class TestExport:

    def test_export_csv(self, handler):
        ok, msg = handler._export("test_items", "csv")
        assert ok
        assert "Exportiert:" in msg
        assert "3 Eintraege" in msg
        assert "csv" in msg

        export_dir = handler.base_path / "data" / "export"
        csv_files = list(export_dir.glob("test_items_*.csv"))
        assert len(csv_files) == 1
        content = csv_files[0].read_text(encoding="utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = [r for r in reader if r]
        assert rows[0] == ["id", "name", "value", "dist_type"]
        assert len(rows) == 4  # header + 3 data rows

    def test_export_json(self, handler):
        ok, msg = handler._export("test_items", "json")
        assert ok
        assert "json" in msg

        export_dir = handler.base_path / "data" / "export"
        json_files = list(export_dir.glob("test_items_*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert len(data) == 3
        assert data[0]["name"] == "alpha"

    def test_export_empty_table(self, handler):
        ok, msg = handler._export("empty_table")
        assert ok
        assert "leer" in msg

    def test_export_nonexistent_table(self, handler):
        ok, msg = handler._export("no_such_table")
        assert not ok
        assert "Fehler" in msg


# ── _insert() ────────────────────────────────────────────────────────

class TestInsert:

    def test_insert_valid(self, handler):
        ok, msg = handler._insert("test_items", '{"name": "delta", "value": 4.2}')
        assert ok
        assert "[OK]" in msg
        conn = sqlite3.connect(str(handler.db_path))
        count = conn.execute("SELECT COUNT(*) FROM test_items WHERE name='delta'").fetchone()[0]
        conn.close()
        assert count == 1

    def test_insert_invalid_json(self, handler):
        ok, msg = handler._insert("test_items", "not json")
        assert not ok
        assert "Ungueltige JSON" in msg

    def test_insert_non_dict_json(self, handler):
        ok, msg = handler._insert("test_items", "[1,2,3]")
        assert not ok
        assert "Objekt" in msg

    def test_insert_unknown_column(self, handler):
        ok, msg = handler._insert("test_items", '{"name": "x", "bogus_col": 1}')
        assert not ok
        assert "Unbekannte Spalten" in msg

    def test_insert_nonexistent_table(self, handler):
        ok, msg = handler._insert("no_such_table", '{"a": 1}')
        assert not ok
        assert "nicht gefunden" in msg


# ── _backup() ────────────────────────────────────────────────────────

class TestBackup:

    def test_backup_creates_file(self, handler, tmp_path):
        backup_dir = tmp_path / "backups"
        with patch("hub.db.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch("hub.db.Path.home", return_value=tmp_path):
                ok, msg = handler._backup()
        assert ok
        assert "[OK]" in msg
        assert "Backup:" in msg
        assert "KB" in msg

    def test_backup_source_missing(self, handler_no_db, tmp_path):
        with patch("hub.db.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch("hub.db.Path.home", return_value=tmp_path):
                ok, msg = handler_no_db._backup()
        assert not ok
        assert "Backup-Fehler" in msg


# ── Connection safety ────────────────────────────────────────────────

class TestConnectionSafety:

    def test_status_closes_connection(self, handler):
        handler._status()
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_tables_closes_connection(self, handler):
        handler._tables()
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_info_closes_connection(self, handler):
        handler._info("test_items")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_query_closes_connection(self, handler):
        handler._query("SELECT 1")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_count_closes_connection(self, handler):
        handler._count("test_items")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_schema_closes_connection(self, handler):
        handler._schema("test_items")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_export_closes_connection(self, handler):
        handler._export("test_items")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_insert_closes_connection(self, handler):
        handler._insert("test_items", '{"name": "conn_test", "value": 0}')
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_info_nonexistent_closes_connection(self, handler):
        handler._info("no_such_table")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()

    def test_schema_nonexistent_closes_connection(self, handler):
        handler._schema("no_such_table")
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("SELECT 1")
        conn.close()
