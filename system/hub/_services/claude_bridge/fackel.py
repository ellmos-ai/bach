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
Fackelträger-System für 24h-Bridge-Sessions
============================================
Stellt sicher dass nur ein PC gleichzeitig die Bridge betreibt.

Features:
- Lock-Acquisition mit Timeout
- Heartbeat alle 60s
- Automatische Freigabe bei Crash (5 Min Timeout)
- Fackel-Übergabe-Request (PC → PC)
"""

import socket
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

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

BACH_DIR = Path(__file__).parent.parent.parent.parent
DB_PATH = BACH_DB

HEARTBEAT_INTERVAL = 60  # Sekunden
TIMEOUT_THRESHOLD = 300  # 5 Minuten

def get_pc_name() -> str:
    """Hostname des aktuellen PC."""
    return socket.gethostname()

def acquire_fackel(session_type: str = 'bridge', user_id: str = 'user') -> Tuple[bool, Optional[str]]:
    """
    Versucht Fackel zu holen.

    Returns:
        (success: bool, message: str)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    pc_name = get_pc_name()
    now = datetime.now().isoformat()

    # 1. Prüfe ob Zeile existiert (aktiv oder inaktiv)
    cur.execute("""
        SELECT pc_name, heartbeat_at, is_active
        FROM bridge_session_lock
        WHERE session_type = ?
    """, (session_type,))

    row = cur.fetchone()

    if row:
        holder_pc, last_heartbeat, is_active = row

        # Gleicher PC oder inaktiv → immer übernehmen
        if holder_pc == pc_name or not is_active:
            cur.execute("""
                UPDATE bridge_session_lock
                SET pc_name = ?, heartbeat_at = ?, acquired_at = ?, is_active = 1
                WHERE session_type = ?
            """, (pc_name, now, now, session_type))
            conn.commit()
            conn.close()
            if not is_active:
                return True, f"Fackel reaktiviert"
            return True, f"Fackel erneuert (gleicher PC)"

        # Anderer PC: Immer Force-Takeover (wer zuletzt anfragt bekommt die Fackel)
        # Alter Halter erkennt den Verlust beim naechsten Heartbeat-Versuch.
        last_heartbeat_dt = datetime.fromisoformat(last_heartbeat)
        timed_out = datetime.now() - last_heartbeat_dt > timedelta(seconds=TIMEOUT_THRESHOLD)
        cur.execute("""
            UPDATE bridge_session_lock
            SET pc_name = ?, heartbeat_at = ?, acquired_at = ?, is_active = 1
            WHERE session_type = ?
        """, (pc_name, now, now, session_type))
        conn.commit()
        conn.close()
        if timed_out:
            return True, f"Fackel uebernommen (Timeout von {holder_pc})"
        return True, f"Fackel uebernommen (Force-Takeover von {holder_pc})"

    else:
        # Keine Zeile → neu erstellen
        cur.execute("""
            INSERT INTO bridge_session_lock (pc_name, user_id, session_type, acquired_at, heartbeat_at)
            VALUES (?, ?, ?, ?, ?)
        """, (pc_name, user_id, session_type, now, now))
        conn.commit()
        conn.close()
        return True, f"Fackel erworben"

def heartbeat(session_type: str = 'bridge') -> bool:
    """Aktualisiert Heartbeat-Timestamp."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    pc_name = get_pc_name()
    now = datetime.now().isoformat()

    cur.execute("""
        UPDATE bridge_session_lock
        SET heartbeat_at = ?
        WHERE session_type = ? AND pc_name = ? AND is_active = 1
    """, (now, session_type, pc_name))

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()

    return updated

def release_fackel(session_type: str = 'bridge') -> bool:
    """Gibt Fackel frei."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    pc_name = get_pc_name()

    cur.execute("""
        UPDATE bridge_session_lock
        SET is_active = 0
        WHERE session_type = ? AND pc_name = ?
    """, (session_type, pc_name))

    released = cur.rowcount > 0
    conn.commit()
    conn.close()

    return released

def get_fackel_holder(session_type: str = 'bridge') -> Optional[str]:
    """
    Gibt PC-Name des aktuellen Fackelträgers zurück.

    Returns:
        PC-Name oder None (wenn frei)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT pc_name, heartbeat_at
        FROM bridge_session_lock
        WHERE session_type = ? AND is_active = 1
    """, (session_type,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    pc_name, last_heartbeat = row
    last_heartbeat_dt = datetime.fromisoformat(last_heartbeat)

    # Timeout-Check
    if datetime.now() - last_heartbeat_dt > timedelta(seconds=TIMEOUT_THRESHOLD):
        return None  # Expired

    return pc_name

def check_fackel_mine(session_type: str = 'bridge') -> bool:
    """Prueft ob der aktuelle PC noch die Fackel haelt.

    Wird vom Daemon im Heartbeat genutzt um Force-Takeover zu erkennen.
    Gibt True zurueck wenn kein Datenbankfehler auftritt und wir die Fackel halten.
    Bei DB-Fehler: True (im Zweifel weiterlaufen).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT pc_name, is_active FROM bridge_session_lock
            WHERE session_type = ?
        """, (session_type,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return False
        pc_name, is_active = row
        return pc_name == get_pc_name() and bool(is_active)
    except Exception:
        return True  # Im Zweifel: weiterlaufen


def request_handover(target_pc: str, session_type: str = 'bridge') -> bool:
    """
    Sendet Fackel-Übergabe-Request an target_pc.

    TODO: Implementiere Netzwerk-Call (API/Socket) an target_pc
    Vorerst: Nutzer muss manuell auf target_pc stoppen

    Returns:
        True wenn Handover erfolgreich
    """
    # Placeholder - Future: HTTP-Call an target_pc Bridge-API
    print(f"[FACKEL] Bitte Bridge auf {target_pc} manuell stoppen")
    return False

if __name__ == "__main__":
    print("=" * 60)
    print("FACKEL.PY TEST")
    print("=" * 60)

    # Test acquire
    print("\n[1] Test acquire_fackel():")
    success, msg = acquire_fackel('bridge')
    print(f"    Acquire: {success} - {msg}")

    # Test heartbeat
    print("\n[2] Test heartbeat():")
    result = heartbeat('bridge')
    print(f"    Heartbeat OK: {result}")

    # Test get_holder
    print("\n[3] Test get_fackel_holder():")
    holder = get_fackel_holder('bridge')
    print(f"    Holder: {holder}")

    # Test release
    print("\n[4] Test release_fackel():")
    result = release_fackel('bridge')
    print(f"    Release OK: {result}")

    # Verify release
    print("\n[5] Verify release:")
    holder = get_fackel_holder('bridge')
    print(f"    Holder after release: {holder}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
