# Aufgabenauswahl der Hintergrundworker

Ein aktiver Hintergrundprozess kann auf Arbeit warten. Das ist getrennt von einer laufenden, durch eine native Task-Lease gebundenen Aufgabe.

Die Aktivitätsnummer `Block N` zählt tatsächliche Aufrufe der Modelllaufzeit. Leerlaufabfragen erhöhen sie nicht. Sie ist weiterhin ein Zähler für den gesamten Workerlauf und keine Anzahl fachlich gescheiterter Versuche einer einzelnen Task.

Der aktuelle Auswahlversuch liefert `queue_status` in der vorhandenen Control-Workeransicht, im Execution-Receipt und in `GET /api/system/workers`. Der Vertrag `bach.worker-queue.v1` enthält Quelle (`canonical_task_api`), Autoritätsmodus (`local` oder `remote`), Zeitpunkt, Kandidaten-, Treffer- und Übernahmeversuchszahlen sowie die gezählten Ablehnungsgründe. `scan_complete=false` bedeutet, dass die Suche nach einem bestätigten Claim endete oder mit einem Fehler abbrach; es belegt keine vollständige Queueinventur.

Gründe der Auswahl:

- `explicit_slot_required`: Der Worker übernimmt nur ausdrücklich seinem Slot zugewiesene Aufgaben.
- `slot_binding` oder `model_binding`: Aufgabe und tatsächliche Workerbesetzung passen nicht zusammen.
- `pickup_category`, `pickup_priority`, `pickup_tags`, `excluded_tag`: Die jeweilige Filtergruppe schließt die Aufgabe aus. Alle konfigurierten Gruppen müssen passen; Kategoriequellen und positive Tags sind innerhalb ihrer Gruppe Alternativen. Bei einer ausdrücklichen Slotzuordnung werden nur Kategorie und Priorität übergangen; Tagfilter gelten weiter.
- `pickup_filter` bleibt als allgemeiner Filtergrund für ältere Beobachtungen beziehungsweise nicht genauer auflösbare Filter bestehen.
- `ownership`: Ein Pickupfilter ist ein Auswahlkriterium, keine Berechtigung. Er hebt eine fremde, nichtleere `assigned_to`-Zuweisung nicht auf. Eine persönliche Aufgabe mit `assigned_to=user` erreicht die automatische Queue dieses Workers nur über eine ausdrückliche `assigned_slot`-Zuweisung an genau dessen Worker-ID. Ohne Filter gilt für ungeroutete Aufgaben die in `selection_policy` ausgewiesene BACH-/Buddha-/Ollama-/eigene-Workerrolle-Regel.
- `deferred_version`: Dieser Workerlauf hat dieselbe Taskversion bereits ohne Ergebnis zurückgegeben. Erst eine Inhaltsänderung lässt einen neuen Versuch zu.
- `held`, `creator_priority`, `not_claimable`, `stale_task_version`, `already_held_by_caller`: Der kanonische Übernahmeversuch wurde abgelehnt. `not_claimable` kann auch offene, fehlende oder ungültige Abhängigkeiten bedeuten; es ist keine genaue Abhängigkeitsinventur.
- `conflict`: Der native Übernahmevertrag bestätigt keine Vergabe. Der bisherige Abbruchpfad bleibt erhalten; die Diagnose löst keinen automatischen Ersatzversuch aus. Auch ausdrücklich gebundene Tasks zeigen ihre bestätigten Übernahmeablehnungen, ohne die Behandlung der Ausnahme zu ändern.
- `changed_selection`: Der frische Tasksnapshot passt nach einer zwischenzeitlichen Änderung nicht mehr.

`empty_queue` bezeichnet eine vollständig gelesene leere Kandidatenqueue. `selection_excluded` bedeutet, dass kein Kandidat die Auswahl erreichte. `acquire_denied` bedeutet, dass Treffer vorhanden waren, deren Übernahme nicht bestätigt wurde. `selection_error` zeigt einen fehlgeschlagenen Auswahlversuch; ein API-Fehler wird nicht als leere Queue ausgegeben.

Lehnt die interne Control-API das Lesen des Workerstatus ab, liefert die GUI-Statusroute kontrolliert HTTP 503 („Workerstatus nicht verfügbar“). Dies ist getrennt von den normalisierten Providerfehlern einer Modellanfrage; interne Fehlerdetails werden nicht an die GUI weitergereicht.

Die Diagnose verändert keine Auswahlberechtigung, Task, Lease, Creator-Schonfrist oder Modellroute. Sie veröffentlicht keine Taskinhalte, Prompts, Holder oder Leasecredentials. Sie ist ein datierter Auswahlbeleg und kein Beleg für aktuelle Inferenz, fachliche Ergebnisqualität oder persönliche Abnahme. Ein neuer Controllerstart beginnt ohne alten Diagnosezustand.

