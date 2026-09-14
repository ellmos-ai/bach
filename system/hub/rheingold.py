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
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


LEAD_CONFIG_FILE = Path.home() / ".bach" / "lead.json"

DEFAULT_RHEINGOLD_HOSTS = [
    "http://100.119.69.90:8000",
    "http://macstudvonlukas:8000",
    "http://macstudvonlukas.local:8000",
]

LEAD_HOSTNAMES = {
    "macstudvonlukas",
    "macstudvonlukas.local",
    "mac-studio",
}


def is_rheingold_lead() -> bool:
    """Prüft, ob dieser Prozess direkt auf dem Rheingold-Lead-Host läuft."""
    if os.environ.get("BACH_IS_RHEINGOLD_LEAD") == "1" or os.environ.get("BACH_MODE") == "lead":
        return True
    hostname = socket.gethostname().lower()
    return hostname in LEAD_HOSTNAMES or hostname.startswith("macstud")


def get_lead_config() -> dict:
    """Ermittelt die konfigurierte Lead-Rolle und Server-URL.

    Modi:
    - 'lead': Dieser Host ist selbst Rheingold-Lead (Mac Studio).
    - 'worker': Host ist Client und nutzt einen festgelegten Rheingold-Lead.
    - 'isolated': Host arbeitet autark/isoliert ohne externe Synchronisation.
    """
    if (
        "pytest" in sys.modules
        or os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("BACH_MODE") == "isolated"
        or os.environ.get("BACH_RHEINGOLD_DISABLED") == "1"
    ):
        if os.environ.get("BACH_TEST_RHEINGOLD") != "1":
            return {"mode": "isolated", "lead_url": None}

    if is_rheingold_lead():
        return {"mode": "lead", "lead_url": None}

    env_url = os.environ.get("BACH_LEAD_URL") or os.environ.get("BACH_RHEINGOLD_URL")
    if env_url:
        return {"mode": "worker", "lead_url": env_url.rstrip("/")}

    if LEAD_CONFIG_FILE.is_file():
        try:
            data = json.loads(LEAD_CONFIG_FILE.read_text(encoding="utf-8"))
            mode = data.get("mode", "worker")
            if mode == "isolated":
                return {"mode": "isolated", "lead_url": None}
            lead_url = data.get("lead_url")
            if lead_url:
                return {"mode": "worker", "lead_url": lead_url.rstrip("/")}
        except Exception:
            pass

    # Grundsatz: Ohne explizit festgelegten Lead arbeitet BACH isoliert
    return {"mode": "isolated", "lead_url": None}


def set_lead_url(url: str, mode: str = "worker") -> Path:
    """Speichert den festgelegten Rheingold-Lead in ~/.bach/lead.json."""
    LEAD_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "lead_url": url.rstrip("/"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    LEAD_CONFIG_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return LEAD_CONFIG_FILE


def clear_lead_config() -> bool:
    """Entfernt die Lead-Konfiguration und schaltet die Instanz auf 'isolated'."""
    if LEAD_CONFIG_FILE.is_file():
        try:
            LEAD_CONFIG_FILE.unlink()
            return True
        except Exception:
            pass
    return False


def get_rheingold_url(timeout: float = 1.2) -> Optional[str]:
    """Ermittelt eine erreichbare Rheingold-Server-URL.

    Gibt None zurück, wenn offline, im Modus 'isolated' oder wenn Lead-Host selbst.
    """
    cfg = get_lead_config()
    if cfg["mode"] != "worker" or not cfg["lead_url"]:
        return None

    candidates: List[str] = [cfg["lead_url"]]
    for fallback in DEFAULT_RHEINGOLD_HOSTS:
        if fallback not in candidates:
            candidates.append(fallback)

    for url in candidates:
        endpoint = f"{url}/api/tasks?limit=1"
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


def pull_tasks_from_rheingold(
    conn: sqlite3.Connection,
    base_url: str,
    timeout: float = 8.0,
) -> Tuple[int, int]:
    """Spiegelt alle Tasks vom Rheingold-Lead in den lokalen Bachgrund.

    Returns:
        (inserted_count, updated_count)
    """
    endpoint = f"{base_url.rstrip('/')}/api/tasks?limit=10000"
    req = urllib.request.Request(
        endpoint,
        headers={"User-Agent": "BACH-RheingoldClient/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    server_tasks = body.get("tasks", [])
    if not server_tasks:
        return 0, 0

    cols = [
        "id", "title", "description", "category", "priority", "tags", "status",
        "estimated_minutes", "actual_minutes", "delegated_to", "delegation_status",
        "source_file", "source_line", "is_recurring", "recurrence_pattern",
        "next_occurrence", "due_date", "executable_command", "created_at",
        "started_at", "completed_at", "updated_at", "dist_type", "modified_by",
        "depends_on", "created_by", "assigned_to", "project", "source",
    ]

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(tasks)")
    available_cols = {row[1] for row in cursor.fetchall()}
    cols = [c for c in cols if c in available_cols]

    local_rows = cursor.execute("SELECT * FROM tasks").fetchall()
    local_map = {row["id"]: dict(row) for row in local_rows}

    inserted = 0
    updated = 0

    for st in server_tasks:
        tid = st.get("id")
        if tid is None or tid < 0:
            continue

        if tid not in local_map:
            col_names = ", ".join(cols)
            placeholders = ", ".join(["?"] * len(cols))
            values = [st.get(c) for c in cols]
            cursor.execute(f"INSERT INTO tasks ({col_names}) VALUES ({placeholders})", values)
            inserted += 1
        else:
            lt = local_map[tid]
            differ = any(lt.get(c) != st.get(c) for c in cols if c != "id")
            if differ:
                set_clause = ", ".join([f"{c} = ?" for c in cols if c != "id"])
                values = [st.get(c) for c in cols if c != "id"] + [tid]
                cursor.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
                updated += 1

    if inserted or updated:
        conn.commit()

    return inserted, updated
