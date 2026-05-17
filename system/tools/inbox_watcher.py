#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: inbox_watcher
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version inbox_watcher

Description:
    [Beschreibung hinzufügen]

Usage:
    python inbox_watcher.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
BACH Inbox Watcher - Ordner-Überwachung für automatische Dokumentensortierung
Phase 10 - INBOX_003

Verwendet watchdog für Dateisystem-Events.
Liest Konfiguration aus data/inbox_folders.txt und data/inbox_config.json

Changelog:
- 2026-01-25: v0.6.0 - INBOX_006 OCR-Integration (pytesseract + pdf2image)
- 2026-01-25: v0.5.0 - Daemon-Integration: --process Modus für periodischen Scan (Session 16:05)
- 2026-01-25: v0.4.0 - Dry-run Modus implementiert (Session 15:22)
- 2026-01-25: v0.3.0 - INBOX_007 Manuelle Review-Queue implementiert (Session 15:04)
- 2026-01-25: v0.2.0 - INBOX_005 Sortier-Regeln Engine implementiert (Session 15:04)
- 2026-01-25: v0.1.0 - Grundgerüst erstellt (Session 14:46)
"""

import os
import sys
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# Watchdog für Dateisystem-Überwachung
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    print("[WARN] watchdog nicht installiert: pip install watchdog")

# OCR für Textextraktion (INBOX_006)
try:
    import pytesseract
    from PIL import Image
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

# BACH-Pfade
BACH_ROOT = Path(__file__).parent.parent
DATA_DIR = BACH_ROOT / "data"
USER_DIR = BACH_ROOT / "user"
INBOX_DIR = USER_DIR / "inbox"
INBOX_FOLDERS_FILE = DATA_DIR / "inbox_folders.txt"
INBOX_CONFIG_FILE = DATA_DIR / "inbox_config.json"


class InboxConfig:
    """Lädt und verwaltet inbox_config.json"""
    
    def __init__(self):
        self.config = self._load_config()
    
    def _load_config(self) -> Dict:
        """Lädt inbox_config.json"""
        if INBOX_CONFIG_FILE.exists():
            with open(INBOX_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"settings": {"enabled": False}, "rules": []}
    
    @property
    def enabled(self) -> bool:
        return self.config.get("settings", {}).get("enabled", False)
    
    @property
    def transfer_zone(self) -> Path:
        zone = self.config.get("settings", {}).get("transfer_zone", "user/inbox/unsortiert")
        return BACH_ROOT / zone
    
    @property
    def rules(self) -> List[Dict]:
        return self.config.get("rules", [])
    
    def save_stats(self, processed: int = 0, sorted_count: int = 0, manual: int = 0):
        """Aktualisiert Statistiken"""
        self.config["stats"]["files_processed"] += processed
        self.config["stats"]["files_sorted"] += sorted_count
        self.config["stats"]["files_manual"] += manual
        self.config["stats"]["last_run"] = datetime.now().isoformat()
        
        with open(INBOX_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2)


# ============================================================
# OCR-Funktionen (INBOX_006)
# ============================================================

def extract_text_from_file(filepath: Path, lang: str = "deu+eng") -> str:
    """
    Extrahiert Text aus einer Datei mittels OCR.
    
    Args:
        filepath: Pfad zur Datei
        lang: Tesseract-Sprachcode (deu+eng für Deutsch+Englisch)
    
    Returns:
        Extrahierter Text oder leerer String bei Fehler
    """
    suffix = filepath.suffix.lower()
    
    # Bilder direkt mit OCR
    if suffix in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif']:
        return _ocr_image(filepath, lang)
    
    # PDFs: Seiten zu Bildern konvertieren, dann OCR
    if suffix == '.pdf':
        return _ocr_pdf(filepath, lang)
    
    # Text-Dateien direkt lesen
    if suffix in ['.txt', '.md', '.csv']:
        try:
            return filepath.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return ""
    
    return ""


def _ocr_image(filepath: Path, lang: str = "deu+eng") -> str:
    """OCR für Bilddateien"""
    if not PYTESSERACT_AVAILABLE:
        return ""
    
    try:
        image = Image.open(filepath)
        text = pytesseract.image_to_string(image, lang=lang)
        return text.strip()
    except Exception as e:
        print(f"[OCR] Fehler bei {filepath.name}: {e}")
        return ""


def _ocr_pdf(filepath: Path, lang: str = "deu+eng", max_pages: int = 3) -> str:
    """
    OCR für PDF-Dateien.
    Konvertiert Seiten zu Bildern und führt OCR durch.
    
    Args:
        filepath: Pfad zur PDF
        lang: Tesseract-Sprachcode
        max_pages: Maximale Seitenzahl für OCR (Performance)
    
    Returns:
        Extrahierter Text aus allen Seiten
    """
    if not PYTESSERACT_AVAILABLE or not PDF2IMAGE_AVAILABLE:
        return ""
    
    try:
        # PDF zu Bildern konvertieren (nur erste Seiten für Performance)
        images = convert_from_path(
            filepath, 
            first_page=1, 
            last_page=max_pages,
            dpi=150  # Niedriger DPI für Geschwindigkeit, reicht für Text
        )
        
        all_text = []
        for i, image in enumerate(images, 1):
            text = pytesseract.image_to_string(image, lang=lang)
            if text.strip():
                all_text.append(text.strip())
        
        return "\n".join(all_text)
    
    except Exception as e:
        print(f"[OCR] PDF-Fehler bei {filepath.name}: {e}")
        return ""


class WatchFolder:
    """Repräsentiert einen überwachten Ordner aus inbox_folders.txt"""
    
    def __init__(self, path: str, mode: str = "manual", 
                 file_filter: str = "*", target: str = "inbox"):
        self.path = Path(path)
        self.mode = mode  # manual, auto, review
        self.file_filter = file_filter  # pdf, *, docx|pdf
        self.target = target  # inbox, user/steuer/...
    
    @classmethod
    def from_line(cls, line: str) -> Optional['WatchFolder']:
        """Parst eine Zeile aus inbox_folders.txt"""
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 1:
            return None
        
        path = parts[0]
        mode = parts[1] if len(parts) > 1 else "manual"
        file_filter = parts[2] if len(parts) > 2 else "*"
        target = parts[3] if len(parts) > 3 else "inbox"
        
        return cls(path, mode, file_filter, target)
    
    def matches_filter(self, filename: str) -> bool:
        """Prüft ob Datei dem Filter entspricht"""
        if self.file_filter == "*":
            return True
        
        ext = Path(filename).suffix.lower().lstrip('.')
        filters = self.file_filter.split('|')
        return ext in filters


def load_watch_folders() -> List[WatchFolder]:
    """Lädt alle überwachten Ordner aus inbox_folders.txt"""
    folders = []
    
    if not INBOX_FOLDERS_FILE.exists():
        print(f"[WARN] {INBOX_FOLDERS_FILE} nicht gefunden")
        return folders
    
    with open(INBOX_FOLDERS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            folder = WatchFolder.from_line(line)
            if folder and folder.path.exists():
                folders.append(folder)
            elif folder:
                print(f"[WARN] Ordner existiert nicht: {folder.path}")
    
    return folders


class InboxEventHandler(FileSystemEventHandler):
    """Verarbeitet Dateisystem-Events für überwachte Ordner"""
    
    def __init__(self, watch_folder: WatchFolder, config: InboxConfig):
        self.watch_folder = watch_folder
        self.config = config
        super().__init__()
    
    def on_created(self, event):
        """Wird aufgerufen wenn neue Datei erstellt wird"""
        if event.is_directory:
            return
        
        filename = Path(event.src_path).name
        
        if not self.watch_folder.matches_filter(filename):
            return
        
        print(f"[INBOX] Neue Datei: {filename}")
        
        # TODO: INBOX_005 - Sortier-Regeln Engine
        # Hier wird später die Sortierung implementiert
        self._process_file(event.src_path)
    
    def _process_file(self, filepath: str):
        """Verarbeitet eine Datei gemäß Modus und Regeln"""
        src = Path(filepath)
        
        # Kurz warten bis Datei vollständig geschrieben
        # (watchdog triggert manchmal zu früh)
        import time
        time.sleep(1)
        
        if self.watch_folder.mode == "auto":
            # Automatisch sortieren (INBOX_005)
            self._auto_sort(src)
        elif self.watch_folder.mode == "review":
            # In Transfer-Zone verschieben + Task erstellen
            self._move_to_transfer(src, create_task=True)
        else:  # manual
            # Nur in Transfer-Zone kopieren
            self._move_to_transfer(src, create_task=False)
    
    def _move_to_transfer(self, src: Path, create_task: bool = False):
        """Verschiebt Datei in Transfer-Zone"""
        dest = self.config.transfer_zone / src.name
        
        # Bei Namenskonflikt umbenennen
        if dest.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = self.config.transfer_zone / f"{src.stem}_{timestamp}{src.suffix}"
        
        try:
            shutil.copy2(src, dest)
            print(f"[INBOX] Kopiert nach: {dest}")
            
            if create_task:
                self._create_review_task(src.name)
        except Exception as e:
            print(f"[ERROR] Kopieren fehlgeschlagen: {e}")
    
    def _create_review_task(self, filename: str):
        """Erstellt einen Review-Task für manuelle Sortierung (INBOX_007)"""
        import subprocess
        
        task_title = f"[INBOX] Review: {filename}"
        bach_py = str(BACH_ROOT / "bach.py")
        
        try:
            result = subprocess.run(
                ["python", bach_py, "task", "add", task_title, "--priority", "P3"],
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=10
            )
            if result.returncode == 0:
                print(f"[INBOX] Task erstellt: {task_title}")
            else:
                print(f"[WARN] Task-Erstellung fehlgeschlagen: {result.stderr}")
        except subprocess.TimeoutExpired:
            print(f"[WARN] Task-Erstellung Timeout")
        except Exception as e:
            print(f"[WARN] Task-Erstellung Fehler: {e}")
    
    def _auto_sort(self, src: Path):
        """Automatische Sortierung basierend auf Regeln (INBOX_005 + INBOX_006 OCR)"""
        filename = src.name.lower()
        
        # Regeln nach Priorität sortieren
        sorted_rules = sorted(
            [r for r in self.config.rules if r.get("enabled", True)],
            key=lambda x: x.get("priority", 999)
        )
        
        # OCR-Text nur bei Bedarf extrahieren (Performance)
        ocr_text = None
        has_content_rules = any(r.get("pattern_type") == "content" for r in sorted_rules)
        
        matched_rule = None
        for rule in sorted_rules:
            pattern = rule.get("pattern", "")
            pattern_type = rule.get("pattern_type", "filename")
            
            # Content-matching mit OCR (INBOX_006)
            if pattern_type == "content":
                if ocr_text is None and has_content_rules:
                    print(f"[OCR] Extrahiere Text aus: {src.name}")
                    ocr_text = extract_text_from_file(src)
                    if ocr_text:
                        print(f"[OCR] {len(ocr_text)} Zeichen extrahiert")
                
                if ocr_text:
                    try:
                        if re.search(pattern, ocr_text, re.IGNORECASE):
                            matched_rule = rule
                            print(f"[OCR] Content-Match: '{pattern}'")
                            break
                    except re.error as e:
                        print(f"[WARN] Ungültiges Pattern '{pattern}': {e}")
                continue
            
            # Filename-matching mit Regex
            try:
                if re.search(pattern, filename, re.IGNORECASE):
                    matched_rule = rule
                    break
            except re.error as e:
                print(f"[WARN] Ungültiges Pattern '{pattern}': {e}")
                continue
        
        if matched_rule and matched_rule.get("id") != "fallback":
            # Regel gefunden - Datei sortieren
            target_path = self._resolve_target(matched_rule.get("target", ""))
            self._move_to_target(src, target_path, matched_rule.get("id"))
            self.config.save_stats(processed=1, sorted_count=1)
        else:
            # Keine Regel oder nur Fallback - in Transfer-Zone
            print(f"[INBOX] Keine Regel gefunden für: {filename}")
            self._move_to_transfer(src, create_task=self.config.config.get("settings", {}).get("auto_task_on_unknown", True))
            self.config.save_stats(processed=1, manual=1)
    
    def _resolve_target(self, target: str) -> Path:
        """Löst Platzhalter im Zielpfad auf"""
        # {year} -> aktuelles Jahr
        target = target.replace("{year}", str(datetime.now().year))
        
        # Relativer Pfad -> BACH_ROOT
        target_path = BACH_ROOT / target
        
        # Ordner erstellen falls nicht vorhanden
        target_path.mkdir(parents=True, exist_ok=True)
        
        return target_path
    
        try:
            shutil.copy2(src, dest)
            print(f"[INBOX] Sortiert [{rule_id}]: {src.name} -> {target_dir}")
            
            # NEU: Banking-Sonderlocke (Task #454)
            if rule_id.startswith("banking") and src.suffix.lower() == ".xml":
                print(f"[INBOX] Banking-Dokument erkannt. Starte Bank-Matcher...")
                self._trigger_bank_matcher(dest)
        except Exception as e:
            print(f"[ERROR] Sortieren fehlgeschlagen: {e}")
            # Fallback: In Transfer-Zone
            self._move_to_transfer(src, create_task=True)

    def _trigger_bank_matcher(self, xml_path: Path):
        """Startet den Bank-Matcher für eine neue XML-Datei."""
        import subprocess
        import sys
        matcher_tool = Path(__file__).parent / "steuer" / "bank_matcher.py"
        if matcher_tool.exists():
            subprocess.Popen([sys.executable, str(matcher_tool), str(xml_path)], cwd=str(BACH_ROOT))
        else:
            print(f"[WARN] bank_matcher.py nicht gefunden unter {matcher_tool}")


def dry_run_scan():
    """Scannt alle Watch-Ordner einmalig und zeigt was passieren würde"""
    print("=== INBOX DRY-RUN SCAN ===\n")
    
    config = InboxConfig()
    folders = load_watch_folders()
    
    if not folders:
        print("[INFO] Keine Watch-Ordner konfiguriert")
        return
    
    # Statistiken
    total_files = 0
    would_sort = 0
    would_manual = 0
    
    # Regeln nach Priorität sortieren
    sorted_rules = sorted(
        [r for r in config.rules if r.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )
    
    for folder in folders:
        print(f"[SCAN] {folder.path} ({folder.mode})")
        
        if not folder.path.exists():
            print(f"  [SKIP] Ordner existiert nicht\n")
            continue
        
        # Alle Dateien im Ordner
        files = [f for f in folder.path.iterdir() if f.is_file()]
        
        if not files:
            print(f"  [EMPTY] Keine Dateien\n")
            continue
        
        for file in files:
            if not folder.matches_filter(file.name):
                continue
            
            total_files += 1
            filename = file.name.lower()
            
            # Regel-Matching
            matched_rule = None
            for rule in sorted_rules:
                pattern = rule.get("pattern", "")
                pattern_type = rule.get("pattern_type", "filename")
                
                if pattern_type == "content":
                    continue
                
                try:
                    if re.search(pattern, filename, re.IGNORECASE):
                        matched_rule = rule
                        break
                except re.error:
                    continue
            
            if matched_rule and matched_rule.get("id") != "fallback":
                target = matched_rule.get("target", "").replace("{year}", str(datetime.now().year))
                print(f"  [SORT] {file.name}")
                print(f"         -> {target} (Regel: {matched_rule.get('id')})")
                would_sort += 1
            else:
                action = "Review-Task" if folder.mode == "review" else "Transfer-Zone"
                print(f"  [MANUAL] {file.name}")
                print(f"           -> {config.transfer_zone.name}/ ({action})")
                would_manual += 1
        
        print()
    
    # Zusammenfassung
    print("=== ZUSAMMENFASSUNG ===")
    print(f"Gescannte Dateien: {total_files}")
    print(f"Würden sortiert:   {would_sort}")
    print(f"Manuell/Review:    {would_manual}")
    print("\n[INFO] Dies war ein Dry-Run - keine Dateien wurden verschoben")


def process_scan():
    """
    Scannt alle Watch-Ordner einmalig und führt Sortierung durch.
    Für Daemon-Integration: Periodischer Aufruf statt dauerhaftem Watchdog.
    
    v0.5.0 - Daemon-Integration
    """
    print(f"=== INBOX PROCESS SCAN [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===\n")
    
    config = InboxConfig()
    folders = load_watch_folders()
    
    if not folders:
        print("[INFO] Keine Watch-Ordner konfiguriert")
        return {"processed": 0, "sorted": 0, "manual": 0, "errors": 0}
    
    # Statistiken
    stats = {"processed": 0, "sorted": 0, "manual": 0, "errors": 0}
    
    # Regeln nach Priorität sortieren
    sorted_rules = sorted(
        [r for r in config.rules if r.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )
    
    for folder in folders:
        if not folder.path.exists():
            print(f"[SKIP] {folder.path} existiert nicht")
            continue
        
        # Alle Dateien im Ordner
        files = [f for f in folder.path.iterdir() if f.is_file()]
        
        if not files:
            continue
        
        for file in files:
            if not folder.matches_filter(file.name):
                continue
            
            stats["processed"] += 1
            filename = file.name.lower()
            
            # OCR-Text nur bei Bedarf extrahieren (Performance)
            ocr_text = None
            has_content_rules = any(r.get("pattern_type") == "content" for r in sorted_rules)
            
            # Regel-Matching (mit OCR für content-Rules)
            matched_rule = None
            for rule in sorted_rules:
                pattern = rule.get("pattern", "")
                pattern_type = rule.get("pattern_type", "filename")
                
                # Content-matching mit OCR (INBOX_006)
                if pattern_type == "content":
                    if ocr_text is None and has_content_rules:
                        print(f"[OCR] Extrahiere Text: {file.name}")
                        ocr_text = extract_text_from_file(file)
                    
                    if ocr_text:
                        try:
                            if re.search(pattern, ocr_text, re.IGNORECASE):
                                matched_rule = rule
                                print(f"[OCR] Content-Match: '{pattern}'")
                                break
                        except re.error:
                            continue
                    continue
                
                try:
                    if re.search(pattern, filename, re.IGNORECASE):
                        matched_rule = rule
                        break
                except re.error:
                    continue
            
            # Verarbeitung
            try:
                if matched_rule and matched_rule.get("id") != "fallback":
                    # Regel gefunden - sortieren
                    target_str = matched_rule.get("target", "").replace("{year}", str(datetime.now().year))
                    target_path = BACH_ROOT / target_str
                    target_path.mkdir(parents=True, exist_ok=True)
                    
                    dest = target_path / file.name
                    if dest.exists():
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        dest = target_path / f"{file.stem}_{timestamp}{file.suffix}"
                    
                    shutil.copy2(file, dest)
                    print(f"[SORT] {file.name} -> {target_str} (Regel: {matched_rule.get('id')})")
                    stats["sorted"] += 1
                else:
                    # Keine Regel - in Transfer-Zone
                    transfer = config.transfer_zone
                    transfer.mkdir(parents=True, exist_ok=True)
                    
                    dest = transfer / file.name
                    if dest.exists():
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        dest = transfer / f"{file.stem}_{timestamp}{file.suffix}"
                    
                    shutil.copy2(file, dest)
                    print(f"[MANUAL] {file.name} -> {transfer.name}/")
                    stats["manual"] += 1
                    
                    # Review-Task erstellen wenn konfiguriert
                    if folder.mode == "review" or config.config.get("settings", {}).get("auto_task_on_unknown", True):
                        _create_review_task_standalone(file.name)
                        
            except Exception as e:
                print(f"[ERROR] {file.name}: {e}")
                stats["errors"] += 1
    
    # Statistiken speichern
    try:
        config.save_stats(processed=stats["processed"], sorted_count=stats["sorted"], manual=stats["manual"])
    except Exception:
        pass  # Stats-Fehler nicht kritisch
    
    # Zusammenfassung
    print(f"\n[DONE] Verarbeitet: {stats['processed']} | Sortiert: {stats['sorted']} | Manual: {stats['manual']} | Fehler: {stats['errors']}")
    return stats


def _create_review_task_standalone(filename: str):
    """Erstellt Review-Task (standalone Version für process_scan)"""
    import subprocess
    
    task_title = f"[INBOX] Review: {filename}"
    bach_py = str(BACH_ROOT / "bach.py")
    
    try:
        subprocess.run(
            ["python", bach_py, "task", "add", task_title, "--priority", "P3"],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10
        )
    except Exception:
        pass  # Task-Fehler nicht kritisch


def start_watcher():
    """Startet den Inbox-Watcher"""
    if not WATCHDOG_AVAILABLE:
        print("[ERROR] watchdog muss installiert sein: pip install watchdog")
        return
    
    config = InboxConfig()
    
    if not config.enabled:
        print("[INFO] Inbox-Watcher ist deaktiviert (inbox_config.json settings.enabled)")
        print("[INFO] Aktivieren mit: enabled=true in inbox_config.json")
        return
    
    folders = load_watch_folders()
    
    if not folders:
        print("[INFO] Keine Watch-Ordner konfiguriert")
        return
    
    observer = Observer()
    
    for folder in folders:
        handler = InboxEventHandler(folder, config)
        observer.schedule(handler, str(folder.path), recursive=False)
        print(f"[WATCH] {folder.path} ({folder.mode}, Filter: {folder.file_filter})")
    
    observer.start()
    print(f"\n[INBOX] Watcher gestartet - Überwache {len(folders)} Ordner")
    print("[INBOX] STRG+C zum Beenden\n")
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[INBOX] Watcher beendet")
    
    observer.join()


def main():
    """CLI Einstiegspunkt"""
    import argparse
    
    parser = argparse.ArgumentParser(description="BACH Inbox Watcher")
    parser.add_argument("--test", action="store_true", 
                       help="Zeigt Konfiguration ohne zu starten")
    parser.add_argument("--dry-run", action="store_true",
                       help="Scannt einmalig ohne Überwachung")
    parser.add_argument("--process", action="store_true",
                       help="Scannt und sortiert einmalig (für Daemon-Jobs)")
    
    args = parser.parse_args()
    
    if args.test:
        print("=== INBOX WATCHER KONFIGURATION ===\n")
        config = InboxConfig()
        print(f"Aktiviert: {config.enabled}")
        print(f"Transfer-Zone: {config.transfer_zone}")
        print(f"Regeln: {len(config.rules)}")
        
        print("\n=== WATCH ORDNER ===\n")
        for folder in load_watch_folders():
            status = "[OK]" if folder.path.exists() else "[X]"
            print(f"  {status} {folder.path}")
            print(f"    Mode: {folder.mode}, Filter: {folder.file_filter}")
        return
    
    if args.dry_run:
        dry_run_scan()
        return
    
    if args.process:
        process_scan()
        return
    
    start_watcher()


if __name__ == "__main__":
    main()
