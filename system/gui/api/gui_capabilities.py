"""Shared consumer contract. Route presence is never a worker readiness claim."""
from datetime import datetime, timezone

from hub._services.gui_contract_service import CAPABILITIES_SCHEMA
from hub._services.gui_page_reads import normalize, page_status, unavailable

PREFIXES = ("/api/user-inbox", "/api/tasks", "/api/task-assignees", "/api/agent-studio/", "/api/system/core-",
            "/api/system/workers", "/api/system/worker-policy", "/api/system/cluster-cockpit", "/api/system/fackel",
            "/api/marblerun/", "/api/capabilities", "/api/governance/", "/api/memory/",
            "/api/domains/", "/api/artifacts", "/api/artefakte", "/api/agent-history", "/api/calendar/", "/api/gui/",
            "/api/skills-board/hierarchy")
# Exact "METHOD /path" pairs for single reads whose path or parent path also holds routes that are not page reads (GET+PUT on
# /api/settings/theme, /api/agents/runtime, PUT /api/agents/{agent_id}/toggle, POST /api/system/external-artifacts/import):
# a prefix or a path-only comparison would catalog those as well.
EXACT_READS = ("GET /api/agents", "GET /api/assignees", "GET /api/settings/theme", "GET /api/setup/ocean-map",
               "GET /api/learning/nemofold/stats", "GET /api/learning/nemofold/candidates", "GET /api/system/external-artifacts",
               "GET /api/task-capabilities")

def declaration(routes, kit, brand, modules, *, public_paths=(), module_sources=(), page_reads=None):
    observed = datetime.now(timezone.utc).isoformat()
    info = page_reads if isinstance(page_reads, dict) else unavailable()
    if kit.get("verified") is not True:
        info = unavailable("gui_kit_not_verified")
    declared = {method + " " + normalize(path) for item in info.get("declared", [])
                for method, _, path in [item.partition(" ")]}
    endpoints = []
    registered = set()
    for route in routes:
        path = getattr(route, "path", "")
        by_prefix = path.startswith(PREFIXES)
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            registered.add(f"{method} {path}")
            if (not by_prefix and f"{method} {path}" not in EXACT_READS
                    and f"{method} {normalize(path)}" not in declared):
                continue
            endpoints.append({"method": method, "path": path,
                "kind": "read" if method == "GET" else "write" if method in {"PUT", "PATCH", "DELETE"} else "action",
                "available": True, "runtime_verified": False, "verification_scope": "adapter",
                "provider": {"id": "bach", "version": None},
                "auth": "none" if method == "GET" and path in public_paths else "device-token",
                "reason": "route_registered_runtime_not_probed"})
    pages = page_status(info, registered)
    return {"schema": CAPABILITIES_SCHEMA, "schema_version": 1,
        "system": {"id": "bach", "adapter_version": "1"},
        "observed_at": observed, "kit": kit, "brand": brand, "modules": modules,
        "gui": {"status": "verified" if kit.get("verified") else "unverified",
                "source_commit": kit.get("revision"), "archive_sha256": kit.get("archive_sha256"),
                "page_reads": {key: info.get(key) for key in
                               ("state", "schema", "reason_code", "sha256")}},
        "pages": pages, "endpoints": endpoints, "module_sources": list(module_sources),
        "missing_adapters": [key for key, item in modules.items() if not item.get("adapter_registered")]}
