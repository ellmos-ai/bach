# T797: private Journal-Mutationsgrenzen

Autorencheckpoint nach statischer Vertragsabnahme des Entwurfs `f9aec97`.
Aktuelle integrierte Defaultbasis `7120cd1e`; Lease-Teilstand `5d465db3` bleibt
unverändert und ist separat unabhängig lokal abgenommen. Dieser Journal-Code
benötigt seine eigene unabhängige Nachabnahme. Kein Runtime-/Volltransferclaim.

## Vorher tatsächlich rot

Testcommit `c0088367` enthält die drei ursprünglichen Reviewer-Assertions,
unverändert bis auf den Importpfad zur permanenten Suite. Alle drei waren rot:
Während der echten letzten Hashprüfung erlosch der Guard, anschließend änderten
Forward-Move, Undo-Move und Undo-Copy dennoch Source/Target-Bytes.

## Tatsächliche Implementierung

Der BACH-Wrapper bindet unveränderte vertrauenswürdige Nemo-Codeobjekte mit
`types.FunctionType` an pro Consumer private Funktions-Globals, Klassen und
Filesystem-Primitives. Kein `eval`/`exec`, kein globaler Monkeypatch, kein zweiter
Journal-/Undoalgorithmus. Ursprüngliche statische Methoden bleiben statisch;
Querverweise auf `ActionJournal` und `self.path` erreichen den privaten Consumer.
Moduleigene sonstige Globals bleiben erhalten, insbesondere `dataclasses.replace`
im Undo-Helper. Die Hashhelfer werden ausschließlich lesend aus ihrem jeweiligen
Originalmodul aufgerufen; Fault-Instrumentierung der Hashprüfung bleibt beobachtbar.

Private Path-Ableitungen behalten den Owner. `replace`, `unlink` und auch rekursive
`mkdir` prüfen unmittelbar vor der echten Mutation erneut Scope und Hostguard.
Journal-/Target-Temporaries, FD-Öffnung, Teilwrites, Flush, Fsync, Commit-Rename und
Cleanup-Unlink haben eigene private Grenzen. Unbekannte mutierende Proxyattribute
und fremde FD werden verweigert. Ein zusätzlicher Instanzlock verweigert gleichzeitigen
und rekursiven Eintritt in denselben Consumer, auch während der Host-Lease-Akquisition.

Die Streams arbeiten unbuffered. Kurze Writes werden vollständig fortgesetzt mit
frischer Freigabe pro Teilwrite; null/ungültiger Fortschritt wird verweigert.
Alle eigenen Handles werden im Fehlerfall geschlossen. Erlischt der Guard, darf
auch Cleanup keine Datei löschen: Ein eigener Temp-Rest bleibt über
`retained_temporary_paths` messbar und ist kein Erfolgsreceipt. Kein automatischer
Cleanup-/Reconcile-Job und keine echte Hostlease-Anbindung.

## Grenzen und Belege

Der Host muss weiterhin tatsächlich einen exklusiven Lease-/Lock-Kontext für
sämtliche Pfade/Elternverzeichnisse bis zum Kontextende halten. Die Fixtures belegen
den Consumervertrag; sie beweisen keine installierte Runtime-Guardimplementation.
Alle vier Nemo-Dateien und die LICENSE bleiben bytegleich `861a3ca5`.

Der enge Gesamtlauf enthält die bisherigen 138 Sicherheitsfälle plus 18 neue
Journal-Grenzfälle, ohne Skip. Geprüft werden die drei Original-Gegenfälle,
alle Persistenzprimitives, Cleanup nach Revocation, Handleabschluss, kurze/abgebrochene
Writes, Same-Consumer-Reentry mit Threads, gleichzeitige unabhängige Consumer,
private Path-Ableitungen/staticmethods und unveränderte Originalglobals.

```text
python -m pytest system/tests/test_imported_journal_countercases.py system/tests/test_imported_journal_safety.py system/tests/test_imported_lease_transaction_modes.py system/tests/test_imported_lease_countercases.py system/tests/test_imported_lease_safety.py system/tests/test_imported_capabilities.py -q
```

Ruff für Wrapper und neue Grenztests sowie `git diff --check` bestehen.
Provenienz, dauerhafte CI und das Vollticket bleiben getrennte Restgates.
