#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Setup Script — Drei-Säulen-Modell (Säule 1: SCRIPT)
=========================================================

Automatisierte Erstinstallation von BACH.
Führt deterministische Schritte aus die kein LLM brauchen.

Schritte (S1-S7):
  S1: Python-Pakete installieren (requirements.txt)
  S2: bach.db initialisieren (127 Tabellen via schema.sql)
  S3: Migrations ausführen (11 SQL-Migrations)
  S4: Pflichtverzeichnisse anlegen
  S5: user/secrets/secrets.json Skeleton
  S6: system_identity in DB
  S7: user_config.json Default

Extras (optional):
  S8-S12: GUI, PDF, Docs, Voice, Analytics via bach[extra]
  S13: Domain-Schemas (steuer, agents)

Referenz: SQ015, ENT-28, INSTALL_KONZEPT.md
Datum: 2026-02-19
"""

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_PACKAGING_COMMANDS = {
    "egg_info",
    "dist_info",
    "editable_wheel",
    "bdist_wheel",
    "sdist",
    "develop",
}


def _read_requirements(requirements_path: Path) -> list[str]:
    """Liest requirements.txt fuer setuptools packaging."""
    if not requirements_path.exists():
        return []

    requirements = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if line:
            requirements.append(line)
    return requirements


def _run_packaging_setup() -> None:
    """Bedient setuptools-Buildhooks fuer pip install -e ."""
    from setuptools import setup as setuptools_setup

    root = Path(__file__).parent
    readme_path = root / "README.md"
    long_description = ""
    if readme_path.exists():
        long_description = readme_path.read_text(encoding="utf-8")

    setuptools_setup(
        name="ellmos-bach",
        version="3.9.1",
        description="BACH root-level editable install shim",
        long_description=long_description,
        long_description_content_type="text/markdown",
        python_requires=">=3.10",
        license="MIT",
        py_modules=["bach", "bach_api"],
        install_requires=_read_requirements(root / "requirements.txt"),
        entry_points={"console_scripts": ["bach=bach:main"]},
    )


if any(arg in _PACKAGING_COMMANDS for arg in sys.argv[1:]):
    _run_packaging_setup()
    raise SystemExit(0)


class BACHSetup:
    """BACH Installation Manager."""

    def __init__(self, bach_root: Path = None):
        """
        Args:
            bach_root: BACH Root-Verzeichnis (default: Script-Parent)
        """
        if bach_root is None:
            # Script liegt im BACH-Root
            bach_root = Path(__file__).parent

        self.root = Path(bach_root)
        self.system = self.root / "system"
        self.data = self.system / "data"
        self.db_path = self.data / "bach.db"
        self.schema_dir = self.data / "schema"
        self.sql_dir = self.data / "sql"
        self.user_dir = self.root / "user"

    def check(self) -> bool:
        """Prueft ob BACH korrekt installiert ist. Exit-Code 0=OK, 2=Probleme."""
        checks = []
        all_ok = True

        # DB
        if self.db_path.exists():
            conn = sqlite3.connect(str(self.db_path))
            count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            conn.close()
            checks.append(f"[OK] bach.db ({count} Tabellen)")
        else:
            checks.append("[!!] bach.db fehlt")
            all_ok = False

        # Verzeichnisse
        for d in [self.data / "logs", self.user_dir]:
            if d.exists():
                checks.append(f"[OK] {d.name}/")
            else:
                checks.append(f"[!!] {d.name}/ fehlt")
                all_ok = False

        # requirements
        req = self.root / "requirements.txt"
        checks.append(f"[OK] requirements.txt" if req.exists() else "[!!] requirements.txt fehlt")

        print("\n".join(checks))
        print(f"\nStatus: {'OK' if all_ok else 'Probleme gefunden'}")
        return all_ok

    def run(self, skip_pip: bool = False, extras: list = None, quiet: bool = False):
        """Führt komplettes Setup aus."""
        if not quiet:
            print("=" * 70)
            print("  BACH Setup — Drei-Säulen-Modell")
            print("=" * 70)
        print(f"BACH Root: {self.root}")
        print(f"System:    {self.system}")
        print(f"DB:        {self.db_path}")
        print()

        steps = [
            ("S1", "Python-Pakete installieren", self._step_s1_pip_install, not skip_pip),
            ("S2", "bach.db initialisieren", self._step_s2_db_init, True),
            ("S3", "Migrations ausführen", self._step_s3_migrations, True),
            ("S4", "Pflichtverzeichnisse anlegen", self._step_s4_directories, True),
            ("S5", "secrets.json Skeleton", self._step_s5_secrets_skeleton, True),
            ("S6", "system_identity in DB", self._step_s6_system_identity, True),
            ("S7", "user_config.json Default", self._step_s7_user_config, True),
            ("S8", "MEMORY.md mit Silo-Index generieren", self._step_s8_memory_md, True),
        ]

        success_count = 0
        for step_id, step_name, step_func, enabled in steps:
            if not enabled:
                print(f"[{step_id}] {step_name} → ÜBERSPRUNGEN")
                continue

            print(f"[{step_id}] {step_name}...")
            try:
                step_func(extras if step_id == "S1" else None)
                print(f"     ✓ OK")
                success_count += 1
            except Exception as e:
                print(f"     ✗ FEHLER: {e}")
                return False

        print()
        print("=" * 70)
        print(f"Setup abgeschlossen: {success_count}/{len([s for s in steps if s[3]])} Schritte erfolgreich")
        print("=" * 70)
        print()
        print("Nächste Schritte:")
        print("  1. Starte BACH: cd system && python bach.py --startup")
        print("  2. LLM arbeitet Onboarding-Tasks ab (Säule 2)")
        print("  3. Optional: API-Keys eintragen, Connectors einrichten (Säule 3)")
        print()

        return True

    def _step_s1_pip_install(self, extras: list = None):
        """S1: Python-Pakete installieren."""
        requirements = self.root / "requirements.txt"

        if not requirements.exists():
            print(f"     [SKIP] requirements.txt nicht gefunden")
            return

        # Base requirements
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
            check=True,
            capture_output=True
        )

        # Extras (falls angegeben)
        if extras:
            extras_str = ",".join(extras)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", f"bach[{extras_str}]"],
                check=True,
                capture_output=True
            )

    def _step_s2_db_init(self, _):
        """S2: bach.db initialisieren (127 Tabellen via schema.sql)."""
        schema_sql = self.schema_dir / "schema.sql"

        if not schema_sql.exists():
            raise FileNotFoundError(f"schema.sql nicht gefunden: {schema_sql}")

        # DB anlegen falls noch nicht vorhanden
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        script = schema_sql.read_text(encoding='utf-8')
        conn.executescript(script)
        conn.commit()
        conn.close()

        print(f"     DB initialisiert: {self.db_path}")

    def _step_s3_migrations(self, _):
        """S3: Migrations ausfuehren (SQL + Python)."""
        migrations_dir = self.schema_dir / "migrations"

        if not migrations_dir.exists():
            print(f"     [SKIP] Kein migrations-Ordner gefunden")
            return

        # SQL-Migrations
        sql_files = sorted(migrations_dir.glob("*.sql"))
        py_files = sorted(migrations_dir.glob("*.py"))
        all_files = sorted(sql_files + py_files, key=lambda f: f.stem)

        if not all_files:
            print(f"     [SKIP] Keine Migrations gefunden")
            return

        conn = sqlite3.connect(str(self.db_path))

        for migration_file in all_files:
            try:
                if migration_file.suffix == ".sql":
                    script = migration_file.read_text(encoding='utf-8')
                    conn.executescript(script)
                elif migration_file.suffix == ".py":
                    # Python-Migration: Modul laden und run(conn) aufrufen
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        f"migration_{migration_file.stem}", migration_file
                    )
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, 'run'):
                        mod.run(conn)
                    elif hasattr(mod, 'migrate'):
                        mod.migrate(conn)
                print(f"     Migration angewendet: {migration_file.name}")
            except Exception as e:
                print(f"     [WARN] Migration {migration_file.name} fehlgeschlagen: {e}")

        conn.commit()
        conn.close()

    def _step_s4_directories(self, _):
        """S4: Pflichtverzeichnisse anlegen."""
        required_dirs = [
            self.data / "logs",
            self.data / "_backups",
            self.data / "messages",
            self.data / "sessions",
            self.data / "dist",
            self.user_dir / "secrets",
        ]

        for d in required_dirs:
            d.mkdir(parents=True, exist_ok=True)

        print(f"     {len(required_dirs)} Verzeichnisse angelegt")

    def _step_s5_secrets_skeleton(self, _):
        """S5: user/secrets/secrets.json Skeleton."""
        secrets_file = self.user_dir / "secrets" / "secrets.json"

        if secrets_file.exists():
            print(f"     [SKIP] secrets.json existiert bereits")
            return

        secrets_file.parent.mkdir(parents=True, exist_ok=True)
        secrets_file.write_text(
            json.dumps({}, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _step_s6_system_identity(self, _):
        """S6: system_identity in DB."""
        conn = sqlite3.connect(str(self.db_path))

        # Prüfen ob identity bereits existiert
        cursor = conn.execute("SELECT COUNT(*) FROM instance_identity")
        if cursor.fetchone()[0] > 0:
            print(f"     [SKIP] system_identity existiert bereits")
            conn.close()
            return

        instance_id = f"bach-{datetime.now().strftime('%Y-%m-%d')}-{secrets.token_hex(2)}"
        now = datetime.now().isoformat()

        conn.execute("""
            INSERT INTO instance_identity (
                instance_id, instance_name, created, seal_status
            ) VALUES (?, ?, ?, ?)
        """, (instance_id, "BACH-Instanz", now, "intact"))

        conn.commit()
        conn.close()

        print(f"     Instance ID: {instance_id}")

    def _step_s7_user_config(self, _):
        """S7: user_config.json Default."""
        config_file = self.system / "config" / "user_config.json"

        if config_file.exists():
            print(f"     [SKIP] user_config.json existiert bereits")
            return

        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps({"startup_mode": "text"}, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _step_s8_memory_md(self, _):
        """S8: MEMORY.md mit Silo-Index generieren (SQ039/SQ065)."""
        memory_md = self.root / "MEMORY.md"

        if memory_md.exists():
            print(f"     [SKIP] MEMORY.md existiert bereits")
            return

        # Import memory_sync dynamisch (vermeidet zirkuläre Imports)
        sys.path.insert(0, str(self.system / "tools"))
        try:
            from memory_sync import MemorySync
            sync = MemorySync(self.root)
            success, msg = sync.generate()
            if success:
                print(f"     {msg}")
            else:
                print(f"     [WARN] Konnte MEMORY.md nicht generieren: {msg}")
        except ImportError as e:
            print(f"     [WARN] memory_sync.py nicht gefunden, erstelle Template")
            # Fallback: Minimales Template
            memory_md.write_text(
                "# BACH Memory\n\n## Manual Notes\n\n(Schreibe hier deine Notizen)\n",
                encoding='utf-8'
            )


def main():
    parser = argparse.ArgumentParser(
        description="BACH Setup — Automatisierte Installation (Säule 1)"
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Überspringe pip install (falls Pakete bereits installiert)"
    )
    parser.add_argument(
        "--extras",
        nargs="+",
        choices=["gui", "pdf", "docs", "voice", "analytics"],
        help="Optionale Extra-Pakete installieren"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Non-interactive Modus fuer CI/CD (Standard-Werte, keine Prompts)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimale Ausgabe (nur Fehler)"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="install",
        choices=["install", "check"],
        help="Setup-Befehl (default: install). 'check' prueft ob alles installiert ist."
    )

    args = parser.parse_args()

    setup = BACHSetup()

    if args.command == "check":
        ok = setup.check()
        sys.exit(0 if ok else 2)
    elif args.command == "install":
        success = setup.run(
            skip_pip=args.skip_pip,
            extras=args.extras,
            quiet=args.quiet
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
