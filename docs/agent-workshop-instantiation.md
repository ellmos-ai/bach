# Agentenvorlagen: aufgezeichnete Revisionen und Kopien

Session: 01a164ec-6c99-7ae0-8363-4981e58c2954 · codex@ASUS-GEI · 2026-10-23
Task: #1951

## Definition und Instanz

Der bestehende Blueprint-Schreibdienst bleibt die Quelle für Definitionen.
Materialisieren und Starten verwenden weiterhin die bestehenden, getrennten
Controllerpfade mit Blueprintversion und Konfigurationsversion.
Ein Speichern, Kopieren oder Wiederherstellen startet keinen Worker und
aktualisiert keine bereits materialisierte oder laufende Instanz.

## Unveränderliche Aufzeichnungen

Beim nächsten regulären Save wird die zuvor beobachtete Definition und danach
die neue Version im selben SQLite-Schreibvorgang aufgezeichnet. Jede Aufzeichnung
enthält ID, Version, Definitionsinhalt, Herkunft, SHA-256 und Erfassungszeit.
Die Tabelle erlaubt keine UPDATE- oder DELETE-Operation; eine abweichende
Aufzeichnung derselben ID/Version bricht den gesamten Schreibvorgang ab.
Pro Aufzeichnung gelten maximal 768 KiB. Laufzeitstatus und veränderliche
Verfügbarkeitsmeldungen eines Paketproviders gehören nicht zur Definition.

Die additive Initialisierung läuft über `ensure_blueprint_schema`, wie die
bestehenden Blueprintmigrationen. Historien-GETs öffnen ausschließlich eine
lesende Verbindung und legen weder Schema noch Seed-Daten an. Die Historie
meldet `storage_ready` und `legacy_history_complete=false` ausdrücklich.
Vor Einführung nicht gespeicherte Revisionen können nicht rekonstruiert werden.
Paketprovider und Seeds werden nicht rückwirkend als vollständige Historie
zertifiziert. Aufgezeichnete Revisionen bleiben bei einer späteren Löschung der
aktuellen Uservorlage erhalten; Historienliste und Einzelabfrage können sie weiterhin lesen. Die Historienliste
meldet in diesem Fall `definition_deleted=true` und `current_version=null`.

## Kopieren und Herkunft

`clone_blueprint` erzeugt mit neuem Namen eine Uservorlage. Der Aufrufer nennt
die aktuelle Quellversion und den bereits vorhandenen `content_sha256` aus der
Blueprintliste. Dieser bestehende Hash ist der semantische Governance-Pinhash;
der separate `snapshot_sha256` schützt die gesamte aufgezeichnete Definition.
Die Quelle wird im Schreibvorgang erneut aufgelöst und archiviert.
`derived_from={blueprint_id, version, sha256}` bleibt nach Erstellung unveränderlich.
Änderungen am Inhalt der Kopie erzeugen regulär eine neue Version.
Die Systemvorlage wird dabei nicht verändert. Herkunft erteilt keine zusätzlichen
Werkzeugrechte und ersetzt keine Governance-Vererbung oder Ressourcenadmission.
Der reguläre Save akzeptiert denselben expliziten Herkunftspin für Clients,
die eine Kopie bereits im Editor bearbeiten.

## Authentifizierte HTTP-Schnittstelle

Alle folgenden Wege verlangen eine aktive Geräteanmeldung. Das Präfix lautet
`/api/agent-studio/blueprints/{id}`:

| Methode und Suffix | Inhalt |
| --- | --- |
| GET `/revisions?limit=50&before_version=...` | Aufgezeichnete Versionen; höchstens 100 pro Seite |
| GET `/revisions/{version}` | Definition und verifizierter Snapshot-Hash |
| GET `/revisions/diff?from_version=1&to_version=2` | Geänderte Felder und begrenzter Textvergleich |
| POST `/revisions/{version}/restore` | Body: `{"expected_version": 3}` |
| POST `/clone` | Body: `{"name":"eigene-kopie","expected_version":1,"source_sha256":"..."}` |

Der Textvergleich meldet eine Kürzung bei mehr als 128 Ki Zeichen.
Wiederherstellen erzeugt eine neue Version mit `restored_from_version`.
Die aktuelle erwartete Version bleibt verbindlich. Systemvorlagen bleiben
schreibgeschützt; aktuelle Feld- und Governanceprüfungen bleiben wirksam.
Ein früher gültiger, inzwischen ungültiger Governancepin wird nicht umgangen.
Keine Route verändert Tasks, Instanzen, Profile oder Workerzustände.

## Noch offene Gesamtabnahme

Diese Lieferung ergänzt den nativen Definitionsvertrag. Bedienung von Historie,
Vergleich und Wiederherstellung in der gemeinsamen GUI, vollständige Referenzen
auf externe Persona-/Prompt-/Skillrevisionen, Teams/Staffeln sowie integrierte
Geräte- und Laufzeitabnahme bleiben eigenständige offene Teile von #1951.
Der ergänzte Kopierknopf der gemeinsamen GUI überträgt den Herkunftspin
und verlangt den Backendmarker `blueprint_revision_contract`. Aus früheren
Kopien entsteht rückwirkend keine Herkunft. Die Oberfläche zur Verwaltung
der Revisionshistorie ist noch offen.
Keine Bereitstellung, kein Modellstart und keine Fachabnahme aus Quellcode ableiten.
