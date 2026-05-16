#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: autolog
Version: 1.0.1
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-08
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version autolog

Description:
    Auto-Logging System - Protokolliert alle BACH Aktionen
    Log-Pfad konsolidiert nach data/logs/ (2026-02-06)

Usage:
    python autolog.py [args]
"""

__version__ = "1.0.1"
__author__ = "BACH Team"

"""
Auto-Logger - Protokolliert automatisch alle Aktionen
=====================================================

Zweistufiges System:
1. auto_log.txt        - Letzte 300 Zeilen (Kurzzeitgedaechtnis)
2. auto_log_extended.txt - Aeltere Eintraege, max 30 Tage (Archiv)

Nach 30 Tagen werden Eintraege endgueltig geloescht.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


MAX_LINES = 300           # Maximale Zeilen im Haupt-Log
ARCHIVE_DAYS = 30         # Tage im Extended-Archiv


class AutoLogger:
    """Automatisches Logging aller Aktionen."""
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.log_file = self.base_path / "data" / "logs" / "auto_log.txt"
        self.extended_file = self.base_path / "data" / "logs" / "auto_log_extended.txt"
        
        # Verzeichnis sicherstellen
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Cleanup bei Start
        self._cleanup_if_needed()
        self._cleanup_extended()
    
    def _cleanup_if_needed(self):
        """Verschiebt alte Eintraege ins Extended-Archiv wenn Log zu gross."""
        if not self.log_file.exists():
            return
        
        try:
            lines = self.log_file.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_LINES:
                # Alte Zeilen ins Extended-Archiv verschieben
                old_lines = lines[:-MAX_LINES]
                keep_lines = lines[-MAX_LINES:]
                
                # Ans Extended-Archiv anhaengen
                with open(self.extended_file, "a", encoding="utf-8") as f:
                    f.write("\n".join(old_lines) + "\n")
                
                # Haupt-Log kuerzen
                self.log_file.write_text("\n".join(keep_lines) + "\n", encoding="utf-8")
                
        except Exception:
            pass  # Nicht kritisch
    
    def _cleanup_extended(self):
        """Entfernt Eintraege aelter als ARCHIVE_DAYS aus dem Extended-Archiv."""
        if not self.extended_file.exists():
            return
        
        try:
            cutoff = datetime.now() - timedelta(days=ARCHIVE_DAYS)
            lines = self.extended_file.read_text(encoding="utf-8").splitlines()
            
            kept_lines = []
            for line in lines:
                # Datum aus Zeile extrahieren [YYYY-MM-DD HH:MM:SS] oder [HH:MM:SS]
                if line.startswith("["):
                    try:
                        # Neues Format: [2026-01-17 02:20:22]
                        if len(line) > 20 and line[5] == "-":
                            date_str = line[1:11]  # YYYY-MM-DD
                            line_date = datetime.strptime(date_str, "%Y-%m-%d")
                            if line_date >= cutoff:
                                kept_lines.append(line)
                            continue
                    except (ValueError, IndexError):
                        pass

                    # Altes Format ohne Datum: behalten (koennen wir nicht datieren)
                    kept_lines.append(line)
                else:
                    # Cleanup-Marker oder andere Zeilen: behalten
                    kept_lines.append(line)
            
            # Nur schreiben wenn sich was geaendert hat
            if len(kept_lines) < len(lines):
                removed = len(lines) - len(kept_lines)
                self.extended_file.write_text(
                    f"[--- {removed} Eintraege aelter als {ARCHIVE_DAYS} Tage entfernt ---]\n" +
                    "\n".join(kept_lines) + "\n",
                    encoding="utf-8"
                )
                
        except Exception:
            pass  # Nicht kritisch
    
    def _write_log(self, message: str):
        """Schreibt direkt in Log-Datei."""
        now = datetime.now()
        # Format: [YYYY-MM-DD HH:MM:SS] message
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}\n"
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[LOG ERROR] {e}", file=sys.stderr)
    
    def log(self, message: str):
        """Loggt eine Nachricht mit Timestamp."""
        self._write_log(message)
    
    def cmd(self, command: str, args: list = None, result: str = ""):
        """Loggt einen ausgefuehrten Befehl."""
        args_str = " ".join(str(a) for a in (args or []))
        if args_str:
            self._write_log(f"CMD: {command} {args_str}")
        else:
            self._write_log(f"CMD: {command}")
    
    def tool(self, tool_name: str, args: list = None):
        """Loggt Tool-Aufruf."""
        args_str = " ".join(str(a) for a in (args or []))
        self._write_log(f"TOOL: {tool_name} {args_str}")
    
    def session_start(self):
        """Markiert Session-Start."""
        self._write_log("SESSION START")
    
    def session_end(self, summary: str = None):
        """Markiert Session-Ende."""
        if summary:
            self._write_log(f"SESSION END: {summary}")
        else:
            self._write_log("SESSION END")


