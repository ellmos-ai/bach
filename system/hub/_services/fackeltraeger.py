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
Fackelträger -- S2 Handover State-Store und API
==============================================

Zentrale Komponente für den Übergabe-Mechanismus zwischen BACH-Bridge-Instanzen.

Aufgaben:
- Eindeutige, stabile `system_id` pro Maschine erzeugen und persistieren.
- State-Tabelle `fackel_state` in `BACH_DB` verwalten.
- HandoverPackage als serialisierbare Dataclass bereitstellen.
- Lokale API-Funktionen für Request/Accept/Status/Release.
- Optional: HTTP-Notification an das Zielsystem über dessen Bridge-API.

Das Modul ist absichtlich frei von bridge_daemon.py, damit es sowohl vom
Daemon, vom API-Server (`server_api.py`) als auch von Standalone-Skripten
importiert werden kann, ohne Zirkelimporte zu erzeugen.
"""

import json
import os
import socket
import sqlite3
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Universal-Import für bach_paths ---------------------------------------
_current = Path(__file__).resolve()
for _parent in [_current] + list(_current.parents):
    _hub = _parent / "hub"
    if _hub.exists() and (_hub / "bach_paths.py").exists():
        if str(_hub) not in sys.path:
            sys.path.insert(0, str(_hub))
        break
from bach_paths import BACH_DB, DATA_DIR

# --- Konstanten -----------------------------------------------------------
HEARTBEAT_INTERVAL = 60          # Sekunden (Empfehlung)
TIMEOUT_THRESHOLD = 300          # 5 Minuten
TABLE_NAME = "fackel_state"
SYSTEM_ID_FILE = DATA_DIR / ".fackel_system_id"

DEFAULT_BRIDGE_PORT = 8000       # Fallback-Port für LAN-Notifications


# --- Dataclasses ----------------------------------------------------------

@dataclass
class HandoverPackage:
    """
    Serialisierbare Payload für eine Fackel-Übergabe.

    Attributes:
        source_system_id: UUID des aktuellen Halters.
        source_pc_name: Hostname des aktuellen Halters.
        target_system_id: UUID des Empfängers.
        target_pc_name: Hostname des Empfängers.
        session_type: Typ der Session (z.B. 'bridge').
        auth_token: Optionaler Sicherheits-Token für die Annahme.
        payload: Freie Key/Value-Daten (z.B. config-Snapshot).
        created_at: ISO-Zeitstempel der Erstellung.
        expires_at: ISO-Zeitstempel des Ablaufs.
    """
    source_system_id: str
    source_pc_name: str
    target_system_id: str
    target_pc_name: str
    session_type: str = "bridge"
    auth_token: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None

    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> "HandoverPackage":
        return cls(**json.loads(raw))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self, dict_factory=dict)


@dataclass
class HandoverStatus:
    """Leseansicht des aktuellen Handover-Status in der DB."""
    session_type: str
    handover_state: str           # idle | requested | accepted | rejected
    holder_system_id: Optional[str] = None
    holder_pc_name: Optional[str] = None
    target_system_id: Optional[str] = None
    target_pc_name: Optional[str] = None
    requested_at: Optional[str] = None
    accepted_at: Optional[str] = None
    package: Optional[HandoverPackage] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.package is not None:
            d["package"] = self.package.to_dict()
        return d


# --- system_id Helfer -----------------------------------------------------

def _generate_system_id() -> str:
    """
    Erzeugt eine stabile, maschinenbezogene UUID.

    Strategie:
    1. Hostname + MAC-Adresse als Namespace verwenden.
    2. Falls MAC nicht ermittelbar, eine zufällige UUID v4 erzeugen.
    3. In DATA_DIR persistieren, damit selbe Maschine immer selbe ID hat.
    """
    hostname = socket.gethostname()
    try:
        node = uuid.getnode()
        mac_component = f"{node:012x}"
    except Exception:
        mac_component = os.environ.get("BACH_SYSTEM_ID_SEED", "no-mac")

    namespace_str = f"{hostname}-{mac_component}"
    system_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, namespace_str)
    return str(system_uuid)


def get_system_id() -> str:
    """Liefert die persistierte oder neu erzeugte system_id dieser Maschine."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SYSTEM_ID_FILE.exists():
        try:
            data = json.loads(SYSTEM_ID_FILE.read_text(encoding="utf-8"))
            sid = data.get("system_id", "").strip()
            if sid:
                return sid
        except Exception:
            pass

    sid = _generate_system_id()
    try:
        SYSTEM_ID_FILE.write_text(
            json.dumps({"system_id": sid, "pc_name": socket.gethostname()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return sid


def get_pc_name() -> str:
    """Hostname des aktuellen Systems."""
    return socket.gethostname()


# --- DB-Schema ------------------------------------------------------------

def _ensure_table() -> None:
    """Erstellt die `fackel_state` Tabelle falls sie fehlt."""
    db_path = Path(BACH_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_type TEXT UNIQUE NOT NULL,
            system_id TEXT,
            pc_name TEXT,
            user_id TEXT,
            acquired_at TEXT,
            heartbeat_at TEXT,
            is_active INTEGER DEFAULT 0,
            handover_state TEXT DEFAULT 'idle',
            handover_target_system_id TEXT,
            handover_target_pc_name TEXT,
            handover_requested_at TEXT,
            handover_accepted_at TEXT,
            handover_payload TEXT,
            updated_at TEXT
        )
    """)
    # Migration: user_id-Spalte nachtragen, falls aus frueherem Schema vorhanden
    try:
        cur.execute(f"SELECT user_id FROM {TABLE_NAME} LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN user_id TEXT")
    conn.commit()
    conn.close()


def _db_execute(
    query: str,
    params: Tuple = (),
    fetch: bool = False,
    fetchone: bool = False,
) -> Any:
    """Kleiner SQLite-Wrapper ohne externe Abhängigkeiten."""
    _ensure_table()
    conn = sqlite3.connect(str(BACH_DB))
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    result = None
    if fetch:
        result = cur.fetchone() if fetchone else cur.fetchall()
    conn.close()
    return result


# --- State-Core -----------------------------------------------------------

def _row_to_status(row: sqlite3.Row) -> HandoverStatus:
    pkg = None
    if row["handover_payload"]:
        try:
            pkg = HandoverPackage.from_json(row["handover_payload"])
        except Exception:
            pass
    return HandoverStatus(
        session_type=row["session_type"],
        handover_state=row["handover_state"] or "idle",
        holder_system_id=row["system_id"],
        holder_pc_name=row["pc_name"],
        target_system_id=row["handover_target_system_id"],
        target_pc_name=row["handover_target_pc_name"],
        requested_at=row["handover_requested_at"],
        accepted_at=row["handover_accepted_at"],
        package=pkg,
    )


def _get_or_create_row(
    session_type: str,
    user_id: str = "",
) -> sqlite3.Row:
    """Holt bestehende Zeile oder legt leere Zeile an."""
    _ensure_table()
    conn = sqlite3.connect(str(BACH_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM {TABLE_NAME} WHERE session_type = ?",
        (session_type,),
    )
    row = cur.fetchone()
    if not row:
        now = datetime.now().isoformat()
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME} (
                session_type, user_id, is_active, handover_state, updated_at
            ) VALUES (?, ?, 0, 'idle', ?)
            """,
            (session_type, user_id, now),
        )
        conn.commit()
        cur.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE session_type = ?",
            (session_type,),
        )
        row = cur.fetchone()
    conn.close()
    return row


def _is_expired(row: sqlite3.Row) -> bool:
    """Prüft, ob der aktuelle Halter das Heartbeat-Timeout überschritten hat."""
    if not row["heartbeat_at"]:
        return True
    try:
        last = datetime.fromisoformat(row["heartbeat_at"])
        return (datetime.now() - last) > timedelta(seconds=TIMEOUT_THRESHOLD)
    except Exception:
        return True


def acquire_fackel_state(
    session_type: str = "bridge",
    force: bool = False,
    user_id: str = "",
) -> Tuple[bool, str]:
    """
    Versucht die Fackel im State-Store zu erwerben.

    Args:
        session_type: Typ der Session.
        force: Wenn True, wird auch von einem aktiven anderen Halter übernommen.
        user_id: Optionaler Benutzer-Identifikator für 24h-Sessions.

    Returns:
        (success, message)
    """
    _ensure_table()
    my_sid = get_system_id()
    my_pc = get_pc_name()
    now = datetime.now().isoformat()

    conn = sqlite3.connect(str(BACH_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM {TABLE_NAME} WHERE session_type = ?",
        (session_type,),
    )
    row = cur.fetchone()

    if not row:
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME} (
                session_type, system_id, pc_name, user_id, acquired_at, heartbeat_at,
                is_active, handover_state, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 'idle', ?)
            """,
            (session_type, my_sid, my_pc, user_id, now, now, now),
        )
        conn.commit()
        conn.close()
        return True, "Fackel erworben (neuer State)"

    holder_sid = row["system_id"]
    is_active = bool(row["is_active"])
    expired = _is_expired(row)

    # Eigene Fackel oder inaktiv/expired → übernehmen/erneuern
    if holder_sid == my_sid or not is_active or expired:
        cur.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET system_id = ?, pc_name = ?, user_id = ?, acquired_at = ?, heartbeat_at = ?,
                is_active = 1, handover_state = 'idle', handover_target_system_id = NULL,
                handover_target_pc_name = NULL, handover_requested_at = NULL,
                handover_accepted_at = NULL, handover_payload = NULL, updated_at = ?
            WHERE session_type = ?
            """,
            (my_sid, my_pc, user_id, now, now, now, session_type),
        )
        conn.commit()
        conn.close()
        if holder_sid == my_sid:
            return True, "Fackel erneuert (eigener State)"
        return True, f"Fackel reaktiviert (vorheriger Halter inaktiv/abgelaufen)"

    # Anderer aktiver Halter
    if force:
        old_holder = holder_sid
        cur.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET system_id = ?, pc_name = ?, user_id = ?, acquired_at = ?, heartbeat_at = ?,
                is_active = 1, handover_state = 'idle', handover_target_system_id = NULL,
                handover_target_pc_name = NULL, handover_requested_at = NULL,
                handover_accepted_at = NULL, handover_payload = NULL, updated_at = ?
            WHERE session_type = ?
            """,
            (my_sid, my_pc, user_id, now, now, now, session_type),
        )
        conn.commit()
        conn.close()
        return True, f"Fackel übernommen (Force-Takeover von {old_holder})"

    conn.close()
    return False, f"Fackel wird von {holder_sid} ({row['pc_name']}) gehalten"


def heartbeat_state(session_type: str = "bridge") -> bool:
    """Aktualisiert den Heartbeat-Timestamp für diese Maschine."""
    _ensure_table()
    my_sid = get_system_id()
    now = datetime.now().isoformat()
    _db_execute(
        f"""
        UPDATE {TABLE_NAME}
        SET heartbeat_at = ?, updated_at = ?
        WHERE session_type = ? AND system_id = ? AND is_active = 1
        """,
        (now, now, session_type, my_sid),
    )
    return True


def release_fackel_state(session_type: str = "bridge") -> bool:
    """Gibt die Fackel frei, falls diese Maschine sie hält."""
    _ensure_table()
    my_sid = get_system_id()
    now = datetime.now().isoformat()
    _db_execute(
        f"""
        UPDATE {TABLE_NAME}
        SET is_active = 0, handover_state = 'idle', handover_target_system_id = NULL,
            handover_target_pc_name = NULL, handover_requested_at = NULL,
            handover_accepted_at = NULL, handover_payload = NULL, updated_at = ?
        WHERE session_type = ? AND system_id = ?
        """,
        (now, session_type, my_sid),
    )
    return True


def get_fackel_holder_state(session_type: str = "bridge") -> Optional[Tuple[str, str]]:
    """
    Liefert (system_id, pc_name) des aktiven Halters oder None.

    Berücksichtigt Heartbeat-Timeout.
    """
    _ensure_table()
    conn = sqlite3.connect(str(BACH_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM {TABLE_NAME} WHERE session_type = ? AND is_active = 1",
        (session_type,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    if _is_expired(row):
        return None
    return (row["system_id"], row["pc_name"])


def check_fackel_mine_state(session_type: str = "bridge") -> bool:
    """Prüft, ob diese Maschine aktiv die Fackel hält."""
    holder = get_fackel_holder_state(session_type)
    if holder is None:
        return False
    return holder[0] == get_system_id()


# --- Handover API ---------------------------------------------------------

def request_handover(
    target_system_id: str,
    target_pc_name: str,
    session_type: str = "bridge",
    payload: Optional[Dict[str, Any]] = None,
    auth_token: Optional[str] = None,
    notify_target: bool = True,
    target_port: int = DEFAULT_BRIDGE_PORT,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Optional[HandoverPackage]]:
    """
    Beantragt eine kontrollierte Übergabe der Fackel an ein Zielsystem.

    Args:
        target_system_id: system_id des Empfängers.
        target_pc_name: Hostname des Empfängers.
        session_type: Typ der Session.
        payload: Optionale Daten für den Empfänger.
        auth_token: Optionaler Sicherheits-Token.
        notify_target: Wenn True, wird ein HTTP-Post an `target_pc_name` gesendet.
        target_port: Port der Bridge-API auf dem Zielsystem.
        config: Daemon-Konfiguration (nur für Auth/Port-Override nötig).

    Returns:
        (success, message, HandoverPackage|None)
    """
    _ensure_table()
    my_sid = get_system_id()
    my_pc = get_pc_name()
    now = datetime.now().isoformat()

    if not check_fackel_mine_state(session_type):
        return False, "Fackel nicht im Besitz - Übergabe kann nicht beantragt werden", None

    package = HandoverPackage(
        source_system_id=my_sid,
        source_pc_name=my_pc,
        target_system_id=target_system_id,
        target_pc_name=target_pc_name,
        session_type=session_type,
        auth_token=auth_token,
        payload=payload or {},
    )

    _db_execute(
        f"""
        UPDATE {TABLE_NAME}
        SET handover_state = 'requested',
            handover_target_system_id = ?,
            handover_target_pc_name = ?,
            handover_requested_at = ?,
            handover_accepted_at = NULL,
            handover_payload = ?,
            updated_at = ?
        WHERE session_type = ?
        """,
        (
            target_system_id,
            target_pc_name,
            now,
            package.to_json(),
            now,
            session_type,
        ),
    )

    if notify_target:
        try:
            _notify_target(
                target_pc_name=target_pc_name,
                target_port=target_port,
                endpoint="/api/fackel/request",
                package=package,
                config=config,
            )
        except Exception as exc:
            # Notification ist optional; Request bleibt gültig.
            return True, f"Handover angefragt (Ziel-Benachrichtigung fehlgeschlagen: {exc})", package

    return True, "Handover angefragt", package


def accept_handover(
    session_type: str = "bridge",
    auth_token: Optional[str] = None,
    user_id: str = "",
) -> Tuple[bool, str, Optional[HandoverPackage]]:
    """
    Nimmt eine ausstehende Übergabe für diese Maschine an.

    Args:
        session_type: Typ der Session.
        auth_token: Optionaler Token zur Validierung (falls im Package gesetzt).

    Returns:
        (success, message, HandoverPackage|None)
    """
    _ensure_table()
    my_sid = get_system_id()
    my_pc = get_pc_name()
    now = datetime.now().isoformat()

    row = _get_or_create_row(session_type)
    if row["handover_state"] != "requested":
        return False, f"Keine ausstehende Übergabe (Status: {row['handover_state']})", None

    package = None
    if row["handover_payload"]:
        try:
            package = HandoverPackage.from_json(row["handover_payload"])
        except Exception:
            return False, "Handover-Payload ist beschädigt", None

    if package and package.target_system_id != my_sid:
        return False, f"Übergabe ist nicht für diese Maschine ({my_sid}) bestimmt", None

    if package and package.auth_token and package.auth_token != (auth_token or ""):
        return False, "Ungültiges Auth-Token für Handover", None

    # Prüfe Ablauf
    if package:
        try:
            expires = datetime.fromisoformat(package.expires_at)
            if datetime.now() > expires:
                _set_handover_state(session_type, "idle")
                return False, "Handover-Request ist abgelaufen", None
        except Exception:
            pass

    # Fackel übernehmen
    _db_execute(
        f"""
        UPDATE {TABLE_NAME}
        SET system_id = ?, pc_name = ?, acquired_at = ?, heartbeat_at = ?,
            is_active = 1, handover_state = 'accepted',
            handover_accepted_at = ?, updated_at = ?, user_id = ?
        WHERE session_type = ?
        """,
        (my_sid, my_pc, now, now, now, now, user_id, session_type),
    )

    msg = "Handover angenommen, Fackel übernommen"
    if package:
        msg += f" von {package.source_pc_name} ({package.source_system_id})"
    return True, msg, package


def get_handover_status(session_type: str = "bridge") -> HandoverStatus:
    """Liefert den aktuellen Handover-Status inklusive Package."""
    _ensure_table()
    row = _get_or_create_row(session_type)
    status = _row_to_status(row)

    # Prüfe abgelaufene Requests
    if status.handover_state == "requested" and status.package:
        try:
            expires = datetime.fromisoformat(status.package.expires_at)
            if datetime.now() > expires:
                _set_handover_state(session_type, "idle")
                row = _get_or_create_row(session_type)
                status = _row_to_status(row)
                status.message = "Handover-Request war abgelaufen und wurde zurückgesetzt"
        except Exception:
            pass

    return status


def release_handover(session_type: str = "bridge") -> Tuple[bool, str]:
    """
    Setzt den Handover-Status auf 'idle' zurück.

    Freigibt eine ausstehende oder angenommene Übergabe, ohne die Fackel selbst
    zu verlieren (siehe `release_fackel_state` für komplettes Abgeben).
    """
    _ensure_table()
    my_sid = get_system_id()
    now = datetime.now().isoformat()
    _db_execute(
        f"""
        UPDATE {TABLE_NAME}
        SET handover_state = 'idle', handover_target_system_id = NULL,
            handover_target_pc_name = NULL, handover_requested_at = NULL,
            handover_accepted_at = NULL, handover_payload = NULL, updated_at = ?
        WHERE session_type = ? AND system_id = ?
        """,
        (now, session_type, my_sid),
    )
    return True, "Handover-Status zurückgesetzt"


def _set_handover_state(session_type: str, state: str) -> None:
    """Interner Helfer zum Zurücksetzen des Handover-Status."""
    now = datetime.now().isoformat()
    _db_execute(
        f"""
        UPDATE {TABLE_NAME}
        SET handover_state = ?, updated_at = ?
        WHERE session_type = ?
        """,
        (state, now, session_type),
    )


# --- Netzwerk-Notification -------------------------------------------------

def _notify_target(
    target_pc_name: str,
    target_port: int,
    endpoint: str,
    package: HandoverPackage,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Sendet ein Handover-Event an die Bridge-API des Zielsystems.

    Verwendet den konfigurierten auth_token sofern vorhanden.
    """
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        return False, "urllib nicht verfügbar"

    auth_token = ""
    if config and isinstance(config, dict):
        auth_token = config.get("server", {}).get("auth_token", "")
        target_port = config.get("server", {}).get("port", target_port)

    url = f"http://{target_pc_name}:{target_port}{endpoint}"
    data = package.to_json().encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.read else ""
        return False, f"HTTP {exc.code}: {body}"
    except Exception as exc:
        return False, str(exc)


