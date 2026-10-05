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
Fackelträger Thin-Wrapper für die Claude Bridge (S2 Handover-Mechanismus)
=========================================================================
Beibehält die alte Bridge-Lock-Logik und den 24h-Regel-Check,
delegiert den Fackel-State aber an `hub/_services/fackeltraeger.py`.

Neu gegenüber der Legacy-Implementierung:
- `request_handover()` baut ein `HandoverPackage`, delegiert die
  Netzwerk-Notification an `fackeltraeger.request_handover()` und
  protokolliert eine Note in `session_context.handover_notes`.
- `accept_handover()` reicht ein empfangenes JSON-Paket an
  `fackeltraeger.accept_handover()` weiter.
- `migrate_from_legacy_lock()` bleibt als Kompatibilitäts-Wrapper erhalten.
"""

import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))

from hub.bach_paths import BACH_DB
from hub._services.fackeltraeger import (
    HandoverPackage,
    acquire_fackel_state,
    check_fackel_mine_state,
    get_fackel_holder_state,
    get_handover_status,
    get_pc_name,
    get_system_id,
    heartbeat_state,
    list_active_holders,
    migrate_from_legacy_lock as _migrate_from_legacy_lock,
    release_fackel_state,
    release_handover as _release_handover,
    request_handover as _request_handover_ft,
    accept_handover as _accept_handover_ft,
)

# --- Kompatibilitäts-Konstanten ---
HEARTBEAT_INTERVAL = 60  # Sekunden
TIMEOUT_THRESHOLD = 300  # 5 Minuten

H24_SESSION_TYPES = ("bridge", "personal_assistant")
MAX_24H_ACTIVE = 2

# `session_context` wird von `bridge_daemon.py` injiziert, damit
# handover-Notes in der aktiven Session verfügbar sind.
try:
    from hub._services import session_context as _session_context
except Exception:  # pragma: no cover - läuft auch ohne Session-Context
    _session_context = None


def _handover_notes() -> List[str]:
    """Zugriff auf `session_context.handover_notes` mit lokalem Fallback."""
    if _session_context is not None and hasattr(_session_context, "handover_notes"):
        return _session_context.handover_notes
    return []


def _append_handover_note(note: str) -> None:
    """Schreibt eine zeitgestempelte Handover-Note."""
    notes = _handover_notes()
    if notes is not None:
        notes.append(f"{datetime.now().isoformat()} — {note}")


def _hash_token(token: str) -> str:
    """Kurzer SHA256-Hash für das Auth-Token im Handover-Paket."""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _active_24h_count(session_type: str, user_id: str = "") -> Tuple[int, bool]:
    """
    Zählt aktive 24h-Instanzen und prüft, ob der gleiche Benutzer
    bereits einen aktiven Eintrag des gegebenen `session_type` hält.

    Regeln:
    - Jeder `user_id` darf maximal eine aktive 24h-Session halten
      (Single-24h-Privileg, Task #1598).
    - Fremde `user_id` zählen gegen das globale 24h-Limit
      `MAX_24H_ACTIVE` (Task #1593).
    """
    holders = list_active_holders()
    active = [h for h in holders if h.get("session_type") in H24_SESSION_TYPES]
    self_active = any(
        h.get("session_type") == session_type and h.get("user_id") == user_id
        for h in active
    )
    # Nur fremde aktive 24h-Einträge zählen gegen das globale Limit.
    foreign_active = [h for h in active if h.get("user_id") != user_id]
    return len(foreign_active), self_active


def _active_holder_user(session_type: str) -> Optional[str]:
    """
    Liefert die `user_id` eines aktiven (nicht expired), nicht-leeren
    Halters für den angegebenen `session_type` zurück; sonst `None`.

    Wird verwendet, um für Nicht-24h-Session-Typen einen Benutzer-Gate
    zu realisieren: eine andere `user_id` darf die Fackel nicht übernehmen,
    solange ein aktiver Halter mit fremder `user_id` existiert.
    """
    for h in list_active_holders():
        if h.get("session_type") != session_type:
            continue
        if h.get("expired"):
            continue
        uid = (h.get("user_id") or "").strip()
        if uid:
            return uid
    return None


def acquire_fackel(session_type: str = "bridge", user_id: str = "user") -> Tuple[bool, Optional[str]]:
    """
    Versucht die Fackel zu holen.

    Beibehält den alten 24h-Regel-Check, delegiert den State-Write aber
    an `fackeltraeger.acquire_fackel_state()`.
    """
    # Erst versuchen, einen bestehenden Legacy-Lock zu übernehmen.
    _migrate_from_legacy_lock(session_type, user_id=user_id)

    # --- 24h-Regeln prüfen (nur für 24h-Session-Typen, Task #1593/#1598) ---
    if session_type in H24_SESSION_TYPES:
        count, self_active = _active_24h_count(session_type, user_id=user_id)

        # Single-24h-Privileg pro User (Task #1598):
        # Derselbe user_id darf nicht gleichzeitig zwei *unterschiedliche*
        # aktive 24h-Session-Typen halten. Ein Re-Acquire des bereits
        # gehaltenen eigenen session_type bleibt erlaubt.
        if user_id:
            eigene_aktiv = [
                h
                for h in list_active_holders()
                if h.get("user_id") == user_id
                and h.get("session_type") in H24_SESSION_TYPES
                and h.get("session_type") != session_type
            ]
            if eigene_aktiv:
                aktive_typen = sorted(
                    {h.get("session_type") for h in eigene_aktiv}
                )
                return (
                    False,
                    f"Single-24h-Privileg verletzt: user '{user_id}' hält bereits {', '.join(aktive_typen)}",
                )

        # Globales Limit: maximal MAX_24H_ACTIVE fremde 24h-Sessions.
        if count >= MAX_24H_ACTIVE:
            aktive = sorted(
                {
                    h.get("session_type")
                    for h in list_active_holders()
                    if h.get("session_type") in H24_SESSION_TYPES
                }
            )
            return (
                False,
                f"24h-Limit erreicht ({count}/{MAX_24H_ACTIVE}). Aktiv: {', '.join(aktive)}",
            )

    # --- Benutzer-Gate für Nicht-24h-Session-Typen ---
    # Für kurzlebige Session-Typen darf eine andere user_id die Fackel
    # nicht übernehmen, solange ein aktiver (nicht expired) Halter existiert.
    if session_type not in H24_SESSION_TYPES:
        active_user = _active_holder_user(session_type)
        if active_user is not None and active_user != user_id:
            return (
                False,
                f"Fackel von anderem Benutzer '{active_user}' gehalten",
            )

    ok, _msg = acquire_fackel_state(session_type, user_id=user_id)
    if not ok:
        holder = get_fackel_holder(session_type)
        return False, f"Fackel bereits bei {holder or 'unbekannt'}"
    return True, "Fackel erworben"


def heartbeat(session_type: str = "bridge") -> bool:
    """Sendet einen Heartbeat an den State-Store."""
    return heartbeat_state(session_type)


def release_fackel(session_type: str = "bridge") -> bool:
    """Gibt die Fackel frei."""
    return release_fackel_state(session_type)


def get_fackel_holder(session_type: str = "bridge") -> Optional[str]:
    """Liefert den aktuellen Fackelhalter (pc_name)."""
    state = get_fackel_holder_state(session_type)
    if state:
        return state[0]
    return None


def check_fackel_mine(session_type: str = "bridge") -> bool:
    """Prüft, ob diese Maschine die Fackel hält (Legacy-Alias)."""
    return check_fackel_mine_state(session_type)


def request_handover(
    target_pc_name: str,
    target_system_id: str,
    session_type: str = "bridge",
    auth_token: str = "",
    note: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    user_id: str = "",
) -> Tuple[bool, str]:
    """
    Baut ein `HandoverPackage` und reicht es an `fackeltraeger.request_handover()`.

    Schreibt zusätzlich eine Handover-Note in `session_context.handover_notes`.
    """
    now = datetime.now()
    expires = now + timedelta(minutes=5)

    package = HandoverPackage(
        session_type=session_type,
        source_system_id=get_system_id(),
        source_pc_name=get_pc_name(),
        target_pc_name=target_pc_name,
        target_system_id=target_system_id,
        issued_at=now.isoformat(),
        expires_at=expires.isoformat(),
        auth_token_hash=_hash_token(auth_token),
        metadata=metadata or {},
    )
    package.metadata["user_id"] = user_id

    note_text = note or f"Handover requested → {target_pc_name} ({target_system_id})"
    _append_handover_note(note_text)

    ok, msg = _request_handover_ft(
        package,
        config={"server": {"auth_token": auth_token}},
    )
    return ok, msg


def accept_handover(package_json: str, auth_token: str = "") -> Tuple[bool, str]:
    """
    Nimmt ein empfangenes Handover-Paket entgegen.
    Delegiert an `fackeltraeger.accept_handover()`.
    """
    import json

    user_id = ""
    try:
        parsed = json.loads(package_json)
        user_id = parsed.get("metadata", {}).get("user_id", "")
    except Exception:
        pass

    ok, msg = _accept_handover_ft(package_json, auth_token, user_id=user_id)
    if ok:
        _append_handover_note(f"Handover accepted: {msg}")
    else:
        _append_handover_note(f"Handover accept failed: {msg}")
    return ok, msg


def get_handover(session_type: str = "bridge") -> Dict[str, Any]:
    """Liefert den aktuellen Handover-Status als Dictionary."""
    status = get_handover_status(session_type)
    return {
        "session_type": status.session_type,
        "state": status.state,
        "source_pc": status.source_pc_name,
        "target_pc": status.target_pc_name,
        "requested_at": status.requested_at,
        "accepted_at": status.accepted_at,
        "completed_at": status.completed_at,
    }


def release_handover(session_type: str = "bridge") -> Tuple[bool, str]:
    """Setzt einen hängenden Handover-Request zurück."""
    return _release_handover(session_type)


def migrate_from_legacy_lock(session_type: str = "bridge") -> Tuple[bool, str]:
    """Kompatibilitäts-Wrapper zur Migration aus der alten Lock-Tabelle."""
    return _migrate_from_legacy_lock(session_type)


__all__ = [
    "acquire_fackel",
    "heartbeat",
    "release_fackel",
    "get_fackel_holder",
    "check_fackel_mine",
    "request_handover",
    "accept_handover",
    "get_handover",
    "release_handover",
    "migrate_from_legacy_lock",
    "HandoverPackage",
    "HEARTBEAT_INTERVAL",
    "TIMEOUT_THRESHOLD",
    "H24_SESSION_TYPES",
    "MAX_24H_ACTIVE",
]
