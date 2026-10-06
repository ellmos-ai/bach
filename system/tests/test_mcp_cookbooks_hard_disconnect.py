"""Acceptance tests for MCP Cookbooks Blaetteransicht and Hard-Disconnect (Task #1691 / GUX-030-066)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from hub._services import mcp_cookbook_service
from hub._services.mcp_cookbook_service import (
    COOKBOOK_SCHEMA,
    DISCONNECT_RECEIPT_SCHEMA,
    get_mcp_cookbook_by_id,
    get_mcp_cookbooks,
    perform_hard_disconnect,
)
from starlette.testclient import TestClient

from system.gui.api.unified_api import router as unified_router


@pytest.fixture
def api_client():
    app = FastAPI()
    app.include_router(unified_router)
    return TestClient(app)


def test_mcp_cookbook_catalog_structure():
    """Verify that catalog schema, 4-page pagination, and all 8 MCP servers are present."""
    catalog = get_mcp_cookbooks()
    assert catalog["schema"] == COOKBOOK_SCHEMA
    assert catalog["total_count"] == 8
    assert len(catalog["cookbooks"]) == 8

    expected_servers = {
        "open-compute",
        "filecommander",
        "controlcenter",
        "codecommander",
        "homebase",
        "servercommander",
        "markitdown",
        "n8n-manager",
    }
    found_servers = {b["id"] for b in catalog["cookbooks"]}
    assert expected_servers == found_servers

    for book in catalog["cookbooks"]:
        assert book["total_pages"] == 4
        # Backwards-compat top-level arrays
        assert isinstance(book["ingredients"], list)
        assert len(book["ingredients"]) > 0
        assert isinstance(book["recipes"], list)
        assert len(book["recipes"]) > 0

        # Rich 4-page structure
        pages = book["pages"]
        assert "page_1_cover" in pages
        assert "page_2_tools" in pages
        assert "page_3_recipes" in pages
        assert "page_4_governance" in pages

        # Page 1 checks
        p1 = pages["page_1_cover"]
        assert p1.get("command") or p1.get("server_command")
        assert p1["protocol_version"] == "2024-11-05"
        assert p1["runtime_status"] in {"cli_detected", "active", "idle", "standby"}

        # Page 2 checks
        p2 = pages["page_2_tools"]
        assert len(p2["tools"]) > 0
        for tool in p2["tools"]:
            assert "name" in tool
            assert tool["mode"] in {"safe", "full"}

        # Page 3 checks
        p3 = pages["page_3_recipes"]
        assert len(p3["recipes"]) > 0
        for rec in p3["recipes"]:
            assert "title" in rec
            assert "prompt" in rec

        # Page 4 checks
        p4 = pages["page_4_governance"]
        sec_level = p4.get("governance_level") or p4.get("security_level")
        assert sec_level
        patterns = p4.get("blocked_path_patterns") or p4.get("blocked_patterns")
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        assert p4.get("mode_note") or p4.get("mode_restrictions") or p4.get("safety_note")


def test_mcp_cookbook_single_lookup():
    """Verify single cookbook lookup and 404 behavior."""
    book = get_mcp_cookbook_by_id("filecommander")
    assert book is not None
    assert book["id"] == "filecommander"
    assert "FileCommander" in book["title"]

    missing = get_mcp_cookbook_by_id("non-existent-mcp-server-xyz")
    assert missing is None


def test_mcp_cookbook_api_endpoints(api_client):
    """Test unified API endpoints for MCP cookbooks."""
    # List endpoint
    res_list = api_client.get("/api/capabilities/mcp/cookbooks")
    assert res_list.status_code == 200
    data = res_list.json()
    assert data["schema"] == COOKBOOK_SCHEMA
    assert len(data["cookbooks"]) == 8

    # Detail endpoint
    res_detail = api_client.get("/api/capabilities/mcp/cookbooks/filecommander")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["id"] == "filecommander"
    assert detail["total_pages"] == 4

    # 404 for unknown
    res_unknown = api_client.get("/api/capabilities/mcp/cookbooks/unknown-agent-foo")
    assert res_unknown.status_code == 404
    assert "detail" in res_unknown.json() or "error" in res_unknown.json()


def test_mcp_disconnect_status_probe(api_client):
    """Test status probe for MCP server process count."""
    res = api_client.get("/api/capabilities/mcp/disconnect/status?server_id=filecommander")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["server_id"] == "filecommander"
    assert "active_processes_count" in status_data
    assert "is_clean" in status_data
    assert status_data["schema"] == DISCONNECT_RECEIPT_SCHEMA

    # Missing server_id
    res_missing = api_client.get("/api/capabilities/mcp/disconnect/status")
    assert res_missing.status_code in {400, 422}


def test_mcp_hard_disconnect_execution(api_client, monkeypatch):
    """Test authoritative hard disconnect returning HardDisconnectReceipt."""
    # Avoid foreign process kills during test runs
    monkeypatch.setattr(
        mcp_cookbook_service,
        "find_server_processes",
        lambda s: [],
    )
    res = api_client.post(
        "/api/capabilities/mcp/disconnect",
        json={"server_id": "filecommander", "force": True},
    )
    assert res.status_code == 200
    receipt = res.json()

    assert receipt["schema"] == DISCONNECT_RECEIPT_SCHEMA
    assert receipt["server_id"] == "filecommander"
    assert receipt["active_processes_remaining"] == 0
    assert receipt["verified_clean"] is True
    assert "processes_terminated" in receipt

    # Bad server_id
    res_bad = api_client.post(
        "/api/capabilities/mcp/disconnect",
        json={"server_id": "invalid-mcp-server-id"},
    )
    assert res_bad.status_code == 400


def test_mcp_hard_disconnect_service_unit(monkeypatch):
    """Direct test of McpCookbookService hard disconnect when no processes running."""
    monkeypatch.setattr(
        mcp_cookbook_service,
        "find_server_processes",
        lambda s: [],
    )
    receipt = perform_hard_disconnect(server_id="open-compute", force=True, operator="test-runner")
    assert receipt["server_id"] == "open-compute"
    assert receipt["schema"] == DISCONNECT_RECEIPT_SCHEMA
    assert receipt["active_processes_remaining"] == 0
    assert receipt["verified_clean"] is True
    assert receipt["status"] == "disconnected_clean"


def test_mcp_hard_disconnect_with_simulated_process_kill(monkeypatch):
    """Test process scan, termination loop, and clean receipt generation."""
    calls = []

    class MockProcess:
        def __init__(self, pid):
            self.pid = pid
            self._running = True

        def terminate(self):
            calls.append(("terminate", self.pid))
            self._running = False

        def kill(self):
            calls.append(("kill", self.pid))
            self._running = False

        def is_running(self):
            return self._running

    import psutil
    monkeypatch.setattr(psutil, "Process", MockProcess)

    # 1st call returns 1 matching process, 2nd call (post-termination check) returns 0
    scan_results = [
        [{"pid": 99999, "name": "filecommander", "cmdline": "mcp-filecommander"}],
        [],
    ]

    monkeypatch.setattr(
        mcp_cookbook_service,
        "find_server_processes",
        lambda s: scan_results.pop(0) if scan_results else [],
    )

    receipt = perform_hard_disconnect(server_id="filecommander", force=True, operator="test-operator")
    assert receipt["server_id"] == "filecommander"
    assert receipt["schema"] == DISCONNECT_RECEIPT_SCHEMA
    assert receipt["active_processes_remaining"] == 0
    assert receipt["verified_clean"] is True
    assert receipt["processes_terminated"] == [99999]
    assert ("terminate", 99999) in calls


def test_skills_astro_contract():
    """Verify that skills.astro contains the full 4-page Fachbuch UI, navigation, and hard disconnect controls."""
    astro_path = Path(__file__).resolve().parent.parent / "gui" / "web" / "src" / "pages" / "skills.astro"
    assert astro_path.exists(), f"Missing skills.astro at {astro_path}"

    content = astro_path.read_text(encoding="utf-8")

    # Blätteransicht Navigation & Indicators
    assert "btn-mcp-prev" in content
    assert "btn-mcp-next" in content
    assert "mcp-page-num" in content
    assert "mcp-page-total" in content
    assert "Seite <span id=\"mcp-page-num\"" in content

    # 4 Chapter tabs
    assert 'data-page="1"' in content
    assert 'data-page="2"' in content
    assert 'data-page="3"' in content
    assert 'data-page="4"' in content
    assert "1. Deckel" in content
    assert "2. Zutaten" in content
    assert "3. Rezepte" in content
    assert "4. Absicherung" in content

    # 4 Pages containers
    assert 'id="mcp-page-1"' in content
    assert 'id="mcp-page-2"' in content
    assert 'id="mcp-page-3"' in content
    assert 'id="mcp-page-4"' in content

    # Hard-Disconnect controls
    assert 'id="btn-hard-disconnect"' in content
    assert 'id="chk-hard-disconnect-force"' in content
    assert 'id="mcp-disconnect-receipt-box"' in content
    assert 'id="receipt-details"' in content
    assert "HardDisconnectReceipt" in content

    # JavaScript functions
    assert "function setMcpPage(pageNum)" in content
    assert "function turnMcpPage(delta)" in content
    assert "async function openMcpCookbook(bookId)" in content
    assert "async function triggerHardDisconnect()" in content
    assert "async function checkMcpProcessStatus(serverId)" in content
