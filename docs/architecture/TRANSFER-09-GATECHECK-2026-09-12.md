# TRANSFER-09 — Fork-Archivierung: Gate-Check 2026-09-12

> Dokument-ID: `TRANSFER-09-GATECHECK-2026-09-12`
> Host: `mac-studio` · Operator: Lukas Geiger
> Referenz: `MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12.md §5`, Plan-Regeln 4.1/4.3
> Ergebnis: **ALLE 5 GATES UNMET — Archivierung KONTRAINDIZIERT, kein Artefakt verschieben.**

## Gate-Matrix (Live-Prüfung 2026-09-12)

| # | Gate | Zustand | Evidenz |
|:--|:--|:--:|:--|
| 1 | assistant-core auf allen Hosts pin-konform (`444a1fff`), `test_notify_via_assistant_core.py` grün | ❌ UNMET | `git -C ~/services/assistant-core rev-parse HEAD` → `ccadcf9` (v0.1.0); requirements.txt pinnt `444a1fffd56236078988d088f6237f706c3e15a9` (v0.2.0). `pytest test_notify_via_assistant_core.py` → `ImportError: cannot import name 'NotificationService'` (Collection-Error, Befund B1). Pin-Commit lokal nicht vorhanden; `git fetch` in Nicht-Interaktiv-Shell scheitert (privates Repo, Operator-Aufgabe). |
| 2 | Windows-Gegenprobe `WORKSTATION-LG` Stufen 2/3/5/7 (Plan 4.3) | ❌ UNMET | Zertifikat-Matrix: alle ⬜ offen. |
| 3 | Echter 3-Host-Lauf `sqlite-transit-sync` über OneDrive-Transit | ❌ UNMET | Zertifikat §5: „Offener Betriebs-Nachlauf". |
| 4 | Scheduler-Legacy-Jobs argv-konvertiert + `--apply`-Prämigration verifiziert | ❌ UNMET | Zertifikat §5: deklarierte Host-Aufgabe vor `--apply`. |
| 5 | Haltefrist abgelaufen (Vorschlag ≥ 2026-10-12, Dauer = Operator-Entscheidung) | ❌ UNMET | Heute 2026-09-12 = Tag der letzten Stufenschließung; Haltefrist startet erst am 2026-10-12. |

## Schutzregel 4.1 (Reversibilität) — aktiv, NICHT archivable
Folgende Pfade sind die **Rollback-Ziele** der Env-Schalter und dürfen solange die Schalter existieren **NICHT** archiviert werden (Live-Prüfung):
- Env-Schalter vorhanden in 11 hub-Dateien: `db_sync.py`, `workflow_hook_provider.py`, `transit_sync_provider.py`, `__init__.py`, `upgrade.py`, `setup.py`, `_services/chat/chat_runtime.py`, `memory_hook_provider.py`, `scheduler.py`, `explorer_provider.py`, `scheduler_provider.py`.
- Legacy-Rollback-Pfade vorhanden: `db_sync.py` (ProSync-Merge, Fail-Closed-Fallback), `scheduler_provider.py`/`scheduler.py` (nativer Scheduler-Store), `system_audit.py` (nativer Audit), `_get_bach_context` in `_services/chat/chat_runtime.py` + `memory_hook_provider.py`, `--native`-Testlauf in `hub/test.py`.
- Zertifikat §3: „Es gibt keinen toten Modul-Altcode, der heute archiviert werden könnte, ohne aktive Pfade zu treffen."

## Entscheidung
Archivierung nach `system/hub/_archive/` wird **nicht ausgeführt**. Task #1235 bleibt blockiert bis alle 5 Gates grün sind.
- Gates 1–4: Operator-/Host-Aufgaben (siehe angelegte Folgetasks).
- Gate 5: Haltefrist-Countdown auf 2026-10-12 gesetzt (Operator kann Dauer verkürzen/verlängern).

## Erst dann (wenn alle Gates grün)
Verschieben **nur reiner Altartefakte** nach `system/hub/_archive/` (nicht der Rollback-Pfade!),
AST-Wächter-Anpassung + Volltest beider Plattformen (mac-studio + WORKSTATION-LG).
Aktuell in `_archive/`: `DEPRECATED_hub.py`, `_archive_handlers/`, `delegation_legacy/` (Prä-Transfer-Altla, unverändert).
