# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-2 (#3986): the route snapshot the GUI repo checks its fetch calls against."""
from tools.export_gui_route_snapshot import build_snapshot


def test_snapshot_lists_the_chat_routes_the_gui_uses_and_not_the_invented_one():
    routes = set(build_snapshot()["routes"])
    for needed in ("POST /api/chat-control/chat", "GET /api/chat-control/history",
                   "GET /api/agent-history/sessions", "GET /api/agent-history/sessions/{}",
                   "POST /api/agent-history/sessions/{}/resume"):
        assert needed in routes, needed
    assert "POST /api/chat/send" not in routes


def test_proxy_route_is_expanded_to_its_whitelisted_paths_only():
    routes = set(build_snapshot()["routes"])
    assert "GET /api/chat-control/status" in routes
    assert "POST /api/chat-control/not-whitelisted" not in routes
    assert not {"GET /api/chat-control/{}", "POST /api/chat-control/{}"} & routes
