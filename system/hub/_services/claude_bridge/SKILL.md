---
name: claude-bridge
version: 1.0.0
type: service
author: BACH Team
created: 2026-09-29
updated: 2026-09-29
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services: []
  workflows: []

description: >
  Telegram⇄Claude-CLI Bridge — FastAPI-Daemon auf 127.0.0.1:8091 mit
  Fackel-Integration (Local/Cloud-Handover)
---
# Claude Bridge - Telegram ⇄ Claude-CLI

> Daemon, der Telegram-Nachrichten (Connector `telegram_main`) an die Claude-CLI weiterreicht und Antworten zurückliefert; stellt eine lokale HTTP-API (Port 8091) für Nachrichten, Status und Steuerung bereit und beteiligt sich am Fackel-System (Wer-rechnet-Steuerung via fackeltraeger).

## Zweck

Der Claude Bridge Service dient als lokale HTTP-Bridge zwischen Telegram (Connector `telegram_main`) und der Claude-CLI. Er empfängt eingehende Nutzernachrichten, leitet sie an das konfigurierte Claude-Modell weiter und liefert die generierte Antwort zurück. Zusätzlich bietet er eine steuerbare Daemon-Infrastruktur (Start/Stop/Status/Control), integriert sich in das Fackel-System zur Verteilung von Rechenlast zwischen lokalem und Cloud-Modus und stellt einen sicheren, konfigurierbaren API-Endpunkt für automatisierte Workflows bereit. Hauptziele sind: dezentraler, benutzerkontrollierter Nachrichtenversand; transparentes Budget- und Permission-Management; sowie nahtlose Einbindung in die BACH-Startspine-Orchestrierung.

## Quick Start

```bash
# Start via startspine (empfohlen, --bridge-Flag):
cd /Users/lukas/services/bach && ~/.venvs/bach/bin/python3 start/startspine.py start --bridge

# Health-Check:
curl -s http://127.0.0.1:8091/api/status

# Setup-Assistent (Erstkonfiguration):
python3 system/hub/_services/claude_bridge/setup_wizard.py
```

## Schnittstellen (server_api.py)

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/message` | POST | Nachricht an die Bridge (Telegram-Pfad simulieren/weiterleiten) |
| `/api/status` | GET | Laufzeit-Status (running, pid, mode, uptime) |
| `/api/control` | POST | Steuerbefehle an den Daemon |

Authentifizierung: `Authorization: Bearer <token>` — Token aus `config.json` unter `server.auth_token`. Ist der Token leer, läuft der Server im lokalen Modus ohne Tokenpflicht (nur 127.0.0.1).

## Architektur

```
claude_bridge/
├── SKILL.md ................... Du bist hier
├── bridge_daemon.py ........... Haupt-Daemon (~120KB): Telegram-Poll, Claude-CLI, Locking, Server-Start
├── server_api.py .............. FastAPI-App: /api/message, /api/status, /api/control (Bearer-Auth)
├── fackel.py .................. Thin-Wrapper um hub/_services/fackeltraeger.py (Fackel-State, S2-Handover)
├── security.py ................ Permissions (restricted/full-access), Tool-Allowlist
├── skill_loader.py ............ Lädt Bridge-Start: Root-SKILL.md + persoenlicher-assistent.txt
├── config.json ................ Laufzeit-Konfiguration (siehe unten)
├── setup_wizard.py ............ Interaktive Erstkonfiguration
├── bridge_tray.py ............. System-Tray-Client (Start/Stop/Status)
├── bridge_reset.py ............ Reset-Skript (Locks/State zurücksetzen)
├── telegram_manual_check.py ... Manueller Telegram-Abruf (Debug)
├── test_skills_load.py ........ Testet skill_loader.py
├── DEPLOYMENT.md .............. Deployment-Doku
├── GUI_KONZEPT_1594.md ........ GUI-Konzept (Task #1594)
└── TESTPLAN_1583.md ........... Testplan (Task #1583)
```

Verwandte Module:
- `hub/_services/fackeltraeger.py` — Fackel-System (Local/Cloud-Zuteilung, Handover-Protokoll)
- `start/startspine.py` — Orchestriert den Bridge-Start (`start --bridge`)
- `system/tools/compute_lock.py` — Fackel-Präferenzen (get/set_fackel_preference)

## Konfiguration (config.json)

| Schlüssel | Wert (Default) | Beschreibung |
|-----------|----------------|--------------|
| `enabled` | `true` | Bridge aktiviert |
| `mode` | `local` | Betriebsmodus |
| `connector_name` | `telegram_main` | Verwendeter Connector |
| `claude_cli.path` / `.model` | `claude` / `sonnet` | CLI-Binary und Modell |
| `server.host` / `.port` | `127.0.0.1` / `8091` | HTTP-API-Bindung |
| `server.auth_token` | `""` | Bearer-Token für die API |
| `bridge.autostart` | `true` | Autostart via startspine |
| `bridge.fackel_check` | `true` | Fackel-Prüfung beim Start |
| `budget.daily_limit_usd` | `5.0` | Tagesbudget (Warnung bei 80 %) |
| `permissions.default_mode` | `restricted` | Tool-Allowlist greift |

## Betriebshinweise

- **Port:** 8091 (fest aus `config.json`; startspine-Defaults stehen ebenfalls auf 8091).
- **Logs:** `/Users/lukas/.local/state/bach/runtime/logs/bridge.log`
- **PYTHONPATH:** muss `/Users/lukas/services/bach/system` enthalten.
- **Bekannte Stolpersteine:** `bridge_daemon.py` pinnt beim Start stdlib-`email` (hub/email.py-Shadowing würde FastAPI brechen); der Daemon läuft als `__main__`-Skript — `_get_bridge()` in `server_api.py` fällt daher auf `sys.modules["__main__"]` zurück. `signal only works in main thread` (Z.~2724) ist ein harmloser Nebenbefund aus dem Server-Thread.

## Changelog

**Aktuelle Version: 1.0.0** (2026-09-29)
- SKILL.md angelegt (Task #1600, Schritt B)
- Bridge lauffähig auf Port 8091: stdlib-email-Pinning + `_get_bridge()`-Fallback gefixt, startspine-Defaults 8080→8091

---

*Erstellt mit BACH Template*
