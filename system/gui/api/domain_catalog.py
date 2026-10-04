"""Read public domain manifests without inferring installation or activity."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_STATUSES = {"active", "released", "development", "alpha", "experimental", "staging", "planned", "deprecated"}


def module_root() -> Path:
    configured = os.environ.get("ELLMOS_MODULES_ROOT")
    return Path(configured).expanduser() if configured else Path.home() / "OneDrive" / ".TOPICS" / ".AI" / ".MODULES"


def discover_domains(root: Path | None = None) -> dict:
    """Return manifest metadata only; a manifest does not prove installation."""
    domains_root = ((root or module_root()) / ".DOMAINS").resolve()
    response = {
        "source": "ellmos_domain_manifests",
        "source_available": False,
        "domains": [],
        "total": 0,
        "installed_count": None,
        "running_count": None,
        "installation_evidence": "not_configured",
    }
    if not domains_root.is_dir():
        return response
    response["source_available"] = True
    try:
        candidates = sorted(domains_root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        response["source_available"] = False
        return response
    seen_ids: set[str] = set()
    for directory in candidates:
        if not _ID.fullmatch(directory.name) or not directory.is_dir():
            continue
        manifest = directory / "ellmos-module.v2.json"
        try:
            if not manifest.resolve().is_relative_to(domains_root) or not manifest.is_file():
                continue
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        module_id = raw.get("id")
        if (raw.get("schema") != "ellmos.module.v2" or raw.get("category") != "domains"
                or not isinstance(module_id, str) or not _ID.fullmatch(module_id)
                or module_id in seen_ids or raw.get("visibility") != "public"):
            continue
        seen_ids.add(module_id)
        name = raw.get("display_name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            name = module_id
        manifest_status = raw.get("status")
        if not isinstance(manifest_status, str) or manifest_status not in _STATUSES:
            manifest_status = "unknown"
        kind = raw.get("kind")
        if not isinstance(kind, str) or kind not in {"library", "service", "runtime", "ui"}:
            kind = "unknown"
        capabilities = raw.get("provides")
        if not isinstance(capabilities, list):
            capabilities = []
        capabilities = [item for item in capabilities if isinstance(item, str) and _ID.fullmatch(item)][:20]
        response["domains"].append({
            "id": module_id,
            "name": name,
            "category": "domains",
            "kind": kind,
            "manifest_status": manifest_status,
            "capabilities": capabilities,
            "evidence_type": "manifest_present",
            "installed": None,
            "running": None,
            "workbench_url": None,
        })
    response["total"] = len(response["domains"])
    return response
