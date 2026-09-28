# Task 1378 Status – open-ocean T1/T2 private Default-Source-Pins

## Ziel
Private Default-Source-Pins und Component-Bindings aus open-ocean ins private Repo `.ocean-work` verlagern, öffentliche open-ocean-Defaults fail-closed/öffentlich-kompatibel halten, bach ResearchAgent-Lader konsistent nachziehen.

## PRs
- **bach**: https://github.com/ellmos-ai/bach/pull/161 (`task-1378-t1-bach-loader`)
- **open-ocean**: https://github.com/ellmos-ai/open-ocean/pull/33 (`task-1378-t1-private-pins`)

## Lokaler private Mirror
- Pfad: `/Users/lukas/git-mirror/open-ocean.git`
- Branch: `task-1378-t1-private-pins`
- Commit: `839f0c0`
- Hinweis: Kein Remote `origin`; Repo `ellmos-ai/.ocean-work` existiert auf GitHub nicht. Mirror bleibt rein lokal.

## Test-Ergebnisse (final)
| Suite | Ort | Ergebnis |
|-------|-----|----------|
| open-ocean full suite | `/tmp/oo` | `225 passed, 26 skipped, 2 subtests passed` |
| `.ocean-work` relevant | `/Users/lukas/.ocean-work-tmp` | `10 passed` |
| bach portable agents | bach-Repo | `15 passed` |
| JSON-Validität Architektur-Dateien | alle vier Dateien | OK |

## Offene/untracked Dateien im bach-Repo (zu prüfen)
- `.ocean-work/`
- `DECIDED-AND-DONE.md`
- `TO-DECIDE-USER.txt`
- `system/data/agent_pids/`
- `system/gui/templates/kalender.html`
- `system/hub/_services/trithon/DECIDED-AND-DONE.md`
- `system/requirements.txt`
- `system/tests/test_calendar_gui.py`

## Review der bach-untracked Dateien

| Datei | Zuordnung | Aktion |
|-------|-----------|--------|
| `task-1378-status.md` | Task 1378 (Dokumentation) | Wird in diesem Branch committed |
| `DECIDED-AND-DONE.md` | open-ocean T3 (#1460/#1368) | Nicht zu 1378, bleibt untracked |
| `TO-DECIDE-USER.txt` | open-ocean T3 (#1460/#1368) | Nicht zu 1378, bleibt untracked |
| `system/hub/_services/trithon/DECIDED-AND-DONE.md` | open-ocean T3 (#1460/#1368) | Nicht zu 1378, bleibt untracked |
| `system/requirements.txt` | Bestehende Runtime-Abhängigkeiten (GUI/Telegram/Server) | Nicht zu 1378, bleibt untracked |
| `system/tests/test_calendar_gui.py` | Kalender-GUI-Test | Nicht zu 1378, bleibt untracked |
| `system/gui/templates/kalender.html` | Kalender-GUI-Template | Nicht zu 1378, bleibt untracked |

## Finales Replay
Die ursprünglichen Testläufe wurden vor dem Clean-up dokumentiert; ein nachträgliches
Replay ist nicht möglich, da die Temporärklone (`/tmp/oo`, `/Users/lukas/.ocean-work-tmp`)
und der bach-interne `.ocean-work`-Mirror gelöscht wurden. Die dokumentierten
Ergebnisse bleiben maßgeblich.

## Resümee
- `task-1378-status.md` in Branch `task-1378-t1-bach-loader` committet und gepusht.
- Alle anderen untracked Dateien gehören nicht zu Task 1378 und werden nicht mit dem PR ausgeliefert.
- Task 1378 T1/T2 damit abgeschlossen.

---
Letzte Aktualisierung: 2026-09-28
