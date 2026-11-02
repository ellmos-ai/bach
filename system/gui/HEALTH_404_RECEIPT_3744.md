# Health & Dist-Manifest 404 Receipt (Task #3744)

## Befund
Vor diesem Fix waren `/api/health` und `/dist-manifest.json` zwar in der Auth-Allowlist von `system/gui/server.py` aufgeführt, besaßen aber keinen expliziten FastAPI-Route-Handler und fielen deshalb mit `404 Not Found` durch.

## Behebung
- `GET /api/health` liefert `200 OK` mit `{"status": "ok"}`.
- `GET /dist-manifest.json` liefert `ASTRO_DIST_DIR / "dist-manifest.json"` als `application/json` (bzw. `404`, falls kein Dist-Manifest im aktiven Build liegt).
- Abgesichert durch `system/tests/test_gui_health_and_dist_3744.py`.
