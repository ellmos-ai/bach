"""Shared consumer contract. Route presence is never a worker readiness claim."""
from datetime import datetime, timezone

from hub._services.gui_contract_service import CAPABILITIES_SCHEMA

PREFIXES = ("/api/tasks", "/api/task-assignees", "/api/agent-studio/", "/api/system/core-",
            "/api/system/workers", "/api/system/cluster-cockpit", "/api/system/fackel",
            "/api/marblerun/", "/api/capabilities", "/api/governance/", "/api/memory/",
            "/api/domains/", "/api/artifacts", "/api/calendar/", "/api/gui/")
PAGE_READS = {
    "/": ["/api/system/cluster-cockpit"],
    "/tasks": ["/api/tasks", "/api/task-assignees"],
    "/agenten/running": ["/api/system/core-agents", "/api/system/core-agents/timeline"],
    "/agenten/blueprints": ["/api/agent-studio/blueprints"],
    "/agenten/fabrika": ["/api/agent-studio/blueprints", "/api/capabilities/skills"],
    "/agenten/marblerun": ["/api/marblerun/catalog", "/api/marblerun/chains"],
    "/agenten/sessions": ["/api/system/core-agents/timeline"],
    "/skills": ["/api/capabilities/skills"],
    "/skills/plugins": ["/api/capabilities/plugins/inventory"],
    "/skills/mcp": ["/api/capabilities/mcp/connections"],
    "/skills/software": ["/api/capabilities/software"],
    "/memory": ["/api/memory/search"],
    "/domains": ["/api/domains/installed"],
    "/artefakte": ["/api/artifacts"],
    "/governance": ["/api/governance/policy-registry", "/api/governance/locks"],
    "/governance/logs": ["/api/governance/audit"],
    "/governance/usecases": [], "/governance/funk": [],
    "/life": ["/api/calendar/events"], "/settings": ["/api/gui/brand"],
}


def declaration(routes, kit, brand, modules, *, public_paths=(), module_sources=()):
    observed = datetime.now(timezone.utc).isoformat()
    endpoints = []
    registered = set()
    for route in routes:
        path = getattr(route, "path", "")
        if not path.startswith(PREFIXES):
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
