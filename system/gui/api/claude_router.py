#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
GUI → Claude Router
====================
Entscheidet ob Anfrage an 24h-Bridge oder Extra-Session geht.

Routing-Regeln:
- Chat/Assistent/Quick-Question → 24h-Bridge (wenn läuft)
- Chat/Assistent/Quick-Question → GUI-24h-Session (wenn Bridge NICHT läuft)
- Code-Analyse/Long-Task → Extra-Session (Worker)
- Task-CRUD → Direkt via BACH CLI (kein LLM)
"""

import subprocess
import sqlite3
from pathlib import Path
from typing import Literal, Optional

import sys
# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

BACH_DIR = Path(__file__).parent.parent.parent
DB_PATH = BACH_DB

RequestType = Literal["chat", "assistant", "quick_question", "code_analysis", "long_task", "task_crud"]

def route_request(request_type: RequestType, prompt: str, user_id: str = "user") -> dict:
    """
    Routet Anfrage basierend auf Typ.

    Returns:
        {"status": "ok", "response": "...", "mode": "bridge|worker|cli"}
    """

    if request_type in ["chat", "assistant", "quick_question"]:
        # Alle Chat-Anfragen an Bridge (läuft immer)
        return send_to_bridge(prompt, user_id)

    elif request_type in ["code_analysis", "long_task"]:
        return spawn_worker_session(prompt, user_id)

    elif request_type == "task_crud":
        return execute_cli_command(prompt)

    else:
        return {"status": "error", "response": f"Unknown request_type: {request_type}"}

def is_bridge_running() -> bool:
    """Prüft ob Bridge-Daemon läuft."""
    import tempfile
    lock_file = Path(tempfile.gettempdir()) / "bach_bridge.lock"
    return lock_file.exists()

def send_to_bridge(prompt: str, user_id: str) -> dict:
    """Sendet Anfrage an 24h-Bridge via Message-Queue."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Nachricht in outbox einfügen
    cur.execute("""
        INSERT INTO connector_outbox (connector, recipient, message, created_at)
        VALUES ('telegram', ?, ?, datetime('now'))
    """, (user_id, prompt))

    conn.commit()
    conn.close()

    # TODO: WebSocket-Notification für Live-Response
    return {"status": "queued", "mode": "bridge", "response": "Anfrage an Bridge gesendet"}

# GUI nutzt Bridge-Session - keine separate GUI-Session mehr nötig

def spawn_worker_session(prompt: str, user_id: str) -> dict:
    """Spawnt neue Worker-Session (nicht persistent)."""
    try:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            encoding='utf-8', errors='replace',
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "mode": "worker", "response": "Timeout nach 120s"}
    except FileNotFoundError:
        return {"status": "error", "mode": "worker", "response": "claude CLI nicht gefunden"}

    if result.returncode != 0:
        return {"status": "error", "mode": "worker", "response": result.stderr or "Unbekannter Fehler"}

    return {
        "status": "ok",
        "mode": "worker",
        "response": result.stdout,
    }

def execute_cli_command(command: str) -> dict:
    """Führt BACH CLI-Befehl direkt aus (kein LLM)."""
    import shlex
    try:
        args = shlex.split(command)
    except ValueError:
        return {"status": "error", "mode": "cli", "response": "Ungültiger Befehl"}

    try:
        result = subprocess.run(
            ["python", str(BACH_DIR / "bach.py")] + args,
            capture_output=True,
            text=True,
            encoding='utf-8', errors='replace',
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "mode": "cli", "response": "Timeout nach 60s"}

    if result.returncode != 0:
        return {"status": "error", "mode": "cli", "response": result.stderr or result.stdout}

    return {
        "status": "ok",
        "mode": "cli",
        "response": result.stdout,
    }
