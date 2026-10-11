# Gebundene Schreibrechte für BACH-Worker

## Geltung

Dieses Dokument beschreibt den Quellvertrag für Task #2073. Es ist keine Aussage über eine installierte Version, einen Produktivlauf oder eine abgeschlossene Betriebsabnahme. Die maßgeblichen Prüfungen liegen an der privaten Workerbindung und am gemeinsamen Tool-Dispatcher.

## Herkunft der Freigabe

Die Laufzeit entnimmt `worker_task_binding`, `require_task_binding` und `allowed_tools` dem vertrauenswürdigen Sitzungskontext. [`chat_runtime._tool_dispatch_kwargs`](../../system/hub/_services/chat/chat_runtime.py) reicht `session.allowed_tools` weiter. Das gilt auch für einen gebundenen Worker, wenn `agent_operations` nicht vorhanden ist. Modellargumente erzeugen oder erweitern keine Freigabe.

[`bach_tools.exec_tool`](../../system/hub/_services/chat/bach_tools.py) prüft zuerst aktive Bindung und verfügbaren Modus. Für als schreibend klassifizierte Werkzeuge verlangt der Dispatcher die konkrete Werkzeugfreigabe aus dem Sitzungskontext. Eine fehlende oder unbekannte Freigabe wird abgewiesen. Eine Promptregel allein gewährt keine Schreibrechte.

## Native Task-Autorität

[`worker_write_guard`](../../system/hub/_services/chat/worker_write_guard.py) fragt die bestehende `TaskLeaseClient`-Autorität über die private Bindung erneut ab. Für eine schreibende Operation müssen alle Bedingungen stimmen:

- Die Bindung ist aktiv und gehört zur exakten Task-ID.
- Die native Lease ist aktuell, gehört diesem Worker und steht auf `in_progress`.
- Fence und `task_version` stimmen mit der privaten Bindung überein.
- Lease-, Lock- oder Scannerfehler lassen die Änderung scheitern.

[`WorkerLeaseBinding.execute_task_manage`](../../system/hub/_services/chat/worker_lease_binding.py) bindet Task-Aktionen zusätzlich an die eigene ID. Ergebnisabgaben verwenden die zentrale `validate_submission`-Prüfung für konkrete, nichtleere Ergebnisse bis 3000 Zeichen. Ein erfolgreicher ACK stellt das Ergebnis auf `review`; er bedeutet weder fachliche Abnahme noch `done`.

## Arbeitsbaum und Sperren

Mutationen sind an den exakten registrierten Task-Arbeitsbaum gebunden. Er muss unter dem konfigurierten Task-Worktree-Root als `task-<id>` existieren, im kanonischen BACH-Git-Repository registriert sein und auf `bach-task/<id>` stehen. Git-Root und gemeinsames Git-Verzeichnis werden geprüft. Pfade werden normalisiert; Traversal und Symlink-Ausbrüche werden abgewiesen.

Vor Änderungen liest der Guard den kanonischen Sperrscanner erneut. Er prüft den Klon samt aufgelöstem OneDrive-Zwilling sowie den Worktree-Root, den Task-Baum und jeden betroffenen Quell- und Zielpfad. Für nicht vorhandene Ziele wird der nächste vorhandene Elternordner geprüft, bevor Elternordner angelegt werden. Jede fremde, unbekannte oder nicht lesbare Sperre blockiert die Mutation.

## Werkzeuggrenzen

| Werkzeug | Aktuelle Grenze |
| --- | --- |
| `safe_shell` ohne `cwd` | Erhält den vorhandenen eingeschränkten Nur-Lese-Pfad für gebundene Analyseworker ohne eigenen Task-Arbeitsbaum. Die aktuelle native Lease, Befehls-Allowlist, Tokenprüfung und Pfad-/Geheimnisschutz bleiben erforderlich. |
| `safe_shell` mit `cwd` | Wird wie ein gebundener Aufruf geprüft; das Arbeitsverzeichnis muss zum registrierten Task-Baum gehören. |
| `execute_command` | Läuft nur mit geprüftem `cwd` im Task-Baum über den begrenzten Prozessrunner. Befehle, Python-Prüfmodule und Git-Unterbefehle sind eingeschränkt; `shell=True` wird nicht verwendet. |
| Dateiänderungen | Schreib-, Änderungs-, Verschiebe-, Kopier- und Verzeichnisaktionen autorisieren die aufgelösten Pfade vor der Mutation erneut. Vor dem Anlegen fehlender Eltern wird der vorhandene Vorfahr gescannt. |
| `finish_task` | Verwendet ausschließlich den gebundenen Task-Baum. Secrets-, Diff- und gezielte Testprüfungen berücksichtigen geänderte Dateien sowie nicht ignorierte neue Dateien vor `git add -A`. Commit, Push und PR laufen über den kontrollierten Task-Git-Workflow; Merge und fachliche Abnahme sind getrennt. |
| `task_manage` | Prüft öffentliche ID- und Ergebnisargumente vor dem privaten Aufruf. Die native Bindung prüft Eigentümerschaft und ACK erneut. Fehler der privaten Autorität oder ein unbekannter ACK bleiben als allgemeiner Fehler sichtbar, ohne Lease- oder Capabilitydetails auszugeben. |
| Cleanup/Papierkorb | Destruktive, nicht an den Task-Baum gebundene Papierkorbaktionen sind für gebundene Worker gesperrt. |

