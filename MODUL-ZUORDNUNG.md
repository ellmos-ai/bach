# MODUL-ZUORDNUNG

Zuordnung von BACH-Fachlogik zu Fachmodulen und Festlegung der
kanonischen KERN-GRENZE. In-Repo-Äquivalent zu den OCEAN/OneDrive-
Dokumenten (AKTUELLER-PLAN.md, ANFORDERUNGEN-DETAIL.md).
Begleitet OCEAN-TRANSFER-PLAN.md (Rückmodularisierung 13.10.2026).

## 0. Kanonische Kern-Grenze (Task #2451)

Quelle und verbindliche Definition: `system/core/README.md`.
Zusammenfassung:

- **KERN** = dünne Infrastruktur, von allen Komponenten genutzt, **keine Fachlogik**:
  `system/bach.py` (CLI), `adapter.py` (Lead-HTTP-Adapter), `db.py`/`safe_db.py`
  (`bach.db`-Speicher), `registry.py`, `base.py`, `aliases.py`, `launcher.py`,
  `network_lock.py`, `provenance.py`, `telemetry.py`, `hooks.py`, `sandbox.py`,
  `app.py`, `__init__.py`.
- **NICHTS** Fachlogik/Module im Kern. Fachlogik gehoert in Fachmodule und wird
  per Rückmodularisierung ausgegliedert.

### 0.1 Fachlogik-Reste im Kern -> Extraktion

| Heute in core | Fachlogik | Ziel-Fachmodul | Folgetask | module-gate |
|---------------|-----------|----------------|-----------|-------------|
| `capabilities.py` | Zugriffskontrolle / Trust-Level / Capability-System | `policy/governance` | Folgetask A: `capabilities`->`policy/governance` | #2445 |
| `agent_runtime.py` | instanziierbare Agenten / Agent-Laufzeit | `agents` | Folgetask B: `agent_runtime`->`agents` | #2445 |
| `instance_registry.py` | Instanz-Discovery / Registry | `coordination/messaging` | Folgetask C: `instance_registry`+`instance_messaging`->`coordination/messaging` | #2445 |
| `instance_messaging.py` | Instanz-Kommunikation / Messaging | `coordination/messaging` | Folgetask C (mit instance_registry) | #2445 |
| `plugin_api.py` | Laufzeit-Erweiterung / Plugin-System | `plugin-system` | Folgetask D: `plugin_api`->`plugin-system` | #2445 |

### 0.2 Extraktionsprinzipien (konsistent mit OCEAN-TRANSFER-PLAN.md)

- Schmale Adapter: Im Kern bleibt nur ein dünner Adapter/Stub (Forwarder ans
  Fachmodul). Kein zweiter Store/Scheduler/Router im Kern.
- policy-registry / Capability-Logik = 1. Transfer (Folgetask A).
- Fachmodul wird das einzige System der Fachlogik; Kern ruft nur ueber Adapter.
- Nicht mehr genutzte Stubs/Altteile -> `DEPRICATED.md`, nicht still im Kern.

### 0.3 Bindungen

- **module-gate #2445:** Jede Extraktion wird gegen die Kern-Grenze (README A 2)
  geprueft: Fachlogik verlaesst core, Adapter bleibt duenn.
- **ocean.py:** Code-Bindung an `ocean.py` (Root) ist in diesem Lauf NICHT
  durchführbar (Datei ausserhalb Read-Scope / blockiert). Sie ist extern
  (OneDrive `open-ocean/`). Folgetask E dokumentiert die ocea n.py-Bindung
  als offen/extern; sie wird im OCEAN-Rueckmodularisierungslauf erledigt.

### 0.4 Folgetasks (per task_manage angelegt, Eltern #2451 bleibt offen / pending)

Bestaetigte Kind-Task-IDs (sequential, Eltern bleibt offen):

- #2611 Folgetask A: `capabilities.py` -> `policy/governance`
- #2612 Folgetask B: `agent_runtime.py` -> `agents`
- #2613 Folgetask C: `instance_registry.py` + `instance_messaging.py` -> `coordination/messaging`
- #2614 Folgetask D: `plugin_api.py` -> `plugin-system`
- #2615 Folgetask E: module-gate #2445 Bindung (Pruefung aller Extraktionen gegen Kern-Grenze)
- #2616 Folgetask F: ocean.py-Bindung (extern/blockiert, im OCEAN-Lauf)

Jede Extraktion (A-D) ist an module-gate #2445 + die Kern-Grenze
`system/core/README.md` A 2 gebunden. ocean.py (#2616) ist extern und in
diesem Lauf nicht umsetzbar.
