"""A configured shared release must serve its exact bytes at every pinned page."""

import hashlib
import json

import pytest
from starlette.testclient import TestClient

PAGES = (
    "/agenten/bibliothek",
    "/agenten/blueprints",
    "/agenten/fabrika",
    "/agenten/marblerun",
    "/agenten/running",
    "/agenten/sessions",
    "/agenten/subscription-agents",
    "/artefakte",
    "/ati",
    "/chat",
    "/daemon",
    "/denkarium",
    "/domains",
    "/financial",
    "/gesundheit",
    "/governance",
    "/governance/funk",
    "/governance/logs",
    "/governance/usecases",
    "/help",
    "/inbox",
    "/",
    "/kontakte",
    "/life",
    "/maintenance",
    "/memory",
    "/notizen",
    "/persoenlich",
    "/prompt-library",
    "/routinen",
    "/settings",
    "/skills",
    "/skills/mcp",
    "/skills/ocean",
    "/skills/plugins",
    "/skills/software",
    "/steuer",
    "/system/installation-updates",
    "/system/ocean",
    "/tasks",
    "/tools",
    "/user-inbox",
)


@pytest.fixture
def shared_release(tmp_path, monkeypatch):
    from gui import server
    from hub._services import gui_contract_service

    files = {}
    payloads = {}
    for page in PAGES:
        name = "index.html" if page == "/" else page.lstrip("/") + ".html"
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = f"<h1>Canonical release: {page}</h1>".encode()
        target.write_bytes(raw)
        payloads[page] = raw
        files[name] = hashlib.sha256(raw).hexdigest()
    reads = json.dumps(
        {"schema": "ellmos.gui.page-reads.v1", "pages": {p: [] for p in PAGES}}
    ).encode()
    (tmp_path / "page-reads.v1.json").write_bytes(reads)
    files["page-reads.v1.json"] = hashlib.sha256(reads).hexdigest()
    (tmp_path / "dist-manifest.json").write_text(
        json.dumps(
            {
                "schema": "ellmos-system-gui.dist.v1",
                "source_commit": "a" * 40,
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    monkeypatch.setenv("ELLMOS_SYSTEM_GUI_DIST", str(tmp_path))
    monkeypatch.setattr(
        gui_contract_service,
        "get_pinned_kit_manifest",
        lambda: {
            "verified": True,
            "pinned_source_commit": "a" * 40,
            "expected_page_count": len(PAGES),
        },
    )
    return server, payloads


@pytest.mark.parametrize("page", PAGES)
def test_every_page_serves_verified_release_without_redirect(shared_release, page):
    server, payloads = shared_release
    response = TestClient(server.app, base_url="http://testserver").get(
        page, follow_redirects=False
    )
    assert response.status_code == 200
    assert response.content == payloads[page]


@pytest.mark.parametrize("page", PAGES)
def test_missing_explicit_release_never_uses_legacy_page(
    shared_release, monkeypatch, tmp_path, page
):
    server, _ = shared_release
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path / "missing")
    response = TestClient(server.app, base_url="http://testserver").get(
        page, follow_redirects=False
    )
    assert response.status_code == 503
    assert response.json()["reason_code"] == "shared_gui_page_missing"


def test_static_shells_do_not_grant_private_api_access(shared_release):
    server, _ = shared_release
    client = TestClient(server.app, base_url="http://testserver")
    for path in (
        "/api/tasks",
        "/api/system/workers",
        "/api/denkarium",
        "/openapi.json",
    ):
        assert client.get(path).status_code == 401
    assert client.get("/not-a-page").status_code == 401
