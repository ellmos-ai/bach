# SPDX-License-Identifier: MIT
"""Operator-Steuerung fuer lange Agenten-Laeufe (OPS-RUN-001).

Konsumenten-Seite zu ``bach agent steer|pause|resume|checkpoint|clear-steer``:
der Agent-Launcher schreibt Steuerdateien in das Arbeitsverzeichnis des
Agenten (``data/temp/agent_<name>/``). Dieser Konsument wertet sie an den
Modell-/Tool-Grenzen des Tool-Loops aus:

  - ``operator_notes.json``      Liste von ``{message, requested_at}``
    -> wird als ``[OPERATOR-HINWEIS]``-Nachricht in den Kontext injiziert
  - ``operator_pause.json``      ``{reason, requested_at}``
    -> kooperative Pause: der Loop wartet, bis ``resume`` die Datei loescht
  - ``operator_checkpoint.json`` ``{acknowledged_at, message}``
    -> wird einmalig als Bestaetigung in den Kontext injiziert

Wirksam ist die Steuerung fuer Agenten, die in BACHs eigener Laufzeit
laufen (Runner ``local`` = hub._services.chat.agent_runner). Externe CLIs
(claude, codex, agy) koennen zwischen Turns nicht beschickt werden; ihre
Steuerdateien bleiben sichtbar (``bach agent status``), werden aber nicht
konsumiert.

Fail-soft durchgaengig: fehlende oder kaputte Dateien aendern das
Laufverhalten nie.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from hub._services.limits import limit

log = logging.getLogger("bach.operator_control")

NOTES_FILE = "operator_notes.json"
PAUSE_FILE = "operator_pause.json"
CHECKPOINT_FILE = "operator_checkpoint.json"


def _read_json(path: Path, default: Any) -> Any:
    """Liest JSON robust; bei Fehlern gilt der Default."""
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


class OperatorControl:
    """Liest und konsumiert Operator-Steuerdateien eines Agenten-Laufs."""

    def __init__(self, control_dir: Path | str,
                 poll_interval: float | None = None,
                 max_pause_wait: float | None = None):
        self.control_dir = Path(control_dir)
        self.poll_interval = (
            poll_interval
            if poll_interval is not None
            else float(limit("BACH_OPERATOR_POLL_INTERVAL", 2))
        )
        self.max_pause_wait = (
            max_pause_wait
            if max_pause_wait is not None
            else float(limit("BACH_OPERATOR_PAUSE_MAX_WAIT", 600))
        )
        self._notes_seen: int = 0
        self._last_marker: Optional[str] = None
        self._checkpoint_seen: Optional[str] = None

    # ---------- Steer ----------

    def drain_notes(self) -> list[dict]:
        """Liefert die Operator-Hinweise, die seit dem letzten Aufruf neu sind.

        Wasserstand ueber den ``requested_at``-Zeitstempel des zuletzt
        gelieferten Eintrags: ``clear-steer`` loescht die Datei komplett und
        legt sie ggf. neu an; ist der Wasserstand-Eintrag nicht mehr
        enthalten, gelten alle Eintraege wieder als neu (kein Hinweis geht
        verloren). Beim allerersten Aufruf werden alle vorgemerkten Hinweise
        geliefert (steer funktioniert auch vor dem Start eines Agenten).
        """
        path = self.control_dir / NOTES_FILE
        payload = _read_json(path, [])
        if not isinstance(payload, list):
            payload = []
        notes = [
            item for item in payload
            if isinstance(item, dict) and item.get("message")
        ]
        if self._last_marker is None:
            start = self._notes_seen if self._notes_seen <= len(notes) else 0
        else:
            idx = max(
                (i for i, n in enumerate(notes)
                 if n.get("requested_at") == self._last_marker),
                default=-1,
            )
            if idx >= 0:
                start = idx + 1
            else:
                # Liste ersetzt (clear-steer): alles gilt als neu.
                self._last_marker = None
                start = 0
        new = notes[start:]
        if new:
            marker = new[-1].get("requested_at")
            if marker is not None:
                self._last_marker = marker
            self._notes_seen = len(notes)
        return new

    # ---------- Pause ----------

    def pending_pause(self) -> Optional[dict]:
        """Liefert eine anstehende kooperative Pause (oder None)."""
        payload = _read_json(self.control_dir / PAUSE_FILE, None)
        if isinstance(payload, dict) and payload.get("reason"):
            return payload
        return None

    async def wait_if_paused(self) -> dict:
        """Wartet kooperativ, bis keine Pause mehr ansteht (resume loescht sie).

        Gibt nach ``max_pause_wait`` Sekunden auf, damit ein vergessenes
        Pause-Flag einen Lauf nie dauerhaft einfriert; der Loop laeuft dann
        mit einer Warnung weiter.

        Rueckgabe: ``{"paused": bool, "waited_sec": float, "timed_out": bool}``
        """
        request = self.pending_pause()
        if request is None:
            return {"paused": False, "waited_sec": 0.0, "timed_out": False}
        started = time.monotonic()
        log.info("Operator-Pause aktiv (%s) - warte auf resume (max %ds)",
                 request.get("reason", "?"), int(self.max_pause_wait))
        while self.pending_pause() is not None:
            if time.monotonic() - started >= self.max_pause_wait:
                log.warning("Operator-Pause nicht aufgehoben - Laufgrenze "
                            "%ds erreicht, fuehre Lauf fort", int(self.max_pause_wait))
                return {
                    "paused": True,
                    "waited_sec": time.monotonic() - started,
                    "timed_out": True,
                }
            await asyncio.sleep(self.poll_interval)
        waited = time.monotonic() - started
        log.info("Operator-Pause nach %.1fs aufgehoben", waited)
        return {"paused": True, "waited_sec": waited, "timed_out": False}

    # ---------- Checkpoint ----------

    def consume_new_checkpoint(self) -> Optional[dict]:
        """Liefert einen neuen bestaetigten Checkpoint genau einmal."""
        payload = _read_json(self.control_dir / CHECKPOINT_FILE, None)
        if not (isinstance(payload, dict) and payload.get("acknowledged_at")):
            return None
        if payload["acknowledged_at"] == self._checkpoint_seen:
            return None
        self._checkpoint_seen = payload["acknowledged_at"]
        if not payload.get("message"):
            payload["message"] = "Sicherer Checkpoint erreicht."
        return payload
