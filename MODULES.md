# MODULES.md — Geteilte Module und ihre Grenzen

Diese Datei beschreibt die module-orientierte Struktur des Repos, die
Ownership jedes Moduls und die Integrationspunkte zu BACH. Sie gilt
ersatzweise für alle Module unter `.MODULES/` und den zugehörigen
Adapter-Code unter `system/hub/_services/`.

---

## 1. Moduldefinition: agents-heart

**Pfad:** `.MODULES/.CONTROL/agents-heart/` · **Version:** v0.1.0

agents-heart ist die provider- und produktneutrale
Besetzungs-/Autorisierungsgrenze für Task-Ausführungen. Das Modul
entscheidet weder Modelle noch Backends und kennt keine BACH-spezifische
Persistenz. Es leistet exakt drei Dinge:

1. **Autorisierung fail-closed:** Vor dem Start einer Ausführung wird der
   versionierte Rollenvertrag geprüft. Kein Vertrag, unbekannter Modus oder
   fehlende Rechte → `AssignmentDenied`. Es gibt keinen offenen Default.
2. **Besetzung mit Identität:** Jede Task-Ausführung erhält ein
   unveränderliches `Assignment` mit `assignment_id` (UUID) und vollständiger
   Korrelationsidentität (Rolle, Agent, Backend, Modell, Slot, Task, Session,
   Initiator).
3. **Korrelierte Ereignisse:** Start und Ende einer Besetzung werden als
   Ereignis-Dicts (`assignment.started` / `assignment.ended`) an einen
   injizierten `event_recorder` übergeben. Das Modul schreibt selbst nirgendwo
   hin — BACH mappt die Ereignisse im Adapter auf `record_activity`.

## 2. Kernkomponenten (alle im Modul exportiert)

| Komponente | Beschreibung |
|---|---|
| `RoleContract` | `@dataclass(frozen=True)`: `role_id`, `revision`, `rights: frozenset[str]`. Minimaler, versionierter Rechtevertrag pro Ausführungspfad. |
| `ROLE_CONTRACTS` | Mapping mit 4 Rollen: `hintergrund_worker`, `task_worker`, `boss_routing`, `expert_role`. Alle mit `revision="v1"` und `rights=frozenset({"task.claim", "task.execute"})`. |
| `_REQUIRED_RIGHTS` | `frozenset({"task.claim", "task.execute"})` — die Mindestrechte für Task-Ausführung; `authorize_role` prüft sie per `issubset`. |
| `Assignment` | `@dataclass(frozen=True)`: `assignment_id`, `role_id`, `role_revision`, `agent_instance_id`, `backend_id`, `model_id`, `slot_id`, `task_id: int \| str`, `session_id`, `initiated_by`, `started_at`. Unveränderliche Identität einer einzelnen Besetzung. |
| `AssignmentDenied` | `RuntimeError`-Subklasse; Signal für fehlende/bekannte-aber-unzureichende Rechte oder unbekannten Modus. |
| `authorize_role(role_id, mode)` | Fail-closed: normalisiert `role_id`, lehnt unbekannte Rollen und Modi außer `{"safe", "full"}` ab, prüft `_REQUIRED_RIGHTS.issubset(rights)`. Gibt den Vertrag zurück oder wirft `AssignmentDenied`. |
| `begin_assignment(...)` | Keyword-only; prüft Rolle, erzeugt `assignment_id`, validiert Pflichttextfelder, erzeugt `session_id` (falls nicht geliefert), fällt bei `initiated_by` auf `agent_instance_id` zurück, ruft `event_recorder` mit `assignment.started` auf, gibt `Assignment` zurück. |
| `finish_assignment(...)` | Keyword-only; validiert `status in {"completed", "released", "error", "interrupted"}`, ruft `event_recorder` mit `assignment.ended` (inkl. `ended_at`, `result`, `reason`) auf. |

Status-Werte für `finish_assignment` decken bewusst die produktiven Endzustände
ab: `completed` (erledigt), `released` (abgegeben/unterbrochen), `error`
(fehlgeschlagen), `interrupted` (hart gestoppt).

