# Report-Provider: Control-Owner und GUI-Anbindung

Der gemeinsame Providervertrag enthält neutrale DTOs und optionale Provider-Entry-Points.
Die konkrete persönliche Berichtpipeline und ihre Konfiguration bleiben privat.

## Zuständigkeit

- Der Control-Dienst bindet den bereits vorhandenen ChatRuntime und einen fest konfigurierten Agenten.
- Der aktuelle Registry-Reader prüft die gepinnte Agenten-, Skill- und Governance-Konfiguration vor dem Dispatch erneut.
- `ControlReportOwner` stellt hierfür einen eigenen, vom Control-Dienst verwalteten Eventloop bereit. Er erzeugt keinen weiteren ChatRuntime, Modellbackend, Speicher oder Bestätigungs-Issuer.
- Die Provider-Hostfactory und ihre Ports bleiben vom HTTP-Transport und diesem BACH-Lebenszyklusadapter getrennt. Die gemeinsame Funktion gehört bei der Ausgliederung in das passende Ocean-Modul; BACH behält diese Control-Anbindung.

## Feste Schnittstelle

| Methode | Control-Pfad | Eingabe |
| --- | --- | --- |
| GET | /api/reports/capabilities | keine |
| GET | /api/reports/sources | genau subject_ref |
| GET | /api/reports/status | genau run_id |
| GET | /api/reports/watcher/status | keine |
| POST | /api/reports/prepare | ReportRequest v1 |
| POST | /api/reports/finish | run_id und approval |
| POST | /api/reports/cleanup | run_id und approval |
| POST | /api/reports/watcher/configure | WatcherConfig v1 |
| POST | /api/reports/watcher/tick | leeres JSON-Objekt |

Control prüft Token und Origin vor dem Lesen von Abfragen oder Body. POST verlangt JSON.
Der Body ist auf 256 KiB begrenzt; doppelte JSON-Schlüssel, nicht endliche Zahlen,
mehrdeutige Abfragen und zusätzliche Transportfelder werden abgewiesen.
JSON-Container dürfen höchstens 32 Ebenen tief verschachtelt sein; die regulären DTOs bleiben weit darunter.
Der Host validiert anschließend den vollständigen fachlichen DTO-Vertrag.

Der einzelne Control-Adapter benötigt Host/API und Tests aus Task #2106.
Im zusammengesetzten Source-Stand sind diese Teile integriert; der Source-Mount ist
mit dem tatsächlichen GUI-Server geprüft. Die GUI stellt dieselben Pfade über ihren
authentifizierten Device-Transport bereit.
Sie spricht ausschließlich das identifizierte Control-Ziel an und importiert keinen
zweiten Control-/Telegram-Dienst.

## Start und Ende

Der vertrauenswürdige Control-Start erhält Hostabhängigkeiten als bereits konstruierte
Objekte über `start_control_api(report_host_dependencies=...)`.
Das konfigurierte `reports`-Objekt darf nur `enabled`, `provider_name` und
`agent_id` enthalten. Requestdaten wählen keine Factories, Modelle oder lokalen Pfade.

Ohne explizite Konfiguration oder Hostabhängigkeiten bleibt Reports unavailable;
es wird kein Report-Thread gestartet. Ein installiertes Providerpaket allein ist
kein produktiver Anschluss.

Ein RPC-Timeout beendet keinen möglicherweise bereits wirkenden Finish-/Watcher-Aufruf.
Die Antwort bleibt unknown; der Caller darf daraus keinen erneuten Schreibversuch ableiten.
Beim Schließen nimmt der Owner keine neuen Aufrufe an und lässt bereits angenommene
Aufrufe auslaufen. Ist das Auslaufen nach der begrenzten Wartezeit nicht beendet,
meldet der Dienst diesen Zustand; er behauptet keinen abgeschlossenen Shutdown.

## Abnahmegrenzen und offene Anschlüsse

Die Transport-/Lifecycle-Regressionssuite prüft feste Routen, Framing, Start/Ende
und das Auslaufen eines zeitüberschreitenden Aufrufs ohne Modellinferenz.
Die Transportprüfung verwendet einen flüchtigen lokalen HTTP-Server.
Sie ersetzt keine produktive Prüfung der privaten Berichtpipeline.

