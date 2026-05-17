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
BACH Claude Bridge - System Tray Manager
==========================================
Startet und ueberwacht den Claude Bridge Daemon.
Zeigt Status im System Tray (gruen=aktiv, gelb=pause, rot=gestoppt).

Usage:
  python bridge_tray.py              Tray-App starten
  pythonw bridge_tray.py             Tray-App ohne Konsole starten

Version: 1.0.0
Erstellt: 2026-02-11
"""

import json
import os
import sys
import subprocess
import tempfile
import time
import threading
from datetime import datetime
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERROR] pystray/Pillow nicht installiert: pip install pystray Pillow")
    sys.exit(1)

# ============ PFADE ============

BRIDGE_DIR = Path(__file__).parent.resolve()
DAEMON_SCRIPT = BRIDGE_DIR / "bridge_daemon.py"
WRAPPER_SCRIPT = BRIDGE_DIR / "bridge_fackel_wrapper.py"
CONFIG_FILE = BRIDGE_DIR / "config.json"
STATE_FILE = BRIDGE_DIR / "state.json"
BACH_DIR = BRIDGE_DIR.parent.parent.parent
LOG_FILE = BACH_DIR / "data" / "logs" / "claude_bridge.log"

# ============ ICON ERSTELLEN ============

def create_icon(color: str, size: int = 64) -> Image.Image:
    """Erstellt ein einfaches rundes Icon mit Farbe."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    colors = {
        "green": (76, 175, 80),
        "yellow": (255, 193, 7),
        "red": (244, 67, 54),
        "gray": (158, 158, 158),
    }
    rgb = colors.get(color, colors["gray"])

    # Aeusserer Kreis (Schatten)
    draw.ellipse([2, 2, size - 2, size - 2], fill=(*rgb, 255))
    # Innerer Glanz
    draw.ellipse([8, 8, size - 12, size - 12], fill=(*[min(c + 40, 255) for c in rgb], 200))

    return img


# ============ TRAY APP ============

