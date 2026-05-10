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
HealthCheckHandler - System-Gesundheitspruefungen
==================================================

Operationen:
  status            Alle Checks ausfuehren und Bericht anzeigen
  disk              Disk-Space pruefen (Warnung <100GB)
  ping <host>       Host erreichbar? (Default: fritz.box)
  dns               DNS-Aufloesung pruefen
  network           Netzwerk-Checks (Ping + DNS)
  nas               NAS-Kapazitaet pruefen (Warnung >80%)
  all               Alle Checks komplett

Nutzt: Systemaufrufe (ping, nslookup), os.statvfs/shutil.disk_usage
"""

import os
import shutil
import socket
import subprocess
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler


class HealthCheckHandler(BaseHandler):

    # Schwellwerte
    DISK_WARN_GB = 100
    NAS_WARN_PERCENT = 80

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "healthcheck"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "Alle Checks ausfuehren",
            "disk": "Disk-Space pruefen",
            "ping": "Host-Erreichbarkeit: ping [host]",
            "dns": "DNS-Aufloesung pruefen",
            "network": "Netzwerk-Checks (Ping + DNS)",
            "nas": "NAS-Kapazitaet pruefen",
            "all": "Alle Checks komplett",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "status": self._status,
            "disk": self._disk,
            "ping": self._ping,
            "dns": self._dns,
            "network": self._network,
            "nas": self._nas,
            "all": self._all,
        }

        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"

        return fn(args, dry_run)

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return self._all(args, dry_run)

    def _all(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = ["System Health Check", "=" * 50, ""]
        all_ok = True

        # Disk
        ok, msg = self._check_disk()
        lines.append(f"{'[OK]' if ok else '[WARN]'} DISK: {msg}")
        if not ok:
            all_ok = False

        # FritzBox Ping
        ok, msg = self._check_ping("fritz.box")
        lines.append(f"{'[OK]' if ok else '[WARN]'} FRITZBOX: {msg}")
        if not ok:
            all_ok = False

        # Internet Ping
        ok, msg = self._check_ping("8.8.8.8")
        lines.append(f"{'[OK]' if ok else '[WARN]'} INTERNET: {msg}")
        if not ok:
            all_ok = False

        # DNS
        ok, msg = self._check_dns()
        lines.append(f"{'[OK]' if ok else '[WARN]'} DNS: {msg}")
        if not ok:
            all_ok = False

        # DB Size
        ok, msg = self._check_db()
        lines.append(f"{'[OK]' if ok else '[WARN]'} DATABASE: {msg}")
        if not ok:
            all_ok = False

        lines.append("")
        lines.append(f"Ergebnis: {'ALLES OK' if all_ok else 'WARNUNGEN VORHANDEN'}")

        self._log_check(all_ok)
        return all_ok, "\n".join(lines)

    def _disk(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        ok, msg = self._check_disk()
        drives = self._check_all_drives()
        lines = [f"Disk Check: {msg}", ""] + drives
        return ok, "\n".join(lines)

    def _ping(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        host = args[0] if args else "fritz.box"
        ok, msg = self._check_ping(host)
        return ok, f"Ping {host}: {msg}"

    def _dns(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        ok, msg = self._check_dns()
        return ok, f"DNS Check: {msg}"

    def _network(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = ["Netzwerk-Checks", "=" * 40]

        for host, label in [("fritz.box", "FritzBox"), ("8.8.8.8", "Google DNS"),
                            ("1.1.1.1", "Cloudflare")]:
            ok, msg = self._check_ping(host)
            lines.append(f"  {'[OK]' if ok else '[FAIL]'} {label} ({host}): {msg}")

        ok, msg = self._check_dns()
        lines.append(f"  {'[OK]' if ok else '[FAIL]'} DNS: {msg}")

        return True, "\n".join(lines)

    def _nas(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        # Versuche typische NAS-Pfade
        nas_paths = [r"\\fritz.nas", r"\\FRITZ.NAS", r"\\NAS", "/mnt/nas"]
        for p in nas_paths:
            if os.path.exists(p):
                try:
                    usage = shutil.disk_usage(p)
                    pct = (usage.used / usage.total) * 100
                    total_gb = usage.total / (1024**3)
                    free_gb = usage.free / (1024**3)
                    ok = pct < self.NAS_WARN_PERCENT
                    status = "OK" if ok else f"WARNUNG (>{self.NAS_WARN_PERCENT}%)"
                    return ok, f"NAS ({p}): {pct:.1f}% belegt, {free_gb:.1f}/{total_gb:.1f} GB frei - {status}"
                except Exception as e:
                    return False, f"NAS ({p}): Fehler - {e}"

        return False, "NAS nicht erreichbar (fritz.nas nicht gefunden)"

    # ------------------------------------------------------------------
    # Internal Checks
    # ------------------------------------------------------------------

    def _check_disk(self) -> Tuple[bool, str]:
        try:
            usage = shutil.disk_usage(os.environ.get("SystemDrive", "C:"))
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            pct = (usage.used / usage.total) * 100
            ok = free_gb >= self.DISK_WARN_GB
            return ok, f"{free_gb:.1f} GB frei von {total_gb:.0f} GB ({pct:.1f}% belegt)"
        except Exception as e:
            return False, f"Fehler: {e}"

    def _check_all_drives(self) -> List[str]:
        lines = []
        if os.name == "nt":
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    try:
                        usage = shutil.disk_usage(drive)
                        free_gb = usage.free / (1024**3)
                        total_gb = usage.total / (1024**3)
                        pct = (usage.used / usage.total) * 100
                        warn = " [!]" if free_gb < self.DISK_WARN_GB else ""
                        lines.append(f"  {drive} {free_gb:.1f}/{total_gb:.0f} GB frei ({pct:.1f}%){warn}")
                    except Exception:
                        pass
        return lines

    def _check_ping(self, host: str) -> Tuple[bool, str]:
        try:
            param = "-n" if os.name == "nt" else "-c"
            result = subprocess.run(
                ["ping", param, "1", "-w", "2000", host],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                try:
                    stdout = result.stdout.decode("utf-8", errors="replace")
                except Exception:
                    stdout = result.stdout.decode("latin-1", errors="replace")
                for line in stdout.split("\n"):
                    low = line.lower()
                    if "time=" in low or "zeit=" in low:
                        return True, f"erreichbar ({line.strip()[:60]})"
                return True, "erreichbar"
            return False, "nicht erreichbar"
        except subprocess.TimeoutExpired:
            return False, "Timeout (5s)"
        except FileNotFoundError:
            return False, "ping-Befehl nicht gefunden"
        except Exception as e:
            return False, f"Fehler: {e}"

    def _check_dns(self) -> Tuple[bool, str]:
        test_hosts = ["google.com", "anthropic.com", "github.com"]
        resolved = 0
        for host in test_hosts:
            try:
                ip = socket.gethostbyname(host)
                resolved += 1
            except socket.gaierror:
                pass

        if resolved == len(test_hosts):
            return True, f"OK ({resolved}/{len(test_hosts)} aufgeloest)"
        elif resolved > 0:
            return True, f"Teilweise ({resolved}/{len(test_hosts)} aufgeloest)"
        else:
            return False, "DNS-Aufloesung fehlgeschlagen"

    def _check_db(self) -> Tuple[bool, str]:
        if self.db_path.exists():
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            ok = size_mb < 500  # Warnung ueber 500MB
            return ok, f"bach.db: {size_mb:.1f} MB"
        return False, "bach.db nicht gefunden"

    def _log_check(self, all_ok: bool):
        """Ergebnis in DB loggen."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO memory_working (type, content, created_at, is_active)
                VALUES ('note', ?, ?, 1)
            """, (f"Health-Check: {'OK' if all_ok else 'WARNUNGEN'}", now))
            conn.commit()
            conn.close()
        except Exception:
            pass
