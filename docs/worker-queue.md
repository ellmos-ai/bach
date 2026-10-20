# Aufgabenauswahl der Hintergrundworker

Ein aktiver Hintergrundprozess kann auf Arbeit warten. Das ist getrennt von einer laufenden, durch eine native Task-Lease gebundenen Aufgabe.

Die Aktivitätsnummer `Block N` zählt tatsächliche Aufrufe der Modelllaufzeit. Leerlaufabfragen erhöhen sie nicht. Sie ist weiterhin ein Zähler für den gesamten Workerlauf und keine Anzahl fachlich gescheiterter Versuche einer einzelnen Task.

Der aktuelle Auswahlversuch liefert `queue_status` in der vorhandenen Control-Workeransicht, im Execution-Receipt und in `GET /api/system/workers`. Der Vertrag `bach.worker-queue.v1` enthält Quelle (`canonical_task_api`), Autoritätsmodus (`local` oder `remote`), Zeitpunkt, Kandidaten-, Treffer- und Übernahmeversuchszahlen sowie die gezählten Ablehnungsgründe. `scan_complete=false` bedeutet, dass die Suche nach einem bestätigten Claim endete oder mit einem Fehler abbrach; es belegt keine vollständige Queueinventur.

Gründe der Auswahl:

- `explicit_slot_required`: Der Worker übernimmt nur ausdrücklich seinem Slot zugewiesene Aufgaben.
- `slot_binding` oder `model_binding`: Aufgabe und tatsächliche Workerbesetzung passen nicht zusammen.
- `pickup_category`, `pickup_priority`, `pickup_tags`, `excluded_tag`: Die jeweilige Filtergruppe schließt die Aufgabe aus. Alle konfigurierten Gruppen müssen passen; Kategoriequellen und positive Tags sind innerhalb ihrer Gruppe Alternativen. OpenRouter- und Ollama-Cloud-Worker wenden keinen Kategorieausschluss an, können aber weiter nach Priorität und Tags filtern. Bei einer ausdrücklichen Slotzuordnung werden zusätzlich Kategorie und Priorität übergangen; Tagfilter gelten weiter.
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

## Taskgebundene öffentliche Code-Leser und Provenienz

Ein gebundener Codeworker aktiviert den eingeschränkten Reader nur, wenn seine private Worker-Konfiguration `start_task_worktree` ausdrücklich freigibt und das Werkzeug im aktuellen Modus verfügbar ist. Modellargumente können diese Fähigkeit nicht setzen. Der Start bindet den registrierten BACH-Taskarbeitsbaum an `ellmos-ai/bach`, prüft anonym die öffentliche GitHub-Metadatenquelle und den exakten `main`-Commit und startet ohne Fetch von genau diesem lokalen Commit. Fehlt die öffentliche Metadaten-/Refbestätigung oder stimmt der lokale Commit nicht exakt überein, bleibt der Code-Leser unverfügbar.

Der bestätigte Basis-Commit wird in der bestehenden branchbezogenen Git-Worktree-Registrierung gespeichert. Weitere Reads folgen diesem festen Pin und prüfen, dass der aktuelle Taskbranch davon abstammt; ein eigener Commit oder ein inzwischen weitergelaufenes Remote-`main` verschiebt den Pin nicht. Die Leser `read_file`, `list_directory` und `search_text` erhalten nur reguläre, symlinkfreie, nicht ignorierte, nicht als geheim eingestufte Dateien aus genau diesem gebundenen Arbeitsbaum. Sie traversieren nicht das Homeverzeichnis oder fremde Worktrees.

Unveränderte Dateien aus dem gepinnten Baum werden als `public_base` eingeordnet. Neue oder vom Task geänderte Dateien sind `task_artifact`; ihre Lage in einem öffentlichen Repository macht ihren Inhalt nicht automatisch öffentlich. Eine bestehende ungebundene oder private Leseroute behält ihre bisherigen Regeln. Ein fehlender oder veralteter Pin wird nicht durch eine URL-Form, einen Tasktext oder einen aktuellen Remotevergleich ersetzt.

Diese Begrenzung gilt für die drei BACH-Leserwerkzeuge. Sie ist keine Betriebssystem-Sandbox für beliebigen Python-, Test- oder sonstigen Prozesscode. Die vorhandene isolierte Prüfausführung hat einen eigenen Vertrag; ein Profil darf aus diesem Reader-Patch allein keine weitergehende Dateisystem- oder Prozessisolation ableiten.
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

## Dauerstart für Cloudworker und sichere Wiederaufnahme

Die dauerhafte Startabsicht wird pro dynamischem Cloudprofil ausdrücklich per Versions-CAS gespeichert; neue Profile erben sie nicht. Das Controllerfeld `_persistent_execution_checkpoint` bleibt intern: Es ist kein editierbares Profilfeld, wird nicht über `/api/slots` oder den Worker-Handoff projiziert und verändert weder Profil- noch Ausführungsdigest. Das Deaktivieren der Dauerfreigabe entfernt Absicht und Checkpoint gemeinsam.


