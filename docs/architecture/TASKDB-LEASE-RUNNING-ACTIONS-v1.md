# TaskDB: versionierte Lease-Aktionen für Running

Ergänzung zu `TASKDB-SALT-LEASE-VERTRAG-v1.md`, Task #1727.
Implementierung und isolierte Prüfungen; Integration und Laufzeitabnahme stehen aus.

## Auftragsversion

`task_version` ist ein SHA-256-Fingerprint des momentanen Auftragsinhalts.
Lease-/Heartbeatfelder, Status und Laufzeitstempel beeinflussen ihn nicht.
NULL-Felder werden ausgelassen, damit additive optionale Spalten eine bestehende
Bindung nicht verändern. Titel, Beschreibung, Abhängigkeiten, Priorität,
Zuordnung, Modell-/Slotvorgaben und weitere Inhaltsfelder sind gebunden.

Task-Liste und Taskdetail liefern den Fingerprint. Sie liefern weder `claim_id`
noch `claim_request_id` oder den internen `claim_task_version`.

Acquire kann die gelesene `task_version` als Vorbedingung erhalten. Bei Erfolg
speichert es die Inhaltsbindung in `claim_task_version` und liefert sie im ACK.
Ein Heartbeat ändert diese Bindung nicht. Renew und Release prüfen auch bei
älteren Requests ohne Versionsfeld die gespeicherte Bindung gegen den aktuellen
Inhalt. Eine Abweichung liefert `409 stale_task_version`.

Neue Worker lesen den Auftrag, senden dessen Version bei Acquire und führen
jede Änderung mit Lease-ID, Fence und dieser Version aus. Bei Ablehnung stoppen
sie die Bearbeitung; ein fehlgeschlagener Renew begründet keine neue Bindung.
Bestehende Leases ohne Inhaltsbindung müssen ablaufen. Danach kann ein neues
Acquire den aktuellen Auftragsinhalt binden.

## Zerlegung

`POST /api/tasks/{id}/lease/decompose` verlangt Geräteauth sowie:

```json
{
  "lease_id": "UUID",
  "fence": 1,
  "task_version": "64 hexadezimale Zeichen",
  "subtasks": [{"title": "Erster Schritt", "description": "Konkrete Fortsetzung"}],
  "close_parent": true,
  "sequential": false
}
```

Fence und Flags sind strikt typisiert; unbekannte Requestfelder werden abgelehnt.
Die Liste enthält 1–100 Teilaufgaben. Teilaufgaben unterstützen Titel,
Beschreibung, Priorität, Kategorie, Zuordnung, Abhängigkeiten sowie Modell- und
Slotvorgaben. Vorhandene Modell-/Slotvorgaben werden standardmäßig vererbt.

Unter derselben `BEGIN IMMEDIATE`-Transaktion werden Lease, Fence, Ablauf und
Inhaltsversion geprüft, alle Teilaufgaben angelegt, die Elternbeschreibung
ergänzt und bei `close_parent=true` der Eltern-Task abgeschlossen. Dann werden
seine Capability-Felder geleert; der Fence bleibt erhalten. Bei offenem Eltern-Task
wird die Versionsbindung auf die eigene bestätigte Beschreibung aktualisiert.
Alle schreibenden Lease-Operationen lesen die aktuelle Serverzeit erst nach dem
Erwerb der Schreibsperre; Wartezeit darf einen abgelaufenen Lease nicht verlängern.

Das ACK enthält `decomposed`, `task_id`, `created_ids`, `created_count`,
`parent_closed`, `fence`, `task_version` und `server_now`. Es wird erst nach
erfolgreichem Commit ausgegeben. Fehler beim Anlegen, Abschluss oder Commit
rollen das gesamte Paket zurück. Ein paralleler oder wiederholter Request mit
alter Version kann keine zweite Teilaufgabengruppe anlegen.

Eine Rollenbesetzung oder Taskzuordnung in einer Teilaufgabe ist noch kein
delegierter Providerlauf. Der native Running-Client muss den bestätigten
Auftrag und dessen Version mit seinem tatsächlich gestarteten Worker verbinden.

## Nativer Ausführungspfad (Quellstand Task #1729)

`start_worker_execution` ist der gemeinsame Controller für den direkten lokalen
Aufruf und `POST /api/workers/run`. Rollenfreigabe, tatsächlicher Task-Acquire,
Generation, unabhängiger Heartbeat, Pausen und terminale Bereinigung gehören zu
diesem Controller. Ohne bestätigten Task-Lease beginnt keine Inferenz.

