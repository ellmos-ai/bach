# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Rheingold Client & Authority Engine
===================================
Verwaltet die Anbindung an den zentralen Rheingold-Lead-Server (Mac Studio)
für kollisionsfreies Multi-Host-Tasking und Hash-to-TaskID Staging.

Architektur:
- Rheingold Lead (Mac Studio:8000): Autoritative Task-ID-Vergabe und Server-Bachgrund.
- Lokaler Bachgrund: Lokaler Cache und Offline-Staging-Puffer.
- Hash-to-ID: Offline-Tasks erhalten 'draft:<host>:<hash>' statt Integer-IDs.
"""

import email
import email.parser
import hashlib
import json
import os
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple


DEFAULT_RHEINGOLD_HOSTS = [
    "http://macstudvonlukas:8000",
    "http://100.119.69.90:8000",
]

LEAD_HOSTNAMES = {
    "macstudvonlukas",
    "macstudvonlukas.local",
    "mac-studio",
}


def is_rheingold_lead() -> bool:
    """Prüft, ob dieser Prozess direkt auf dem Rheingold-Lead-Host läuft."""
    if os.environ.get("BACH_IS_RHEINGOLD_LEAD") == "1":
        return True
    hostname = socket.gethostname().lower()
    return hostname in LEAD_HOSTNAMES or hostname.startswith("macstud")


def get_rheingold_url(timeout: float = 1.2) -> Optional[str]:
    """Ermittelt eine erreichbare Rheingold-Server-URL.

    Gibt None zurück, wenn offline, Lead-Host selbst oder per ENV deaktiviert.
    """
    if os.environ.get("BACH_RHEINGOLD_DISABLED") == "1":
        return None

    # Wenn wir auf dem Lead selbst sind, arbeiten wir direkt lokal
    if is_rheingold_lead():
        return None

    candidates: List[str] = []
    env_url = os.environ.get("BACH_RHEINGOLD_URL")
    if env_url:
        candidates.append(env_url.rstrip("/"))
    candidates.extend(DEFAULT_RHEINGOLD_HOSTS)

    for url in candidates:
        endpoint = f"{url}/api/tasks"
        try:
            req = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "BACH-RheingoldClient/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue

    return None


def generate_draft_hash(title: str, category: str = "", host: Optional[str] = None) -> str:
    """Generiert einen kollisionsfreien Staging-Hash für Offline-Tasks."""
    h_name = (host or socket.gethostname()).split(".")[0].lower()[:6]
    seed = f"{h_name}:{time.time_ns()}:{title}:{category}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()[:8]
    return f"draft:{h_name}:{digest}"


def post_task_to_rheingold(
    base_url: str,
    payload: dict,
    timeout: float = 5.0,
) -> Tuple[bool, dict]:
    """Sendet einen Task an den Rheingold-Server."""
    endpoint = f"{base_url.rstrip('/')}/api/tasks"
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "BACH-RheingoldClient/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if resp.status in (200, 201) and body.get("success"):
                return True, body
            return False, body
    except Exception as e:
        return False, {"error": str(e)}


def sync_drafts_to_rheingold(
    conn: sqlite3.Connection,
    base_url: str,
) -> List[Dict[str, any]]:
    """Überträgt alle lokal gestagten Entwürfe an Rheingold und ersetzt die temporären IDs."""
    cursor = conn.cursor()
    # Finde alle Tasks mit Draft-Source
    cursor.execute("""
        SELECT id, title, description, priority, category, status, due_date, source, depends_on
        FROM tasks
        WHERE source LIKE 'draft:%'
        ORDER BY id ASC
    """)
    drafts = cursor.fetchall()
    promoted = []

    for row in drafts:
        old_id, title, desc, prio, cat, stat, due, draft_src, deps = row
        payload = {
            "title": title,
            "description": desc or "",
            "priority": prio or "P3",
            "category": cat or "general",
            "status": stat or "pending",
            "due_date": due,
            "depends_on": deps,
            "source": draft_src,
            "created_by": socket.gethostname().split(".")[0].lower(),
        }

        ok, res = post_task_to_rheingold(base_url, payload)
        if ok and "id" in res:
            new_id = res["id"]
            # Aktualisiere Task im lokalen Bachgrund
            cursor.execute("""
                UPDATE tasks
                SET id = ?, source = ?
                WHERE id = ?
            """, (new_id, f"promoted:{draft_src}", old_id))

            # Aktualisiere auch Abhängigkeiten, falls andere Tasks von der alten ID abhingen
            cursor.execute("""
                UPDATE tasks
                SET depends_on = REPLACE(depends_on, ?, ?)
                WHERE depends_on LIKE ?
            """, (str(old_id), str(new_id), f"%{old_id}%"))

            promoted.append({
                "old_id": old_id,
                "draft_hash": draft_src,
                "new_id": new_id,
                "title": title,
                "status": res.get("status", "promoted"),
            })

    if promoted:
        conn.commit()

    return promoted
