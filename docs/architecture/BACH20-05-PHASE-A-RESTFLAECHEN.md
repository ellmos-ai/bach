# BACH20-05 — Phase A: Restflächen-Inventar (13 Flächen)

> **Dokument-ID:** BACH20-05-PHASE-A-RESTFLAECHEN-2026-09-30
> **Quellen:** BACH20-01-INVENTAR-2026-09-27 (8er-Modul-Matrix, Klassifikationsschema), BACH20-02-SYSTEMMANIFEST (Schema bach-system-manifest-v1), Live-Listings `system/` (Checkout task-1427)
> **Task:** #1427 (BACH-2.0-Rückfluss, Phase A)
> **Bezug:** Ergänzt BACH20-01 um die 13 betrieblichen Restflächen jenseits der 8 TRANSFER-Module.

---

## 1. Einordnung

BACH20-01 klassifiziert Core, 8 externe TRANSFER-Module, Adapter, Daten und Legacy.
Dieses Dokument inventarisiert die **13 übrigen Betriebsflächen** des Monorepos nach demselben
Klassifikationsschema (`core` / `modul` / `adapter` / `daten` / `legacy` gemäß
bach-system-manifest-v1). Alle 13 Flächen sind **monorepo-intern** (kein externes
TRANSFER-Repo, kein Commit-Pin) und laufen unter `sot_kennzeichnung=aktiv`.

---

## 2. Flächen-Matrix (13 Restflächen)

| # | Fläche | Konkrete Pfade (Ist-Stand, gelistet) | Klassifikation | Befund |
|---|---|---|---|---|
| 1 | **Handler** | `system/hub/` (137 Einträge, u. a. Handler-Module) | **core** | Hub-Handler bleiben monorepo-intern; externe Anbindung nur über `*_provider.py`-Seams (Adapter). |
| 2 | **API** | `hub/apibook.py`, `system/bach_api.py`, `system/gui/api/` | **core** | Interne API-Fläche; kein externes Repo. |
| 3 | **CLI** | `system/bach.py`, `system/bin/` | **core** | Einstiegspunkt/Bin-Skripte; kein externes Repo. |
| 4 | **MCP** | `hub/mcp.py`, `hub/mcp_client.py`, `system/tools/mcp_server.py`, `system/tools/mcp/` | **core** | MCP-Server/-Client monorepo-intern. |
| 5 | **Plugins** | `hub/plugins.py`, `system/core/plugin_api.py` | **core** | Plugin-Registry + Core-Plugin-API; intern. |
| 6 | **Services** | `hub/_services/` (u. a. `_services/chat/` in assistant-core-Anbindung, Welle 1+2) | **core** | Interne Services; `_services/chat/` ist zugleich Seam zu assistant-core (Adapter-Anteil, siehe BACH20-01 §2 Modul 4). |
| 7 | **Skills** | `system/skills/` (`_services`, `_templates`, `therapie`, `workflows`), `hub/skills.py`, `system/tools/skills/` | **core** (Engine) / **daten** (Skill-Inhalte) | Skill-Engine intern; Skill-Definitionen sind Inhaltsdaten, kein Code-Pin. |
| 8 | **Tools** | `system/tools/` (u. a. `maintenance/`, `self_test/`), `hub/tools.py` | **core** (Engine) / **daten** (Tool-Definitionen) | Analog Skills: Engine intern, Definitionen Inhaltsdaten. |
| 9 | **Workflows** | `system/skills/workflows/`, `system/tools/workflows_export.py` | **core** (Export/Engine) / **daten** (Workflow-Definitionen) | Anbindung workflowhooker läuft separat über `hub/workflow_hook_provider.py` (Adapter, BACH20-01 §2 Modul 7). |
| 10 | **Secrets** | `hub/secrets_handler.py`, `hub/security.py`, `system/core/network_lock.py` | **core** | Sicherheits-/Secrets-Behandlung bleibt zwingend monorepo-intern (kein Externalisierungs-Kandidat). |
| 11 | **Update** | `hub/update.py`, `hub/upgrade.py`, `hub/snapshot.py` | **core** | Selbstaktualisierung intern; berührt keine TRANSFER-Module. |
| 12 | **Restore** | `hub/restore.py`, `hub/backup.py` | **core** | Backup/Restore intern; Rollback-Ziele der Env-Schalter (Fallback-Pfade) bleiben gemäß BACH20-01 §1 **nicht archivierbar** bis #1340/#1341. |
| 13 | **GUI** | `system/gui/` (`server.py`, `api/`, `web/`, `templates/`, `static/`, `config.py`, `backend_origin.py`), `hub/gui.py` | **core** mit **adapter**-Anteil | `gui/server.py` ist zugleich Seam zu accounts-core (BACH20-01 §2 Modul 3); der Adapter-Anteil hält Env-Schalter/Fallback. |

---

## 3. Querschnitts-Befunde

- **Adapter-Anteile in Restflächen:** `hub/*_provider.py`, `hub/test.py`, `hub/notify.py`,
  Seams in `hub/steuer.py` und `gui/server.py` sind bereits in BACH20-01 §1 als **Adapter**
  klassifiziert; sie überschneiden sich mit den Flächen 1, 6 und 13 und werden dort nicht
  doppelt gezählt.
- **Daten-Fläche:** Kanonisch `BACH_DB` (Runtime-DB-Verzeichnis), **nicht** `system/data/`
  im Checkout (BACH20-01 §1). Skill-/Tool-/Workflow-Definitionen (Flächen 7–9) sind
  zusätzliche Inhaltsdaten im Checkout.
- **Legacy:** `_archive/` bleibt unverändert (Rollback-Integrität); `system/bach_legacy.py`
  und `hub/daemon.py` sind dokumentierte Kompat-Wrapper und fallen **nicht** in die
  Legacy-Archivierung.
- **Kein Externalisierungs-Kandidat:** Secrets/Update/Restore (Flächen 10–12) sind
  trustkritisch und bleiben dauerhaft core.

---

## 4. Konsequenz für das Systemmanifest (BACH20-02)

Für jede der 13 Flächen ist ein Manifest-Eintrag mit Pflichtfeldern
`name`, `klassifikation` (aus §2), `sot_kennzeichnung=aktiv`, `status` anzulegen.
Da alle Flächen monorepo-intern sind, gilt `pin=""` (Pin-Regex erlaubt Leerstring);
kein `env_schalter` außerhalb der 6-fach-Whitelist `BACH_USE_EXTERNAL_*` + `NATIVE_FLAG`.
Ist/Soll-Abgleich (Validator V3) entfällt für diese Einträge; der Vollständigkeits-Abgleich
gegen diese Matrix ist Teil von V3 (Taggleich-Ausnahme gilt weiterhin).

---

## 5. Offene Verweise

| Punkt | Stand | Task |
|---|---|---|
| Schema-Erweiterung (Lizenz, Plattformen, Aktivierungsmodus, Provenienz) | Phase B | **#1427** → BACH20-06 |
| Windows-Gegenproben / Fallback-Archivierung | offen | #1340 / #1341 (aus BACH20-01 §4) |

---

*Erstellt: 2026-09-30 · Quellenstand: Checkout task-1427, BACH20-01/02 · Abschlussgrenze: vollständige Inventarisierung der 13 Restflächen mit Pfaden und Klassifikation — erreicht.*
