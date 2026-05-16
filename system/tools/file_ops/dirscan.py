#!/usr/bin/env python3
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
Tool: c_dirscan
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_dirscan

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_dirscan.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
Directory Scanner - Automatische IST/SOLL Zustand Verwaltung
============================================================

- Startup: IST-Zustand erfassen
- Shutdown: Änderungen = neuer SOLL-Zustand
- Heuristik: Claude-Änderungen sind gewollt
"""
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple


class DirectoryScanner:
    """Scannt und vergleicht Verzeichnisstrukturen."""
    
    # Ignorierte Patterns
    IGNORE_PATTERNS = {
        "__pycache__",
        ".pyc",
        ".git",
        ".idea",
        ".vscode",
        "auto_log.txt",  # Ändert sich ständig
        "current.md",    # Memory ändert sich ständig
    }
    
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.truth_file = base_path / "data" / "directory_truth.json"
    
    def _should_ignore(self, path: Path) -> bool:
        """Prüft ob Pfad ignoriert werden soll."""
        path_str = str(path)
        for pattern in self.IGNORE_PATTERNS:
            if pattern in path_str:
                return True
        return False
    
    def scan(self) -> Dict:
        """
        Scannt aktuellen Verzeichnis-Zustand.
        
        Returns:
            Dict mit Struktur und Hashes
        """
        result = {
            "timestamp": datetime.now().isoformat(),
            "directories": [],
            "files": {},
        }
        
        for path in self.base_path.rglob("*"):
            if self._should_ignore(path):
                continue
            
            rel_path = str(path.relative_to(self.base_path))
            
            if path.is_dir():
                result["directories"].append(rel_path)
            elif path.is_file():
                # Hash für Dateien (nur kleine Dateien)
                try:
                    if path.stat().st_size < 100000:  # < 100KB
                        content = path.read_bytes()
                        file_hash = hashlib.md5(content).hexdigest()[:8]
                    else:
                        file_hash = "large"
                    
                    result["files"][rel_path] = {
                        "hash": file_hash,
                        "size": path.stat().st_size
                    }
                except OSError:
                    result["files"][rel_path] = {"hash": "error", "size": 0}
        
        result["directories"].sort()
        
        return result
    
    def load_truth(self) -> Dict:
        """Lädt gespeicherten SOLL-Zustand."""
        if not self.truth_file.exists():
            return {}
        
        try:
            with open(self.truth_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    
    def save_truth(self, state: Dict):
        """Speichert neuen SOLL-Zustand."""
        self.truth_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.truth_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def compare(self, current: Dict, truth: Dict) -> Dict:
        """
        Vergleicht aktuellen Zustand mit SOLL-Zustand.
        
        Returns:
            Dict mit Unterschieden
        """
        diff = {
            "new_dirs": [],
            "deleted_dirs": [],
            "new_files": [],
            "deleted_files": [],
            "modified_files": [],
        }
        
        if not truth:
            return diff
        
        # Verzeichnisse
        current_dirs = set(current.get("directories", []))
        truth_dirs = set(truth.get("directories", []))
        
        diff["new_dirs"] = sorted(current_dirs - truth_dirs)
        diff["deleted_dirs"] = sorted(truth_dirs - current_dirs)
        
        # Dateien
        current_files = current.get("files", {})
        truth_files = truth.get("files", {})
        
        current_paths = set(current_files.keys())
        truth_paths = set(truth_files.keys())
        
        diff["new_files"] = sorted(current_paths - truth_paths)
        diff["deleted_files"] = sorted(truth_paths - current_paths)
        
        # Modifizierte Dateien
        for path in current_paths & truth_paths:
            if current_files[path].get("hash") != truth_files[path].get("hash"):
                diff["modified_files"].append(path)
        
        diff["modified_files"].sort()
        
        return diff
    
    def startup_check(self) -> Tuple[bool, str]:
        """
        Startup-Check: Vergleicht IST mit SOLL.
        
        Returns:
            (has_changes, report)
        """
        current = self.scan()
        truth = self.load_truth()
        
        if not truth:
            # Erster Start - aktuellen Zustand als SOLL speichern
            self.save_truth(current)
            return False, "[DIR-SCAN] Erster Start - SOLL-Zustand initialisiert"
        
        diff = self.compare(current, truth)
        
        # Änderungen zählen
        total_changes = (
            len(diff["new_dirs"]) +
            len(diff["deleted_dirs"]) +
            len(diff["new_files"]) +
            len(diff["deleted_files"]) +
            len(diff["modified_files"])
        )
        
        if total_changes == 0:
            return False, "[DIR-SCAN] Keine externen Änderungen seit letzter Session"
        
        # Report erstellen
        lines = ["[DIR-SCAN] Änderungen seit letzter Session:", ""]
        
        if diff["new_dirs"]:
            lines.append(f"  Neue Ordner: {len(diff['new_dirs'])}")
            for d in diff["new_dirs"][:5]:
                lines.append(f"    + {d}")
            if len(diff["new_dirs"]) > 5:
                lines.append(f"    ... und {len(diff['new_dirs']) - 5} weitere")
        
        if diff["deleted_dirs"]:
            lines.append(f"  Gelöschte Ordner: {len(diff['deleted_dirs'])}")
            for d in diff["deleted_dirs"][:5]:
                lines.append(f"    - {d}")
        
        if diff["new_files"]:
            lines.append(f"  Neue Dateien: {len(diff['new_files'])}")
            for f in diff["new_files"][:5]:
                lines.append(f"    + {f}")
            if len(diff["new_files"]) > 5:
                lines.append(f"    ... und {len(diff['new_files']) - 5} weitere")
        
        if diff["deleted_files"]:
            lines.append(f"  Gelöschte Dateien: {len(diff['deleted_files'])}")
            for f in diff["deleted_files"][:5]:
                lines.append(f"    - {f}")
        
        if diff["modified_files"]:
            lines.append(f"  Geänderte Dateien: {len(diff['modified_files'])}")
            for f in diff["modified_files"][:5]:
                lines.append(f"    ~ {f}")
        
        return True, "\n".join(lines)
    
    def shutdown_update(self) -> str:
        """
        Shutdown: Aktuellen Zustand als neuen SOLL speichern.
        
        Heuristik: Claude-Änderungen sind gewollt.
        """
        current = self.scan()
        old_truth = self.load_truth()
        
        # Diff für Report
        diff = self.compare(current, old_truth) if old_truth else {}
        
        # Neuen SOLL speichern
        self.save_truth(current)
        
        # Report
        total_changes = sum(len(v) for v in diff.values() if isinstance(v, list))
        
        if total_changes == 0:
            return "[DIR-SCAN] Keine Änderungen - SOLL-Zustand unverändert"
        
        return f"[DIR-SCAN] SOLL-Zustand aktualisiert ({total_changes} Änderungen übernommen)"



# CLI-Schnittstelle
if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description="Directory Scanner - IST/SOLL Zustand verwalten",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python dirscan.py                    # Status anzeigen
  python dirscan.py --scan             # Aktuellen Zustand scannen
  python dirscan.py --compare          # Vergleich IST vs SOLL
  python dirscan.py --update           # SOLL-Zustand aktualisieren
  python dirscan.py --path /other/dir  # Anderes Verzeichnis
"""
    )
    parser.add_argument("--scan", action="store_true", help="Aktuellen Zustand scannen und anzeigen")
    parser.add_argument("--compare", action="store_true", help="Vergleich IST vs SOLL")
    parser.add_argument("--update", action="store_true", help="Aktuellen Zustand als neuen SOLL speichern")
    parser.add_argument("--path", type=str, default=None, help="Basis-Pfad (Standard: BACH-Ordner)")
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    
    args = parser.parse_args()
    
    # Basis-Pfad bestimmen
    if args.path:
        base = Path(args.path)
    else:
        base = Path(__file__).parent.parent  # BACH-Ordner
    
    scanner = DirectoryScanner(base)
    
    if args.scan:
        result = scanner.scan()
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"[SCAN] {base}")
            print(f"  Verzeichnisse: {len(result['directories'])}")
            print(f"  Dateien: {len(result['files'])}")
            print(f"  Zeitstempel: {result['timestamp']}")
    
    elif args.compare:
        has_changes, report = scanner.startup_check()
        print(report)
        sys.exit(1 if has_changes else 0)
    
    elif args.update:
        report = scanner.shutdown_update()
        print(report)
    
    else:
        # Status
        truth = scanner.load_truth()
        if truth:
            print(f"[DIRSCAN STATUS]")
            print(f"  Basis: {base}")
            print(f"  SOLL-Zustand: {truth.get('timestamp', 'unbekannt')}")
            print(f"  Verzeichnisse: {len(truth.get('directories', []))}")
            print(f"  Dateien: {len(truth.get('files', {}))}")
            print(f"\nOptionen: --scan, --compare, --update")
        else:
            print(f"[DIRSCAN] Kein SOLL-Zustand vorhanden")
            print(f"  Erstelle mit: python dirscan.py --update")
