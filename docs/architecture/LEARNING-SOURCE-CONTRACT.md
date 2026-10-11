# Lernquellen-Vertrag v1

Stand: 2026-10-10
Geltungsbereich: Task 1999, gemeinsamer Lernquellen-Handler und begrenzte Quellenadapter

## Zweck und Grenzen

Der Lernquellen-Handler verbindet eine explizit freigegebene, begrenzte Quelle mit einem vom Aufrufer gelieferten Lernvorschlag. Er prüft Herkunft, Hashes, Schema, Signal, Privatsphäre und mögliche Duplikate und erzeugt eine überprüfbare Vorschau. Er entscheidet nicht selbst, welche Erfahrung semantisch wichtig ist, und belegt weder Wiederverwendung noch Ergebnisqualität.

Die Vorschau über analyze ist lesend. Sie kann candidate oder no_candidate liefern und verändert keine Kandidaten, Zieldateien, aktiven Skills oder Scheduler. store legt ausschließlich einen inaktiven, versionierten Prüfkandidaten in den vorhandenen Hermes- beziehungsweise NemoFold-Kandidatenbestand. Es gibt keinen zweiten Kandidatenspeicher und keine direkte Veröffentlichung. Rule-Vorschläge sind Entwürfe ohne Governance-Autorität.

Die nachgelagerte Quarantäne und Review aus der PR-303-Abhängigkeit bleiben maßgeblich. Der Adapter erzeugt keine aktive Skill-Datei und umgeht weder die bestehende Freigabe noch die Promotion. Ein Code- oder CI-Erfolg ist kein Beleg für eine Installation oder einen Lauf auf dem Mac Studio.

## Konfiguration der Quellenwurzeln

BACH_LEARNING_SOURCE_ROOTS ist ein JSON-Objekt aus stabilen Wurzel-IDs und absoluten, vorhandenen Verzeichnissen. Standard ist {}; damit ist keine Lernquelle freigegeben. Beispiel einer neutralen Konfiguration:

~~~json
{"approved":"/srv/bach-learning"}
~~~

Die Anfrage nennt nur die Wurzel-ID und einen relativen Dateipfad. Absolute Anfragepfade, Pfade mit .., Symlink-Wurzeln und Zugriffe außerhalb der freigegebenen Wurzel werden abgelehnt. Ein expliziter SHA-256-Hash der Quelle ist Pflicht. Pfad- und Hashprüfungen sind keine atomare Garantie gegen eine gleichzeitige Umbenennung im Dateisystem.

## Quellvertrag: bach.learning-source.v1

Jede Anfrage enthält source mit kind, root, path und sha256. Hermes benötigt zusätzlich entry_id. Unterstützte kind-Werte:

| kind | Eingabe und Bindung | Beleggrenze |
|---|---|---|
| session | Vorbereiteter JSON-Export mit Schema bach.learning-source.v1, session_id und events. Jedes Ereignis hat eine eindeutige id, role (user, assistant oder tool) und content; tool und outcome sind optional. | Höchstens 200 Ereignisse. Bei dieser Quelle wird ein Kandidat nur mit einem erkannten Auswahlmarker in einem ausgewählten user-Ereignis erwogen; sonst no_candidate. |
| hermes_ledger | Hermes-JSONL-Ledger im nativen Format. entry_id ist eine eindeutige 12-stellige kleingeschriebene Hex-ID. Nur Pflegeereignisse create, edit, update oder patch mit einem after-Manifest werden angenommen. | Die gelisteten absoluten Manifestpfade müssen in der freigegebenen Wurzel liegen; jeder Dateiinhalt wird gegen seinen SHA-256 geprüft. Das Ledger ist Telemetrie, keine Genehmigung und kein Qualitätsnachweis. Der Adapter liest das Format; er startet keinen Hermes-Curatorlauf. |
| nemofold_voyage | Voyage-Datei aus der nativen run-reports/web-console/voyages-Bibliothek. Die Voyage-ID ist an den Dateinamen gebunden. | NemoFold VoyageStore.load wird mit require_receipt=True aufgerufen. Der zugehörige Receipt- und Jobvertrag muss die Originaldatei binden; Datei und Receipt werden vor und nach dem Provider-Read gegen ihre Hashes geprüft. Belegt ist ein gespeicherter Plan, keine Ausführung. |

