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
Claude Bridge Setup Wizard
===========================
Interaktiver Setup-Assistent fuer neue Nutzer der Claude Telegram Bridge.

Schritte:
1. Bot-Token eingeben und validieren
2. Chat-ID ermitteln
3. BACH-Pfade erkennen
4. Claude CLI Pfad konfigurieren
5. config.json generieren

Task: 987
"""
import json
import os
import sys
from pathlib import Path

# UTF-8 fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _validate_bot_token(token: str) -> dict:
    """Validiert Bot-Token gegen Telegram API."""
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/getMe"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                bot = data["result"]
                return {"ok": True, "username": bot.get("username"), "name": bot.get("first_name")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Unbekannter Fehler"}


def _get_updates(token: str) -> list:
    """Holt letzte Updates um Chat-ID zu ermitteln."""
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/getUpdates?limit=10"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return data.get("result", [])
    except Exception:
        pass
    return []


def _send_test_message(token: str, chat_id: str) -> bool:
    """Sendet Test-Nachricht zur Verifizierung."""
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": "BACH Bridge Setup - Test erfolgreich!"}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ok", False)
    except Exception:
        return False


def _find_claude_cli() -> str:
    """Sucht Claude CLI auf dem System."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
        Path.home() / ".local" / "bin",
        Path("/usr/local/bin"),
    ]

    for base in candidates:
        if not base.exists():
            continue
        for match in base.rglob("claude*"):
            if match.is_file() and match.suffix in ('', '.exe'):
                return str(match)

    # Fallback: im PATH suchen
    import shutil
    path = shutil.which("claude")
    if path:
        return path

    return ""


