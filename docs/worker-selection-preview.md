# Native Worker-Auswahlvorschau

Task2260, Quellenlieferung23.10.2026.
Session:01a164ec-6c99-7ae0-8363-4981e58c2954.

## Zweck und Grenze

Die Vorschau erklärt die aktuell gespeicherte Worker-Konfiguration. Sie erwirbt
keine Lease, verändert keine Konfiguration und startet keine Aufgabe, Inferenz,
Werkzeuge oder Dienste. Ein Auswahlmatch ist keine Übernahmefreigabe.
Der vollständige Parent2260 bleibt offen.

Die Berechnung erfolgt im bestehenden nativen Controller mit demselben
_native_task_client() und WorkerLeaseBinding-Selector wie die echte Aufnahme.
Damit gilt dessen konfigurierter Laufzeitdatenbank-/Leadpfad, keine zweite Queue.
Die GUI reicht den authentifizierten Request über den bestehenden lokalen
Control-Adapter weiter; sie berechnet keine eigene Auswahl.

## API

GUI/API: GET /api/system/workers/{worker_id}/selection-preview

Native Control-API: GET /api/workers/selection-preview?id={worker_id}

Beide Grenzen verlangen ihre bestehende Geräte-/Control-Autorisierung.
Optionale Parameter: limit1–100, Standard50; offset0–100000.
Ein expliziter Task-Pin erlaubt ausschließlich offset0.

Rückgabe: bach.worker-selection-preview.v1. Quelle, Worker-ID,
Konfigurationsversion, getrennte Ausführungsprofilversion, Zeitpunkt, Seitenposition, Anzahl dieser Kandidaten,
native gemeldete Gesamtzahl, Fortsetzung, Auswahlmatches und feste Grundcodes.
candidate_count zählt nur die Seite; reported_total ist keine atomare
Gesamtqueue. Jede weitere Seite besitzt einen eigenen Zeit-/Konfigurationsbeleg.

Die automatische Auswahl verwendet unverändert _selection_rejection_reason und
die aktuell gespeicherten Rückgabeversionen des nativen Controllers.
Ein fester Task-Pin verwendet wie der echte explizite Pfad _matches_slot und
fällt bei Ablehnung nicht zur normalen Queue zurück. Review-Grants werden für
die Vorschau niemals erzeugt. Reservierte Review-Pins melden selection=unconfirmed
statt eines unbelegten Matches oder Ausschlusses. Der private Reviewpfad könnte
andere Pickup-Regeln verwenden; die Vorschau erteilt dessen Grant nicht.
Automatischer Review ist keine persönliche Posteingangsfrage.

Höchstens100 Kandidaten und256 unterschiedliche Abhängigkeitszustände pro
Anfrage; mehr als32 Referenzen einer Aufgabe werden als nicht bestätigte
Abhängigkeitsangabe markiert. Keine Titel, Beschreibungen, Prompts, Rohfehler,
Halterdaten, Generationen, Tokens oder Lease-Credentials in der Antwort.
Die Adapterprojektion validiert Schema, Version, IDs, Zeit, Typen, Grenzen,
Grundcodes und Zählerkorrelation und verwirft fremde Felder.

Die gesamte Vorschau besitzt ein gemeinsames Zeitbudget von fünf Sekunden,
geprüft vor und nach jedem synchronen Leseaufruf. Ein bereits laufender Aufruf
behält seinen Transport-Timeout; das Budget unterbricht ihn nicht. Nach Ablauf
beginnt kein weiterer Aufruf. Im Remote-Modus gilt zusätzlich eine gemeinsame
Obergrenze von 128 Leseaufrufen, einschließlich Kandidatenseite, explizitem Pin,
Lease-Reads, Dependency-Snapshots und fehlgeschlagenen Aufrufen. Cachetreffer
verbrauchen keinen weiteren Aufruf. Bei Erschöpfung wird die gesamte Anfrage
als nicht bestätigt abgebrochen (HTTP 503); es gibt keine erfolgreiche Teilseite.