## 3. Abhängigkeiten und Bindestrick

**Das neutrale Modul hat ausschließlich Python-Stdlib-Abhängigkeiten:**
`uuid`, `dataclasses`, `typing`, `datetime`. Es importiert NICHTS aus BACH.

`record_activity` (BACH-Activity-Log aus `slots_config.py`) ist
**ausschließlich Implementierungsdetail des BACH-Adapters**
`system/hub/_services/agents_heart.py`. Der Adapter lädt das neutrale Modul
per `importlib` vom Standardpfad
`.MODULES/.CONTROL/agents-heart/agents_heart.py` (überschreibbar über die
Umgebungsvariable `BACH_AGENTS_HEART_MODULE`), re-exportiert die
öffentlichen Symbole und injiziert als `event_recorder` eine Closure, die
`assignment.started` → `record_activity(..., status="running", event="assignment_started")`
und `assignment.ended` → `record_activity(..., event="assignment_ended")`
mappt. Damit bleibt die Persistenzgrenze sauber zwischen dem Modul
(beschreibt Ereignisse) und BACH (speichert sie).

## 4. Trithon-Abgleich

- `assignment_id`/`session_id` aus agents-heart korrelieren mit
  `ExecutionReceipt` und `LedgerEntry` in
  `system/hub/_services/trithon/routing_contract.py`: Der Receipt trägt die
  Besetzungsidentität mit, der Ledger verzeichnet den korrelierten Lauf.
- `system/hub/_services/trithon_dispatch.py` orchestriert die Kette
  **Claim → Besetzung → Noop → Receipt**: Contract-Claim über die
  Task-Master-TaskDB, Besetzung über den BACH-Adapter
  (`begin_assignment`/`finish_assignment`), Ausführung über den
  NoopExecutor, Abschluss über `ExecutionReceipt` und Ledger-Eintrag.
- Die Ereignis-Sequenz des Adapters (`assignment_started` →
  `assignment_ended`) deckt sich zeitlich mit Claim- und Receipt-Schritten;
  die `assignment_id` ist das Korrelationsfeld für den Abgleich.

## 5. Phase-3-Schema-Lücke (dokumentierter Vorbehalt — NICHT implementiert)

Der Trithon-Phasenplan (Phase 3) sieht Felder **capability**, **budget** und
**idempotency** für Ausführungskontrakte vor. Diese sind in der aktuellen
`routing_contract.py` **nicht vorhanden**, und agents-heart v0.1.0
implementiert keine dieser Dimensionen (keine Capability-Verhandlung, kein
Budget-Limit, keine Idempotency-Schlüssel). Dies ist ein bewusst
dokumentierter Vorbehalt: Sobald Phase 3 umgesetzt wird, werden
- die Kontrakt-Felder ergänzt,
- `RoleContract.rights` um capability-Rechte erweitert,
- `Assignment` um Budget-/Idempotency-Felder ergänzt
— jeweils als Versionssprung (v0.2.0) mit kompatibler Migrationsnotiz. Bis
dahin gilt: jede Ausführung über agents-heart ist unbudgetiert und
nicht-idempotent; Absicherung erfolgt über Claim-Sperre (ein Besetzer pro
Task) und Activity-Log.

## 6. Ownership-Matrix

| Bereich | Owner |
|---|---|
| agents-heart (Besetzung/Autorisierung, `.MODULES/.CONTROL/agents-heart`) | BACH/Ocean Shared Modules |
| TaskDB, Lease/Claim, Task-Lebenszyklus | Task-Master (Lead-TaskDB, Trithon-Adapter) |
| Prozesssteuerung (Start/Stop/Neustart von Worker-Prozessen) | agent-launcher |
| LLM-Modelle und Provider-Anbindung | Backend-Module |
| GUI/Tray | Clients |
| Ressourcen-Arbitrierung | Fackel/Compute-Lock |

agents-heart fällt unter Shared Modules und wird von BACH und Ocean über
jeweils eigene, dünne Adapter konsumiert (siehe `MANIFEST.json`, `consumers`).

