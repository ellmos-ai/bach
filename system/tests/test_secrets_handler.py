"""Tests fuer hub/secrets_handler.py — Secrets-Management"""

import json
import sqlite3
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM = Path(__file__).resolve().parent.parent
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))


@pytest.fixture
def secrets_env(tmp_path):
    """Erstellt tmp DB mit secrets-Tabelle und Secrets-Datei."""
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS secrets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'manual',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

    secrets_file = tmp_path / "bach_secrets.json"

    return tmp_path, db_path, secrets_file


@pytest.fixture
def handler(secrets_env):
    """Erstellt SecretsHandler mit Mock-DB."""
    tmp_path, db_path, secrets_file = secrets_env

    def mock_conn():
        return sqlite3.connect(str(db_path))

    with patch("hub.secrets_handler.GET_CONNECTION", mock_conn):
        from hub.secrets_handler import SecretsHandler
        h = SecretsHandler(secrets_file=str(secrets_file))
    return h


@pytest.fixture
def populated(handler, secrets_env):
    """Handler mit vorbestückten Secrets."""
    tmp_path, db_path, secrets_file = secrets_env
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO secrets (key, value, description, category, source, created_at, updated_at) "
        "VALUES ('telegram_token', '123:ABC', 'Telegram Bot', 'api', 'manual', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO secrets (key, value, description, category, source, created_at, updated_at) "
        "VALUES ('openai_key', 'sk-xyz', 'OpenAI API', 'api', 'file', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO secrets (key, value, description, category, source, created_at, updated_at) "
        "VALUES ('db_password', 'secret123', 'Database PW', 'infra', 'manual', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    handler.conn = sqlite3.connect(str(db_path))
    return handler


# ================================================================
# TestInit
# ================================================================
class TestInit:
    def test_default_init(self, secrets_env):
        _, db_path, secrets_file = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn):
            from hub.secrets_handler import SecretsHandler
            h = SecretsHandler(secrets_file=str(secrets_file))
            assert h.secrets_file == Path(str(secrets_file))
            assert h.conn is not None

    def test_custom_secrets_file(self, secrets_env):
        _, db_path, _ = secrets_env
        custom = Path(str(secrets_env[0])) / "custom_secrets.json"

        def mock_conn():
            return sqlite3.connect(str(db_path))

        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn):
            from hub.secrets_handler import SecretsHandler
            h = SecretsHandler(secrets_file=str(custom))
            assert h.secrets_file == custom


# ================================================================
# TestListSecrets
# ================================================================
class TestListSecrets:
    def test_empty_list(self, handler):
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.list_secrets()
        assert "Keine Secrets" in captured.getvalue()

    def test_list_shows_secrets(self, populated):
        captured = StringIO()
        with patch("sys.stdout", captured):
            populated.list_secrets()
        output = captured.getvalue()
        assert "telegram_token" in output
        assert "openai_key" in output
        assert "Gesamt: 3" in output

    def test_list_shows_categories(self, populated):
        captured = StringIO()
        with patch("sys.stdout", captured):
            populated.list_secrets()
        output = captured.getvalue()
        assert "api" in output
        assert "infra" in output


# ================================================================
# TestGetSecret
# ================================================================
class TestGetSecret:
    def test_get_existing(self, populated):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = populated.get_secret("telegram_token")
        assert result == "123:ABC"
        assert "telegram_token" in captured.getvalue()

    def test_get_nonexistent(self, populated):
        captured = StringIO()
        stderr = StringIO()
        with patch("sys.stdout", captured), patch("sys.stderr", stderr):
            result = populated.get_secret("nonexistent")
        assert result is None
        assert "nicht gefunden" in stderr.getvalue()

    def test_get_returns_value(self, populated):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = populated.get_secret("db_password")
        assert result == "secret123"


