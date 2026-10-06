# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach GUI & CLI Adapter for Swarm Radar / GPS (from Roshambo).

Provides real-time visibility into active subagents, who holds which task lease,
and collision history (turned away workers) across hosts (ASUS-GEI, WORKSTATION-LG, Mac Studio).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SwarmLeaseEntry:
    task_id: int
    title: str
    claimed_by: str
    claim_host: str
    heartbeat_at: Optional[str]
    expires_at: Optional[str]
    is_active: bool


class BachSwarmRadar:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_radar_snapshot(self) -> Dict[str, Any]:
        """Returns the current state of active leases, agents, and claims."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            # Ensure columns exist safely
            cursor.execute("PRAGMA table_info(tasks)")
            cols = {r[1] for r in cursor.fetchall()}
            if "claim_id" not in cols:
                return {
                    "total_active_leases": 0,
                    "leases": [],
                    "active_hosts": [],
                    "active_agents": [],
                }

            cursor.execute(
                """
                SELECT id, title, claimed_by, claim_host, claim_heartbeat_at, claim_expires_at,
                       datetime('now') <= datetime(claim_expires_at) as is_live
                  FROM tasks
                 WHERE claim_id IS NOT NULL
                   AND claimed_by IS NOT NULL
                   AND datetime('now') <= datetime(claim_expires_at)
                 ORDER BY claim_expires_at DESC
                """
            )
            leases: List[SwarmLeaseEntry] = []
            hosts = set()
            agents = set()

            for row in cursor.fetchall():
                is_live = bool(row[6])
                entry = SwarmLeaseEntry(
                    task_id=row[0],
                    title=row[1],
                    claimed_by=row[2],
                    claim_host=row[3] or "local",
                    heartbeat_at=row[4],
                    expires_at=row[5],
                    is_active=is_live,
                )
                leases.append(entry)
                if is_live:
                    hosts.add(entry.claim_host)
                    agents.add(entry.claimed_by)

            return {
                "total_active_leases": len(leases),
                "leases": [
                    {
                        "task_id": l.task_id,
                        "title": l.title,
                        "claimed_by": l.claimed_by,
                        "claim_host": l.claim_host,
                        "expires_at": l.expires_at,
                        "heartbeat_at": l.heartbeat_at,
                    }
                    for l in leases
                ],
                "active_hosts": sorted(list(hosts)),
                "active_agents": sorted(list(agents)),
                "polled_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            conn.close()
