# Task #2332 — Belegmatrix: Agentenprofil-Löschung (`delete_worker_profile`)

Stand: statische Code-Verifikation vollständig. **Testausführung in dieser Session nicht bestätigt**
(`execute_command` 7× ohne Bestätigung → Wirkung unbekannt). Es werden daher **keine** Testergebnisse
behauptet. Keine Live-Profildaten wurden gelöscht.

## 1. GUI → API → Backend (Kette vollständig belegt)

| Ebene | Datei / Zeile | Beleg |
|---|---|---|
| Button | `system/gui/web/src/pages/agenten/running.astro:885` | Lösch-Button „Profil löschen" |
| Frontend-Call | `running.astro:1009–1015` `deleteWorker()` | `POST /api/system/workers/<id>/delete` |
| GUI-Route | `system/gui/api/unified_api.py:3653–3666` | `@router.post("/system/workers/{worker_id}/delete")` → `delete_system_worker` → `worker_action("delete", {"id": worker_id}, device_token=…)` |
| Aktions-Mapping | `system/gui/api/worker_status_adapter.py:53–59` | `_ACTIONS["delete"] = ("POST", "workers/delete")` |
| Whitelist | `worker_status_adapter.py:41–52` (Z. 47) | `("POST", "workers/delete")` in `_ALLOWED_CONTROL` |
| Control-API-Client | `worker_status_adapter.py:643–689`, Request Z. 668–670 | `_request_control_api(method, endpoint, …)` gegen `gui_server._chat_control_base_url()` (Z. 430) |
| Backend-Route | `system/hub/_services/chat/telegram_chat.py:6881–6887` | `POST /api/workers/delete` (+ Alias `/api/worker/delete`) → `delete_worker_profile` |
| Backend-Route (alt) | `telegram_chat.py:7109–7116` | `DELETE /api/workers?id=` → `delete_worker_profile` |
| Core-Logik | `telegram_chat.py:1888–1927` | `delete_worker_profile` |

Negativ-Beleg: `system/gui/server.py` enthält keine Treffer für `workers/delete` / `system/workers`
→ Worker-Routing liegt ausschließlich in `system/gui/api/unified_api.py`.

## 2. Geordnetes Stoppen (kein Löschen laufender Profile)

- `worker_status_adapter.py:663–666`: Snapshot via `read_worker_status`; nicht vorhanden → **404**
  `"Workerprofil nicht gefunden"`; `status in {"running","stopping"}` → **409**
  `"Laufende Worker müssen zuerst gestoppt werden"`.
- `telegram_chat.py:1810–1885` `_assert_worker_profile_inactive`: Controller-Run-Identität + Lease-Prüfung,
  Fehlercodes `execution_unconfirmed` (→409) und `leased`.
- Backend-Verankerung: `telegram_chat.py:1888–1927` ruft `_assert_worker_profile_inactive` vor dem Entfernen.

## 3. Core-/System-Schutz

- `telegram_chat.py:1888–1927`: Core-/System-Slot → **404** (Schutz vor Löschung von Kernprofilen);
  `telegram_chat.py:124` importiert `DEFAULT_CORE_SLOTS` als Schutzquelle.
- `system/hub/_services/chat/slots_config.py:1842–1845` `remove_worker`: lehnt mehrdeutige sowie Core-IDs
  mit `ValueError` ab (zweite Schutzschicht auf Config-Ebene).
- ID-Validierung: Adapter `worker_status_adapter.py:656–658` gegen `_SAFE_ID` → `WorkerActionRejected` (400);
  Backend `telegram_chat.py:1888–1927` eigene ID-Validierung → **400**.

## 4. Archivierung (erst archivieren, dann entfernen)

- `telegram_chat.py:1905` → `slots_config.remove_worker` (`slots_config.py:1837–1884`).
- `slots_config.py:1864–1868`: `worker_run_archive.archive_terminal_records` nach `<config>/worker-run-archive`.
- `slots_config.py:1870–1875`: durable Persistenz auf POSIX-Systemen.
- `agent_library.py:37–48` `archive_then_remove_profile` mit Loader `agent_library.py:24` — Reihenfolge
  Archiv → Entfernen ist im Namen und in der Aufrufkette abgebildet.

## 5. Guard / Budget-Recovery

- `slots_config.py:1850–1853`: `remove_worker` ohne `_runtime_guard` → `RuntimeError`.
- `telegram_chat.py:1888–1927`: `remove_worker` läuft unter `_runtime_guard`; Budget-Recovery-Fall → **409**.
- Testbeleg für diese Semantik: `system/tests/test_agent_library_delete.py:106–114`
  (`RuntimeError("worker_delete_execution_unconfirmed")`) und `:117–135`
  (`worker_delete_budget_unconfirmed` → 409, `ValueError` → 503).

## 6. Readbacks & Antwortformate

- Adapter-Erfolg: `worker_status_adapter.py:674–688` → `{"ok": True, "action": …, ggf. "id", "receipt"}`.
- Backend-Erfolg: `telegram_chat.py:1888–1927` → `{"ok": True, "id": …}` mit **200**.
- Strict Readback: Backend **503**, wenn das Profil nach dem Entfernen noch sichtbar ist
  (`telegram_chat.py:1888–1927`); Testbeleg „Readback-Ghost" → 503:
  `system/tests/test_agent_library_delete.py:138–152`.

## 7. Fehler-Mapping (einheitlich)

| Ursache | Adapter/API | Backend |
|---|---|---|
| ungültige ID | 400 (`WorkerActionRejected`) | 400 |
| Profil unbekannt / Core-Schutz | 404 | 404 |
| laufend/stopping, Lease, `execution_unconfirmed`, Budget-Recovery | 409 | 409 |
| Control-API: `result.get("ok") is not True` | 409 (`worker_status_adapter.py:671–672`) | – |
| Control-API nicht erreichbar | `WorkerStatusUnavailable` → **503** „Workerprofil konnte nicht entfernt werden" | – |
| Archiv-Fehler `ValueError` | – | 503 |
| Readback nicht bestätigt | – | 503 |

## 8. Testabdeckung (Datei vorhanden, Ausführung NICHT bestätigt)

`system/tests/test_agent_library_delete.py` (152 Zeilen):
Erfolg + strict Readback; Execution-unconfirmed 409 (`:82–85`); ungültige ID 400 (`:88–91`);
unbekannt/Core 404 (`:94–103`); `remove_worker` ohne Guard → RuntimeError (`:106–114`);
archive-fail 409 / ValueError 503 (`:117–135`); Readback-Ghost 503 (`:138–152`).

**Offener Punkt:** `python -m pytest system/tests/test_agent_library_delete.py -q` konnte in dieser Session
nicht bestätigt ausgeführt werden (7 Fehlversuche, „Werkzeugausführung nicht bestätigt"). Testergebnis
bleibt damit unbelegt; Source-Commit mit PR erst nach bestätigtem Lauf.