## 7. Versionierung

- **SemVer**, aktuell **v0.1.0**: Erste abgegrenzte Version; API-Fläche ist
  die exportierte Symbolmenge. Breaking Changes (z. B. Pflichtfelder in
  `Assignment`, neue Modi in `authorize_role`) → Major-Bump v1.0.0;
  additive Ergänzungen (Phase-3-Felder, siehe Abschnitt 5) → Minor-Bump
  v0.2.0.
- **MANIFEST.json** (im Modulordner): `name: agents-heart`, `version: 0.1.0`,
  `license: MIT`, `author: BACH/Ocean Shared Modules`,
  `entry_point: agents_heart.py`,
  `exports: [RoleContract, ROLE_CONTRACTS, Assignment, AssignmentDenied, authorize_role, begin_assignment, finish_assignment]`,
  `dependencies: []` (nur Stdlib), `consumers: BACH (>=1.0, adapter),
  Ocean (>=1.0, adapter)` sowie die `separation_of_concerns`-Matrix aus
  Abschnitt 6. Rollenverträge tragen zusätzlich eine eigene `revision`
  (aktuell `"v1"`) — Vertragsänderungen an einer Rolle sind ein eigener,
  überprüfbarer Sprung.

## 8. Adapter-Migration (BACH-Seite)

- **Aufrufer bleiben unverändert:** `telegram_chat.py` (begin ~3310),
  `worker.py` (~271) und `trithon_dispatch.py` (~283) importieren weiter von
  `hub._services.agents_heart` und rufen `finish_assignment` positional mit
  dem Assignment als erstem Argument; der Adapter hält diese Signatur
  (`finish_assignment(assignment, *, status, result="", reason="", path=None)`).
- **Explizite Aktivierung statt stiller Fallback:** Der Adapter lädt das
  neutrale Modul vom Standardpfad; abweichende Pfade werden nur über
  `BACH_AGENTS_HEART_MODULE` wirksam (Muster analog zum
  policy-registry-Transfer aus dem OCEAN-TRANSFER-PLAN: schmaler Adapter,
  überprüfbarer Pin, klare Aktivierungsoption).
- **Neue Parameter des neutralen Moduls** (`session_id`, `initiated_by` in
  `begin_assignment`) sind optional; der Adapter reicht sie immer durch.
  Fehlen sie, erzeugt das Modul eine Session-ID bzw. fällt auf die
  Instanz-ID zurück — bestehende Aufrufer ohne diese Felder funktionieren
  unverändert.

## 9. Rollback

Der Adapter `system/hub/_services/agents_heart.py` ersetzt das bisherige
eigenständige BACH-Modul an derselben Stelle. Ein Rollback ist damit
minimal-invasiv:

```
git checkout HEAD -- system/hub/_services/agents_heart.py
```

stellt das eigenständige BACH-Original wieder her; alle Aufrufer sind danach
wieder gegen die ursprüngliche Implementierung gebunden. Das neutrale Modul
unter `.MODULES/.CONTROL/agents-heart/` ist rein additiv und kann
unabhängig davon verbleiben (es wird ohne Adapter nicht geladen).

## 10. Nachweisführung

- **Runtime-Nachweis:** `record_activity`-Einträge im Activity-Log je
  Besetzung mit `event: assignment_started` (status `running`) bzw.
  `event: assignment_ended` und der gemeinsamen `assignment_id` sowie
  Rolle, Instanz, Backend, Modell, Slot, Task-ID, Session und Initiator.
  Getestet in `system/tests/test_agents_heart.py` (u. a. zwei korrelierte
  Einträge mit identischer `assignment_id` und `started_at`).
- **Schema-/No-op-Nachweis:** Trithon-Seite — `NoopExecutor` und
  `ExecutionReceipt` in `trithon_dispatch.py`/`routing_contract.py` zeigen
  die Claim→Besetzung→Ausführung→Receipt-Kette mit derselben
  Korrelationsidentität.