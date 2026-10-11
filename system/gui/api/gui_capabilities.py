"""Shared consumer contract. Route presence is never a worker readiness claim."""
from datetime import datetime, timezone

from hub._services.gui_contract_service import CAPABILITIES_SCHEMA

PREFIXES = ("/api/user-inbox", "/api/tasks", "/api/task-assignees", "/api/agent-studio/", "/api/system/core-",
            "/api/system/workers", "/api/system/cluster-cockpit", "/api/system/fackel",
            "/api/marblerun/", "/api/capabilities", "/api/governance/", "/api/memory/",
            "/api/domains/", "/api/artifacts", "/api/artefakte", "/api/agent-history", "/api/calendar/", "/api/gui/")
# Exact paths for single GET reads whose parent path also holds routes that are not page reads (for example /api/agents/runtime,
# PUT /api/agents/{agent_id}/toggle, POST /api/system/external-artifacts/import): a prefix would catalog those as well.
EXACT_PATHS = ("/api/agents", "/api/settings/theme", "/api/setup/ocean-map", "/api/learning/nemofold/stats",
               "/api/learning/nemofold/candidates", "/api/system/external-artifacts")
# Page -> endpoints the ellmos-system-gui page actually reads (checked against ellmos-system-gui origin/main, 2026-10-11):
# "/" src/components/SystemClusterStatus.astro:34 and src/pages/index.astro:227; "/agenten/sessions" src/lib/agent-history.mjs:77,89,92
# (loaded by src/pages/agenten/sessions.astro:90), session detail src/lib/agent-history.mjs:82, profiles src/scripts/agent-history.mjs:112;
# "/" also src/lib/task-summary.js:2; "/artefakte" src/pages/artefakte.astro:168,243,253; "/settings" src/pages/settings.astro:253
# (cluster-cockpit via the included component), 513 ocean-map, 562 theme, 615 backend-origin, 630 nemofold stats, 650 candidates,
# 752 external-artifacts.
PAGE_READS = {
    "/": ["/api/system/cluster-cockpit", "/api/agent-studio/blueprints", "/api/tasks"],
    "/tasks": ["/api/tasks", "/api/task-assignees"],
    "/agenten/running": ["/api/system/core-agents", "/api/system/core-agents/timeline"],
    "/agenten/blueprints": ["/api/agent-studio/blueprints"],
    "/agenten/fabrika": ["/api/agent-studio/blueprints", "/api/capabilities/skills"],
    "/agenten/marblerun": ["/api/marblerun/catalog", "/api/marblerun/chains"],
    "/agenten/sessions": ["/api/agent-history/sessions", "/api/agent-history/tasks", "/api/memory/sessions",
                         "/api/agent-history/sessions/{snapshot_id}", "/api/agents"],
    "/skills": ["/api/capabilities/skills"],
    "/skills/plugins": ["/api/capabilities/plugins/inventory"],
    "/skills/mcp": ["/api/capabilities/mcp/connections"],
    "/skills/software": ["/api/capabilities/software"],
    "/skills/ocean": ["/api/capabilities/ocean"],
    "/user-inbox": ["/api/user-inbox"],
    "/memory": ["/api/memory/search"],
    "/domains": ["/api/domains/installed"],
    "/artefakte": ["/api/artefakte", "/api/artifacts/content", "/api/artifacts/download"],
    "/governance": ["/api/governance/policy-registry", "/api/governance/locks"],
    "/governance/logs": ["/api/governance/audit"],
    "/governance/usecases": [], "/governance/funk": [],
    "/life": ["/api/calendar/events"], "/settings": ["/api/gui/backend-origin", "/api/system/cluster-cockpit", "/api/setup/ocean-map", "/api/settings/theme",
                 "/api/learning/nemofold/stats", "/api/learning/nemofold/candidates", "/api/system/external-artifacts"],
}


def declaration(routes, kit, brand, modules, *, public_paths=(), module_sources=()):
    observed = datetime.now(timezone.utc).isoformat()
    endpoints = []
    registered = set()
    for route in routes:
        path = getattr(route, "path", "")
        if not (path.startswith(PREFIXES) or path in EXACT_PATHS):
            continue
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            registered.add(f"{method} {path}")
            endpoints.append({"method": method, "path": path,
                "kind": "read" if method == "GET" else "write" if method in {"PUT", "PATCH", "DELETE"} else "action",
                "available": True, "runtime_verified": False, "verification_scope": "adapter",
                "provider": {"id": "bach", "version": None},
                "auth": "none" if method == "GET" and path in public_paths else "device-token",
                "reason": "route_registered_runtime_not_probed"})
    pages = []
    for path, reads in PAGE_READS.items():
        required = ["GET " + read for read in reads]
        missing = [read for read in required if read not in registered]
        pages.append({"id": path.strip("/").replace("/", ".") or "home", "path": path,
            "status": "unavailable" if missing else "configured",
            "requires": required, "missing": missing,
            "todo": ["Runtime und Bedienung am aktiven Provider prüfen"]})
    return {"schema": CAPABILITIES_SCHEMA, "schema_version": 1,
        "system": {"id": "bach", "adapter_version": "1"},
        "observed_at": observed, "kit": kit, "brand": brand, "modules": modules,
        "gui": {"status": "verified" if kit.get("verified") else "unverified",
                "source_commit": kit.get("revision"), "archive_sha256": kit.get("archive_sha256")},
        "pages": pages, "endpoints": endpoints, "module_sources": list(module_sources),
        "missing_adapters": [key for key, item in modules.items() if not item.get("adapter_registered")]}