# ================================================================
# TestSetSecret
# ================================================================
class TestSetSecret:
    def test_set_new(self, handler, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = handler.set_secret("new_key", "new_value", "A new secret", "test")
        assert result is True
        assert "erstellt" in captured.getvalue()

    def test_set_updates_existing(self, populated, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = populated.set_secret("telegram_token", "new_token_val", "Updated", "api")
        assert result is True
        assert "aktualisiert" in captured.getvalue()

        captured2 = StringIO()
        with patch("sys.stdout", captured2):
            val = populated.get_secret("telegram_token")
        assert val == "new_token_val"

    def test_set_syncs_to_file(self, handler, secrets_env):
        _, _, secrets_file = secrets_env
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.set_secret("sync_test", "sync_val", "Test sync")
        assert secrets_file.exists()
        data = json.loads(secrets_file.read_text(encoding="utf-8"))
        assert "sync_test" in data["secrets"]
        assert data["secrets"]["sync_test"]["value"] == "sync_val"

    def test_set_with_category(self, handler, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.set_secret("cat_key", "cat_val", "desc", "infrastructure")
        cursor = handler.conn.cursor()
        cursor.execute("SELECT category FROM secrets WHERE key = 'cat_key'")
        assert cursor.fetchone()[0] == "infrastructure"


# ================================================================
# TestDeleteSecret
# ================================================================
class TestDeleteSecret:
    def test_delete_existing(self, populated, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = populated.delete_secret("telegram_token")
        assert result is True
        assert "gelöscht" in captured.getvalue() or "geloescht" in captured.getvalue()

    def test_delete_nonexistent(self, handler):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = handler.delete_secret("nonexistent")
        assert result is False

    def test_delete_syncs_file(self, populated, secrets_env):
        _, _, secrets_file = secrets_env
        captured = StringIO()
        with patch("sys.stdout", captured):
            populated.delete_secret("telegram_token")
        if secrets_file.exists():
            data = json.loads(secrets_file.read_text(encoding="utf-8"))
            assert "telegram_token" not in data.get("secrets", {})


# ================================================================
# TestSyncFromFile
# ================================================================
class TestSyncFromFile:
    def test_sync_missing_file_enforces_authority(self, handler):
        captured = StringIO()
        handler.conn.execute(
            "INSERT INTO secrets (key, value, created_at, updated_at) VALUES ('old', 'val', '', '')"
        )
        handler.conn.commit()
        with patch("sys.stdout", captured):
            handler.sync_from_file(enforce_authority=True)
        cursor = handler.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM secrets")
        assert cursor.fetchone()[0] == 0

    def test_sync_missing_file_no_authority(self, handler):
        captured = StringIO()
        handler.conn.execute(
            "INSERT INTO secrets (key, value, created_at, updated_at) VALUES ('keep', 'val', '', '')"
        )
        handler.conn.commit()
        with patch("sys.stdout", captured):
            handler.sync_from_file(enforce_authority=False)
        cursor = handler.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM secrets")
        assert cursor.fetchone()[0] == 1

    def test_sync_from_valid_file(self, handler, secrets_env):
        _, _, secrets_file = secrets_env
        data = {
            "meta": {"version": "1.0"},
            "secrets": {
                "file_key1": {"value": "val1", "description": "desc1", "category": "api"},
                "file_key2": {"value": "val2", "description": "desc2", "category": "infra"},
                "_example_skip": {"value": "skip", "description": "example"},
            }
        }
        secrets_file.write_text(json.dumps(data), encoding="utf-8")
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.sync_from_file()
        cursor = handler.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM secrets")
        assert cursor.fetchone()[0] == 2
        cursor.execute("SELECT value FROM secrets WHERE key = 'file_key1'")
        assert cursor.fetchone()[0] == "val1"

    def test_sync_skips_examples(self, handler, secrets_env):
        _, _, secrets_file = secrets_env
        data = {
            "meta": {"version": "1.0"},
            "secrets": {
                "_example_key": {"value": "skip_me", "description": "example"},
                "real_key": {"value": "keep_me", "description": "real"},
            }
        }
        secrets_file.write_text(json.dumps(data), encoding="utf-8")
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.sync_from_file()
        cursor = handler.conn.cursor()
        cursor.execute("SELECT key FROM secrets")
        keys = [r[0] for r in cursor.fetchall()]
        assert "_example_key" not in keys
        assert "real_key" in keys

    def test_sync_updates_existing(self, populated, secrets_env):
        _, _, secrets_file = secrets_env
        data = {
            "meta": {"version": "1.0"},
            "secrets": {
                "telegram_token": {"value": "NEW_TOKEN", "description": "Updated via file", "category": "api"},
            }
        }
        secrets_file.write_text(json.dumps(data), encoding="utf-8")
        captured = StringIO()
        with patch("sys.stdout", captured):
            populated.sync_from_file()
        cursor = populated.conn.cursor()
        cursor.execute("SELECT value FROM secrets WHERE key = 'telegram_token'")
        assert cursor.fetchone()[0] == "NEW_TOKEN"

    def test_sync_broken_file(self, handler, secrets_env):
        _, _, secrets_file = secrets_env
        secrets_file.write_text("NOT JSON", encoding="utf-8")
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            handler.sync_from_file()
        assert "Fehler" in stderr.getvalue()


# ================================================================
# TestSyncToFile
# ================================================================
class TestSyncToFile:
    def test_sync_creates_file(self, handler, secrets_env):
        _, _, secrets_file = secrets_env
        handler.conn.execute(
            "INSERT INTO secrets (key, value, description, category, created_at, updated_at) "
            "VALUES ('test_key', 'test_val', 'test desc', 'api', '2026-01-01', '2026-01-01')"
        )
        handler.conn.commit()
        handler._sync_to_file()
        assert secrets_file.exists()
        data = json.loads(secrets_file.read_text(encoding="utf-8"))
        assert "test_key" in data["secrets"]
        assert data["meta"]["version"] == "1.0"

    def test_sync_creates_parent_dir(self, secrets_env):
        _, db_path, _ = secrets_env
        nested_file = secrets_env[0] / "sub" / "dir" / "secrets.json"

        def mock_conn():
            return sqlite3.connect(str(db_path))

        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn):
            from hub.secrets_handler import SecretsHandler
            h = SecretsHandler(secrets_file=str(nested_file))
            h.conn.execute(
                "INSERT INTO secrets (key, value, description, category, created_at, updated_at) "
                "VALUES ('k', 'v', '', '', '', '')"
            )
            h.conn.commit()
            h._sync_to_file()
        assert nested_file.exists()


# ================================================================
# TestHandleCommand
# ================================================================
class TestHandleCommand:
    def test_help(self, secrets_env):
        _, db_path, secrets_file = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        captured = StringIO()
        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn), \
             patch("sys.stdout", captured):
            from hub.secrets_handler import handle_secrets_command
            handle_secrets_command([])
        assert "Verwendung" in captured.getvalue()

    def test_help_flag(self, secrets_env):
        _, db_path, _ = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        captured = StringIO()
        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn), \
             patch("sys.stdout", captured):
            from hub.secrets_handler import handle_secrets_command
            handle_secrets_command(["--help"])
        assert "Verwendung" in captured.getvalue()

    def test_unknown_subcommand(self, secrets_env):
        _, db_path, _ = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        stderr = StringIO()
        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn), \
             patch("sys.stderr", stderr):
            from hub.secrets_handler import handle_secrets_command
            handle_secrets_command(["foobar"])
        assert "Unbekannter" in stderr.getvalue()

    def test_get_missing_key_arg(self, secrets_env):
        _, db_path, _ = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        stderr = StringIO()
        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn), \
             patch("sys.stderr", stderr):
            from hub.secrets_handler import handle_secrets_command
            handle_secrets_command(["get"])
        assert "Key fehlt" in stderr.getvalue()

    def test_set_missing_args(self, secrets_env):
        _, db_path, _ = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        stderr = StringIO()
        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn), \
             patch("sys.stderr", stderr):
            from hub.secrets_handler import handle_secrets_command
            handle_secrets_command(["set", "onlykey"])
        assert "fehlen" in stderr.getvalue()

    def test_delete_missing_key(self, secrets_env):
        _, db_path, _ = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        stderr = StringIO()
        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn), \
             patch("sys.stderr", stderr):
            from hub.secrets_handler import handle_secrets_command
            handle_secrets_command(["delete"])
        assert "Key fehlt" in stderr.getvalue()


