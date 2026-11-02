# -*- coding: utf-8 -*-
# Kalibrierung 2026-11-01 (Task #3718): EXPECTED_DIST_FILE_COUNT=375,
# Legacy-12-Routen (routes_plan.count=38), Deploy-Abweichung dokumentiert (Rest via #3720).
# Beleg: PR #623 (gui_readback_3718 final kalibriert, Unittest 4/4 OK).
"""Real-Server-Readback der GUI fuer BACH-Task #3718 (Meilenstein 3.15.0).

Sammelt Belege vom real laufenden BACH-GUI-Server auf http://127.0.0.1:8000
(39 HTML-Routen inkl. Tab-Aliase + Legacy-Fallbacks + GUI-API-Vertraege) und
schreibt das Ergebnis IMMER in gui_readback_3718_result.json — auch wenn
einzelne Tests scheitern oder der Server nicht erreichbar ist (Je-Eintrag-
Schreiben via add_result plus Finalisierung in tearDownClass).

Regeln (Uebergabe #3718):
- unittest-Aufruf: python -m unittest -v gui_readback_3718 (cwd=Worktree-Root)
- Nur stdlib (urllib), kein requests-Dep, Timeout 10s je Request, KEIN
  Serverstart im Skript — der Server muss bereits auf Port 8000 laufen.
- Hard-Assertions NUR auf /api/gui/kit-manifest:
    pinned_source_commit == eb0251ac4b85574087ad934611d19dc3df1f9c4c
    installed_dist.page_count == 375 (Distdateien inkl. Distmanifest, MILESTONE.md:24;
    nur falls installed_dist present; 39 gilt nur fuer dist-manifest html_files)
- /api/gui/capabilities: schema/pages/version nur dokumentierend (soft).
- /dist-manifest.json: 404 ist ERWARTET und soft ("not served over HTTP");
  200 => parse, Hard-Asserts (source_commit, 39 .html) + serverseitige
  Routenliste fuer den HTML-Readback; 404 => Routenplan via PAGE_READS-Import
  (gui.api.gui_capabilities) mit HARDCODED-Fallback.
- Verbindungsfehler => unittest ERROR + Result-Datei mit Ist-Beleg
  "Server nicht erreichbar"; kein Weiterinterpretieren.
"""
import hashlib
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("BACH_READBACK_BASE", "http://127.0.0.1:8000")
WORKTREE = os.path.dirname(os.path.abspath(__file__))
WORKTREE_SYSTEM = os.path.join(WORKTREE, "system")
RESULT_PATH = os.path.join(WORKTREE, "gui_readback_3718_result.json")

PINNED_SOURCE_COMMIT = "eb0251ac4b85574087ad934611d19dc3df1f9c4c"
EXPECTED_PAGE_COUNT = 39  # nur dist-manifest .html-Anzahl (MILESTONE.md:24)
EXPECTED_DIST_FILE_COUNT = 375  # installed_dist.page_count = Distdateien inkl. Distmanifest (MILESTONE.md:24)
EXPECTED_GUI_VERSION = "0.2.30"  # nur dokumentierend im Kopf der Result-Datei

DEFAULT_LEGACY_FALLBACKS = [
    "/ati", "/chat", "/denkarium", "/financial", "/gesundheit", "/help",
    "/kontakte", "/maintenance", "/persoenlich", "/steuer", "/tools", "/inbox",
]
DEFAULT_TAB_ALIASES = ["/system?tab=ocean", "/daemon?tab=chains"]

