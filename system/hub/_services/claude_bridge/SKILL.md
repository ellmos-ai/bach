---
name: claude_bridge
version: 1.0.0
type: service
author: BACH Team
created: 2026-10-30
updated: 2026-10-30
last_updated: 2026-10-30
anthropic_compatible: true
status: active
dependencies: [fastapi, uvicorn]
description: >
  HTTP-Bridge auf FastAPI/uvicorn, die Claude-Code-Sessions an BACH koppelt.
  Sie laedt den Skill-Bestand, kapselt die Authentifizierung via Token und
  stellt Schutzfunktionen bereit. Deployment-Hinweise (Hetzner CCX33,
  SSH-Tunnel) stehen in DEPLOYMENT.md.
---

# Claude Bridge

**Kategorie:** Systemdienst (HTTP-Bridge)

## Zweck
Der Ordner enthaelt die Claude Bridge: einen FastAPI/uvicorn-Server, der
Claude-Code-Sessions an BACH anbindet. `bridge_daemon.py` startet den Server
(`server_api.py`), `skill_loader.py` laedt die Skills, `security.py` kapselt
die Authentifizierung und `fackel.py` enthaelt Schutzfunktionen.

Wichtig: `auth_token` in config.json ist Pflicht — ohne Token laeuft die API
unauthentifiziert. `cors_origins` ist konfigurierbar. Einzelheiten zum
Deployment (Hetzner CCX33, SSH-Tunnel) stehen in DEPLOYMENT.md im Ordner und
werden hier nicht dupliziert.

## Nutzung
```bash
# Server starten
PYTHONIOENCODING=utf-8 python bridge_daemon.py --server

# oder: config.json mit "mode": "server" (host 127.0.0.1:8080)
```

## Dateien
- `bridge_daemon.py` — Start und Steuerung
- `server_api.py` — FastAPI-Server
- `skill_loader.py` — Skill-Loader
- `security.py` — Authentifizierung
- `fackel.py` — Schutzfunktionen
- `DEPLOYMENT.md` — Deployment (Hetzner CCX33, SSH-Tunnel)