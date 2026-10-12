# Ressourcen-Lease-Status: lesender Schema-Gate

Der Status-Endpunkt liest den vorhandenen Lease-Zustand. Ein GET legt kein Schema an und repariert keine fehlenden Tabellen.

## HTTP-Vertrag

`GET /api/resources/{name}/lease` bleibt durch die vorhandene Geräteauthentifizierung geschützt. Ein passender `X-Lease-Id`-Header darf zusätzlich `own` für die eigene Lease anzeigen; ohne passenden Header wird diese Halterprojektion nicht ausgegeben. Die Lease-ID wird nicht im Status-Ergebnis zurückgegeben.

- `200`: registrierte Ressource und vollständiges Lease-Schema; die Antwort enthält den aktuellen Status.
- `404`: Ressource ist nicht registriert.
- `503`: das Lease-Schema fehlt, ist unvollständig oder kann nicht geprüft werden. Der stabile Fehlercode lautet `resource_lease_schema_unavailable`.
- `401`/`403`: die bestehende Geräteauthentifizierung verweigert den Zugriff.

## Schema-Prüfung

`require_resource_lease_schema()` prüft die erwarteten Tabellen über `sqlite_master`, ihre Spalten und die vollständige Primärschlüsselstruktur der kanonischen DDL über `PRAGMA table_info`. Es führt dabei weder DDL noch Schreibanweisungen oder eine Transaktion aus. Ein fehlendes, unvollständiges oder inkompatibles Schema wird als `ResourceLeaseSchemaUnavailable` gemeldet, statt beim GET stillschweigend verändert zu werden.

Die explizite Schemaeinrichtung und Migration bleiben getrennte Schreibpfade. Der Status-Endpunkt ist kein Migrations- oder Reparaturbefehl.

## Client und CLI

`ResourceLeaseClient.status()` bildet ausschließlich den HTTP-503-Fehler mit dem bekannten Fehlercode auf `ResourceLeaseUnavailableError` ab. Der geerbte `TaskLeaseClient`-Transport wandelt sonstige 5xx-Antworten standardmäßig in `LeaseConnectionError` um. Nur der Resource-Client lässt exakt HTTP 503 mit einem Objekt `detail.code == resource_lease_schema_unavailable` zum bestehenden Mapping durch. Generische 500-/503-Antworten, Authentifizierungsfehler und fehlerhafte JSON-Antworten bleiben fail-closed; sie werden nicht als Schema-Problem umgedeutet. Die CLI zeigt den bekannten Zustand mit `[UNAVAILABLE]` und gibt keine internen Tabellennamen oder SQL-Details aus.

## Prüfgrenze

Die Regressionen prüfen fehlendes und partielles Schema, registrierte Ressourcen im freien, aktiven und freigegebenen Zustand, unveränderte Datenbankdatei sowie unveränderten Transaktionszustand. HTTP-Tests prüfen außerdem, dass Authentifizierung erhalten bleibt. Diese Quell- und Testprüfung führt keine produktive Migration, Registrierung oder Dienständerung aus.
