"""Shared consumer contract. Route presence is never a worker readiness claim."""
from datetime import datetime, timezone

from hub._services.gui_contract_service import CAPABILITIES_SCHEMA

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
               "GET /api/settings/ui", "GET /api/task-capabilities")
# Reads of src/layouts/BachLayout.astro -> src/components/Header.astro:242,280 and src/lib/domain-pins.mjs:46 (domain menu): every
# page makes them. Only the pages checked so far list them; completeness for all pages is a task of the GUI manifest (#2087).
LAYOUT_READS = ["/api/gui/brand", "/api/gui/backend-origin", "/api/domains/pins"]
# Page -> endpoints the ellmos-system-gui page actually reads (pinned to the GUI51 page-reads manifest in tests):
# "/" src/pages/index.astro:227 (SystemClusterStatus is only included by settings.astro:4,253); "/agenten/sessions" src/lib/agent-history.mjs:77,89,92
# (loaded by src/pages/agenten/sessions.astro:90), inbox tab src/scripts/user-inbox-tab.mjs:28, TaskCreateForm.astro:118,183 and
# src/lib/task-assignment.mjs:127, session detail src/lib/agent-history.mjs:82, profiles src/scripts/agent-history.mjs:112;
# "/" also src/lib/task-summary.js:2; "/artefakte" src/pages/artefakte.astro:168,243,253; "/settings" src/pages/settings.astro:253
# (cluster-cockpit via the included component), 513 ocean-map, 562 theme, 615 backend-origin, 630 nemofold stats, 650 candidates,
# 752 external-artifacts.
PAGE_READS = {
    "/": ["/api/agent-studio/blueprints", "/api/tasks"],
    "/tasks": ["/api/tasks", "/api/task-assignees"],
    "/agenten/running": ["/api/system/core-agents", "/api/system/core-agents/timeline"],
    "/agenten/blueprints": ["/api/agent-studio/blueprints"],
    "/agenten/subscription-agents": ["/api/agent-studio/blueprints", "/api/capabilities/skills/library"],
    "/agenten/fabrika": ["/api/agent-studio/blueprints", "/api/capabilities/skills"],
    "/agenten/marblerun": ["/api/marblerun/catalog", "/api/marblerun/chains"],
    "/agenten/sessions": ["/api/agent-history/sessions", "/api/agent-history/tasks", "/api/memory/sessions",
                         "/api/agent-history/sessions/{snapshot_id}", "/api/agents"],
    # ellmos-system-gui reads the library inventory (capability-board-client.mjs INVENTORIES.skills), not /api/capabilities/skills.
    "/skills": ["/api/capabilities/skills/library"],
    # The assignment tab of /skills is optional and not a page of its own: it is declared through `endpoints` (GET/PUT /api/skills-board/hierarchy).
    "/skills/plugins": ["/api/capabilities/plugins/inventory"],
    "/skills/mcp": ["/api/capabilities/mcp/connections"],
    "/skills/software": ["/api/capabilities/software"],
    "/skills/ocean": ["/api/capabilities/ocean"],
    "/user-inbox": ["/api/user-inbox"],
    "/memory": ["/api/memory/search"],
    "/domains": ["/api/domains/installed"],
    "/artefakte": ["/api/artefakte"],
    "/governance": ["/api/governance/policy-registry", "/api/governance/locks"],
    "/governance/logs": ["/api/governance/audit"],
    "/governance/usecases": [], "/governance/funk": [],
    "/life": ["/api/calendar/events"], "/settings": ["/api/gui/backend-origin", "/api/setup/ocean-map", "/api/settings/theme", "/api/settings/ui",
                 "/api/learning/nemofold/stats", "/api/learning/nemofold/candidates", "/api/system/external-artifacts"],
}
# Required actions retain their HTTP method; compose is a preview POST, never a GET.
PAGE_ACTIONS = {
    "/agenten/subscription-agents": ["POST /api/agent-studio/subscription-agents/compose"],
}

# Optional reads (the page stays usable without them, so they never make it unavailable): layout reads and user-triggered or
# detail reads. These entries track the current GUI51 manifest for pages with optional reads; optional writes are cataloged as
# routes but do not make a page unavailable.
PAGE_OPTIONAL_READS = {
    "/": LAYOUT_READS,
    "/agenten/subscription-agents": ["/api/tasks", "/api/gui/capabilities"] + LAYOUT_READS,
    "/agenten/sessions": ["/api/user-inbox", "/api/assignees", "/api/task-assignees", "/api/tasks/{task_id}",
                           "/api/task-capabilities"] + LAYOUT_READS,
    "/tasks": ["/api/assignees", "/api/tasks/{task_id}/result", "/api/tasks/{task_id}/result/history",
                "/api/task-capabilities", "/api/tasks/{task_id}", "/api/tasks/{task_id}/worker-policy"] + LAYOUT_READS,
    "/artefakte": ["/api/artifacts/content", "/api/artifacts/download"] + LAYOUT_READS,
    "/settings": ["/api/system/worker-policy", "/api/system/cluster-cockpit", "/api/domains/pins", "/api/gui/brand"],
}


def declaration(routes, kit, brand, modules, *, public_paths=(), module_sources=()):
    observed = datetime.now(timezone.utc).isoformat()
    endpoints = []
    registered = set()
    for route in routes:
        path = getattr(route, "path", "")
        by_prefix = path.startswith(PREFIXES)
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if not by_prefix and f"{method} {path}" not in EXACT_READS:
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
        required = ["GET " + read for read in reads] + PAGE_ACTIONS.get(path, [])
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
