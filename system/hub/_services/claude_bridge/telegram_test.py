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
BACH Telegram Direkttest
========================
Testet die Telegram-Verbindung unabhaengig vom Bridge-Daemon.

Aufruf:
    python telegram_test.py           - Verbindung + Status pruefen
    python telegram_test.py send "Nachricht"  - Testnachricht senden
    python telegram_test.py recv      - Letzte Nachrichten abrufen

Autor: BACH System
Datum: 2026-02-18
"""

import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

BRIDGE_DIR = Path(__file__).parent.resolve()
HUB_DIR = BRIDGE_DIR.parent
BACH_DIR = HUB_DIR.parent
DB_PATH = BACH_DB

os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def get_telegram_config():
    """Laedt Bot-Token und Chat-ID aus DB + config.json."""
    config_file = BRIDGE_DIR / "config.json"
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding='utf-8'))
        except Exception:
            pass

    chat_id = config.get("chat_id", "")
    token = ""

    # Token aus DB (connections Tabelle)
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute(
            "SELECT auth_config FROM connections WHERE name = 'telegram_main' AND is_active = 1 LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            auth = json.loads(row[0]) if row[0] else {}
            token = auth.get("bot_token", "")
    except Exception as e:
        print(f"[WARN] DB nicht erreichbar: {e}")

    return token, chat_id


def api_call(token: str, method: str, params: dict = None, timeout: int = 10):
    """Ruft Telegram API auf."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    if params:
        data = json.dumps(params, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    else:
        req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return body.get("result"), None
            return None, body.get("description", "Unknown error")
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"URL Error: {e.reason}"
    except Exception as e:
        return None, str(e)


def test_connection():
    """Verbindung und Bot-Info pruefen."""
    token, chat_id = get_telegram_config()

    print("\n=== BACH Telegram Direkttest ===\n")

    if not token:
        print("[FEHLER] Kein Bot-Token gefunden (DB oder config.json)")
        return False

    print(f"Bot-Token: ...{token[-10:]}")
    print(f"Chat-ID: {chat_id}")

    # getMe
    result, err = api_call(token, "getMe")
    if err:
        print(f"\n[FEHLER] getMe: {err}")
        return False

    print(f"\n[OK] Bot verbunden:")
    print(f"     Name: {result.get('first_name', '?')}")
    print(f"     Username: @{result.get('username', '?')}")
    print(f"     ID: {result.get('id', '?')}")

    # getUpdates (letzte 1)
    result2, err2 = api_call(token, "getUpdates", {"limit": 1, "timeout": 1})
    if err2:
        print(f"\n[WARN] getUpdates: {err2}")
    else:
        count = len(result2) if result2 else 0
        print(f"\n[OK] getUpdates erreichbar ({count} neue Updates)")

    print(f"\n[OK] Telegram-Verbindung funktioniert!")
    return True


def send_test_message(text: str):
    """Sendet Testnachricht."""
    token, chat_id = get_telegram_config()

    if not token or not chat_id:
        print("[FEHLER] Kein Token oder Chat-ID")
        return

    print(f"Sende: '{text}' -> {chat_id}")
    result, err = api_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text
    })
    if err:
        print(f"[FEHLER] {err}")
    else:
        msg_id = result.get("message_id", "?")
        print(f"[OK] Gesendet! Message-ID: {msg_id}")


def receive_messages():
    """Letzten Nachrichten abrufen."""
    token, chat_id = get_telegram_config()

    if not token:
        print("[FEHLER] Kein Token")
        return

    result, err = api_call(token, "getUpdates", {"limit": 5, "timeout": 2}, timeout=5)
    if err:
        print(f"[FEHLER] {err}")
        return

    if not result:
        print("[INFO] Keine neuen Nachrichten")
        return

    print(f"\nLetzte {len(result)} Update(s):")
    for upd in result:
        msg = upd.get("message", {})
        text = msg.get("text", "(kein Text)")
        sender = msg.get("from", {}).get("first_name", "?")
        date = msg.get("date", 0)
        uid = upd.get("update_id", "?")
        print(f"  [{uid}] {sender}: {text[:80]}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"

    if cmd == "test":
        test_connection()
    elif cmd == "send":
        text = " ".join(sys.argv[2:]) or "BACH Telegram Test"
        if test_connection():
            print()
            send_test_message(text)
    elif cmd == "recv":
        receive_messages()
    else:
        print(f"Unbekannter Befehl: {cmd}")
        print("Gueltig: test | send <text> | recv")


if __name__ == "__main__":
    main()
