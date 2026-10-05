# TaskDB Salt-Lease-Vertrag v1 (T793 / BACH-Task #1720)

**Status:** Vertragsentwurf v1. Spezifikation, keine Implementierung.
**Stand:** 2026-10-05. Grundlage ist der Quellstand `origin/main` 950f59af.
**Bezug:** BACH-Task #1720 (LEASE 1/4). Darauf bauen #1721 (Lead-Dienst), #1722 (Clients/Trithon) und #1723 (Mehrhost-Abnahme) auf. Sammelaufgabe ist #1696 mit der Entscheidung D5-USER-ACCEPTED-2026-10-04. Das zugehörige Ticket ist T-20261003-793817309.
**Autor:** agy-opus@ASUS-GEI, Claim über die Lead-TaskDB.

> Die Endpunkte und Felder in Abschnitt 4–6 sind **vorgeschlagen**. Sie existieren im Live-Lead derzeit **nicht**. Wer sie verwendet oder als vorhanden meldet, bevor #1721 abgenommen ist, verletzt diesen Vertrag.

---

## 1. Zweck und Geltungsbereich

Dieser Vertrag legt fest, wie eine ausführbare Übernahme einer gemeinsamen BACH/Ocean-Softwareaufgabe als **befristeter, gefencter Lease** in der kanonischen TaskDB des Leads vergeben, gelesen, verlängert und zurückgegeben wird. Er setzt D5 um:

- Der Mac Studio ist der feste Lead. Seine TaskDB ist Verteilungs- und Claim-Autorität (GUX-005). Es gibt keinen eigenen Lead pro Aufgabe.
- Jede Übernahme bekommt genau einen Lease mit gemeinsamer `issued_at`/`expires_at` und einem Fencing-Wert.
- TTL-Profile richten sich nach der Taskgröße.
- Offline darf ein Worker nur bis zum bekannten Ablauf weiterarbeiten. Neue Claims und Verlängerungen setzen Kontakt zum Lead voraus.
- Der Ersteller hat nur einen **befristeten** Erstzugriffsvorrang. Er erhält nie einen parallelen Lease.
- Release/Return beendet die lokale Arbeit. Ein Ergebnis darf gepuffert und später zugestellt werden.
- Die TaskDB-Task-ID ist die stabile Identität. Der Ticket-Hash dient nur als Provenienz, zur Deduplizierung und als Bezug für das Claim-Salt.