Weiterhin separat erforderlich sind die private Konfigurationsbereitstellung,
persistente Artefaktspeicher, native Receipt-Authority, authentifizierte menschliche
Bestätigung und deren tatsächliche UI/CLI-Caller. Diese dürfen nicht durch Testports
oder selbst ausgestellte Agentenfreigaben ersetzt werden.

Die Transportregressionen prüfen zusätzlich einen flüchtigen Loopback-HTTP-Server mit den tatsächlichen ControlHandler-Methoden und dem vorhandenen Tokenprüfer. Alle neun Routen dispatchen auf den einzigen Owner-Loop; Auth-/Origin-/Content-Type-/Größen-/JSON-Abweisungen führen zu null Hostcalls. Der Modellport bleibt ein RecordingHost. Ein zusätzlicher Integrationstest verwendet das tatsächliche gui.server.app einschließlich DeviceAuthMiddleware und alle neun registrierten Reports-Routen. Der GUI-Client erreicht über echtes Loopback-HTTP den einzigen Owner-Loop. Der Geräteverifier und der Reporthost sind isolierte Testports; fehlende und widerrufene Gerätekennungen führen zu null Hostcalls. Dies belegt den Source-Mount und den Transport, keine native Geräte- oder private Report-Abnahme.

## Auswahl der Control-Zugangsdaten

Ein gesetzter BACH_CONTROL_API_TOKEN hat Vorrang. Wird BACH_CONTROL_API_TOKEN_FILE ausdrücklich gesetzt, ist allein diese Datei die nächste Quelle: fehlend, leer, nicht lesbar oder ungültiges UTF-8 bedeutet unavailable. Es erfolgt dann kein Rückfall auf einen anderen Standardschlüssel oder Keyring. Ohne expliziten Dateipfad bleibt die bestehende Standardschlüssel-/Keyringauflösung erhalten.

## Installierte Hostabhängigkeiten und Operator-Client

Der Control-Einstieg lädt optionale Hostabhängigkeiten beim Start über
`load_report_host_dependencies(CONFIG.get("reports"))`. Nur ein vollständig
valides, ausdrücklich aktiviertes Objekt mit `enabled`, `provider_name` und
`agent_id` erlaubt die Auswahl. Im installierten Entry-Point-Verzeichnis
`ellmos.report_host_dependencies` muss genau eine Factory mit dem konfigurierten
Providernamen vorhanden sein. Sie erhält keine Argumente und löst ihre eigene
private Konfiguration auf. Der öffentliche Loader enthält keine privaten Pfade,
Vorlagen, Modelle oder Zugangsdaten.

Die Factory liefert ausschließlich die vorhandenen Hostabhängigkeiten
`word_template`, `anonymizer`, `document_reader`, `operator_confirmation` und
`cloud_model`, soweit konfiguriert. Der bestehende Hostassembler prüft deren
Ports. Das lokale Modell bleibt an den vorhandenen ChatRuntime und seinen
Governance-Vertrag gebunden. Fehlende, mehrdeutige oder fehlerhafte Plugins bleiben
unavailable; es gibt keine Auswahl eines Ersatzproviders und keine neue Runtime.
Ein installierter Python-Entry-Point ist vertrauenswürdiger Hostcode, keine Sandbox.

Der BACH-Editable-Install registriert `ellmos.report_clients / bach-control` mit
`bach_report_client:create_report_control_client`. Der Root-Shim findet den
Systemcode relativ zu seiner eigenen Installation. Der Client verwendet exakt
den vorhandenen GUI-Control-Transport mit seinen neun festen RPC-Pfaden,
konfigurierter Zielauflösung, Identitätsprüfung und Authentifizierung. Die
Konstruktion startet weder Netzwerkverkehr noch Inferenz und stellt keine
menschliche Bestätigung aus. Es gibt keine URL- oder Tokenparameter im Factoryvertrag.
Die private Operator-CLI muss diesen installierten Client ausdrücklich konsumieren.

Dieser Anschluss ergänzt den bestehenden quellgebundenen Editable-Install; er
behauptet keinen eigenständigen BACH-Wheel mit vollständig enthaltenem Systembaum.
Die produktive private Hostfactory, sichere persistente Ports, menschliche
Bestätigung und tatsächliche Berichtausführung bleiben gesondert abzunehmen.
