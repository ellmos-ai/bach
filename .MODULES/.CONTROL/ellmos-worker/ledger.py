# MODUL-ZUORDNUNG: Inhaltsschutz vor Werkzeugaufrufen
# SPDX-License-Identifier: MIT
# Herkunft: SentinelFleet (AGPL-3.0, commit e7f9c748); durch alleinigen
# Rechteinhaber Lukas unter MIT neu lizenziert; siehe NOTICE im Modulordner.

"""Hash-Ledger für die ellmos-worker-Prüfkette.

Append-only JSONL-Datei: jede Zeile ist ein JSON-Eintrag mit Verweis auf den
SHA-256-Hash der Vorzeile (Hash-Kette ab GENESIS). verify() prüft rohe Zeilen
auf Ladbarkeit, Pflichtfelder, erlaubte Ergebnisse und Hash-Verkettung.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from hashlib import sha256

GENESIS = "0" * 64

_ERGEBNISSE = ("pass", "deny", "executed", "dry_run", "error")
_PFLICHTFELDER = ("ts", "stufe", "tool_name", "args_hash", "ergebnis", "nachweis_id")


def hash_line(line):
    """SHA-256 über eine physische Ledger-Zeile (UTF-8)."""
    return sha256(line.encode("utf-8")).hexdigest()


class Ledger:
    """Append-only Hash-Ledger (JSONL) für Prüfkettennachweise."""

    def __init__(self, path):
        self.path = path

    def _read_lines(self):
        if not os.path.exists(self.path):
            return []
        lines = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\r\n")
                if line:
                    lines.append(line)
        return lines

    def append(self, stufe, tool_name, args_hash, ergebnis, nachweis_id, detail=None):
        """Hängt einen Eintrag an und verkettet ihn per Hash mit der Vorzeile."""
        lines = self._read_lines()
        prev_hash = hash_line(lines[-1]) if lines else GENESIS
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stufe": stufe,
            "tool_name": tool_name,
            "args_hash": args_hash,
            "ergebnis": ergebnis,
            "nachweis_id": nachweis_id,
            "prev_hash": prev_hash,
        }
        if detail is not None:
            entry["detail"] = detail
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        parent = os.path.dirname(str(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def entries(self):
        """Geparste Einträge; unlesbare Zeilen werden übersprungen."""
        out = []
        for line in self._read_lines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def verify(self):
        """Prüft die Hash-Kette über die rohen Zeilen (Tamper-Erkennung)."""
        if not os.path.exists(self.path):
            return True
        expected_prev = GENESIS
        for raw_line in self._read_lines():
            try:
                entry = json.loads(raw_line)
            except ValueError:
                return False
            if not isinstance(entry, dict):
                return False
            for feld in _PFLICHTFELDER:
                if feld not in entry:
                    return False
            if entry.get("prev_hash") != expected_prev:
                return False
            if entry.get("ergebnis") not in _ERGEBNISSE:
                return False
            expected_prev = hash_line(raw_line)
        return True