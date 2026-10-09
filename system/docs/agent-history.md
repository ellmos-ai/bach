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

## Stand

Quellimplementierung vorhanden; Veröffentlichung, unabhängiges Review und installierte Abnahme dieses Pakets stehen noch aus.
