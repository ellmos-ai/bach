# TaskDB Salt-Lease Abnahme- und Integrationsprotokoll (v1.0)

> Privacy-Nachtrag 2026-10-07: Persönliche Netzwerkadressen wurden durch die Dokumentationsplatzhalter `lead.example` und `192.0.2.1` ersetzt. Die folgenden historischen Betriebsbefunde bestätigen keine aktuelle Erreichbarkeit dieser Platzhalter.

**Referenz:** Task `#1723` (`[T793][LEASE 4/4] Mehrhost-Claim, Ablauf und Fencing isoliert abnehmen`)  
**Übergeordnete Sammelaufgabe:** `#1696` (`[GUI-GUX][T793] TaskDB-/Lead-Authority, Salt-Leases und Task-Master-Rollen`)  
**Ticket:** `T-20261003-793817309`  
**Datum:** 2026-10-05  
**Autor / Akteur:** `gemini@ASUS-GEI`  
**PR-Kette:** `#195` (Lead Service #1721) -> `#198` (Snapshot ACK #1725) -> `#199` (Status Fencing #1726) -> `#200` (Clients & Trithon #1722) -> `#201` (Acceptance Suite #1723)

---

## 1. Executive Summary & Abnahmeumfang

Mit Task `#1723` wird die 4-teilige Lease-Architektur für BACH und Ocean empirisch und isoliert abgenommen:
- **#1720:** Kanonischer Datenstruktur- und Protokollvertrag (`docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`).
- **#1721:** Lead Lease Service und HTTP-Endpoints (`system/hub/_services/task_lease.py`, `system/hub/web/api/tasks.py`).
- **#1725:** Atomarer Snapshot-ACK vor Commit (`system/hub/_services/task_lease.py`).
- **#1726:** Generischer Statuswechsel-Schutz (`system/hub/task_audit.py`).
- **#1722:** TaskLeaseClient, Trithon-Dispatch, CLI und `bach_api` (`system/hub/_services/task_lease_client.py`, `docs/architecture/TASKDB-SALT-LEASE-CLIENTS-v1.md`).
- **#1723:** Vollständige Concurrency-, Lifecycle-, Fencing- und Stack-Readback-Abnahme.

Alle Prüfungen wurden isoliert auf synthetischen Testdatenbanken (`pytest`) durchgeführt. Es wurden zu keinem Zeitpunkt Produktions-Tasks der TaskDB beansprucht oder verändert.

---

## 2. Empirischer Nachweis der Akzeptanzkriterien

Die Testsuite `system/tests/test_multi_host_lease_acceptance.py` umfasst 14 strukturierte Abnahmetests, die zu 100% bestanden wurden (14 passed in 5.52s, Gesamtsuite mit Regressionen: 97 passed).

### 2.1 Concurrency & Mehrhost-Rennen (Kriterium 1: Kein Doppel-Claim)
- **Threaded Race Test (`test_concurrent_threads_race_exact_one_winner`):**
  - **Szenario:** 5 simultane Client-Identitäten (`opus@Mac-Studio`, `gemini@ASUS-GEI`, `codex@WORKSTATION-LG`, `kimi@Mac-Mini`, `worker5@Cloud-Host`) starten synchronisiert über ein `threading.Barrier` im selben Zeitfenster einen Claim auf dieselbe Task-ID.
  - **Ergebnis:** Exakt ein Client erhält `granted=True` mit `fence=1`. Die anderen 4 Clients erhalten `LeaseDeniedError` mit Grund `held` bzw. `conflict`.
  - **DB-Integrität:** `tasks.claim_fence == 1`, `tasks.claimed_by == winner`, `tasks.status == 'in_progress'`. Die Audit-Tabelle `task_history` verzeichnet exakt einen einzigen `lease_acquire`-Eintrag.
- **HTTP REST-Race Test (`test_concurrent_http_api_race`):**
  - **Szenario:** Parallele HTTP `POST /api/tasks/{id}/lease`-Aufrufe über `ThreadPoolExecutor`.
  - **Ergebnis:** Exakt 1x HTTP 200 OK (Lease vergeben), 2x HTTP 409 Conflict.
  - **Capability-Schutz:** Die Antwort der 409-Ablehnungen leakt zu keinem Zeitpunkt die `lease_id` des Gewinners.

### 2.2 Lifecycle, Fristen & Offline-Deadline (Kriterium 2)
- **Gemeinsame Fristen (`test_shared_issued_and_expires_at`):**
  - `LeaseAck.issued_at` und `LeaseAck.expires_at` stimmen exakt mit den Datenbankspalten `claim_issued_at` und `claim_expires_at` überein.
  - Dauer entspricht der Profilspezifikation (z. B. 300s für Profil S im Testprofil).
- **Verlängerungs-Deckel (`test_renewal_capped_at_max_lifetime`):**
  - Wiederholte Verlängerungen sind strikt an die im Profil definierte `max_total` gebunden.
  - Nach Erreichen der Gesamtlaufzeit wird jeder weitere Verlängerungsversuch mit `max_total_reached` abgewiesen (fail-closed).
- **Offline-Deadline Guard (`test_offline_safety_buffer_deadline_enforcement`):**
  - Nach Vertrag §8.1 berechnet der Client `local_deadline = receive_time + (expires_at - server_now) - safety_buffer`.
  - Nach Überschreiten der errechneten lokalen Sicherheitsfrist bricht `assert_locally_valid()` vor Erreichen von `expires_at` mit `LeaseOfflineDeadlineExceeded` ab, sodass keine Zombie-Writes auf lokaler Seite entstehen.
- **Rückabwicklung & Statusübergänge (`test_release_and_return_transitions`):**
  - `outcome="done"` -> Task-Status `done`, Lease-Felder atomar geleert.
  - `outcome="return"` -> Task-Status `pending`, sofort re-claimbar.
  - `outcome="blocked"` -> Task-Status `blocked`.

### 2.3 Ablauf & Re-Claimability (Kriterium 3: Inkrementierte Fences)
- **Ablauf- und Reclaim-Test (`test_expired_lease_is_reclaimable_with_incremented_fence`):**
  - Worker A beansprucht Task bei `T0` mit `claim_fence = 1`.
  - Vor Ablauf wird Worker B abgewiesen (`held`).
  - Nach Ablauf (`now > expires_at`) beansprucht Worker B denselben Task.
  - **Befund:** Der Claim gelingt sofort, und das Fencing wird atomar auf `claim_fence = 2` inkrementiert.
  - Worker B ist neuer offizieller Halter; Worker A ist vollständig entwertet.

### 2.4 Fencing & Schutz vor veralteten Workern (Kriterium 4)
- **Veralteter Worker Renewal (`test_stale_worker_renewal_rejected`):**
  - Worker A versucht nach Übernahme durch Worker B mit `fence=1` zu verlängern.
  - **Befund:** Fail-closed abgewiesen (`stale_fence`).
- **Veralteter Worker Release & Late-Result (`test_stale_worker_release_rejected_and_late_result_recorded`):**
  - Worker A reicht nach Übernahme ein spätes Arbeitsergebnis (`result_ref`, `note`) mit altem Fence 1 ein.
  - **Befund:** Freigabe wird mit `stale_fence` abgelehnt. Der Task-Status bleibt unberührt auf `in_progress` unter Worker B.
  - Zur Wahrung der Nachvollziehbarkeit wird das verspätete Ergebnis in `task_history` als `late_result` auditiert, ohne operative Schreibrechte zu gewähren.
- **Generischer Statuswechsel-Schutz (`test_direct_or_generic_status_update_blocked_by_lease_guard`):**
  - Jeder direkte Statuswechsel über `apply_task_field_changes` oder generische PUT-Routen auf einem geleasten Task ohne Lease-Autorisierung löst `LeaseRequired` aus.
- **Fence-Tamper-Schutz (`test_fence_tamper_fails_closed`):**
  - Dieser ursprüngliche Test verändert ausschließlich den Fence; er belegt keine Inhaltsversionsprüfung.
- **Inhaltsversionsprüfung (Task #1728):**
  - `test_operator_content_change_rejects_http_holder` ändert die Beschreibung bei unverändertem Fence. Renew und Release des alten HTTP-Adapters werden mit `stale_task_version` abgewiesen. Der lokale Adapter wird separat mit echter Inhaltsänderung geprüft.

---

## 3. Schichten-Readback Matrix

| Schicht | Komponente | Getestete Funktionen / Befehle | Status |
| :--- | :--- | :--- | :--- |
| **Schicht 1** | TaskDB (SQLite) | Schema-Erstellung, `idx_tasks_claim_expires_at`, WAL-Modus, History-Auditierung | **PASS (100%)** |
| **Schicht 2** | `TaskLeaseClient` | In-Process SQLite Adapter und isolierter urllib-Request/FastAPI-Pfad; `acquire`, `read`, `renew`, `release`, `decompose` | **isoliert geprüft; Live-Lead offen** |
| **Schicht 3** | CLI (`system/hub/task.py`) | `bach task lease`, `lease-show`, `lease-renew`, `lease-release` | **PASS (100%)** |
| **Schicht 4** | Python API (`bach_api.py`) | `task.lease_acquire()`, `task.lease_read()`, `task.lease_renew()`, `task.lease_release()` | **PASS (100%)** |
| **Schicht 5** | Trithon Dispatch | `execute_intent_v1()`, `SyntheticTicket`, `ExecutionReceipt` mit `lease_id` & `fence` | **PASS (100%)** |

---

## 4. Live Mac-Studio Lead Readback

- **Tunnel & Erreichbarkeit:** SSH-Tunnel von `ASUS-GEI` (`127.0.0.1:8000`) zu Mac Studio Lead (`192.0.2.1:8000`) ist aktiv.
- **Lead API Status:**
  - Task `#1723` wurde auf der Lead TaskDB offiziell übernommen und zurückgelesen (`assigned_to: gemini@ASUS-GEI`, `claimed_by: api`).
  - Vorherige Kettenglieder: `#1720` (done), `#1721` (done), `#1725` (done), `#1726` (done), `#1722` (done).
  - Da der Lead-Dienst auf dem Mac Studio derzeit noch auf dem Stand vor Merge von PR #195–#200 läuft, werden die neuen Lease-Endpunkte dort nach Merge und Deployment der PR-Kette aktiv. Die lokale Abnahmesuite lief daher isoliert gegen lokale SQLite- und FastAPI-Testclients.

---

## 5. Handover & Sammelaufgabe #1696

Gemäss Akzeptanzkriterien von Task `#1723` und `#1696`:
> *"#1696 wird nach Abschluss dieser Kette wieder auf pending gesetzt, weil seine übrigen GUX-Punkte (Task-Master/Ticket-Master-Rollen und DB-Unifizierung) separat offen bleiben."*

1. **Task #1723 Abschluss:** Wird nach Commit und PR-Erstellung auf `status: done` gesetzt.
2. **Sammelaufgabe #1696 Rückversetzung:** Task `#1696` wird auf der Lead TaskDB von `blocked` auf `pending` zurückgesetzt, damit die nachgelagerten GUX-Punkte (GUX-007, GUX-008, GUX-072, GUX-073, GUX-090) bearbeitet werden können.


## 6. Review-Nachprüfung (Task #1728)

Die ursprünglichen grünen Rennen deckten den HTTP-Client nicht ab und rechtfertigten die vollständige Remote-Abnahme nicht. Ergänzt sind verbindliche Worker-Authority ohne Öffnen lokaler Projektionen, tatsächliche Bearer-Requests über den Adapter an die isolierte Lead-App, ungültige/fehlende Geräteauth, Timeout ohne Mutationsretry, nach bestätigtem Server-Commit verlorenes Zerlegungs-ACK ohne zweite Kindergruppe, ungültige/kurze Fristen und korrelierte ACKs. Trithons Stale-Fence-Test liest nun zusätzlich den Ticket-Ledger zurück: Ein abgelehnter Release darf kein `done` hinterlassen.

Diese Tests simulieren Transportfehler und Uhrzeiten. Sie belegen keine Netzwerkverfügbarkeit oder Geräteanmeldung des installierten Mac-Leads. Die ursprüngliche Task-Statusaufnahme in Abschnitt 4 ist ein datierter Readback und kein Lease-Deployment. Mac-/BACH-/Ocean-Laufzeitabnahme, Browser und formale PR-Freigaben bleiben offen.
