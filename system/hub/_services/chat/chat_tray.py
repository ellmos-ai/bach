#!/usr/bin/env python3
"""
BACH Unified System Tray
========================

Cross-platform (macOS/Windows/Linux) System Tray für das BACH OS.
Steuert: Chat-Backend, Services, Prompts (PromptBoard), Idle Worker.

Voraussetzungen:
  pip install pystray Pillow

Start:
  python chat_tray.py [--port 8081] [--host macstudvonlukas]
"""
import argparse
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
import time
import urllib.request
import urllib.error

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Benötigt: pip install pystray Pillow")
    sys.exit(1)

DEFAULT_PROMPTS = {
    "Aufgaben": {
        "Offene Tasks zeigen": "Zeige alle offenen Tasks sortiert nach Priorität",
        "Tagesplan erstellen": "Erstelle einen Tagesplan basierend auf meinen offenen Tasks und Prioritäten",
        "Nächste Aufgabe": "Was ist die wichtigste Aufgabe die ich als nächstes erledigen sollte?",
    },
    "System": {
        "Systemstatus": "Gib einen Überblick über den aktuellen BACH-Systemstatus",
        "Wartungscheck": "Führe einen Wartungscheck durch: DB-Größe, Logs, offene Issues",
        "Übersetzungen prüfen": "Prüfe die Qualität der Übersetzungen in der Datenbank und berichte Probleme",
    },
    "Wissen": {
        "Memory durchsuchen": "Durchsuche mein Memory nach: ",
        "Zusammenfassung": "Fasse die letzten Aktivitäten und Änderungen zusammen",
        "Facts abrufen": "Zeige alle gespeicherten Facts",
    },
}

PROMPTBOARD_LIBRARY_ENV = "BACH_PROMPTBOARD_LIBRARY"
PROMPTBOARD_APP_ENV = "BACH_PROMPTBOARD_APP"