Der feste Kernslot `buddha_always_on` wird aus seiner gespeicherten Konfiguration
gelesen. Fehlender Slot, abweichende ID, doppelte dynamische ID oder untypisierte
Aktivierung werden abgelehnt. Er erhält die Ausführungsart `continuous`; sein
Slotname und seine konfigurierte Modell-, Backend-, Modus- und Filterwahl bleiben
erhalten. Andere Kernslots werden dadurch nicht zu dynamischen Workern. Ein
tatsächlich registrierter aktiver Kernworker erscheint in `/api/workers` als
Systemslot mit `deletable=false` und seiner aktuellen Generation. Gespeicherte
Generations- oder Taskaktionsfelder ersetzen keinen aktiven privaten Controller.

Die Zulassung des Kernworkers bindet seine Ausführungskonfiguration. Ändert sie
sich, lehnen der Session-Leser und die private Taskbindung weitere operative
Grenzen ab. Eigene Task-ID-Metadaten sind davon getrennt. Der unabhängige
Heartbeat darf eine bekannte Lease während des Endes eines bereits gestarteten
Aufrufs erhalten; anschließend bleibt ihre bestätigte Rückgabe möglich. Eine
unbekannte Lease-Antwort wird dadurch nicht wieder gültig.

Eine bestätigte PR-Freigabe zählt über den korrelierten typisierten
`LeaseReleaseAck` als Review. Fortlaufende Worker schließen dieses Assignment als
`released/task_review` und suchen den nächsten Auftrag. Der Erledigt-Zähler steigt
erst nach einem tatsächlichen Done-/Elternabschluss-ACK. Ein Einzellauf endet nach
Review im Status `idle` ohne Task-ID. Modelltext und alte Abschlussmeldungen können
diese Übergänge nicht bestätigen.

Dieser Abschnitt beschreibt den Quellstand. Der Tray startet und beobachtet
den nativen Controller; das eigenständige Worker-Skript benötigt noch die
Umstellung. Mac-/Desktop-Installation,
Geräteauth und die tatsächliche Laufzeitabnahme sind gesonderte offene Schritte.

### Startprüfung und tatsächliches Ende

Ein Start wird vor der Rollenprüfung unter seiner Worker-ID reserviert. Die
optionale `start_request_id` besteht aus 32 kleinen hexadezimalen Zeichen.
Ein zweiter Start derselben Worker-ID erhält während dieser Prüfung `409` mit
dem Zustand `starting`; dieselbe Request-ID liefert den vorhandenen Startbeleg
und eröffnet keine zweite Rollenprüfung. Ein Stop wartet auf die tatsächliche
Startprüfung und verhindert danach den Workerstart.

`GET /api/workers/execution?id=…&start_request_id=…` verlangt Control-Auth und
liefert einen Beleg mit Schema `bach.worker-execution.v1`, Control-Instanz,
Request-ID, Generation, Zustand und separatem Terminalflag. Ein Caller kann die
gelesene Instanz mit `expected_service_instance` als Startvorbedingung senden.
Eine andere Instanz oder eine nicht bestätigte Request-ID ist kein Nachweis,
dass ein früherer Worker beendet wurde.

Die Zustände unterscheiden Startprüfung, Lauf, Stop, abschließende Bereinigung
und einen unbestätigten Start. `terminal=true` verlangt sowohl die abgeschlossene
Bereinigung als auch das tatsächliche Ende des eigenen Workerthreads. Vor einem
Workerstart genügt das tatsächliche Ende der synchronen Startprüfung. Ein
fehlgeschlagener Threadstart wird nicht als „kein Worker“ interpretiert: Bis zum
nachgewiesenen Ende bleibt er unbestätigt und verhindert einen weiteren Start.
Gespeicherte Taskabschluss-IDs stammen ausschließlich aus der privaten Bindung.

### Tray als Starter und Beobachter

Der Tray verwendet für Always-On ausschließlich den exakten Kernslot. Er
übernimmt keine Tasks über GUI-Statusupdates und eröffnet keine eigenen
Task-Chats. Modell, Backend, Modus, Rundenlimit und Filter werden nicht als
Startüberschreibung gesendet. Taskauswahl, Lease, Inferenz, Review/Done sowie
Pausenzähler gehören zum Controller.

