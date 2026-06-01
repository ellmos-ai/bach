# SPDX-License-Identifier: MIT
"""
GUI Handler - Web-Server Verwaltung
===================================

bach gui start         Server starten
bach gui stop          Server stoppen
bach gui status        Server-Status anzeigen
"""
import sys
import subprocess
import time
from pathlib import Path
from .base import BaseHandler


class GuiHandler(BaseHandler):
    """Handler fuer gui Operationen"""

    BACKGROUND_STARTUP_TIMEOUT_SECONDS = 5.0
    BACKGROUND_STARTUP_POLL_SECONDS = 0.25
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.gui_dir = base_path / "gui"
        self.server_script = self.gui_dir / "server.py"
    
    @property
    def profile_name(self) -> str:
        return "gui"
    
    @property
    def target_file(self) -> Path:
        return self.gui_dir
    
    def get_operations(self) -> dict:
        return {
            "start": "Web-Server starten (--port X fuer anderen Port)",
            "start-bg": "Web-Server im Hintergrund starten",
            "stop": "Web-Server stoppen",
            "status": "Server-Status anzeigen",
            "info": "GUI-Informationen anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "start":
            port = 8000
            if "--port" in args:
                idx = args.index("--port")
                if idx + 1 < len(args):
                    try:
                        port = int(args[idx + 1])
                    except ValueError:
                        pass
            return self._start_server(port, dry_run)
        elif operation == "start-bg":
            port = 8000
            if "--port" in args:
                idx = args.index("--port")
                if idx + 1 < len(args):
                    try:
                        port = int(args[idx + 1])
                    except ValueError:
                        pass
            return self._start_background(port, dry_run)
        elif operation == "stop":
            port = 8000
            if "--port" in args:
                idx = args.index("--port")
                if idx + 1 < len(args):
                    try:
                        port = int(args[idx + 1])
                    except ValueError:
                        pass
            return self._stop_server(port)
        elif operation == "status":
            return self._show_status()
        elif operation == "info":
            return self._show_info()
        else:
            return self._show_info()
    
    def _start_server(self, port: int, dry_run: bool) -> tuple:
        """Startet den GUI-Server."""
        if not self.server_script.exists():
            return (False, f"[ERROR] Server-Script nicht gefunden: {self.server_script}")
        
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Server starten auf Port {port}")
        
        # Pruefen ob uvicorn installiert ist
        try:
            import uvicorn
        except ImportError:
            return (False, "[ERROR] uvicorn nicht installiert!\n        pip install fastapi uvicorn")
        
        output = [
            "[OK] Starte BACH GUI Server...",
            f"     URL: http://127.0.0.1:{port}",
            f"     API: http://127.0.0.1:{port}/docs",
            "",
            "     Druecke Ctrl+C zum Beenden"
        ]
        
        print("\n".join(output))
        
        # Server starten (blockiert)
        try:
            sys.path.insert(0, str(self.gui_dir))
            from server import run_server
            run_server(port=port)
        except KeyboardInterrupt:
            return (True, "\n[OK] Server beendet.")
        except Exception as e:
            return (False, f"[ERROR] Server-Fehler: {e}")
        
        return (True, "[OK] Server beendet.")
    
    def _start_background(self, port: int, dry_run: bool) -> tuple:
        """Startet den GUI-Server im Hintergrund."""
        if not self.server_script.exists():
            return (False, f"[ERROR] Server-Script nicht gefunden: {self.server_script}")
        
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Server im Hintergrund starten auf Port {port}")
        
        if self._is_port_open(port):
            return (True, f"[OK] GUI Server laeuft bereits auf Port {port}")
        
        # Server im Hintergrund starten
        try:
            if sys.platform == "win32":
                CREATE_NO_WINDOW = 0x08000000
                subprocess.Popen(
                    [sys.executable, str(self.server_script), "--port", str(port)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
            else:
                subprocess.Popen(
                    [sys.executable, str(self.server_script), "--port", str(port)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            
            if self._wait_for_port(
                port,
                timeout_seconds=self.BACKGROUND_STARTUP_TIMEOUT_SECONDS,
                poll_interval=self.BACKGROUND_STARTUP_POLL_SECONDS,
            ):
                return (True, f"[OK] GUI Server gestartet (http://127.0.0.1:{port})")
            return (False, f"[WARN] Server gestartet, aber Port {port} antwortet nicht")
                
        except Exception as e:
            return (False, f"[ERROR] Konnte Server nicht starten: {e}")

    def _is_port_open(self, port: int) -> bool:
        """Prueft ob ein lokaler TCP-Port bereits Verbindungen annimmt."""
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            return sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()

    def _wait_for_port(
        self,
        port: int,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> bool:
        """Wartet kurz auf asynchron gestartete Serverprozesse."""
        attempts = max(1, int(timeout_seconds / poll_interval))
        for attempt in range(attempts):
            if self._is_port_open(port):
                return True
            if attempt < attempts - 1:
                time.sleep(poll_interval)
        return False

    def _find_pid_on_port(self, port: int) -> int:
        """Findet die PID des Prozesses auf einem Port."""
        import re
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "TCP"],
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=10
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) < 5 or parts[0].upper() != "TCP":
                        continue
                    if not parts[1].endswith(f":{port}"):
                        continue
                    if parts[-1].isdigit():
                        return int(parts[-1])
            else:
                result = subprocess.run(
                    ["lsof", "-i", f":{port}", "-t"],
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=10
                )
                if result.stdout.strip():
                    return int(result.stdout.strip().splitlines()[0])
        except Exception:
            pass
        return None

    def _stop_server(self, port: int) -> tuple:
        """Stoppt den GUI-Server auf dem angegebenen Port."""
        import socket
        import signal

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()

        if result != 0:
            return (True, f"[OK] Kein Server aktiv auf Port {port}")

        pid = self._find_pid_on_port(port)
        if not pid:
            return (False, f"[ERROR] Server laeuft auf Port {port}, aber PID nicht ermittelbar")

        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=10
                )
            else:
                import os
                os.kill(pid, signal.SIGTERM)

            import time
            time.sleep(1)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            still_running = sock.connect_ex(('127.0.0.1', port)) == 0
            sock.close()

            if still_running:
                return (False, f"[WARN] Server (PID {pid}) konnte nicht gestoppt werden")
            return (True, f"[OK] Server gestoppt (PID {pid})")
        except Exception as e:
            return (False, f"[ERROR] Konnte Prozess {pid} nicht beenden: {e}")

    def _show_status(self) -> tuple:
        """Zeigt Server-Status."""
        port = 8000
        if self._is_port_open(port):
            pid = self._find_pid_on_port(port)
            pid_info = f" (PID {pid})" if pid else ""
            status = f"[ONLINE] Server laeuft auf Port {port}{pid_info}"
        else:
            status = "[OFFLINE] Server nicht aktiv"

        output = [
            "=== GUI STATUS ===",
            "",
            status,
            "",
            f"Server-Script: {self.server_script}",
            f"Existiert: {'Ja' if self.server_script.exists() else 'Nein'}"
        ]

        return (True, "\n".join(output))
    
    def _show_info(self) -> tuple:
        """Zeigt GUI-Informationen."""
        # Dateien zaehlen
        templates = list((self.gui_dir / "templates").glob("*.html")) if (self.gui_dir / "templates").exists() else []
        css_files = list((self.gui_dir / "static" / "css").glob("*.css")) if (self.gui_dir / "static" / "css").exists() else []
        js_files = list((self.gui_dir / "static" / "js").glob("*.js")) if (self.gui_dir / "static" / "js").exists() else []
        
        output = [
            "=== GUI INFO ===",
            "",
            f"GUI-Verzeichnis: {self.gui_dir}",
            f"Server-Script:   {self.server_script}",
            "",
            "--- Dateien ---",
            f"Templates: {len(templates)}",
            f"CSS:       {len(css_files)}",
            f"JS:        {len(js_files)}",
            "",
            "--- Befehle ---",
            "bach gui start         Server starten",
            "bach gui start --port 9000  Anderer Port",
            "bach gui status        Status pruefen"
        ]
        
        return (True, "\n".join(output))
