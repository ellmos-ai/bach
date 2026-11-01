"""Readback-Wiederholung am Livesystem für Task #3720: GUI-Dist-Pin 0.2.30/eb0251ac4b85.

Dieses unittest-Modul (pytest-kompatibel, ausschließlich stdlib, keine Repo-Imports)
prüft gegen den laufenden Live-Server unter http://127.0.0.1:8000 (Mac-Deploy-Port 8000):

* /api/health antwortet mit Status 200 (Bestätigung des Mac-Deploys auf Port 8000).
* /api/gui/kit-manifest pinnt top-level die GUI-Version 0.2.30 auf den Quell-Commit
  eb0251ac4b85574087ad934611d19dc3df1f9c4c, Archiv
  ellmos-system-gui-0.2.30-eb0251ac4b85.zip (SHA-256 ff07b556…), mit 39 erwarteten
  .html-Seiten.
* installed_dist im Kit-Manifest meldet verified=True mit page_count==39 – das ist
  die Readback-Wiederholung des operatorseitigen Reinstalls der gepinnten Dist.
* /dist-manifest.json liefert 39 .html-Seiten.

Falls /dist-manifest.json am Livesystem nicht geroutet ist oder hinter der DeviceAuth
liegt, tritt als dokumentierter Ersatznachweis das Feld installed_dist aus
/api/gui/kit-manifest an seine Stelle; Test d warnt dann per warnings.warn, statt zu
scheitern. Solange der Operator-Reinstall aussteht, fallen die Tests c und d bewusst
rot aus – das ist der ehrliche Live-Befund, kein Testfehler.
"""

import http.cookiejar
import json
import unittest
import urllib.error
import urllib.request
import warnings

BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = 5
PINNED_SOURCE_COMMIT = "eb0251ac4b85574087ad934611d19dc3df1f9c4c"
PINNED_VERSION = "0.2.30"
EXPECTED_PAGE_COUNT = 39
KIT_SCHEMA = "ellmos-system-gui.kit-manifest.v1"
DIST_SCHEMA = "ellmos-system-gui.dist.v1"
ARCHIVE = "ellmos-system-gui-0.2.30-eb0251ac4b85.zip"
ARCHIVE_SHA = "ff07b55656349da60cb18b5ead867da3f03d43d81e6964bc6448212d7412b188"


class LiveReadbackError(AssertionError):
    """Live-Server nicht erreichbar – Readback nicht prüfbar."""


def _get(path, opener=None):
    """GET gegen den Live-Server; liefert (Statuscode, Body als Bytes)."""
    url = BASE_URL + path
    try:
        if opener is None:
            response = urllib.request.urlopen(url, timeout=TIMEOUT)
        else:
            response = opener.open(url, timeout=TIMEOUT)
    except urllib.error.HTTPError as error:
        # Ein HTTP-Fehlerstatus ist ein reguläres Ergebnis des Readbacks.
        return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LiveReadbackError(
            f"Live-Server 127.0.0.1:8000 nicht erreichbar – Readback nicht prüfbar "
            f"(GET {path}: {error!r})"
        ) from error
    return response.getcode(), response.read()


def _get_json(path, opener=None):
    """GET gegen den Live-Server; liefert (Statuscode, JSON-Objekt als dict)."""
    status, body = _get(path, opener=opener)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise AssertionError(
            f"Antwort von {path} (Status {status}) ist kein JSON: {error!r}; "
            f"Body-Anfang: {body[:200]!r}"
        ) from error
    if not isinstance(payload, dict):
        raise AssertionError(
            f"Antwort von {path} (Status {status}) ist kein JSON-Objekt; "
            f"Body-Anfang: {body[:200]!r}"
        )
    return status, payload


