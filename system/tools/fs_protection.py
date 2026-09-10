#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: fs_protection
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version fs_protection

Description:
    [Beschreibung hinzufügen]

Usage:
    python fs_protection.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
fs_protection.py - BACH Filesystem Protection & Backup System v2.0
===================================================================

Sichert und validiert die Systemintegritaet mit dist_type Klassifizierung.

Tasks: FS-PROTECT-01 bis FS-PROTECT-06 (#773-778)

Features:
- Pfad-Klassifizierung (dist_type 0/1/2)
- Snapshot-System fuer Core-Dateien
- Integrity Check mit Hash-Vergleich
- Heal/Restore aus Snapshots

Usage:
    python tools/fs_protection.py [backup|check|heal|classify <path>]

v2.0 - 2026-01-30: Erweitert um dist_type System (Task 773)
v1.0 - Initial
"""

import os
import sys
import shutil
import hashlib
import json
import sqlite3
import zipfile
import fnmatch
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Pfade
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
USER_DIR = BASE_DIR / "user"
BACKUP_DIR = BASE_DIR / "_backups"
DIST_DIR = BASE_DIR / "dist"
SNAPSHOTS_DIR = DIST_DIR / "snapshots"
MANIFEST_FILE = DATA_DIR / "fs_manifest.json"

# The runtime database lives outside the OneDrive source tree.  Keep a
# direct-script fallback for this standalone tool, but prefer the central
# path whenever the BACH package is importable.
try:
    from hub.bach_paths import BACH_DB
except ImportError:  # pragma: no cover - standalone invocation fallback
    BACH_DB = DATA_DIR / "bach.db"


# =============================================================================
# DIST_TYPE KLASSIFIZIERUNG
# =============================================================================
#
# dist_type = 2 (CORE): Systemkritisch, nicht aenderbar
# dist_type = 1 (TEMPLATE): Systemdatei, zuruecksetzbar
# dist_type = 0 (USER): User-Daten, nicht im Installer
#
# PRINZIP: DEFAULT = systemrelevant (2), nur explizite Ausnahmen sind User (0)
# =============================================================================

class PathClassifier:
    """Klassifiziert Pfade nach dist_type."""

    # CORE (dist_type=2) - Systemkritische Dateien
    CORE_PATTERNS = [
        "bach.py",
        "bach_paths.py",
        "setup_db.py",
        "hub/*.py",
        "hub/**/*.py",
        "tools/*.py",
        "services/*.py",
        "agents/*.md",
        "agents/*.txt",
        "agents/**/*.md",
        "agents/_experts/*.md",
        "agents/_experts/**/*.md",
        "skills/workflows/*.md",
        "skills/_services/**/*.py",
        "connectors/*.py",
        "partners/**/*",
        "data/schema*.sql",
        "gui/*.py",
        "gui/*.html",
        "gui/static/**/*",
    ]

    # USER (dist_type=0) - Explizit ausgeschlossene Pfade
    USER_PATTERNS = [
        "tools/_user/*",
        "tools/_user/**/*",
        "tools/_archive/*",
        "tools/_archive/**/*",
        "skills/_prompts/user_*",
        "skills/_prompts/_user/*",
        "_archive/*",
        "_archive/**/*",
        "_system/data/system/data/system/data/system/data/backups/*",
        "_system/data/system/data/system/data/system/data/backups/**/*",
        "user/*",
        "user/**/*",
        "data/*.db",  # DBs sind Template, nicht Core
        "docs/_archive/*",
        "docs/_archive/**/*",
        "logs/*",
        "logs/**/*",
    ]

    # TEMPLATE (dist_type=1) - Zuruecksetzbare Systemdateien
    TEMPLATE_PATTERNS = [
        "data/bach.db",
        "data/schema.sql",
        "user/IDENTITY.md",
        "skills/_prompts/*.md",
        "docs/help/*.md",
        "ROADMAP.md",
        "README.md",
    ]

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or BASE_DIR

    def _matches_any(self, rel_path: str, patterns: List[str]) -> bool:
        """Prueft ob Pfad auf eines der Patterns matched."""
        # Normalisiere Pfad (forward slashes)
        rel_path = rel_path.replace("\\", "/")

        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            # Auch ohne fuehrenden Pfad pruefen
            if "/" in rel_path:
                filename = rel_path.split("/")[-1]
                if fnmatch.fnmatch(filename, pattern):
                    return True
        return False

    def classify_path(self, path: Path) -> int:
        """
        Klassifiziert einen Pfad nach dist_type.

        Args:
            path: Absoluter oder relativer Pfad

        Returns:
            dist_type: 0 (USER), 1 (TEMPLATE), 2 (CORE)
        """
        # Relativen Pfad ermitteln
        try:
            if path.is_absolute():
                rel_path = str(path.relative_to(self.base_path))
            else:
                rel_path = str(path)
        except ValueError:
            # Pfad ausserhalb von BACH
            return 0

        # Normalisiere
        rel_path = rel_path.replace("\\", "/")

        # 1. Zuerst USER pruefen (explizite Ausnahmen)
        if self._matches_any(rel_path, self.USER_PATTERNS):
            return 0

        # 2. Dann TEMPLATE pruefen
        if self._matches_any(rel_path, self.TEMPLATE_PATTERNS):
            return 1

        # 3. Dann CORE pruefen
        if self._matches_any(rel_path, self.CORE_PATTERNS):
            return 2

        # 4. DEFAULT: Unbekannte Dateien sind USER
        # (Sicherheit: Lieber nicht ins Distribution packen)
        return 0

    def is_protected(self, path: Path) -> bool:
        """Prueft ob eine Datei geschuetzt ist (dist_type >= 1)."""
        return self.classify_path(path) >= 1

    def get_protection_level(self, path: Path) -> str:
        """Gibt Schutzlevel als String zurueck."""
        dist_type = self.classify_path(path)
        return {0: "USER", 1: "TEMPLATE", 2: "CORE"}[dist_type]

    def scan_directory(self, directory: Path = None) -> Dict[int, List[str]]:
        """
        Scannt ein Verzeichnis und gruppiert Dateien nach dist_type.

        Returns:
            Dict mit dist_type als Key und Liste von Pfaden als Value
        """
        directory = directory or self.base_path
        result = {0: [], 1: [], 2: []}

        for root, dirs, files in os.walk(directory):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for file in files:
                file_path = Path(root) / file
                dist_type = self.classify_path(file_path)
                rel_path = str(file_path.relative_to(self.base_path))
                result[dist_type].append(rel_path)

        return result


class FSProtection:
    """Filesystem Protection mit Snapshot und Heal."""

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or BASE_DIR
        self.classifier = PathClassifier(self.base_path)
        self.db_path = BACH_DB

        # Verzeichnisse erstellen
        BACKUP_DIR.mkdir(exist_ok=True)
        DIST_DIR.mkdir(exist_ok=True)
        SNAPSHOTS_DIR.mkdir(exist_ok=True)

    def _resolve_manifest_path(self, rel_path: str) -> Path:
        """Resolve mixed legacy manifest paths against the canonical roots.

        Older manifest rows store files below ``system/`` both with and
        without that prefix, while repository-root files (for example
        ``README.md``) have no prefix.  Prefer an existing system-relative
        candidate, then an existing repository-root candidate; for a missing
        path preserve the same directory convention so a genuine absence is
        reported accurately.
        """
        relative = Path(rel_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Ungueltiger Manifestpfad: {rel_path}")

        project_root = self.base_path.parent if self.base_path.name == "system" else self.base_path
        system_candidate = self.base_path / relative
        root_candidate = project_root / relative
        if relative.parts and relative.parts[0] == "system":
            return root_candidate
        if system_candidate.exists() or not root_candidate.exists():
            return system_candidate
        return root_candidate

    def _get_conn(self) -> sqlite3.Connection:
        """Datenbankverbindung."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_hash(self, filepath: Path) -> str:
        """Berechnet SHA256-Hash einer Datei."""
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def _path_to_snapshot_name(self, rel_path: str) -> str:
        """Konvertiert Pfad zu Snapshot-Dateiname."""
        # hub/time.py -> hub_time.py.orig
        return rel_path.replace("/", "_").replace("\\", "_") + ".orig"

    def _snapshot_name_to_path(self, snapshot_name: str) -> str:
        """Konvertiert Snapshot-Name zurueck zu Pfad."""
        # hub_time.py.orig -> hub/time.py
        if snapshot_name.endswith(".orig"):
            snapshot_name = snapshot_name[:-5]
        # Einfache Heuristik: Erster Underscore ist Verzeichnistrenner
        # Das ist nicht perfekt, aber fuer die meisten Faelle OK
        return snapshot_name.replace("_", "/", 1)

    def create_backup(self, tag: str = "auto") -> Tuple[bool, str]:
        """Erstellt ein ZIP-Backup der kritischen Verzeichnisse."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"BACH_Backup_{tag}_{timestamp}.zip"
        backup_path = BACKUP_DIR / backup_name

        print(f"[FS] Erstelle Backup: {backup_name}...")
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for folder in [DATA_DIR, USER_DIR]:
                    if not folder.exists():
                        continue
                    for root, dirs, files in os.walk(folder):
                        for file in files:
                            if file in ("nul", ".DS_Store"):
                                continue
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(self.base_path)
                            try:
                                zipf.write(file_path, arcname)
                            except Exception:
                                pass

            self._update_manifest(backup_name)
            print(f"[OK] Backup erstellt: {backup_path}")
            return True, str(backup_path)
        except Exception as e:
            return False, str(e)

    def _update_manifest(self, last_backup: str):
        """Speichert den Stand der Dateien und das letzte Backup."""
        manifest = {
            "last_backup": last_backup,
            "last_check": datetime.now().isoformat(),
            "version": "2.0",
            "files": {}
        }

        # Checksummen fuer kritische Dateien
        for db in ["bach.db"]:
            p = DATA_DIR / db
            if p.exists():
                manifest["files"][db] = self._get_hash(p)

        MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def check_integrity(self) -> Tuple[bool, str]:
        """Prueft Dateien gegen Snapshots und Manifest."""
        if not MANIFEST_FILE.exists():
            print("[FS] Kein Manifest gefunden. Erstelle neues...")
            self._update_manifest("initial")
            return True, "Manifest initialisiert."

        results = {
            "ok": [],
            "modified": [],
            "missing": [],
            "untracked": []
        }

        # Alle geschuetzten Dateien pruefen
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT path, template_hash FROM distribution_manifest
            WHERE dist_type >= 1
        """).fetchall()
        conn.close()

        for row in rows:
            rel_path = row["path"]
            expected_hash = row["template_hash"]

            try:
                file_path = self._resolve_manifest_path(rel_path)
            except ValueError:
                results["missing"].append(rel_path)
                continue

            if not file_path.exists():
                results["missing"].append(rel_path)
                continue

            if expected_hash:
                actual_hash = self._get_hash(file_path)
                if actual_hash != expected_hash:
                    results["modified"].append(rel_path)
                else:
                    results["ok"].append(rel_path)
            else:
                results["ok"].append(rel_path)

        # Output formatieren
        lines = ["[FS] Integrity Check", ""]

        if results["missing"]:
            lines.append(f"MISSING ({len(results['missing'])}):")
            for p in results["missing"][:5]:
                lines.append(f"  [X] {p}")
            if len(results["missing"]) > 5:
                lines.append(f"  ... und {len(results['missing']) - 5} weitere")

        if results["modified"]:
            lines.append(f"\nMODIFIED ({len(results['modified'])}):")
            for p in results["modified"][:5]:
                lines.append(f"  [!] {p}")
            if len(results["modified"]) > 5:
                lines.append(f"  ... und {len(results['modified']) - 5} weitere")

        lines.append(f"\nOK: {len(results['ok'])} | Modified: {len(results['modified'])} | Missing: {len(results['missing'])}")

        success = len(results["missing"]) == 0
        return success, "\n".join(lines)

    def heal(self, file_path: str = None, force: bool = False) -> Tuple[bool, str]:
        """Stellt Datei(en) aus Snapshots wieder her."""
        if file_path:
            return self._heal_single(file_path, force)
        else:
            return self._heal_all(force)

    def _heal_single(self, rel_path: str, force: bool = False) -> Tuple[bool, str]:
        """Stellt eine einzelne Datei wieder her."""
        snapshot_name = self._path_to_snapshot_name(rel_path)
        snapshot_path = SNAPSHOTS_DIR / snapshot_name

        if not snapshot_path.exists():
            return False, f"[FS] Kein Snapshot fuer: {rel_path}"

        target_path = self._resolve_manifest_path(rel_path)

        # Backup der aktuellen Version
        if target_path.exists() and not force:
            backup_path = target_path.with_suffix(target_path.suffix + ".bak")
            shutil.copy2(target_path, backup_path)
            print(f"[FS] Backup erstellt: {backup_path.name}")

        # Restore
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_path, target_path)

        return True, f"[FS] Wiederhergestellt: {rel_path}"

    def _heal_all(self, force: bool = False) -> Tuple[bool, str]:
        """Stellt alle fehlenden/beschaedigten Dateien wieder her."""
        snapshots = list(SNAPSHOTS_DIR.glob("*.orig"))
        if not snapshots:
            return False, (
                "[FS] Heal abgebrochen: Keine gueltigen Snapshots vorhanden. "
                "Erstelle zuerst bewusst Snapshots mit `bach dist snapshot --all`."
            )

        healed = []
        failed = []

        for snapshot_file in snapshots:
            rel_path = self._snapshot_name_to_path(snapshot_file.name)
            target_path = self._resolve_manifest_path(rel_path)

            if not target_path.exists():
                success, msg = self._heal_single(rel_path, force)
                if success:
                    healed.append(rel_path)
                else:
                    failed.append(rel_path)

        lines = ["[FS] Heal All", ""]
        lines.append(f"Wiederhergestellt: {len(healed)}")
        lines.append(f"Fehlgeschlagen: {len(failed)}")

        if healed:
            lines.append("\nWiederhergestellt:")
            for p in healed[:10]:
                lines.append(f"  [OK] {p}")

        return len(failed) == 0, "\n".join(lines)

    def create_snapshot(self, file_path: str = None, all_files: bool = False) -> Tuple[bool, str]:
        """Erstellt Snapshot(s) von geschuetzten Dateien."""
        if file_path:
            return self._snapshot_single(file_path)
        elif all_files:
            return self._snapshot_all()
        else:
            return False, "Usage: snapshot <file> oder snapshot --all"

    def _snapshot_single(self, rel_path: str) -> Tuple[bool, str]:
        """Erstellt Snapshot einer einzelnen Datei."""
        source_path = self._resolve_manifest_path(rel_path)

        if not source_path.exists():
            return False, f"[FS] Datei nicht gefunden: {rel_path}"

        snapshot_name = self._path_to_snapshot_name(rel_path)
        snapshot_path = SNAPSHOTS_DIR / snapshot_name

        shutil.copy2(source_path, snapshot_path)

        # Hash in DB speichern
        file_hash = self._get_hash(source_path)
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO distribution_manifest
            (path, dist_type, template_hash, updated_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (rel_path, self.classifier.classify_path(source_path), file_hash))
        conn.commit()
        conn.close()

        return True, f"[FS] Snapshot erstellt: {snapshot_name}"

    def _snapshot_all(self) -> Tuple[bool, str]:
        """Erstellt Snapshots aller Core/Template Dateien."""
        created = 0
        skipped = 0

        # Alle Dateien scannen
        scan_result = self.classifier.scan_directory()

        # Nur CORE (2) und TEMPLATE (1) Dateien
        for dist_type in [2, 1]:
            for rel_path in scan_result[dist_type]:
                # Nur bestimmte Dateitypen
                if not rel_path.endswith(('.py', '.md', '.sql', '.html', '.css', '.js')):
                    skipped += 1
                    continue

                source_path = self._resolve_manifest_path(rel_path)
                if not source_path.exists() or not source_path.is_file():
                    skipped += 1
                    continue

                success, _ = self._snapshot_single(rel_path)
                if success:
                    created += 1

        return True, f"[FS] Snapshots erstellt: {created} | Uebersprungen: {skipped}"


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI Entry Point."""
    args = sys.argv[1:] if len(sys.argv) > 1 else ["help"]
    op = args[0] if args else "help"

    fs = FSProtection()
    classifier = PathClassifier()

    if op == "backup":
        tag = args[1] if len(args) > 1 else "manual"
        success, msg = fs.create_backup(tag)

    elif op == "check":
        success, msg = fs.check_integrity()

    elif op == "heal":
        file_path = args[1] if len(args) > 1 else None
        force = "--force" in args
        success, msg = fs.heal(file_path, force)

    elif op == "snapshot":
        if "--all" in args:
            success, msg = fs.create_snapshot(all_files=True)
        elif len(args) > 1:
            success, msg = fs.create_snapshot(file_path=args[1])
        else:
            success, msg = False, "Usage: snapshot <file> oder snapshot --all"

    elif op == "classify":
        if len(args) < 2:
            success, msg = False, "Usage: classify <path>"
        else:
            path = Path(args[1])
            dist_type = classifier.classify_path(path)
            level = classifier.get_protection_level(path)
            success, msg = True, f"{path}: dist_type={dist_type} ({level})"

    elif op == "scan":
        print("[FS] Scanne Verzeichnis...")
        result = classifier.scan_directory()
        print(f"\nCORE (dist_type=2): {len(result[2])} Dateien")
        print(f"TEMPLATE (dist_type=1): {len(result[1])} Dateien")
        print(f"USER (dist_type=0): {len(result[0])} Dateien")
        success, msg = True, ""

    elif op == "help":
        success = True
        msg = """
BACH Filesystem Protection v2.0
================================

Befehle:
  backup [tag]      Erstellt ZIP-Backup
  check             Prueft Integritaet gegen Snapshots
  heal [file]       Stellt Datei(en) aus Snapshots her
  heal --all        Stellt alle fehlenden Dateien her
  snapshot <file>   Erstellt Snapshot einer Datei
  snapshot --all    Erstellt Snapshots aller Core/Template Dateien
  classify <path>   Zeigt dist_type fuer Pfad
  scan              Scannt und gruppiert alle Dateien nach dist_type

dist_type:
  0 = USER      - User-Daten (nicht im Installer)
  1 = TEMPLATE  - Systemdatei (zuruecksetzbar)
  2 = CORE      - Systemkritisch (nicht aenderbar)
"""
    else:
        success, msg = False, f"Unbekannte Operation: {op}\nNutze: python fs_protection.py help"

    if msg:
        print(msg)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
