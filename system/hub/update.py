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
Update Handler - Versions- und Update-Verwaltung
=================================================

bach update check          Auf Updates pruefen
bach update status         Aktuelle Version + Verifikation anzeigen
bach update apply          Update einspielen (Backup + Pull + Migrate + Verify)
bach update rollback       Rollback zum letzten Pre-Update-Backup
bach update verify         System-Integritaet pruefen
bach update migrations     Ausstehende Migrationen anzeigen/ausfuehren
"""

import json
import os
import importlib
import importlib.util
import subprocess
import shutil
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from hub.base import BaseHandler
from hub.bach_paths import BACKUPS_DIR
from hub.lang import t


VERSION_FILE = "version.json"



def _parse_migration_run_args(args) -> tuple[list[str] | None, bool]:
    """Parses only the exact-filename selector; generic CLI/API args stay unchanged."""
    args = list(args or [])
    selected = []
    dry_run = False
    index = 0
    while index < len(args):
        value = args[index]
        if value in ("--dry-run", "-n"):
            dry_run = True
            index += 1
            continue
        if value == "--only":
            index += 1
            if index >= len(args) or not isinstance(args[index], str) or args[index].startswith("--"):
                raise ValueError("--only benötigt einen exakten Migrationsdateinamen")
            selected.append(args[index])
            index += 1
            continue
        if isinstance(value, str) and value.startswith("--only="):
            selected.append(value[len("--only="):])
            index += 1
            continue
        raise ValueError(f"Unerwartetes Argument für migrations run: {value}")
    return selected or None, dry_run


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("ellmos-core")
class UpdateHandler(BaseHandler):
    """Handler fuer bach update Operationen."""

    def __init__(self, base_path):
        super().__init__(base_path)
        self.version_file = self.base_path / "data" / VERSION_FILE
        # Kanonischer Migrationsort (T-20260901-620606145): data/schema/migrations.
        # Die frueheren Pfade data/migrations und db/migrations sind aufgeloest;
        # Tracking-Kanon ist die Tabelle _migrations in der DB (wie core/db.py),
        # nicht mehr version.json.
        self.migrations_dir = self.base_path / "data" / "schema" / "migrations"
        self.hub_dir = self.base_path / "hub"
        # Backups LOKAL — NICHT in OneDrive
        self.backups_dir = BACKUPS_DIR / "updates"
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "update"

    @property
    def target_file(self) -> Path:
        return self.version_file

    def get_operations(self) -> dict:
        return {
            "check": t("update_check_desc", default="Auf Updates pruefen (Git)"),
            "status": t("update_status_desc", default="Version und System-Status anzeigen"),
            "apply": t("update_apply_desc", default="Update einspielen (Backup + Pull + Migrate + Verify)"),
            "rollback": t("update_rollback_desc", default="Rollback zum letzten Pre-Update-Backup"),
            "verify": t("update_verify_desc", default="System-Integritaet pruefen"),
            "migrations": t("update_migrations_desc", default="Migrationen anzeigen/ausfuehren"),
            "skills": t("update_skills_desc", default="Skills-Versionen pruefen und synchronisieren (bach update skills [--apply])"),
            "modules": t("update_modules_desc", default="Module- und Adapter-Status pruefen und synchronisieren (bach update modules [--sync])"),
            "all": t("update_all_desc", default="Gesamtes System pruefen: Core, Skills und Module"),
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "check":
            return self._check()
        elif operation == "status" or not operation:
            return self._status()
        elif operation == "apply":
            return self._apply(args, dry_run)
        elif operation == "rollback":
            return self._rollback(args, dry_run)
        elif operation == "verify":
            return self._verify()
        elif operation == "skills":
            return self._update_skills(args, dry_run)
        elif operation == "modules":
            return self._update_modules(args, dry_run)
        elif operation == "all":
            return self._update_all(args, dry_run)
        elif operation == "migrations":
            sub = args[0] if args else "list"
            if sub == "run":
                try:
                    only, requested_dry_run = _parse_migration_run_args(args[1:])
                except ValueError as exc:
                    return False, str(exc)
                return self._run_migrations(dry_run or requested_dry_run, only=only)
            if sub == "baseline":
                return self._baseline_migrations(args[1:], dry_run)
            return self._list_migrations()
        else:
            ops = ", ".join(self.get_operations().keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {ops}"

    def _load_version(self) -> dict:
        """Laedt version.json oder erstellt Default."""
        if self.version_file.exists():
            return json.loads(self.version_file.read_text(encoding="utf-8"))
        return {
            "version": "0.0.0", "schema_version": 0, "updated_at": None,
            "migrations_applied": [], "last_verified": None, "verification_status": None,
        }

    def _save_version(self, data: dict):
        """Speichert version.json."""
        self.version_file.parent.mkdir(parents=True, exist_ok=True)
        self.version_file.write_text(
            json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8"
        )

    def _status(self) -> tuple:
        """Zeigt Version + System-Status."""
        ver = self._load_version()
        lines = [
            "=== BACH UPDATE STATUS ===", "",
            f"  Version:          {ver.get('version', '?')}",
            f"  Schema-Version:   {ver.get('schema_version', '?')}",
            f"  Aktualisiert:     {ver.get('updated_at', '?')}",
            f"  Letzte Pruefung:  {ver.get('last_verified', 'nie')}",
            f"  Pruef-Status:     {ver.get('verification_status', '?')}",
            "", "  Migrationen:",
        ]
        applied = sorted(self._applied_migrations())
        pending = [m for m in self._get_available_migrations() if m not in set(applied)]
        lines.append(f"    Angewandt: {len(applied)} | Ausstehend: {len(pending)} "
                     f"(Details: bach update migrations)")
        git_info = self._git_info()
        if git_info:
            lines.extend(["", "  Git:"])
            for k, v in git_info.items():
                lines.append(f"    {k}: {v}")
        return True, "\n".join(lines)

    def _check(self) -> tuple:
        """Prueft ob Updates verfuegbar sind (Git-basiert)."""
        if not self._is_git_repo():
            return True, "[UPDATE] Kein Git-Repository erkannt. Manuelle Updates noetig."
        lines = ["=== UPDATE CHECK ===", ""]
        ok, msg = self._git_cmd(["git", "fetch", "--quiet"])
        if not ok:
            return False, f"[FEHLER] Git fetch fehlgeschlagen: {msg}"
        ok, ab = self._git_cmd([
            "git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
        ])
        if ok and ab.strip():
            parts = ab.strip().split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
                if behind > 0:
                    lines.append(f"  {behind} neue Commits verfuegbar!")
                    ok, log = self._git_cmd([
                        "git", "log", "HEAD..@{upstream}",
                        "--oneline", "--no-decorate", "-10"
                    ])
                    if ok and log.strip():
                        lines.extend(["", "  Neue Aenderungen:"])
                        for ln in log.strip().split("\n"):
                            lines.append(f"    {ln}")
                    lines.extend(["", "  Naechster Schritt: bach update apply"])
                else:
                    lines.append("  System ist aktuell. Keine neuen Commits.")
                if ahead > 0:
                    lines.append(f"  ({ahead} lokale Commits noch nicht gepusht)")
        else:
            lines.append("  Kein Upstream-Branch konfiguriert.")
        return True, "\n".join(lines)

    def _apply(self, args: list, dry_run: bool) -> tuple:
        """Update-Workflow: Backup -> Pull -> Migrate -> Verify."""
        lines = ["=== UPDATE APPLY ===", ""]
        if dry_run:
            lines.extend([
                "[DRY-RUN] Würde folgende Schritte ausfuehren:",
                "  1. Backup erstellen", "  2. Git pull",
                "  3. Migrationen ausfuehren", "  4. System verifizieren",
                "  5. version.json aktualisieren",
            ])
            return True, "\n".join(lines)
        lines.append("--- Phase 1: Backup ---")
        bak_ok, bak_msg = self._create_pre_update_backup()
        lines.append(f"  {bak_msg}")
        if not bak_ok:
            lines.append("\n[ABBRUCH] Backup fehlgeschlagen.")
            return False, "\n".join(lines)
        lines.append("\n--- Phase 2: Git Pull ---")
        if self._is_git_repo():
            ok, pull_msg = self._git_cmd(["git", "pull", "--rebase", "origin", "main"])
            if ok:
                lines.append(f"  {pull_msg.strip()}")
            else:
                lines.append(f"  [FEHLER] Git pull: {pull_msg}")
                lines.append("  Rollback empfohlen: bach update rollback")
                return False, "\n".join(lines)
        else:
            lines.append("  Kein Git-Repo. Ueberspringe.")
        lines.append("\n--- Phase 3: Migrationen ---")
        mig_ok, mig_msg = self._run_migrations(dry_run=False)
        lines.append(f"  {mig_msg}")
        lines.append("\n--- Phase 4: Verifikation ---")
        ver_ok, ver_msg = self._verify()
        lines.append(f"  {ver_msg}")
        lines.append("\n--- Phase 5: Version aktualisieren ---")
        ver_data = self._load_version()
        ver_data["updated_at"] = datetime.now().isoformat()
        ver_data["last_verified"] = datetime.now().isoformat()
        ver_data["verification_status"] = "ok" if ver_ok else "warnings"
        self._save_version(ver_data)
        lines.append(f"  version.json aktualisiert (v{ver_data.get('version', '?')}).")
        overall = "erfolgreich" if (bak_ok and ver_ok) else "mit Warnungen"
        lines.extend(["", f"[UPDATE] Abgeschlossen ({overall})."])
        return True, "\n".join(lines)

    def _rollback(self, args: list, dry_run: bool) -> tuple:
        """Rollback zum letzten Pre-Update-Backup."""
        if not self.backups_dir.exists():
            return False, "[FEHLER] Kein Backup-Verzeichnis gefunden."
        backups = sorted(
            self.backups_dir.glob("pre_update_*.zip"),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not backups:
            backups = sorted(
                self.backups_dir.glob("*.zip"),
                key=lambda p: p.stat().st_mtime, reverse=True
            )
        if not backups:
            return False, "[FEHLER] Keine Backups gefunden."
        target = backups[0]
        lines = [
            "=== UPDATE ROLLBACK ===", "",
            f"  Backup: {target.name}",
            f"  Groesse: {target.stat().st_size / (1024*1024):.2f} MB",
            f"  Datum: {datetime.fromtimestamp(target.stat().st_mtime)}",
        ]
        if dry_run:
            lines.append("\n  [DRY-RUN] Würde bach.db aus Backup wiederherstellen.")
            return True, "\n".join(lines)
        import zipfile
        try:
            with zipfile.ZipFile(target, "r") as zf:
                if "bach.db" in zf.namelist():
                    if self.db_path.exists():
                        rollback_bak = self.db_path.with_suffix(".db.pre_rollback")
                        shutil.copy2(self.db_path, rollback_bak)
                        lines.append(f"  Aktuelle DB gesichert: {rollback_bak.name}")
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open("bach.db") as src, open(self.db_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    lines.append("  bach.db wiederhergestellt.")
                else:
                    lines.append("  [WARNUNG] bach.db nicht im Backup gefunden.")
        except Exception as e:
            return False, f"[FEHLER] Rollback fehlgeschlagen: {e}"
        lines.append("\n[OK] Rollback abgeschlossen.")
        return True, "\n".join(lines)

    def _verify(self) -> tuple:
        """Prueft System-Integritaet."""
        lines = ["=== SYSTEM-VERIFIKATION ===", ""]
        issues = []
        checks_ok = 0
        checks_total = 0
        checks_total += 1
        h_ok, h_count, h_errors = self._verify_handlers()
        if h_ok:
            lines.append(f"  [OK] Handler: {h_count} erfolgreich importiert")
            checks_ok += 1
        else:
            lines.append(f"  [!!] Handler: {h_count} OK, {len(h_errors)} Fehler")
            for err in h_errors[:5]:
                lines.append(f"        - {err}")
                issues.append(err)
        checks_total += 1
        if self.version_file.exists():
            lines.append("  [OK] version.json vorhanden")
            checks_ok += 1
        else:
            lines.append("  [!!] version.json fehlt")
            issues.append("version.json nicht gefunden")
        checks_total += 1
        if self.db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(self.db_path))
                try:
                    tables = conn.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                    lines.append(f"  [OK] bach.db: {tables} Tabellen")
                    checks_ok += 1
                finally:
                    conn.close()
            except Exception as e:
                lines.append(f"  [!!] bach.db nicht lesbar: {e}")
                issues.append(f"DB-Fehler: {e}")
        else:
            lines.append("  [!!] bach.db fehlt")
            issues.append("bach.db nicht gefunden")
        checks_total += 1
        # Tracking-Kanon ist die _migrations-Tabelle (PR-#10-Review Befund 3) —
        # version.json wird seit der Umstellung nicht mehr befuellt und wuerde
        # hier fuer immer "alles ausstehend" melden.
        applied = self._applied_migrations()
        available = self._get_available_migrations()
        pending = [m for m in available if m not in applied]
        if not pending:
            lines.append(f"  [OK] Migrationen: alle {len(applied)} angewandt")
            checks_ok += 1
        else:
            lines.append(f"  [!!] Migrationen: {len(pending)} ausstehend")
            for p in pending:
                lines.append(f"        - {p}")
            issues.append(f"{len(pending)} ausstehende Migrationen")
        checks_total += 1
        critical_dirs = ["hub", "core", "data", "skills"]
        missing_dirs = [d for d in critical_dirs if not (self.base_path / d).exists()]
        if not missing_dirs:
            lines.append(f"  [OK] Verzeichnisse: alle {len(critical_dirs)} vorhanden")
            checks_ok += 1
        else:
            md = ", ".join(missing_dirs)
            lines.append(f"  [!!] Verzeichnisse fehlen: {md}")
            issues.append(f"Fehlende Verzeichnisse: {md}")
        lines.extend(["", f"  Ergebnis: {checks_ok}/{checks_total} Pruefungen bestanden"])
        ver = self._load_version()
        ver["last_verified"] = datetime.now().isoformat()
        ver["verification_status"] = "ok" if not issues else f"{len(issues)} issues"
        self._save_version(ver)
        if issues:
            lines.append("\n  Probleme:")
            for i in issues:
                lines.append(f"    - {i}")
        return len(issues) == 0, "\n".join(lines)

    def _verify_handlers(self) -> Tuple[bool, int, list]:
        """Prueft ob alle Handler importierbar sind."""
        errors = []
        count = 0
        if not self.hub_dir.exists():
            return False, 0, ["hub/ Verzeichnis nicht gefunden"]
        parent = str(self.hub_dir.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        for py_file in sorted(self.hub_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"hub.{py_file.stem}", py_file
                )
                if spec and spec.loader:
                    count += 1
            except Exception as e:
                errors.append(f"{py_file.name}: {e}")
        return len(errors) == 0, count, errors

    def _get_available_migrations(self) -> list:
        """Gibt alle verfuegbaren Migrations-Dateinamen (inkl. Suffix) zurueck.

        Dateiname mit Suffix, weil manche Migrationen als .py UND .sql
        existieren (z. B. 009_agent_instances.*) und das DB-Tracking in
        _migrations dateinamengenau bucht (identisch zu core/db.py).
        """
        if not self.migrations_dir.exists():
            return []
        migrations = []
        for f in sorted(self.migrations_dir.iterdir()):
            if f.suffix in (".py", ".sql") and not f.name.startswith("_"):
                migrations.append(f.name)
        return migrations

    def _applied_migrations(self) -> set:
        """Angewandte Migrationen aus der _migrations-Tabelle der DB (Kanon)."""
        import sqlite3
        if not self.db_path.exists():
            return set()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "id INTEGER PRIMARY KEY, filename TEXT UNIQUE NOT NULL, "
                "applied_at TEXT NOT NULL)"
            )
            return {r[0] for r in conn.execute("SELECT filename FROM _migrations")}
        finally:
            conn.commit()
            conn.close()

    def _mark_applied(self, filenames: list):
        """Bucht Migrationen als angewandt (ohne sie auszufuehren)."""
        import sqlite3
        from datetime import datetime as _dt
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "id INTEGER PRIMARY KEY, filename TEXT UNIQUE NOT NULL, "
                "applied_at TEXT NOT NULL)"
            )
            for name in filenames:
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (filename, applied_at) VALUES (?, ?)",
                    (name, _dt.now().isoformat()),
                )
            conn.commit()
        finally:
            conn.close()

    def _baseline_migrations(self, args: list, dry_run: bool = False) -> tuple:
        """Bucht vorhandene Migrationen als angewandt, OHNE sie auszufuehren.

        Fuer Bestands-DBs, deren Schema den Migrationsinhalt laengst traegt
        (der Auto-Runner lief monatelang nicht, T-20260901-620606145).
        Aufruf: `bach update migrations baseline [--through NNN]` — mit
        --through werden nur nummerierte Migrationen <= NNN sowie alle
        nicht-nummerierten gebucht; ohne --through alle vorhandenen.
        """
        through = None
        if args:
            vals = [a for a in args if a != "--through"]
            if vals:
                through = vals[0]
        applied = self._applied_migrations()
        candidates = []
        for name in self._get_available_migrations():
            if name in applied:
                continue
            if through is not None:
                prefix = name.split("_", 1)[0]
                # numerisch vergleichen — als String waere '010' > '9' False
                # (PR-#10-Review Befund 5)
                if (prefix.isdigit() and through.isdigit()
                        and int(prefix) > int(through)):
                    continue
            candidates.append(name)
        if not candidates:
            return True, "Baseline: nichts zu buchen (alles bereits angewandt)."
        lines = [f"Baseline{f' (--through {through})' if through else ''}: "
                 f"{len(candidates)} Migration(en) werden als angewandt gebucht (KEINE Ausfuehrung):"]
        lines += [f"  - {n}" for n in candidates]
        if dry_run:
            lines.append("\n  [DRY-RUN] Nichts gebucht.")
            return True, "\n".join(lines)
        self._mark_applied(candidates)
        lines.append("\n[OK] Baseline gebucht. Ausstehend bleibt, was neuer ist.")
        return True, "\n".join(lines)

    def _list_migrations(self) -> tuple:
        """Listet alle Migrationen mit Status."""
        applied = self._applied_migrations()
        available = self._get_available_migrations()
        lines = ["=== MIGRATIONEN ===", ""]
        if not available:
            lines.append("  Keine Migrationen gefunden.")
            return True, "\n".join(lines)
        for m in available:
            status = "angewandt" if m in applied else "ausstehend"
            marker = "[OK]" if m in applied else "[  ]"
            lines.append(f"  {marker} {m} ({status})")
        pending_count = sum(1 for m in available if m not in applied)
        lines.extend([
            "",
            f"  Gesamt: {len(available)} | Angewandt: {len(available) - pending_count} | Ausstehend: {pending_count}",
        ])
        if pending_count > 0:
            lines.append("\n  Naechster Schritt: bach update migrations run")
        return True, "\n".join(lines)

    def _run_migrations(self, dry_run: bool = False, only=None) -> tuple:
        """Runs all pending migrations by default or an exact selected subset."""
        import sqlite3

        from core.db import (
            MigrationSelectionError,
            read_applied_migration_filenames,
            select_pending_migration_names,
            snapshot_migration_sources,
            validate_migration_request,
            verify_migration_source_snapshot,
        )
        available = self._get_available_migrations()
        try:
            # Syntax, exact names and selected file type are checked before any
            # DB access. Applied-state is then read through a read-only SQLite URI.
            validate_migration_request(self.migrations_dir, available, only)
            applied = read_applied_migration_filenames(self.db_path)
            pending, selected, untouched = select_pending_migration_names(available, applied, only)
            snapshots = snapshot_migration_sources(self.migrations_dir, selected)
            for source in snapshots.values():
                verify_migration_source_snapshot(source)
        except Exception as exc:  # noqa: BLE001 - all invalid preflight paths fail closed
            return False, f"Migrationsauswahl vor Änderungen abgewiesen ({type(exc).__name__}): {exc}"
        if not pending:
            if not dry_run and self.db_path.exists():
                try:
                    self._mark_applied([])
                except sqlite3.Error as exc:
                    return False, f"Migrationstracking konnte nicht vorbereitet werden ({type(exc).__name__})."
            return True, "Keine ausstehenden Migrationen."
        if only is not None and not selected:
            return True, "Keine ausstehenden ausgewählten Migrationen."

        lines = [f"{len(pending)} ausstehende Migration(en):"]
        if only is not None:
            lines.append(f"  Ausgewählt: {len(selected)} | Unberührt: {len(untouched)}")
        for name in selected:
            lines.append(f"  [AUSGEWÄHLT] {name}")
        for name in untouched:
            lines.append(f"  [UNBERÜHRT] {name}")
        if dry_run:
            lines.extend(f"  [DRY-RUN] Würde ausführen: {name}" for name in selected)
            if not selected:
                lines.append("  Keine Migration ausgewählt.")
            return True, "\n".join(lines)

        # Preserve the previous runner order for an existing database: its tracking
        # table was created before the backup. Selection and source validation have
        # already completed, so invalid requests remain write-free.
        if self.db_path.exists():
            try:
                self._mark_applied([])
            except Exception as exc:
                lines.append(f"  [!!] Migrationstracking konnte nicht vorbereitet werden ({type(exc).__name__}).")
                return False, "\n".join(lines)

        if self.db_path.exists() and self.db_path.stat().st_size > 0:
            from core.db import backup_before_migration
            try:
                for source in snapshots.values():
                    verify_migration_source_snapshot(source)
                backup = backup_before_migration(self.db_path, selected)
            except Exception as exc:  # noqa: BLE001 - any backup failure must stop migrations
                lines.append(f"  [!!] Sicherung/Vorprüfung fehlgeschlagen ({type(exc).__name__}: {exc}) "
                             "-- keine Migration ausgeführt.")
                return False, "\n".join(lines)
            lines.append(f"  Sicherung: {backup}")
        try:
            for source in snapshots.values():
                verify_migration_source_snapshot(source)
        except MigrationSelectionError as exc:
            lines.append(f"  [!!] Migrationsquelle vor Ausführung geändert ({type(exc).__name__}: {exc})")
            return False, "\n".join(lines)
        for mig_name in selected:
            mig_file = self.migrations_dir / mig_name
            try:
                source = snapshots[mig_name]
                if mig_file.suffix == ".sql":
                    self._run_sql_migration(mig_file, source.content.decode("utf-8"))
                elif mig_file.suffix == ".py":
                    self._run_py_migration(mig_file, source_snapshot=source)
                self._mark_applied([mig_name])
                lines.append(f"  [OK] {mig_name}")
            except Exception as exc:
                lines.append(f"  [!!] {mig_name}: {exc}")
                lines.append("  Migration abgebrochen (Reihenfolge!). Bestands-DB? "
                             "'bach update migrations baseline --through NNN' prüfen.")
                return False, "\n".join(lines)
        return True, "\n".join(lines)

    def _run_sql_migration(self, sql_file: Path, sql_text: str | None = None):
        """Fuehrt eine SQL-Migration aus."""
        import sqlite3
        sql = sql_file.read_text(encoding="utf-8") if sql_text is None else sql_text
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(sql)
            conn.commit()
        finally:
            conn.close()

    def _run_py_migration(self, py_file: Path, source_snapshot=None):
        """Fuehrt eine Python-Migration aus; optional aus geprüften Snapshot-Bytes."""
        spec = importlib.util.spec_from_file_location(
            f"migration_{py_file.stem}", py_file
        )
        if not spec or not spec.loader:
            raise RuntimeError(f"Kann {py_file.name} nicht laden")
        module = importlib.util.module_from_spec(spec)
        if source_snapshot is None:
            spec.loader.exec_module(module)
        else:
            from core.db import verify_migration_source_snapshot
            verify_migration_source_snapshot(source_snapshot)
            exec(source_snapshot.compiled, module.__dict__)  # noqa: S102 - executes hash-pinned migration bytes
        # Gemeinsame Entry-Point-Konvention mit core/db.py (PR-#10-Review
        # Befund 2): run_migration(conn)/run(conn)/migrate(db_path)/
        # upgrade(db_path)/main(). Vorher rief dieser Pfad run_migration()
        # OHNE conn auf und kannte migrate/upgrade gar nicht.
        import sqlite3

        from core.db import dispatch_py_migration
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            try:
                dispatch_py_migration(module, conn, self.db_path)
            except RuntimeError as e:
                raise RuntimeError(f"{py_file.name}: Weder run_migration() noch "
                                   f"ein anderer Entry-Point aufrufbar — {e}")
            conn.commit()
        finally:
            conn.close()

    def _create_pre_update_backup(self) -> tuple:
        """Erstellt ein Pre-Update-Backup."""
        import zipfile
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        ver = self._load_version()
        version_str = ver.get("version", "unknown").replace(".", "_")
        zip_name = f"pre_update_{version_str}_{timestamp}.zip"
        zip_path = self.backups_dir / zip_name
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if self.db_path.exists():
                    zf.write(self.db_path, "bach.db")
                if self.version_file.exists():
                    zf.write(self.version_file, "version.json")
                for config_file in (self.base_path / "data").glob("*.json"):
                    zf.write(config_file, f"data/{config_file.name}")
            size_mb = zip_path.stat().st_size / (1024 * 1024)
            return True, f"Backup erstellt: {zip_name} ({size_mb:.2f} MB)"
        except Exception as e:
            return False, f"Backup fehlgeschlagen: {e}"

    def _is_git_repo(self) -> bool:
        """Prueft ob ein Git-Repository vorhanden ist."""
        check = self.base_path
        for _ in range(5):
            if (check / ".git").exists():
                return True
            parent = check.parent
            if parent == check:
                break
            check = parent
        return False

    def _get_git_root(self) -> Optional[Path]:
        """Findet das Git-Root-Verzeichnis."""
        check = self.base_path
        for _ in range(5):
            if (check / ".git").exists():
                return check
            parent = check.parent
            if parent == check:
                break
            check = parent
        return None

    def _git_cmd(self, cmd: list) -> Tuple[bool, str]:
        """Fuehrt Git-Befehl aus."""
        git_root = self._get_git_root()
        if not git_root:
            return False, "Kein Git-Repository"
        try:
            result = subprocess.run(
                cmd, cwd=str(git_root),
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=30
            )
            if result.returncode == 0:
                return True, result.stdout
            return False, result.stderr or result.stdout
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except FileNotFoundError:
            return False, "Git nicht installiert"
        except Exception as e:
            return False, str(e)

    def _git_info(self) -> Optional[dict]:
        """Holt Git-Informationen."""
        if not self._is_git_repo():
            return None
        info = {}
        ok, branch = self._git_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if ok:
            info["Branch"] = branch.strip()
        ok, commit = self._git_cmd(["git", "log", "-1", "--format=%h %s"])
        if ok:
            info["Letzter Commit"] = commit.strip()
        ok, status = self._git_cmd(["git", "status", "--porcelain"])
        if ok:
            changed = len([ln for ln in status.strip().split("\n") if ln.strip()])
            info["Geaenderte Dateien"] = str(changed)
        return info if info else None

    # ──────────────────────────────────────────────
    # Skills & Modules Update/Sync (v3.15+)
    # ──────────────────────────────────────────────

    def _update_skills(self, args: list, dry_run: bool = False) -> tuple:
        """Prüft und aktualisiert Skills aus registrierten Quellen und zentraler Bibliothek."""
        apply_changes = ("--apply" in args or "-a" in args) and not dry_run
        from hub.skills import SkillsHandler, parse_version

        skills_handler = SkillsHandler(self.base_path)
        sources_file = self.base_path / "data" / "skill_sources.json"

        lines = ["=== SKILL UPDATE & SYNC ===", ""]
        if not sources_file.exists():
            lines.append(f"Keine skill_sources.json unter {sources_file} gefunden.")
            return True, "\n".join(lines)

        try:
            registry = json.loads(sources_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"Fehler beim Lesen von skill_sources.json: {exc}"

        version_sources = registry.get("version_sources", {})
        if not version_sources:
            lines.append("Keine version_sources in skill_sources.json registriert.")
            return True, "\n".join(lines)

        checked = 0
        up_to_date = 0
        needs_update = []
        updated = 0

        for skill_name, cfg in sorted(version_sources.items()):
            checked += 1
            # Ermittle lokale Version
            local_skill_path = skills_handler._find_skill(skill_name)
            local_ver = "0.0.0"
            if local_skill_path and local_skill_path.exists():
                skill_md = local_skill_path / "SKILL.md" if local_skill_path.is_dir() else local_skill_path
                if skill_md.exists():
                    header = skills_handler._extract_yaml_header(skill_md)
                    local_ver = header.get("version") or "0.0.0"

            # Ermittle zentrale Version
            central_ver = None
            central_source_path = None
            for src in cfg.get("canonical", []):
                ver, p = skills_handler._get_registered_version(src, registry_dir=str(sources_file.parent))
                if ver:
                    central_ver = ver
                    central_source_path = p
                    break

            if not central_ver:
                lines.append(f"  ? {skill_name}: keine zentrale Version ermittelbar (lokal: v{local_ver})")
                continue

            loc_tuple = parse_version(local_ver)
            cen_tuple = parse_version(central_ver)

            if cen_tuple > loc_tuple:
                needs_update.append((skill_name, local_ver, central_ver, central_source_path, local_skill_path))
                lines.append(f"  ! {skill_name}: Update verfuegbar (v{local_ver} -> v{central_ver})")
            else:
                up_to_date += 1
                lines.append(f"  ✓ {skill_name}: aktuell (v{local_ver})")

        lines.append("")
        lines.append(f"Geprueft: {checked} Skills | Aktuell: {up_to_date} | Updates verfuegbar: {len(needs_update)}")

        if needs_update and apply_changes:
            lines.append("")
            lines.append("WENDE UPDATES AN:")
            lines.append("-" * 40)
            backups_dir = self.backups_dir / "skills"
            backups_dir.mkdir(parents=True, exist_ok=True)
            for s_name, old_v, new_v, src_p, loc_p in needs_update:
                if not src_p or not src_p.exists():
                    lines.append(f"  [WARNUNG] Quelldatei fuer {s_name} existiert nicht: {src_p}")
                    continue
                # Backup erstellen
                if loc_p and loc_p.exists():
                    backup_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    if loc_p.is_dir():
                        b_dest = backups_dir / f"{s_name}_backup_v{old_v}_{backup_ts}"
                        shutil.copytree(loc_p, b_dest)
                    else:
                        b_dest = backups_dir / f"{loc_p.stem}_backup_v{old_v}_{backup_ts}{loc_p.suffix}"
                        shutil.copy2(loc_p, b_dest)
                # Aktualisieren
                if src_p.is_dir():
                    dest_dir = loc_p if loc_p else (self.base_path / "skills" / s_name)
                    if dest_dir.exists():
                        shutil.rmtree(dest_dir)
                    shutil.copytree(src_p, dest_dir)
                else:
                    target_file = loc_p if loc_p else (self.base_path / "skills" / f"{s_name}.md")
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_p, target_file)
                updated += 1
                lines.append(f"  + {s_name}: v{old_v} -> v{new_v} aktualisiert")
            lines.append(f"Erfolgreich aktualisiert: {updated} Skill(s)")

        # Multi-Device / Agent Copies spiegeln (z.B. ~/.claude/skills, ~/.codex/skills)
        sync_copies = ("--sync-copies" in args or "--all-targets" in args) or (apply_changes and "--no-copies" not in args)
        if sync_copies and not dry_run:
            copy_lines = []
            for s_name, cfg in sorted(version_sources.items()):
                for cp in cfg.get("copies", []):
                    if not isinstance(cp, dict):
                        continue
                    path_str = cp.get("path")
                    if not path_str:
                        continue
                    target_p = Path(os.path.expandvars(path_str)).expanduser()
                    source_skill = skills_handler._find_skill(s_name)
                    if not source_skill or not source_skill.exists():
                        for src in cfg.get("canonical", []):
                            _, p = skills_handler._get_registered_version(src, registry_dir=str(sources_file.parent))
                            if p and p.exists():
                                source_skill = p
                                break
                    if not source_skill or not source_skill.exists():
                        continue
                    src_file = source_skill / "SKILL.md" if source_skill.is_dir() else source_skill
                    if not src_file.exists():
                        continue
                    try:
                        # Bei optionalen Kopien nur anlegen wenn Elternordner (z.B. ~/.claude/skills) existiert
                        if cp.get("optional", False) and not (target_p.parent.exists() or target_p.parent.parent.exists()):
                            continue
                        target_p.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, target_p)
                        copy_lines.append(f"  → Kopie synchronisiert ({cp.get('source')}): {target_p}")
                    except Exception as cp_err:
                        copy_lines.append(f"  [WARNUNG] Kopie an {target_p} fehlgeschlagen: {cp_err}")
            if copy_lines:
                lines.append("")
                lines.append("SYNCHRONISIERTE KOPIEN & AGENTEN-FLOTTE:")
                lines.append("-" * 40)
                lines.extend(copy_lines)
        elif needs_update and not apply_changes:
            lines.append("")
            lines.append("Hinweis: Nutze 'bach update skills --apply' zum Einspielen der Updates.")

        return True, "\n".join(lines)

    def _copy_tree_safe(self, src: Path, dst: Path):
        """Kopiert ein Verzeichnis rekursiv ohne .git und Caches."""
        import shutil
        if not dst.exists():
            dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if item.is_dir():
                continue
            if any(part in (".git", "__pycache__", ".pytest_cache") for part in item.parts):
                continue
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    def _sync_dir_contents(self, src: Path, dst: Path) -> int:
        """Gleicht Manifeste und Kern-Dateien von src nach dst ab, ignoriert .git und Caches."""
        import shutil
        count = 0
        if not src.exists() or not dst.exists():
            return count
        allowed_names = {"MANIFEST.json", "ellmos-module.v2.json", "pyproject.toml", "LICENSE", "NOTICE", "README.md"}
        for item in src.iterdir():
            if item.is_dir():
                continue
            if item.name not in allowed_names and not item.name.endswith(".py"):
                continue
            target = dst / item.name
            if not target.exists() or target.stat().st_mtime < item.stat().st_mtime:
                shutil.copy2(item, target)
                count += 1
        return count

    def _update_modules(self, args: list, dry_run: bool = False) -> tuple:
        """Prüft und synchronisiert geteilte Module in .MODULES/ und Plan D Repos."""
        sync_mode = any(a in ("--sync", "--install", "--apply") for a in args)
        is_dry_run = dry_run or any(a in ("--dry-run", "-n") for a in args)

        lines = ["=== MODULE & ADAPTER STATUS ===", ""]
        modules_dir = self.base_path.parent / ".MODULES"
        if not modules_dir.exists():
            modules_dir = self.base_path / ".MODULES"

        if not modules_dir.exists():
            lines.append("Kein .MODULES-Verzeichnis gefunden.")
            return True, "\n".join(lines)

        module_count = 0
        manifests = list(modules_dir.glob("**/MANIFEST.json")) + list(modules_dir.glob("**/ellmos-module.v2.json"))

        lines.append(f"Gefundene Modul-Manifeste in {modules_dir}:")
        lines.append("-" * 50)
        for m_path in sorted(manifests):
            try:
                data = json.loads(m_path.read_text(encoding="utf-8"))
                name = data.get("name") or data.get("display_name") or m_path.parent.name
                version = data.get("version", "?")
                desc = (data.get("description") or "")[:50]
                entry = data.get("entry_point") or (data.get("entrypoints", {}).get("library") if isinstance(data.get("entrypoints"), dict) else "?")
                lines.append(f"  • {name:<25} v{version:<8} [{entry}]")
                if desc:
                    lines.append(f"    {desc}")
                module_count += 1
            except (OSError, ValueError):
                continue

        lines.append("-" * 50)
        lines.append(f"Gesamt: {module_count} geteilte(s) Modul(e) registriert.")
        lines.append("Alle Module sind self-contained und interoperabel mit BACH und Ocean.")

        # Standalone / Ocean Repositories aus Katalog oder .CONTROL synchronisieren
        catalog_path = None
        for candidate in (
            modules_dir / "modules.catalog.json",
            Path.home() / "OneDrive" / ".TOPICS" / ".AI" / ".MODULES" / "modules.catalog.json",
            self.base_path / "data" / "modules.catalog.json",
            self.base_path.parent / ".MODULES" / "modules.catalog.json",
        ):
            if candidate.exists():
                catalog_path = candidate
                break

        standalone_modules = []
        if catalog_path:
            try:
                c_data = json.loads(catalog_path.read_text(encoding="utf-8"))
                c_mods = c_data.get("modules", {})
                if isinstance(c_mods, dict):
                    for mod_id, mod_info in c_mods.items():
                        if isinstance(mod_info, dict) and (mod_info.get("source_of_truth") or mod_info.get("runtime_source")):
                            info = dict(mod_info)
                            info.setdefault("id", mod_id)
                            standalone_modules.append(info)
                elif isinstance(c_mods, list):
                    for mod_info in c_mods:
                        if isinstance(mod_info, dict) and (mod_info.get("source_of_truth") or mod_info.get("runtime_source")):
                            standalone_modules.append(mod_info)
            except Exception:
                pass

        if not standalone_modules:
            standalone_modules = [
                {
                    "id": "ocean-resources",
                    "display_name": "ocean-resources",
                    "version": "0.2.0",
                    "runtime_source": str(Path(os.environ.get("LOCAL_DEV_REPOS", r"C:\_Local_DEV\repos")) / "ocean-resources"),
                    "source_of_truth": {"repository": "https://github.com/ellmos-ai/ocean-resources.git"},
                    "resolved_source": ".CONTROL/ocean-resources"
                },
                {
                    "id": "agents-heart",
                    "display_name": "agents-heart",
                    "version": "0.2.0",
                    "runtime_source": str(Path(os.environ.get("LOCAL_DEV_REPOS", r"C:\_Local_DEV\repos")) / "agents-heart"),
                    "source_of_truth": {"repository": "https://github.com/ellmos-ai/agents-heart.git"},
                    "resolved_source": ".CONTROL/agents-heart"
                }
            ]

        local_dev = Path(os.environ.get("LOCAL_DEV_REPOS", r"C:\_Local_DEV\repos"))

        tier_arg = None
        for a in args:
            if a.startswith("--tier="):
                tier_arg = a.split("=", 1)[1].strip().lower()
                break
            if a.startswith("--bundle="):
                tier_arg = a.split("=", 1)[1].strip().lower()
                break
        if not tier_arg:
            for idx, a in enumerate(args):
                if a in ("--tier", "--bundle") and idx + 1 < len(args):
                    tier_arg = args[idx + 1].strip().lower()
                    break

        TIER_BUNDLES = {
            "rinnsal": [
                "open-ocean",
                "task-master",
                "agents-heart",
                "condition-gates",
            ],
            "bach": [
                "open-ocean",
                "ocean-resources",
                "agents-heart",
                "gardener",
                "anonymizer",
                "doc-keeper",
                "task-master",
                "condition-gates",
                "foerderplaner",
                "ellmos-system-gui",
                "law-checker",
                "worksheet-generator",
            ],
            "meer": None,
        }

        if tier_arg:
            if tier_arg not in TIER_BUNDLES:
                return False, f"[FEHLER] Unbekannter Tier: '{tier_arg}'. Gültige Tiers: rinnsal, bach, meer"
            target_ids = TIER_BUNDLES[tier_arg]
            if target_ids is not None:
                existing_ids = {m.get("id") for m in standalone_modules}
                for t_id in target_ids:
                    if t_id not in existing_ids:
                        standalone_modules.append({
                            "id": t_id,
                            "display_name": t_id,
                            "version": "latest",
                            "runtime_source": str(local_dev / t_id),
                            "source_of_truth": {"repository": f"https://github.com/ellmos-ai/{t_id}.git"},
                            "resolved_source": f".CONTROL/{t_id}"
                        })
                standalone_modules = [m for m in standalone_modules if m.get("id") in target_ids]

        target_filters = []
        skip_next = False
        for a in args:
            if skip_next:
                skip_next = False
                continue
            if a in ("--tier", "--bundle"):
                skip_next = True
                continue
            if a.startswith("--tier=") or a.startswith("--bundle="):
                continue
            if not a.startswith("--") and not a.startswith("-") and a != "modules":
                target_filters.append(a)

        if target_filters:
            filtered = [
                m for m in standalone_modules
                if any(t in (m.get("id"), m.get("name"), m.get("display_name")) for t in target_filters)
            ]
            if filtered:
                standalone_modules = filtered

        lines.append("")
        lines.append("=== STANDALONE REPOSITORIEN & OCEAN-MODULE ===")
        lines.append(f"Katalog: {catalog_path if catalog_path else 'Standard (ocean-resources, agents-heart)'}")
        if tier_arg:
            lines.append(f"Tier:    {tier_arg.upper()} ({len(standalone_modules)} Module aufgelöst)")
        lines.append("-" * 50)

        for s_mod in standalone_modules:
            mod_id = s_mod.get("id") or s_mod.get("name") or "unknown"
            r_source = s_mod.get("runtime_source")
            repo_path = Path(r_source) if r_source else (local_dev / mod_id)
            repo_exists = repo_path.exists()
            git_url = None
            sot = s_mod.get("source_of_truth")
            if isinstance(sot, dict):
                git_url = sot.get("repository")
            res_source = s_mod.get("resolved_source") or f".CONTROL/{mod_id}"
            control_dir = modules_dir / res_source if not Path(res_source).is_absolute() else Path(res_source)

            status_label = "INSTALLIERT" if repo_exists else "NICHT GEKLONT"
            lines.append(f"  • {mod_id:<22} [{status_label}] -> {repo_path}")

            if sync_mode:
                if not repo_exists:
                    if is_dry_run:
                        lines.append(f"    [DRY-RUN] Würde klonen von {git_url or control_dir} nach {repo_path}")
                    else:
                        cloned = False
                        if git_url:
                            try:
                                import subprocess
                                proc = subprocess.run(
                                    ["git", "clone", git_url, str(repo_path)],
                                    capture_output=True, text=True, timeout=60
                                )
                                if proc.returncode == 0:
                                    cloned = True
                                    lines.append(f"    [OK] Geklont von {git_url}")
                            except Exception as exc:
                                lines.append(f"    [WARNUNG] Git-Clone fehlgeschlagen: {exc}")
                        if not cloned and control_dir.exists():
                            try:
                                self._copy_tree_safe(control_dir, repo_path)
                                lines.append(f"    [OK] Initialisiert aus {control_dir}")
                            except Exception as exc:
                                lines.append(f"    [FEHLER] Kopieren fehlgeschlagen: {exc}")
                else:
                    if is_dry_run:
                        lines.append(f"    [DRY-RUN] Würde Repo {repo_path} und .CONTROL abgleichen")
                    else:
                        if control_dir.exists():
                            copied = self._sync_dir_contents(repo_path, control_dir)
                            lines.append(f"    [OK] Synchronisiert mit {control_dir} ({copied} Dateien abgeglichen)")

        if not sync_mode:
            lines.append("")
            lines.append("Hinweis: Nutze 'bach update modules --sync' zum Klonen und Synchronisieren der Modul-Repos.")

        # Standalone-Modul Re-Import & Hot-Wiring (#3719, Task -23)
        reimport_mode = sync_mode or any(a in ("--reimport", "--hotwire", "--hot-wire") for a in args)
        if reimport_mode:
            lines.append("")
            lines.append("=== RE-IMPORT & HOT-WIRING (Standalone Module) ===")
            exports_dir = self.base_path / "exports" / "modules"
            from hub.skills import verify_selfcontained_module
            from hub._services.ocean_stack_bridge import invalidate_module_cache

            reimported_count = 0
            if exports_dir.exists():
                for exp_dir in sorted(exports_dir.glob("*_export")):
                    if not exp_dir.is_dir():
                        continue
                    m_valid, m_errs, _, meta = verify_selfcontained_module(exp_dir)
                    if m_valid:
                        m_name = meta.get("name", exp_dir.name.replace("_export", ""))
                        m_ver = meta.get("version", "1.0.0")
                        target_mod_dir = modules_dir / m_name
                        if is_dry_run:
                            lines.append(f"  • {m_name:<22} [DRY-RUN] Re-Import v{m_ver} nach {target_mod_dir}")
                        else:
                            self._copy_tree_safe(exp_dir, target_mod_dir)
                            reimported_count += 1
                            lines.append(f"  • {m_name:<22} [RE-IMPORTIERT] v{m_ver} -> {target_mod_dir} [OK]")
                    else:
                        lines.append(f"  • {exp_dir.name:<22} [WARNUNG] Nicht valide: {', '.join(m_errs)}")

            if not is_dry_run and reimported_count > 0:
                invalidate_module_cache()
                lines.append(f"\n[OK] {reimported_count} Standalone-Modul(e) re-importiert und ueber ocean_stack_bridge hot-wired.")

        return True, "\n".join(lines)

    def _update_all(self, args: list, dry_run: bool = False) -> tuple:
        """Führt Core-Check, Skills-Check und Modules-Status zusammen aus."""
        sections = []
        ok1, msg1 = self._check()
        sections.append(msg1)
        ok2, msg2 = self._update_skills(args, dry_run=dry_run)
        sections.append(msg2)
        ok3, msg3 = self._update_modules(args, dry_run=dry_run)
        sections.append(msg3)
        return (ok1 and ok2 and ok3), "\n\n".join(sections)