Die in der Eingabe gelieferte Quelle ist höchstens 1.000.000 Byte groß. Für ein Hermes-Ereignis gilt dieselbe Gesamtgrenze einschließlich referenzierter Dateien; einzelne referenzierte Dateien sind auf 200.000 Byte begrenzt. Ein Receipt ist auf 4.096 Byte begrenzt. Die Request-JSON ist auf 200.000 Byte und ein Sessionexport auf 200 Ereignisse begrenzt. Diese Quellgrenzen sind keine Gesamtgrenze für alle separaten Katalog- und Leitfaden-Lesevorgänge eines Aufrufs.

## Vorschlag und Ergebnisvertrag

Die Request-Wurzel erlaubt source, proposal und optional gemeinsam expected_revision sowie expected_digest. Der SHA-256-Digest ist 64-stellig, die Revision eine positive Ganzzahl. Beide CAS-Felder müssen bei einem Versionsupdate gemeinsam vorliegen.

proposal ist vollständig und enthält:

| Feld | Bedeutung |
|---|---|
| kind | skill, chain oder rule |
| name, trigger, reason | Identität, Auslöser und Begründung |
| body | Skilltext mit passender Frontmatter, strukturierte Kettendefinition oder nichtleerer Regelentwurf |
| event_ids | Eindeutige IDs ausgewählter Ereignisse aus der tatsächlich gelesenen Quelle |
| parameters | Liste aus name, value und description für private Literale, die im Vorschlag durch <NAME> ersetzt werden |
| side_effects, required_capabilities | Begrenzte Textlisten; dokumentieren Vorschlagseigenschaften, gewähren aber keine Fähigkeit |
| dedup | decision (new, extend oder covered) plus reason; bei extend/covered zusätzlich target und basis_version |

Jede semantische Auswahl bleibt prüfpflichtig. Der Dienst liest vorhandene Nachbarn aus den freigegebenen Skill- und Kettenkatalogen und bindet die vom Aufrufer gelieferte Dedup-Entscheidung sowie, soweit erforderlich, deren Basisversion; er trifft keine eigenständige semantische Duplikatentscheidung. Der Vertrag zeichnet semantic_review_required: true und empirically_validated: false auf. Bei session muss ein ausgewähltes user-Ereignis einen bekannten Auswahlmarker enthalten. Ohne Vorschlag, ohne dieses Signal oder bei dedup-Entscheidung covered lautet das Ergebnis no_candidate; es wird nichts gespeichert.

Das Ergebnis candidate enthält den Vertrag bach.learning-candidate.v1, einen Digest sowie Herkunfts-, Ereignis-, Leitfaden- und Nachbarbelege. Die Leitfäden skill-extractor und workflow-extract werden tatsächlich gelesen; die zur Laufzeit aufgelöste Version und der Hash werden gebunden. Die Version wird nicht fest auf 1.3.1 gesetzt, weil der aufgelöste Katalog abweichen kann. Die fest unterstützten, in den Leitfäden erwähnten Referenzen neutralisierung.md, transcript-quellen.md und automation-bausteine.md werden mit Hash als gelesen, aber nicht ausgeführt protokolliert. Der Vorschlag selbst bleibt eine vom Aufrufer gelieferte, noch zu prüfende Auswahl.

## Privatsphäre, Speicherung und Freigabe

Der Dienst weist in Vorschlägen erkannte Pfad-, Konto-, IP- und Credential-Muster sowie Credential-Felder zurück; der Musterfilter ist kein vollständiger semantischer Geheimnisdetektor. Credential-ähnliche Namen sind auch als Dictionary-Schlüssel unzulässig. Die Parameterisierung ersetzt ausgewählte private Literale durch Platzhalter; sie belegt nicht, dass ein Inhalt frei von weiteren Geheimnissen ist. Interne Herkunftsmetadaten und Ereignislokatoren bleiben zur Quellenprüfung erhalten und können private Angaben enthalten. Kandidatenlisten und Detailansichten verlangen deshalb ein aktives Device-Token, auch wenn der Router ohne die übergeordnete Auth-Middleware eingebunden wird. Diese internen Verträge sind keine öffentlich zu exportierenden Skills oder Regeln.

analyze und no_candidate führen weder Kandidaten- noch Zieländerungen aus. store schreibt nur nach vollständiger Prüfung in die bereits vorhandene Hermes- oder NemoFold-Kandidatenablage, setzt den Status pending und liefert Kandidaten-ID, Revision und Digest zurück. Wiederholung identischer Inhalte ist idempotent; Aktualisierungen müssen den zuvor gelesenen Kandidaten mit Revision und Digest per Compare-and-Swap treffen. Konflikte werden abgelehnt, statt einen zweiten Store oder stilles Überschreiben zu erzeugen.

