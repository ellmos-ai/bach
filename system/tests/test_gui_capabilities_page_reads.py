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
    "/": ["/api/system/cluster-cockpit", "/api/agent-studio/blueprints"],
    "/agenten/sessions": ["/api/agent-history/sessions", "/api/agent-history/tasks", "/api/memory/sessions"],
    "/artefakte": ["/api/artefakte", "/api/artifacts/content", "/api/artifacts/download"],
    "/settings": ["/api/gui/backend-origin"],
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
            assert read.startswith(caps.PREFIXES), f"{page}: {read} is not covered by PREFIXES"