def run_wizard(base_path: Path = None):
    """Fuehrt den interaktiven Setup-Wizard durch."""
    print()
    print("=" * 55)
    print("  BACH Claude Bridge - Setup Wizard")
    print("=" * 55)
    print()
    print("Dieser Assistent richtet die Telegram Bridge ein.")
    print("Du brauchst: Einen Telegram Bot (via @BotFather)")
    print()

    config = {
        "enabled": True,
        "poll_interval_seconds": 5,
        "connector_name": "telegram_main",
        "chat_id": "",
        "claude_cli": {"path": "", "cwd": "", "model": "sonnet"},
        "permissions": {
            "default_mode": "restricted",
            "full_access_timeout_seconds": 3600,
            "restricted_allowed_tools": "Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch,Task,NotebookEdit,Skill"
        },
        "chat": {"timeout_seconds": 300, "message_batch_wait_seconds": 3, "history_count": 15, "max_turns": 3},
        "worker": {"timeout_seconds": 1800, "max_concurrent": 2, "model": "sonnet"},
        "budget": {"daily_limit_usd": 5.0, "warn_at_percent": 80, "chat_cost_estimate": 0.03, "worker_minute_cost": 0.05},
        "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"},
        "bridge": {"autostart": True, "start_without_connectors": True, "fackel_check": True,
                    "heartbeat_interval": 60, "timeout_threshold": 300, "use_fackel_wrapper": True}
    }

    # --- Schritt 1: Bot-Token ---
    print("SCHRITT 1: Telegram Bot Token")
    print("-" * 40)
    print("Erstelle einen Bot bei @BotFather in Telegram:")
    print("  1. Oeffne @BotFather in Telegram")
    print("  2. Sende /newbot")
    print("  3. Folge den Anweisungen")
    print("  4. Kopiere den Token")
    print()

    while True:
        token = input("Bot-Token eingeben: ").strip()
        if not token:
            print("  Token darf nicht leer sein.")
            continue

        print("  Validiere Token...")
        result = _validate_bot_token(token)
        if result["ok"]:
            print(f"  [OK] Bot: @{result['username']} ({result['name']})")
            break
        else:
            print(f"  [FEHLER] {result['error']}")
            retry = input("  Erneut versuchen? (j/n): ").strip().lower()
            if retry != 'j':
                print("Setup abgebrochen.")
                return None

    # Token sicher speichern (1) Legacy-Datei fuer Rueckwaertskompatibilitaet
    keys_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BACH" / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    token_file = keys_dir / "telegram_bot_token.txt"
    token_file.write_text(token, encoding="utf-8")
    print(f"  Token gespeichert: {token_file}")

    # Token sicher speichern (2) bach_secrets.json (primaere Quelle, ENT-44)
    try:
        _WIZARD_DIR = Path(__file__).parent
        _SYSTEM_DIR = _WIZARD_DIR.parent.parent.parent
        sys.path.insert(0, str(_SYSTEM_DIR))
        from hub.secrets_handler import SecretsHandler
        sh = SecretsHandler()
        sh.set_secret(
            "telegram_main_bot_token",
            token,
            "Telegram Bot Token (Claude Bridge)",
            "api"
        )
        print(f"  Token auch in bach_secrets.json gespeichert.")
    except Exception as _e:
        print(f"  [WARN] bach_secrets.json nicht aktualisiert: {_e}")
    print()

    # --- Schritt 2: Chat-ID ---
    print("SCHRITT 2: Deine Chat-ID")
    print("-" * 40)
    print("Sende eine Nachricht an deinen Bot in Telegram.")
    input("Druecke Enter wenn du die Nachricht gesendet hast...")

    updates = _get_updates(token)
    chat_ids = set()
    for upd in updates:
        msg = upd.get("message", {})
        chat = msg.get("chat", {})
        if chat.get("id"):
            chat_ids.add(str(chat["id"]))
            print(f"  Gefunden: Chat-ID {chat['id']} ({chat.get('first_name', '?')} {chat.get('last_name', '')})")

    if chat_ids:
        if len(chat_ids) == 1:
            config["chat_id"] = chat_ids.pop()
        else:
            config["chat_id"] = input(f"  Mehrere IDs gefunden. Welche verwenden? [{', '.join(chat_ids)}]: ").strip()
    else:
        config["chat_id"] = input("  Keine Nachrichten gefunden. Chat-ID manuell eingeben: ").strip()

    # Test-Nachricht
    if config["chat_id"]:
        print("  Sende Test-Nachricht...")
        if _send_test_message(token, config["chat_id"]):
            print("  [OK] Test-Nachricht gesendet! Pruefe Telegram.")
        else:
            print("  [WARN] Test-Nachricht fehlgeschlagen. Chat-ID korrekt?")
    print()

    # --- Schritt 3: BACH-Pfade ---
    print("SCHRITT 3: BACH-Pfade")
    print("-" * 40)

    if base_path:
        bach_path = base_path
    else:
        bach_path = Path(__file__).resolve().parent.parent.parent.parent
    print(f"  BACH System: {bach_path}")

    if not (bach_path / "bach.py").exists():
        custom = input("  bach.py nicht gefunden. Pfad eingeben: ").strip()
        if custom:
            bach_path = Path(custom)
    config["claude_cli"]["cwd"] = str(bach_path).replace("\\", "/")
    print()

    # --- Schritt 4: Claude CLI ---
    print("SCHRITT 4: Claude CLI")
    print("-" * 40)

    claude_path = _find_claude_cli()
    if claude_path:
        print(f"  Gefunden: {claude_path}")
        use = input("  Verwenden? (j/n): ").strip().lower()
        if use != 'j':
            claude_path = input("  Claude CLI Pfad: ").strip()
    else:
        print("  Claude CLI nicht automatisch gefunden.")
        claude_path = input("  Pfad zu claude(.exe): ").strip()

    config["claude_cli"]["path"] = claude_path.replace("\\", "/")

    # Modell
    model = input("  Modell (sonnet/opus/haiku) [sonnet]: ").strip() or "sonnet"
    config["claude_cli"]["model"] = model
    print()

    # --- Schritt 5: Config generieren ---
    print("SCHRITT 5: Konfiguration speichern")
    print("-" * 40)

    config_path = Path(__file__).parent / "config.json"
    config_path.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding='utf-8')
    print(f"  [OK] Config gespeichert: {config_path}")
    print()

    print("=" * 55)
    print("  Setup abgeschlossen!")
    print()
    print("  Starten: bach claude-bridge start")
    print("  Status:  bach claude-bridge status")
    print("=" * 55)

    return config


if __name__ == "__main__":
    run_wizard()
