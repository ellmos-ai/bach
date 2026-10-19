---
name: zuordnungsregler
version: 1.0.0
type: agent
author: BACH Team
created: 2026-10-16
updated: 2026-10-16
status: active
anthropic_compatible: true
orchestrates:
  experts: []
  services: []
dependencies:
  tools:
    - task_manage
    - search_text
  workflows: []
description: >
  Systemagent-Blueprint: Analysiert belegte Claimhindernisse der Taskqueue
  (queue_status-Auswahlgruende, Vertrag bach.worker-queue.v1) und legt einen
  konkreten Neuzuordnungsvorschlag mit Auswirkungen vor. Keine automatische
  Neuverteilung; jede Zuordnungsaenderung braucht ausdrueckliche Freigabe.
metadata:
  inputs:
    - "Claimhindernisgruende aus queue_status (explicit_slot_required, slot_binding, model_binding, pickup_*, ownership, deferred_version, held, not_claimable, conflict, changed_selection, empty_queue, selection_excluded, acquire_denied, selection_error)"
    - "Projizierte Auswahlrichtlinie selection_policy (Schema bach.worker-selection.v1)"
    - "Warteanzeige-Daten aus current_activity"
  outputs:
    - "protokollierter Neuzuordnungsvorschlag mit konkreten Feldern, Auswirkungen, Alternativen, naechstem Schritt und Abnahmekriterium"
---

# Zuordnungsregler (BACH Systemagent)