# ================================================================
# TestGetSecretsFilePath
# ================================================================
class TestGetSecretsFilePath:
    def test_default_path(self, secrets_env):
        _, db_path, _ = secrets_env

        def mock_conn():
            return sqlite3.connect(str(db_path))

        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn):
            from hub.secrets_handler import get_secrets_file_path, DEFAULT_SECRETS_FILE
            path = get_secrets_file_path()
            assert path == DEFAULT_SECRETS_FILE

    def test_override_from_config(self, secrets_env):
        _, db_path, _ = secrets_env
        conn = sqlite3.connect(str(db_path))
        custom_path = str(secrets_env[0] / "custom.json")
        conn.execute("INSERT INTO system_config (key, value) VALUES ('secrets_file_path', ?)", (custom_path,))
        conn.commit()
        conn.close()

        def mock_conn():
            return sqlite3.connect(str(db_path))

        with patch("hub.secrets_handler.GET_CONNECTION", mock_conn):
            from hub.secrets_handler import get_secrets_file_path
            path = get_secrets_file_path()
            assert str(path) == custom_path


# ================================================================
# TestEdgeCases
# ================================================================
class TestEdgeCases:
    def test_description_truncation_in_list(self, handler):
        long_desc = "A" * 50
        handler.conn.execute(
            "INSERT INTO secrets (key, value, description, category, source, created_at, updated_at) "
            "VALUES ('long_desc_key', 'val', ?, 'test', 'manual', '', '')",
            (long_desc,)
        )
        handler.conn.commit()
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.list_secrets()
        output = captured.getvalue()
        assert "..." in output

    def test_set_then_get_roundtrip(self, handler, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.set_secret("round_key", "round_val", "roundtrip test")
        captured2 = StringIO()
        with patch("sys.stdout", captured2):
            val = handler.get_secret("round_key")
        assert val == "round_val"

    def test_unicode_values(self, handler, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.set_secret("unicode_key", "Wert mit Ümläuten: äöüß", "Umlaut-Test")
        captured2 = StringIO()
        with patch("sys.stdout", captured2):
            val = handler.get_secret("unicode_key")
        assert val == "Wert mit Ümläuten: äöüß"

    def test_empty_value_allowed(self, handler, secrets_env):
        captured = StringIO()
        with patch("sys.stdout", captured):
            handler.set_secret("empty_val", "", "Empty is ok")
        captured2 = StringIO()
        with patch("sys.stdout", captured2):
            val = handler.get_secret("empty_val")
        assert val == ""
