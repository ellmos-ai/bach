#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: MIT
"""
LeaseHandler - Polaris (Polarstern): Ressourcen-Lease ("star") fuer Einzelschreiber-Ressourcen (BACH #2121)

Aufruf: bach polaris <resource> <aktion> [optionen]

Aktionen:
  acquire   --by <agent@host> [--ttl POLARIS] [--intent T] [--version <sha256>] [--show-capability]
  renew     --lease-id <uuid> --fence <n> [--version <sha256>]
  release   --lease-id <uuid> --fence <n> [--version <sha256>]
  status    [--lease-id <uuid>]
  register  --allowed <muster,..> --server-role <muster> [--standby <muster,..>]
            [--bind <geraet=muster,..>]   (nur an der Lead-Authority)

Ohne erreichbaren Lead gibt es keine Uebernahme (Ressource bleibt nur lesbar).
"""

import sqlite3
from pathlib import Path
from typing import List, Tuple

from .base import BaseHandler

_USAGE = ("Usage: bach polaris <resource> acquire|renew|release|status|register [optionen] "
          "(Details: bach polaris help)")


def _flags(args: List[str]) -> dict:
    out, i = {}, 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key, eq, val = arg[2:].partition("=")
            if not eq:
                val = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
                i += 1 if val else 0
            out[key] = val
        i += 1
    return out


class LeaseHandler(BaseHandler):
    """Handler fuer Ressourcen-Leases. Die 'Operation' ist der Ressourcenname."""

    @property
    def profile_name(self) -> str:
        return "polaris"

    @property
    def target_file(self) -> Path:
        return self._canonical_db

    def get_operations(self) -> dict:
        return {
            "<resource> acquire": "Polaris star anfordern (--by agent@host [--ttl POLARIS] [--version HASH])",
            "<resource> renew": "Polaris star verlaengern (--lease-id --fence [--version HASH])",
            "<resource> release": "Polaris star zurueckgeben (--lease-id --fence [--version HASH])",
            "<resource> status": "Halter, Fence, Version anzeigen",
            "<resource> register": "Ressource registrieren (nur am Lead)",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self._canonical_db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation in ("help", "-h", "--help", ""):
            return True, __doc__
        if not args:
            return False, _USAGE
        action, opts = args[0], _flags(args[1:])
        if dry_run and action != "status":
            return True, "[DRY-RUN] Keine Lease-Aenderung"

        from hub._services.resource_lease_client import (
            LeaseError, LeaseProtocolError, ResourceLeaseClient, ResourceLeaseDeniedError,
        )
        try:
            with ResourceLeaseClient.for_db(self._get_db) as client:
                return self._run(client, operation, action, opts)
        except ResourceLeaseDeniedError as e:
            return False, f"[CONFLICT] {operation}: {e.reason}"
        except (LeaseError, LeaseProtocolError) as e:
            return False, f"[ERROR] {operation}: {e}"

    def _run(self, client, resource: str, action: str, opts: dict) -> Tuple[bool, str]:
        if action == "status":
            st = client.status(resource, lease_id=opts.get("lease-id") or None)
            lines = [f"{resource}: Leased={st.leased}, Fence={st.fence}, Version={st.resource_version}, "
                     f"Server aktiv={st.server_active}"]
            if st.holder:
                lines.append(f"Halter: {st.holder.get('worker_id')} ({st.holder.get('role')}), "
                             f"Ablauf {st.expires_at}")
            if st.own:
                lines.append("[OWN POLARIS STAR CONFIRMED]")
            return True, "\n".join(lines)

        if action == "acquire":
            by = (opts.get("by") or "").strip()
            if not by:
                return False, "Usage-Fehler: --by <agent@host> ist erforderlich"
            ack = client.acquire(resource, worker_id=by, host=opts.get("host") or None,
                                 ttl_profile=opts.get("ttl") or None, intent=opts.get("intent", ""),
                                 resource_version=opts.get("version") or None)
            text = (f"[OK] Polaris star {resource} an {ack.worker_id} ({ack.role}, Fence {ack.fence}, "
                    f"Profil {ack.ttl_profile}, Frist bis {ack.expires_at}, "
                    f"Renew alle {ack.renew_after_seconds}s)")
            if "show-capability" in opts:
                return True, text + "\nLease-Capability: " + ack.lease_id
            return True, text + "\n(Capability nicht ausgegeben; mit --show-capability anzeigen)"

        if action in ("renew", "release"):
            lease_id, fence = opts.get("lease-id", ""), opts.get("fence", "")
            if not lease_id or not fence.isdigit():
                return False, f"Usage: bach polaris {resource} {action} --lease-id <uuid> --fence <n>"
            version = opts.get("version") or None
            if action == "renew":
                new = client.renew_ref(resource, lease_id, int(fence), resource_version=version)
                return True, f"[OK] Polaris star {resource} verlaengert (Fence {new.fence}, bis {new.expires_at})"
            done = client.release_ref(resource, lease_id, int(fence), resource_version=version)
            return True, (f"[OK] Polaris star {resource} zurueckgegeben (Fence {done.fence}"
                          f"{', verspaetet' if done.late else ''})")

        if action == "register":
            if not client.is_lead_authority:
                return False, "[ERROR] register ist nur an der Lead-Authority moeglich (nicht isolated/Worker)"
            from hub._services.resource_lease import register_resource
            split = lambda v: [p for p in (v or "").split(",") if p]  # noqa: E731
            bindings: dict = {}
            for pair in split(opts.get("bind")):  # Format geraet=muster, mehrfach je Geraet moeglich
                device, _, pattern = pair.partition("=")
                bindings.setdefault(device, []).append(pattern)
            info = register_resource(client._conn, resource, allowed_workers=split(opts.get("allowed")),
                                     device_bindings=bindings,
                                     server_role=opts.get("server-role", ""),
                                     standby_roles=split(opts.get("standby")))
            return True, f"[OK] Ressource {resource} registriert: {info}"
        return False, _USAGE
