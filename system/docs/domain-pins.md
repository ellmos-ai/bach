# Domänen-Pins und Menüadoption
Task #1932. Eine gespeicherte stabile Domain-ID erscheint im gemeinsamen Domänenmenü.
Ohne angebundene Fachseite öffnet der Menüeintrag die zugehörige Katalogkarte.

## Native API
GET /api/domains/pins liefert bach.domain-pins.v1: version, persisted, pins und total.
POST /api/domains/{id}/pin verlangt den ausdrücklich gewünschten booleschen pinned-Status und die gelesene version.
POST /api/domains/pins verlangt pinned_ids und version für einen ausdrücklich beauftragten Listenersatz.
Geräteauthentifizierung wird gegen die aktive Device-Registrierung gelesen. Fremde Origins bleiben gesperrt.

Die SHA256-Version bindet den rohen Speicherinhalt. Die Abwesenheitsversion ist fest und persisted=false kennzeichnet Voreinstellungen.
Ein GET erstellt keine Verzeichnisse und ersetzt bei einem unlesbaren Bestand keine Daten.
Legacylisten und Objekte mit pins werden gelesen. Zusätzliche Objektfelder bleiben beim Speichern erhalten.
Stabile IDs dürfen erhalten bleiben, wenn das Modul inzwischen aus dem Katalog entfernt wurde.

## Schreiben und Konflikte
Alle Schreibpfade verlangen CAS, verwenden die gemeinsame Betriebssystem-Sperre und einen atomaren Dateitausch.
Der kanonische Lock-Scanner prüft Eltern und Zwillinge. Eine fehlende Scanner-Konfiguration oder aktive Sperre verweigert den Zugriff.
Ein Link- oder Symlinkpfad wird verweigert. Der aktuelle Dateiinhalt wird vor dem Tausch erneut geprüft.
Die Mutexdatei und vorübergehende Schreibdateien sind gitignored; echte Pinpräferenzen werden durch den Auftrag nicht verändert.

HTTP 428: Version fehlt. HTTP 409: Version geändert. HTTP 423: gesperrt oder ungeprüft.
HTTP 422: ungültige ID/Liste/boolescher Zustand. HTTP 503: Bestand oder Autorisierung nicht lesbar.
Der Browser liest nach einer unbestätigten Antwort erneut und wiederholt keine Mutation automatisch.

## Abnahmegrenze
Unit- und API-Tests verwenden synthetische Speicher, Geräte und Tokens.
Browser-/Deployment-Abnahme, unabhängiger Review und produktive Menüadoption stehen zum Zeitpunkt dieser Notiz noch aus.
