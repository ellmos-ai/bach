# Executive Summary: 24h-Bridge, Fackeltraeger & GUI-Routing

**Datum:** 2026-09-29
**Anlass:** Telegram-Nachrichten #965–972 (Lukas)
**Status:** Ist-Analyse abgeschlossen, Umsetzung gestartet (manuell, ohne Worker gemaess #971)

---

## 1. Kernentscheidungen

| Thema | Entscheidung |
|---|---|
| GUI-Routing (#1594) | Default-Routing an den 24h-Fackeltraeger |
| Extrasessions | Nur explizit angefordert UND mit Zeitlimit |
| Lokale 24h-GUI-Session | Laeuft OHNE Fackel-Claim, UI-Badge "lokal" |
| 24h-Session-Typen | bridge + personal_assistant (H24_SESSION_TYPES) |
| Max. aktive 24h-Sessions | 2 (MAX_24H_ACTIVE) |
| Arbeitsweise (#971) | Manuelle Umsetzung, KEINE Worker/Schwarm |

## 2. Ist-Zustand (Analyseergebnis)

### Autostart (#965)
- **GUI + Tray:** startspine.py managed gui/chat/tray + Ollama-Readiness; Aufruf ueber [D] in start/bach.bat.
- **Bridge:** getrennt davon. Start via config.json (bridge.autostart=true), bridge_daemon v2.3 (FastAPI-Server-Mode, Bearer-Auth, CORS, Port 8000) bzw. bridge.sh + Tray. Auf Hetzner analog.

### Bridge ohne Telegram (#967)
- Ja. config: start_without_connectors=true, chat_id=telegram_main. Die Bridge startet auch ohne Telegram-Connector.
- Nachrichten-Komprimierung laeuft nativ in der Bridge.

### Fackeltraeger
- fackel.py delegiert an hub/_services/fackeltraeger.py.
- system_id-UUID pro Maschine, fackel_state-Tabelle in BACH_DB, HandoverPackage-Dataclass, Heartbeat 60s / Timeout 300s.

### GUI
- gui/server.py: FastAPI mit vielen /api/*-Endpoints, DEFAULT_TASK_ASSIGNEE=OLLAMA (Entscheid D-20260906-002).
- **Fackel-/PA-Routing fehlt komplett** (keine /api/fackel-Endpoints vorhanden).

### Baustelle
- **skills/personal_assistant existiert noch nicht** (skills/ enthaelt nur _services, _templates, therapie, workflows).

## 3. Umsetzungsplan (Uebersicht)

1. Bridge-Autostart in bach.bat/startspine verankern (startspine hat aktuell keinen bridge-Service).
2. Root-SKILL.md: Bootstrapping-Abschnitt Personal-Assistent fuer die Bridge.
3. GUI-Default-Routing zu 24h-Fackeltraeger inkl. /api/fackel/*-Endpoints in gui/server.py.
4. skills/personal_assistant neu anlegen.
5. #972: c_*.py-Tools ohne Prefix auf Zielordner verteilen (coding/, cli/, claude/, converters/, ...).

Details: UMSETZUNGSPLAN_24H_BRIDGE_FACKEL_2026-09-29.md (gleicher Ordner).

## 4. Alte Blocker (unveraendert, nicht Teil dieses Auftrags)

- #1463 / #1462: warten auf USER
- #1250: warten auf OPERATOR
- #1599 / #1570: offen
- Msg #1200: bleibt unbeantwortet