Für `openrouter/free` können geeignete BACH-Aufgaben ausdrücklich zugewiesen oder über einen begrenzten Pickupfilter für die automatische Auswahl eingegrenzt werden. Der Filter kann ungeroutete passende Aufgaben auswählen, übernimmt aber keine nichtleeren Codex-, User- oder sonstigen fremden Zuweisungen. Im automatischen Queuepfad erfordert eine persönliche User-Aufgabe die ausdrückliche Route an die eigene Worker-ID. Ein Filter ändert keine Modellbindung und erlaubt keinen kostenpflichtigen Ersatz.

## Taskrouting und lokale Modellressourcen

`assigned_slot` ist eine logische Taskroute zu einer Worker-ID. Sie ist nicht derselbe Steckplatz wie eine lokale Modellressource. Ein lokaler Modellressourcen-Steckplatz reserviert beziehungsweise prüft eine lokal erreichbare Inferenzressource; im BACH-Vertrag sind das Ollama- und LM-Studio-Ziele. Externe Anbieter wie OpenRouter oder `ollama-cloud` benötigen keinen lokalen Modellressourcen-Steckplatz. Für sie gelten weiterhin Taskroute, `required_model`, Zuweisungs- und Pickupregeln, sofern diese an der Task gesetzt sind.

Bei einer persönlichen Aufgabe (`assigned_to=user`) erlaubt nur `assigned_slot` mit genau der eigenen Worker-ID die automatische Auswahl durch diesen Worker. Die explizite Route übergeht Kategorie- und Prioritätsfilter, nicht aber Slot-/Modellbindungen oder aktive Tagbeschränkungen. Eine konfigurierte direkte `task_id` ist ebenfalls eine ausdrückliche Taskroute und kein allgemeiner Pickupfilter. Creator-Delegation ist ein eigener, ausdrücklich an eine Task gebundener Sequenzpfad. Diese Routen ändern weder Besitzrechte anderer Worker noch den Schutz der nativen Task-Lease.

## Konfiguration und ältere GUI-Karten

`GET /api/workers/configuration?id=…` am Control-Dienst beziehungsweise
`GET /api/system/workers/{id}/configuration` am GUI-Adapter liefert die
gemeinsam projizierte, schreibgeschützte `selection_policy` mit Schema
`bach.worker-selection.v1`. Sie enthält `require_assigned_slot`, den
`pickup_filter` (`enabled`, `categories`, `priorities`, `tags`, `exclude_tags`)
und den abgeleiteten Eigentumsmodus für ungeroutete Aufgaben. Fremde
Konfigurationsfelder und private Leasewerte werden nicht übernommen.

Der bestehende `POST /api/workers/configuration`-Endpunkt nimmt Änderungen als
CAS-Anfrage mit `id`, `configuration_version` und `changes` entgegen. Die
gesamte `selection_policy` bleibt ein Leseobjekt; als neues Policy-Änderungsfeld
ist ausschließlich `changes.pickup_filter` editierbar. Die Eingabe muss ein
Objekt mit genau den fünf bekannten Schlüsseln enthalten: `enabled` muss ein
Boolean sein; jedes der vier Listenfelder muss eine Liste aus Strings sein.
Listen dürfen jeweils höchstens 64 Einträge enthalten, jeder Eintrag höchstens
100 Zeichen; NUL-Zeichen und unbekannte Schlüssel werden abgelehnt. Der
Bearbeiter darf weder `require_assigned_slot` noch Task-Zuweisungen oder
Modellbindungen über diesen Filter ändern.

Die CAS-Version bindet die projizierte Policy mit ein. Veraltete Versionen
werden abgewiesen. Der Worker muss außerdem einen bearbeitbaren Nichtlaufstatus
(`idle`, `paused`, `completed` oder `error`) haben und darf nicht abgelaufen sein;
der GUI-Adapter prüft den Status und bestätigt die gespeicherte Konfiguration
durch Readback. Änderungen am Filter ändern die Konfigurationsversion; reine
Laufmetadaten tun dies nicht. Bei einem älteren Control-Dienst ohne diese
Projektion bleibt die Policy unbekannt; der Adapter erfindet keine Standardwerte.

Die Warteanzeige in `current_activity` wird aus derselben validierten
Livebeobachtung gebildet. Sie nennt Kandidaten, Auswahlmatches, Ausschlusszahlen,
Task-API und UTC-Zeit, sodass bestehende GUI-Karten den Grund ohne einen neuen
Renderer zeigen können. Dies ersetzt weder den strukturierten Beleg noch eine
native Lease. Die Dokumentation beschreibt den Quellvertrag. Control-Dienst und
GUI-Adapter müssen gemeinsam integriert sein, bevor der Bearbeitungsweg
verfügbar ist. Eine Quelländerung allein ändert weder eine residente
Controllergeneration noch ihre Laufzeitkonfiguration; nach Integration muss
der wirksame Zustand gesondert über frische Laufzeit-Readbacks geprüft werden.
Hiermit wird keine Aktivierung oder Änderung einer produktiven
Worker-Konfiguration behauptet.
