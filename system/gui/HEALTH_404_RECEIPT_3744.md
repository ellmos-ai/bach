# Receipt: 404-Klärung `/api/health` + `/dist-manifest.json` (Task #3744)

Stand: Live-Readback gegen `http://127.0.0.1:8000` (laufender Dienst).
Zweck: Beleg, dass der Live-404 **kein** Code-Defekt dieses Branches und **kein**
Middleware-Fehler ist, sondern ein Deployment-/Neustart-Zustand.

## 1. Live-Beobachtung (Vor-Zustand)

| Pfad | Status | Body (Kurzform) |
| --- | --- | --- |
| `/api/health` | 404 | `{"detail":"Not Found"}` (22 B, FastAPI-Default) |
| `/dist-manifest.json` | 401 | `{"error":"Geräteanmeldung erforderlich"}` (41 B) |
| `/api/gui/kit-manifest` | 200 | Kit-Manifest mit `is_kit_verified: false` |
| `/` | 200 | 70 KB, `<title>Dashboard \| System GUI</title>` |
| `/openapi.json`, `/docs`, `/gui/openapi.json` | 401 | `Geräteanmeldung erforderlich` |
| `/api/openapi.json` | 401 | `Missing device authorization token` (70 B) |

## 2. Code-Abgleich (`system/gui/server.py`, Stand Branch)

- `server.py:1301` `app = FastAPI(...)`.
- `server.py:1898` `app.add_middleware(DeviceAuthMiddleware)`,
  `server.py:1928` `app.add_middleware(HostAllowlistMiddleware)`.
  Beide Registrierungen liegen **vor** der Route-Definition
  `@app.get("/api/health")` (`server.py:5906`). Starlette baut den
  Middleware-Stack beim ersten Request; da zu diesem Zeitpunkt noch keine Routen
  registriert sind, entsteht daraus **kein** Fehler. Reihenfolge ist unverdächtig.
- `EXEMPT_API_PATHS` (`server.py:1683–1705`) enthält `/api/health` (1684) und
  `/api/gui/kit-manifest` (1690). `/api/health` passiert die Auth also frei —
  dennoch 404. `/dist-manifest.json` steht **nicht** in der Liste und wird
  deshalb von der Middleware mit 401 abgewiesen (`server.py:1713`), bevor eine
  Route greift.

## 3. Befund

Der 404-Body ist der FastAPI-Default von Starlette ("Not Found") und stammt
nicht aus einem Handler des Branches (dort: `{"status": "ok"}` bzw.
`"Gui dist manifest unavailable"`). Gleichzeitig liefert
`/api/gui/kit-manifest` live 200 — die Route existiert also im laufenden
Prozess.

=> Der laufende Prozess fährt einen Code-Stand, der **nach** der Einführung von
`/api/gui/kit-manifest`, aber **vor** dem Commit mit
`@app.get("/api/health")` (`server.py:5906`) liegt. Es fehlt der Neustart bzw.
das Deployment des aktuellen Branch-Stands. **Ursache: Deployment/Neustart, nicht
Middleware und nicht Routing.**

Der 401 auf `/dist-manifest.json` ist dagegen codekonform (Pfad nicht exempt) und
verschwindet erst mit gültigem Bearer-Token oder einer bewussten Exempt-Ergänzung
— beides nicht Teil von #3744.

## 4. Zusatzbefund Kit-Verifikation

Live `pinned_source_commit: eb0251ac4b85…`, installiert aber `688805fa96bc…`
(`commit_mismatch`), `dist_page_count 375` vs. `expected_page_count 39` =>
`is_kit_verified` false (`server.py:2047–2064`). Die installierte Dist entspricht
nicht dem gepinnten Paket `ellmos-system-gui-0.2.30-eb0251ac4b85.zip`
(sha256 `ff07b556…b188`). Ein Reinstall ist im Repo nicht automatisierbar
(kein Reinstall-CLI, `system/gui/web/` ohne `dist/`, `system/gui/staging/` ohne
Archiv) und ist als Folgetask ausgelagert.

## 5. Nachweis

- `system/tests/test_gui_health_and_dist_3744.py` — Unit-Beleg, dass die Routen
  im Branch existieren und regulaer antworten (4 passed).
- `system/tests/test_live_gui_readback_3744.py` — tolerante Live-Sonde, die den
  Zustand oben readback-fähig festhält (Soll-Prüfung strikt opt-in via
  `BACH_LIVE_GUI_STRICT=1`).
