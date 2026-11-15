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
Instance Registry - Verwaltet aktive BACH-Instanzen via Filesystem
===================================================================

Jede laufende BACH-Instanz erstellt eine JSON-Datei in data/instances/.
Damit koennen Instanzen einander finden (fuer Messaging, Coordination).

Instanz-Dateien:
    data/instances/<instance_id>.json
    {
        "instance_id": "DESKTOP-ABC-12345",
        "hostname": "DESKTOP-ABC",
        "pid": 12345,
        "started_at": "2026-03-01T10:00:00",
        "source": "cli",
        "capabilities": ["messaging"]
    }

PID-basierte Stale-Detection:
    - Beim Auflisten wird geprueft ob der PID noch lebt
    - Tote Instanzen werden automatisch aufgeraeumt

Version: 1.0.0
"""

import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


class InstanceRegistry:
    """Verwaltet aktive BACH-Instanzen via Filesystem.

    Jede Instanz registriert sich mit einer JSON-Datei.
    Stale-Detection via PID-Check.

    Altteil (BACH #4147, 2026-11-15): nie aktiviert, ``App.enable_messaging`` hat keinen
    Aufrufer, und am Mac-Lead existiert kein ``data/instances``. Siehe DEPRICATED.md.
    """

    # Marker wie @deprecated_legacy_bach, aber ohne dessen Import: ``import hub`` kostet beim
    # Laden von core/app.py rund 0,8 s. ponytail: ohne DeprecationWarning, bis zur Entfernung.
    __ocean_deprecated__ = True
    __ocean_replacement__ = "memoryhooker.inbox / ticket-master host receipts"

    def __init__(self, data_dir: Path, source: str = "cli"):
        """Initialisiert die Registry.

        Args:
            data_dir: Pfad zum data/ Verzeichnis (system/data/)
            source: Quelle dieser Instanz ("cli", "telegram", "claude", "gui")
        """
        self.instances_dir = data_dir / "instances"
        self.instances_dir.mkdir(parents=True, exist_ok=True)
        self.source = source

        # Eindeutige Instanz-ID: hostname-pid
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.instance_id = f"{self.hostname}-{self.pid}"
        self._instance_file: Optional[Path] = None

    def register(self) -> Path:
        """Registriert diese Instanz (erstellt JSON-Datei).

        Returns:
            Path zur erstellten Instanz-Datei

        Hinweis:
            Sollte beim Startup aufgerufen werden.
            deregister() sollte beim Shutdown aufgerufen werden.
        """
        self._instance_file = self.instances_dir / f"{self.instance_id}.json"

        info = {
            "instance_id": self.instance_id,
            "hostname": self.hostname,
            "pid": self.pid,
            "started_at": datetime.now().isoformat(),
            "source": self.source,
            "capabilities": ["messaging"],
        }

        self._safe_write_json(self._instance_file, info)
        return self._instance_file

    def deregister(self):
        """Entfernt diese Instanz (loescht JSON-Datei).

        Sollte beim Shutdown aufgerufen werden.
        Fehler werden toleriert (Datei koennte schon weg sein).
        """
        if self._instance_file and self._instance_file.exists():
            try:
                self._instance_file.unlink()
            except OSError:
                # OneDrive-Lock oder bereits geloescht -- kein Problem
                pass

    def list_active(self, include_self: bool = True) -> list[dict]:
        """Listet alle aktiven Instanzen auf.

        Prueft ob PIDs noch leben. Tote Instanzen werden aufgeraeumt.

        Args:
            include_self: Eigene Instanz mitauflisten (default: True)

        Returns:
            Liste von Instanz-Dicts
        """
        active = []

        if not self.instances_dir.exists():
            return active

        for f in self.instances_dir.glob("*.json"):
            try:
                info = self._safe_read_json(f)
                if info is None:
                    continue

                # PID-Check: Ist der Prozess noch am Leben?
                pid = info.get("pid")
                hostname = info.get("hostname", "")

                if hostname == self.hostname and pid:
                    if not self._is_pid_alive(pid):
                        # Stale -- aufraumen
                        self._safe_remove(f)
                        continue

                # Eigene Instanz filtern?
                if not include_self and info.get("instance_id") == self.instance_id:
                    continue

                active.append(info)

            except (json.JSONDecodeError, KeyError):
                # Korrupte Datei -- aufraumen
                self._safe_remove(f)

        return active

    def list_other_instances(self) -> list[dict]:
        """Listet alle ANDEREN aktiven Instanzen (ohne sich selbst).

        Returns:
            Liste von Instanz-Dicts (ohne die eigene Instanz)
        """
        return self.list_active(include_self=False)

    def cleanup_stale(self) -> int:
        """Raeumt Dateien fuer tote Prozesse auf.

        Returns:
            Anzahl aufgeraeumter Instanzen
        """
        removed = 0

        if not self.instances_dir.exists():
            return 0

        for f in self.instances_dir.glob("*.json"):
            try:
                info = self._safe_read_json(f)
                if info is None:
                    self._safe_remove(f)
                    removed += 1
                    continue

                pid = info.get("pid")
                hostname = info.get("hostname", "")

                # Nur lokale PIDs pruefen (Remote-Hosts koennen wir nicht checken)
                if hostname == self.hostname and pid:
                    if not self._is_pid_alive(pid):
                        self._safe_remove(f)
                        removed += 1

            except (json.JSONDecodeError, KeyError):
                self._safe_remove(f)
                removed += 1

        return removed

    def get_instance_info(self, instance_id: str) -> Optional[dict]:
        """Liest Info zu einer bestimmten Instanz.

        Args:
            instance_id: ID der Instanz

        Returns:
            Instanz-Dict oder None
        """
        f = self.instances_dir / f"{instance_id}.json"
        if f.exists():
            return self._safe_read_json(f)
        return None

    def status(self) -> str:
        """Gibt formatierten Status der Registry zurueck."""
        active = self.list_active()
        lines = [
            "INSTANCE REGISTRY STATUS",
            "=" * 50,
            f"Eigene ID: {self.instance_id}",
            f"Aktive Instanzen: {len(active)}",
        ]

        if active:
            lines.append(f"\n{'ID':<30} {'Source':>10} {'Seit':>20}")
            lines.append("-" * 62)
            for inst in active:
                iid = inst.get("instance_id", "?")
                src = inst.get("source", "?")
                started = inst.get("started_at", "?")[:19]
                marker = " (self)" if iid == self.instance_id else ""
                lines.append(f"  {iid:<28} {src:>10} {started:>20}{marker}")

        return "\n".join(lines)

    # ─── Hilfsmethoden ──────────────────────────────────────────────

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Prueft ob ein Prozess mit gegebener PID noch laeuft.

        Funktioniert auf Windows und Linux.
        """
        try:
            # os.kill(pid, 0) sendet kein Signal, prueft nur Existenz
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    @staticmethod
    def _safe_write_json(path: Path, data: dict):
        """Schreibt JSON-Datei atomar (erst temp, dann rename).

        Schuetzt vor korrupten Dateien bei Crashes oder OneDrive-Locks.
        """
        tmp_path = path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename (auf Windows: ersetzt existierende Datei)
            # os.replace ist atomar auf den meisten Filesystemen
            os.replace(str(tmp_path), str(path))
        except OSError:
            # Fallback: Direkt schreiben wenn rename fehlschlaegt
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _safe_read_json(path: Path) -> Optional[dict]:
        """Liest JSON-Datei sicher (toleriert OneDrive-Locks).

        Returns:
            Dict oder None bei Fehler
        """
        for attempt in range(3):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(0.1)  # Kurz warten bei Lock
        return None

    @staticmethod
    def _safe_remove(path: Path):
        """Loescht Datei sicher (toleriert Lock-Fehler)."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
