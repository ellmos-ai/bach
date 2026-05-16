#!/usr/bin/env python3
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
BACH Inbox Scanner Service
==========================

Automatische Ueberwachung von Eingangsordnern und regelbasierte Sortierung.

Tasks: INBOX_001-008 (Phase 10)
"""

import os
import json
import re
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# Optional: watchdog fuer Echtzeit-Ueberwachung
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

# BACH Paths
BACH_DIR = Path(__file__).parent.parent.parent.parent
DATA_DIR = BACH_DIR / "data"
USER_DIR = BACH_DIR / "user"

FOLDERS_FILE = DATA_DIR / "inbox_folders.txt"
CONFIG_FILE = DATA_DIR / "inbox_config.json"


@dataclass
class ScanResult:
    """Ergebnis eines Scan-Durchlaufs."""
    processed: int = 0
    sorted: int = 0
    unsorted: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class RuleEngine:
    """Regel-Engine fuer Dokumenten-Matching (INBOX_005)."""

    def __init__(self, config: Dict[str, Any]):
        self.settings = config.get("settings", {})
        self.rules = config.get("rules", [])
        self.fallback = config.get("fallback", {})

        # Sortiere Regeln nach Prioritaet
        self.rules.sort(key=lambda r: r.get("priority", 100))

    def match(self, filepath: Path, content: str = "") -> Optional[Dict[str, Any]]:
        """Findet passende Regel fuer Datei.

        Args:
            filepath: Pfad zur Datei
            content: Extrahierter Textinhalt (optional)

        Returns:
            Passende Regel oder None
        """
        filename = filepath.name.lower()
        content_lower = content.lower() if content else ""

        for rule in self.rules:
            if self._check_conditions(rule.get("conditions", {}), filename, content_lower):
                return rule

        return None

    def _check_conditions(self, conditions: Dict, filename: str, content: str) -> bool:
        """Prueft ob Bedingungen erfuellt sind."""
        # Filename-Check
        filename_patterns = conditions.get("filename_contains", [])
        if filename_patterns:
            if not any(p.lower() in filename for p in filename_patterns):
                return False

        # Content-Check (nur wenn Content vorhanden)
        content_patterns = conditions.get("content_contains", [])
        if content_patterns and content:
            if not any(p.lower() in content for p in content_patterns):
                return False

        # Regex-Check (optional)
        regex_pattern = conditions.get("filename_regex")
        if regex_pattern:
            if not re.search(regex_pattern, filename, re.IGNORECASE):
                return False

        return True

    def get_target_path(self, rule: Dict[str, Any]) -> Path:
        """Generiert Zielpfad mit Variablen-Ersetzung."""
        target = rule.get("target", self.fallback.get("target", ""))

        # Variable {year} ersetzen
        year = datetime.now().year
        target = target.replace("{year}", str(year))

        return Path(target)


class InboxScanner:
    """Haupt-Scanner-Service (INBOX_003)."""

    def __init__(self):
        self.config = self._load_config()
        self.folders = self._load_folders()
        self.rule_engine = RuleEngine(self.config)
        self._observer = None

    def _load_config(self) -> Dict[str, Any]:
        """Laedt Konfiguration aus inbox_config.json."""
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"[Scanner] Config-Fehler: {e}")
        return {"settings": {}, "rules": [], "fallback": {}}

    def _load_folders(self) -> List[Path]:
        """Laedt zu ueberwachende Ordner aus inbox_folders.txt."""
        folders = []
        if FOLDERS_FILE.exists():
            for line in FOLDERS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    # Format: PFAD | MODUS | FILTER | ZIEL
                    parts = line.split("|")
                    path_str = parts[0].strip()
                    path = Path(path_str)
                    
                    if path.exists() and path.is_dir():
                        folders.append(path)
                    else:
                        # Versuche relative Pfade aufzulösen (ab USER_DIR)
                        rel_path = USER_DIR / path_str
                        if rel_path.exists() and rel_path.is_dir():
                            folders.append(rel_path)
                        else:
                            print(f"[Scanner] Ordner nicht gefunden: {path_str}")
        return folders

    def scan_once(self) -> ScanResult:
        """Fuehrt einmaligen Scan aller Ordner durch."""
        result = ScanResult()

        for folder in self.folders:
            try:
                for filepath in folder.iterdir():
                    if filepath.is_file() and not filepath.name.startswith("."):
                        self._process_file(filepath, result)
            except PermissionError as e:
                result.errors.append(f"Zugriff verweigert: {folder}")

        return result

    def _process_file(self, filepath: Path, result: ScanResult):
        """Verarbeitet einzelne Datei."""
        result.processed += 1

        # Warte bis Datei stabil (nicht mehr geschrieben wird)
        if not self._wait_for_stable(filepath):
            return

        # Inhaltsextraktion (optional)
        content = self._extract_content(filepath)

        # Regel-Matching
        rule = self.rule_engine.match(filepath, content)

        if rule:
            target_dir = self.rule_engine.get_target_path(rule)
            self._move_file(filepath, target_dir, rule, result)
            result.sorted += 1
        else:
            # Fallback: Unsortiert
            fallback_dir = Path(self.config.get("fallback", {}).get("target", USER_DIR / "inbox" / "unsortiert"))
            self._move_file(filepath, fallback_dir, None, result)
            result.unsorted += 1

    def _wait_for_stable(self, filepath: Path, timeout: int = 30) -> bool:
        """Wartet bis Datei nicht mehr geschrieben wird."""
        wait_seconds = self.config.get("settings", {}).get("stable_wait_seconds", 5)

        try:
            last_size = -1
            stable_count = 0

            for _ in range(timeout):
                current_size = filepath.stat().st_size
                if current_size == last_size:
                    stable_count += 1
                    if stable_count >= 2:
                        return True
                else:
                    stable_count = 0
                    last_size = current_size
                time.sleep(wait_seconds / 2)

            return True  # Timeout, aber versuche trotzdem
        except FileNotFoundError:
            return False

    def _extract_content(self, filepath: Path) -> str:
        """Extrahiert Text aus Datei (INBOX_006 OCR)."""
        suffix = filepath.suffix.lower()

        # PDF-Extraktion
        if suffix == ".pdf":
            try:
                from .pdf_service import extract_text_from_pdf
                return extract_text_from_pdf(str(filepath))
            except ImportError:
                pass

        # Textdateien
        if suffix in [".txt", ".md", ".csv"]:
            try:
                return filepath.read_text(encoding="utf-8", errors="ignore")[:5000]
            except OSError:
                pass

        # OCR fuer Bilder (falls aktiviert)
        if suffix in [".jpg", ".jpeg", ".png", ".tiff"] and self.config.get("settings", {}).get("ocr_enabled"):
            try:
                from .ocr_service import extract_text_from_image
                return extract_text_from_image(str(filepath))
            except ImportError:
                pass

        return ""

    def _move_file(self, filepath: Path, target_dir: Path, rule: Optional[Dict], result: ScanResult):
        """Verschiebt Datei in Zielordner."""
        try:
            # Zielordner erstellen
            target_dir.mkdir(parents=True, exist_ok=True)

            # Dateiname (optional: umbenennen)
            new_name = filepath.name
            if rule and "rename_with_date" in rule.get("actions", []):
                date_prefix = datetime.now().strftime("%Y-%m-%d_")
                new_name = date_prefix + filepath.name

            target_path = target_dir / new_name

            # Duplikat-Handling
            if target_path.exists():
                base = target_path.stem
                suffix = target_path.suffix
                counter = 1
                while target_path.exists():
                    target_path = target_dir / f"{base}_{counter}{suffix}"
                    counter += 1

            # Move oder Copy
            move_mode = self.config.get("settings", {}).get("move_mode", "move")
            if move_mode == "copy":
                shutil.copy2(filepath, target_path)
            else:
                shutil.move(str(filepath), str(target_path))

            print(f"[Scanner] {filepath.name} -> {target_path}")

        except Exception as e:
            result.errors.append(f"Fehler bei {filepath.name}: {e}")

    def start_watch(self):
        """Startet Echtzeit-Ueberwachung (INBOX_003 Watchdog)."""
        if not WATCHDOG_AVAILABLE:
            print("[Scanner] watchdog nicht installiert. Nutze 'pip install watchdog'.")
            return False

        class InboxHandler(FileSystemEventHandler):
            def __init__(self, scanner):
                self.scanner = scanner

            def on_created(self, event):
                if isinstance(event, FileCreatedEvent):
                    filepath = Path(event.src_path)
                    if filepath.is_file() and not filepath.name.startswith("."):
                        result = ScanResult()
                        self.scanner._process_file(filepath, result)

        self._observer = Observer()
        handler = InboxHandler(self)

        for folder in self.folders:
            self._observer.schedule(handler, str(folder), recursive=False)
            print(f"[Scanner] Ueberwache: {folder}")

        self._observer.start()
        return True

    def stop_watch(self):
        """Stoppt Echtzeit-Ueberwachung."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def get_status(self) -> Dict[str, Any]:
        """Liefert Scanner-Status."""
        return {
            "enabled": self.config.get("settings", {}).get("enabled", False),
            "watching": self._observer is not None and self._observer.is_alive(),
            "folders_count": len(self.folders),
            "rules_count": len(self.rule_engine.rules),
            "folders": [str(f) for f in self.folders]
        }


# ═══════════════════════════════════════════════════════════════
# CLI Interface
# ═══════════════════════════════════════════════════════════════

def main():
    """CLI Einstiegspunkt."""
    import sys

    scanner = InboxScanner()

    if len(sys.argv) < 2:
        print("Usage: python scanner_service.py [run|watch|status]")
        return

    cmd = sys.argv[1]

    if cmd == "run":
        print("[Scanner] Starte Scan...")
        result = scanner.scan_once()
        print(f"[Scanner] Ergebnis: {result.processed} verarbeitet, {result.sorted} sortiert, {result.unsorted} unsortiert")
        if result.errors:
            print(f"[Scanner] Fehler: {result.errors}")

    elif cmd == "watch":
        print("[Scanner] Starte Ueberwachung... (Ctrl+C zum Beenden)")
        if scanner.start_watch():
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                scanner.stop_watch()
                print("\n[Scanner] Gestoppt.")

    elif cmd == "status":
        status = scanner.get_status()
        print(f"[Scanner] Status: {json.dumps(status, indent=2)}")

    else:
        print(f"Unbekannter Befehl: {cmd}")


if __name__ == "__main__":
    main()