Der Vertrag hält tools_granted: false, targets_published: false und scheduler.configured: false fest. Für Scheduler-Konfiguration ist eine separate Freigabe nötig. Fähigkeiten, Nebenwirkungen und Regeln in einem Vorschlag verleihen keine Rechte oder Governance-Autorität.

## Aufrufwege

CLI:

~~~text
bach learning analyze <request.json>
bach learning store <request.json> --dry-run
bach learning store <request.json> -n
bach learning store <request.json>
~~~

analyze ist immer eine Vorschau. store mit --dry-run oder -n prüft denselben Auftrag, speichert aber keinen Kandidaten; store ohne diese Flags speichert den inaktiven Kandidaten.

HTTP:

~~~text
POST /api/learning/sources/analyze
POST /api/learning/sources/store
~~~

Beide HTTP-Routen verlangen zuerst ein aktives Device-Token, übermittelt im Authorization: Bearer-Header oder im Cookie bach_device_token. Danach wird der Request-Stream vor dem JSON-Parsing auf 200.000 Byte begrenzt; ein größerer Body liefert HTTP 413. Ungültiges UTF-8/JSON oder eine Request-Wurzel ohne JSON-Objekt liefert HTTP 422. Anschließend nutzen sie dieselbe Handler-Pipeline wie die CLI. analyze bleibt lesend; store legt den Prüfkandidaten ab. Die Kandidatenlisten und Detailrouten beider Anbieter sind ebenfalls Device-authentifiziert.

Library API:

~~~python
from bach_api import learning
learning.analyze("request.json")
learning.store("request.json")
~~~

Diese Methoden verwenden den bestehenden Handler-Proxy und liefern dessen JSON-Ergebnis als Text, keinen typisierten Dictionary-Vertrag. `learning.raw("analyze", "request.json")` liefert `(success, message)`; erst nach erfolgreichem Aufruf kann der Aufrufer `message` mit `json.loads` auswerten. Eine Fehlermeldung ist kein JSON-Ergebnis. `learning.raw("store", "request.json", "--dry-run")` dient als Vorschau ohne Speicherung.

## Schematisches Beispiel

Die Sitzung liegt als session.json relativ zur freigegebenen Wurzel approved. Der Hash aus Nullen ist ein Platzhalter und muss durch den tatsächlichen Quellhash ersetzt werden.

~~~json
{
  "source": {
    "kind": "session",
    "root": "approved",
    "path": "session.json",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "proposal": {
    "kind": "skill",
    "name": "flow-note",
    "trigger": "Wenn derselbe Ablauf erneut gebraucht wird",
    "reason": "Der Aufrufer hat einen wiederverwendbaren Ablauf vorgeschlagen.",
    "body": "---\nname: flow-note\nversion: 0.1.0\ntype: skill\n---\nBeschreibe hier den zu prüfenden Ablauf.\n",
    "event_ids": ["event-1"],
    "parameters": [],
    "side_effects": [],
    "required_capabilities": [],
    "dedup": {
      "decision": "new",
      "reason": "Kein passender vorhandener Kandidat wurde angegeben."
    }
  }
}
~~~

Die referenzierte Sessiondatei muss selbst dieses Schema erfüllen:

~~~json
{
  "schema": "bach.learning-source.v1",
  "session_id": "example-session",
  "events": [
    {
      "id": "event-1",
      "role": "user",
      "content": "Beim nächsten Mal soll dieser Ablauf wiederverwendbar sein."
    }
  ]
}
~~~

Das Beispiel zeigt nur das Eingabeformat. Die Auswahl bleibt prüfpflichtig; ein gültiger Hash, Receipt oder Ledger-Eintrag belegt weder fachliche Güte noch erfolgreiche Wiederverwendung.

## Verbleibende Beweis- und Releasegrenzen

- Native Skill-Promotion ist separat gated; Tasks 2000/2001 bleiben eigenständig.
- Eine unabhängige erfolgreiche Wiederverwendung mit Ergebnisqualitätsnachweis ist nicht Teil dieser Änderung (Task 2002).
- Provider-Pins und eine nachgewiesene installierte Quelle sind separat offen (Task 2003). Der CI-Checkout des NemoFold-Quellstands ersetzt keinen Mac-Studio-Installationsnachweis.
- Automatischer Sessionexport und Scheduler bleiben außerhalb dieses Vertrags.
- Die älteren direkten Wege Hermes distill und NemoFold synthesize samt Heuristiken bleiben bestehen. Sie erfüllen diesen gemeinsamen Originalquellenvertrag nicht und sind nicht als native Originalintegration zu bezeichnen.
