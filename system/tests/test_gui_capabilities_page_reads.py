# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Existing GUI consumer checks use an explicit isolated manifest fixture, never production hand tables."""
import json
import re
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import server  # noqa: E402
from gui.api import gui_capabilities as caps  # noqa: E402
from gui.api.agent_history import router as agent_history_router  # noqa: E402
from gui.api.task_assignment import router as task_assignment_router
from gui.api.unified_api import router as unified_router
from gui.api.user_inbox import build_router as build_user_inbox_router  # noqa: E402
from gui.api.worker_policy import router as worker_policy_router  # noqa: E402
from hub._services.gui_page_reads import parse

# Frozen excerpt of ellmos-system-gui public/page-reads.v1.json at GUI51 commit 77d42f93c85eb66d1e74361535c13f6e18e4e288:
# (method, path, required).
MANIFEST_SOURCE = "ellmos-system-gui 77d42f93c85eb66d1e74361535c13f6e18e4e288 public/page-reads.v1.json"
MANIFEST_LAYOUT = [
    ("GET", "/api/gui/brand", False), ("GET", "/api/gui/backend-origin", False), ("GET", "/api/domains/pins", False),
    ("POST", "/api/domains/{id}/pin", False),
]
MANIFEST_PAGES = {
    "/": [("GET", "/api/agent-studio/blueprints", True), ("GET", "/api/tasks", True)],
    "/tasks": [
        ("GET", "/api/tasks", True), ("GET", "/api/task-assignees", True),
        ("GET", "/api/assignees", False), ("GET", "/api/tasks/{id}/result", False),
        ("GET", "/api/tasks/{id}/result/history", False), ("GET", "/api/task-capabilities", False),
        ("GET", "/api/tasks/{id}", False), ("GET", "/api/tasks/{id}/worker-policy", False),
        # GUI51 reads the same task detail from both the detail panel and task-creation form.
        ("GET", "/api/tasks/{id}", False),
    ],
    "/agenten/sessions": [
        ("GET", "/api/agent-history/sessions", True), ("GET", "/api/agent-history/sessions/{snapshot_id}", True),
        ("GET", "/api/agent-history/tasks", True), ("GET", "/api/memory/sessions", True), ("GET", "/api/agents", True),
        ("GET", "/api/user-inbox", False), ("PATCH", "/api/user-inbox/{id}", False), ("GET", "/api/task-assignees", False),
        ("GET", "/api/assignees", False), ("POST", "/api/tasks", False), ("GET", "/api/tasks/{id}", False),
        ("GET", "/api/task-capabilities", False),
    ],
    "/artefakte": [("GET", "/api/artefakte", True), ("GET", "/api/artifacts/content", False),
                   ("GET", "/api/artifacts/download", False)],
    "/settings": [
        ("GET", "/api/gui/backend-origin", True), ("GET", "/api/system/worker-policy", False),
        ("PUT", "/api/system/worker-policy", False), ("GET", "/api/system/cluster-cockpit", False),
        ("GET", "/api/setup/ocean-map", True), ("GET", "/api/settings/theme", True), ("GET", "/api/settings/ui", True),
        ("GET", "/api/learning/nemofold/stats", True), ("GET", "/api/learning/nemofold/candidates", True),
        ("GET", "/api/system/external-artifacts", True), ("PUT", "/api/settings/theme", False),
        ("PUT", "/api/settings/ui", False),
        ("POST", "/api/learning/nemofold/candidates/{id}/approve", False),
        ("POST", "/api/learning/nemofold/candidates/{id}/reject", False),
        ("POST", "/api/learning/nemofold/synthesize", False), ("POST", "/api/system/external-artifacts/import", False),
    ],
}


def _n(path):
    return re.sub(r"\{[^}]*\}", "{}", path)


def _derived(page):
    """(required GET paths, optional GET paths) of a page: its own entries plus the layout ones; a read that is required on the
    page is not repeated as optional."""
    own = MANIFEST_PAGES[page]
    required = list(dict.fromkeys(p for m, p, r in own if m == "GET" and r))
    optional = list(dict.fromkeys(p for m, p, r in own if m == "GET" and not r))
    optional += [p for m, p, r in MANIFEST_LAYOUT if m == "GET" and p not in required and p not in optional]
    return required, optional


PINNED = {page: _derived(page)[0] for page in MANIFEST_PAGES}
PINNED_OPTIONAL = {page: _derived(page)[1] for page in MANIFEST_PAGES}


def _get_routes():
    # The unified router is not mounted under `from gui import server` (circular import in the test process), so the route
    # sources (the user-inbox router is built without a store) are read directly.
    # Worker-policy endpoints are also read from their owning router: broad-suite app setup can vary mount state/order.
    found = set()
    for source in (server.app.routes, unified_router.routes, agent_history_router.routes,
                   task_assignment_router.routes, worker_policy_router.routes,
                   build_user_inbox_router(lambda: None).routes):
        for route in source:
            if "GET" in (getattr(route, "methods", None) or ()):
                found.add(route.path)
    return found


def _get_route_methods():
    sources = (server.app.routes, unified_router.routes, agent_history_router.routes,
               task_assignment_router.routes, worker_policy_router.routes,
               build_user_inbox_router(lambda: None).routes)
    return {(method, route.path) for source in sources for route in source
            for method in (getattr(route, "methods", None) or ())}