# --- Kompatibilität / Migration -------------------------------------------

def migrate_from_legacy_lock(
    session_type: str = "bridge",
    legacy_table: str = "bridge_session_lock",
    user_id: str = "",
) -> Tuple[bool, str]:
    """
    Migriert einen aktiven Eintrag aus der alten `bridge_session_lock` Tabelle
    in den neuen `fackel_state` Store.

    Wird von fackel.py aufgerufen wenn die alte Tabelle noch Daten enthält.
    """
    _ensure_table()
    my_sid = get_system_id()
    my_pc = get_pc_name()
    now = datetime.now().isoformat()

    try:
        conn = sqlite3.connect(str(BACH_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT pc_name, heartbeat_at, is_active
            FROM {legacy_table}
            WHERE session_type = ?
            """,
            (session_type,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return False, "Kein Legacy-Eintrag vorhanden"

        legacy_pc = row["pc_name"]
        legacy_active = bool(row["is_active"])
        # Wenn Legacy-Eintrag aktiv und wir sind der Host → übernehmen
        if legacy_active and legacy_pc == my_pc:
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME} (
                    session_type, system_id, pc_name, acquired_at, heartbeat_at,
                    is_active, handover_state, updated_at, user_id
                ) VALUES (?, ?, ?, ?, ?, 1, 'idle', ?, ?)
                ON CONFLICT(session_type) DO UPDATE SET
                    system_id = excluded.system_id,
                    pc_name = excluded.pc_name,
                    acquired_at = excluded.acquired_at,
                    heartbeat_at = excluded.heartbeat_at,
                    is_active = excluded.is_active,
                    handover_state = excluded.handover_state,
                    updated_at = excluded.updated_at,
                    user_id = excluded.user_id
                """,
                (session_type, my_sid, my_pc, now, row["heartbeat_at"] or now, now, user_id),
            )
            conn.commit()
            conn.close()
            return True, "Legacy-Fackel in State-Store übernommen"

        conn.close()
        return False, f"Legacy-Eintrag gehört {legacy_pc}"
    except sqlite3.OperationalError as exc:
        return False, f"Legacy-Tabelle nicht verfügbar: {exc}"


# --- Kleinere Helpers ------------------------------------------------------

def list_active_holders() -> List[Dict[str, Any]]:
    """Liefert alle aktiven Fackel-Halter (für Status-Übersichten)."""
    _ensure_table()
    rows = _db_execute(
        f"""
        SELECT session_type, system_id, pc_name, heartbeat_at, user_id
        FROM {TABLE_NAME}
        WHERE is_active = 1
        """,
        fetch=True,
    )
    result = []
    for r in rows:
        expired = False
        try:
            last = datetime.fromisoformat(r[3])
            expired = (datetime.now() - last) > timedelta(seconds=TIMEOUT_THRESHOLD)
        except Exception:
            expired = True
        result.append({
            "session_type": r[0],
            "system_id": r[1],
            "pc_name": r[2],
            "heartbeat_at": r[3],
            "user_id": r[4],
            "expired": expired,
        })
    return result


# --- CLI / Smoke-Test -----------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("FACKELTRÄGER STATE-STORE TEST")
    print("=" * 60)
    print(f"System-ID : {get_system_id()}")
    print(f"PC-Name   : {get_pc_name()}")
    print(f"BACH_DB   : {BACH_DB}")

    print("\n[1] Acquire State:")
    ok, msg = acquire_fackel_state("bridge")
    print(f"    {ok} - {msg}")

    print("\n[2] Heartbeat State:")
    print(f"    {heartbeat_state('bridge')}")

    print("\n[3] Check mine:")
    print(f"    {check_fackel_mine_state('bridge')}")

    print("\n[4] Holder:")
    holder = get_fackel_holder_state("bridge")
    print(f"    {holder}")

    print("\n[5] Handover Status:")
    status = get_handover_status("bridge")
    print(f"    {status.to_dict()}")

    print("\n[6] Release State:")
    release_fackel_state("bridge")
    print(f"    Holder after release: {get_fackel_holder_state('bridge')}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
