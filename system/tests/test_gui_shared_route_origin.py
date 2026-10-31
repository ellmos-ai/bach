"""BACH #2626: each path that shared GUI 0.2.29 ships a page for is served from the dist or is a registered, reasoned fallback."""
import os

import pytest

os.environ.setdefault("BACH_GUI_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")

import gui.server as server  # noqa: E402
from gui.api.gui_capabilities import LEGACY_PAGE_FALLBACKS, PAGE_READS  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

# Paths measured on 26 Oct 2026 as dist pages of 0.2.29 that BACH still answered from its own templates.
MEASURED = ["/routinen", "/ati", "/chat", "/denkarium", "/financial", "/gesundheit", "/help", "/inbox", "/kontakte",
            "/maintenance", "/persoenlich", "/steuer", "/tools"]


def marker(path):
    return f"<!-- shared-dist {path} -->".encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    for path in MEASURED:
        (tmp_path / (path.lstrip("/") + ".html")).write_bytes(marker(path))
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    monkeypatch.delenv("ELLMOS_SYSTEM_GUI_DIST", raising=False)
    return TestClient(server.app, base_url="http://testserver", raise_server_exceptions=False), tmp_path


@pytest.mark.parametrize("path", MEASURED)
def test_each_measured_path_has_a_proven_origin(client, path):
    http, _ = client
    response = http.get(path)
    assert response.status_code == 200
    if path in LEGACY_PAGE_FALLBACKS:
        assert LEGACY_PAGE_FALLBACKS[path].strip()
        assert marker(path) not in response.content
    else:
        assert path in PAGE_READS
        assert response.content == marker(path)


def test_routinen_falls_back_to_the_bach_template_without_a_shared_page(client):
    http, dist = client
    (dist / "routinen.html").unlink()
    response = http.get("/routinen")
    assert response.status_code == 200
    assert b"shared-dist" not in response.content


def test_inbox_keeps_the_foerderplaner_anonymisation_tab(client):
    http, _ = client
    response = http.get("/inbox")
    assert response.status_code == 200
    assert "Quarantäne / Anonymisierung".encode() in response.content
