# SPDX-License-Identifier: MIT
"""GUI Contract Service - Shared GUI Kit, Universal Fallback & Backend Origin.

Implements the contract and verification layer for GUX-001–004 and GUX-092
(Ticket T-20261003-793817309, Task #1695):
- GUX-001: Pinned Kit Commit & Manifest Verification (ellmos-system-gui.brand.v1, ellmos-system-gui.dist.v1)
- GUX-002: Universal GUI Fallback Isolation & Differentiation
- GUX-003: Backend Origin, Instance Binding & Non-Claim Guarantee
- GUX-004: Canonical Definitions of SALT, Trithon, and Muschelgrund
- GUX-092: Standalone Dashboard Functions & Fallback Parity
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

KIT_MANIFEST_PATH = Path(__file__).resolve().parent.parent.parent / "gui" / "kit_manifest.json"
BRAND_SCHEMA = "ellmos-system-gui.brand.v1"
ORIGIN_SCHEMA = "ellmos-system-gui.backend-origin.v1"
KIT_SCHEMA = "ellmos-system-gui.kit-manifest.v1"
DIST_SCHEMA = "ellmos-system-gui.dist.v1"
CAPABILITIES_SCHEMA = "ellmos.gui.capabilities.v1"


def resolve_gui_distribution(gui_dir: Path, configured: str | None = None) -> Path:
    """An explicit consumer release remains authoritative, including when missing."""
    if configured:
        return Path(os.path.expandvars(configured)).expanduser()
    return gui_dir / "web" / "dist"


def get_pinned_kit_manifest(manifest_path: Path = KIT_MANIFEST_PATH) -> dict[str, Any]:
    """Read the pinned release identity for the shared GUI kit."""
    if not manifest_path.exists():
        return {
            "schema": KIT_SCHEMA,
            "pinned_source_commit": None,
            "version": None,
            "dist_manifest_schema": DIST_SCHEMA,
            "expected_page_count": 16,
            "release_archive": None,
            "release_archive_sha256": None,
            "verified": False,
            "error": "kit_manifest_not_found",
        }
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != KIT_SCHEMA:
            return {
                "schema": KIT_SCHEMA,
                "verified": False,
                "error": "invalid_kit_manifest_schema",
            }
        if (not re.fullmatch(r"[0-9a-f]{40}", str(data.get("pinned_source_commit", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(data.get("release_archive_sha256", "")))
                or data.get("dist_manifest_schema") != DIST_SCHEMA
                or type(data.get("expected_page_count")) is not int
                or data["expected_page_count"] < 1
                or not isinstance(data.get("version"), str) or not data["version"]
                or not isinstance(data.get("release_archive"), str) or not data["release_archive"].endswith(".zip")
                or Path(data["release_archive"]).name != data["release_archive"]):
            return {"schema": KIT_SCHEMA, "verified": False, "error": "invalid_release_identity"}
        # Valid identity metadata. Installed byte verification happens separately.
        data["verified"] = True
        return data
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {
            "schema": KIT_SCHEMA,
            "verified": False,
            "error": "manifest_read_error",
        }


def verify_installed_dist(dist_dir: Path, expected_commit: str | None = None) -> dict[str, Any]:
    """Verify that an installed or referenced dist/ directory matches its dist-manifest."""
    if not dist_dir.exists() or not dist_dir.is_dir():
        return {
            "installed": False,
            "verified": False,
            "reason_code": "dist_directory_missing",
            "page_count": 0,
        }

    manifest_file = dist_dir / "dist-manifest.json"
    if not manifest_file.exists():
        return {
            "installed": True,
            "verified": False,
            "reason_code": "dist_manifest_missing",
            "page_count": 0,
        }

    try:
        dist_meta = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(dist_meta, dict) or dist_meta.get("schema") != DIST_SCHEMA:
            return {
                "installed": True,
                "verified": False,
                "reason_code": "invalid_dist_manifest_schema",
                "page_count": 0,
            }

        if not re.fullmatch(r"[0-9a-f]{40}", str(dist_meta.get("source_commit", ""))):
            return {"installed": True, "verified": False, "reason_code": "invalid_source_commit", "page_count": 0}
        files_map = dist_meta.get("files", {})
        if not isinstance(files_map, dict) or not files_map:
            return {
                "installed": True,
                "verified": False,
                "reason_code": "empty_dist_manifest",
                "page_count": 0,
            }

        if expected_commit and dist_meta.get("source_commit") != expected_commit:
            return {
                "installed": True,
                "verified": False,
                "reason_code": "commit_mismatch",
                "expected_commit": expected_commit,
                "actual_commit": dist_meta.get("source_commit"),
                "page_count": len(files_map),
            }

        root = dist_dir.resolve()
        actual_files = set()
        for item in dist_dir.rglob("*"):
            if item.is_symlink():
                return {"installed": True, "verified": False, "reason_code": "dist_symlink", "page_count": 0}
            if item.is_file() and item != manifest_file:
                actual_files.add(item.relative_to(dist_dir).as_posix())
        mismatches: list[str] = []
        for rel_path, expected_digest in files_map.items():
            if (not isinstance(rel_path, str) or not rel_path or "\\" in rel_path
                    or ":" in rel_path or rel_path.startswith("/")
                    or any(part in {"", ".", ".."} for part in rel_path.split("/"))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(expected_digest))):
                return {"installed": True, "verified": False, "reason_code": "invalid_dist_entry", "page_count": 0}
            fpath = dist_dir / rel_path
            if not fpath.resolve().is_relative_to(root):
                return {"installed": True, "verified": False, "reason_code": "invalid_dist_entry", "page_count": 0}
            if not fpath.is_file():
                mismatches.append(f"missing: {rel_path}")
                continue
            actual_digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if actual_digest != expected_digest:
                mismatches.append(f"digest_mismatch: {rel_path}")

        if actual_files != set(files_map):
            mismatches.append("file_set_mismatch")

        if mismatches:
            return {
                "installed": True,
                "verified": False,
                "reason_code": "integrity_mismatch",
                "mismatches": mismatches[:5],
                "page_count": len([k for k in files_map if k.endswith(".html")]),
            }

        html_pages = [k for k in files_map if k.endswith(".html")]
        return {
            "installed": True,
            "verified": True,
            "source_commit": dist_meta.get("source_commit"),
            "reason_code": "verified",
            "page_count": len(html_pages),
            "files_count": len(files_map),
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {
            "installed": True,
            "verified": False,
            "reason_code": "dist_inspection_error",
            "page_count": 0,
        }


def get_architectural_concepts() -> dict[str, Any]:
    """Canonical definitions for SALT, Trithon, and Muschelgrund (GUX-004).

    Prevents conflation between task leases, multi-host dispatch, and cognitive memory.
    """
    return {
        "schema": "ellmos.architecture.concepts.v1",
        "verified": True,
        "concepts": {
            "salt": {
                "name": "SALT (State & Authority Lease Token)",
                "role": "Task-Claim- & Ressourcen-Sperrkoordination",
                "purpose": (
                    "Koordiniert atomare Task-Übernahmen (claim-salt) und exklusive Ressourcen-Locks (lock-salt) "
                    "über zeitlich begrenzte Leases mit Monotonic Fencing und TTL. SALT erteilt KEINE impliziten "
                    "Schreibfreibriefe und setzt lokale LOCK*.txt-Schutzdateien niemals außer Kraft."
                ),
                "scope": ["task_leases", "claim_salt", "lock_salt", "fencing"],
                "authority_model": "Fail-closed, Single-Owner per Lease, Expiration-Guarded",
            },
            "trithon": {
                "name": "Trithon (Multi-Host Intent Dispatch & Execution)",
                "role": "Verteilte Ausführungs- & Scheduler-Abstraktion",
                "purpose": (
                    "Koordiniert die rechnerübergreifende Beauftragung von Intent-Ausführungen zwischen Mac Studio "
                    "(Lead), Windows Laptop (ASUS-GEI) und Linux Workstation. Dispatched Intents via SyntheticTicket, "
                    "begleitet Runs durch agents-heart Besetzungen und erzeugt kryptografisch signierte ExecutionReceipts."
                ),
                "scope": ["intent_dispatch", "synthetic_ticket", "execution_receipt", "multi_host_scheduler"],
                "authority_model": "Host-bound execution with Lead TaskDB synchronization",
            },
            "muschelgrund": {
                "name": "Muschelgrund (Curated Memory Projection)",
                "role": "Kognitiver Langzeitspeicher & Episodisches Gedächtnis",
                "purpose": (
                    "Historischer Speicherort für kuratierte Wissensprojektionen, Sitzungsgedächtnis, "
                    "Reflexionen und episodische Puffer. Vollständig getrennt von Host-Clustern oder "
                    "Lead-Server-Rollen (keine Vermischung mit Trithon/SALT-Topologie)."
                ),
                "scope": ["deep_memory", "session_memory", "episodic_buffer", "knowledge_projections"],
                "authority_model": "Domain-scoped, provenance-tracked, append-oriented",
            },
        },
        "system_insignia": {
            "fackel": "Zeigt tatsächlichen Compute-Besitz und steuert Vorrang zwischen Hintergrund-Worker und interaktivem Chat.",
            "lead_authority": "Mac Studio TaskDB als alleinige operative SSoT für Zuweisungen und Erledigungsnachweise.",
        },
    }
