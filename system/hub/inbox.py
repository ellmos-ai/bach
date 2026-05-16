#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Inbox Handler v1.0
=======================
CLI-Handler fuer inbox_watcher Steuerung

Befehle:
  bach inbox start       Inbox-Watcher starten
  bach inbox stop        Inbox-Watcher stoppen
  bach inbox status      Status anzeigen
  bach inbox scan        Einmaliger Dry-Run Scan
  bach inbox config      Konfiguration anzeigen
"""

import os
import sys
import subprocess
import signal
from pathlib import Path
from io import StringIO

# Pfade
HANDLER_DIR = Path(__file__).parent
BACH_DIR = HANDLER_DIR.parent.parent
DATA_DIR = BACH_DIR / "data"
TOOLS_DIR = BACH_DIR / "tools"
INBOX_WATCHER = TOOLS_DIR / "inbox_watcher.py"
INBOX_PID_FILE = DATA_DIR / "inbox_watcher.pid"


class InboxHandler:
    """Handler fuer Inbox-Watcher Steuerung."""

    def __init__(self, base_path: Path = None):
        """Initialisiert den InboxHandler.

        Args:
            base_path: Basis-Pfad des BACH-Systems (fuer Kompatibilitaet mit bach.py)
        """
        self.base_path = base_path or HANDLER_DIR.parent
    
    def _is_running(self) -> tuple:
        """Prueft ob inbox_watcher laeuft."""
        if not INBOX_PID_FILE.exists():
            return False, None
        
        try:
            pid = int(INBOX_PID_FILE.read_text(encoding="utf-8").strip())
            
            # Windows: tasklist pruefen
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                    capture_output=True,
                    text=True
                )
                if str(pid) in result.stdout:
                    return True, pid
            else:
                # Unix: kill -0
                os.kill(pid, 0)
                return True, pid
                
        except (ValueError, ProcessLookupError, OSError):
            pass
        
        # PID-File aufraeumen wenn Prozess nicht existiert
        INBOX_PID_FILE.unlink(missing_ok=True)
        return False, None
    
    def _start(self) -> tuple:
        """Startet inbox_watcher als Hintergrund-Prozess."""
        running, pid = self._is_running()
        
        if running:
            return True, f"[INBOX] Bereits aktiv (PID: {pid})"
        
        if not INBOX_WATCHER.exists():
            return False, f"[ERROR] inbox_watcher.py nicht gefunden: {INBOX_WATCHER}"
        
        # Starten als Hintergrund-Prozess
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            process = subprocess.Popen(
                [sys.executable, str(INBOX_WATCHER)],
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
        else:
            process = subprocess.Popen(
                [sys.executable, str(INBOX_WATCHER)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
        
        # PID speichern
        INBOX_PID_FILE.write_text(str(process.pid))
        
        return True, f"""[INBOX] Watcher gestartet (PID: {process.pid})
        PID-File: {INBOX_PID_FILE}
        
        Stoppen mit: bach inbox stop"""
    
    def _stop(self) -> tuple:
        """Stoppt inbox_watcher."""
        running, pid = self._is_running()
        
        if not running:
            return True, "[INBOX] Nicht aktiv"
        
        try:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                             capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            
            INBOX_PID_FILE.unlink(missing_ok=True)
            return True, f"[INBOX] Gestoppt (PID: {pid})"
            
        except Exception as e:
            return False, f"[ERROR] Stoppen fehlgeschlagen: {e}"
    
    def _status(self) -> tuple:
        """Zeigt Status des inbox_watcher."""
        running, pid = self._is_running()
        
        lines = ["=== INBOX WATCHER STATUS ===\n"]
        
        if running:
            lines.append(f"Status:   [RUNNING]")
            lines.append(f"PID:      {pid}")
        else:
            lines.append(f"Status:   [STOPPED]")
        
        lines.append(f"Script:   {INBOX_WATCHER}")
        lines.append(f"PID-File: {INBOX_PID_FILE}")
        
        # Konfiguration laden
        try:
            sys.path.insert(0, str(BACH_DIR))
            from tools.inbox_watcher import InboxConfig, load_watch_folders
            config = InboxConfig()
            folders = load_watch_folders()
            
            lines.append(f"\n--- Konfiguration ---")
            lines.append(f"Aktiviert:     {config.enabled}")
            lines.append(f"Transfer-Zone: {config.transfer_zone}")
            lines.append(f"Regeln:        {len(config.rules)}")
            lines.append(f"Watch-Ordner:  {len(folders)}")
        except Exception as e:
            lines.append(f"\n[WARN] Konfiguration nicht ladbar: {e}")
        
        return True, "\n".join(lines)
    
    def _scan(self) -> tuple:
        """Fuehrt einen Dry-Run Scan aus."""
        result = subprocess.run(
            [sys.executable, str(INBOX_WATCHER), '--dry-run'],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return True, result.stdout + result.stderr
    
    def _config(self) -> tuple:
        """Zeigt Konfiguration."""
        result = subprocess.run(
            [sys.executable, str(INBOX_WATCHER), '--test'],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return True, result.stdout + result.stderr
    
    def handle(self, operation: str, args: list) -> tuple:
        """Handler-Einstiegspunkt (BaseHandler-kompatibel)."""
        
        if not operation or operation == 'status':
            return self._status()
        elif operation == 'start':
            return self._start()
        elif operation == 'stop':
            return self._stop()
        elif operation == 'scan':
            return self._scan()
        elif operation == 'config':
            return self._config()
        else:
            return True, """BACH Inbox Handler
==================

Befehle:
  bach inbox start     Inbox-Watcher starten (Hintergrund)
  bach inbox stop      Inbox-Watcher stoppen
  bach inbox status    Status anzeigen
  bach inbox scan      Einmaliger Dry-Run Scan
  bach inbox config    Konfiguration anzeigen
"""


def get_handler():
    """Factory-Funktion fuer Handler."""
    return InboxHandler()


if __name__ == "__main__":
    handler = InboxHandler()
    op = sys.argv[1] if len(sys.argv) > 1 else "status"
    args = sys.argv[2:] if len(sys.argv) > 2 else []
    success, msg = handler.handle(op, args)
    print(msg)
