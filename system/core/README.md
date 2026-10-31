# core/ - BACH kanonische KERN-GRENZE

Diese Datei ist die **kanonische Definition** der BACH-Kern-Grenze (Task #2451).
Sie legt verbindlich fest, was zum *Kern* zulaesst und was **Fachlogik** ist und
deshalb **NICHT** in `system/core/` gehoert. Fachlogik gehoert in die
Fachmodule (policy/governance, agents, coordination/messaging, plugin-system)
und wird per OCEAN-Rueckmodularisierung ausgegliedert.

> Kern = duenn, stabil, von allen anderen Komponenten genutzt, **keine**
> Fachlogik. Fachlogik gehoert nie in den Kern.

## 1. Definition der KERN-GRENZE

Der Kern enthaelt ausschliesslich **dünne Infrastruktur** ohne Fachlogik:

### ENTHALTEN ist Kern (durfen hier bleiben)

| Datei | Zweck | Kern-Grund |
|-------|-------|------------|
| `system/bach.py` | BACH-CLI (Kern-CLI-Einstiegspunkt; Root `bach.py` ist nur Wrapper -> `system/bach.py`, cwd=`system/`, Import-Pfad `from core.db …`) | CLI-Kerneinstieg |
| `adapter.py` | HandlerAdapter / Lead-HTTP-Adapter (Legacy <-> neue API, Adapter-Pattern) | dünner Adapter, kernkonform |
| `db.py` | Datenbank-Verwaltung (SQLite-Connection, Schema-Loading) | `bach.db`-Speicher |
| `safe_db.py` | Sichere DB-Zugriffsschicht ueber `db.py` | `bach.db`-Speicher |
| `registry.py` | Tool/Skill-Registry (Auto-Discovery, Registrierung) | Kern-Infrastruktur |
| `base.py` | Basis-Klassen und Utilities | Kern-Infrastruktur |
| `aliases.py` | Befehlskuerzel (z.B. `t` -> `task`) | Kern-Infrastruktur |
| `launcher.py` | BACH Launcher (Startup-Sequenz) | Kern-Infrastruktur |
| `network_lock.py` | Concurrency-/Netzwerk-Schreibsperre | Kern-Infrastruktur |
| `provenance.py` | Provenance-/Metadaten-Verwaltung | Kern-Infrastruktur |
| `telemetry.py` | Telemetrie / Observability | Kern-Infrastruktur |
| `hooks.py` | Hook-System (Pre/Post-Execution) als Grenzschnittstelle | Kern-Infrastruktur |
| `sandbox.py` | Ausfuehrungs-Sandbox (Isolation) | Kern-Infrastruktur |
| `app.py` | App-Initialisierung / Bootstrap | Kern-Infrastruktur |
| `__init__.py` | Package-Docstring | Kern-Infrastruktur |

### NICHTS Fachlogik im Kern

`system/core/` darf **keine Fachlogik und keine Module** enthalten.
Ein Modul ist Fachlogik, wenn es eine fachliche Entscheidung/Regel
(Zugriffskontrolle, Agentenverhalten, Instanzkoordinierung, Laufzeit-Erweiterung)
verkodiert und nicht nur duenne Infrastrukturschnittstelle bereitstellt.

## 2. Fachlogik-Reste im Kern -> Extraktionsliste

Folgende Dateien enthalten heute noch Fachlogik im Kern und sind
**Herausloesekandidaten**. Sie duerfen nach der Extraktion nur als
**dünner Adapter/Stub** im Kern bleiben (Forwarder an das Fachmodul).

| Datei (heute in core) | Enthaltene Fachlogik | Ziel-Fachmodul | Folgetask |
|------------------------|----------------------|----------------|-----------|
| `capabilities.py` | Zugriffskontrolle / Trust-Level / Capability-System | policy / governance | Folgetask: `capabilities` -> `policy/governance` (module-gate #2445) |
| `agent_runtime.py` | instanziierbare Agenten / Agent-Laufzeitumgebung | agents | Folgetask: `agent_runtime` -> `agents` (module-gate #2445) |
| `instance_registry.py` | Instanz-Discovery / Registry | coordination / messaging | Folgetask: `instance_registry`+`instance_messaging` -> `coordination/messaging` (module-gate #2445) |
| `instance_messaging.py` | Instanz-Kommunikation / Messaging | coordination / messaging | Folgetask: `instance_registry`+`instance_messaging` -> `coordination/messaging` (module-gate #2445) |
| `plugin_api.py` | Laufzeit-Erweiterung / Plugin-System | plugin-system | Folgetask: `plugin_api` -> `plugin-system` (module-gate #2445) |

### Extraktionsprinzipien (siehe OCEAN-TRANSFER-PLAN.md / MODUL-ZUORDNUNG.md A 0)

- **Schmale Adapter:** Im Kern bleibt nach der Extraktion nur ein duenner
  Adapter/Stub, der Forwarder an das Fachmodul ist. Kein zweiter Store,
  kein zweiter Scheduler, kein zweiter Router im Kern.
- **policy-registry zuerst:** Capability-/Trust-Logik ist der erste Transfer
  (policy-registry), danach die uibrigen Fachmodule.
- **Kein zweites System:** Fachmodul wird das einzige System der jeweiligen
  Fachlogik; der Kern ruft nur ueber den Adapter.
- **Deprecation:** Altteile / nicht mehr genutzte Stubs werden in
  `DEPRICATED.md` dokumentiert, statt still im Kern zu liegen.

## 3. Verwendung

```python
# Datenbank-Zugriff (intern)
from core.db import get_connection

# Registry
from core.registry import ToolRegistry

# Aliases
from core.aliases import resolve_alias
```

## 4. Wichtig

- `db.py` verwaltet die Verbindung zu `data/bach.db`.
- Fuer normalen Zugriff auf Tasks/Memory/Lessons: `bach_api` verwenden, nicht `core.db`.
- `registry.py` wird beim Startup automatisch geladen.
- Fachlogik gehoert in die Fachmodule (siehe A 2). Im Kern darf nur der
  duenne Adapter bleiben.

---
*Kanonische Kern-Grenze (Task #2451). Fachlogik wird ausgegliedert,
Kern bleibt duenn und stabil.*
