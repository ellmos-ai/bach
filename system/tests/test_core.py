# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Unit Tests fuer core/ Module
==============================
Tests fuer base, db, registry, adapter, app.
"""

import sys
import sqlite3
import tempfile
from pathlib import Path

# System-Pfad sicherstellen
SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest


# ═══════════════════════════════════════════════════════════════
# core/base.py Tests
# ═══════════════════════════════════════════════════════════════

class TestResult:
    def test_basic_creation(self):
        from core.base import Result
        r = Result(True, "Erfolg")
        assert r.success is True
        assert r.message == "Erfolg"
        assert r.data is None

    def test_with_data(self):
        from core.base import Result
        r = Result(True, "OK", data={"count": 42})
        assert r.data == {"count": 42}

    def test_tuple_unpacking(self):
        from core.base import Result
        r = Result(True, "Hallo")
        success, message = r
        assert success is True
        assert message == "Hallo"

    def test_bool(self):
        from core.base import Result
        assert bool(Result(True, "OK")) is True
        assert bool(Result(False, "Fail")) is False


class TestParsedArgs:
    def test_empty(self):
        from core.base import ParsedArgs
        args = ParsedArgs()
        assert args.positional == []
        assert args.options == {}
        assert args.flags == set()
        assert args.first is None
        assert args.rest == []

    def test_positional(self):
        from core.base import ParsedArgs
        args = ParsedArgs(positional=["add", "Test-Task"])
        assert args.first == "add"
        assert args.rest == ["Test-Task"]

    def test_get_flag(self):
        from core.base import ParsedArgs
        args = ParsedArgs(flags={"dry-run", "verbose"})
        assert args.get("dry-run") is True
        assert args.get("verbose") is True
        assert args.get("missing") is None
        assert args.get("missing", "default") == "default"

    def test_get_option(self):
        from core.base import ParsedArgs
        args = ParsedArgs(options={"output": "/tmp/out"})
        assert args.get("output") == "/tmp/out"

    def test_to_list(self):
        from core.base import ParsedArgs
        args = ParsedArgs(
            positional=["add", "Test"],
            options={"priority": "P1"},
            flags={"dry-run"}
        )
        result = args.to_list()
        assert "add" in result
        assert "Test" in result
        assert "--priority" in result
        assert "P1" in result
        assert "--dry-run" in result


class TestParseArgs:
    def test_simple(self):
        from core.base import parse_args
        args = parse_args(["add", "Test-Task"])
        assert args.positional == ["add", "Test-Task"]

    def test_flags(self):
        from core.base import parse_args, OpDef
        op_def = OpDef(flags=["dry-run", "verbose"])
        args = parse_args(["--dry-run", "task"], op_def)
        assert "dry-run" in args.flags
        assert args.positional == ["task"]

    def test_key_value(self):
        from core.base import parse_args
        args = parse_args(["--output=/tmp/out", "--format", "json"])
        assert args.options["output"] == "/tmp/out"
        assert args.options["format"] == "json"


# ═══════════════════════════════════════════════════════════════
# core/db.py Tests
# ═══════════════════════════════════════════════════════════════

class TestDatabase:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test.db"
        self.schema_dir = Path(self.tmpdir)

        # Minimales Schema erstellen
        schema = (self.schema_dir / "schema.sql")
        schema.write_text(
            "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, name TEXT);",
            encoding="utf-8"
        )

    def test_init_schema(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        assert db.table_exists("test_table")

    def test_execute_write_and_read(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()

        db.execute_write("INSERT INTO test_table (name) VALUES (?)", ("Alice",))
        rows = db.execute("SELECT * FROM test_table")
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"

    def test_execute_one(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()

        db.execute_write("INSERT INTO test_table (name) VALUES (?)", ("Bob",))
        row = db.execute_one("SELECT * FROM test_table WHERE name = ?", ("Bob",))
        assert row is not None
        assert row["name"] == "Bob"

        missing = db.execute_one("SELECT * FROM test_table WHERE name = ?", ("Nobody",))
        assert missing is None

    def test_execute_scalar(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()

        db.execute_write("INSERT INTO test_table (name) VALUES (?)", ("Charlie",))
        count = db.execute_scalar("SELECT COUNT(*) FROM test_table")
        assert count == 1

    def test_tables(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        assert "test_table" in db.tables()

    def test_migrations(self):
        from core.db import Database
        # Migration erstellen
        migrations_dir = self.schema_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_column.sql").write_text(
            "ALTER TABLE test_table ADD COLUMN email TEXT;",
            encoding="utf-8"
        )

        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        db.run_migrations()

        # Pruefe Migration-Tracking
        assert db.table_exists("_migrations")
        applied = db.execute("SELECT filename FROM _migrations")
        assert len(applied) == 1
        assert applied[0]["filename"] == "001_add_column.sql"

    def test_is_empty_fresh_then_populated(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        assert db.is_empty()
        db.init_schema()
        assert not db.is_empty()

    def test_is_empty_ignores_migrations_table(self):
        from core.db import Database
        db = Database(self.db_path, self.schema_dir)
        db.run_migrations()  # legt nur _migrations an
        assert db.is_empty()

    def test_baseline_migrations_books_without_executing(self):
        from core.db import Database
        migrations_dir = self.schema_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_would_crash.sql").write_text(
            "ALTER TABLE test_table ADD COLUMN name TEXT;",  # Spalte existiert schon
            encoding="utf-8")
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        db.baseline_migrations()
        names = {r["filename"] for r in db.execute("SELECT filename FROM _migrations")}
        assert names == {"001_would_crash.sql"}
        applied, error = db.run_migrations()
        assert applied == [] and error is None  # gebucht -> laeuft nie

    def test_py_migration_with_migrate_entrypoint_runs(self):
        # PR-#10-Review Befund 2: migrate(db_path)-Dateien wurden vorher
        # still als applied gebucht, ohne je zu laufen
        from core.db import Database
        migrations_dir = self.schema_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "002_migrate_style.py").write_text(
            "import sqlite3\n"
            "def migrate(db_path):\n"
            "    conn = sqlite3.connect(db_path)\n"
            "    conn.execute('CREATE TABLE IF NOT EXISTS migrated_marker (id INTEGER)')\n"
            "    conn.commit()\n"
            "    conn.close()\n",
            encoding="utf-8"
        )
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        applied, error = db.run_migrations()
        assert error is None
        assert applied == ["002_migrate_style.py"]
        assert db.table_exists("migrated_marker")

    def test_py_migration_without_entrypoint_fails_loud(self):
        from core.db import Database
        migrations_dir = self.schema_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "002_no_entry.py").write_text("x = 1\n", encoding="utf-8")
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        applied, error = db.run_migrations()
        assert applied == []
        assert error is not None and "002_no_entry.py" in error
        names = {r["filename"] for r in db.execute("SELECT filename FROM _migrations")}
        assert "002_no_entry.py" not in names  # nie still buchen

    def test_migration_backlog_detects_unbaselined_gap(self):
        from core.db import Database
        migrations_dir = self.schema_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_old.sql").write_text("SELECT 1;", encoding="utf-8")
        (migrations_dir / "003_mid.sql").write_text("SELECT 1;", encoding="utf-8")
        (migrations_dir / "005_new.sql").write_text("SELECT 1;", encoding="utf-8")
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        # Nichts gebucht, DB nicht leer -> alles ist Rueckstand
        assert db.migration_backlog() == ["001_old.sql", "003_mid.sql", "005_new.sql"]
        # 003 gebucht -> 001 ist Rueckstand (Luecke), 005 ist regulaer neu
        db.execute_write(
            "INSERT INTO _migrations (filename, applied_at) VALUES ('003_mid.sql', '2026-09-01')")
        assert db.migration_backlog() == ["001_old.sql"]
        # 001 auch gebucht -> kein Rueckstand mehr; 005 darf automatisch laufen
        db.execute_write(
            "INSERT INTO _migrations (filename, applied_at) VALUES ('001_old.sql', '2026-09-01')")
        assert db.migration_backlog() == []

    def test_run_migrations_fail_soft_stops_chain(self):
        from core.db import Database
        migrations_dir = self.schema_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_ok.sql").write_text(
            "CREATE TABLE IF NOT EXISTS a1 (id INTEGER);", encoding="utf-8")
        (migrations_dir / "002_broken.sql").write_text(
            "THIS IS NOT SQL;", encoding="utf-8")
        (migrations_dir / "003_after.sql").write_text(
            "CREATE TABLE IF NOT EXISTS a3 (id INTEGER);", encoding="utf-8")
        db = Database(self.db_path, self.schema_dir)
        db.init_schema()
        applied, error = db.run_migrations()
        # 001 gebucht, 002 gescheitert, 003 NICHT ausgefuehrt (Reihenfolge)
        assert applied == ["001_ok.sql"]
        assert error is not None and "002_broken.sql" in error
        assert not db.table_exists("a3")
        names = {r["filename"] for r in db.execute("SELECT filename FROM _migrations")}
        assert names == {"001_ok.sql"}

    def test_init_schema_applies_release_language_seed_for_new_db(self):
        from core.db import Database

        (self.schema_dir / "schema.sql").write_text(
            """
            CREATE TABLE IF NOT EXISTS languages_config (
                id INTEGER PRIMARY KEY,
                default_language TEXT,
                enabled_languages TEXT
            );
            CREATE TABLE IF NOT EXISTS languages_translations (
                id INTEGER PRIMARY KEY,
                key TEXT,
                namespace TEXT,
                language TEXT,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS languages_dictionary (
                id INTEGER PRIMARY KEY,
                term TEXT,
                translation TEXT,
                source_lang TEXT,
                target_lang TEXT
            );
            """,
            encoding="utf-8",
        )

        seed_dir = self.schema_dir / "exports" / "translations"
        seed_dir.mkdir(parents=True)
        (seed_dir / "languages_seed.release.sql").write_text(
            """
            INSERT OR REPLACE INTO languages_config (id, default_language, enabled_languages)
            VALUES (1, 'de', '["de","en","es"]');
            INSERT OR REPLACE INTO languages_translations (id, key, namespace, language, value)
            VALUES (1, 'save', 'cli', 'es', 'Guardar');
            """,
            encoding="utf-8",
        )

        db = Database(self.db_path, self.schema_dir)
        db.init_schema()

        row = db.execute_one("SELECT default_language, enabled_languages FROM languages_config WHERE id = 1")
        translation = db.execute_one("SELECT value FROM languages_translations WHERE key = 'save' AND language = 'es'")

        assert row["default_language"] == "de"
        assert "es" in row["enabled_languages"]
        assert translation["value"] == "Guardar"


# ═══════════════════════════════════════════════════════════════
# core/registry.py Tests
# ═══════════════════════════════════════════════════════════════

class TestHandlerRegistry:
    def test_create_empty(self):
        from core.registry import HandlerRegistry
        reg = HandlerRegistry()
        assert reg.count == 0
        assert reg.names == []

    def test_discover(self):
        from core.registry import HandlerRegistry
        reg = HandlerRegistry()
        count = reg.discover(SYSTEM_ROOT / "hub")
        assert count > 0
        assert "task" in reg.names
        assert "memory" in reg.names

    def test_discover_with_aliases(self):
        from core.registry import HandlerRegistry
        from core.aliases import COMMAND_ALIASES
        reg = HandlerRegistry()
        reg.discover(SYSTEM_ROOT / "hub", aliases=COMMAND_ALIASES)
        assert "mem" in reg.names  # alias fuer memory

    def test_discover_skips_host_conflict_copies(self, tmp_path, monkeypatch, capsys):
        from core.registry import HandlerRegistry

        for filename in (
            "normal-handler.py",
            "upgrade.py",
            "upgrade-WORKSTATION-LG.py",
            "upgrade-ASUS-GEI-2.py",
        ):
            (tmp_path / filename).write_text("", encoding="utf-8")

        loaded = []
        reg = HandlerRegistry()

        def fake_load(py_file, hub_dir):
            loaded.append(py_file.name)
            return 1

        monkeypatch.setattr(reg, "_load_handlers_from_file", fake_load)

        assert reg.discover(tmp_path) == 2
        assert loaded == ["normal-handler.py", "upgrade.py"]
        warnings = capsys.readouterr().out
        assert "upgrade-WORKSTATION-LG.py" in warnings
        assert "upgrade-ASUS-GEI-2.py" in warnings
        assert "upgrade.py" in warnings

    def test_suggest(self):
        from core.registry import HandlerRegistry
        reg = HandlerRegistry()
        reg.discover(SYSTEM_ROOT / "hub")
        suggestions = reg.suggest("taks")  # Tippfehler
        assert "task" in suggestions

    def test_levenshtein(self):
        from core.registry import HandlerRegistry
        assert HandlerRegistry._levenshtein("task", "task") == 0
        assert HandlerRegistry._levenshtein("task", "tast") == 1
        assert HandlerRegistry._levenshtein("task", "test") == 2


# ═══════════════════════════════════════════════════════════════
# core/adapter.py Tests
# ═══════════════════════════════════════════════════════════════

class TestHandlerAdapter:
    def test_tuple_to_result(self):
        from core.adapter import HandlerAdapter
        from core.base import Result, ParsedArgs

        class FakeHandler:
            profile_name = "fake"
            def get_operations(self):
                return {}
            def handle(self, operation, args, dry_run=False):
                return (True, f"OK: {operation}")

        adapter = HandlerAdapter(FakeHandler())
        result = adapter.handle("test", ParsedArgs(positional=["arg1"]))
        assert isinstance(result, Result)
        assert result.success is True
        assert "OK: test" in result.message

    def test_profile_name_proxy(self):
        from core.adapter import HandlerAdapter

        class FakeHandler:
            profile_name = "fake"
            def get_operations(self): return {}
            def handle(self, op, args, dry_run=False): return (True, "")

        adapter = HandlerAdapter(FakeHandler())
        assert adapter.profile_name == "fake"


# ═══════════════════════════════════════════════════════════════
# core/app.py Tests
# ═══════════════════════════════════════════════════════════════

class TestApp:
    def test_create(self):
        from core.app import App
        app = App(SYSTEM_ROOT)
        assert app.base_path == SYSTEM_ROOT

    def test_db_lazy(self):
        from core.app import App
        app = App(SYSTEM_ROOT)
        # DB sollte lazy sein
        assert app._db is None
        db = app.db
        assert app._db is not None

    def test_registry_lazy(self):
        from core.app import App
        app = App(SYSTEM_ROOT)
        assert app._registry is None
        reg = app.registry
        assert app._registry is not None
        assert reg.count > 0

    def test_paths_does_not_prepend_hub_directory(self, monkeypatch):
        from core.app import App

        hub_dir = str(SYSTEM_ROOT / "hub")
        monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != hub_dir])

        app = App(SYSTEM_ROOT)
        paths = app.paths

        assert paths.BACH_ROOT
        assert hub_dir not in sys.path

    def test_get_handler(self):
        from core.app import App
        app = App(SYSTEM_ROOT)
        handler = app.get_handler("task")
        assert handler is not None

    def test_execute(self):
        from core.app import App
        app = App(SYSTEM_ROOT)
        success, message = app.execute("task", "list")
        assert success is True
        assert len(message) > 0

    def test_execute_forwards_dry_run_flag(self):
        from core.app import App

        called = {}

        class DummyHandler:
            def handle(self, operation, args, dry_run=False):
                called["operation"] = operation
                called["args"] = list(args)
                called["dry_run"] = dry_run
                return True, "ok"

        app = App(SYSTEM_ROOT)
        app.get_handler = lambda _name: DummyHandler()

        success, message = app.execute("dummy", "run", ["target", "--dry-run"])

        assert success is True
        assert message == "ok"
        assert called == {
            "operation": "run",
            "args": ["target", "--dry-run"],
            "dry_run": True,
        }

    def test_execute_does_not_swallow_internal_type_error(self):
        from core.app import App

        class DummyHandler:
            def handle(self, operation, args, dry_run=False):
                raise TypeError("inner boom")

        app = App(SYSTEM_ROOT)
        app.get_handler = lambda _name: DummyHandler()

        success, message = app.execute("dummy", "run", ["target", "--dry-run"])

        assert success is False
        assert "inner boom" in message


class TestBachCliDispatch:
    def _dummy_app(self, called, handler_name="dummy"):
        class DummyHandler:
            def handle(self, operation, args, dry_run=False):
                called["operation"] = operation
                called["args"] = list(args)
                called["dry_run"] = dry_run
                return True, "[DRY-RUN] ok" if dry_run else "ok"

        class DummyRegistry:
            def suggest(self, _command):
                return []

        class DummyApp:
            registry = DummyRegistry()

            def get_handler(self, name):
                return DummyHandler() if name == handler_name else None

        return DummyApp()

    def test_subcommand_handler_gets_dry_run_flag(self, monkeypatch, capsys):
        import bach as bach_cli

        called = {}
        monkeypatch.setattr(bach_cli, "_get_app", lambda: self._dummy_app(called))
        monkeypatch.setattr(bach_cli, "_run_injectors", lambda *args, **kwargs: None)
        monkeypatch.setattr(bach_cli, "cmd", lambda *args, **kwargs: None)
        monkeypatch.setenv("BACH_USE_LAUNCHER", "0")
        monkeypatch.setattr(sys, "argv", ["bach.py", "dummy", "run", "target", "--dry-run"])

        rc = bach_cli.main()

        assert rc == 0
        assert called == {
            "operation": "run",
            "args": ["target", "--dry-run"],
            "dry_run": True,
        }
        assert "[DRY-RUN] ok" in capsys.readouterr().out

    def test_profile_handler_gets_dry_run_flag(self, monkeypatch, capsys):
        import bach as bach_cli

        called = {}
        monkeypatch.setattr(bach_cli, "_get_app", lambda: self._dummy_app(called))
        monkeypatch.setattr(bach_cli, "_run_injectors", lambda *args, **kwargs: None)
        monkeypatch.setattr(bach_cli, "cmd", lambda *args, **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["bach.py", "--dummy", "run", "target", "--dry-run"])

        rc = bach_cli.main()

        assert rc == 0
        assert called == {
            "operation": "run",
            "args": ["target", "--dry-run"],
            "dry_run": True,
        }
        assert "[DRY-RUN] ok" in capsys.readouterr().out

    def test_startup_profile_preserves_quick_operation(self, monkeypatch, capsys):
        import bach as bach_cli

        called = {}
        monkeypatch.setattr(bach_cli, "_get_app", lambda: self._dummy_app(called, "startup"))
        monkeypatch.setattr(bach_cli, "_run_injectors", lambda *args, **kwargs: None)
        monkeypatch.setattr(bach_cli, "cmd", lambda *args, **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["bach.py", "--startup", "quick", "--mode=silent", "--partner=Codex"])

        rc = bach_cli.main()

        assert rc == 0
        assert called == {
            "operation": "quick",
            "args": ["--mode=silent", "--partner=Codex"],
            "dry_run": False,
        }
        assert "ok" in capsys.readouterr().out

    def test_startup_profile_keeps_free_positional_arg_as_handler_arg(self, monkeypatch, capsys):
        import bach as bach_cli

        called = {}
        monkeypatch.setattr(bach_cli, "_get_app", lambda: self._dummy_app(called, "startup"))
        monkeypatch.setattr(bach_cli, "_run_injectors", lambda *args, **kwargs: None)
        monkeypatch.setattr(bach_cli, "cmd", lambda *args, **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["bach.py", "--startup", "Codex", "--mode=silent"])

        rc = bach_cli.main()

        assert rc == 0
        assert called == {
            "operation": "",
            "args": ["Codex", "--mode=silent"],
            "dry_run": False,
        }
        assert "ok" in capsys.readouterr().out

    def test_shutdown_profile_preserves_quick_operation(self, monkeypatch, capsys):
        import bach as bach_cli

        called = {}
        monkeypatch.setattr(bach_cli, "_get_app", lambda: self._dummy_app(called, "shutdown"))
        monkeypatch.setattr(bach_cli, "_run_injectors", lambda *args, **kwargs: None)
        monkeypatch.setattr(bach_cli, "cmd", lambda *args, **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["bach.py", "--shutdown", "quick", "Pause", "--partner=Codex"])

        rc = bach_cli.main()

        assert rc == 0
        assert called == {
            "operation": "quick",
            "args": ["Pause", "--partner=Codex"],
            "dry_run": False,
        }
        assert "ok" in capsys.readouterr().out

    def test_partner_runtime_commands_route_to_partner_handler(self, monkeypatch, capsys):
        import bach as bach_cli

        called = {}

        class DummyHandler:
            def handle(self, operation, args, dry_run=False):
                called["operation"] = operation
                called["args"] = list(args)
                called["dry_run"] = dry_run
                return True, "[DRY-RUN] partner ok" if dry_run else "partner ok"

        class DummyApp:
            def get_handler(self, name):
                return DummyHandler() if name == "partner" else None

        monkeypatch.setattr(bach_cli, "_get_app", lambda: DummyApp())

        rc = bach_cli._handle_partner("delegate", ["Smoke", "--dry-run"])

        assert rc == 0
        assert called == {
            "operation": "delegate",
            "args": ["Smoke", "--dry-run"],
            "dry_run": True,
        }
        assert "[DRY-RUN] partner ok" in capsys.readouterr().out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