class BridgeTray:
    """System Tray Manager fuer den Claude Bridge Daemon."""

    def __init__(self):
        self.daemon_proc = None
        self.state = "stopped"  # stopped, running, paused
        self.permission_mode = "restricted"
        self.budget_enabled = True
        self.budget_spent = 0.0
        self.budget_limit = 5.0
        self.voice_mode = False
        self.max_turns = 0  # 0 = kein Limit
        self.chat_timeout = 0  # 0 = kein Timeout
        self.current_model = "sonnet"
        self.watchdog_active = True
        self.lock = threading.Lock()

        # Initialen State laden
        self._sync_budget_from_state()

        # Config laden
        self.config = self._load_config()

        self.icon = pystray.Icon(
            name="BACH Bridge",
            icon=create_icon("gray"),
            title="BACH Bridge: Initialisiere...",
            menu=self._build_menu()
        )

        # Autostart-Check
        if self.config.get('bridge', {}).get('autostart', False):
            should_start = self._should_autostart(self.config)
            if should_start:
                self.log("Autostart aktiviert - Bridge wird gestartet", "INFO")
                # Startet in run() nach Icon-Initialisierung
            else:
                self.log("Autostart blockiert (Connector fehlt oder Fackel blockiert)", "WARN")

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "Start",
                self._on_start,
                visible=lambda item: self.state != "running",
            ),
            pystray.MenuItem(
                "Pause",
                self._on_pause,
                visible=lambda item: self.state == "running",
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: f"Modus: {self.permission_mode.upper()}",
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                lambda text: "Auf Vollzugriff wechseln" if self.permission_mode == "restricted" else "Auf Eingeschraenkt wechseln",
                self._on_toggle_mode,
                visible=lambda item: self.state == "running",
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: f"Budget: ${self.budget_spent:.2f}/${self.budget_limit:.2f} [{'AN' if self.budget_enabled else 'AUS'}]",
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                lambda text: "Budget ausschalten" if self.budget_enabled else "Budget einschalten",
                self._on_toggle_budget,
            ),
            pystray.MenuItem(
                "Budget-Limit setzen",
                pystray.Menu(
                    pystray.MenuItem("$5", lambda icon, item: self._on_set_budget(5.0)),
                    pystray.MenuItem("$10", lambda icon, item: self._on_set_budget(10.0)),
                    pystray.MenuItem("$20", lambda icon, item: self._on_set_budget(20.0)),
                    pystray.MenuItem("$50", lambda icon, item: self._on_set_budget(50.0)),
                    pystray.MenuItem("Eigener Betrag...", self._on_set_budget_custom),
                ),
            ),
            pystray.MenuItem(
                "Budget zuruecksetzen",
                self._on_reset_budget,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: f"Voice: {'AN' if self.voice_mode else 'AUS'}",
                self._on_toggle_voice,
                visible=lambda item: self.state == "running",
            ),
            pystray.MenuItem(
                "Max-Turns setzen",
                pystray.Menu(
                    pystray.MenuItem(
                        lambda text: "Kein Limit (aktuell)" if self.max_turns == 0 else "Kein Limit",
                        lambda icon, item: self._on_set_max_turns(0)
                    ),
                    pystray.MenuItem(
                        lambda text: "10 Turns (aktuell)" if self.max_turns == 10 else "10 Turns",
                        lambda icon, item: self._on_set_max_turns(10)
                    ),
                    pystray.MenuItem(
                        lambda text: "20 Turns (aktuell)" if self.max_turns == 20 else "20 Turns",
                        lambda icon, item: self._on_set_max_turns(20)
                    ),
                    pystray.MenuItem(
                        lambda text: "50 Turns (aktuell)" if self.max_turns == 50 else "50 Turns",
                        lambda icon, item: self._on_set_max_turns(50)
                    ),
                    pystray.MenuItem("Eigener Wert...", self._on_set_max_turns_custom),
                ),
                visible=lambda item: self.state == "running",
            ),
            pystray.MenuItem(
                lambda text: f"Timeout: {'AUS' if self.chat_timeout == 0 else str(self.chat_timeout) + 's'}",
                pystray.Menu(
                    pystray.MenuItem(
                        lambda text: "AUS (aktuell)" if self.chat_timeout == 0 else "AUS",
                        lambda icon, item: self._on_set_timeout(0)
                    ),
                    pystray.MenuItem(
                        lambda text: "120s (aktuell)" if self.chat_timeout == 120 else "120s",
                        lambda icon, item: self._on_set_timeout(120)
                    ),
                    pystray.MenuItem(
                        lambda text: "300s (aktuell)" if self.chat_timeout == 300 else "300s",
                        lambda icon, item: self._on_set_timeout(300)
                    ),
                    pystray.MenuItem(
                        lambda text: "600s (aktuell)" if self.chat_timeout == 600 else "600s",
                        lambda icon, item: self._on_set_timeout(600)
                    ),
                    pystray.MenuItem("Eigener Wert...", self._on_set_timeout_custom),
                ),
                visible=lambda item: self.state == "running",
            ),
            pystray.MenuItem(
                lambda text: f"Modell: {self.current_model.upper()}",
                pystray.Menu(
                    pystray.MenuItem(
                        lambda text: "Sonnet (aktuell)" if self.current_model == "sonnet" else "Sonnet",
                        lambda icon, item: self._on_set_model("sonnet")
                    ),
                    pystray.MenuItem(
                        lambda text: "Opus (aktuell)" if self.current_model == "opus" else "Opus",
                        lambda icon, item: self._on_set_model("opus")
                    ),
                    pystray.MenuItem(
                        lambda text: "Haiku (aktuell)" if self.current_model == "haiku" else "Haiku",
                        lambda icon, item: self._on_set_model("haiku")
                    ),
                ),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Status",
                self._on_status,
            ),
            pystray.MenuItem(
                "Logs oeffnen",
                self._on_logs,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Beenden",
                self._on_quit,
            ),
        )

    # ---------- ACTIONS ----------

    def _on_start(self, icon, item):
        self._start_daemon()

    def _on_pause(self, icon, item):
        self._stop_daemon()
        self.state = "paused"
        self.watchdog_active = False
        self._update_icon()

    def _on_toggle_mode(self, icon, item):
        """Toggle Berechtigungsmodus via Daemon --test Kommando."""
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [sys.executable, str(DAEMON_SCRIPT), "--test", "toggle"],
                capture_output=True, text=True, timeout=5, env=env,
                encoding='utf-8', errors='replace'
            )
            if result.returncode != 0:
                icon.notify(f"Toggle fehlgeschlagen (Exit {result.returncode})", "BACH Bridge Fehler")
                return
            # Modus wird beim naechsten Watchdog-Zyklus synchronisiert
            # Sofort toggeln fuer responsives UI
            if self.permission_mode == "restricted":
                self.permission_mode = "full"
                icon.notify("Vollzugriff aktiviert", "BACH Bridge")
            else:
                self.permission_mode = "restricted"
                icon.notify("Eingeschraenkter Modus", "BACH Bridge")
            self._update_icon()
        except Exception as e:
            icon.notify(f"Toggle fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_toggle_budget(self, icon, item):
        """Toggle Budget ein/aus."""
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            cmd = "budget off" if self.budget_enabled else "budget on"
            result = subprocess.run(
                [sys.executable, str(DAEMON_SCRIPT), "--test", cmd],
                capture_output=True, timeout=5, env=env,
                encoding='utf-8', errors='replace'
            )
            if result.returncode != 0:
                icon.notify(f"Budget-Toggle fehlgeschlagen (Exit {result.returncode})", "BACH Bridge Fehler")
                return
            # State direkt aktualisieren fuer responsives UI
            self.budget_enabled = not self.budget_enabled
            self._update_state_file_budget(enabled=self.budget_enabled)
            status = "eingeschaltet" if self.budget_enabled else "ausgeschaltet"
            icon.notify(f"Budget {status}", "BACH Bridge")
            self._update_icon()
        except Exception as e:
            icon.notify(f"Budget-Toggle fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_set_budget(self, amount: float):
        """Setzt Budget-Limit auf einen bestimmten Betrag."""
        try:
            cfg = {}
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if "budget" not in cfg:
                cfg["budget"] = {}
            cfg["budget"]["daily_limit_usd"] = amount
            CONFIG_FILE.write_text(
                json.dumps(cfg, indent=4, ensure_ascii=False),
                encoding="utf-8"
            )
            self.budget_limit = amount
            self.icon.notify(f"Budget-Limit: ${amount:.2f}/Tag", "BACH Bridge")
            self._update_icon()
        except Exception as e:
            self.icon.notify(f"Budget setzen fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_set_budget_custom(self, icon, item):
        """Oeffnet Eingabedialog fuer eigenen Budget-Betrag."""
        def _ask():
            try:
                import tkinter as tk
                from tkinter import simpledialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                result = simpledialog.askfloat(
                    "BACH Budget-Limit",
                    "Neues Tageslimit in USD:",
                    initialvalue=self.budget_limit,
                    minvalue=0.5,
                    maxvalue=1000.0,
                    parent=root
                )
                root.destroy()
                if result is not None:
                    self._on_set_budget(result)
            except Exception as e:
                icon.notify(f"Eingabe fehlgeschlagen: {e}", "BACH Bridge Fehler")
        threading.Thread(target=_ask, daemon=True).start()

    def _on_reset_budget(self, icon, item):
        """Setzt den Budget-Verbrauch auf 0 zurueck."""
        try:
            self.budget_spent = 0.0
            self._update_state_file_budget(spent=0.0)
            icon.notify("Budget zurueckgesetzt ($0.00)", "BACH Bridge")
            self._update_icon()
        except Exception as e:
            icon.notify(f"Budget-Reset fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_toggle_voice(self, icon, item):
        """Toggle Voice-Modus ein/aus."""
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            cmd = "voice off" if self.voice_mode else "voice on"
            result = subprocess.run(
                [sys.executable, str(DAEMON_SCRIPT), "--test", cmd],
                capture_output=True, timeout=5, env=env,
                encoding='utf-8', errors='replace'
            )
            if result.returncode != 0:
                icon.notify(f"Voice-Toggle fehlgeschlagen (Exit {result.returncode})", "BACH Bridge Fehler")
                return
            self.voice_mode = not self.voice_mode
            self._update_state_file(voice_mode=self.voice_mode)
            status = "aktiviert" if self.voice_mode else "deaktiviert"
            icon.notify(f"Voice-Modus {status}", "BACH Bridge")
        except Exception as e:
            icon.notify(f"Voice-Toggle fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_set_model(self, model_name: str):
        """Setzt das Claude-Modell und synchronisiert mit Daemon."""
        try:
            old = self.current_model
            self.current_model = model_name
            self._update_state_file(current_model=model_name)
            self.icon.notify(f"Modell: {old} -> {model_name.upper()}", "BACH Bridge")
            self._update_icon()
        except Exception as e:
            self.icon.notify(f"Modell-Wechsel fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_set_max_turns(self, turns: int):
        """Setzt Max-Turns in state.json."""
        try:
            self.max_turns = turns
            self._update_state_file(max_turns=turns)
            label = "kein Limit" if turns == 0 else f"{turns} Turns"
            self.icon.notify(f"Max-Turns: {label}", "BACH Bridge")
        except Exception as e:
            self.icon.notify(f"Max-Turns setzen fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_set_max_turns_custom(self, icon, item):
        """Oeffnet Eingabedialog fuer eigene Max-Turns."""
        def _ask():
            try:
                import tkinter as tk
                from tkinter import simpledialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                result = simpledialog.askinteger(
                    "BACH Max-Turns",
                    "Max Tool-Calls pro Antwort (0 = kein Limit):",
                    initialvalue=self.max_turns,
                    minvalue=0,
                    maxvalue=500,
                    parent=root
                )
                root.destroy()
                if result is not None:
                    self._on_set_max_turns(result)
            except Exception as e:
                icon.notify(f"Eingabe fehlgeschlagen: {e}", "BACH Bridge Fehler")
        threading.Thread(target=_ask, daemon=True).start()

    def _on_set_timeout(self, seconds: int):
        """Setzt Chat-Timeout in state.json."""
        try:
            self.chat_timeout = seconds
            self._update_state_file(chat_timeout=seconds)
            label = "AUS" if seconds == 0 else f"{seconds}s"
            self.icon.notify(f"Chat-Timeout: {label}", "BACH Bridge")
        except Exception as e:
            self.icon.notify(f"Timeout setzen fehlgeschlagen: {e}", "BACH Bridge Fehler")

    def _on_set_timeout_custom(self, icon, item):
        """Oeffnet Eingabedialog fuer eigenen Timeout-Wert."""
        def _ask():
            try:
                import tkinter as tk
                from tkinter import simpledialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                result = simpledialog.askinteger(
                    "BACH Chat-Timeout",
                    "Inaktivitaets-Timeout in Sekunden (0 = kein Timeout):",
                    initialvalue=self.chat_timeout,
                    minvalue=0,
                    maxvalue=3600,
                    parent=root
                )
                root.destroy()
                if result is not None:
                    self._on_set_timeout(result)
            except Exception as e:
                icon.notify(f"Eingabe fehlgeschlagen: {e}", "BACH Bridge Fehler")
        threading.Thread(target=_ask, daemon=True).start()

    def _update_state_file(self, enabled=None, spent=None, voice_mode=None, max_turns=None, current_model=None, chat_timeout=None):
        """Aktualisiert Felder direkt in state.json."""
        try:
            state = {}
            if STATE_FILE.exists():
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if enabled is not None:
                state["budget_enabled"] = enabled
            if spent is not None:
                state["daily_spent"] = spent
            if voice_mode is not None:
                state["voice_mode"] = voice_mode
            if max_turns is not None:
                state["max_turns"] = max_turns
            if current_model is not None:
                state["current_model"] = current_model
            if chat_timeout is not None:
                state["chat_timeout"] = chat_timeout
            STATE_FILE.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _update_state_file_budget(self, enabled=None, spent=None):
        """Aktualisiert Budget-Felder direkt in state.json (Rueckwaertskompatibilitaet)."""
        self._update_state_file(enabled=enabled, spent=spent)

    def _load_config(self) -> dict:
        """Lädt config.json."""
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {}

    def _should_autostart(self, config: dict) -> bool:
        """
        Prüft ob Bridge automatisch starten soll.

        Regeln:
        1. Connector konfiguriert → JA
        2. start_without_connectors=true → JA
        3. Fackel blockiert → NEIN
        """
        # 1. Connector-Check
        telegram_enabled = config.get('enabled', False)
        has_connector = telegram_enabled

        # 2. start_without_connectors
        start_without = config.get('bridge', {}).get('start_without_connectors', True)

        if not has_connector and not start_without:
            self.log("Kein Connector konfiguriert und start_without_connectors=false", "INFO")
            return False

        # 3. Fackel-Check
        if config.get('bridge', {}).get('fackel_check', True):
            try:
                sys.path.insert(0, str(BRIDGE_DIR))
                from fackel import get_fackel_holder, get_pc_name
                holder = get_fackel_holder('bridge')
                if holder and holder != get_pc_name():
                    self.log(f"Fackel blockiert von {holder}", "WARN")
                    return False
            except Exception as e:
                self.log(f"Fackel-Check fehlgeschlagen: {e}", "ERROR")

        return True

    def log(self, msg: str, level: str = "INFO"):
        """Schreibt Log-Eintrag."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [Tray] [{level}] {msg}"
        print(line)
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _sync_budget_from_state(self):
        """Liest State aus state.json und config.json."""
        try:
            if STATE_FILE.exists():
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self.budget_enabled = state.get("budget_enabled", True)
                self.budget_spent = state.get("daily_spent", 0.0)
                self.voice_mode = state.get("voice_mode", False)
                self.max_turns = state.get("max_turns", 0)
                self.chat_timeout = state.get("chat_timeout", 0)
                self.current_model = state.get("current_model", "sonnet")
        except Exception:
            pass
        try:
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.budget_limit = cfg.get("budget", {}).get("daily_limit_usd", 5.0)
        except Exception:
            pass

    def _on_status(self, icon, item):
        """Zeigt Status-Notification."""
        if self.state == "running":
            budget_status = f"{'AN' if self.budget_enabled else 'AUS'}"
            pid_str = f"PID {self.daemon_proc.pid}" if self.daemon_proc else "extern"
            turns_str = "kein Limit" if self.max_turns == 0 else str(self.max_turns)
            timeout_str = "AUS" if self.chat_timeout == 0 else f"{self.chat_timeout}s"
            msg = (f"Bridge laeuft ({pid_str})\n"
                   f"Modell: {self.current_model.upper()}\n"
                   f"Modus: {self.permission_mode}\n"
                   f"Budget: ${self.budget_spent:.2f}/${self.budget_limit:.2f} [{budget_status}]\n"
                   f"Voice: {'AN' if self.voice_mode else 'AUS'}\n"
                   f"Max-Turns: {turns_str}\n"
                   f"Timeout: {timeout_str}")
        elif self.state == "paused":
            msg = "Bridge pausiert"
        else:
            msg = "Bridge gestoppt"
        icon.notify(msg, "BACH Bridge Status")

    def _on_logs(self, icon, item):
        """Oeffnet Log-Datei im Standard-Editor."""
        if LOG_FILE.exists():
            if sys.platform == "win32":
                os.startfile(str(LOG_FILE))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(LOG_FILE)])
            else:
                subprocess.Popen(["xdg-open", str(LOG_FILE)])
        else:
            icon.notify("Keine Logs vorhanden", "BACH Bridge")

    def _on_quit(self, icon, item):
        """Beendet alles: Daemon + Tray."""
        self.watchdog_active = False
        self._stop_daemon()
        self.state = "stopped"
        icon.stop()

    # ---------- DAEMON MANAGEMENT ----------

    def _is_daemon_running_externally(self) -> bool:
        """Prueft ob ein Bridge-Daemon bereits auf diesem PC laeuft (nicht von uns gestartet).

        Nutzt die PID aus der Daemon-Lock-Datei (bach_bridge.lock).
        NICHT die Fackel — die Fackel ist System-Ebene (welcher PC darf laufen),
        nicht Prozess-Ebene (laeuft gerade ein Prozess).
        """
        try:
            import tempfile, ctypes
            daemon_lock = Path(tempfile.gettempdir()) / "bach_bridge.lock"
            if not daemon_lock.exists():
                return False
            pid_text = daemon_lock.read_text(encoding="utf-8").strip()
            if not pid_text:
                return False
            pid = int(pid_text)
            if sys.platform == "win32":
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                import os as _os
                try:
                    _os.kill(pid, 0)
                    return True
                except OSError:
                    return False
        except Exception:
            return False

    def _start_daemon(self):
        with self.lock:
            if self.daemon_proc and self.daemon_proc.poll() is None:
                return  # Laeuft bereits (unser Kind)

            # Pruefe ob ein externer Daemon bereits laeuft
            if self._is_daemon_running_externally():
                self.state = "running"
                self.daemon_proc = None
                self.watchdog_active = True
                self._update_icon()
                self.log("Externe Bridge-Instanz erkannt - angehangen", "INFO")
                return

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            creation_flags = (
                subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0
            )

            # Fackel-Wrapper nutzen?
            use_wrapper = self.config.get('bridge', {}).get('use_fackel_wrapper', True)
            script = WRAPPER_SCRIPT if use_wrapper else DAEMON_SCRIPT

            try:
                self.daemon_proc = subprocess.Popen(
                    [sys.executable, str(script)],
                    cwd=str(BRIDGE_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    creationflags=creation_flags,
                )
                self.state = "running"
                self.watchdog_active = True
                self._update_icon()
                mode_label = "Fackel-Wrapper" if use_wrapper else "Direkt"
                self.log(f"Bridge gestartet ({mode_label})", "INFO")
            except Exception as e:
                self.state = "stopped"
                self._update_icon()
                self.icon.notify(f"Start fehlgeschlagen: {e}", "BACH Bridge Fehler")
                self.log(f"Start fehlgeschlagen: {e}", "ERROR")

    def _stop_daemon(self):
        with self.lock:
            if self.daemon_proc and self.daemon_proc.poll() is None:
                # Sauber stoppen ueber --stop
                try:
                    env = os.environ.copy()
                    env["PYTHONIOENCODING"] = "utf-8"
                    subprocess.run(
                        [sys.executable, str(DAEMON_SCRIPT), "--stop"],
                        capture_output=True, text=True, timeout=10,
                        env=env,
                        encoding='utf-8', errors='replace'
                    )
                except Exception:
                    pass

                # Falls noch aktiv: kill
                try:
                    if self.daemon_proc.poll() is None:
                        self.daemon_proc.terminate()
                        self.daemon_proc.wait(timeout=5)
                except Exception:
                    try:
                        self.daemon_proc.kill()
                    except Exception:
                        pass

            self.daemon_proc = None

    def _update_icon(self):
        colors = {
            "running": "green",
            "paused": "yellow",
            "stopped": "red",
        }
        titles = {
            "running": "BACH Bridge: Aktiv",
            "paused": "BACH Bridge: Pausiert",
            "stopped": "BACH Bridge: Gestoppt",
        }
        if self.daemon_proc and self.state == "running":
            mode_label = "VOLL" if self.permission_mode == "full" else "EINGESCHR."
            budget_label = f"${self.budget_spent:.2f}/${self.budget_limit:.2f}" if self.budget_enabled else "Budget AUS"
            titles["running"] = f"BACH Bridge: Aktiv [{mode_label}] {budget_label}"

        self.icon.icon = create_icon(colors.get(self.state, "gray"))
        self.icon.title = titles.get(self.state, "BACH Bridge")

    # ---------- WATCHDOG ----------

    def _sync_mode_from_log(self):
        """Liest aktuellen Modus aus dem Log (fuer Sync bei Telegram-Toggle)."""
        try:
            if not LOG_FILE.exists():
                return
            lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
            for line in reversed(lines[-30:]):
                if "MODUS: full" in line:
                    if self.permission_mode != "full":
                        self.permission_mode = "full"
                        self._update_icon()
                    return
                if "MODUS: restricted" in line:
                    if self.permission_mode != "restricted":
                        self.permission_mode = "restricted"
                        self._update_icon()
                    return
        except Exception:
            pass

    def _watchdog_loop(self):
        """Ueberwacht Daemon-Prozess und startet bei Crash neu.

        Erkennt auch extern gestartete Daemons und haengt sich dran an,
        statt endlos neue Instanzen zu spawnen.
        """
        time.sleep(3)  # Kurz warten nach Start

        while getattr(self.icon, '_running', False):
            # Modus und Budget vom Daemon synchronisieren
            self._sync_mode_from_log()
            self._sync_budget_from_state()

            if self.watchdog_active and self.state == "running":
                child_dead = (self.daemon_proc is None or
                              self.daemon_proc.poll() is not None)

                if child_dead:
                    # Unser Kind ist tot (oder wir haben keins) --
                    # aber vielleicht laeuft ein externer Daemon?
                    if self._is_daemon_running_externally():
                        # Externer Daemon aktiv → einfach mitlaufen
                        self.daemon_proc = None
                        if self.state != "running":
                            self.state = "running"
                            self._update_icon()
                    else:
                        # Wirklich tot → pruefen ob Fackel-Verlust
                        exit_code = (self.daemon_proc.returncode
                                     if self.daemon_proc else -1)
                        self.state = "stopped"
                        self._update_icon()

                        if exit_code == 2:
                            # Fackel durch anderen PC uebernommen → Tray beendet sich
                            self.watchdog_active = False
                            self.icon.notify(
                                "Fackel an anderen PC abgegeben. Tray wird beendet.",
                                "BACH Bridge Fackel"
                            )
                            self.log("Fackel verloren (Exit 2) - Tray beendet sich", "WARN")
                            time.sleep(2)
                            self.icon.stop()
                        else:
                            self.icon.notify(
                                f"Bridge gestoppt (Exit {exit_code}). Neustart in 5s...",
                                "BACH Bridge Watchdog"
                            )
                            time.sleep(5)

                            if self.watchdog_active:
                                self._start_daemon()

            elif self.state != "running" and self.state != "paused":
                # Gestoppt aber externer Daemon laeuft? → anhangen
                if self._is_daemon_running_externally():
                    self.state = "running"
                    self.watchdog_active = True
                    self._update_icon()
                    self.log("Externer Daemon erkannt - Status aktualisiert", "INFO")

            time.sleep(3)

    # ---------- RUN ----------

    def run(self):
        """Startet Tray-App: Icon + Daemon + Watchdog."""
        # Daemon starten (nur wenn Autostart aktiv oder kein Autostart-Flag)
        if self.config.get('bridge', {}).get('autostart', False):
            if self._should_autostart(self.config):
                self._start_daemon()
        else:
            # Kein Autostart konfiguriert → Daemon trotzdem starten (bisheriges Verhalten)
            self._start_daemon()

        # Watchdog in eigenem Thread
        watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        watchdog.start()

        # Tray-Icon ausfuehren (blockiert)
        self.icon.run()


# ============ DUPLIKAT-SPERRE ============

LOCK_FILE = Path(tempfile.gettempdir()) / "bach_bridge_tray.lock"
_tray_lock_handle = None


def _check_single_instance() -> bool:
    """Verhindert mehrfachen Start der Tray-App.

    Nutzt OS-Level Advisory Lock: msvcrt.locking (Windows) bzw. fcntl.flock (Unix).
    Bei Prozessabbruch gibt das OS das Dateihandle automatisch frei →
    naechster Start kann den Lock problemlos erwerben.
    """
    global _tray_lock_handle
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _tray_lock_handle = open(LOCK_FILE, "a+", encoding="utf-8")
        if sys.platform == "win32":
            import msvcrt
            _tray_lock_handle.seek(0)
            msvcrt.locking(_tray_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_tray_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _tray_lock_handle.seek(0)
        _tray_lock_handle.truncate()
        _tray_lock_handle.write(str(os.getpid()))
        _tray_lock_handle.flush()
        return True
    except (OSError, IOError):
        if _tray_lock_handle:
            _tray_lock_handle.close()
            _tray_lock_handle = None
        return False


def _cleanup_lock():
    global _tray_lock_handle
    if _tray_lock_handle:
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    _tray_lock_handle.seek(0)
                    msvcrt.locking(_tray_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(_tray_lock_handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            _tray_lock_handle.close()
        except Exception:
            pass
        _tray_lock_handle = None
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

# ============ MAIN ============

if __name__ == "__main__":
    if not _check_single_instance():
        # Bereits eine Instanz aktiv
        sys.exit(0)
    try:
        app = BridgeTray()
        app.run()
    finally:
        _cleanup_lock()