class BACHTray:

    POLL_INTERVAL = 5
    IDLE_THRESHOLD = 12  # 12 × 5s = 60s ohne Sessions → Idle-Arbeit starten

    def __init__(self, host="127.0.0.1", port=8081, webchat_port=8080, gui_port=8000):
        self.host = host
        self.control_port = port
        self.gui_port = gui_port
        self.base_url = f"http://{host}:{port}"
        self.gui_url = f"http://{host}:{gui_port}"
        self.webchat_url = f"http://{host}:{webchat_port}"
        self.ollama_url = f"http://{host}:11434"
        self.telegram_url = "https://t.me/bach_assistant_bot"
        self.state = {
            "backend": "?",
            "backend_cli": "",
            "model": "?",
            "mode": "safe",
            "think": True,
            "bach": False,
            "sessions": 0,
            "connected": False,
            "max_tool_rounds": 12,
            "current_tool": "",
            "last_tools": [],
        }
        self.backends = {}
        self.models = []
        self.icon = None
        self._stop = threading.Event()

        self.services = {
            "gui": False,
            "webchat": False,
            "control": False,
            "ollama": False,
        }

        self.idle_enabled = False
        self.idle_consecutive = 0
        self.idle_task_name = None
        self.idle_processing = False

        self.prompt_source = "defaults"
        self.prompts = self._load_prompts()

    # --- API ---

    def _api(self, method, path, body=None, base=None, timeout=5):
        url = (base or self.base_url) + path
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _check_url(self, url, timeout=2):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _refresh(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            status_future = pool.submit(
                self._api, "GET", "/api/status", None, None, 1
            )
            gui_future = pool.submit(self._check_url, self.gui_url + "/", 1)
            webchat_future = pool.submit(self._check_url, self.webchat_url + "/", 1)
            ollama_future = pool.submit(
                self._check_url, self.ollama_url + "/api/tags", 1
            )
            status = status_future.result()
            self.services["gui"] = gui_future.result()
            self.services["webchat"] = webchat_future.result()
            self.services["ollama"] = ollama_future.result()

        if status and "backend" in status:
            self.state.update(status)
            self.state["connected"] = True
        else:
            self.state["connected"] = False

        if self.state["connected"]:
            bs = self._api("GET", "/api/backends", timeout=2)
            if bs and not bs.get("error"):
                self.backends = bs

            ms = self._api("GET", "/api/models", timeout=2)
            if ms and "models" in ms:
                self.models = ms["models"]

        self.services["control"] = self.state["connected"]

    # --- PromptBoard ---

    def _promptboard_project_dir(self):
        user_profile = os.environ.get("USERPROFILE")
        if not user_profile:
            return None
        project_dir = (
            Path(user_profile)
            / "OneDrive"
            / ".TOPICS"
            / ".SOFTWARE"
            / "LLM"
            / "REL-PUB_PromptBoard"
        )
        return project_dir if project_dir.exists() else None

    def _promptboard_library_candidates(self):
        candidates = []
        env_path = os.environ.get(PROMPTBOARD_LIBRARY_ENV)
        if env_path:
            candidates.append(Path(env_path).expanduser())

        candidates.append(Path.home() / ".promptboard" / "library.json")

        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "PromptBoard" / "library.json")

        project_dir = self._promptboard_project_dir()
        if project_dir:
            candidates.extend([
                project_dir / "library.json",
                project_dir / "data" / "library.json",
            ])

        return candidates

    def _promptboard_app_candidates(self):
        candidates = []
        env_path = os.environ.get(PROMPTBOARD_APP_ENV)
        if env_path:
            candidates.append(Path(env_path).expanduser())

        project_dir = self._promptboard_project_dir()
        if project_dir:
            dist_dir = project_dir / "dist"
            if dist_dir.exists():
                candidates.extend(
                    sorted(
                        dist_dir.glob("PromptBoard-*-win64.exe"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                )
            candidates.extend([
                project_dir / "start.bat",
                project_dir / "releases" / "PromptBoard.msix",
            ])
        return candidates

    def _promptboard_app_path(self):
        for candidate in self._promptboard_app_candidates():
            if candidate.exists():
                return candidate
        return None

    def _coerce_prompt_mapping(self, payload):
        if not isinstance(payload, dict):
            return {}

        # BACH tray native format: {"Kategorie": {"Name": "Prompt"}}
        native = {}
        for category, prompts in payload.items():
            if not isinstance(prompts, dict):
                continue
            clean_prompts = {
                str(name): str(text)
                for name, text in prompts.items()
                if str(name).strip() and str(text).strip()
            }
            if clean_prompts:
                native[str(category) or "Prompts"] = clean_prompts
        if native:
            return native

        # PromptBoard library.json format: {"items": [{name, content, category, item_type}]}
        items = payload.get("items")
        if not isinstance(items, list):
            return {}

        imported = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            content = str(item.get("content") or "").strip()
            if not name or not content:
                continue
            category = str(item.get("category") or item.get("item_type") or "PromptBoard").strip()
            imported.setdefault(category or "PromptBoard", {})[name] = content
        return imported

    def _read_prompt_file(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return self._coerce_prompt_mapping(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _load_prompts(self):
        config_dir = os.path.expanduser("~/.config/bach")
        prompts_path = Path(config_dir) / "prompts.json"
        prompts = self._read_prompt_file(prompts_path)
        if prompts:
            self.prompt_source = str(prompts_path)
            return prompts

        for candidate in self._promptboard_library_candidates():
            prompts = self._read_prompt_file(candidate)
            if prompts:
                self.prompt_source = str(candidate)
                return prompts
        self.prompt_source = "defaults"
        return DEFAULT_PROMPTS

    def promptboard_smoke_snapshot(self):
        app_path = self._promptboard_app_path()
        library_candidates = []
        for candidate in self._promptboard_library_candidates():
            library_candidates.append({
                "path": str(candidate),
                "exists": candidate.exists(),
            })

        prompt_count = sum(len(prompts) for prompts in self.prompts.values())
        return {
            "app_path": str(app_path) if app_path else None,
            "app_found": app_path is not None,
            "library_candidates": library_candidates,
            "library_found": any(item["exists"] for item in library_candidates),
            "menu_has_open_app": app_path is not None,
            "prompt_source": self.prompt_source,
            "using_default_prompts": self.prompt_source == "defaults",
            "prompt_categories": list(self.prompts.keys()),
            "prompt_count": prompt_count,
        }

    def _copy_to_clipboard(self, text):
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
            elif sys.platform == "win32":
                subprocess.run(["clip"], input=text.encode("utf-16le"), check=False)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"],
                               input=text.encode("utf-8"), check=False)
            if self.icon:
                self.icon.notify("In Zwischenablage kopiert", "BACH Prompt")
        except FileNotFoundError:
            pass

    def _send_prompt(self, prompt):
        result = self._api("POST", "/api/chat", {
            "prompt": prompt,
            "chat_id": "tray-prompt",
        }, timeout=120)
        if result and result.get("ok"):
            answer = result.get("answer", "")[:120]
            if self.icon:
                self.icon.notify(answer, "BACH Antwort")
        else:
            if self.icon:
                self.icon.notify("Senden fehlgeschlagen", "BACH Prompt")

    def _make_prompt_copy_action(self, text):
        def action(*_):
            self._copy_to_clipboard(text)
        return action

    def _make_prompt_send_action(self, text):
        def action(*_):
            threading.Thread(target=self._send_prompt, args=(text,), daemon=True).start()
        return action

    # --- Idle Worker ---

    def _idle_tick(self):
        if not self.idle_enabled or self.idle_processing:
            return

        active = self.state.get("active_sessions", self.state.get("sessions", 0))
        if active > 0:
            self.idle_consecutive = 0
            return

        self.idle_consecutive += 1

        if self.idle_consecutive >= self.IDLE_THRESHOLD:
            threading.Thread(target=self._process_idle_task, daemon=True).start()

    def _process_idle_task(self):
        if self.idle_processing:
            return
        self.idle_processing = True
        self._update_icon()

        try:
            tasks_resp = self._api("GET", "/api/tasks?assigned_to=OLLAMA&status=pending", base=self.gui_url)
            if not tasks_resp or not tasks_resp.get("success") or not tasks_resp.get("tasks"):
                tasks_resp = self._api("GET", "/api/tasks?assigned_to=BUDDHA&status=pending", base=self.gui_url)

            if not tasks_resp or not tasks_resp.get("tasks"):
                return

            task = tasks_resp["tasks"][0]
            task_id = task.get("id")
            title = task.get("title", "Unbenannt")
            desc = task.get("description", "")
            self.idle_task_name = title

            self._api("PUT", f"/api/tasks/{task_id}",
                       {"status": "in-progress"}, base=self.gui_url)

            prompt = (
                f"Du bearbeitest eine zugewiesene Aufgabe im Idle-Modus. "
                f"Task #{task_id}: {title}"
            )
            if desc:
                prompt += f"\nBeschreibung: {desc}"
            prompt += "\nBitte erledige die Aufgabe und berichte kurz das Ergebnis."

            result = self._api("POST", "/api/chat", {
                "prompt": prompt,
                "chat_id": "idle-worker",
            }, timeout=300)

            if result and result.get("ok"):
                self._api("PUT", f"/api/tasks/{task_id}",
                           {"status": "completed"}, base=self.gui_url)
                if self.icon:
                    self.icon.notify(f"Erledigt: {title}", "BACH Idle")
            else:
                self._api("PUT", f"/api/tasks/{task_id}",
                           {"status": "open"}, base=self.gui_url)

        except Exception as e:
            print(f"[Idle] Fehler: {e}")
        finally:
            self.idle_processing = False
            self.idle_task_name = None
            self.idle_consecutive = 0
            self._update_icon()

    # --- Icons ---

    def _make_icon(self, color):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=color)
        try:
            if sys.platform == "darwin":
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
            elif sys.platform == "win32":
                font = ImageFont.truetype("arial", 32)
            else:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
            draw.text((14, 10), "B", fill="white", font=font)
        except (OSError, IOError):
            draw.text((16, 14), "B", fill="white")
        return img

    @property
    def _icon_image(self):
        if self.idle_processing:
            return self._make_icon((90, 120, 220, 255))  # blue = idle working
        if self.state["connected"]:
            if self.state.get("mode") == "full":
                return self._make_icon((255, 165, 0, 255))  # orange = full
            return self._make_icon((0, 200, 100, 255))  # green = connected safe
        return self._make_icon((180, 40, 40, 255))  # red = disconnected

    # --- Menu ---

    def _build_menu(self):
        items = []

        # ── Status ──
        if self.state["connected"]:
            status = f"{self.state['backend']}"
            if self.state["backend_cli"]:
                status += f" ({self.state['backend_cli']})"
            items.append(pystray.MenuItem(f"Backend: {status}", None, enabled=False))
            items.append(pystray.MenuItem(f"Modell: {self.state['model']}", None, enabled=False))
            mode_str = (self.state.get("mode") or "safe").upper()
            think_str = "AN" if self.state.get("think") else "AUS"
            items.append(pystray.MenuItem(
                f"Modus: {mode_str} | Denken: {think_str}", None, enabled=False,
            ))
            items.append(pystray.Menu.SEPARATOR)

            # Backend
            backend_items = []
            for name, info in self.backends.items():
                label = name
                if info.get("status"):
                    label += f" [{info['status']}]"
                backend_items.append(pystray.MenuItem(
                    label, self._make_backend_action(name),
                ))
            if backend_items:
                items.append(pystray.MenuItem("Backend", pystray.Menu(*backend_items)))

            # Model
            if self.models:
                model_items = []
                for m in self.models[:15]:
                    model_items.append(pystray.MenuItem(
                        m, self._make_model_action(m),
                        checked=lambda item, m=m: m == self.state["model"],
                    ))
                items.append(pystray.MenuItem("Modell", pystray.Menu(*model_items)))

            items.append(pystray.Menu.SEPARATOR)

            # Mode
            items.append(pystray.MenuItem(
                "Safe-Modus",
                lambda *_: self._set_mode("safe"),
                checked=lambda item: self.state["mode"] == "safe",
            ))
            items.append(pystray.MenuItem(
                "Full-Modus",
                lambda *_: self._set_mode("full"),
                checked=lambda item: self.state["mode"] == "full",
            ))
            items.append(pystray.Menu.SEPARATOR)

            # Think
            items.append(pystray.MenuItem(
                "Denkmodus",
                self._toggle_think,
                checked=lambda item: self.state["think"],
            ))
            items.append(pystray.Menu.SEPARATOR)

            # Max Tool-Runden
            mr = self.state.get("max_tool_rounds", 0)
            mr_label = "Unbegrenzt" if mr == 0 else str(mr)
            round_items = []
            for val in [5, 10, 20, 0]:
                lbl = "Unbegrenzt" if val == 0 else str(val)
                round_items.append(pystray.MenuItem(
                    lbl, self._make_rounds_action(val),
                    checked=lambda item, v=val: self.state.get("max_tool_rounds", 0) == v,
                ))
            items.append(pystray.MenuItem(
                f"Max Tool-Runden ({mr_label})", pystray.Menu(*round_items),
            ))

            # Tool-Aktivität
            ct = self.state.get("current_tool", "")
            lt = self.state.get("last_tools", [])
            if ct:
                items.append(pystray.MenuItem(
                    f"Tool: {ct} (Runde {self.state.get('tool_round', 0)})",
                    None, enabled=False,
                ))
            elif lt:
                items.append(pystray.MenuItem(
                    f"Letzte Tools: {', '.join(lt)}",
                    None, enabled=False,
                ))

        else:
            items.append(pystray.MenuItem("Nicht verbunden", None, enabled=False))
            items.append(pystray.MenuItem(f"Versuche: {self.base_url}", None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)

        # ── Services ──
        svc_items = []
        svc_labels = {
            "gui": f"GUI Dashboard (:{self.gui_port})",
            "webchat": "Buddha Chat (:8080)",
            "control": f"Chat/Control (:{self.control_port})",
            "ollama": "Ollama (:11434)",
        }
        for key, label in svc_labels.items():
            status_icon = "✅" if self.services.get(key) else "❌"
            svc_items.append(pystray.MenuItem(
                f"{status_icon} {label}", None, enabled=False,
            ))
        items.append(pystray.MenuItem("Services", pystray.Menu(*svc_items)))

        # ── PromptBoard ──
        prompt_items = []
        app_path = self._promptboard_app_path()
        if app_path:
            prompt_items.append(pystray.MenuItem("PromptBoard App öffnen", self._open_promptboard))
            prompt_items.append(pystray.Menu.SEPARATOR)
        for category, prompts in self.prompts.items():
            cat_items = []
            for name, text in prompts.items():
                cat_items.append(pystray.MenuItem(
                    f"\U0001F4CB {name}",
                    self._make_prompt_copy_action(text),
                ))
                cat_items.append(pystray.MenuItem(
                    f"▶ Senden: {name}",
                    self._make_prompt_send_action(text),
                    enabled=lambda item: self.state["connected"],
                ))
            prompt_items.append(pystray.MenuItem(category, pystray.Menu(*cat_items)))
        if prompt_items:
            items.append(pystray.MenuItem("PromptBoard", pystray.Menu(*prompt_items)))

        items.append(pystray.Menu.SEPARATOR)

        # ── Idle Worker ──
        idle_label = "Idle-Modus"
        if self.idle_processing:
            idle_label += f": {self.idle_task_name or 'Arbeitet...'}"
        elif self.idle_enabled:
            idle_label += ": Bereit"
        else:
            idle_label += ": AUS"

        idle_items = [
            pystray.MenuItem(
                "Idle-Modus aktivieren",
                self._toggle_idle,
                checked=lambda item: self.idle_enabled,
                enabled=lambda item: self.state["connected"] and self.services["gui"],
            ),
        ]
        if self.idle_processing:
            idle_items.append(pystray.MenuItem(
                f"Bearbeitet: {self.idle_task_name or '?'}", None, enabled=False,
            ))
        idle_items.append(pystray.MenuItem(
            f"Schwelle: {self.IDLE_THRESHOLD * self.POLL_INTERVAL}s Leerlauf",
            None, enabled=False,
        ))
        items.append(pystray.MenuItem(idle_label, pystray.Menu(*idle_items)))

        items.append(pystray.Menu.SEPARATOR)

        # ── Zugangswege ──
        items.append(pystray.MenuItem(
            "GUI Dashboard",
            self._open_gui,
            enabled=lambda item: self.services["gui"],
        ))
        items.append(pystray.MenuItem(
            "Buddha Chat",
            self._open_webchat,
            enabled=lambda item: self.services["webchat"],
        ))
        items.append(pystray.MenuItem("Telegram", self._open_telegram))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Beenden", self._quit))

        return pystray.Menu(*items)

    # --- Actions ---

    def _notify_error(self, action_name):
        if self.icon:
            self.icon.notify(f"{action_name} fehlgeschlagen", "BACH")

    def _make_backend_action(self, name):
        def action(*_):
            result = self._api("POST", "/api/backend", {"name": name})
            if result is None:
                self._notify_error(f"Backend → {name}")
            self._refresh()
            self._update_icon()
        return action

    def _make_model_action(self, model):
        def action(*_):
            result = self._api("POST", "/api/model", {"model": model})
            if result is None:
                self._notify_error(f"Modell → {model}")
            self._refresh()
            self._update_icon()
        return action

    def _set_mode(self, mode, *_):
        result = self._api("POST", "/api/mode", {"mode": mode})
        if result is None:
            self._notify_error(f"Modus → {mode}")
        self._refresh()
        self._update_icon()

    def _toggle_think(self, *_):
        new_val = not self.state["think"]
        result = self._api("POST", "/api/think", {"think": new_val})
        if result is None:
            self._notify_error("Think-Toggle")
        self._refresh()
        self._update_icon()

    def _make_rounds_action(self, rounds):
        def action(*_):
            result = self._api("POST", "/api/max_tool_rounds", {"rounds": rounds})
            if result is None:
                self._notify_error(f"Tool-Rounds → {rounds}")
            self._refresh()
            self._update_icon()
        return action

    def _toggle_idle(self, *_):
        self.idle_enabled = not self.idle_enabled
        if not self.idle_enabled:
            self.idle_consecutive = 0
        self._update_icon()
        status = "aktiviert" if self.idle_enabled else "deaktiviert"
        if self.icon:
            self.icon.notify(f"Idle-Modus {status}", "BACH")

    def _open_gui(self, *_):
        import webbrowser
        webbrowser.open(self.gui_url)

    def _open_webchat(self, *_):
        import webbrowser
        webbrowser.open(self.webchat_url)

    def _open_promptboard(self, *_):
        app_path = self._promptboard_app_path()
        if not app_path:
            if self.icon:
                self.icon.notify("PromptBoard-App nicht gefunden", "BACH PromptBoard")
            return
        try:
            if sys.platform == "win32" and app_path.suffix.lower() in {".bat", ".msix"}:
                os.startfile(str(app_path))
            else:
                subprocess.Popen(
                    [str(app_path)],
                    cwd=str(app_path.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except OSError:
            if self.icon:
                self.icon.notify("PromptBoard-Start fehlgeschlagen", "BACH PromptBoard")

    def _open_telegram(self, *_):
        import webbrowser
        webbrowser.open(self.telegram_url)

    def _quit(self, *_):
        self._stop.set()
        if self.icon:
            self.icon.stop()

    def _update_icon(self):
        if self.icon:
            self.icon.icon = self._icon_image
            self.icon.menu = self._build_menu()

    # --- Polling ---

    def _poll_loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            old_signature = (
                self.state["connected"],
                self.state["mode"],
                self.state["backend"],
                self.state["model"],
                self.state["think"],
                tuple(sorted(self.services.items())),
            )
            self._refresh()
            new_signature = (
                self.state["connected"],
                self.state["mode"],
                self.state["backend"],
                self.state["model"],
                self.state["think"],
                tuple(sorted(self.services.items())),
            )
            if new_signature != old_signature:
                self._update_icon()
            self._idle_tick()
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.1, self.POLL_INTERVAL - elapsed))

    # --- Run ---

    def run(self):
        self.icon = pystray.Icon(
            "bach-system",
            self._icon_image,
            "BACH System",
            self._build_menu(),
        )

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        self.icon.run()


def main():
    parser = argparse.ArgumentParser(description="BACH Unified System Tray")
    parser.add_argument("--host", default="127.0.0.1", help="Control API Host")
    parser.add_argument("--port", type=int, default=8081, help="Control API Port")
    parser.add_argument("--gui-port", type=int, default=8000, help="GUI Port")
    parser.add_argument("--webchat-port", type=int, default=8080, help="Webchat Port")
    parser.add_argument(
        "--smoke-promptboard",
        action="store_true",
        help="Print PromptBoard tray detection smoke data and exit",
    )
    args = parser.parse_args()

    tray = BACHTray(
        host=args.host,
        port=args.port,
        webchat_port=args.webchat_port,
        gui_port=args.gui_port,
    )
    if args.smoke_promptboard:
        print(json.dumps(tray.promptboard_smoke_snapshot(), ensure_ascii=False, indent=2))
        return
    tray.run()


if __name__ == "__main__":
    main()