Jeder beim Startmonitor zugelassene Worker erhält ein eigenes Stop-Signal, das mit dem gemeinsamen Server-Shutdown verknüpft bleibt. Ein manueller Stop oder Startfehler setzt nur das Signal des betroffenen Workers; er löst keinen gemeinsamen Shutdown aus und cancelt nicht direkt andere Profile oder den Monitor. Der Monitor kann anschließend gemäß seiner bestehenden Retry-Policy regulär enden. `server_close()` setzt das gemeinsame Signal und erreicht damit alle verbundenen Startup-Worker sowie den Monitor. Tritt es während der Assignment-Eröffnung ein, darf die zugehörige physische Generation nicht starten. Diese Controllersemantik ist durch isolierte Tests belegt; sie behauptet keinen produktiven Start.

Vor einer automatischen Admission wird admission_pending dauerhaft geschrieben. Das private Schema v2 bindet Worker-ID, Service-Instanz, Start-Request-ID, Opt-in-ID, Profilversion und Trace-Quellfingerprint sowie bereits die zufällige Generation, physische Worker-ID und vollständige Lease-Worker-ID (worker-…@host). admitted ändert nur die Phase; Generation und physische Identitäten bleiben unverändert. Ein alter v1-Checkpoint oder jede unvollständige Bindung bleibt gesperrt. Die Generation ist nicht über öffentliche Startparameter wählbar.

Nach einem Dienstneustart kann ein alter Checkpoint nur bei Status idle oder stale running geprüft werden. Die Reconciliation liest über den kanonischen TaskLeaseClient lückenlos alle pending, open, in_progress und progress-Kandidaten, weil genau diese Status die normale `WorkerLeaseBinding.acquire_next`-Kette über `_acquire_next_observed` paginiert. Pro Task werden kanonischer Snapshot, Taskversion, Lease-Status/Fence/Holder sowie sämtliche nativen Tool-Trace-Seiten erfasst. Zwei vollständige Scans müssen einschließlich Profilstatus, Kandidaten, Taskversionen, Fencewerten, Generationen und Ereignissen denselben Digest ergeben. Fehlende Seiten, Scanlimits, Lese-/Versionsfehler und Unterschiede blockieren.

Ein aktiver Lease mit der alten Lease-Worker-ID, eine abweichende Worker-/Generationsbindung oder irgendein Traceereignis der alten Generation auf einer erneut auswählbaren Task blockiert die Wiederaufnahme. Das gilt auch nach acknowledged: ein Werkzeug-ACK ist keine fachliche Taskabnahme. Die nativen Kandidatenseiten enthalten keine review-, completed-, done- oder blocked-Tasks; sie werden vom normalen Acquire nicht erneut beansprucht. Wird eine Task später wieder auswählbar, erscheint sie erneut in der vollständigen Kandidatensuche und ihr alter Trace sperrt dann.

Eine vollständige leere Ereignismenge ist nur mit dem gespeicherten Instrumentierungs-Fingerprint aussagekräftig: `ChatRuntime._process_turn` führt über `_tool_loop` zum instrumentierten `_tool_loop_impl`; dessen Taskbindungsprüfung blockiert fehlende Bindungen, und der normale Dispatcher schreibt `started` vor der Werkzeugwirkung. Leasebindung sowie native Task-/Trace-Reader sind ebenfalls Teil des Fingerprints. Erst wenn zwei vollständige Scans für die alte Worker-ID weder aktiven Lease noch Trace finden, kann ein privater CAS denselben Profil-/Opt-in-/Status-/Checkpointstand binden, das alte Checkpoint löschen und stale `running` auf `idle` setzen. Die Startprüfung lädt danach das Profil neu und beginnt eine neue, zufällig erzeugte Generation; sie akzeptiert oder erledigt keine Task.

Der getestete Basisstand `main` (`615d817…`) enthält die #2079-Normal-Loop-Traceintegration aus PR #340 (`ad44f63d…`). Die Reconciliation bleibt bei fehlenden, unvollständigen oder instabilen Task-/Trace-Leseergebnissen fail-closed. Die isolierten Quellregressionen belegen diese Integration, aber keine produktive Cloud-Wiederaufnahme oder Betriebsabnahme. Ein leerer Leerlaufthread oder eine angelegte Dauerfreigabe ist weder ein Taskergebnis noch eine Betriebsabnahme.

### Öffentliche Git-Quellprüfung: begrenzte Leseoperationen

Der Provenance-Reader akzeptiert ausschließlich die fest definierten Leseoperationen für Origin, Main-Commit, Head-Commit und die Task-Quellregistrierung. Ausführbare Datei und Git-Unterbefehle werden intern festgelegt; eine freie Argumentliste gehört nicht zu dieser Schnittstelle. Die Registrierungskennung wird aus einer kanonischen positiven numerischen Task-ID erzeugt. Unbekannte Operationen und ungültige IDs werden vor dem Prozessstart abgewiesen. Dieser Vertrag verleiht keine Schreib-, Deploy- oder Taskfreigabe.

