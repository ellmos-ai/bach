# T797: Lease-Nachbesserung nach unabhängigen Gegenfällen

Aktuelle Defaultbasis `7120cd1e891a447a8de1bb27f2b57480d47a435b`, regulär mit
dem bisherigen Autorenstand `861a3ca5` integriert (`2265336b`). Kein Reset.
Der Journalcode und dessen vier Nemo-Dateien bleiben bytegleich `861a3ca5`.

Die 17 unabhängigen Temp-Gegenfälle wurden mit unveränderten Assertions in
`test_imported_lease_countercases.py` übernommen; nur der Importpfad wurde
an den permanenten Testsuite-Ort angepasst. Testcheckpoint `55cf3e57`:
**10 fehlgeschlagen, 7 bestanden**, einschließlich vier bestandener Kontrollen
für fremde Caller-Savepoints.

## Enges Produktdelta

- Zeitstempel müssen ein vollständiges tatsächliches Kalenderdatum mit Uhrzeit
  und gültiger optionaler Zeitzone enthalten. Python validiert sie unverändert;
  nur gültige Instants werden in UTC für SQLite verglichen. Julianzahlen,
  Uhrzeiten ohne Datum, unmögliche Tage, unzulässige Minuten-/Stunden-/Sekundenwerte
  und ungültige Zeitzonen werden fail-closed erhalten. Die Validierung steht
  als deterministische Funktion innerhalb der einen atomaren UPDATE-Bedingung.
- Der vorhandene Erzeuger stellt kanonische RFC-4122-UUIDv4 aus. Erneuerung,
  Freigabe und Übernahme einer abgelaufenen Lease verlangen denselben Vertrag.
  NIL ist syntaktisch eine UUID, besitzt jedoch keine zulässige Version/Variante
  dieses Erzeugervertrags; sie darf ebenso wie `not-a-uuid` nicht autorisieren.
- Jede eigene Mutation beginnt ausdrücklich `BEGIN IMMEDIATE`, auch auf einer
  Autocommit-Verbindung. Bei jedem Fehler wird diese eigene Transaktion
  zurückgerollt. Der bereits vor SQL bestehende Guard gegen fremde Transaktionen
  und Savepoints bleibt erhalten. Kein bestehender fremder Inhalt wird committet.

## Belege und Grenzen

17 Reviewer-Gegenfälle plus 15 ergänzende Fälle (Autocommit/Reopen und
Datums-/Offset-/Byte-Unverändertheit) zusammen mit den bisherigen 92 Fällen:
**124 bestanden, null Skips**, 9.70 Sekunden. Alle drei Autocommitfälle wurden
zusätzlich gegen die unveränderten Adapterbytes aus `55cf3e57` ausgeführt:
**3 fehlgeschlagen**, bereits veränderte Zeilen nach `RAISE(FAIL)` tatsächlich
sichtbar. Diese historischen Bytes wurden ausschließlich in eine lokale
Tempdatei geladen; keine Quelldatei und keine Live-Datenbank wurde verändert.

Die Caller-Savepoint-Kontrollen und vier konkurrierende Erstclaims bleiben grün.
Die Änderungen betreffen nur den experimentellen SQLite-Adapter, seine
Gegenfalltests und dieses Receipt. Kein Runtimecaller, keine DB-Migration,
kein Journalfix, keine Workflowänderung und keine Veröffentlichung.
Unabhängige erneute Abnahme steht aus; das Vollticket bleibt offen.
