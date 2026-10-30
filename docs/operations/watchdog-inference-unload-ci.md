# CI-Einbindung des Unload-Guard-Tests (Task 2419)

## Zweck

`system/tests/test_memory_pressure_unload_guard.py` prueft die racefreie
Koordination des Modell-Unloads (`memory_pressure_watchdog.sh`) gegen
`HostInferenceGate` / `inference.lock`. Der Test muss in CI laufen, sonst
ist die Absicherung nur lokal wirksam.

## Stand

- Testdatei vorhanden: `system/tests/test_memory_pressure_unload_guard.py`
- Gate-Test vorhanden: `system/tests/test_host_inference_gate.py`
- CI-Einbindung als Patch vorbereitet:
  `docs/operations/patches/tests-yml-add-unload-guard.patch`

Der Patch ergaenzt ausschliesslich den bestehenden Step
`Local model sockets and host admission` um die Guard-Testdatei.
Er aendert weder die Ausschlussliste noch den Sammel-Step noch Job-Struktur.

## Blocker

Der Worker-Push auf `bach-task/2419` / PR #599 wurde von GitHub abgelehnt:

```
! [remote rejected] bach-task/2419 -> bach-task/2419
(refusing to allow an OAuth App to create or update workflow
 `.github/workflows/tests.yml` without `workflow` scope)
```

Der Worker-Token darf `.github/workflows/` nicht schreiben. Die Datei wurde
deshalb im Worktree unveraendert gelassen; die Aenderung liegt als Patch bei.

## Anwendung (Maintainer)

```bash
git apply docs/operations/patches/tests-yml-add-unload-guard.patch
git commit -am "ci: unload-guard test in local model sockets step"
git push
```

Danach erscheint der Guard-Test im PR-Check `tests` und laeuft auf
`ubuntu-latest` mit Python 3.12.

## Lokaler Nachweis (vor dem Push zu erbringen)

```bash
python -m pytest -q -p no:cacheprovider \
  system/tests/test_memory_pressure_unload_guard.py \
  system/tests/test_host_inference_gate.py
```

## Nicht betroffen

Der Host-Watchdog `compute_queue/memory_pressure_watchdog.sh` bleibt
unveraendert; Task 2419 liefert nur den BACH-seitigen Guard, die
Gate-Ergaenzung und die Dokumentation als Kandidat/Diff.
