#!/usr/bin/env python3
"""
BACH Chat System Tray
======================

Cross-platform (macOS/Windows/Linux) System Tray zur Steuerung
des BACH Telegram Chat Bots über die Control API.

Voraussetzungen:
  pip install pystray Pillow

Start:
  python chat_tray.py [--port 8081] [--host 127.0.0.1]
"""
import argparse
import json
import os
import sys
import threading

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
import time
import urllib.request
import urllib.error
from io import BytesIO

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Benötigt: pip install pystray Pillow")
    sys.exit(1)


class BACHTray:

    POLL_INTERVAL = 5

    def __init__(self, host="127.0.0.1", port=8081):
        self.base_url = f"http://{host}:{port}"
        self.gui_url = f"http://{host}:8000"
        self.webchat_url = f"http://{host}:8080"
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

    # --- API ---

    def _api(self, method, path, body=None):
        url = self.base_url + path
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _refresh(self):
        status = self._api("GET", "/api/status")
        if status and "backend" in status:
            self.state.update(status)
            self.state["connected"] = True
        else:
            self.state["connected"] = False

        bs = self._api("GET", "/api/backends")
        if bs and not bs.get("error"):
            self.backends = bs

        ms = self._api("GET", "/api/models")
        if ms and "models" in ms:
            self.models = ms["models"]

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
        if self.state["connected"]:
            if self.state.get("mode") == "full":
                return self._make_icon((255, 165, 0, 255))
            return self._make_icon((0, 200, 100, 255))
        return self._make_icon((180, 40, 40, 255))

    # --- Menu ---

    def _build_menu(self):
        items = []

        # Status
        if self.state["connected"]:
            status = f"{self.state['backend']}"
            if self.state["backend_cli"]:
                status += f" ({self.state['backend_cli']})"
            items.append(pystray.MenuItem(f"Backend: {status}", None, enabled=False))
            items.append(pystray.MenuItem(f"Modell: {self.state['model']}", None, enabled=False))
            mode_str = (self.state.get("mode") or "safe").upper()
            think_str = "AN" if self.state.get("think") else "AUS"
            items.append(pystray.MenuItem(
                f"Modus: {mode_str} | Denken: {think_str}",
                None, enabled=False,
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
                    checked = m == self.state["model"]
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

            items.append(pystray.Menu.SEPARATOR)

            # Zugangswege
            items.append(pystray.MenuItem(
                "GUI Dashboard (:8000)",
                self._open_gui,
            ))
            items.append(pystray.MenuItem(
                "Web Chat (:8080)",
                self._open_webchat,
            ))
            items.append(pystray.MenuItem(
                "Telegram (@bach_assistant_bot)",
                self._open_telegram,
            ))
            items.append(pystray.MenuItem(
                f"Control API ({self.base_url})",
                self._open_control_api,
            ))

        else:
            items.append(pystray.MenuItem("Nicht verbunden", None, enabled=False))
            items.append(pystray.MenuItem(f"Versuche: {self.base_url}", None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Beenden", self._quit))

        return pystray.Menu(*items)

    # --- Actions ---

    def _make_backend_action(self, name):
        def action(*_):
            self._api("POST", "/api/backend", {"name": name})
            self._refresh()
            self._update_icon()
        return action

    def _make_model_action(self, model):
        def action(*_):
            self._api("POST", "/api/model", {"model": model})
            self._refresh()
            self._update_icon()
        return action

    def _set_mode(self, mode, *_):
        self._api("POST", "/api/mode", {"mode": mode})
        self._refresh()
        self._update_icon()

    def _toggle_think(self, *_):
        new_val = not self.state["think"]
        self._api("POST", "/api/think", {"think": new_val})
        self._refresh()
        self._update_icon()

    def _make_rounds_action(self, rounds):
        def action(*_):
            self._api("POST", "/api/max_tool_rounds", {"rounds": rounds})
            self._refresh()
            self._update_icon()
        return action

    def _open_gui(self, *_):
        import webbrowser
        webbrowser.open(self.gui_url)

    def _open_webchat(self, *_):
        import webbrowser
        webbrowser.open(self.webchat_url)

    def _open_telegram(self, *_):
        import webbrowser
        webbrowser.open(self.telegram_url)

    def _open_control_api(self, *_):
        import webbrowser
        webbrowser.open(self.base_url)

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
            old_connected = self.state["connected"]
            old_mode = self.state["mode"]
            self._refresh()
            if self.state["connected"] != old_connected or self.state["mode"] != old_mode:
                self._update_icon()
            self._stop.wait(self.POLL_INTERVAL)

    # --- Run ---

    def run(self):
        self._refresh()
        self.icon = pystray.Icon(
            "bach-chat",
            self._icon_image,
            "BACH Chat",
            self._build_menu(),
        )

        poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        poll_thread.start()

        self.icon.run()


def main():
    parser = argparse.ArgumentParser(description="BACH Chat System Tray")
    parser.add_argument("--host", default="127.0.0.1", help="Control API Host")
    parser.add_argument("--port", type=int, default=8081, help="Control API Port")
    args = parser.parse_args()

    tray = BACHTray(host=args.host, port=args.port)
    tray.run()


if __name__ == "__main__":
    main()
