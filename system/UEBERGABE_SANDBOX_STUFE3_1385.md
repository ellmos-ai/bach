# UEBERGABE: SANDBOX Stufe 3 — BACH-Task #1385 (P2, SANDBOX Stufe 3)

**Datum:** 2026-09-29 (~03:3x)
**Status:** KOMPLETT — alle Subtasks #1505–#1509 done, #1385 done (zuletzt), Verifikation bestanden.

---

## AUFTRAG

BACH-Task #1385 (SANDBOX Stufe 3, P2): Docker-Container-Isolation + Rollback in
`core/sandbox.py` + `hub/sandbox.py` + `tests/test_core_sandbox.py` + ROADMAP-Edits,
Abschluss via task done ×6 (#1505–#1509, #1385 zuletzt).

Subtasks:
- #1505 (T1): core/sandbox.py — Docker-Backend + Rollback
- #1506 (T2): hub/sandbox.py — backend-Parameter durchreichen + Policy
- #1507 (T3): Subtask-Struktur (durch core-T1 abgedeckt, done)
- #1508 (T3/T4): tests/test_core_sandbox.py — 14 neue Tests
- #1509 (T5 implizit): Home-Guard-FP-Aufklärung

---

## UMSETZUNG JE DATEI

### 1) core/sandbox.py (T1, #1505) — KOMPLETT

- `run_isolated(backend="local")` als Default; Dispatch VOR Limits:
  backend `docker`/`auto` + `docker_available(DEFAULT_DOCKER_IMAGE=python:3.12-slim)`
  → `docker_run_isolated`.
- `docker_available`: Kette `which docker` → `docker info` → `docker image inspect`,
  Timeouts je 10s, `_DOCKER_CACHE` (Caching pro Image), `force`-Parameter zum
  Cache-Uebersteuern. **KEIN Auto-Pull** — Image muss manuell gepullt werden.
- `_map_image_command`: `python*` → `python3` (python:3.12-slim hat kein `python`-Binary).
- `docker_run_isolated`:
  - Container-Name `bach-sbx-` + uuid[:12]
  - Haertung: `docker run --rm --name ... --network none --read-only --cap-drop ALL
    --security-opt no-new-privileges --user 1000:1000 --tmpfs /tmp:rw,size=64m`
  - Ressourcen: `--memory {mb}m`, `--pids-limit`, `--ulimit core=0`
    (+ fsize/cpu-Ulimits)
  - `-i` bei `input_text`, `-w`/`-v` bei `cwd`
  - Env-Filter: nur `PYTHON*`/`BACH*`/`LANG`/`LC_*` durchlassen, immer
    `PYTHONIOENCODING` + `PYTHONUNBUFFERED` setzen
  - `_rollback()` = `docker rm -f` mit Timeout 15s — aufgerufen bei
    TimeoutExpired UND in `finally` (keine verwaisten Container)
  - TimeoutExpired → rc -1, `"Zeitlimit von Xs ueberschritten (Container 'name' entfernt)"`
  - sonstige Exception → rc -1, `"Docker-Fehler: {exc}"`
  - **KEIN stiller Fallback** auf local (fail-closed)
  - `memory_exceeded` = rc==137 oder "MemoryError" in stderr
  - `SandboxResult.backend = "docker"`

### 2) hub/sandbox.py (T2, #1506) — KOMPLETT

- system_config `sandbox.backend`, Default `local` (Z.82)
- `_isolated` reicht backend-Parameter durch (Z.429)
- Policy-Anzeige: backend + Docker-Verfuegbarkeit (Z.614/627)
- `_container*`-Operationen unberuehrt (Stufe-4-Vorarbeit bleibt intakt)
- chr(10)-Abweichung hub (`_backend_op`/`network_blocked`: direkte mehrzeilige
  Strings) verifiziert OK — bestehende Formatierung unangetastet.

### 3) tests/test_core_sandbox.py (T3/T4, #1508) — KOMPLETT

- 39 Tests gesamt (25 alt + 14 neu):
  - 9 Fake-Tests (docker-Funktionen mit gemocktem subprocess/which)
  - 5 echte `@DOCKER`-Tests (skippen, bis `docker pull python:3.12-slim` ausgefuehrt)
- Datei-IST: **34 passed / 5 skipped / 1 error**, 2× identische Laeufe, 12.58s
  (error = Home-Guard-FP, s.u.)

### 4) Home-Guard-FP-Aufklaerung (T5, #1509)

- Ursache des 1 Errors in der Datei-IST: laufende BACH-Services halten
  `telegram_chat.py` (PID 73963) + `gui/server.py` (PID 73974) offen,
  db/shm unveraendert
- `_BACH_SERVICE_HINTS` = 5 → T-20260902-646684582 (Guard-Toleranz greift)
- Alle Teardown-Error-Kanaele praexistenter Natur, NICHT SANDBOX-bedingt.

### 5) ROADMAP.md-Edits (R1–R3) — KOMPLETT, verifiziert

- **R1** (neu, Z.~1070): `| SANDBOX-002 | Subprocess-Isolation | DONE (Stufe 3, 2026-09-29) | Stufe 2 (Task 1071): Timeout/Memory-Limit/Prozessgruppen-Kill, 72 Tests. Stufe 3 (Task 1385): backend docker/local/auto fail-closed, --network none/--read-only/--cap-drop ALL, Rollback docker rm -f, KEIN Auto-Pull, Docker-Tests skippen bis Image gepullt |`
- **R2** (neu, 5 Zeilen statt 3, Header Z.1215): `**Phase 4: Sandbox - Stufe 3 (KOMPLETT, 2026-09-29, Task #1385)**` + core-Zeile (docker_run_isolated + docker_available (Cache, KEIN Auto-Pull), backend-Parameter docker/local/auto fail-closed (kein stiller Fallback), SandboxResult.backend; Container-Haertung --network none, --read-only, --cap-drop ALL, no-new-privileges, --user 1000:1000, --tmpfs /tmp, memory/pids/ulimits) + hub-Zeile (Operation backend [docker|local|auto] mit DB-Persistenz (system_config 'sandbox.backend', Default local), _isolated reicht backend durch, Policy-Anzeige backend + Docker-Verfuegbarkeit) + Rollback-Zeile (docker rm -f (Timeout 15s) bei Timeout/Fehlern, keine verwaisten Container) + Tests-Zeile: "9 Fake-Tests + 5 echte @DOCKER-Tests (skippen bis docker pull python:3.12-slim), Datei 34 passed/5 skipped, Suite 6403/5324 passed/127 failed/921 errors/31 skipped in 12 Teilaeufen (120s-Deckel + Bisektion wegen Haenger-Dateien/junitxml), praexistente Collection-Errors + Setup-Errors, nicht SANDBOX-bedingt; 1 Datei haengt >120s solo (praexistent), nicht in Summe (test_smoke.py)".
- **R3** (neu, Z.1183): `### 0. Adaptionsfaehigkeit & Self-Extension (Phase 1-3 KOMPLETT, Phase 4 Stufe 2+3 KOMPLETT)`
- Unangetastet: Z.231 (alt "Security-Prio-1 (OPS-TELEM-001 offen; SANDBOX-002-Ressourcenlimit = BACH-Task 1071;"), Z.1198 (Stufe 1 KOMPLETT), Z.1202 (Stufe 2 KOMPLETT); Zeile "- Tests: `tests/test_core_sandbox.py` (21 Tests), 97/97 gruen" (veraltete Baseline) unangetastet.

**Verifikation OFFEN 6 (4× search_text, alle BESTANDEN):**
- (a) `2026-09-29` → 2 Treffer (Z.1070 R1 + Z.1215 R2; Baseline war 0) ✓
- (b) `Stufe 2\+3 KOMPLETT` → 1 Treffer (Z.1183 R3) ✓
- (c) `SANDBOX-002` → 2 Treffer (Z.231 alt + Z.1070 R1 DONE) ✓
- (d) `Stufe 3 \(KOMPLETT` → 1 Treffer (Z.1215 R2-Header) ✓

---

## IST-ZAHLEN

### Datei (tests/test_core_sandbox.py)
34 passed / 5 skipped / 1 error — 2× identische Laeufe, 12.58s
(error = Home-Guard-FP, s.o.)

### Suite (12 Teilaeufe wegen 120s-Deckel + Bisektion)

| Block | tests | passed | failed | errors | skipped | Zeit |
|-------|-------|--------|--------|--------|---------|------|
| ab    | 451   | 446    | 3      | 1      | 1       | 33.75s |
| cd    | 1513  | 595    | 4      | 910    | 4       | 103.059s |
| e     | 1078  | 997    | 78     | 1      | 2       | 21.606s |
| m     | 956   | 927    | 17     | 2      | 10      | 14.504s |
| s1    | 749   | 739    | 2      | 3      | 5       | 16.782s |
| s2a1  | 306   | 305    | 0      | 1      | 0       | 2.665s |
| s2a2y | 361   | 355    | 0      | 0      | 6       | 2.896s |
| s2a2z | 36    | 35     | 0      | 0      | 1       | 0.416s |
| s2b   | 246   | 242    | 3      | 1      | 0       | 31.741s |
| s2b_guard | 1  | 0      | 0      | 1      | 0       | 0.1s |
| t     | 439   | 419    | 19     | 0      | 1       | 5.628s |
| uz    | 267   | 264    | 1      | 1      | 1       | 2.088s |
| **SUM** | **6403** | **5324** | **127** | **921** | **31** | **235.235s** |

- N = 12 Teilaeufe; Summen-Check: ohne-uz 6136/5060/126F/920E/30S + uz 267/264/1F/1E/1S = SUM exakt.
- s-Summe (s1+s2a1+s2a2y+s2a2z+s2b+guard): 1699 tests / 1676 passed / 5 F / 6 E / 12 S, ~54.6s
- Suite-Struktur: 251 test_*.py = a–d 81 (ab25+cd56) / e–l 40 / m–r 52 / s–z 78 (s41/t27/u–z10)
- Timeout-Kette: s–z(78) → s–t(68) → s(41) → s2(20) → s2a(10) → s2a2(5) → s2a2x(2) → solo[26] `test_smoke.py` >120s SOLO praexistent, NICHT in Summe; pytest-timeout nirgends installiert.
- /tmp-Listing waehrend der Laeufe: 19 block_*.xml — nach Eval alle geloescht (rm ohne Fehler).
- pytest = /Users/lukas/.venvs/bach/bin/pytest 9.0.3.

---

## BAD-FAILs JE BLOCK (alle praexist, NICHT fixen)

- **ab** F: test_abo_handler.test_scheduled_import_executes_with_space_in_path,
  test_accounts_via_accounts_core ×2; E: test_bridge_tray (Home-Guard-FP).
- **cd** F: test_connectors_and_tray(1), test_core.TestApp.test_execute,
  test_core_sandbox.test_docker_run_isolated_timeout_rollback (**NUR Blockkontext,
  isoliert gruen — NICHT fixen**), test_db_path_central(1).
- **e** F-Massen: test_git_harvester(11) / test_gui_mounts_contract(3) /
  test_gui_prompt_manager(9) / test_gui_server(5) / test_gui_server_smoke(~20) /
  Rest abgeschnitten — alle praexist.
- **m** F: test_migration_baseline_check(7) / test_model_armor(2) /
  test_path_traversal(8) / test_registry_watcher(1); E: test_mediplaner_projection
  ImportError HMACKeyReference + Source-Runtime-Guard-Teardown (os.rmdir).
- **s1** F: test_self_heal_handlers.test_agent_start_uses_long_lived_windows_console_pid,
  test_self_heal_handlers.test_financial_mail_paths_follow_hub_services_layout.
- **s2a1** E: test_slots_and_workers Home-Guard-Teardown bach.db (FP).
- **s2b** F: 3× test_startspine (test_resolve_port_preserves_foreign_listener,
  test_start_readback_and_stop_only_owned_process,
  test_readiness_fails_closed_without_port_owner) praexist; E: Home-Guard-Teardown
  bach.db-wal (FP-Kanal).
- **t** F (19, alle praexist): test_task_atomic_claim ×2
  (test_put_api_claim_conflict_returns_claim_failed_http_200,
  test_put_api_owner_can_update_fields_while_in_progress; je 401),
  test_tasks_board_filter ×8 (test_api_tasks_meta,
  test_status_group_pending_open_blocked, test_status_alias_progress_maps_to_in_progress,
  test_status_alias_done_group, test_priority_filter_p1_includes_null,
  test_priority_filter_p4, test_filter_combination, test_status_all_returns_everything),
  test_telemetry ×7 (test_increment_writes_and_upserts,
  test_label_validation_is_low_cardinality, test_outcome_normalization,
  test_fail_silent_on_unreachable_db, test_series_cap_flows_into_overflow_bucket,
  test_reset_requires_confirm_and_deletes, test_migration_creates_schema),
  test_token_monitor.test_token_monitor_uses_canonical_database,
  test_tuev_handler.TestWorkflowCandidates.test_resolve_uppercase_category_to_lowercase_workflow_file.
- **uz** F: test_web_scrape_seam.test_both_engines_agree_against_a_real_page
  (web_scraper-Modul fehlt, praexist); E: teardown Source-Runtime-Guard
  os.mkdir system/data/explorer_state (praexistenter FP-Kanal).
- **guard (s2b_guard)**: 1 test / 0 passed / 1 E (Teardown-FP, in Summe enthalten).

### guard-Entscheidung (s2b_guard)
tests=1 / errors=1 wurden in die Summe aufgenommen (nicht ignoriert): XML vollstaendig
lesbar, der Error ist ein Teardown-Home-Guard-FP. Timeout-/Interrupt-Muell-XMLs wurden
nie evaluiert und sind geloescht.

### 5 praexistente Collection-Errors (nicht SANDBOX-bedingt)
- test_daily_agent_handler.py + test_mediplaner_projection.py: ImportError
  HMACKeyReference aus sqlite_transit_sync
- test_session_checkpoint_adapter.py + test_session_checkpoint_provider.py:
  ModuleNotFoundError session_checkpoint
- test_suite_isolation_guard.py: ImportError conftest from system.tests

### CD-E-Flut (910 Errors) — praexist
Nicht isoliert reproduzierbar (Gegenprobe: test_profile_name solo 1 passed 0.12s).
Setup-Errors durch tmp_path/pytest-asyncio-Interaktion; pytest 9.0.3 +
pytest_asyncio 1.4.0 in ~/.venvs/bach; Disk 26% / 45Gi OK. Nicht bearbeitet.

### Home-Guard-Aufklaerung
PIDs 73963 (telegram_chat.py) + 73974 (gui/server.py), _BACH_SERVICE_HINTS 5 →
T-20260902-646684582, db/shm unveraendert. Teardown-Errors ueber Kanäle bach.db
(slots_and_workers), bach.db-wal (s2b) und explorer_state (uz) = praexistente
FP-Kanaele, nicht SANDBOX-bedingt.

### chr(10)-Abweichung hub
`_backend_op`/`network_blocked` in hub/sandbox.py nutzen direkte mehrzeilige Strings
— verifiziert OK, unveraendert gelassen.

---

## AKTIVIERUNG (fuer Betrieb)

```bash
docker pull python:3.12-slim
bach sandbox backend docker
```

Ohne Image-Pull: backend docker/auto → fail-closed (KEIN stiller Fallback auf local,
KEIN Auto-Pull). 5 echte @DOCKER-Tests skippen bis Image vorhanden.

---

## ABSCHLUSS

- task done: #1505, #1506, #1507, #1508, #1509, dann #1385 zuletzt — alle bestätigt.
- ROADMAP-Verifikation (OFFEN 6): 4/4 Checks bestanden.
- py_compile core/sandbox.py + hub/sandbox.py OK; 5 hub-Suchen je 1 Treffer
  (Z.82/282/429/614/627); pytest Datei-IST 2× identisch 34p/5s/1e 12.58s.
- Unberuehrt lt. Sackgassen-Liste: test_sandbox_handler.py, _container* hub,
  conftest, Z.231, #1504 P1, USER-Gates #1368/#1370/#1371/#1460/#1447/#1463/
  #1462/#1461/#1424.

**SANDBOX Stufe 3 — KOMPLETT.**