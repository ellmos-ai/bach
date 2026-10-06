# T211214113 – korrekte Erfolgsrückgabe beim Seal-Update

## Symptom und Ursache

Der tatsächliche Identity-Writer verwendet `INSERT OR REPLACE`. Das verschiebt
eine SQLite-rowid von 1 nach 2. Das bisherige Seal-Update mit `WHERE rowid=1`
meldete danach Erfolg, obwohl keine Zeile verändert wurde. Der Fehler besteht
auf Laptop-/Mac-Quellständen vor und nach der akzeptierten PR175-Migration;
er ist keine Migrationregression.

`instance_id` ist laut `schema_distribution.sql` und PR175 der fachliche
Primärschlüssel. Mehrere Identityzeilen sind zulässig; ein aktiver Selektor für
mehrdeutigen Bestand fehlt. Deshalb kann dieser Handler ausschließlich eine
eindeutige, nichtleere Text-Identity aktualisieren. Es gibt keine fachliche
rowid=1-Garantie.

## Fix und Grenzen

Nur `SealHandler._update_kernel_hash` ändert sich. Eine eigene
`BEGIN IMMEDIATE`-Transaktion schützt die Auswahl. Das Update verwendet den
Primärschlüssel, verlangt genau eine betroffene Zeile und prüft vor dem Commit
die Zielwirkung sowie alle unveränderten Nichtzielwerte. Trigger mit keiner
Wirkung, rückgängig gemachter Wirkung oder zusätzlicher Änderung werden
verweigert und zurückgerollt. Erfolg verlangt ein tatsächliches Commit und
keine verbleibende eigene Transaktion. Fehlende DB/Identity, Mehrdeutigkeit,
NULL/ungültige Identity und ungültiger neuer Hash liefern `False`.

Ein bestehender NULL-Kernelhash darf mit einem gültigen Hash repariert werden.
Eine bereits aktive vom Caller bereitgestellte Transaktion wird verweigert,
ohne sie zu schließen, zu committen oder zurückzurollen. SQLite-/Cleanupfehler
liefern `False`; dieser Wert ist bei nicht behebbaren I/O- oder Cleanupfehlern
keine absolute Garantie ausbleibender Dateiwirkung. Die Tests prüfen tatsächliche
Commit-/Rollbackwirkung durch unabhängiges Reopen.

Distribution-Writer, Reader, Sampling, Schema, T903 und Workflows bleiben
unverändert. Keine Live-Sealierung, Migration oder Runtimeintegration.

## Belege und Prävention

Separater RED-Testcommit: 30 Fälle, davon 25 fehlgeschlagen, fünf bestanden,
keine Skips. Der ursprüngliche Replace-Fall ist auf beiden 13-/14-Spaltenformen
rot. Der minimale Fix und vier weitere Fehler-/Shadowfälle bestehen unter
Windows mit normaler Projekt-Conftest sowie im isolierten POSIX-Harness:
jeweils 34/34 ohne Skips. Größere oder vollständige Seal-Abnahme ist daraus
nicht abgeleitet.

Alle Daten sind synthetisch in privaten TEMP-Verzeichnissen; HOME und Netzwerk
sind im Testkörper verweigert. Der echte Handler und der echte Writer werden
mit ausdrücklich injizierten Pfaden geladen. Keine Änderung an akzeptierten
Hostbackupbildern. Der neue Test `test_seal_identity_row_contract.py` muss nach
unabhängigem Review vom einzigen Workflowwriter in die permanente CI aufgenommen
werden. Independent Review, CI und tatsächliche Integration bleiben getrennte
Ticketgates.
