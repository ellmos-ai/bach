# Aufgabenauswahl der Hintergrundworker

Ein aktiver Hintergrundprozess kann auf Arbeit warten. Das ist getrennt von einer laufenden, durch eine native Task-Lease gebundenen Aufgabe.

Die Aktivitätsnummer `Block N` zählt tatsächliche Aufrufe der Modelllaufzeit. Leerlaufabfragen erhöhen sie nicht. Sie ist weiterhin ein Zähler für den gesamten Workerlauf und keine Anzahl fachlich gescheiterter Versuche einer einzelnen Task.

Der aktuelle Auswahlversuch liefert `queue_status` in der vorhandenen Control-Workeransicht, im Execution-Receipt und in `GET /api/system/workers`. Der Vertrag `bach.worker-queue.v1` enthält Quelle (`canonical_task_api`), Autoritätsmodus (`local` oder `remote`), Zeitpunkt, Kandidaten-, Treffer- und Übernahmeversuchszahlen sowie die gezählten Ablehnungsgründe. `scan_complete=false` bedeutet, dass die Suche nach einem bestätigten Claim endete oder mit einem Fehler abbrach; es belegt keine vollständige Queueinventur.

Gründe der Auswahl:

- `explicit_slot_required`: Der Worker übernimmt nur ausdrücklich seinem Slot zugewiesene Aufgaben.
- `slot_binding` oder `model_binding`: Aufgabe und tatsächliche Workerbesetzung passen nicht zusammen.
- `pickup_category`, `pickup_priority`, `pickup_tags`, `excluded_tag`: Die jeweilige Filtergruppe schließt die Aufgabe aus. Alle konfigurierten Gruppen müssen passen; Kategoriequellen und positive Tags sind innerhalb ihrer Gruppe Alternativen. Bei einer ausdrücklichen Slotzuordnung werden nur Kategorie und Priorität übergangen; Tagfilter gelten weiter.
- `pickup_filter` bleibt als allgemeiner Filtergrund für ältere Beobachtungen beziehungsweise nicht genauer auflösbare Filter bestehen.
- `ownership`: Ohne ausdrückliche Slotzuordnung oder aktivierten Pickupfilter fehlt eine passende BACH-/Buddha-/Ollama-/Worker-Zuweisung.
- `deferred_version`: Dieser Workerlauf hat dieselbe Taskversion bereits ohne Ergebnis zurückgegeben. Erst eine Inhaltsänderung lässt einen neuen Versuch zu.
- `held`, `creator_priority`, `not_claimable`, `stale_task_version`, `already_held_by_caller`: Der kanonische Übernahmeversuch wurde abgelehnt. `not_claimable` kann auch offene, fehlende oder ungültige Abhängigkeiten bedeuten; es ist keine genaue Abhängigkeitsinventur.
- `conflict`: Der native Übernahmevertrag bestätigt keine Vergabe. Der bisherige Abbruchpfad bleibt erhalten; die Diagnose löst keinen automatischen Ersatzversuch aus. Auch ausdrücklich gebundene Tasks zeigen ihre bestätigten Übernahmeablehnungen, ohne die Behandlung der Ausnahme zu ändern.
- `changed_selection`: Der frische Tasksnapshot passt nach einer zwischenzeitlichen Änderung nicht mehr.

`empty_queue` bezeichnet eine vollständig gelesene leere Kandidatenqueue. `selection_excluded` bedeutet, dass kein Kandidat die Auswahl erreichte. `acquire_denied` bedeutet, dass Treffer vorhanden waren, deren Übernahme nicht bestätigt wurde. `selection_error` zeigt einen fehlgeschlagenen Auswahlversuch; ein API-Fehler wird nicht als leere Queue ausgegeben.

Lehnt die interne Control-API das Lesen des Workerstatus ab, liefert die GUI-Statusroute kontrolliert HTTP 503 („Workerstatus nicht verfügbar“). Dies ist getrennt von den normalisierten Providerfehlern einer Modellanfrage; interne Fehlerdetails werden nicht an die GUI weitergereicht.

Die Diagnose verändert keine Auswahlberechtigung, Task, Lease, Creator-Schonfrist oder Modellroute. Sie veröffentlicht keine Taskinhalte, Prompts, Holder oder Leasecredentials. Sie ist ein datierter Auswahlbeleg und kein Beleg für aktuelle Inferenz, fachliche Ergebnisqualität oder persönliche Abnahme. Ein neuer Controllerstart beginnt ohne alten Diagnosezustand.

Für `openrouter/free` werden geeignete vorhandene BACH-Aufgaben ausdrücklich zugewiesen oder über einen bewusst begrenzten Automationsfilter freigegeben. Breite Kategorie-/Prioritätsfilter können auch Codex-/User-Aufgaben auswählen und sollen daher nicht ohne Prüfung des Arbeitsscope aktiviert werden. Ein kostenpflichtiger Ersatz wird dadurch nicht erlaubt.

## Konfiguration und ältere GUI-Karten

`GET /api/workers/configuration?id=…` am Control-Dienst beziehungsweise
`GET /api/system/workers/{id}/configuration` am GUI-Adapter liefert die
schreibgeschützte `selection_policy` mit Schema `bach.worker-selection.v1`.
Sie enthält `require_assigned_slot`, die fünf Pickupfilter-Felder und den
abgeleiteten Eigentumsmodus für ungeroutete Aufgaben. Fremde Konfigurationsfelder
und private Leasewerte werden nicht übernommen. Änderungen an diesen
Auswahlwerten ändern die Konfigurationsversion; reine Laufmetadaten tun dies
nicht. Der bestehende Bearbeitungsendpunkt akzeptiert `selection_policy` nicht
als Schreibfeld. Bei einem älteren Control-Dienst ohne diese Projektion bleibt
sie unbekannt; der Adapter erfindet keine Standardwerte.

Die Warteanzeige in `current_activity` wird aus derselben validierten
Livebeobachtung gebildet. Sie nennt Kandidaten, Auswahlmatches, Ausschlusszahlen,
Task-API und UTC-Zeit, sodass bestehende GUI-Karten den Grund ohne einen neuen
Renderer zeigen können. Dies ersetzt weder den strukturierten Beleg noch eine
native Lease. Neue Code- und Hilfefelder sind erst nach Integration und
Aktivierung des passenden Control- und GUI-Backendstands im Betrieb vorhanden.
