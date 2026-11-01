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

from contextlib import contextmanager
import json
import os
import threading
from datetime import datetime, timezone
from hashlib import sha256

GENESIS = "0" * 64

_ERGEBNISSE = ("pass", "deny", "executed", "dry_run", "error")
_PFLICHTFELDER = ("ts", "stufe", "tool_name", "args_hash", "ergebnis", "nachweis_id")
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


def _get_thread_lock(key: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _exclusive_ledger_lock(ledger_path):
    norm_key = os.path.abspath(os.fspath(ledger_path))
    parent = os.path.dirname(norm_key)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lock_path = norm_key + ".lock"
    t_lock = _get_thread_lock(norm_key)
    with t_lock:
        with open(lock_path, "a+b") as lock_fh:
            lock_fh.seek(0, os.SEEK_END)
            if lock_fh.tell() == 0:
                lock_fh.write(b"\0")
                lock_fh.flush()
            lock_fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_fh.seek(0)
                    msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


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
        with _exclusive_ledger_lock(self.path):
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