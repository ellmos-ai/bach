# -*- coding: utf-8 -*-
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
Database - Connection Management und Migration Runner
=====================================================
Zentrale DB-Verwaltung mit Schema-Datei und Migrationen.
Nutzt bestehende bach.db, fuegt fehlende Tabellen per IF NOT EXISTS hinzu.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional


def dispatch_py_migration(mod, conn, db_path):
    """Ruft den Entry-Point einer .py-Migration auf — gemeinsame Konvention
    fuer core/db.py UND hub/update.py (Review BACH PR #10, Befund 2).

    Unterstuetzt: run_migration(conn) | run(conn) | migrate(db_path) |
    upgrade(db_path) | main(). migrate/upgrade nur bei genau einem
    Pflichtparameter (z. B. migrate_prompts.py braucht drei — das kann kein
    generischer Runner bedienen und MUSS laut scheitern statt still gebucht
    zu werden).
    """
    import inspect

    def _single_required_param(fn) -> bool:
        required = [
            p for p in inspect.signature(fn).parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                           inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        return len(required) == 1

    if hasattr(mod, "run_migration"):
        mod.run_migration(conn)
    elif hasattr(mod, "run"):
        mod.run(conn)
    elif hasattr(mod, "migrate") and _single_required_param(mod.migrate):
        mod.migrate(str(db_path))
    elif hasattr(mod, "upgrade") and _single_required_param(mod.upgrade):
        mod.upgrade(str(db_path))
    elif hasattr(mod, "main"):
        mod.main()
    else:
        raise RuntimeError(
            "Weder run_migration(conn), run(conn), migrate(db_path), "
            "upgrade(db_path) noch main() generisch aufrufbar — Migration "
            "wird NICHT als angewandt gebucht."
        )


class Database:
    """SQLite-Datenbank mit Connection Management und Migrationen."""

    def __init__(self, db_path: Path, schema_dir: Path):
        self.db_path = db_path
        self.schema_dir = schema_dir
        self._ensure_dir()

    def _ensure_dir(self):
        """Stellt sicher, dass DB-Verzeichnis existiert."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        """Context Manager fuer DB-Verbindung mit WAL und FK."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")  # 30 Sekunden in Millisekunden
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list:
        """Fuehrt SQL aus und gibt Ergebnis als list[dict] zurueck."""
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            if sql.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cursor.fetchall()]
            return []

    def execute_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Fuehrt SQL aus und gibt erste Zeile zurueck."""
        results = self.execute(sql, params)
        return results[0] if results else None

    def execute_scalar(self, sql: str, params: tuple = ()):
        """Fuehrt SQL aus und gibt einzelnen Wert zurueck."""
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def execute_write(self, sql: str, params: tuple = ()) -> int:
        """Fuehrt INSERT/UPDATE/DELETE aus, gibt lastrowid zurueck."""
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def is_empty(self) -> bool:
        """True, wenn die DB noch keine Nutzertabellen hat.

        _migrations und sqlite-interne Tabellen zaehlen nicht. Bestands-DBs
        duerfen init_schema() NICHT erneut bekommen: schema.sql enthaelt
        CREATE-Statements ohne IF NOT EXISTS und wuerde dort abbrechen.
        """
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return True
        count = self.execute_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name != '_migrations' AND name NOT LIKE 'sqlite_%'"
        )
        return not count

    def init_schema(self):
        """Erstellt die Tabellen aus schema.sql (nur fuer frische DBs gedacht).

        schema.sql enthaelt CREATE-Statements ohne IF NOT EXISTS — auf
        Bestands-DBs vorher is_empty() pruefen (siehe core/app.py).
        """
        is_new_db = not self.db_path.exists() or self.db_path.stat().st_size == 0
        schema_file = self.schema_dir / "schema.sql"
        if not schema_file.exists():
            return

        with self.connect() as conn:
            conn.executescript(schema_file.read_text(encoding="utf-8"))
            if is_new_db:
                self._apply_release_language_seed(conn)

    def _release_language_seed_candidates(self) -> list[Path]:
        """Moegliche Pfade fuer generierte Sprach-Seed-Dateien."""
        return [
            self.schema_dir.parent.parent / "exports" / "translations" / "languages_seed.release.sql",
            self.schema_dir.parent / "exports" / "translations" / "languages_seed.release.sql",
            self.schema_dir / "exports" / "translations" / "languages_seed.release.sql",
        ]

    def _apply_release_language_seed(self, conn: sqlite3.Connection):
        """Importiert generierte Sprach-Seeds bei frischer DB-Erstellung."""
        for seed_file in self._release_language_seed_candidates():
            if not seed_file.exists():
                continue
            conn.executescript(seed_file.read_text(encoding="utf-8"))
            break

    def baseline_migrations(self):
        """Bucht alle vorhandenen Migrationsdateien als angewandt — ohne Ausfuehrung.

        Fuer frische DBs direkt nach init_schema(): schema.sql traegt bereits den
        Endstand, die historischen Migrationen duerfen dort nie laufen (ALTER
        TABLE auf schon vorhandene Spalten wuerde krachen). Entspricht dem
        ueblichen "fake initial"-Muster.
        """
        migrations_dir = self.schema_dir / "migrations"
        if not migrations_dir.exists():
            return
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            for mig_file in sorted(migrations_dir.glob("*")):
                if mig_file.suffix not in (".sql", ".py") or mig_file.name.startswith("_"):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (filename, applied_at) VALUES (?, ?)",
                    (mig_file.name, datetime.now().isoformat())
                )

    def migration_backlog(self) -> list:
        """Ausstehende Migrationen, die AELTER sind als der juengste gebuchte
        Stand — das Kennzeichen einer Bestands-DB ohne Baseline.

        Eine solche DB darf der App-Start NICHT automatisch scharf migrieren
        (Review PR #10, Befund 1 — empirisch belegt am Produktiv-DB-Vorfall
        2026-09-01): der Rueckstand wird kontrolliert per
        `bach update migrations baseline [--through NNN]` gebucht. Regulaer
        nachgezogene DBs haben nur Migrationen NEUER als der letzte gebuchte
        nummerierte Stand als pending — die laufen weiterhin automatisch.
        """
        migrations_dir = self.schema_dir / "migrations"
        if not migrations_dir.exists():
            return []
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            applied = {row[0] for row in
                       conn.execute("SELECT filename FROM _migrations").fetchall()}

        def _num_prefix(name: str):
            prefix = name.split("_", 1)[0]
            return int(prefix) if prefix.isdigit() else None

        applied_nums = [n for n in (_num_prefix(a) for a in applied) if n is not None]
        max_applied = max(applied_nums) if applied_nums else -1

        backlog = []
        for mig_file in sorted(migrations_dir.glob("*")):
            if mig_file.suffix not in (".sql", ".py") or mig_file.name.startswith("_"):
                continue
            if mig_file.name in applied:
                continue
            num = _num_prefix(mig_file.name)
            if num is None:
                # nicht-nummerierte pending zaehlen als Rueckstand, sobald die
                # DB ueberhaupt schon nummerierte Buchungen hat (Bestands-DB)
                if max_applied >= 0:
                    backlog.append(mig_file.name)
            elif num <= max_applied:
                backlog.append(mig_file.name)
            elif max_applied < 0:
                # nicht-leere DB ganz ohne Buchungen: ALLES ist Rueckstand
                backlog.append(mig_file.name)
        return backlog

    def run_migrations(self):
        """Fuehrt ausstehende Migrationen aus <schema_dir>/migrations/ aus.

        Tracking: Tabelle _migrations (Dateiname inkl. Suffix). Jede Migration
        laeuft in eigener Verbindung; beim ersten Fehler stoppt die Kette
        (Reihenfolge!), bereits gebuchte bleiben gebucht, die App darf trotzdem
        starten (fail-soft mit lauter Warnung — Bestands-DBs holen Rueckstand
        kontrolliert per `bach update migrations baseline` auf).

        Returns:
            (applied: list[str], error: str | None)
        """
        migrations_dir = self.schema_dir / "migrations"
        applied_now: list[str] = []
        if not migrations_dir.exists():
            return applied_now, None

        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            applied = {row[0] for row in
                       conn.execute("SELECT filename FROM _migrations").fetchall()}

        for mig_file in sorted(migrations_dir.glob("*")):
            if mig_file.suffix not in (".sql", ".py") or mig_file.name.startswith("_"):
                continue
            if mig_file.name in applied:
                continue
            print(f"  Migration: {mig_file.name}")
            try:
                with self.connect() as conn:
                    if mig_file.suffix == ".sql":
                        # Hinweis (Review PR #10, Befund 4): executescript
                        # committed implizit pro Script — ein mitten im Script
                        # scheiterndes Mehr-Statement-SQL hinterlaesst
                        # Teilzustand und bleibt ungebucht. Bewusste Grenze,
                        # Ticket im Repo-TODO; die Fehlermeldung nennt die Datei.
                        conn.executescript(mig_file.read_text(encoding="utf-8"))
                    else:
                        import importlib.util
                        spec = importlib.util.spec_from_file_location(f"mig_{mig_file.stem}", mig_file)
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        dispatch_py_migration(mod, conn, self.db_path)
                    conn.execute(
                        "INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
                        (mig_file.name, datetime.now().isoformat())
                    )
            except Exception as e:
                error = (
                    f"Migration {mig_file.name} fehlgeschlagen: {e} — Kette gestoppt. "
                    f"Bestands-DB? Rueckstand per 'bach update migrations baseline "
                    f"[--through NNN]' buchen, dann neu starten."
                )
                print(f"  [!!] {error}")
                return applied_now, error
            applied_now.append(mig_file.name)
        return applied_now, None

    def table_exists(self, name: str) -> bool:
        """Prueft ob Tabelle existiert."""
        result = self.execute_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (name,)
        )
        return result > 0

    def tables(self) -> list:
        """Gibt alle Tabellennamen zurueck."""
        rows = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]

    def row_count(self, table: str) -> int:
        """Gibt Zeilenanzahl einer Tabelle zurueck."""
        return self.execute_scalar(f"SELECT COUNT(*) FROM [{table}]") or 0


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    """
    Erstellt SQLite-Connection mit optimalen Einstellungen.

    Fixes BUG-HQ5-B-001: Database Lock durch fehlende Timeouts.

    Args:
        db_path: Pfad zur Datenbank

    Returns:
        Konfigurierte SQLite-Connection

    Settings:
        - 30s Connection-Timeout (für OneDrive-Sync-Konflikte)
        - WAL-Mode (Write-Ahead Logging)
        - Foreign Keys aktiviert
        - 30s Busy-Timeout (für concurrent access)
    """
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # 30 Sekunden
    return conn
