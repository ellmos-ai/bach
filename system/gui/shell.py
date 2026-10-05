#!/usr/bin/env python3
"""GUI-Schale: verbindet oder startet den BACH-GUI-Server unter Rollen-Autorisierung.

Quelle: QUEUED 652455601 (externes Ticketsystem T-20260926-170164898 /
T-20260926-658915805, Body lokal nicht verfuegbar; minimale Umsetzung aus
Tasktitel #1410 + Code-Struktur server.py/chat_tray.py).

Kette: #1410 GUI-Schale (QUEUED 652455601) -> #1414 Tray (QUEUED 112086128)
-> #1416 composition.rules.json (QUEUED 387788448).

Ablauf run():
  1. begin_assignment() mit Rolle/Modus. Fail-closed: unbekannte Rolle oder
     Modus ausserhalb {"safe","full"} -> AssignmentDenied -> status "denied".
  2. connect_or_start(): Health-Check GET {base_url}/api/status. Antwortet der
     Server, wird verbunden (started=False); sonst startet _start_server()
     gui/server.py als Kind-Prozess (server_command) und pollt bis
     start_timeout auf Bereitschaft.
  3. open_window(): Browser/Opener auf base_url (optional, --no-browser).
  4. finish_assignment(): "completed" (gui_ready), "released"
     (window_open_failed) oder "error" (gui_connect_failed). Aktivitaeten
     landen via record_activity in der Slots-Aktivitaetshistorie
     (slot_id "gui_shell").
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

GUI_DIR = Path(__file__).resolve().parent
SYSTEM_DIR = GUI_DIR.parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from hub._services.agents_heart import (  # noqa: E402  (Import nach Path-Bootstrap)
    AssignmentDenied,
    begin_assignment,
    finish_assignment,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_ROLE_ID = "expert_role"
DEFAULT_MODE = "safe"
DEFAULT_TASK_ID = "1410"
HEALTH_PATH = "/api/status"

# Endstatus-Werte von finish_assignment (vgl. hub/_services/agents_heart.py).
_STATUS_COMPLETED = "completed"
_STATUS_RELEASED = "released"
_STATUS_ERROR = "error"


def parse_gui_url(url):
    """GUI-URL 'http://host:port/...' -> (host, port:int); Default-Port 80."""
    text = str(url or "").strip()
    if text.startswith("http://"):
        text = text[len("http://"):]
    text = text.split("/", 1)[0].rstrip("/")
    if not text:
        return (DEFAULT_HOST, DEFAULT_PORT)
    host, sep, port_text = text.rpartition(":")
    if sep and host:
        try:
            return (host, int(port_text))
        except ValueError:
            return (text, 80)
    return (text, 80)


class GUIShell:
    """GUI-Schale: Health-Check, Serverstart, Verbindung, Rollen-Autorisierung."""

    def __init__(
        self,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        role_id=DEFAULT_ROLE_ID,
        mode=DEFAULT_MODE,
        server_command=None,
        opener=None,
        log_dir=None,
        slots_config_path=None,
        start_timeout=30.0,
        poll_interval=0.5,
    ):
        self.host = str(host)
        self.port = int(port)
        self.role_id = role_id
        # Bewusst KEINE mode-Validierung im Konstruktor: ungueltige Modi laufen
        # in begin_assignment fail-closed auf AssignmentDenied -> status "denied".
        self.mode = mode
        self.opener = opener
        self.slots_config_path = slots_config_path
        self.start_timeout = float(start_timeout)
        self.poll_interval = float(poll_interval)
        self.base_url = f"http://{self.host}:{self.port}"
        self.log_dir = Path(log_dir) if log_dir is not None else SYSTEM_DIR / "data" / "logs"
        if server_command is None:
            server_command = [
                sys.executable,
                str(GUI_DIR / "server.py"),
                "--host",
                str(self.host),
                "--port",
                str(self.port),
            ]
        self.server_command = list(server_command)
        self.process = None

    # ------------------------------------------------------------------ helpers

    def check_health(self, timeout=2.0):
        """True, wenn GET {base_url}{HEALTH_PATH} mit HTTP 200 antwortet.

        Muster: chat_tray._check_url — True nur bei status==200, sonst False.
        """
        status_url = self.base_url + HEALTH_PATH
        try:
            with urlopen(status_url, timeout=timeout) as resp:
                if getattr(resp, "status", None) == 200:
                    return True
                return False
        except (URLError, OSError):
            return False

    def _start_server(self):
        """Startet server_command als Kind-Prozess. Rueckgabe (ok, error)."""
        log_file = None
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = open(self.log_dir / "gui_shell.log", "ab")
        except OSError:
            log_file = None  # Fallback: DEVNULL (Design: log_file oder DEVNULL)
        try:
            self.process = subprocess.Popen(
                self.server_command,
                shell=False,
                stdout=log_file if log_file is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            if log_file is not None:
                log_file.close()
            self.process = None
            return (False, f"Server-Prozess konnte nicht gestartet werden: {exc}")
        if log_file is not None:
            # Der Kind-Prozess erbt den Deskriptor; im Parent schliessen.
            log_file.close()
        return (True, "")

    def connect_or_start(self):
        """Server verbinden oder starten. Rueckgabe {connected,started,url,error}."""
        if self.check_health():
            return {
                "connected": True,
                "started": False,
                "url": self.base_url,
                "error": "",
            }
        ok, error = self._start_server()
        if not ok:
            return {
                "connected": False,
                "started": False,
                "url": self.base_url,
                "error": error,
            }
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                rc = self.process.returncode
                return {
                    "connected": False,
                    "started": True,
                    "url": self.base_url,
                    "error": f"Server-Prozess endete vor Bereitschaft (exit {rc})",
                }
            if self.check_health():
                return {
                    "connected": True,
                    "started": True,
                    "url": self.base_url,
                    "error": "",
                }
            time.sleep(self.poll_interval)
        return {
            "connected": False,
            "started": True,
            "url": self.base_url,
            "error": (
                f"Server nicht bereit nach {self.start_timeout}s "
                f"({self.base_url}{HEALTH_PATH})"
            ),
        }

    def open_window(self):
        """Oeffnet base_url (self.opener oder webbrowser). Rueckgabe bool."""
        try:
            opened = (self.opener or webbrowser.open)(self.base_url)
        except Exception:
            return False
        return bool(opened)

    # --------------------------------------------------------------------- flow

    def _result(self, ok, started, connected, window_opened,
                assignment_id, status, error):
        """Einheitliches Ergebnis-dict (ok nur bei completed)."""
        return {
            "ok": bool(ok),
            "url": self.base_url,
            "started": bool(started),
            "connected": bool(connected),
            "window_opened": bool(window_opened),
            "assignment_id": assignment_id,
            "status": status,
            "error": error,
        }

    def run(self, task_id=DEFAULT_TASK_ID, open_window=True):
        """Kompletter Ablauf mit Assignment-Autorisierung (siehe Modul-Docstring)."""
        try:
            assignment = begin_assignment(
                role_id=self.role_id,
                mode=self.mode,
                agent_instance_id=f"gui-shell-{os.getpid()}",
                backend_id="bach-gui",
                model_id="web-gui",
                slot_id="gui_shell",
                task_id=task_id,
                session_id=str(uuid.uuid4()),
                initiated_by="user",
                path=self.slots_config_path,
            )
        except AssignmentDenied as exc:
            return self._result(
                ok=False,
                started=False,
                connected=False,
                window_opened=False,
                assignment_id="",
                status="denied",
                error=f"AssignmentDenied: {exc}",
            )

        connect = self.connect_or_start()
        if not connect["connected"]:
            finish_assignment(
                assignment,
                status=_STATUS_ERROR,
                reason=connect["error"],
                result="gui_connect_failed",
                path=self.slots_config_path,
            )
            return self._result(
                ok=False,
                started=connect["started"],
                connected=False,
                window_opened=False,
                assignment_id=assignment.assignment_id,
                status=_STATUS_ERROR,
                error=connect["error"],
            )

        window_opened = False
        if open_window:
            window_opened = self.open_window()
            if not window_opened:
                finish_assignment(
                    assignment,
                    status=_STATUS_RELEASED,
                    result="window_open_failed",
                    path=self.slots_config_path,
                )
                return self._result(
                    ok=False,
                    started=connect["started"],
                    connected=True,
                    window_opened=False,
                    assignment_id=assignment.assignment_id,
                    status=_STATUS_RELEASED,
                    error="GUI-Fenster konnte nicht geoeffnet werden",
                )

        finish_assignment(
            assignment,
            status=_STATUS_COMPLETED,
            result="gui_ready",
            path=self.slots_config_path,
        )
        return self._result(
            ok=True,
            started=connect["started"],
            connected=True,
            window_opened=window_opened,
            assignment_id=assignment.assignment_id,
            status=_STATUS_COMPLETED,
            error="",
        )

    # ------------------------------------------------------------------- config

    @classmethod
    def from_env(cls, environ=None):
        """Instanz aus BACH_GUI_URL > BACH_GUI_HOST/BACH_GUI_PORT > Defaults."""
        env = os.environ if environ is None else environ
        url = env.get("BACH_GUI_URL")
        if url:
            host, port = parse_gui_url(url)
            return cls(host=host, port=port)
        host = env.get("BACH_GUI_HOST") or DEFAULT_HOST
        port_text = env.get("BACH_GUI_PORT")
        port = int(port_text) if port_text else DEFAULT_PORT
        return cls(host=host, port=port)


def main(argv=None):
    """CLI: GUI-Schale verbinden/starten und Ergebnis als JSON drucken."""
    parser = argparse.ArgumentParser(
        prog="gui-shell",
        description=(
            "BACH GUI-Schale: GUI-Server verbinden/starten mit "
            "Rollen-Autorisierung (QUEUED 652455601)."
        ),
    )
    parser.add_argument("--host", default=os.environ.get("BACH_GUI_HOST") or DEFAULT_HOST)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BACH_GUI_PORT") or DEFAULT_PORT),
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("BACH_GUI_URL") or "",
        help="GUI-URL (Default: BACH_GUI_URL); ueberschreibt --host/--port",
    )
    parser.add_argument("--role", default=DEFAULT_ROLE_ID)
    parser.add_argument("--mode", choices=["safe", "full"], default=DEFAULT_MODE)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--no-browser", action="store_true",
                        help="GUI nicht im Browser oeffnen")
    parser.add_argument("--check-only", action="store_true",
                        help="Nur Health-Check; JSON drucken; exit 1 wenn down")
    parser.add_argument("--start-timeout", type=float, default=30.0)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--slots-config", default=None)
    args = parser.parse_args(argv)

    host, port = args.host, args.port
    if args.url:
        host, port = parse_gui_url(args.url)

    shell = GUIShell(
        host=host,
        port=port,
        role_id=args.role,
        mode=args.mode,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        slots_config_path=args.slots_config,
        start_timeout=args.start_timeout,
    )

    if args.check_only:
        ok = shell.check_health()
        print(json.dumps(
            {"ok": ok, "url": shell.base_url, "status": "ok" if ok else "down"},
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0 if ok else 1

    result = shell.run(task_id=args.task_id, open_window=not args.no_browser)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))