class GuiLiveReadbackTestCase(unittest.TestCase):
    """Readback-Wiederholung am Livesystem 127.0.0.1:8000 (Mac-Deploy-Port 8000)."""

    maxDiff = None

    def _assert_installed_dist_verified(self, installed):
        """Prüft installed_dist: installiert, verified, 39 .html-Seiten, Pin-Commit."""
        detail = f"installed_dist={json.dumps(installed, sort_keys=True, ensure_ascii=False)}"
        self.assertIsInstance(installed, dict, f"installed_dist ist kein Objekt; {detail}")
        self.assertTrue(
            installed.get("installed"),
            f"GUI-Dist ist laut Live-Befund nicht installiert; {detail}",
        )
        self.assertTrue(
            installed.get("verified"),
            f"GUI-Dist ist laut Live-Befund nicht verified; {detail}",
        )
        self.assertEqual(
            installed.get("page_count"),
            EXPECTED_PAGE_COUNT,
            f"installed_dist.page_count ist {installed.get('page_count')!r} "
            f"statt {EXPECTED_PAGE_COUNT}; {detail}",
        )
        self.assertEqual(
            installed.get("source_commit"),
            PINNED_SOURCE_COMMIT,
            f"installed_dist.source_commit ist {installed.get('source_commit')!r} "
            f"statt Pin {PINNED_SOURCE_COMMIT}; {detail}",
        )

    def _assert_dist_manifest_body(self, body):
        """Prüft den Body von /dist-manifest.json: Schema, Pin, 39 .html-Dateien."""
        try:
            manifest = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            self.fail(f"/dist-manifest.json ist kein JSON: {error!r}; Body-Anfang: {body[:200]!r}")
        self.assertIsInstance(
            manifest,
            dict,
            f"/dist-manifest.json ist kein JSON-Objekt; Body-Anfang: {body[:200]!r}",
        )
        self.assertEqual(
            manifest.get("schema"),
            DIST_SCHEMA,
            f"schema ist {manifest.get('schema')!r} statt {DIST_SCHEMA}; "
            f"Manifest={json.dumps(manifest, sort_keys=True, ensure_ascii=False)}",
        )
        self.assertEqual(
            manifest.get("source_commit"),
            PINNED_SOURCE_COMMIT,
            f"source_commit ist {manifest.get('source_commit')!r} statt Pin "
            f"{PINNED_SOURCE_COMMIT}; "
            f"Manifest={json.dumps(manifest, sort_keys=True, ensure_ascii=False)}",
        )
        files_map = manifest.get("files")
        self.assertIsInstance(
            files_map,
            dict,
            f"/dist-manifest.json ohne files-Objekt; "
            f"Manifest={json.dumps(manifest, sort_keys=True, ensure_ascii=False)}",
        )
        html_pages = [name for name in files_map if name.endswith(".html")]
        self.assertEqual(
            len(html_pages),
            EXPECTED_PAGE_COUNT,
            f"/dist-manifest.json liefert {len(html_pages)} .html-Seiten statt "
            f"{EXPECTED_PAGE_COUNT}; Dateien: {sorted(files_map)}",
        )

    def test_health_ok_mac_deploy_port_8000(self):
        """Test a: /api/health am Mac-Deploy-Port 8000 antwortet mit 200."""
        status, body = _get("/api/health")
        self.assertEqual(
            status,
            200,
            f"/api/health antwortet am Mac-Deploy-Port 8000 mit Status {status} statt 200; "
            f"Body-Anfang: {body[:200]!r}",
        )

    def test_kit_manifest_pin_is_0_2_30_eb0251ac(self):
        """Test b: Kit-Manifest pinnt top-level auf 0.2.30/eb0251ac4b85, 39 Seiten."""
        status, payload = _get_json("/api/gui/kit-manifest")
        detail = f"kit-manifest={json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
        self.assertEqual(
            status,
            200,
            f"/api/gui/kit-manifest antwortet mit Status {status} statt 200; {detail}",
        )
        self.assertEqual(
            payload.get("schema"),
            KIT_SCHEMA,
            f"schema weicht von {KIT_SCHEMA} ab; {detail}",
        )
        self.assertEqual(
            payload.get("pinned_source_commit"),
            PINNED_SOURCE_COMMIT,
            f"pinned_source_commit weicht vom Pin {PINNED_SOURCE_COMMIT} ab; {detail}",
        )
        self.assertEqual(
            payload.get("version"),
            PINNED_VERSION,
            f"version weicht von {PINNED_VERSION} ab; {detail}",
        )
        self.assertEqual(
            payload.get("expected_page_count"),
            EXPECTED_PAGE_COUNT,
            f"expected_page_count weicht von {EXPECTED_PAGE_COUNT} ab; {detail}",
        )
        self.assertEqual(
            payload.get("release_archive"),
            ARCHIVE,
            f"release_archive weicht von {ARCHIVE} ab; {detail}",
        )
        self.assertEqual(
            payload.get("release_archive_sha256"),
            ARCHIVE_SHA,
            f"release_archive_sha256 weicht von {ARCHIVE_SHA} ab; {detail}",
        )

    def test_installed_dist_verified_with_39_html_pages(self):
        """Test c: installed_dist meldet verified=True mit page_count==39."""
        status, payload = _get_json("/api/gui/kit-manifest")
        detail = f"kit-manifest={json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
        self.assertEqual(
            status,
            200,
            f"/api/gui/kit-manifest antwortet mit Status {status} statt 200; {detail}",
        )
        self.assertIn(
            "installed_dist",
            payload,
            f"kit-manifest enthält kein Feld installed_dist; {detail}",
        )
        self._assert_installed_dist_verified(payload.get("installed_dist"))

    def test_dist_manifest_serves_39_html_pages(self):
        """Test d: /dist-manifest.json mit 39 .html-Seiten; sonst Ersatznachweis."""
        status, body = _get("/dist-manifest.json")
        if status == 200:
            self._assert_dist_manifest_body(body)
            return
        if status != 401:
            self.fail(
                f"/dist-manifest.json antwortet ohne Cookie mit unerwartetem Status {status} "
                f"statt 200 oder 401; Body-Anfang: {body[:200]!r}"
            )

        # DeviceAuth-Gate: Cookie-Bootstrap über die öffentliche Loopback-Startseite.
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        bootstrap_status, _ = _get("/", opener=opener)
        retry_status, retry_body = _get("/dist-manifest.json", opener=opener)

        if retry_status == 200:
            self._assert_dist_manifest_body(retry_body)
            return

        if retry_status == 401:
            befund = "DeviceAuth-geschützt"
        elif retry_status == 404:
            befund = "nicht geroutet"
        else:
            self.fail(
                f"/dist-manifest.json antwortet trotz Cookie-Bootstrap mit unerwartetem "
                f"Status {retry_status} (Bootstrap-Status {bootstrap_status}); "
                f"Body-Anfang: {retry_body[:200]!r}"
            )

        # Dokumentierter Ersatznachweis: installed_dist aus dem Kit-Manifest.
        try:
            kit_status, kit_payload = _get_json("/api/gui/kit-manifest", opener=opener)
            self.assertEqual(
                kit_status,
                200,
                f"Ersatznachweis /api/gui/kit-manifest antwortet mit Status {kit_status} "
                f"statt 200; "
                f"kit-manifest={json.dumps(kit_payload, sort_keys=True, ensure_ascii=False)}",
            )
            self._assert_installed_dist_verified(kit_payload.get("installed_dist"))
        except AssertionError as error:
            self.fail(
                f"/dist-manifest.json ist {befund} (Status {retry_status} trotz "
                f"Cookie-Bootstrap, Bootstrap-Status {bootstrap_status}); Ersatznachweis "
                f"kit-manifest installed_dist ebenfalls rot: {error}"
            )

        warnings.warn(
            f"/dist-manifest.json ist {befund} (Status {retry_status} trotz Cookie-Bootstrap); "
            f"Ersatznachweis kit-manifest installed_dist ist grün: "
            f"Pin {PINNED_VERSION}/{PINNED_SOURCE_COMMIT[:12]} verified mit "
            f"{EXPECTED_PAGE_COUNT} .html-Seiten."
        )


if __name__ == "__main__":
    unittest.main()