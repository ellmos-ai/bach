# Gepinnte Governance-Referenzen und Laufbindung (v1)

Stand: 2026-10-11, GithubBot-OCEAN P05 Schritt 3b + 3c (Mac-BACH #2060).
Code: `system/hub/_services/governance_binding.py`. Tests: `system/tests/test_governance_binding.py`.

## Zweck und Grenzen

Ein Blueprint kann Policy-, Rule- und Decision-Einträge der `policy-registry` mit Version und
Hash referenzieren und von einer anderen Vorlage erben. BACH löst diesen Satz bei Save,
Materialize und jedem Lauf serverseitig auf und hält ihn im Laufbeleg fest. Es gibt keine
zweite normative Registry: Normen bleiben in `policy-registry` und werden nur über den
vorhandenen Adapter `policy_registry_adapter.observe()` gelesen. BACH speichert lediglich
Pins `(id, version, sha256)`. Durchgesetzt werden weiterhin nur die Werkzeugfreigaben; die
Normtexte selbst setzt BACH nicht um (`enforcement_verified` bleibt `false`).

Nicht Teil dieses Schritts: Modell-Fallback-Kette (3d, mit P06), GUI-Picker für
`policy_refs`, Ocean-Adapter.

## Blueprint-Felder (in `governance`, additiv)

```json
{"policy_refs": [{"registry": "policy-registry", "id": "P-001", "version": "2026-07-26",
                  "sha256": "<64 hex>", "role": "agent"}],
 "inherits_from": {"blueprint_id": 12, "version": 3, "sha256": "<64 hex>"}}
```

| Feld | Regel |
|---|---|
| `policy_refs[]` | genau die fünf Felder; `registry` = `policy-registry`; `sha256` = 64 Kleinbuchstaben-hex; höchstens 64 Einträge, IDs eindeutig; `null` = keine |
| `role` | `role` oder `agent`. `global` ist dem Host vorbehalten (`policy_ref_role_invalid`) |
| `inherits_from` | Elternzeile mit ganzzahliger `blueprint_id` und `version` sowie `sha256` = `content_sha256` der Elternzeile |
| `pin_log` | serverseitig gepflegt, siehe Migration; ein vom Client gesendeter Wert wird verworfen |

`GET /api/agent-studio/blueprints` liefert je Zeile `content_sha256` als Pin-Wert. Er wird über
das kanonische JSON von `kind, persona_role, persona_prompt, animus_type, modus, skills,
contractus, governance` gebildet, ohne `pin_log`.

## Auflösung einer Referenz

Der Adapter liefert die Registry-Projektion. `verify()` hat dabei jede lokale Quelle gegen
ihren deklarierten Hash geprüft. Eine Referenz löst nur exakt auf:

| Prüfung | Fehlercode |
|---|---|
| ID fehlt in der Registry | `policy_ref_unknown` |
| Registry führt eine andere Version | `policy_ref_stale` |
| gleiche Version, anderer deklarierter sha256 | `policy_ref_hash_mismatch` |
| Quelle nicht verifiziert (`hash-mismatch`, `missing`, `unreadable`, `remote-unchecked`, ohne Hash) | `policy_ref_unverified` |
| kein `policy`/`rule`/`decision`, nicht `adopted` oder Status nicht `active`/`superseded` | `policy_ref_not_binding` |
| Provider nicht konfiguriert oder Herkunft falsch | `policy_provider_unavailable` |
| Registry änderte sich während des Lesens | `policy_registry_changed` |

`superseded` bleibt gepinnt gültig: Eine neuere Norm ändert den Agenten nicht still. Pins auf
Remote-Pointer lassen sich nicht verifizieren und werden deshalb geschlossen abgewiesen.
Formfehler führen zu `policy_ref_invalid`, `inherits_from_invalid` oder `governance_invalid`.

## Schichten und globaler Mindestvertrag

Die Reihenfolge ist: global (Host) → Elternvorlagen (nächste zuerst) → eigener Blueprint.
Untere Schichten ergänzen nur.

- **Globaler Mindestvertrag:** `BACH_GOVERNANCE_GLOBAL_FILE`, Standard
  `<BACH_LOCAL_DIR>/governance_global.json` (hostlokal, nicht im Repo):
  `{"schema": "bach.governance-global.v1", "policy_refs": [... role "global"], "forbidden_tools": ["<Werkzeug>"]}`.
  Fehlt die Datei, verbietet er nichts zusätzlich. Ist sie ungültig, folgt
  `governance_global_invalid`. Die globalen Refs zeigen in die Registry; sie sind die
  Übernahmeliste des Hosts, keine zweite Registry.
- Die Datei wird nur serverseitig gelesen. Keine Route schreibt sie oder gibt sie aus; nach
  außen erscheinen nur die globalen Pins in `refs` und ihr Inhalt über `effective_sha256`.
- `forbidden_tools` ist Durchsetzungskonfiguration, keine Norm. Jedes Verbot soll über
  `policy_refs` (Rolle `global`) auf die Policy in der Registry zeigen, die es begründet.
  Eine Prüfung dieser Zuordnung gibt es in v1 noch nicht.
- Eine Schicht, die eine globale ID mit anderem Pin referenziert oder ein global verbotenes
  Werkzeug freigibt (Whitelist samt Aliasen, ohne Whitelist der Standardsatz), wird mit
  `governance_global_violation` abgewiesen. Das gilt auch, wenn ein Steckplatz später über die
  Kernfelder ein verbotenes Werkzeug erhält: Der nächste Lauf wird abgewiesen.
- Eine Kindvorlage darf den Pin einer Elternvorlage nicht ersetzen (`policy_ref_override`).
  Werkzeuge werden mit jeder Eltern-Whitelist geschnitten. `read_only_research` in einer
  Schicht hält den Agenten im sicheren Modus.
- Vererbung: Die Elternzeile muss existieren (`inherits_from_unknown`), dieselbe Version
  (`inherits_from_stale`) und denselben Inhaltshash (`inherits_from_hash_mismatch`) haben.
  Die Kette ist höchstens 8 tief (`inherits_from_too_deep`) und zyklenfrei
  (`inherits_from_cycle`).

## Bindung und effective_sha256

Bei Materialize wird die Bindung serverseitig im Steckplatz gespeichert. `governance_binding`,
`blueprint_id` und `blueprint_version` setzt nur `materialize_system_blueprint`. Kein
Slot-Editor und keine API ändert oder entfernt sie: Der Kerneditor kennt die Felder nicht, und
`update_slot` (auch `POST /api/slots`) weist sie ab. Andere Slot-Edits lassen die Bindung
unverändert.

```json
{"schema": "bach.governance-binding.v1", "refs": [...], "inherits": [...],
 "global": {"policy_refs": [...], "forbidden_tools": [...]}, "profile": "...", "tool_whitelist": [...],
 "legacy": false, "effective_sha256": "<64 hex>"}
```

`refs` enthält alle Schichten mit Rolle, sortiert nach (global, role, agent) und ID.
`global` ist der Inhalt des geladenen globalen Vertrags (sortiert); er fließt damit kanonisch in
`effective_sha256` ein, und der Beleg bindet die globale Schicht mit. **Hashregel:**
`effective_sha256` = sha256 über das kanonische JSON aller übrigen Felder der Bindung
(`sort_keys=True`, Trenner `,`/`:`, `ensure_ascii=False`, UTF-8). Es ist dieselbe Regel wie
beim Provider-sha256 der Systemvorlagen. Der Wert lässt sich also aus der gespeicherten
Bindung nachrechnen. Ein Blueprint ohne `policy_refs` und ohne `inherits_from` ist
`legacy: true`. Für ihn gelten der globale Mindestvertrag sowie `profile` und
`tool_whitelist` wie bisher; eine Registry braucht er nur, wenn der Host globale Refs pinnt.

## Prüfzeitpunkte

- **Save:** Die Auflösung läuft vor der Schreibsperre; bei einer Abweisung wird nichts
  gespeichert. Die Agent-Studio-Routen (Save, Materialize, Start) antworten auf eine Abweisung
  mit HTTP 400, `detail` ist der Fehlercode.
- **Materialize:** Die Auflösung läuft vor der Schreibsperre. Der folgende Versions-CAS
  erkennt einen Save, der dazwischen kam.
- **Jeder Lauf:** Der Policy-Reader des Controllers (`_execution_slot_reader().read()`) prüft die
  gespeicherte Bindung erneut. Er tut das neben der Prüfung der `skill_refs` und auf demselben
  Ablehnungsweg; das gilt auch für Starts über `/api/workers/run` ohne Agent-Studio. Die Pins
  müssen noch exakt auflösen, die Bindung muss sich nachrechnen lassen
  (`governance_binding_invalid` bei Manipulation), und der globale Vertrag muss unverändert
  sein (`governance_global_changed`). Bei der Admission folgt wie bei geänderten Skills HTTP 503
  mit `error_code: admission_unconfirmed`; es entsteht kein Assignment und kein Worker-Thread.
  Der Agent-Studio-Start prüft vorher selbst (HTTP 400 mit Fehlercode) und zusätzlich die
  Vererbungskette gegen die Datenbank.
- Steckplätze, die vor 3b materialisiert wurden, haben keine Bindung. Sie laufen als legacy
  weiter; global verbotene Werkzeuge werden auch für sie abgewiesen.

Die Registry wird nur gelesen, wenn Refs vorhanden sind. Dabei prüft `verify()` alle lokalen
Quellen. Deshalb prüft die erste Lesung eines Readers (die Admission) immer; weitere Lesungen
desselben Laufs prüfen höchstens alle `RUN_RECHECK_SECONDS` (60 s). Änderungen an der Bindung
oder den Werkzeugen im Steckplatz erkennt der vorhandene Policy-Snapshot bei jeder Lesung.

## Migration (kein stiller Wechsel)

Löst ein Pin nicht mehr auf, bleibt der Agent gesperrt, bis er explizit migriert wird:
(1) Save mit den neuen Pins und `expected_version` (CAS), (2) erneutes Materialize, das einen
terminalen Zustand verlangt. Ändert ein Save `policy_refs` oder `inherits_from`, hängt der
Server an `governance.pin_log` an: `{at, blueprint_version, changed: [IDs | "inherits_from"],
pins_sha256}`. Das Log ist append-only und auf 100 Einträge begrenzt.

## Laufbeleg (3c): `bach.worker-execution.v1`, additiv

Ab der Admission enthält jeder Beleg:

```json
{"governance_binding": {"effective_sha256": "<64 hex | null>", "refs": [...], "legacy": true},
 "model_binding": {"chain_index": 0, "backend": "<Slot-Backend>", "model": "<Slot-Modell>",
                   "switch_reason": null}}
```

Ein Worker ohne Bindung, also dynamische oder Kern-Worker sowie Steckplätze aus der Zeit vor
3b, meldet `effective_sha256: null, refs: [], legacy: true`. `model_binding` nennt bis zur
Fallback-Kette (3d/P06) immer Glied 0 mit Backend und Modell des Steckplatzes.

Consumer-Prüfung: `blueprint-studio.mjs` (`correlatedStart`), `native_sequences.py`,
`tray_worker_execution.py`, `blueprint_service.start_blueprint_worker` und
`worker_status_adapter` prüfen nur bekannte Felder und dulden zusätzliche. Die Projektion in
`worker_status_adapter.dispatch_blueprint_worker` reicht die beiden Felder an den
Agent-Studio-Start durch.
