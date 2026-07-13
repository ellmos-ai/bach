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
FS Handler - Filesystem Protection CLI
=======================================

Subcommands:
  bach fs check              Integritaet pruefen
  bach fs heal [file]        Datei(en) wiederherstellen
  bach fs heal --all         Alle fehlenden wiederherstellen
  bach fs classify <path>    Zeigt dist_type fuer Pfad
  bach fs scan               Scannt und gruppiert Dateien
  bach fs status             Zeigt Schutz-Status

  bach dist snapshot --all   Erstellt Snapshots aller Core-Dateien
  bach dist snapshot <file>  Erstellt Snapshot einer Datei
  bach dist list             Zeigt Snapshot-Liste

v1.1.84: Initial Implementation (Tasks 773-778)
"""
import sys
from pathlib import Path
from typing import Tuple
from .base import BaseHandler

# Import FSProtection
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from fs_protection import FSProtection, PathClassifier


class FSHandler(BaseHandler):
    """Handler fuer bach fs - Filesystem Protection"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.fs = FSProtection(base_path)
        self.classifier = PathClassifier(base_path)

    @property
    def profile_name(self) -> str:
        return "fs"

    @property
    def target_file(self) -> Path:
        return self._canonical_db

    def get_operations(self) -> dict:
        return {
            "check": "Integritaet pruefen",
            "heal": "Datei(en) wiederherstellen",
            "classify": "dist_type fuer Pfad zeigen",
            "scan": "Dateien nach dist_type gruppieren",
            "status": "Schutz-Status anzeigen",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "check" or not operation:
            return self.fs.check_integrity()

        elif operation == "heal":
            if "--all" in args:
                force = "--force" in args
                return self.fs.heal(force=force)
            elif args:
                file_path = args[0]
                force = "--force" in args
                return self.fs.heal(file_path, force)
            else:
                return False, "Usage: bach fs heal <file> oder bach fs heal --all"

        elif operation == "classify":
            if not args:
                return False, "Usage: bach fs classify <path>"
            path = Path(args[0])
            dist_type = self.classifier.classify_path(path)
            level = self.classifier.get_protection_level(path)
            return True, f"{path}: dist_type={dist_type} ({level})"

        elif operation == "scan":
            result = self.classifier.scan_directory()
            lines = ["[FS] Dateisystem-Scan", ""]
            lines.append(f"CORE (dist_type=2): {len(result[2])} Dateien")
            lines.append(f"TEMPLATE (dist_type=1): {len(result[1])} Dateien")
            lines.append(f"USER (dist_type=0): {len(result[0])} Dateien")
            return True, "\n".join(lines)

        elif operation == "status":
            return self._status()

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach fs check"

    def _status(self) -> Tuple[bool, str]:
        """Zeigt Schutz-Status."""
        import sqlite3
        conn = None
        try:
            conn = sqlite3.connect(str(self.target_file))

            # Snapshots zaehlen
            snapshots_dir = self.base_path / "dist" / "snapshots"
            snapshot_count = len(list(snapshots_dir.glob("*.orig"))) if snapshots_dir.exists() else 0

            # Manifest-Eintraege
            manifest_count = conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0]
        finally:
            if conn:
                conn.close()

        # Letzte Pruefung aus fs_manifest.json
        import json
        manifest_file = self.base_path / "data" / "fs_manifest.json"
        last_check = "nie"
        last_backup = "keins"
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
            last_check = manifest.get("last_check", "nie")[:19]
            last_backup = manifest.get("last_backup", "keins")

        lines = [
            "[FS] Filesystem Protection Status",
            "",
            f"Snapshots:       {snapshot_count} Dateien",
            f"Manifest:        {manifest_count} Eintraege",
            f"Letzte Pruefung: {last_check}",
            f"Letztes Backup:  {last_backup}",
            "",
            "Befehle:",
            "  bach fs check        Integritaet pruefen",
            "  bach fs heal --all   Alle fehlenden wiederherstellen",
            "  bach dist snapshot   Snapshots aktualisieren",
        ]

        return True, "\n".join(lines)


# HINWEIS: DistHandler war hier frueher als Duplikat definiert (Bug #986).
# Der vollstaendige DistHandler befindet sich in hub/dist.py (497 Zeilen).
# Dieser Mini-Handler (73 Zeilen) hat den echten ueberschrieben.
# Entfernt: 2026-02-12