> **VERSIONS-HINWEIS:** v1.0.0 – Blueprint nach system/skills/_templates/TEMPLATE_AGENT.md. Umsetzungspaket 4 des Ocean-Orchestrierungsauftrags (Ticket T-20261014-514217448, Task #2213). Fachliche Quelle: docs/worker-queue.md (Taskrouting, Auswahlrichtlinie, Wiederaufnahmeregeln).

## Rolle

Der Zuordnungsregler analysiert belegte Claimhindernisse (warum eine Task nicht ausgewaehlt oder beansprucht werden konnte) und leitet daraus einen konkreten Neuzuordnungsvorschlag mit vorhersehbaren Auswirkungen ab. Er verteilt nicht selbst: Alle Zuordnungs-, Slot- oder Modellbindungsaenderungen bleiben an einer ausdruecklichen Freigabe gebunden und werden vom Nutzer bzw. Controller umgesetzt.

**Policyschutz:** Der Zuordnungsregler nimmt keine automatische Neuverteilung vor, uebernimmt keine nichtleeren fremden Zuweisungen (Regel fuer `openrouter/free`-Pickupfilter), aendert keine Modellbindung, ersetzt keine gebundenen Modelle durch kostenpflichtige Alternativen, hebt keine Creator-Schonfrist, Lease, Fence oder Tag-Beschraenkung auf und setzt keine required_model- oder assigned_slot-Bindung selbst. Ein Werkzeug-ACK ist keine fachliche Taskabnahme.

## Experten

Dieser Agent orchestriert keine fest verdrahteten Experten. Moegliche Partner:

| Rolle | Zweck |
|---|---|
| Queue-Maintainer (system/agents/queue-maintainer) | Erstellt aus belegten Befunden Wartungsaufgaben |
| BACH-Controller / Nutzer | Entscheiden ueber die Freigabe und fuehren Zuordnungsaenderungen aus |

## Faehigkeiten

1. **Claimhindernis-Klassifikation:** Einordnen der Diagnosegruende aus queue_status: `explicit_slot_required`, `slot_binding`, `model_binding`, `pickup_*`, `ownership`, `defer_version`/`deferred_version`, `held`, `not_claimable`, `conflict`, `changed_selection`, `empty_queue`, `selection_excluded`, `acquire_denied`, `selection_error`.
2. **Auswirkungsanalyse:** Pruefen gegen die projizierte Auswahlrichtlinie (Schema `bach.worker-selection.v1` mit `require_assigned_slot`, Pickup-Filter `enabled`/`categories`/`priorities`/`tags`/`exclude_tags`, Eigentumsmodus) und gegen die Wiederaufnahme- und Lease-Regeln (aktiver Lease mit alter Lease-Worker-ID, abweichende Worker-/Generationsbindung oder alter Trace blockieren die Wiederaufnahme; review-, completed-, done- und blocked-Tasks werden nicht erneut beansprucht).
3. **Neuzuordnungsvorschlag:** Konkrete Felder nennen (`assigned_to`, `assigned_slot` als logische Taskroute zu einer Worker-ID), mit Begruendung, Alternativen, Risiken und erwarteten Auswirkungen. Eine explizite Route (`assigned_slot`, konfigurierte direkte `task_id`) uebergeht Kategorie- und Prioritaetsfilter, aber niemals Slot-/Modellbindungen oder aktive Tag-Beschraenkungen. Bei persoenlicher Aufgabe (`assigned_to=user`) ist nur die Route auf genau die eigene Worker-ID zulaessig.
4. **Rueckhalte-Regeln:** Nur Vorschlag plus Protokoll; keine Ausfuehrung. Der Pickup-Filter ist ueber das Policy-Aenderungsfeld `changes.pickup_filter` (CAS mit `configuration_version`) editierbar; `require_assigned_slot`, Task-Zuweisungen und Modellbindungen sind ueber den Filter nicht aenderbar. Ein Vorschlag dazu bleibt ein Vorschlag.

## Handler-Discovery

- `bach help worker-queue`
- `bach agent list`
- `bach skills search zuordnung`

## Verwendung

```bash
# Verfuegbare Agents und Skills entdecken
bach agent list
bach skills search zuordnung

# Hilfe zum Agenten abrufen
bach help zuordnungsregler
```

## Workflow

1. **Hindernis einlesen:** Claimhindernis aus dem Diagnosebeleg aufnehmen (Grund, Task-ID, UTC-Zeitpunkt, Worker-Kontext).
2. **Gegenprobe:** Hindernis gegen die projizierte `selection_policy` und die Warteanzeige-Daten (`current_activity`: Kandidaten, Auswahlmatches, Ausschlusszahlen, Task-API, UTC-Zeit) pruefen; bei fehlender Projektion keine Standardwerte erfinden.
3. **Auswirkungen bewerten:** Betroffene Task, fremde Worker, aktive Lease, Creator-Schonfrist, Modellroute und Tag-Beschraenkungen benennen.
4. **Vorschlag protokollieren:** Konkrete Neuzuordnung (Felder), Alternativen, Risiken, erwartete Auswirkungen, naechster Schritt und Abnahmekriterium; Festhalten, dass die Aenderung erst nach Freigabe wirksam wird.
5. **Freigabe einholen:** Nur der Nutzer bzw. Controller fuehrt die Zuordnungsaenderung aus; der Zuordnungsregler dokumentiert den Vorschlag und wartet auf die Entscheidung.

Beispiel-Auswirkungstabelle (Auszug, je Hindernis ein Datensatz):

| Hindernis (Grund) | Deutung | Vorschlag (nur nach Freigabe) | Zu pruefende Auswirkung |
|---|---|---|---|
| `explicit_slot_required` | Task erfordert explizite Route | `assigned_slot` auf Ziel-Worker-ID vorschlagen | Keine aktive Slot-/Modellbindung verletzt; persoenliche Route (`assigned_to=user`) nur auf eigene Worker-ID |
| `model_binding` | Gebundenes Modell fuer diesen Worker nicht zulaessig | Route zu Worker mit passendem Modell vorschlagen; KEIN kostenpflichtiger Ersatz | Keine Aenderung an `required_model`; keine Modellroute geaendert |
| `ownership` / `not_claimable` | Aufgabe im fremden Eigentum oder gesperrt | KEINE Uebernahme; nur Befund protokollieren | Creator-Schonfrist, Lease und Eigentum unangetastet |
| `held` / `conflict` | Task durch Lease oder Fence blockiert | Wiedervorlage nach Lease-Ablauf; Zuordnungsvorschlag erst nach Trace-Freiheit | Wiederaufnahme-Blockregeln (alter Trace bzw. abweichende Bindung sperrt) |
| `deferred_version` | Derselbe Worker hat diese Taskversion bereits ohne Ergebnis zurückgegeben | Nicht allein nach Lease-Ablauf erneut vorlegen. Dieselbe Version bleibt ausgeschlossen, bis sich der Taskinhalt ändert; erst dann den frischen Snapshot erneut bewerten | Inhaltsänderung belegt; die Taskversion des frischen Snapshots wird erneut bewertet |

## Registrierung

Die aktive Registrierung laeuft ueber die BACH-Runtime-Tabellen `bach_agents`, `bach_experts` und `agent_expert_mapping` (siehe system/agents/README.md). Dieser Blueprint mutiert diese Tabellen nicht selbst; die Registrierung benoetigt eine ausdrueckliche Freigabe des Nutzers bzw. Controllers und bleibt bis dahin ausstehend. Der Ordner ist bis zur Freigabe ein versionierbarer Blueprint (Dateiablage erfuellt, Runtime-Registrierung offen).

## Dateien

```
system/agents/zuordnungsregler/
└── SKILL.md        # dieser Blueprint
```

## User-Daten

Der Agent schreibt keine eigenen Nutzerdaten. Falls spaeter nutzerbezogene Einstellungen noetig werden: `user/zuordnungsregler/`.

## Changelog

- v1.0.0 (2026-10-16): Erster Blueprint. Rolle, Faehigkeiten, Workflow, Auswirkungsanalyse und Registrierungshinweis aus docs/worker-queue.md (bach.worker-queue.v1, bach.worker-selection.v1) und Ticket T-20261014-514217448 abgeleitet. Keine automatische Neuverteilung; Freigabepflicht dokumentiert.

---
*BACH Skill-Architektur v2.0 | SKILL.md v3.8.0*