Vor dem einzigen Start-POST wird eine öffentliche Startvormerkung unter
`~/.bach/<brand>_worker_<endpoint-hash>.json` atomar gespeichert. Sie enthält
Control-Adresse, Service-Instanz, Request-ID und später die bestätigte Generation;
keine Task-Capability, Geräteauth oder Promptinhalte. Ein neu gestarteter Tray
liest diese Vormerkung vor weiteren Aktionen. Unbekannte Startantworten führen
ausschließlich zum korrelierten GET. Fehlender Record, Servicewechsel, falsche
Generation, beschädigte Datei und Speicherfehler erlauben keinen zweiten Start.
Die HTTP-Abfragen verwenden ausschließlich Control-Auth und folgen keinen
Redirects; es gibt keinen GUI- oder TaskDB-Fallback.

Ein tatsächliches Terminal-ACK leert die Vormerkung. Eine synchrone Ablehnung
vor der Reservierung kann sie ebenfalls leeren, wenn das `admission`-Objekt
`admitted=false` sowie exakt Worker-ID, Request-ID und Service-Instanz bestätigt.
Ein Fehlercode allein genügt nicht. Gewinnt ein anderer Start die Reservierung,
kann dessen Lauf nach dem korrelierten Ablehnungsbeleg beobachtet werden.

Bereits unbestätigte Legacy-Chataufrufe bleiben gesperrt; Verlauf, Taskstatus,
Antworttext und Ablaufzeit beweisen ihr physisches Ende nicht. Vor der
Installation ist deshalb der alte Executor kontrolliert zu leeren. Das
Hostflag `BACH_IDLE_WORKER=0` verhindert neue Tray-Starts und wiederkehrende
Taskerzeugung. Für einen bekannten laufenden Controller fordert der Tray den
unten beschriebenen Stop an und wartet auf dessen tatsächliches Ende. Die
Standalone-Umstellung und die vollständige Rollen-/Arbeitsverzeichnis-Parität
bleiben weitere Integrationsschritte.

„Running“ verlangt einen aktiven Hintergrund-Rechenturn mit der exakten
Chat-ID `buddha_always_on`. Ein HTTP-Aufruf oder lebender wartender Controller
allein genügt nicht. Startprüfung, Beendigung und unbestätigte Läufe werden
gesondert angezeigt. Vordergrund-Chats disarmen Always-On nicht.

### Stop einer bestätigten Generation

`POST /api/workers/stop` unterstützt die zusammengehörigen Felder
`expected_service_instance`, `expected_start_request_id` und
`expected_generation`. Alle drei müssen 32 kleine hexadezimale Zeichen sein;
teilweise oder falsch typisierte Bindungen werden mit `400` abgelehnt. Eine
andere aktuelle Ausführung erhält `409` ohne Stop oder Statusänderung.
Auswahl, Bindungsprüfung und Stopanforderung geschehen unter derselben
Controllersperre. Gewartet wird anschließend ohne diese Sperre auf genau den
erfassten Thread. Späte Statusschreibvorgänge dürfen auch einen inzwischen
gespeicherten neueren Lauf nicht überschreiben.

Die Antwort enthält den Ausführungsbeleg des erfassten Controls. Er bleibt auf
die alte Generation bezogen, wenn nach deren physischem Ende bereits ein neuer
Lauf begonnen hat. Metadatenstatus und physisches Terminalflag sind getrennt;
ein Join-Timeout oder ein Stop-Receipt allein bestätigt kein Ende. Die bisherige
manuelle ID-only-Schnittstelle bleibt kompatibel, der Tray nutzt ausschließlich
die vollständige Bindung.

Der Tray speichert `stop_requested=true` vor dem einmaligen Stop-POST in seiner
Startvormerkung. Nach verlorener Antwort oder Tray-Neustart fragt er nur den
korrelierten Lauf ab. Ein unbestätigter Start ohne bekannte Generation wird
nicht gestoppt. Bereits stoppende oder abschließend bereinigende Läufe werden
beobachtet. Konfigurierter Cooldown und Vordergrund-Rechenvorrang lösen keinen
Hoststop aus; eine deaktivierte Host- oder Slotaktivierung tut dies.

Ein bekanntes Execution-Record bleibt bei fehlender Slotkonfiguration lesbar.
Ein vollständig gebundener Stop darf dabei die beim Start gespeicherte minimale
Workeridentität verwenden. Neue Inferenz erhält dadurch keine Zulassung. Fehlt
die tatsächliche Konfiguration an der Metadatengrenze, werden Status-, Aktivitäts-,
Pausen- und Abschlussbelegschreibvorgänge ausgelassen; eine Hintergrundoperation
darf an diesen Grenzen keine Default-Konfiguration anlegen.
