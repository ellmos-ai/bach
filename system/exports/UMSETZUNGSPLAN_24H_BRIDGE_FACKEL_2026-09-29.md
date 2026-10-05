# Umsetzungsplan: 24h-Bridge, Fackelträger & GUI-Integration

**Datum:** 2026-09-29
**Status:** Umsetzung (manuell, ohne Worker/Schwarm – siehe #971)
**Vorläufer:** EXECUTIVE_SUMMARY_24H_BRIDGE_FACKEL_2026-09-29.md/.pdf (erledigt), Referenz: system/docs/FACKELTRAEGER_UMSETZUNGSPLAN.md (287 Zeilen, vollständig analysiert)
**Antwort an Lukas:** Msg #1201 gesendet

---

## 1. Ziel

Die 24h-Bridge (claude_bridge, Port 8000) wird zum vollwertigen BACH-Service mit Autostart, das Fackelträger-Modell wird implementiert (max. 2×24h-Sessions pro Benutzer: Bridge + persönlicher Assistent, ortsgebunden, Single-24h-Privileg pro System), und die GUI zeigt Fackel-Status mit Handover-Dialog. Routen ohne zugewiesenen Fackelträger werden an den lokalen 24h-Fackelträger geroutet (Badge "lokal").

**Wichtig:** Umsetzung erfolgt manuell Schritt für Schritt. KEIN agent_spawn, KEIN Schwarm (Vorgabe #971).

---

## 2. Die 7 Grundsätze (aus FACKELTRAEGER_UMSETZUNGSPLAN.md)

1. **Ein Herz pro Benutzer** – nur eine aktive Fackel-Träger-Identität je Benutzerkontext.
2. **Max. 2×24h pro Benutzer** – Bridge-Assistent + persönlicher Assistent.
3. **Single-24h-Privileg pro System** – pro system_id nur eine 24h-Session.
4. **Fackel ist ortsgebunden** – sie gehört zu (user_id, system_id), nicht zu einem Prozess.
5. **Komprimierung = Claude-Code-Standard** – Handover-Pakete nutzen Standard-Compaction.
6. **Bridge ist ohne Connector startbar** – start_without_connectors=true; Bridge läuft lokal weiter.
7. **Logisch konsistent** – Regeln gelten systemweit, keine Sonderfälle pro Dienst.

---

## 3. Komponenten

| Komponente | Ort | Status |
|---|---|---|
| bridge_daemon.py v2.3 | hub/_services/claude_bridge/ | existiert (Port 8000, Bearer/CORS) |
| fackel.py (H24_SESSION_TYPES, MAX_24H_ACTIVE, acquire_fackel) | hub/_services/claude_bridge/fackel.py | existiert |
| **fackeltraeger.py** (Regel-Engine, State-Store, Handover-Orchestrierung) | hub/_services/fackeltraeger.py | **NEU anzulegen** |
| bridge_tray.py Autostart | start/startspine.py + bach.bat | **zu integrieren** |
| GUI: Fackel-Status + Handover-Dialog | gui/server.py + Frontend | **zu integrieren** |
| skills/personal_assistant | skills/ | **NEU anzulegen** |

**State:** `BACH_RUNTIME_DIR/fackel/` mit `fackel_state.json`, `handover/`, `worker/`, `meta/`

**fackel_state.json Schema:**
```json
{
  "version": 1,
  "owner_system_id": "<hash+BACH_SYSTEM_ID>",
  "owner_user_id": "<user>",
  "fackeln": [
    {"id": "...", "type": "bridge_assistant|personal_assistant",
     "system_id": "...", "user_id": "...",
     "started_at": "...", "last_seen": "...", "status": "..."}
  ]
}
```

**Handover:** Fackel-ID = (user_id, system_id, session_id, timestamp). 4 Schritte: (1) Request → (2) Regeln prüfen + Paket schnüren → (3) alte Instanz komprimiert + sendet → (4) neue startet; alte beendet sich erst nach Bestätigung.

**API (Bridge/GUI):** POST /fackel/request|handover|release, GET /fackel/status, POST /worker/todo, GET /worker/todo/next.
**Events:** fackel.started, fackel.handover.*, fackel.released, worker.todo.*

---

## 4. Konkrete Umsetzungsschritte

### Schritt A) Bridge-Autostart in startspine.py + bach.bat

Konkrete Edits in `/Users/lukas/services/bach/start/startspine.py`:

1. **Service-Tupel erweitern:** Start-Loop Zeile ~563 (`("tray","chat","gui")` → `("tray","chat","bridge","gui")` – Bridge NACH chat, VOR gui), Status-Loop Zeile ~950 (`("gui","chat","tray")` + "bridge"), Stop-Loop Zeile ~1023 (+"bridge").
2. **_service_health (ab Z. 280):** Case "bridge" → HTTP-Healthcheck gegen `http://127.0.0.1:8000/health` (Bearer nicht nötig für Health; Timeout ~2s).
3. **_start_service (ab Z. 461):** Spec für "bridge" → Start von `hub/_services/claude_bridge/bridge_daemon.py` (venv-python, env: BACH-Config, Port 8000, start_without_connectors=true).
4. **argparse start (Z. 1159–1169):** `start.add_argument("--bridge", ...)` ergänzen (~Z. 1161); stop `--services`-Hilfetext (Z. ~1180) um "bridge" erweitern (Kommaliste gui,chat,tray,bridge).
5. **_rollback_started_services (Z. 558):** Bridge in die Rollback-Liste aufnehmen.
6. **bach.bat:** `:gui`-Sequenz/Menü so erweitern, dass die Bridge im Standard-Boot mitgestartet wird (Menüpunkt-Hilfetexte prüfen; Default-Pfad `:default_start` → startspine.py start bekommt Bridge implizit über Loops).

### Schritt B) Root-SKILL.md Bootstrapping (persönlicher Assistent für Bridge)

- Root-SKILL.md (repo-root) wird von bridge_daemon.py beim Start geladen und definiert Bootstrapping: Identität = persönlicher Assistent, Lade-Reihenfolge (root-SKILL.md → pers.-Assistent-Skill), Fackel-Awareness (acquire/status), Verhalten bei fehlendem Connector (Prinzip 6: lokal weiterarbeiten).

### Schritt C) gui/server.py: /api/fackel/* + Default-Routing

- Endpoints: GET /api/fackel/status, POST /api/fackel/request, POST /api/fackel/handover, POST /api/fackel/release → Proxy/Weiterleitung an Bridge (127.0.0.1:8000) bzw. direkt an fackeltraeger.py.
- **Default-Routing:** Tasks/Routen ohne zugewiesenen Fackelträger → an 24h-Fackelträger des lokalen Systems; UI-Badge **"lokal"** für nicht-geclaimte (DEFAULT_TASK_ASSIGNEE="OLLAMA" ist bekannter Ist-Zustand; Doku: compute_lock.py fackel_preference get/set, VALID_FACKEL_PREFERENCES, slots_config.update_fackel_preference).
- Handover-Dialog im GUI: Status-Badge, aktive Fackeln (max. 2), Handover-Button mit 4-Schritt-Flow.

### Schritt D) skills/personal_assistant anlegen

- Neuer Skill-Ordner `skills/personal_assistant/` mit SKILL.md: Rolle (persönlicher 24h-Assistent des Users), Fackel-Regeln (max 2×24h, Single-24h pro System), Komprimierungs-/Handover-Verhalten, worker/todo-Nutzung.

### Schritt E) Task-Mapping #1591–#1596

| Task | Inhalt | Abhängigkeit |
|---|---|---|
| #1591 | Handover-Orchestrierung (4 Schritte) | vor #1593 |
| #1593 | Regel-Engine (7 Grundsätze in fackeltraeger.py) | nach #1591 |
| #1594 | GUI-Konzept Fackel-Status/Handover-Dialog | parallel, dann C |
| #1596 | Worker-Tage (worker/todo API) | nach fackeltraeger.py |
| (Schritt A) | Bridge-Autostart startspine/bach.bat | sofort |
| (Schritt D) | Skill personal_assistant | sofort |

---

## 5. Offene Fragen (mit Vorab-Festlegung)

1. **system_id** = Hash + BACH_SYSTEM_ID (Doppel-Absicherung).
2. **State-Ablage:** lokal in BACH_RUNTIME_DIR + Mirror-Sync (OneDrive-Mirror).
3. **Lock bei parallelem Handover:** ja, Sperre während 4-Schritt-Flow.
4. **Handover-Paket:** max. 50 MB.
5. **Migration:** schrittweise (Bridge-Autostart zuerst, dann Fackelträger, dann GUI).
6. **Handover-Berechtigung:** nur lokaler User darf Handover auslösen.

---

## 6. Vorgehen

1. startspine.py Details lesen (Z. 240–460: _service_health-Body, _start_service-Signatur/Spec-Format), gui/server.py, hub/_services/claude_bridge/fackel.py + bridge_daemon.py v2.3, config.json, compute_lock.py.
2. Umsetzung in Reihenfolge A → B → D → C → E (manuell, kein Schwarm).
3. Danach #972: c_*.py-Tools umsortieren (system/tools → coding/, cli/, claude/, converters/).
4. NICHT anfassen: #1463/#1462 (USER), #1250 (OPERATOR), #1599/#1570, Msg #1200, Migration 051_steuer_bank_matches.sql (Warnung ignorieren).

**Bekannte Rahmendaten:** config.json (mode=local, bridge.autostart=true, start_without_connectors=true, chat_id=telegram_main); BACH_DB=/Users/lukas/services/bach/system/data/bach.db (fackel_state-Tabelle); CLI: /Users/lukas/.venvs/bach/bin/python3 /Users/lukas/services/bach/bach.py (immer absolut).
