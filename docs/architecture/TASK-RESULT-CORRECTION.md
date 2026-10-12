# Task-Ergebnisse: Abnahme, Korrektur und Ausgabegrenze

Dieses Dokument beschreibt den API-Vertrag aus Task #2136. Es belegt weder
eine produktive Runtime-Installation noch die Provisionierung eines Result-Operators.

## Unterstützung erkennen

Vor dem Erstellen einer Task kann ein Client GET /api/task-capabilities lesen.
Die Headless-API stellt denselben Vertrag unter
GET /api/v1/task-capabilities bereit:

    {
      "schema": "bach.task-capabilities.v1",
      "result_max_chars": {
        "supported": true,
        "min": 1,
        "max": 3000,
        "nullable": true
      }
    }

Der Endpunkt liegt vor dem dynamischen Pfad /api/tasks/{task_id}. Ein altes
Backend ohne diesen Endpunkt oder ohne das bekannte Schema gilt für diese
Funktion als nicht verfügbar. Clients senden dann kein result_max_chars und
keine Korrekturanfrage. Sie leiten Unterstützung nicht aus einem unbekannten
Fehler oder einem vorhandenen Operator-Token ab.

GET /api/tasks/{task_id} projiziert result_max_chars als nullable Feld.
Ein fehlender Wert ist null. So bleibt auch eine unbegrenzte Bestands-Task
eindeutig von einer alten API ohne dieses Feld unterscheidbar.

## Ausgabegrenze

result_max_chars ist bei GUI- und Headless-Create/Edit optional. Zulässig sind
nur echte Ganzzahlen von 1 bis 3000; boolesche Werte, Zeichenketten und Werte
außerhalb dieses Bereichs werden vor einer Mutation abgewiesen. Bei Edit entfernt
ein ausdrücklich gesetztes null die Grenze. Bei Create oder Edit ohne das
Feld bleibt der bisherige unbegrenzte beziehungsweise gespeicherte Wert bestehen.

null wird aus dem Task-Inhaltsdigest ausgelassen. Deshalb ändern fehlende und
nullable null Werte die Legacy-Digests und die daran gebundenen aktiven
Leases nicht. Ein gesetzter numerischer Wert gehört zum Inhalt und ändert dessen
Version. Eine Submission über dem Limit wird anhand des Task-Readbacks vor Beginn der
Release-Transaktion abgewiesen und unter der Schreibsperre erneut geprüft. Die
Ausführungslease bleibt bestehen, damit der Worker ohne erneutes Ausführen des
bereits abgeschlossenen schreibenden Tools ein gekürztes Ergebnis abgeben kann.

## Ergebnis-Korrektur

Korrektur ist eine getrennte Operatorfähigkeit. GET /api/tasks/{task_id}/result
projiziert operator_capabilities.request_correction. Alte Result-Operatoren
bleiben accept only; ein Token allein beweist keine Korrekturberechtigung.

POST /api/tasks/{task_id}/result/correction verwendet den Header
X-BACH-Result-Operator und bindet den Request an das zuletzt gelesene Ergebnis:

    {
      "result_id": 59,
      "result_sha256": "<64 kleingeschriebene Hexzeichen>",
      "generation": "worker-generation",
      "fence": 7,
      "task_version": "<64 kleingeschriebene Hexzeichen>",
      "status_revision": 145,
      "request_id": "UUIDv4",
      "correction_note": "Konkrete Ergänzung, höchstens 1200 Zeichen."
    }

Der Handler prüft Operator-Scope und alle Versions-/Ergebnisbindungen in einer
Transaktion. Erfolg liefert bach.task-result-correction-request.v1, eine
correction_id, correction_round, Quellresultat-ID/-SHA, status: pending,
next_task_version und replayed. Dieselbe Request-ID ist idempotent.
Geändertes Ergebnis oder Task-Readback führt zu 409 result_changed_reload;
fehlender Korrekturscope zu 403 result_operator_correction_scope_required;
ungültiger Request zu 422 correction_request_invalid. Ein Client wiederholt
einen unbekannt beendeten POST nicht mit einer neuen Request-ID.