ENTRIES = []                                  # Result-Entries (chronologisch)
KIT_SUMMARY = {}                              # Ist-Werte von /api/gui/kit-manifest
ROUTE_LIST = []                               # [(route, kind)] fuer HTML-Readback
LEGACY_LIST = list(DEFAULT_LEGACY_FALLBACKS)  # Legacy-Fallback-Pfade
ROUTES_PLAN = {"source": None, "reason": None, "count": 0, "html_200": 0,
               "routes_compact": ""}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def compute_verdict():
    """OK erfordert positive Installationsbelege und vollständige HTML-GETs."""
    reasons = []
    if KIT_SUMMARY.get("http_status") != 200:
        reasons.append("kit-manifest ohne HTTP 200")
    if KIT_SUMMARY.get("schema") != "ellmos-system-gui.kit-manifest.v1":
        reasons.append("kit-manifest mit unbekanntem Schema")
    pin = KIT_SUMMARY.get("pinned_source_commit")
    if pin != PINNED_SOURCE_COMMIT:
        reasons.append("kit-manifest pinned_source_commit != Pin (Ist=%r)" % pin)
    inst = KIT_SUMMARY.get("installed_dist")
    if not isinstance(inst, dict):
        reasons.append("installed_dist nicht als Objekt belegt")
    else:
        if inst.get("installed") is not True:
            reasons.append("installed_dist.installed ist nicht true")
        if inst.get("verified") is not True:
            reasons.append("installed_dist.verified ist nicht true")
        if inst.get("source_commit") != PINNED_SOURCE_COMMIT:
            reasons.append("installed_dist.source_commit entspricht nicht dem Pin")
        if inst.get("page_count") != EXPECTED_DIST_FILE_COUNT:
            reasons.append("installed_dist.page_count != %d Distdateien (Ist=%r)"
                           % (EXPECTED_DIST_FILE_COUNT, inst.get("page_count")))
        if inst.get("reason_code") == "commit_mismatch":
            reasons.append("installed_dist meldet commit_mismatch")

    planned = {route for route, kind in ROUTE_LIST
               if kind in ("page", "page_root", "tab_alias")}
    if len(planned) != EXPECTED_PAGE_COUNT:
        reasons.append("Routenplan belegt %d statt %d eindeutige HTML-Routen"
                       % (len(planned), EXPECTED_PAGE_COUNT))
    html = [e for e in ENTRIES if e["kind"] in ("page", "page_root", "tab_alias")]
    if not html:
        reasons.append("keine HTML-Routen-GETs belegt")
    else:
        observed = {e["route"] for e in html}
        missing = planned - observed
        if missing:
            reasons.append("HTML-GETs fehlen für: %s" % ",".join(sorted(missing)))
        bad = [e for e in html if e["status"] != 200]
        if bad:
            reasons.append("%d/%d HTML-Routen ohne Status 200: %s"
                           % (len(bad), len(html),
                              ",".join("%s:%s" % (e["route"], e["status"]) for e in bad)[:400]))
    return ("NOT-OK" if reasons else "OK"), reasons


def write_result_file():
    """Schreibt die Result-Datei (immer, auch bei Failures/Errors)."""
    verdict, reasons = compute_verdict()
    kinds, statuses = {}, {}
    for e in ENTRIES:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        statuses[str(e["status"])] = statuses.get(str(e["status"]), 0) + 1
    payload = {
        "base": BASE,
        "generated_at": _now(),
        "task": "3718",
        "milestone": "3.15.0",
        "expected_gui_pin": {"gui_version": EXPECTED_GUI_VERSION,
                             "source_commit": PINNED_SOURCE_COMMIT,
                             "page_count": EXPECTED_PAGE_COUNT},
        "kit_summary": KIT_SUMMARY,
        "routes_plan": ROUTES_PLAN,
        "summary": {"entries": len(ENTRIES), "kinds": kinds, "statuses": statuses},
        "verdict": verdict,
        "verdict_reasons": reasons,
        # Entries als kompakte JSON-Zeilen (eine Zeile je Eintrag):
        "entries": [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in ENTRIES],
    }
    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("Result-Datei nicht schreibbar (%s): %s\n" % (RESULT_PATH, exc))
    return payload


def add_result(kind, route, status, content=None, note="", error=None):
    entry = {
        "kind": kind,
        "route": route,
        "status": status,
        "sha256": hashlib.sha256(content).hexdigest() if content is not None else None,
        "bytes": len(content) if content is not None else None,
        "note": note,
        "error": error,
        "ts": _now(),
    }
    ENTRIES.append(entry)
    write_result_file()
    return entry