### Freigabe der Worker-Queue und lokale Ollama-Wiederverwendung

Nach der Übermittlung prüft der Worker den verifizierten kanonischen Ergebnis-Readback anhand von Task, Ergebnis-ID und Hash, Generation, Fence, Taskversion, Übermittlungsbeleg und Ergebnisrevision. Ein exakt aktuelles Ergebnis gibt denselben Worker sofort für den nächsten Queue-Claim frei, auch wenn die verknüpfte Prüfung oder Abschlussbewertung noch aussteht. Das Ergebnis bleibt prüfungs- und abschlussrichtlinienpflichtig; externe Schutzgates für geschützte Repository-Änderungen, Veröffentlichung, Löschung und Ausgaben bleiben bestehen. Fehlende oder veraltete Readbacks halten den Worker an.

Die Prüfung ist eine separate verknüpfte Task. Eine frische Generation darf sie übernehmen, auch wenn sie vom ursprünglichen Autor stammt. Ein Review desselben Autors oder Slots wird als nicht unabhängig erfasst und kann die Annahme nicht erfüllen. Cloud-Worker dürfen Review-Tasks übernehmen, wenn eine gültige Route vorliegt; die Richtlinienberechtigung entscheidet weiterhin, ob das Review für den Abschluss zählt.

Wird eine fest zugeordnete Task aus einem sicheren Claim-Grund abgelehnt, entfernt der zugehörige Worker nur seine eigene gespeicherte Zuordnung, protokolliert die Ablehnung und versucht den normalen Selector erneut. Die abgelehnte ID wird in dieser Generation übersprungen. Ein Lease-Konflikt bleibt fail-closed.

Buddha Always-On verwendet ein verifiziert geladenes Ollama-Modell mit ausreichendem konfiguriertem Kontext wieder. Nur dessen Gewichte werden beim zusätzlichen RAM-Bedarf angerechnet; KV-Headroom, Prozess-Overhead, Systemreserve und die freien Persistenzdateisysteme werden weiter geprüft. Ein antwortender Ollama-Server ohne residenten Modellbeleg durchläuft das volle Hostbudget. Der Readback nennt Grundlage und gemessene Budgets; der Wiederaufnahmevertrag akzeptiert keine älteren Nullbudget-Belege.

Vor und nach dem Warten auf Inferenzzugang liest die Runtime ihre aktuelle Modellbindung erneut. Agent, Modellziel, Priorität und Kontextbindung müssen unverändert und aktiviert bleiben. Eine Änderung an einem anderen Worker darf die eigene Inferenz nicht abbrechen: Die globale Katalogversion bleibt für Konfigurations-CAS erhalten, gehört aber nicht zum Identitätsvergleich eines laufenden Modellaufrufs.

Beim frischen Start prüft Buddha Always-On vor dem ersten Queue-Claim seine exakte lokale Ollama-Bindung und die Fackel-Präferenz. Ist das Modell bereits resident, verwendet es den vorhandenen Modellbeleg. Antwortet der Ollama-Server, ohne dass das Modell resident ist, lädt BACH es mit einer leeren Chat-Nachrichtenliste; dadurch entstehen weder ein Taskprompt noch ein Transkript- oder Run-Zähler-Eintrag. Der Aufruf läuft mit Hintergrundpriorität durch das gemeinsame Host-Inferenz-Gate. Bei Compute-Vorrang, nicht bestätigter Kapazität oder nicht erreichbarem Server wartet Buddha und prüft erneut.

Der Controller prüft vor dem nächsten Claim nur den aktuellen Ergebnisbeleg des Workerlaufs. Ist dieser Readback exakt, wird der nächste Claim sofort freigegeben; fehlt ein aktueller Ergebnisbeleg, blockieren auch keine älteren gespeicherten Ergebnisreviews den Claim. Review und Abschlussbewertung laufen über ihre getrennten Aufgaben-/Prüfungswege. Der Controller-Poll reconciled alte Bindings nicht und markiert Ergebnisse nach Ablauf nicht automatisch als `completed_unreviewed`; ungeprüfte Ergebnisse bleiben sichtbar, ohne die normale Queue zu blockieren.

Cloud-Worker mit OpenRouter- oder Ollama-Cloud-Route können alle Aufgabenkategorien übernehmen. Dazu zählt auch eine Ollama-Route, deren Modellname auf `:cloud` endet. Ihre Kategorieauswahl schließt daher keine Taskart aus; konfigurierte Prioritäts- und Tagfilter sowie fremde Zuständigkeiten, Modellbindungen, Slotzuweisungen, Abhängigkeiten und aktive Leases bleiben wirksam. Ihre Claims verwenden auch bei nativer Sequenzdelegation das kürzere Lease-Profil `S` (15 Minuten je Claim/Erneuerung, höchstens zwei Stunden für denselben Lauf), damit ein abgebrochener Cloud-Worker früher wieder freigibt.
