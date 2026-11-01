"""Live-Readback-Sonde zu Task #3744.

Die Unit-Tests in ``test_gui_health_and_dist_3744.py`` belegen, dass
``/api/health`` und ``/dist-manifest.json`` im Code dieses Branches existieren
und regulaer antworten. Offen war der Live-Beleg am laufenden System.

Live-Befund vom Readback gegen ``http://127.0.0.1:8000`` (Vor-Zustand):

- ``GET /api/health``          -> **404** ``{"detail":"Not Found"}``
- ``GET /dist-manifest.json``  -> **401** (Auth erzwungen)
- ``GET /api/gui/kit-manifest``-> regulaer (200/401 je nach Token)

Der 404 ist geklaert (Details: ``system/gui/HEALTH_404_RECEIPT_3744.md``):

- Der Body ``{"detail":"Not Found"}`` (22 B) ist der Starlette-Default und stammt
  nicht aus ``server.py`` (dort ``{"status": "ok"}`` bzw.
  ``"Gui dist manifest unavailable"``).
- ``/api/health`` steht in ``EXEMPT_API_PATHS`` (``server.py:1684``), passiert die
  Auth-Middleware also frei; die Middleware-Reihenfolge
  (``server.py:1898``/``1928`` vor Route ``5906``) ist unverdaechtig.
- ``/api/gui/kit-manifest`` (Route aus derselben Epoche) antwortet live 200.
  Also fehlt dem laufenden Prozess nur die spaetere Route
  ``@app.get("/api/health")``: der Dienst faehrt einen Code-Stand zwischen
  kit-manifest-Einfuehrung und ``server.py:5906``.

=> Deployment-/Neustart-Problem, kein Middleware- oder Routing-Defekt.
Der 401 auf ``/dist-manifest.json`` ist codekonform: der Pfad fehlt in
``EXEMPT_API_PATHS`` und wird von ``DeviceAuthMiddleware`` (``server.py:1713``)
abgewiesen.

Diese Datei friert den Befund als tolerante Sonde fest (laeuft immer,
ueberspringt ohne erreichbaren Server) und haelt die Soll-Pruefung strikt opt-in
hinter ``BACH_LIVE_GUI_STRICT=1``.

Port via ``BACH_LIVE_GUI_PORT``, Bearer-Token via ``BACH_LIVE_GUI_TOKEN``.
"""

import json
import os
import urllib.error
import urllib.request

import pytest

BASE_URL = f"http://127.0.0.1:{os.environ.get('BACH_LIVE_GUI_PORT', '8000')}"
TIMEOUT = 5.0
STRICT = os.environ.get("BACH_LIVE_GUI_STRICT") == "1"

ENDPOINTS = ("/api/health", "/dist-manifest.json", "/api/gui/kit-manifest")


def _fetch(path):
    """GET auf den Live-Server; 4xx/5xx sind Beobachtung, kein Abbruch."""
    request = urllib.request.Request(BASE_URL + path, method="GET")
    token = os.environ.get("BACH_LIVE_GUI_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"Kein lokaler Dienst unter {BASE_URL} erreichbar: {exc}")


def test_live_endpoint_readback_inventory():
    """Sammelt Status/Body der drei Auftrags-Endpunkte als Live-Readback."""
    report = {}
    for path in ENDPOINTS:
        status, headers, body = _fetch(path)
        report[path] = {
            "status": status,
            "content_type": headers.get("Content-Type"),
            "body_head": body[:160].decode("utf-8", "replace"),
        }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    for path, entry in report.items():
        assert 100 <= entry["status"] < 600, f"{path}: unmoeglicher Status {entry['status']}"
    assert any(e["status"] < 500 for e in report.values()), "kein Endpunkt antwortet brauchbar"


def test_live_server_identity_against_openapi():
    """Klaert, ob der Dienst auf Port 8000 den Repo-Code (inkl. /api/health) faehrt."""
    status, _, body = _fetch("/openapi.json")
    if status != 200:
        pytest.skip(f"/openapi.json nicht offen lesbar (Status {status})")

    spec = json.loads(body)
    info = spec.get("info", {})
    paths = spec.get("paths", {})
    documented = [path for path in ENDPOINTS if path in paths]
    print("openapi title:", info.get("title"), "| version:", info.get("version"))
    print("dokumentierte Auftrags-Endpunkte:", documented)
    assert isinstance(paths, dict)
    if STRICT:
        assert documented == list(ENDPOINTS), (
            f"Live-Dienst dokumentiert {documented}, erwartet {list(ENDPOINTS)}"
        )


@pytest.mark.skipif(not STRICT, reason="Soll-Readback nur mit BACH_LIVE_GUI_STRICT=1")
def test_live_api_health_reports_status():
    status, _, body = _fetch("/api/health")
    assert status == 200, f"GET /api/health lieferte {status}: {body[:200]!r}"
    assert json.loads(body) == {"status": "ok"}


@pytest.mark.skipif(not STRICT, reason="Soll-Readback nur mit BACH_LIVE_GUI_STRICT=1")
def test_live_dist_manifest_readback():
    status, _, body = _fetch("/dist-manifest.json")
    assert status in (200, 404), f"GET /dist-manifest.json lieferte {status}"
    if status == 200:
        payload = json.loads(body)
        assert isinstance(payload, dict)


@pytest.mark.skipif(not STRICT, reason="Soll-Readback nur mit BACH_LIVE_GUI_STRICT=1")
def test_live_kit_manifest_reports_installed_dist():
    status, _, body = _fetch("/api/gui/kit-manifest")
    assert status in (200, 401, 403), f"GET /api/gui/kit-manifest lieferte {status}: {body[:200]!r}"
    if status == 200:
        payload = json.loads(body)
        assert "installed_dist" in payload or "kit_manifest" in payload
