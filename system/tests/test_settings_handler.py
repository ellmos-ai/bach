# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SettingsHandler (hub/settings.py)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.settings import SettingsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_config_table(conn):
    conn.execute("""
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            type TEXT DEFAULT 'string',
            category TEXT,
            description TEXT,
            dist_type INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    conn.commit()


@pytest.fixture
def fake_settings_env(tmp_path, monkeypatch):
    """Minimal env with system_config table."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_config_table(conn)

    conn.execute(
        "INSERT INTO system_config (key, value, type, category, description, dist_type) "
        "VALUES ('timeout', '30', 'int', 'behavior', 'Timeout in Sekunden', 0)"
    )
    conn.execute(
        "INSERT INTO system_config (key, value, type, category, description, dist_type) "
        "VALUES ('secrets_path', '~/.bach/secrets.json', 'string', 'security', 'Pfad zu Secrets', 2)"
    )
    conn.execute(
        "INSERT INTO system_config (key, value, type, category, description, dist_type) "
        "VALUES ('auto_backup', 'true', 'bool', 'backup', 'Automatisches Backup', 1)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def handler(fake_settings_env):
    base, _ = fake_settings_env
    return SettingsHandler(base)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "settings"

    def test_target_file(self, handler, fake_settings_env):
        _, db_path = fake_settings_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "get" in ops
        assert "set" in ops
        assert "reset" in ops
        assert "export" in ops
        assert "categories" in ops


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_all(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "timeout" in output
        assert "secrets_path" in output
        assert "auto_backup" in output

    def test_list_by_category(self, handler):
        ok, output = handler.handle("list", ["--category=security"])
        assert ok is True
        assert "secrets_path" in output
        assert "timeout" not in output

    def test_list_empty_category(self, handler):
        ok, output = handler.handle("list", ["--category=nonexistent"])
        assert ok is True
        assert "Keine Einstellungen" in output

    def test_list_dist_type_labels(self, handler):
        ok, output = handler.handle("list", [])
        assert "USER" in output
        assert "CORE" in output
        assert "TMPL" in output


# ═══════════════════════════════════════════════════════════════
# GET
# ═══════════════════════════════════════════════════════════════


class TestGet:
    def test_get_existing(self, handler):
        ok, output = handler.handle("get", ["timeout"])
        assert ok is True
        assert "timeout" in output
        assert "30" in output
        assert "behavior" in output

    def test_get_not_found(self, handler):
        ok, output = handler.handle("get", ["nonexistent_key"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_get_no_args(self, handler):
        ok, output = handler.handle("get", [])
        assert ok is True
        assert "bach settings" in output


# ═══════════════════════════════════════════════════════════════
# SET
# ═══════════════════════════════════════════════════════════════


class TestSet:
    def test_set_existing_user(self, handler):
        ok, output = handler.handle("set", ["timeout=60"])
        assert ok is True
        assert "aktualisiert" in output
        ok2, out2 = handler.handle("get", ["timeout"])
        assert "60" in out2

    def test_set_new_key(self, handler):
        ok, output = handler.handle("set", ["new_key=hello"])
        assert ok is True
        assert "erstellt" in output
        ok2, out2 = handler.handle("get", ["new_key"])
        assert "hello" in out2

    def test_set_core_blocked(self, handler):
        ok, output = handler.handle("set", ["secrets_path=/new/path"])
        assert ok is False
        assert "CORE" in output

    def test_set_with_category(self, handler):
        ok, output = handler.handle("set", ["my_key=val", "--category=test"])
        assert ok is True
        ok2, out2 = handler.handle("get", ["my_key"])
        assert "test" in out2

    def test_set_with_description(self, handler):
        ok, output = handler.handle("set", ["my_key=val", "--desc=My description"])
        assert ok is True
        ok2, out2 = handler.handle("get", ["my_key"])
        assert "My description" in out2

    def test_set_invalid_format(self, handler):
        ok, output = handler.handle("set", ["no_equals_sign"])
        assert ok is False
        assert "Format" in output

    def test_set_empty_key(self, handler):
        ok, output = handler.handle("set", ["=value"])
        assert ok is False
        assert "leer" in output

    def test_set_dry_run(self, handler):
        ok, output = handler.handle("set", ["timeout=999"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output
        ok2, out2 = handler.handle("get", ["timeout"])
        assert "30" in out2


# ═══════════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════════


class TestReset:
    def test_reset_user_setting(self, handler):
        ok, output = handler.handle("reset", ["timeout"])
        assert ok is True
        assert "geloescht" in output
        ok2, out2 = handler.handle("get", ["timeout"])
        assert ok2 is False

    def test_reset_core_blocked(self, handler):
        ok, output = handler.handle("reset", ["secrets_path"])
        assert ok is False
        assert "CORE" in output

    def test_reset_not_found(self, handler):
        ok, output = handler.handle("reset", ["nonexistent"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_reset_dry_run(self, handler):
        ok, output = handler.handle("reset", ["timeout"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output
        ok2, _ = handler.handle("get", ["timeout"])
        assert ok2 is True


# ═══════════════════════════════════════════════════════════════
# EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════


class TestExportImport:
    def test_export_json(self, handler):
        ok, output = handler.handle("export", [])
        assert ok is True
        data = json.loads(output)
        assert "timeout" in data
        assert data["timeout"]["value"] == "30"

    def test_export_to_file(self, handler, tmp_path):
        outfile = str(tmp_path / "export.json")
        ok, output = handler.handle("export", [outfile])
        assert ok is True
        assert "exportiert" in output
        data = json.loads(Path(outfile).read_text(encoding="utf-8"))
        assert "timeout" in data

    def test_import_file(self, handler, tmp_path):
        import_data = {
            "imported_key": {"value": "imported_val", "type": "string", "category": "test", "description": "test", "dist_type": 0}
        }
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data), encoding="utf-8")

        ok, output = handler.handle("import", [str(import_file)])
        assert ok is True
        assert "1 Settings importiert" in output

        ok2, out2 = handler.handle("get", ["imported_key"])
        assert ok2 is True
        assert "imported_val" in out2

    def test_import_skips_core(self, handler, tmp_path):
        import_data = {
            "secrets_path": {"value": "/hacked", "type": "string", "category": "security", "description": "hacked", "dist_type": 2}
        }
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data), encoding="utf-8")

        ok, output = handler.handle("import", [str(import_file)])
        assert ok is True
        assert "1 CORE uebersprungen" in output

        ok2, out2 = handler.handle("get", ["secrets_path"])
        assert "/hacked" not in out2

    def test_import_file_not_found(self, handler):
        ok, output = handler.handle("import", ["/nonexistent/file.json"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_import_dry_run(self, handler, tmp_path):
        import_data = {"key1": {"value": "v", "dist_type": 0}}
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data), encoding="utf-8")

        ok, output = handler.handle("import", [str(import_file)], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output


# ═══════════════════════════════════════════════════════════════
# CATEGORIES
# ═══════════════════════════════════════════════════════════════


class TestCategories:
    def test_categories_list(self, handler):
        ok, output = handler.handle("categories", [])
        assert ok is True
        assert "backup" in output
        assert "behavior" in output
        assert "security" in output

    def test_categories_count(self, handler):
        ok, output = handler.handle("categories", [])
        assert "3 Kategorien" in output


# ═══════════════════════════════════════════════════════════════
# DEFAULT OPERATION
# ═══════════════════════════════════════════════════════════════


class TestDefaultOp:
    def test_unknown_op_shows_help(self, handler):
        ok, output = handler.handle("unknown", [])
        assert ok is True
        assert "bach settings" in output

    def test_empty_op_shows_help(self, handler):
        ok, output = handler.handle("", [])
        assert ok is True
        assert "bach settings" in output