def test_pinned_pages_equal_the_gui_manifest_required_and_optional_reads():
    _, out = _cataloged([])
    projected = {item["path"]: item for item in out["pages"]}
    for page in MANIFEST_PAGES:
        required, optional = _derived(page)
        actual = projected[page]
        assert sorted(map(_n, actual["requires"])) == sorted(_n("GET " + p) for p in required), (page, "required", MANIFEST_SOURCE)
        assert sorted(map(_n, actual["optional_unserved"])) == sorted(_n("GET " + p) for p in optional), (page, "optional", MANIFEST_SOURCE)


def test_optional_reads_never_decide_the_page_status():
    required_all = [r for page in MANIFEST_PAGES for r in PINNED[page]]
    routes = [_Route(read, {"GET"}) for read in required_all]  # every optional route missing
    _, out = _cataloged(routes)
    pages = {p["path"]: p for p in out["pages"]}
    for page in MANIFEST_PAGES:
        assert pages[page]["status"] == "configured", page
        assert not set(PINNED_OPTIONAL[page]) & {r.removeprefix("GET ") for r in pages[page]["requires"]}, page


def test_every_pinned_read_has_a_bach_route_and_a_declared_prefix():
    routes = _get_routes()
    normalized = {_n(route) for route in routes}
    cataloged, _ = _cataloged([_Route(route, {"GET"}) for route in routes])
    declared = {_n(item) for item in cataloged}
    for page, reads in [(p, PINNED[p] + PINNED_OPTIONAL[p]) for p in PINNED]:
        for read in reads:
            assert _n(read) in normalized, f"{page}: no GET route {read}"
            assert _n(f"GET {read}") in declared, f"{page}: {read} is not declared"


def test_worker_policy_reads_and_writes_are_optional_but_cataloged():
    settings = {"GET /api/system/worker-policy", "PUT /api/system/worker-policy"}
    task = {"GET /api/tasks/{task_id}/worker-policy", "PUT /api/tasks/{task_id}/worker-policy"}
    actual = _get_route_methods()
    assert {tuple(item.split(" ", 1)) for item in settings | task} <= actual
    routes = [_Route("/api/system/worker-policy", {"GET", "PUT"}),
              _Route("/api/tasks/{task_id}/worker-policy", {"GET", "PUT"})]
    cataloged, out = _cataloged(routes)
    assert settings | task <= cataloged
    pages = {p["path"]: p for p in out["pages"]}
    assert "GET /api/system/worker-policy" not in pages["/settings"]["requires"]
    assert "GET /api/tasks/{task_id}/worker-policy" not in pages["/tasks"]["requires"]
    assert "/api/system/worker-policy" in PINNED_OPTIONAL["/settings"]
    assert _n("/api/tasks/{task_id}/worker-policy") in {_n(read) for read in PINNED_OPTIONAL["/tasks"]}


def test_ui_settings_get_and_put_are_both_cataloged_and_registered():
    ui_routes = {"GET /api/settings/ui", "PUT /api/settings/ui"}
    actual = _get_route_methods()
    assert {tuple(item.split(" ", 1)) for item in ui_routes} <= actual
    routes = [_Route("/api/settings/ui", {"GET", "PUT"})]
    cataloged, out = _cataloged(routes)
    assert ui_routes <= cataloged
    endpoints = {f"{e['method']} {e['path']}": e for e in out["endpoints"]}
    assert endpoints["GET /api/settings/ui"]["kind"] == "read"
    assert endpoints["PUT /api/settings/ui"]["kind"] == "write"


class _Route:
    def __init__(self, path, methods):
        self.path, self.methods = path, methods


def _cataloged(routes):
    document = {"schema": "ellmos.gui.page-reads.v1",
                "layout": [{"method": m, "path": p, "required": r} for m, p, r in MANIFEST_LAYOUT],
                "pages": {page: [{"method": m, "path": p, "required": r} for m, p, r in entries]
                          for page, entries in MANIFEST_PAGES.items()}}
    out = caps.declaration(routes, {"verified": True}, {}, {},
                           page_reads=parse(json.dumps(document).encode()))
    return {f"{e['method']} {e['path']}" for e in out["endpoints"]}, out


def test_exact_paths_do_not_catalog_sibling_routes():
    routes = [_Route("/api/agents", {"GET"}), _Route("/api/agents/runtime", {"GET"}),
              _Route("/api/settings/theme", {"GET", "PUT"}), _Route("/api/assignees", {"GET", "POST"}),
              _Route("/api/agents/{agent_id}/toggle", {"PUT"}),
              _Route("/api/system/external-artifacts", {"GET"}), _Route("/api/system/external-artifacts/import", {"POST"}),
              _Route("/api/learning/nemofold/candidates", {"GET"}),
              _Route("/api/learning/nemofold/candidates/{candidate_id}/approve", {"POST"})]
    cataloged, _ = _cataloged(routes)
    # A registered write explicitly named by the manifest is cataloged; unrelated siblings remain excluded
    assert cataloged == {"GET /api/agents", "GET /api/system/external-artifacts", "GET /api/learning/nemofold/candidates",
                         "GET /api/settings/theme", "PUT /api/settings/theme", "GET /api/assignees",
                         "POST /api/system/external-artifacts/import",
                         "POST /api/learning/nemofold/candidates/{candidate_id}/approve"}


def test_new_page_reads_make_pages_configured_and_missing_route_makes_them_unavailable():
    routes = [_Route(read, {"GET"}) for reads in PINNED.values() for read in reads]
    _, out = _cataloged(routes)
    assert all(p["status"] == "configured" for p in out["pages"])
    _, out = _cataloged([r for r in routes if r.path != "/api/setup/ocean-map"])
    pages = {p["path"]: p for p in out["pages"]}
    assert pages["/settings"]["status"] == "unavailable"
    assert pages["/settings"]["missing"] == ["GET /api/setup/ocean-map"]
