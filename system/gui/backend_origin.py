"""Read-only, non-secret observation of the GUI's active BACH data source."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "ellmos-system-gui.backend-origin.v1"
DEFAULT_MANIFEST = Path.home() / ".bach" / "gui_backend_origin.json"
_LABEL = re.compile(r"^[\w .-]{1,40}$", re.UNICODE)


def observe_backend_origin(database: Path, api_database: Path,
                           manifest: Path = DEFAULT_MANIFEST) -> dict:
    """Report a mode only when declaration, machine, and live DB all agree.

    ``database`` is server.get_bach_db's Path; ``api_database`` is the Path
    used by unified_api._get_conn. Both must resolve to one existing file.
    This probe establishes connectivity and two expected tables, not task sync
    or database integrity. No private path, hostname, or hash enters the reply.
    """
    result = {
        "schema": SCHEMA,
        "mode": "unknown",
        "declared_mode": "unknown",
        "backend_kind": None,
        "instance_label": None,
        "connection_verified": False,
        "schema_verified": False,
        "instance_verified": False,
        "adapter_binding_verified": False,
        "has_claim_authority": False,
        "cache_active": False,
        "source": "not_verified",
        "reason_code": "manifest_unavailable_or_invalid",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        if manifest.stat().st_size > 4096:
            return result
        declaration = json.loads(manifest.read_text(encoding="utf-8"))
        declared = declaration.get("mode")
        label = declaration.get("instance_label")
        if (declaration.get("schema") != SCHEMA or declared not in {"server", "local"}
                or declaration.get("backend_kind") != "bach_sqlite"
                or not isinstance(label, str) or not _LABEL.fullmatch(label)):
            return result
        result["declared_mode"] = declared
        result["backend_kind"] = "bach_sqlite"
        node_hash = hashlib.sha256(platform.node().encode("utf-8")).hexdigest()
        result["instance_verified"] = declaration.get("expected_node_sha256") == node_hash
    except (OSError, ValueError, TypeError, AttributeError):
        return result

    try:
        resolved = database.resolve(strict=True)
        result["adapter_binding_verified"] = resolved == api_database.resolve(strict=True)
        if not result["adapter_binding_verified"]:
            result["reason_code"] = "adapter_binding_mismatch"
            return result
        uri = resolved.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            conn.execute("PRAGMA query_only = ON")
            result["connection_verified"] = conn.execute("SELECT 1").fetchone() == (1,)
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('tasks','bach_agents')"
            )}
            result["schema_verified"] = names == {"tasks", "bach_agents"}
    except (OSError, sqlite3.Error):
        result["reason_code"] = "database_unavailable"
        return result

    if (result["connection_verified"] and result["schema_verified"]
            and result["instance_verified"] and result["adapter_binding_verified"]):
        result["mode"] = declared
        result["instance_label"] = label
        result["source"] = "deployment_manifest_and_live_sqlite"
        result["reason_code"] = "verified"
        # GUX-003: Pure read status must not claim Lead TaskDB claim functionality without an active lease
        result["has_claim_authority"] = (declared == "server" and not declaration.get("read_only_observation", False))
        result["cache_active"] = bool(declaration.get("offline_cache_active", False))
    elif not result["schema_verified"]:
        result["reason_code"] = "schema_unavailable"
    else:
        result["reason_code"] = "instance_unverified"
    return result