Die Anfrage erhält das ursprüngliche Resultat samt Digest. Sie überschreibt
keine Originalbytes. Die nächste Abgabe muss an eine neue Worker-Generation
gebunden sein; sie ersetzt das frühere Ergebnis nicht in der Historie.

## Historie und gebundener Korrekturkontext

GET /api/tasks/{task_id}/result/history?before_event_id=&limit= liefert
bach.task-result-history.v1 mit events, next_before_event_id und has_more.
Die Ausgabe ist neueste zuerst; der Cursor ist exklusiv,
limit liegt zwischen 1 und 50. Unterstützte Ereignisse sind:

- result_submitted: Ergebnis-ID, SHA, Originaltext, Generation, Fence und
  Taskversion;
- correction_requested: Korrektur-ID/-Runde, Quellresultat-ID/-SHA, Hinweis
  und Request-ID;
- result_accepted: angenommene Ergebnis-ID und SHA.

occurred_at ist kanonisches UTC-ISO mit Z. Die Zeitdeutung folgt dem nativen
Lease-Parser: ein naiver T-Zeitstempel ist lokale Lead-Zeit, ein SQLite-Wert
mit Leerzeichen ist UTC; explizite Offsets bleiben maßgeblich. Ein ungültiger
Zeitstempel wird nur aus einem ebenfalls geprüften task_history.changed_at
ersetzt, nie durch blindes Anhängen von Z.

Die Abfrage liest pro Ereignisquelle höchstens min(max(limit * 10, 100), 500)
Kandidaten und verwendet task-, Ereignis- und Aktionsindizes. `has_more=true`
gibt es nur mit einer vollen Seite und mindestens einem weiteren verifizierten
Ereignis; der exklusive Cursor ist dann die ID des letzten ausgegebenen
Ereignisses. Reicht das begrenzte Suchfenster nicht aus, um volle Seite und
Folgeereignis zu belegen, antwortet der Server mit 503
`result_history_unavailable`, statt eine widersprüchliche Teilseite zu liefern.
Beschädigte oder nicht zur Auditzeile passende Ergebniskandidaten werden ebenfalls
nicht still aus der Erfolgsausgabe entfernt. GET führt keine Schemaänderung aus.
Fehlen für eine vorhandene Ergebnistabelle die erforderlichen Indizes, antwortet
der Server ebenfalls mit 503, bis ein regulärer Schema-/Writepfad sie bereitstellt.

Korrekturhistorie wird gegen die zugehörige `task_history`-Zeile geprüft. Dazu
gehören ID, Request-ID, Runde, Quellergebnis-ID und -SHA, Generation, Fence,
Quell-Taskversion, Statusrevision, Hinweis, nächste Taskversion, anforderndes
Operatorgerät und Zeitstempel. Diese Bindungsfelder werden geprüft, ohne das
History-DTO um interne Versionen oder Geräte-IDs zu erweitern. Ein vorhandener
nicht-NULL-Korrekturzeiger muss auf ein vollständiges, auditgebundenes Ledger
zeigen; ein defekter Zeiger führt zu einem nicht bestätigten Korrekturkontext.
Ein fehlendes Feld oder ein explizit NULL gesetzter Zeiger bleibt ein Legacyfall.
Eine gültige Korrektur, deren Quellresultat bereits durch eine neuere Abgabe
überholt wurde, bleibt in der Historie, ist aber kein aktiver Promptkontext.

Eine aktive Task-Lease kann ihren Korrekturkontext über
GET /api/tasks/{task_id}/lease/correction-context abrufen. Die Lease-ID steht
nur im X-Lease-Id-Header. fence, task_version und generation werden als
Query-Bindung geprüft. Fehlt eine exakte Übereinstimmung, ist der Kontext
unavailable. Ein früheres Ergebnis ist untrusted Datenkontext, keine Anweisung.
Ohne Korrekturanfrage bleibt der bisherige Worker-Prompt unverändert.

## Abnahmegrenzen

Der Server ändert Taskstatus, Korrekturhistorie und Versionsbindung atomar.
Operator-Credentials werden durch diesen Sourceumfang weder ausgegeben noch
neu provisioniert. GUI-/Native-Integration, Runtime-Deployment und eine
fachliche Abnahme eines korrigierten Ergebnisses bleiben getrennte Schritte.
