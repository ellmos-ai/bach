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

### 0.3 Bindungen (Stand 2026-10-31, Meilenstein `v3.15.0-ocean-stack-m1`)

- **module-gate #2445:** Jede Extraktion wird gegen die Kern-Grenze (README A 2)
  geprueft: Fachlogik verlaesst core, Adapter bleibt duenn.
- **Zentrale Ocean-Stack-Brücke (`system/hub/_services/ocean_stack_bridge.py`):**
  Bindet BACH als gebrandeten Teil-OS-Stack direkt an `ocean-resources` (`RAMDistributor`),
  `task-master` (`taskplan.lease.TaskLeaseManager`) und `open-ocean/tools/*`
  (`worker_worktree_policy`, `task_result_review_policy`, `escalation_ladder`,
  `persona_routing`, `learning_loop`, `agent_library`, `capability_views`,
  `governance_bridge`). Abgelöste BACH-Klassen (`OceanRamDistributor`,
  `BundledTaskPlanClient`) tragen `@deprecated_legacy_bach(...)`.
- **`ocean.py`:** Der Taskkern `taskplan` ist sowohl in `bach.py task` als auch
  in `open-ocean/ocean.py task` (`list|show|add|claim|done|next`) angebunden.

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

### 0.5 Taskkern `taskplan` (Task #2216 — Nutzerentscheidung PLANABGLEICH-20261024N-TASKKERN)

- Nutzerentscheidung (24.10.2026, gueltige Fassung in Task #2216): Der
  **Taskkern / das Modul `taskplan`** (Fachlogik Taskverwaltung; BACH und
  Ocean schreiben beide ueber den Taskkern) wird im Repo **`task-master`**
  gebaut. Die historische Fassung (Bauort `ticket-master`) ist aufgehoben.
- Der Audit-Befund „taskplan bridge implementation is not in the taskkern
  module“ ist damit zutreffend und wird hier dokumentiert statt im BACH-Code
  umgebaut (Bauort ausserhalb dieses Arbeitsbaums): Die Taskkern-
  Implementierung liegt gewollt ausserhalb des BACH-Repos. In BACH bleibt
  bewusst nur der duenne Adapter `system/hub/_services/taskplan_bridge.py`
  uebrig (additiver Spiegel BACH-Tasks -> taskplan-DB,
  `write_policy=legacy_only`; kein zweiter Store/Scheduler im Kern —
  konsistent mit Abschnitt 0.2). Er ist die BACH-seitige Bindung an den
  Taskkern und implementiert den Taskkern NICHT selbst.
- ocean.py-Bindung an den Taskkern: extern (OneDrive `open-ocean/`, analog
  Folgetask E #2616) und im OCEAN-Rueckmodularisierungslauf zu ziehen. Für
  Ausbau des Taskkerns selbst ist das `task-master`-Repo der Bauort; ein
  Folgetask dort wird bei Bedarf gelegt.