def fetch(route, timeout=10):
    """GET via urllib; gibt (status, body_bytes|None, err|None) zurueck."""
    url = route if route.startswith(("http://", "https://")) else BASE.rstrip("/") + route
    req = urllib.request.Request(url, headers={"User-Agent": "bach-gui-readback-3718/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read(), None
    except urllib.error.HTTPError as exc:
        return exc.code, None, "HTTPError %s" % exc.code
    except Exception as exc:  # URLError/ConnectionRefusedError/Timeout
        return None, None, "%s: %s" % (type(exc).__name__, exc)


def route_for_page(name):
    """Routen-Mapping (Testkontrakt): index.html -> '/', sonst '/'+name ohne
    '.html'; Sonder-Tabs: system/ocean.html -> '/system?tab=ocean',
    daemon.html -> '/daemon?tab=chains'."""
    n = str(name).strip()
    if n.endswith(".html"):
        n = n[: -len(".html")]
    n = n.strip("/")
    if n in ("", "index"):
        return "/", "page_root"
    if n == "system/ocean":
        return "/system?tab=ocean", "tab_alias"
    if n == "daemon":
        return "/daemon?tab=chains", "tab_alias"
    return "/" + n, "page"


def pages_from_page_reads(obj):
    """PAGE_READS robust auswerten (dict-Keys oder Liste str/dict)."""
    pages = []
    if isinstance(obj, dict):
        pages.extend(k for k in obj.keys())
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            if isinstance(item, str):
                pages.append(item)
            elif isinstance(item, dict):
                for key in ("name", "page", "id", "key", "file", "path"):
                    val = item.get(key)
                    if isinstance(val, str):
                        pages.append(val)
                        break
    return pages


def normalize_legacy_path(p):
    s = str(p).strip()
    if not s or s.startswith(("http://", "https://")):
        return None
    s = s.split("?", 1)[0].split("#", 1)[0]
    if not s.startswith("/"):
        s = "/" + s
    if len(s) > 1:
        s = s.rstrip("/")
    return s


def raise_unreachable(status, err, route):
    if status is None:
        add_result("env", route, None,
                   note="Server nicht erreichbar unter %s — Ist-Beleg Verbindungsfehler, keine Weiterinterpretation" % BASE,
                   error=err)
        write_result_file()
        raise RuntimeError("Server nicht erreichbar unter %s (%s)" % (BASE, err))


class GuiReadback3718(unittest.TestCase):
    """Real-Server-Readback auf http://127.0.0.1:8000 (Task #3718)."""

    # (a) /api/gui/capabilities — dokumentierend, kein 39-Assert:
    def test_01_api_gui_capabilities_soft(self):
        status, body, err = fetch("/api/gui/capabilities")
        raise_unreachable(status, err, "/api/gui/capabilities")
        data = None
        note = ""
        if status == 200 and body:
            try:
                data = json.loads(body.decode("utf-8", "replace"))
            except ValueError as exc:
                note = "JSON-Parse-Fehler: %s" % exc
        if data is not None:
            pages_field = data.get("pages", data.get("page_reads", data.get("pages_list")))
            note = ("schema=%r version=%r pages_type=%s pages_count=%s top_keys=%s"
                    % (data.get("schema"),
                       data.get("version", data.get("gui_version")),
                       type(pages_field).__name__,
                       (len(pages_field) if hasattr(pages_field, "__len__") else None),
                       ",".join(sorted(map(str, data.keys()))[:20])))
            decl = data.get("declaration")
            if isinstance(decl, dict):
                note += " declaration=%s" % ",".join(
                    "%s=%r" % (k, decl.get(k)) for k in sorted(map(str, decl.keys()))[:8])
        elif status == 401:
            note = "401 (eigentlich GET-exempt) — dokumentiert, Soft"
        add_result("api", "/api/gui/capabilities", status, body, note=note, error=err)

    # (b) /api/gui/kit-manifest — EINZIGE Hard-Asserts (Pin + page_count):
    def test_02_api_gui_kit_manifest_hard_pin(self):
        status, body, err = fetch("/api/gui/kit-manifest")
        raise_unreachable(status, err, "/api/gui/kit-manifest")
        if status != 200 or not body:
            add_result("api", "/api/gui/kit-manifest", status, body,
                       note="kit-manifest nicht 200 — Hard-Beleg fehlt", error=err)
            write_result_file()
            self.fail("GET /api/gui/kit-manifest liefert Status %r ohne Body (err=%r)" % (status, err))
            return
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except ValueError as exc:
            add_result("api", "/api/gui/kit-manifest", status, body,
                       note="JSON-Parse-Fehler: %s" % exc, error=str(exc))
            write_result_file()
            self.fail("kit-manifest unparsebar: %s" % exc)
            return
        pinned = data.get("pinned_source_commit")
        installed = data.get("installed_dist")
        inst_summary = None
        if isinstance(installed, dict):
            inst_summary = {k: installed.get(k) for k in
                            ("installed", "verified", "reason_code", "page_count", "source_commit")}
        KIT_SUMMARY.update({"http_status": status, "schema": data.get("schema"),
                            "pinned_source_commit": pinned,
                            "installed_dist": inst_summary})
        add_result("api", "/api/gui/kit-manifest", status, body,
                   note="pinned_source_commit=%r installed_dist=%s"
                        % (pinned, json.dumps(inst_summary, ensure_ascii=False, sort_keys=True)
                           if inst_summary is not None
                           else json.dumps(installed, default=str, ensure_ascii=False)[:300]))
        self.assertEqual(pinned, PINNED_SOURCE_COMMIT,
                         "kit-manifest pinned_source_commit %r != Pin %r" % (pinned, PINNED_SOURCE_COMMIT))
        if isinstance(installed, dict):
            self.assertEqual(installed.get("page_count"), EXPECTED_DIST_FILE_COUNT,
                             "installed_dist.page_count %r != 375 Distdateien" % installed.get("page_count"))
        else:
            # Design-Vorgabe: page_count nur hard-asserten, wenn present; sonst
            # dokumentieren (compute_verdict markiert das als NOT-OK-Baustein).
            add_result("api", "/api/gui/kit-manifest.page_count", status, body,
                       note="installed_dist nicht present — page_count dokumentiert statt hard-assert; Ist: %r" % installed)

    # (c) /dist-manifest.json — 404 ist erwartet-soft; 200 => serverseitige
    #     Routenliste (verbindlich) fuer den HTML-Readback:
    def test_03_dist_manifest_and_route_plan(self):
        status, body, err = fetch("/dist-manifest.json")
        raise_unreachable(status, err, "/dist-manifest.json")
        if status == 404:
            add_result("dist_manifest", "/dist-manifest.json", 404,
                       note="not served over HTTP — ERWARTET (Soft-Eintrag, kein Hard-Fail); "
                            "Routenplan daher aus PAGE_READS-Import/Fallback")
            self._routes_from_fallback("dist-manifest 404 (not served over HTTP)")
            return
        if status == 200 and body:
            try:
                data = json.loads(body.decode("utf-8", "replace"))
            except ValueError as exc:
                add_result("dist_manifest", "/dist-manifest.json", 200, body,
                           note="JSON-Parse-Fehler: %s" % exc, error=str(exc))
                self._routes_from_fallback("dist-manifest unparsebar")
                return
            src_commit = data.get("source_commit")
            files = data.get("files")
            if isinstance(files, dict):
                files_keys = list(files.keys())
            elif isinstance(files, list):
                files_keys = [x for x in files]
            else:
                files_keys = []
            html_files = sorted(k for k in files_keys
                                if isinstance(k, str) and k.endswith(".html"))
            add_result("dist_manifest", "/dist-manifest.json", 200, body,
                       note="source_commit=%r; files=%d; html_files=%d"
                            % (src_commit, len(files_keys), len(html_files)))
            self.assertEqual(src_commit, PINNED_SOURCE_COMMIT,
                             "dist-manifest source_commit %r != Pin %r" % (src_commit, PINNED_SOURCE_COMMIT))
            self.assertEqual(len(html_files), EXPECTED_PAGE_COUNT,
                             "dist-manifest html-Anzahl %d != 39" % len(html_files))
            routes, seen = [], set()
            for name in html_files:
                route, kind = route_for_page(name)
                if route not in seen:
                    routes.append((route, kind))
                    seen.add(route)
            ROUTE_LIST[:] = routes
            ROUTES_PLAN.update({"source": "dist-manifest.json (serverseitig)",
                                "reason": "dist-manifest 200", "count": len(routes),
                                "routes_compact": ",".join(r for r, _ in routes)})
            add_result("routes_plan", "(plan)", None,
                       note="Routenplan aus dist-manifest: %d Routen (source_commit=%r)" % (len(routes), src_commit))
            return
        add_result("dist_manifest", "/dist-manifest.json", status, body,
                   note="unerwarteter Status %r (Soft, kein Hard-Fail); autoritative 39er-Liste ohne Auth nicht lesbar" % status, error=err)
        self._routes_from_fallback("dist-manifest Status=%r" % status)

    def _routes_from_fallback(self, reason):
        legacy = list(DEFAULT_LEGACY_FALLBACKS)
        pages, page_source = [], "kein Import"
        try:
            if WORKTREE_SYSTEM not in sys.path:
                sys.path.insert(0, WORKTREE_SYSTEM)
            from gui.api.gui_capabilities import PAGE_READS, LEGACY_PAGE_FALLBACKS  # noqa: F401
            pages = pages_from_page_reads(PAGE_READS)
            page_source = "gui.api.gui_capabilities.PAGE_READS"
            mod_legacy = []
            if isinstance(LEGACY_PAGE_FALLBACKS, (list, tuple)):
                for item in LEGACY_PAGE_FALLBACKS:
                    if isinstance(item, str):
                        mod_legacy.append(item)
                    elif isinstance(item, dict):
                        val = item.get("path", item.get("route", item.get("name")))
                        if isinstance(val, str):
                            mod_legacy.append(val)
            elif isinstance(LEGACY_PAGE_FALLBACKS, dict):
                mod_legacy = [k for k in LEGACY_PAGE_FALLBACKS.keys() if isinstance(k, str)]
            norm = [normalize_legacy_path(p) for p in mod_legacy]
            norm = [p for p in norm if p]
            if norm:
                legacy = norm
            add_result("routes_plan", "(plan)", None,
                       note="PAGE_READS importiert (%s): %d Keys; LEGACY_PAGE_FALLBACKS: %d Pfade; "
                            "Fallback-Grund: %s" % (page_source, len(pages), len(legacy), reason))
        except Exception as exc:
            add_result("routes_plan", "(plan)", None,
                       note="PAGE_READS-Import fehlgeschlagen (%s) — HARDCODED-Fallback: 24 PAGE_READS "
                            "serverseitig verbindlich; Routen nur '/' + 2 Tab-Aliase + %d Legacy-Pfade (%s)"
                            % (exc, len(legacy), reason),
                       error="import failed: %s" % exc)
        routes, seen = [], set()
        for name in pages:
            route, kind = route_for_page(name)
            if route not in seen:
                routes.append((route, kind))
                seen.add(route)
        for tp in ("/",) + tuple(DEFAULT_TAB_ALIASES):
            if tp not in seen:
                routes.append((tp, "page_root" if tp == "/" else "tab_alias"))
                seen.add(tp)
        for p in legacy:
            if p not in seen:
                routes.append((p, "page"))
                seen.add(p)
        ROUTE_LIST[:] = routes
        LEGACY_LIST[:] = legacy
        source = "%s + Legacy %d; Grund: %s" % (page_source, len(legacy), reason)
        reason = "%s; Ziel 39 lt. MILESTONE; ohne Auth pruefbar %d; Differenz dokumentiert" % (reason, len(routes))
        ROUTES_PLAN.update({"source": source, "reason": reason, "count": len(routes),
                            "routes_compact": ",".join(r for r, _ in routes)})
        add_result("routes_plan", "(plan)", None,
                   note="Routenplan final: %d Routen via %s" % (len(routes), source))

    # (d) HTML-Readback je Route + dokumentierte Legacy-Pfade (e: 401 toleriert):
    def test_04_html_routes_readback(self):
        if not ROUTE_LIST:
            add_result("routes", "(keine)", None,
                       note="Keine Routenliste — vorherige Tests scheiterten; kein HTML-Readback moeglich")
            write_result_file()
            self.skipTest("Keine Routenliste (Server unerreichbar oder Route-Plan ungueltig)")
        seen, ok200 = set(), 0
        for route, kind in ROUTE_LIST:
            if route in seen:
                continue
            seen.add(route)
            status, body, err = fetch(route)
            note = ""
            if status is None:
                note = "Verbindungsfehler (Server offline?)"
            elif status == 401:
                note = "401 (Auth) — toleriert und dokumentiert"
            elif status == 404:
                note = "404 (Route nicht ausgeliefert — dokumentiert)"
            add_result(kind, route, status, body, note=note, error=err)
            if status == 200 and kind in ("page", "page_root", "tab_alias"):
                ok200 += 1
        ROUTES_PLAN.update({"count": len(seen), "html_200": ok200,
                            "routes_compact": ",".join(sorted(seen))})
        for lp in LEGACY_LIST:
            if lp in seen:
                continue
            seen.add(lp)
            status, body, err = fetch(lp)
            note = "Legacy-Fallback (Status 200 erwartet; Content darf vom Dist-Bytes abweichen)"
            if status is None:
                note = "Legacy: Verbindungsfehler"
            elif status == 401:
                note = "Legacy: 401 (Auth)"
            elif status == 404:
                note = "Legacy: 404 (Fallback nicht registriert — dokumentiert)"
            add_result("legacy", lp, status, body, note=note, error=err)
        # Kein Hard-Assert je Route (Vorgabe): Documentation-only; Verdict
        # in Result-Datei via compute_verdict().

    @classmethod
    def tearDownClass(cls):
        # Sicherheitshalber final schreiben (Verdict/Summary aktualisiert):
        write_result_file()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