Nicht Teil dieses Vertrags sind Ressourcen-Locks (lock-salt, `LOCK.*`-Dateien, lock-master) und die Worker-Ausführung (#1697).

## 2. Ist-Befund (belegt am Quellstand, Zeilennummern `origin/main`)

| Mechanismus | Ort | Eigenschaften | Was fehlt |
|---|---|---|---|
| **BACH-Alt-Claim** („30-Minuten-Claim“) | `system/hub/task_audit.py` `claim_task_atomic` L280, `release_claim` L341, `reap_stale_in_progress_tasks` L381 | Atomares bedingtes UPDATE auf `status/claimed_by/claimed_at`, Frist 1800 s. Spalten werden zur Laufzeit von `ensure_task_claim_columns` angelegt (`system/hub/_services/task_schema.py`). | Lease-ID, Fencing, Host, Renew. `claimed_at` ist lokale Zeit ohne Zone. Der Reaper setzt `pending` ohne Owner-Prüfung. Er läuft nur manuell (`bach task reap`, `bach_api.task.reap`). |
| **GUI/Tray-Claimpfad** | `system/gui/server.py` PUT `/api/tasks/{id}` (`is_new_claim` L2259) | `status=in_progress` + `changed_by` ruft `claim_task_atomic` auf. Bei Konflikt kommt `{"status":"claim_failed"}` mit HTTP 200 zurück. | Andere Statuswechsel (z. B. `done`) laufen ohne Owner-Prüfung durch. |
| **Headless-API** | `system/gui/api/headless.py` PUT `/api/v1/tasks/{id}` L307 | Nutzt nur `apply_task_field_changes` | Kein atomarer Claim |
| **Roshambo-Lease-Adapter (importiert)** | `system/imported_capabilities/category_1_solved_wanted/leases/adapter_bach.py` (`try_claim_task_atomic`, `renew_task_lease`, `release_task_lease`) | SQLite, Spalten `claim_id` (UUIDv4), `claimed_by`, `claim_expires_at`, `claim_heartbeat_at`, `claim_host`. `BEGIN IMMEDIATE`, UTC-Prüfung, Renew und Release nur mit gültiger `claim_id`. Review: `docs/REVIEW-T797-LEASE-FOLLOWUP-20260930.md` | **Kein Runtime-Caller, keine Migration.** Kein monotones Fencing. Kein Ersteller-Vorrang. Kein TTL-Profil. |
| **Roshambo-Original** | Repo `roshambo`, `src/roshambo/leases.py` (`acquire`, `heartbeat`, `release`, `who_has`), `schema/001_init.sql` Tabelle `claims` | CockroachDB/psycopg, PK `(swarm_id, resource)` als Mutex, Server-`now()`, `claim_id` als Bearer-Capability, Audit-Log. CLI und MCP (stdio). | HTTP-Schreib-API, Auth, Fencing-Epoch, TTL-Profile, Reaper, Idempotenzschlüssel. Auf `main` leakt `who_has` die `claim_id`; behoben erst im ungemergten Branch `codex/lease-view-renew-20261003`. |
| **Trithon-Host-Fencing** | `system/hub/_services/trithon/fencing.py` (`register_node` L130, `claim_lead` L222, Token-Hash L219) | Hostlokales Filelock und monotoner `term` pro Node. Token = `sha256(salt:node_id:term)`. Der Modulheader sagt ausdrücklich: kein verteilter Lease. | Gilt nur hostlokal und hat keinen Taskbezug |
| **Trithon-Dispatch** | `system/hub/_services/trithon_dispatch.py` `execute_intent_v1` L173 | Ruft `claim_task_atomic` auf (L229) und dann den `NoopExecutor` (L84). Danach `UPDATE … status='done'` **ohne Claim-Prüfung** (L297). | Fencing beim Abschluss |
| **Trithon-JSONL-`claim_contract`** | `system/hub/_services/trithon/routing_contract.py` | Ledger-Einträge pending/claimed/done/blocked | TTL, Heartbeat, Dateisperre |
| **Rheingold-Worker** | `system/hub/rheingold.py` `pull_tasks_from_rheingold` L287 | Spiegelt Lead-Tasks in die lokale Datenbank | Claim-Spalten werden nicht gespiegelt. Claims und Status gehen nicht zum Lead zurück (siehe #1694). |

Live-Readback vom 2026-10-05: Die Lead-API (Version 1.1.85, erreicht per SSH-Tunnel von einem lokalen Port auf den Lead-Kandidaten aus `system/hub/rheingold.py`) liefert in Task-Zeilen `claimed_by` und `claimed_at`, aber kein `claim_id`, kein `claim_expires_at` und kein Fencing.

## 3. Entscheidung: Wie passt Roshambo?

**Roshambo wird als Vertragsvorbild und Codequelle adaptiert. Als eigenständige Lease-Authority wird es nicht direkt angebunden.**

Begründung:

1. **Eine Authority:** Eine direkte Anbindung bräuchte eine zweite Claim-Datenbank (CockroachDB, Tabelle `claims`) neben der Lead-TaskDB. Das verbieten #1720 Punkt 3 und GUX-005/072. Die Lease-Daten liegen daher als Spalten in `tasks` der Lead-TaskDB. Das entspricht dem Ansatz von `adapter_bach.py`.
2. **Kein Cloud-Zwang:** Roshambo setzt einen erreichbaren CockroachDB-Cluster und einen DSN auf jedem Client voraus. Ein lokales Backend steht nur auf der Roadmap (`docs/ROADMAP-LOCAL-DB.md`).
3. **Lücken:** Roshambo fehlen Fencing-Epoch, Auth, TTL-Profile und Idempotenz. Diese Lücken müssten ohnehin auf BACH-Seite geschlossen werden.

Übernommen werden aus Roshambo:

- **Leasesemantik:** Ein Halter pro Ressource. Ablauf und Übernahme werden atomar in einem Statement entschieden.
- **Serverzeit:** Die Zeit bestimmt allein der Server.
- **Ablehnung als Ergebnis:** Eine Ablehnung ist ein Ergebnis mit Halter und Intent, kein Fehler.
- **Renew:** Eine Verlängerung verkürzt nie (`GREATEST`) und gelingt nur bei lebendem Lease.
- **Release:** Freigabe nur per Capability.
- **Audit:** Jede Lease-Aktion schreibt eine Audit-Zeile.
- **Holder-Ansicht ohne `claim_id`:** wie im Branch `codex/lease-view-renew-20261003`.

Technisch ist der Ausgangspunkt `adapter_bach.py`. #1721 erweitert ihn um Fencing, Profile, Ersteller-Vorrang und Idempotenz.

## 4. Datenmodell (Lead-TaskDB, Tabelle `tasks`)

| Feld (API) | Spalte | Typ | Gesetzt von | Bedeutung |
|---|---|---|---|---|
| `task_id` | `id` | int | – | Stabile Identität. Die einzige Lease-Ressource. |
| `lease_id` | `claim_id` | UUIDv4-Text | Lead | Lease-Capability. Wird nur an den Halter ausgegeben und nie in Listen oder Holder-Ansichten gezeigt. |
| `worker_id` | `claimed_by` | Text | Client (validiert) | Format `<agent>@<host>`, z. B. `agy-opus@ASUS-GEI`. |
| `host` | `claim_host` | Text | Client (validiert) | Hostname des ausführenden Systems |
| `issued_at` | `claim_issued_at` **(neu)** | UTC ISO-8601 | Lead | Zeitpunkt des Acquire |
| `expires_at` | `claim_expires_at` | UTC ISO-8601 | Lead | Hartes Fristende |
| `heartbeat_at` | `claim_heartbeat_at` | UTC ISO-8601 | Lead | Letzte Verlängerung |
| `fence` | `claim_fence` **(neu)** | int, monoton | Lead | Steigt bei **jedem** erfolgreichen Acquire um 1, auch bei Übernahme nach Ablauf. Sinkt nie. |
| `ttl_profile` | `claim_ttl_profile` **(neu)** | `S`/`M`/`L`/`XL` | Lead | Gewähltes Profil (Abschnitt 6) |
| `salt_ref` | `claim_salt_ref` **(neu)** | Text, optional | Lead | Claim-Salt-Bezug (Abschnitt 7) |
| `claimed_at` | `claimed_at` | Text | Lead | **Kompatibilitätsfeld.** Wird bei Acquire auf `issued_at` gesetzt. |

Fencing-Regel: Jede schreibende Taskoperation eines Workers (Statuswechsel, Abschluss, Ergebnis, Receipt) muss `lease_id` **und** `fence` mitschicken. Der Lead akzeptiert sie nur, wenn beide Werte zum aktuellen Lease passen und `now() < expires_at` gilt. Andernfalls antwortet er mit `409 stale_fence`. Ein monotoner Integer ist nötig, weil die UUID `claim_id` nicht geordnet ist und Downstream-Systeme (Trithon-Receipts, Ergebnispuffer) „älter als“ prüfen können müssen.

## 5. Operationen (vorgeschlagene Lead-HTTP-API)

Alle Antworten enthalten `server_now`, die UTC-Zeit des Leads. Clients rechnen Fristen immer relativ zu `server_now`, nie zur eigenen Uhr. Alle Schreiboperationen erfordern die Geräteanmeldung des Leads (`docs/architecture/DEVICE-AUTH-STRATEGIE.md`). Eine Ablehnung wird als HTTP 200/409 mit Ergebnisobjekt gemeldet, nicht als 5xx.

### 5.1 Acquire

`POST /api/tasks/{task_id}/lease`

```json
{
  "worker_id": "agy-opus@ASUS-GEI",
  "host": "ASUS-GEI",
  "ttl_profile": "M",
  "intent": "Spezifikation LEASE 1/4 schreiben",
  "request_id": "6f1c0c1e-2a8e-4c55-9b0f-0d7c3f5e7a10"
}
```

ACK, wenn der Lease gewährt wird (HTTP 200):

```json
{
  "granted": true,
  "task_id": 1720,
  "lease_id": "3b2f9a64-8d1e-4b7a-9f3c-1a2b3c4d5e6f",
  "fence": 7,
  "worker_id": "agy-opus@ASUS-GEI",
  "host": "ASUS-GEI",
  "issued_at": "2026-10-05T00:10:00.000000Z",
  "expires_at": "2026-10-05T00:40:00.000000Z",
  "ttl_profile": "M",
  "server_now": "2026-10-05T00:10:00.000000Z"
}
```

Ablehnung (HTTP 409). Die Antwort enthält keine `lease_id` des Halters:

```json
{
  "granted": false,
  "task_id": 1720,
  "reason": "held",
  "holder": {"worker_id": "codex@WORKSTATION-LG", "host": "WORKSTATION-LG",
             "intent": "…", "expires_at": "2026-10-05T00:35:12.000000Z"},
  "server_now": "2026-10-05T00:10:00.000000Z"
}
```

Semantik:

- Der Lead prüft alles in **einem** bedingten UPDATE unter `BEGIN IMMEDIATE`:
  - Der Status ist in `pending`/`open`.
  - Die Abhängigkeiten sind erfüllt.
  - Es gibt keinen lebenden Lease (neu oder alt, siehe Abschnitt 9).
  - Ein laufendes Ersteller-Vorrangfenster steht nicht entgegen.
- Erfolg setzt `status='in_progress'`, `claim_fence = claim_fence + 1` und alle Lease-Felder. Außerdem schreibt der Lead `task_history` und eine Audit-Zeile.
- **Idempotenz:** Wiederholt derselbe `worker_id` den Aufruf mit demselben `request_id` bei lebendem Lease, liefert der Lead denselben ACK erneut, mit derselben `lease_id` und demselben `fence`. Das löst den Fall „Antwort verloren“, den Roshambo nicht abdeckt. Ein anderer `request_id` desselben Workers bei lebendem Lease wird mit `reason: "already_held_by_caller"` abgelehnt und erzeugt keinen zweiten Lease.

### 5.2 Read

`GET /api/tasks/{task_id}/lease` liefert die Holder-Ansicht **ohne** `lease_id`:

```json
{"task_id": 1720, "status": "in_progress", "leased": true, "fence": 7,
 "holder": {"worker_id": "agy-opus@ASUS-GEI", "host": "ASUS-GEI", "intent": "…"},
 "issued_at": "…Z", "expires_at": "…Z", "ttl_profile": "M", "legacy": false,
 "server_now": "…Z"}
```

Der Halter liest seinen eigenen Lease mit Header `X-Lease-Id`. Passt der Wert, kommt zusätzlich `"own": true` zurück.

### 5.3 Renew

`POST /api/tasks/{task_id}/lease/renew` mit `{"lease_id": "…", "fence": 7}`

- Gelingt nur, wenn `lease_id` und `fence` passen und `now() < expires_at` gilt.
- Neue Frist: `expires_at = MAX(expires_at, now() + profile_ttl)`.
- Die Gesamtlaufzeit ist auf `profile_max_total` begrenzt, gerechnet ab `issued_at`.
- Der Fence-Wert bleibt bei Renew **unverändert**.
- Antworten: ACK wie bei 5.1, oder 409 mit `reason` aus `expired`, `stale_fence`, `max_total_reached`.

Ein abgelaufener Lease ist nie verlängerbar. Wer weiterarbeiten will, muss neu acquiren und erhält dabei einen neuen Fence.

### 5.4 Release / Return

`POST /api/tasks/{task_id}/lease/release`

```json
{"lease_id": "…", "fence": 7, "outcome": "done",
 "result_ref": "git:bach@docs/t1720-salt-lease-contract-20261005", "note": "…"}
```

`outcome` und der daraus folgende Status:

| `outcome` | Neuer Status | Bedeutung |
|---|---|---|
| `return` | `pending` | Arbeit abgebrochen, Task wieder claimbar |
| `done` | `done` | Akzeptanz erfüllt; Beleg in `result_ref` und `note` |
| `blocked` | `blocked` | Blocker gefunden; Begründung in `note` |

Gilt nur bei passendem `lease_id`/`fence` und lebendem Lease. Danach werden alle Lease-Spalten außer `claim_fence` geleert; `claim_fence` bleibt als Hochwassermarke stehen.

`done` über diesen Pfad ist der **einzige** Weg, wie ein Worker eine geleaste Task abschließt. Ein generisches PUT mit `status` auf eine geleaste Task antwortet `409 lease_required`.

## 6. TTL-Profile

| Profil | TTL je Acquire/Renew | `profile_max_total` | Für |
|---|---|---|---|
| `S` | 15 min | 2 h | Mikro-Fixes, Doku-Korrekturen |
| `M` (Default) | 30 min | 8 h | Normale Mikro-Tasks; entspricht dem bisherigen 1800-s-Claim |
| `L` | 60 min | 24 h | Mehrdateien-Implementierung mit Tests |
| `XL` | 120 min | 72 h | Nur bei Task-Feld `estimated_minutes > 480` oder Operatorfreigabe |

Der Lead entscheidet das Profil. Ein angefragtes größeres Profil kann er herabstufen; die Antwort enthält dann das tatsächlich vergebene. Die Werte sind serverseitig konfigurierbar. Die Tabelle ist der Startwert für #1721.

## 7. Salts: Claim-Salt und Lock-Salt

- **Claim-Salt** koordiniert Task-Claims. Gespeichert wird `claim_salt_ref = sha256("claim-salt:v1:" + ticket_hash)`, und zwar nur, wenn die Task eine Ticket-Provenienz hat (z. B. `source = ticket:T-20261003-793817309:…`). Der Wert dient zur Deduplizierung: Zwei Tasks mit derselben Ticket-Provenienz lassen sich erkennen. Die Lease-Identität ist er **nicht**; Ressource bleibt `task_id`.
- **Lock-Salt** koordiniert Ressourcen-Locks. Dazu gehört auch das Node-Salt in `trithon/fencing.py`. Lock-Salts erscheinen in keinem Feld dieses Vertrags.
- **Keines der beiden Salts gibt Schreibrecht.** Ein gültiger Lease ersetzt weder die Prüfung von `LOCK.user.*`, `LOCK.until.*`, `LOCK.condition.*` und `LOCK.txt` noch die Repo-Regeln. Ist das Ziel gesperrt, muss der Worker trotz Lease mit `outcome: "blocked"` zurückgeben.

## 8. Offline-Arbeit, Ersteller-Vorrang, gepufferte Ergebnisse

1. **Lokale Frist:** Beim ACK berechnet der Client `local_deadline = local_receive_time + (expires_at − server_now) − 60 s`. Die 60 s Sicherheitsabzug decken Laufzeit und Uhrdrift ab.
2. **Offline:** Ohne Lead-Kontakt darf der Client bis `local_deadline` weiterarbeiten. Danach **muss** er die Arbeit stoppen: keine Commits auf gemeinsame Branches, keine Deployments, keine Statusbehauptung.
3. **Puffer:** Ein Ergebnis, das nach dem Stopp oder offline entstanden ist, bleibt lokal als `pending-return` mit `task_id`, `lease_id` und `fence`.
4. **Zustellung:** Bei erneutem Kontakt geht der Puffer per Release an den Lead.
   - Ist der Lease noch lebendig und der Fence aktuell, wird normal angenommen.
   - Sonst antwortet der Lead `409 stale_fence`. Das Ergebnis darf dann nur als **Hinweis** angehängt werden (`task_history`, Aktion `late_result`, ohne Statuswechsel). Für eine Übernahme ist ein neues Acquire nötig.
5. **Neue Claims und Renew** setzen immer Lead-Kontakt voraus. Lokale Projektionen (Rheingold-Pull) vergeben nie Leases.
6. **Ersteller-Vorrang:**
   - Ab `created_at` darf für `first_claim_window = 10 min` nur `created_by` acquiren. Andere erhalten `409 reason: "creator_priority"` mit `until`.
   - Das Fenster gibt es einmal pro Task, es wird nicht verlängert.
   - Es entsteht dabei kein paralleler oder reservierter Lease.

## 9. Fehlerfälle

| Fall | Antwort | Client-Verhalten |
|---|---|---|
| Lease gehalten | 409 `held` + Holder | Andere Task wählen |
| Eigener lebender Lease, neue `request_id` | 409 `already_held_by_caller` | Ursprünglichen ACK verwenden; bei Verlust dieselbe `request_id` wiederholen |
| Ersteller-Fenster aktiv | 409 `creator_priority` + `until` | Warten oder andere Task wählen |
| Status terminal oder `blocked`, Abhängigkeit offen | 409 `not_claimable` + `status`/`blocked_by` | Andere Task wählen |
| Renew/Release nach Ablauf | 409 `expired` | Stoppen, puffern, neu acquiren |
| Fence oder `lease_id` passt nicht | 409 `stale_fence` | Sofort stoppen, kein weiterer Schreibversuch |
| Generischer Status-PUT auf geleaste Task | 409 `lease_required` | Release-Pfad verwenden |
| Fehlende Geräteanmeldung | 401/403 | Abbrechen, nichts lokal als geclaimt markieren |
| Lead nicht erreichbar | Netzwerkfehler | Bestehenden Lease bis `local_deadline` nutzen, sonst nichts beginnen |

## 10. Abgrenzung der drei Mechanismen

- **Roshambo-Lease (dieser Vertrag, adaptiert):** taskbezogener, befristeter, gefencter Lease in der Lead-TaskDB. Er ist die einzige Übernahme-Autorität für gemeinsame BACH/Ocean-Softwaretasks.
- **BACH-Alt-Claim (30 min):** hostlokaler Claim ohne Lease-ID und ohne Fencing. Er bleibt bis zur Migration lesbar und belegt die Task (Abschnitt 11), ist aber **kein** Lease im Sinne von D5.
- **Trithon-Host-Fencing:** schützt die Lead-Rolle eines Nodes **auf einem Host**, über `term` und Token. Es ist kein Task-Lease und kein Mehrhost-Lock. Trithon-Dispatch muss für Taskabschlüsse künftig den Lease-Fence aus Abschnitt 4 verwenden, nicht den Node-Term.

## 11. Migrationspfad für alte `claimed_by`/`claimed_at`-Zeilen

1. **Schema (#1721):** Nur additive Spalten `claim_issued_at`, `claim_fence` (Default 0), `claim_ttl_profile`, `claim_salt_ref`. Die Adapterspalten aus `adapter_bach.py` werden per `ensure_task_lease_schema` angelegt. Keine Daten werden umgeschrieben oder gelöscht.
2. **Legacy-Erkennung:** Eine Zeile mit `status='in_progress'`, gesetztem `claimed_by` und `claim_id IS NULL` gilt als Legacy-Claim.
   - Sie ist lebendig, solange `claimed_at` jünger als 1800 s ist. Die Prüfung erfolgt in UTC, mit derselben Zonenheuristik wie der Reaper (`task_audit.py` L381 ff.).
   - Lebendige Legacy-Claims blockieren Acquire (`held`, `legacy: true`).
   - Abgelaufene Legacy-Claims darf Acquire übernehmen; dabei wird der Fence erhöht.
   - Das schließt die Interop-Lücke des heutigen Adapters: Er kann Zeilen mit `claim_id IS NULL` und `status='in_progress'` nie übernehmen.
3. **Bestehende Pfade umstellen (#1721/#1722):**
   - PUT `/api/tasks/{id}` mit `status=in_progress` ruft intern Acquire mit Profil `M` auf und gibt `lease_id`/`fence` zurück.
   - `bach task claim/release` und `bach_api.task` bekommen Lease-Varianten.
   - Headless PUT (`headless.py` L307) erhält denselben Claim-Pfad.
   - `trithon_dispatch.py` schließt nur mit Fence ab (L297 heute ohne Prüfung).
   - `release_claim` und `reap_stale_in_progress_tasks` leeren auch die Adapterspalten und prüfen den Fence.
4. **Rheingold-Worker:** `pull_tasks_from_rheingold` spiegelt die Lease-Holder-Ansicht nur lesend. Sie darf lokal keinen Claim begründen. Statusänderungen gehen über die Lease-API zum Lead (Überschneidung mit #1694).
5. **Abschaltung des Alt-Claims:** erst nach der Abnahme von #1723. Danach lehnt `claim_task_atomic` auf dem Lead-Store ab und verweist auf Acquire. Historische Zeilen bleiben unverändert.

## 12. Readback-Beispiel (Abnahmeform für #1721–#1723)

```text
1. POST /api/tasks/<synth>/lease  (Worker A, request_id r1) → granted, fence=1, expires_at=E1
2. POST /api/tasks/<synth>/lease  (Worker B)                → 409 held, holder=A
3. GET  /api/tasks/<synth>/lease                            → leased=true, fence=1, keine lease_id
4. POST …/lease/renew (A, fence=1)                          → expires_at ≥ E1, fence=1
5. [Frist ablaufen lassen]  POST …/lease/renew (A)          → 409 expired
6. POST /api/tasks/<synth>/lease  (Worker B)                → granted, fence=2
7. POST …/lease/release (A, fence=1, outcome=done)          → 409 stale_fence; Status unverändert
8. POST …/lease/release (B, fence=2, outcome=return)        → status=pending, claim_fence=2 bleibt
```

Ausschließlich mit synthetischen, isolierten Tasks. Produktive Tasks und Worker werden für Tests weder geclaimt noch gestartet.

## 13. Offene Punkte

- Die Ticketdatei T-20261003-793817309 wurde auf ASUS-GEI gesucht, aber nicht gefunden. `TICKET_MASTER_TICKETS_DIR` ist dort nicht gesetzt, und `.MODULES\.CONTROL\ticket-master\tickets` enthält sie nicht.
- Die Profilwerte (Abschnitt 6) und das Ersteller-Fenster (10 min) sind Startwerte. Sie bedürfen keiner neuen Grundsatzentscheidung, sind aber in #1721 konfigurierbar umzusetzen.
- Ob für die Lease-Endpunkte dieselbe Geräteanmeldung gilt wie für `/api/system/cluster-cockpit`, muss #1721 am Live-Lead belegen. Der PUT auf `/api/tasks/{id}` war am 2026-10-05 ohne Anmeldung möglich.

## 14. Einordnung im ellmos-Modulmodell

Grundlage ist das öffentliche Organisationsprofil von ellmos-ai (Stand 2026-09-27) mit den Schichten Module, Bundle, Stack, System und Fleet. Daneben stehen die lokalen Klone unter `C:\_Local_DEV\repos\` (Prüfung am 2026-10-05).

| Modul | Rolle laut Profil | Rolle in diesem Vertrag |
|---|---|---|
| **roshambo** | Fleet-Koordination: „roshambo with system-gap-master“, serialisierbare Leases | Liefert die Lease-Semantik (Abschnitt 3). Roshambos eigene `docs/ROADMAP-LOCAL-DB.md` hält fest, dass für Heimlabor-Schwärme SQLite oder PostgreSQL einfacher sind als CockroachDB. Dort ist ein `StorageBackend`-Interface geplant. **Migrationsoption nach #1723:** Ein Roshambo-Backend auf der Lead-TaskDB, mit der Lease-Ressource `task:<task_id>`, darf die BACH-interne Implementierung ersetzen. Das Wire-Format aus Abschnitt 5 bleibt dabei gleich, und eine zweite Claim-Datenbank entsteht nicht. |
| **task-master** | Eigenständiges SQLite-Taskmodul mit den Rollen TASKSOLVER, TASKWRITER und MAINTAINER | Konsument des Vertrags. TASKSOLVER übernimmt Arbeit nur über Acquire, Renew und Release. Das Task-Master-Board (GUX-072/073) zeigt nur die Holder-Ansicht aus 5.2. Gibt es einen Lead, ist eine lokale task-master-Datenbank Projektion, keine Authority. |
| **ticket-master** | Router und Triage | Nur Provenienz (`source`, `claim_salt_ref`). Sein dateibasierter `.claim-<HOST>` bleibt DB-loser Fallback (GUX-007) und ist kein Lease auf Lead-Tasks. |
| **lock-master** | Datei- und Projekt-Locks (`LOCK*.txt`) | Domäne des Lock-Salt (Abschnitt 7). Er wird nicht über diesen Vertrag gesteuert und vom Lease nicht übersteuert. |
| **sqlite-transit-sync** und **system-gap-master** | Snapshot- und Zeilen-Sync zwischen Hosts | Die Lease-Spalten (`claim_*`) dürfen per Sync **nie** zusammengeführt oder überschrieben werden. Sie sind nur auf dem Lead schreibbar und werden höchstens lesend gespiegelt (vgl. Abschnitt 11 Punkt 4). |
| **ellmos-system-gui** / **ellmos-universal-gui** | Gemeinsame Oberfläche für BACH und Ocean | Zeigen die Holder-Ansicht (Worker, Host, `expires_at`, `fence`) als echte Daten. Ohne Lead-Verbindung zeigen sie eine erkennbare Baustelle und keinen vorgetäuschten Claim-Zustand. |

Ob die Profilangaben mit den Manifesten unter `OneDrive\.TOPICS\.AI\.BUNDLES` und `.STACKS` übereinstimmen, wurde für diesen Abschnitt nicht geprüft.

session: 2d165522-8524-4d54-b865-ef44a48a372e | agy-opus@ASUS-GEI | 2026-10-05
