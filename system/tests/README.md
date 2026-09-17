# Sichere BACH-Testläufe

Pytest lädt `conftest.py` vor den Testmodulen. Dort werden Datenbank, Backups,
Secrets, Pläne, Fackel-, Slot- und allgemeine Runtime-Pfade in einen privaten
Sitzungsordner umgeleitet. `BACH_TEST_MODE=1` wird an Kindprozesse vererbt und
verbietet reale OneDrive-Prozesssteuerung. Beim Sessionstart wird die
Slot-Konfiguration dort auch auf Disk initialisiert; ein Temp-Pfad allein
genügt für strikte Control-API-Endpunkte nicht.

Zusätzlich blockiert ein Audit-Wächter Schreibzugriffe unter den echten
Checkout-Pfaden `system/data`, `system/system/data` und
`system/tools/llmauto/logs`. Ein Subprozess-Wächter verweigert unter anderem
`OneDrive.exe /shutdown` und Prozessbeendigungsbefehle.

## Prüfpfad

Zuerst die Regressionen und bekannten früheren Verursacher ausführen:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest -q -p no:cacheprovider `
  system/tests/test_suite_isolation_guard.py `
  system/tests/test_cloud_service.py `
  system/tests/test_daemon_service.py `
  system/tests/test_smoke.py `
  system/tests/test_connectors_and_tray.py `
  system/tests/test_slots_and_workers.py `
  system/tests/test_abo_handler.py `
  system/tests/test_chain_control.py `
  system/tests/test_plugin_security.py `
  system/tests/test_security_scan_handler.py
```

Erst wenn dieser Lauf grün ist und keine Runtime-Datei im Checkout entstand,
darf die vollständige Suite folgen:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest -q -p no:cacheprovider system/tests
```

Nach dem Lauf sind der unveränderte OneDrive-Prozess und ein sauberer
`git status --short` bezüglich Runtime-Artefakten Teil des Nachweises. Ein
grüner Testlauf allein genügt nicht.

## Grenze: Vorimport vor pytest

Nur den kanonischen Einstieg vom Repo-Root verwenden: `python -m pytest`.
Ein `python -c`-Harness, das BACH-Module vor pytest und `conftest.py` importiert,
kann Pfade auf produktives `~/.bach` festschreiben, bevor die Test-Umgebung
greift. In einem solchen nichtkanonischen Lauf meldete der Teardown Änderungen
an `bach.db-wal`, `bach.db-shm` und `memoryhooker_audit.jsonl`. Die Meldung
belegt Änderungen während des Laufs, aber nicht allein den exakten Schreiber.
Die produktiven Dateien wurden nicht zurückgesetzt oder gelöscht. Der Guard
gilt erst nach seinem Laden; ein Vorimport liegt außerhalb dieses Vertrags.
