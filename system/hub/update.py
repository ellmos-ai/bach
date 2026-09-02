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
        elif operation == "migrations":
            sub = args[0] if args else "list"
            if sub == "run":
                return self._run_migrations(dry_run)
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
                "[DRY-RUN] Wuerde folgende Schritte ausfuehren:",
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
            lines.append("\n  [DRY-RUN] Wuerde bach.db aus Backup wiederherstellen.")
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

    def _run_migrations(self, dry_run: bool = False) -> tuple:
        """Fuehrt ausstehende Migrationen aus (Tracking: _migrations-Tabelle)."""
        applied = self._applied_migrations()
        available = self._get_available_migrations()
        pending = [m for m in available if m not in applied]
        if not pending:
            return True, "Keine ausstehenden Migrationen."
        lines = [f"{len(pending)} ausstehende Migration(en):"]
        for mig_name in pending:
            mig_file = self.migrations_dir / mig_name
            if not mig_file.exists():
                lines.append(f"  [!!] {mig_name}: Datei nicht gefunden")
                continue
            if dry_run:
                lines.append(f"  [DRY-RUN] Wuerde ausfuehren: {mig_name}")
                continue
            try:
                if mig_file.suffix == ".sql":
                    self._run_sql_migration(mig_file)
                elif mig_file.suffix == ".py":
                    self._run_py_migration(mig_file)
                self._mark_applied([mig_name])
                lines.append(f"  [OK] {mig_name}")
            except Exception as e:
                lines.append(f"  [!!] {mig_name}: {e}")
                lines.append("  Migration abgebrochen (Reihenfolge!). Bestands-DB? "
                             "'bach update migrations baseline --through NNN' pruefen.")
                return False, "\n".join(lines)
        return True, "\n".join(lines)

    def _run_sql_migration(self, sql_file: Path):
        """Fuehrt eine SQL-Migration aus."""
        import sqlite3
        sql = sql_file.read_text(encoding="utf-8")
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(sql)
            conn.commit()
        finally:
            conn.close()

    def _run_py_migration(self, py_file: Path):
        """Fuehrt eine Python-Migration aus."""
        spec = importlib.util.spec_from_file_location(
            f"migration_{py_file.stem}", py_file
        )
        if not spec or not spec.loader:
            raise RuntimeError(f"Kann {py_file.name} nicht laden")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
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