selection_reason übernimmt die tatsächlichen Selectorcodes. Keine Kopie der
Modell-/Slot-/Zuständigkeits-/Pickup-Regeln. Noch nicht integrierte Flags aus
der separaten2261-/2422-Lieferung werden nicht als vorhanden ausgegeben.

## Zusätzliche Beobachtungen

| Code | Bedeutung |
|---|---|
|lease_held|Lease beim Lesen belegt; ohne eigenen Leaseausweis ist keine eigene Halterschaft bestätigt.|
|task_changed|Lease- und Kandidatenbeleg haben verschiedene Taskversionen.|
|lease_unavailable|Leasezustand nicht bestätigt.|
|status_not_pending|Status nicht pending/open; Beobachtung, kein nachgebautes Erwerbsurteil.|
|dependencies_unfinished|Mindestens ein gelesener Vorgänger ist nicht exakt done, wie vom nativen Dependencyvertrag verlangt.|
|dependencies_invalid|Ungültige oder für diese begrenzte Vorschau zu viele Referenzen.|
|dependencies_unavailable|Ein Vorgängerzustand fehlt oder das Lesebudget ist erschöpft.|
|review_route_unchecked|Ein expliziter Pin trägt einen reservierten Reviewmarker; keine Reviewautorität erteilt.|

## Keine Zulassungsentscheidung

claimability bleibt not_checked, snapshot_atomic bleibt false und
configuration_saved bleibt false. unchecked_gates benennt atomaren Erwerb,
Creator-Priorität, Reviewautorität, Provider, Quellregister, Werkzeugrechte,
Ressourcen, tatsächliches Laufprofil und Startup-Recovery ausdrücklich als
ungeprüft. Fehlende Beobachtungsgründe sind kein positiver Nachweis dieser
Schritte. Anbieterfehler oder persönliche/externe Freigaben werden nicht als
fiktive Dependency- oder Leasegründe ausgegeben.

configuration_version bezeichnet denselben bearbeitbaren Konfigurationsbeleg
wie GET workers/configuration. execution_profile_version ist der getrennte
native Ausführungsprofil-Digest. Zustimmung zum Dauerbetrieb und dessen
tatsächlicher Lauf werden damit nicht gleichgesetzt.

Nach der Beobachtung werden beide Versionen und die native Lauf-/Rückgabezuordnung
erneut verglichen; Änderungen beenden die Anfrage als nicht bestätigt.
Tasks und Leases können jederzeit wechseln. Nur der spätere native
Erwerbs-/Ausführungsvertrag entscheidet über die echte Handlung.

Die bestehenden kanonischen TaskLeaseClient-Lesewege rufen additive
Schemainitialisierung auf. Diese Vorschau führt keine Task-/Lease-/Queueupdates
ein, ist jedoch kein SQLite-mode=ro-Zugang zu einer unmigrierten Datenbank.
Vor einer produktiven Freigabe müssen die nativen Schemavoraussetzungen erfüllt
und separat bestätigt sein; diese Quelle führt keinen Produktivaufruf aus.

## Lieferung und offene Abnahme

Historische2260-/2261-Quellen, Resultate und Reviews bleiben erhalten.
Dieser Schritt liefert die native Vorschau gespeicherter Konfiguration.
Noch offen: hypothetische Änderungen vor dem Speichern; globale Defaults und
Worker-Overrides bei allen Materialisierungs-/Resetwegen; Integration der
vorhandenen2261-/2422-Quelle; GUI-/CLI-Bedienung; vollständige Default-/Vorschau-/
Queue-Parität und native Laufzeitabnahme. Keine Kindtask wird damit angenommen.

Der ursprüngliche Quellenslice enthielt keine neuen Testfälle. Der Budget-Fix
ergänzt isolierte Regressionen für langsame und fehlgeschlagene Reads,
Kandidaten, Dependencies, explizite Pins und den schnellen Normalfall.
Statische Syntax-/Diffprüfung und unabhängiger Quellenreview werden getrennt
dokumentiert. Automatische bestehende PR-CI ist ein eigener
Beleg und ersetzt die offenen Fokus-/Regressions-/Geräteabnahmen nicht.
Kein Deploy, Workerstart oder aktive Konfigurationsänderung.
