# Native Dialoge und Taskverlauf

## Schnittstellen

Geräteauthentifizierte, ausschließlich lesende GUI-Endpunkte:

- GET /api/agent-history/sessions: gespeicherte aktuelle und archivierte Transkriptausschnitte. agent_id und archive filtern vor Zählung und Pagination.
- GET /api/agent-history/sessions/{id}: sichtbare Nachrichten eines gespeicherten Ausschnitts. Profiltranskripte verlangen die explizite, weiterhin verifizierte Profilbindung.
- GET /api/agent-history/tasks: dauerhafte Taskereignisse. task_id und aktueller status sind kombinierbar; Seitenlimit 1 bis 100.

Alle Leser öffnen die vorhandene kanonische bach.db schreibgeschützt. Sie erstellen keine Datenbank und starten keine Provider. Fehlende Quellen ergeben HTTP 503, fehlende Transkripte 404 und unbestätigte Profilbindungen 409.

## Speicherstand

Die vorhandene SessionStore-Persistenz speichert regulär höchstens 40 Nachrichten und 24000 Zeichen pro Nachricht. Diese Ansicht zeigt vorhandene Ausschnitte und Archive. Bereits abgeschnittene Nachrichten können nicht rekonstruiert werden; ein vollständiges Nachrichtenjournal ist eine separate Erweiterung.

Systemnachrichten und private Reasoning-Felder werden nicht projiziert. Nachrichtentexte werden in der GUI als Text dargestellt. Referenzierte Aufgaben sind Links, kein eigener fachlicher Abschlussnachweis. Der Taskverlauf projiziert Metadaten und Statusänderungen, keine Akteure oder geänderten Beschreibungsinhalte.

## Ältere Archive

Ein älteres v1-Archiv ohne das optionale Feld chat_id wird mit einer leeren Transportkennung gelesen, wie beim bestehenden Snapshotleser. Explizites JSON-null und ungültige Metadatentypen bleiben Quellenfehler. Eine vorhandene Profilbindung bleibt verbindlich; ein Archiv ohne passende Profilkennung wird nicht als Profiltranskript freigegeben. Die Leser verändern keine gespeicherten Archive.

## Auslieferungsnachweis

Der Quellstand und eine installierte Abnahme sind getrennte Nachweise. /api/gui/kit-manifest prüft die aktive Distribution gegen den gepinnten Commit und die Dateihashes. Der native Aufgabenbeleg in Task1938 enthält Review-, CI- und Deploymentnachweise sowie offene Abnahmegrenzen.
