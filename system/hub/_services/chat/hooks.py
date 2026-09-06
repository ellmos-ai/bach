# -*- coding: utf-8 -*-
"""Hook-Punkte fuer BACHs Chat-Loop.

BACH war bisher nur Speicherziel der Hooker (memoryhooker/backends/bach.py),
aber keine Hook-Quelle: Sein Tool-Loop feuert keine Events, an denen
MemoryHooker oder WorkflowHooker ansetzen koennten. Dieses Modul schliesst
das - dieselben Events wie bei Claude Code, dasselbe stdin-JSON.

Konfiguration in ~/.config/bach/chat_hooks.json:

    {
      "PostToolUse": ["python -m workflowhooker hook-run PostToolUse --output-format plain"],
      "UserPromptSubmit": ["python -m memoryhooker hook-run UserPromptSubmit --output-format plain"]
    }

Fehlt die Datei, passiert nichts. Ein Hook, der klemmt, darf den Loop nie
aufhalten: Timeout, und jeder Fehler wird geschluckt.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_PATH = Path(os.path.expanduser("~/.config/bach/chat_hooks.json"))
TIMEOUT = 20
MAX_OUTPUT = 4000

_cache: dict | None = None
_cache_mtime: float = 0.0


def _config() -> dict:
    """Hook-Konfiguration, neu gelesen wenn die Datei sich geaendert hat."""
    global _cache, _cache_mtime
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        _cache, _cache_mtime = {}, 0.0
        return {}
    if _cache is None or mtime != _cache_mtime:
        try:
            _cache = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _cache_mtime = mtime
        except Exception as e:
            log.warning("chat_hooks.json unlesbar: %s", e)
            _cache = {}
    return _cache or {}


def enabled(event: str) -> bool:
    return bool(_config().get(event))


def fire(event: str, session_id: str, prompt: str = "", extra: dict | None = None) -> str:
    """Feuert die Hooks eines Events und gibt gesammelten Zusatzkontext zurueck.

    Rueckgabe ist Text zum Anhaengen an den Verlauf - oder "" wenn nichts
    kam. Wirft nie: ein kaputter Hook darf einen laufenden Bau nicht toeten.
    """
    befehle = _config().get(event) or []
    if not befehle:
        return ""

    payload = {
        "session_id": session_id,
        "hook_event_name": event,
        "prompt": prompt,
        "cwd": os.getcwd(),
    }
    if extra:
        payload.update(extra)
    roh = json.dumps(payload, ensure_ascii=False)

    teile = []
    for befehl in befehle:
        try:
            r = subprocess.run(
                befehl, shell=True, input=roh, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            log.warning("Hook %s: Timeout nach %ss (%s)", event, TIMEOUT, befehl[:60])
            continue
        except Exception as e:
            log.warning("Hook %s: %s", event, e)
            continue

        text = (r.stdout or "").strip()
        if not text:
            continue
        # Claude-Code-Format akzeptieren, sonst Klartext nehmen
        if text.startswith("{"):
            try:
                d = json.loads(text)
                text = (d.get("hookSpecificOutput") or {}).get("additionalContext", "") or ""
                text = text.strip()
            except Exception:
                pass
        if text:
            teile.append(text)

    return "\n\n".join(teile)[:MAX_OUTPUT]