# Globale Instanz
_logger: Optional[AutoLogger] = None


def get_logger(base_path: Path = None) -> AutoLogger:
    """Gibt Logger-Instanz zurueck (Singleton)."""
    global _logger
    
    if _logger is None:
        if base_path is None:
            base_path = Path(__file__).parent.parent
        _logger = AutoLogger(base_path)
    
    return _logger


def log(message: str):
    """Shortcut fuer Logging."""
    get_logger().log(message)


def cmd(command: str, args: list = None, result: str = ""):
    """Shortcut fuer Command-Logging."""
    get_logger().cmd(command, args, result)


def tool(tool_name: str, args: list = None):
    """Shortcut fuer Tool-Logging."""
    get_logger().tool(tool_name, args)



# CLI-Schnittstelle
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Auto-Logger - Protokolliert alle Aktionen",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python autolog.py                    # Letzte 20 Eintraege
  python autolog.py --tail 50          # Letzte 50 Eintraege
  python autolog.py --extended         # Extended-Archiv anzeigen
  python autolog.py --count            # Anzahl Eintraege
  python autolog.py --log "Test"       # Manueller Eintrag
"""
    )
    parser.add_argument("--tail", type=int, nargs="?", const=20, default=None, help="Letzte n Eintraege (Standard: 20)")
    parser.add_argument("--extended", action="store_true", help="Extended-Archiv anzeigen")
    parser.add_argument("--count", action="store_true", help="Anzahl Eintraege anzeigen")
    parser.add_argument("--log", type=str, help="Manuellen Eintrag schreiben")
    parser.add_argument("--path", type=str, default=None, help="Basis-Pfad (Standard: BACH-Ordner)")
    
    args = parser.parse_args()
    
    # Logger initialisieren
    base = Path(args.path) if args.path else Path(__file__).parent.parent
    logger = get_logger(base)
    
    if args.log:
        logger.log(args.log)
        print(f"[OK] Eintrag geschrieben: {args.log}")
    
    elif args.count:
        main_count = 0
        ext_count = 0
        if logger.log_file.exists():
            main_count = len(logger.log_file.read_text(encoding="utf-8").splitlines())
        if logger.extended_file.exists():
            ext_count = len(logger.extended_file.read_text(encoding="utf-8").splitlines())
        print(f"[AUTOLOG]")
        print(f"  Haupt-Log:  {main_count} Eintraege (max {MAX_LINES})")
        print(f"  Extended:   {ext_count} Eintraege")
        print(f"  Gesamt:     {main_count + ext_count} Eintraege")
    
    elif args.extended:
        if logger.extended_file.exists():
            content = logger.extended_file.read_text(encoding="utf-8")
            print(content)
        else:
            print("[INFO] Kein Extended-Archiv vorhanden")
    
    else:
        # Standard: Tail anzeigen
        n = args.tail if args.tail else 20
        if logger.log_file.exists():
            lines = logger.log_file.read_text(encoding="utf-8").splitlines()
            for line in lines[-n:]:
                print(line)
            if len(lines) > n:
                print(f"\n[...] {len(lines) - n} aeltere Eintraege nicht angezeigt")
        else:
            print("[INFO] Noch keine Log-Eintraege")