Der Prüfrunner weist auf Windows den Start zurück, wenn der bestehende Prozessbaum-Schutz über `psutil` fehlt. Bei Prüfungsergebnissen werden Erfolg, Fehler, Timeout und Exitcode getrennt ausgegeben. Ein Exitcode ungleich null ist kein erfolgreicher Lauf, auch wenn kein Text ausgegeben wurde.

## Änderungen und Wiederaufnahme

[`worker_git.finish_task`](../../system/hub/worker_git.py) prüft getrackte Änderungen und nicht ignorierte neue Dateien vor dem Staging. Secret- und Git-Leseprüfungen schlagen geschlossen fehl, wenn Git oder ein Datei-Read nicht verlässlich antwortet. Der Test-Gate liest geänderte und neue Testdateien, bevor `git add -A` ausgeführt wird.

Bei fehlender Lease, geänderter Taskversion, unklarer Sperrlage, abgebrochenem Runner oder unbekanntem ACK wird nicht blind wiederholt. Zuerst ist der native Task-/Lease-Zustand zu lesen. Für einen Worker ohne registrierten Task-Baum bleiben nur die ausdrücklich begrenzten Nur-Lese-Aufrufe verfügbar; Mutationen und gebundene Prüfungen bleiben gesperrt.

## Gebundene Prüfziele

Bei `compileall`, pytest, Ruff, mypy und pyright werden bekannte Quell-, Konfigurations-, Report-, Cache- und temporäre Pfade gegen den registrierten Task-Arbeitsbaum geprüft. Unbekannte oder mehrdeutige Prüfoptionen werden vor dem Prozessstart abgewiesen. `compileall` erhält einen Task-lokalen Python-Bytecode-Cache; mit `-b` liegen Bytecode-Dateien neben den gebundenen Task-Quellen. pytest erhält Task-lokale Temp-, Cache- und Coverage-Ziele sowie auf den Task-Baum begrenzte Testsuchen; Ruff und Typechecker erhalten Task-lokale Cacheziele. Ein geerbtes `BACH_DB` wird für den Prüflauf durch eine Datenbank im Task-Arbeitsbaum ersetzt. npm ist nur für den vorhandenen Testskriptaufruf zugelassen und erhält einen Task-lokalen Cache. Bekannte temporäre, Konfigurations- und Cache-Umgebungsvariablen werden auf Ziele im Task-Arbeitsbaum gesetzt. Der Testlauf im gebundenen `finish_task` nutzt den freigegebenen Interpreter mit `python -m pytest` im selben Prüfpfad und wertet ein typisiertes `core.sandbox.SandboxResult` mit Exitcode, Timeout und Speicherstatus aus; fehlende oder unbekannte Ergebnisformen sperren den Abschluss.

Die Bindung begrenzt die erkannten CLI-Ziele und Umgebungsvariablen. Sie ist keine Betriebssystem-Sandbox: ausgeführte Tests, Plugins, npm-Skripte oder andere Programmteile können eigene Seiteneffekte auslösen, die nicht aus den Prüfargumenten hervorgehen.

## Grenzen und Nachweise

Diese Anwendung ist keine Betriebssystem-Sandbox. Sie bindet die aufgeführten Workeraktionen an Task, Sitzung, registrierten Git-Arbeitsbaum und aktuelle Sperrbelege. Sie verleiht dem Worker keine vollständige Dateisystemisolation und macht eine Musterliste für Geheimnisse nicht zu einem vollständigen Geheimnisdetektor.

Regressionen liegen unter [`test_worker_write_guard.py`](../../system/tests/test_worker_write_guard.py), [`test_bound_worker_git.py`](../../system/tests/test_bound_worker_git.py) und [`test_worker_git.py`](../../system/tests/test_worker_git.py). Ein vorhandener Testquelltext ist noch kein Laufnachweis. Codeprüfung, Mac-Testlauf, Integration, Installation und tatsächlicher Workerbetrieb bleiben getrennte Belege.
