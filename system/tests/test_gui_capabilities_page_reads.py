# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PAGE_READS names what ellmos-system-gui pages really read (checked against ellmos-system-gui origin/main, 2026-10-11).

Each pinned entry carries its GUI source line in gui_capabilities.py; this test holds the entries, proves that the BACH route
exists for every one of them and that the declaration prefixes cover them (otherwise the page would be reported unavailable
only because the route is not declared)."""
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import server  # noqa: E402
from gui.api import gui_capabilities as caps  # noqa: E402
from gui.api.agent_history import router as agent_history_router  # noqa: E402
from gui.api.unified_api import router as unified_router  # noqa: E402

PINNED = {
    "/": ["/api/system/cluster-cockpit", "/api/agent-studio/blueprints", "/api/tasks"],
    "/agenten/sessions": ["/api/agent-history/sessions", "/api/agent-history/tasks", "/api/memory/sessions",
                          "/api/agent-history/sessions/{snapshot_id}", "/api/agents"],
    "/artefakte": ["/api/artefakte", "/api/artifacts/content", "/api/artifacts/download"],
    "/settings": ["/api/gui/backend-origin", "/api/system/cluster-cockpit", "/api/setup/ocean-map", "/api/settings/theme",
                  "/api/learning/nemofold/stats", "/api/learning/nemofold/candidates", "/api/system/external-artifacts"],
}


def _get_routes():
    # The unified router is not mounted under `from gui import server` (circular import in the test process), so the three route
    # sources are read directly.
    found = set()
    for source in (server.app.routes, unified_router.routes, agent_history_router.routes):
        for route in source:
            if "GET" in (getattr(route, "methods", None) or ()):
                found.add(route.path)
    return found


def test_page_reads_hold_the_endpoints_the_gui_reads():
    for page, reads in PINNED.items():
        assert caps.PAGE_READS[page] == reads, page


def test_every_pinned_read_has_a_bach_route_and_a_declared_prefix():
    routes = _get_routes()
    for page, reads in PINNED.items():
        for read in reads:
            assert read in routes, f"{page}: no GET route {read}"
            assert read.startswith(caps.PREFIXES) or read in caps.EXACT_PATHS, f"{page}: {read} is not declared"


class _Route:
    def __init__(self, path, methods):
        self.path, self.methods = path, methods


def _cataloged(routes):
    out = caps.declaration(routes, {}, {}, {})
    return {f"{e['method']} {e['path']}" for e in out["endpoints"]}, out


def test_exact_paths_do_not_catalog_sibling_routes():
    routes = [_Route("/api/agents", {"GET"}), _Route("/api/agents/runtime", {"GET"}),
              _Route("/api/agents/{agent_id}/toggle", {"PUT"}),
              _Route("/api/system/external-artifacts", {"GET"}), _Route("/api/system/external-artifacts/import", {"POST"}),
              _Route("/api/learning/nemofold/candidates", {"GET"}),
              _Route("/api/learning/nemofold/candidates/{candidate_id}/approve", {"POST"})]
    cataloged, _ = _cataloged(routes)
    assert cataloged == {"GET /api/agents", "GET /api/system/external-artifacts", "GET /api/learning/nemofold/candidates"}


def test_new_page_reads_make_pages_configured_and_missing_route_makes_them_unavailable():
    routes = [_Route(read, {"GET"}) for reads in caps.PAGE_READS.values() for read in reads]
    _, out = _cataloged(routes)
    assert all(p["status"] == "configured" for p in out["pages"])
    _, out = _cataloged([r for r in routes if r.path != "/api/setup/ocean-map"])
    pages = {p["path"]: p for p in out["pages"]}
    assert pages["/settings"]["status"] == "unavailable"
    assert pages["/settings"]["missing"] == ["GET /api/setup/ocean-map"]
