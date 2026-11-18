# Nativer Doku-Wartungsbetrieb

## Autoritäten und Umfang

BACH konsumiert den Due-/Claim-/Run-Vertrag von `ellmos-scheduler` über
`hub/scheduler_provider.py`. Der Wartungsprozess führt keine Inferenz aus.
Er legt begrenzte Analyseaufgaben über die kanonische Task-API an; TaskDB,
Worker-Leases, Ergebnisablage und persönliche Ergebnisfreigabe bleiben nativ.

Dokuaufgaben erhalten ihre Zuweisung atomar beim Anlegen über
`bach task add ... --assigned bach` beziehungsweise `task.add(assigned_to="bach")`.
Modell-/Slotbindung und Beschreibung werden dabei im selben INSERT gespeichert.
Ohne Zuweisungsoption bleibt der bestehende Datenbankstandard erhalten.
Eine bereits vorhandene falsch zugewiesene Aufgabe wird als Bindungskonflikt
erhalten; der Wartungsowner schreibt sie nicht nachträglich um. Offline-Entwürfe
übertragen ihre gespeicherte Zuweisung bei der Promotion an den Lead. Dessen
zusätzliche Authentifizierungs- und Assignment-Gates gelten weiterhin.

Es gibt einen exklusiven Betrieb mit OS-Prozesslock für die fünf Jobs
`bach.docs.delta` und `bach.docs.routine.*`. Die vier übernommenen Schedulerjobs
für Backup, Rotation und Übersetzungen bleiben erhalten. Dieser Wartungsowner
startet sie nicht. Der alte Session-Daemon bleibt deaktiviert.

Der Delta-Job erkennt integrierte Git-Revisionen nach Merge/Deploy beim nächsten
Takt. Er prüft höchstens 256 geänderte Dateien, legt höchstens ein Paket pro Tick
an und benennt höchstens sechs Quellen im einzelnen Analyseauftrag. Weitere
Quellen bleiben ausdrücklich ungeprüft. Offene Arbeit und Review blockieren
erneute Anlage desselben Pakets. Ein verlorener Anlage-ACK wird über den privaten nativen Producer-Beleg
rückgelesen, bevor nochmals angelegt wird; siehe Repository-Zuordnung unten.

Die Routinen `help_forensic`, `roadmap_review`, `doc_freshness` und
`docs_changelog_review` übernehmen ihre Intervalle und bisherigen Dispatchmarker
aus der vorhandenen Recurring-Konfiguration. Native Scheduler-Receipts sind
anschließend die Laufautorität. Eine ausdrücklich aktivierte Wartungskonfiguration
delegiert diese vier Routinen aus dem alten Recurring-Pfad. Andere Routinen bleiben
dort. Bestehende offene Legacy-Dokuaufgaben werden erhalten und nicht übernommen.

## Start und Status

`bach scheduler maintenance status --json` und `GET /api/maintenance/status`
lesen ausschließlich ein begrenztes Statusreceipt. Der API-Pfad verlangt die
vorhandene Geräteauthentifizierung. Keine Jobanlage, DB-Migration, Lease oder
Dienstaktivierung durch Lesen. PID, Prozessstartzeit, tatsächlicher Scriptpfad,
Konfigurationshash und frischer Heartbeat müssen zusammenpassen.

`bach scheduler maintenance plan --json` erstellt einen unverbindlichen Plan.
`configure` verlangt explizite kanonische Lock-Werkzeuge und den aufgelösten
OneDrive-/Projektzwilling. Root und TaskDB-Verzeichnis werden mitgeschützt.
Die Konfiguration wird einmalig angelegt und nicht überschrieben.
`--enable` aktiviert die Konfiguration, startet aber keinen Prozess.

`launch-plan --json` liefert einen portablen Mac-LaunchAgent-Entwurf mit den
tatsächlich ermittelten Python-, Repo-, TaskDB- und Konfigurationspfaden. Er
installiert oder startet nichts. Für CLI, GUI und Recurring dieselbe kanonische
Konfiguration `<TaskDB-Verzeichnis>/maintenance/config.json` verwenden.
Python muss den Interpreterpfad des BACH-venv beibehalten; sein Symlinkziel kann
ein globaler Interpreter ohne die installierten Module sein. Der Plan darf diesen
Pfad daher nicht durch Auflösen des Symlinks ersetzen.
Abweichende CLI-Runtimepfade sind Diagnose-/Testpfade und kein zweiter Betrieb.

Nach regulärer Integration den Entwurf kontrolliert unter dem Benutzer des
Mac-Dienstes installieren, genau dieses Label laden und `status` rücklesen.
Autostart, automatischer erfolgreicher Lauf und produktive Taskaufnahme benötigen
eigene Laufbelege; die Anwesenheit dieses Dokuments bestätigt sie nicht.

## Budgets, Rückweg und Ergebnisse

Standard: Delta alle 300 Sekunden, Prozessprüfung alle 60 Sekunden. Der Takt ist
konfigurierbar. Pro Tick höchstens ein nativer Job. Mindestens 512 MiB verfügbarer
RAM; Scheduler-DB einschließlich WAL/SHM höchstens 64 MiB und zusätzliche freie
Speicherreserve. Bei Fehlern wartet der laufende Owner exponentiell 60–3600 Sekunden.
Nach Prozessneustart wird Backoff aus den begrenzten nativen Run-Receipts
wiederhergestellt. Native Due-/Run-Receipts und Taskdedup bleiben erhalten.
Keine versteckte automatische Taskbearbeitung.

Alle schreibenden Schritte prüfen Root, TaskDB-Bereich, Projektzwilling und
Zielpfad. Unknown oder Locks blockieren.
Die Scanner-/lock_utils-Quellpaare sind an die bestätigten kanonischen Stände
gebunden. Abweichende oder aktualisierte Werkzeuge verlangen explizite Adoption
des Quellpins; eine frei gewählte Datei namens lock_scan.py erhält keine Autorität.
Der Ownerlock gehört zur kanonischen TaskDB-Runtime, auch bei unterschiedlichen
Repo-Checkouts/Scheduler-State-DBs. Remote-Workerhosts starten keinen Wartungsowner.

Bestehende Jobkonflikte und geänderte
Konfiguration verlangen einen kontrollierten Neustart bzw. einen neuen Plan.
Manuelle native Job-/Globalpause wird nicht überschrieben.

Rückweg: genau den neuen LaunchAgent entladen, `enabled=false` setzen, native
Receipts erhalten. OS-Prozesslock wird beim Exit freigegeben. Alte Doku-Routinen
sind danach wieder dem bisherigen Recurring-Pfad zugeordnet. Den Session-Daemon
dabei nicht starten. Keine fremden Prozesse, Aufgaben oder Jobdefinitionen löschen.

Die vorhandenen Methoden help-forensic, help-expert-review, root-docs-review und
docs-analyse liefern gezielte empirische Prüfschritte. Historische Modell-,
Pfad-, Fanout-, Zeit- und Archivvorgaben darin begründen keine aktuelle Befugnis.
Tatsachendoku folgt bestätigter Realität; gewünschte Verbesserungen bleiben Solltasks.

Dispatch → gespeicherter Vorschlag → unabhängiger Review → tatsächlicher
Dokurepair → persönliche Ergebnisfreigabe sind getrennte Nachweise.
`last_review_success` stammt ausschließlich aus nativ akzeptiertem Ergebnis.
Akzeptierte Analyse ist kein Repair; `last_repair_success` bleibt ohne gesonderten
Reparaturnachweis leer. `last_success` bei einem Schedulerjob bestätigt nur dessen
Dispatchlauf, keine abgeschlossene fachliche Dokumentprüfung.

## Gemeinsame Methode und BACH-Adapter

Neue Delta- und Routineaufgaben verweisen zuerst auf
[doc-reality-loop-bach](../../system/skills/workflows/doc-reality-loop-bach.md).
Der zugehörige [Quellpin](../../system/skills/workflows/doc-reality-loop-source.v1.json)
bindet den gemeinsamen Ocean-Vertrag, Prüfer und beide Workflowsprachen an
unveränderte Git-Blobs eines festen Commits. Eine spätere Quelländerung erfordert
einen neuen geprüften Pin; der Adapter lädt oder startet keinen Fremdcode.

Die bisherigen vier Workflowtexte liefern Herkunft und Fachkontext. Der Adapter
ordnet ihre Varianten zu und verlangt Aussagen-/Leseraufnahme, getrennte
Quell- und Laufzeitbelege, erhaltene Sollanforderungen und eine vollständig
belegte Zustandskette. Er beauftragt weiterhin ausschließlich Analyse.

Bekannte exakte Altbeschreibungen bleiben bei der ACK-Recovery zulässig.
Tasktitel, Bindung, Kategorie und offene Arbeit werden weiter geprüft;
alte Tasks und Resultate werden nicht migriert. Neue Aufgaben erhalten die
Adapteranweisung. Dieser Quellenstand ist kein Nachweis für Aktivierung,
tatsächlichen Prüflauf, Registerintegration oder erfolgreichen Dokurepair.


## Repository-Zuordnung des nativen Wartungsproduzenten (BACH #4241)

Der installierte Wartungsowner verwendet weiterhin den lokalen nativen
TaskHandler. Sein interner Create-Einstieg erhält eine prozessprivate,
nicht serialisierbare Producer-Capability. Ein öffentliches Taskfeld, ein
creation_origin, project, Titel oder Eintrag in documentation.json
kann diese Capability nicht erzeugen.

Vor einer neuen Anlage müssen der geschützte konfigurierte BACH-Root, dessen
sauberer HEAD und Origin sowie der bereits vom Sourceowner provisionierte
öffentliche Clone für exakt diese Revision übereinstimmen. Der Producer liest
die bestehende Registry und den Source-Proof; er klont nichts. Ein fehlender
Clone, unbekannte Sperrauskunft oder abweichender aktueller öffentlicher
Default-Branch verhindert die Anlage sichtbar als maintenance_source_unverified
beziehungsweise nativer Fencefehler. Der Sourceowner muss den passenden Clone
ausdrücklich vor dem Dispatch bereitstellen.

### Atomarer Beleg und Wiederanlauf

maintenance_task_intents ist eine private Metadatentabelle **in derselben
kanonischen ~/.bach/bach.db**. Sie ist keine zweite Taskliste. Der bestehende
lokale Task-INSERT, die ursprüngliche Inhaltsversion, der private Intent und
sein nativer maintenance_producer_create-Auditbeleg werden in einer
SQLite-Transaktion festgeschrieben. Ein Fehler rollt alle vier zurück.
Lesepfade erstellen keine Tabellen. Ein verschwindender DB-Pfad wird
mit mode=ro/mode=rw nicht neu angelegt.

Der Operationsschlüssel bindet den physischen Root, Delta/Routine, Paketname
und Quellrevision beziehungsweise native Fälligkeit. Eine bestätigte Operation
hat genau eine Task-ID. Ein neuer Aufruf liest zuerst diesen Beleg, bevor er
einen neuen Task erzeugen darf. Ein unbestätigter öffentlicher Task mit
passendem Titel wird nicht als nativer Producer-Task übernommen.
Pro Paket/Routine wird eine weitere offene native Operation im
Task-Create-Writer ausgeschlossen.

Die Registry-Zuordnung erfolgt anschließend über
enroll_maintenance_task_repository(client, task_id, expected_registry_sha256=...).
Repo, ursprünglicher Source-Pin und Taskversion stammen ausschließlich aus dem
privaten Beleg. Der Helfer nutzt den gemeinsamen Registry-Writer-Fence und eine
explizite Digest-CAS. Git- und Sourceprüfungen laufen außerhalb der
SQLite-Schreibtransaktion; unmittelbar vor dem Registry-Publish werden Beleg,
Taskversion, freier Pendingzustand und physische DB-Identität unter
BEGIN IMMEDIATE erneut geprüft. Der Helfer verändert weder Task noch Lease,
Resultat oder Workerrechte.

| Unterbrechung / Änderung | Nativer Wiederanlauf |
| --- | --- |
| Vor dem Create-Commit | Keine halbe Task/Beleg-Kombination; derselbe Auftrag kann erneut angelegt werden. |
| Create-Commit erfolgt, ACK oder Cache-Schreiben fehlt | Persistenten Operationsbeleg lesen; dieselbe Task-ID zuordnen und Cache rekonstruieren. |
| Registry-Fence/CAS oder Source-Prüfung verhindert Enrollment | Task und Producer-Beleg bleiben erhalten; der nächste Lauf versucht die ausstehende Zuordnung vor dem bisherigen Pending-Return erneut. |
| Registry-Publish erfolgt, ACK fehlt | Vorhandene passende Bindung wird als vollständig bestätigt; kein zweiter Task und kein erneuter Registry-Write. |
| Main wurde inzwischen weiterentwickelt | Der bei der Anlage öffentlich bestätigte immutable Pin bleibt erhalten; kein automatisches Repinning auf die neue Revision. |
| Ungebundener Task wurde inhaltlich geändert | maintenance_task_version_changed; kein automatisches Umschreiben oder neuer Task. Eine ausdrückliche Operatorprüfung ist nötig. |
| Ungebundener Task ist bereits geleast | maintenance_task_not_pending; Lease und Task bleiben unverändert. |
| Bereits passend gebundener Task wurde später legitim bearbeitet | Bindung bleibt vollständig; die frühere Create-Version wird nicht zu einer dauerhaften Bearbeitungssperre. |
| Alter offener Cacheverweis ohne Producer-Beleg und ohne Registry-Bindung | maintenance_legacy_enrollment_required; ausschließlich expliziter Operator-Backfill. |

Delta und Routinen rekonstruieren ihre neuesten nativen Belegreferenzen
begrenzt pro Paket/Routine. Dies passiert auch dann, wenn eine offene Aufgabe
normalerweise zu idle beziehungsweise waiting_review_or_work führen würde.
Fehler bleiben native fehlgeschlagene Schedulerläufe mit konkretem Grund;
ein erzeugter Task allein gilt nicht als erfolgreich zugeordnet.


Ein erneutes ensure mit derselben Operations-ID muss genau denselben
normalisierten Create-Auftrag enthalten: Titel, Beschreibung, Priorität,
Modell-/Slotbindung und die übrigen nativen Create-Felder. Jede Abweichung
endet vor Enrollment mit maintenance_operation_conflict, auch wenn der
ursprüngliche Create-Commit bereits bestätigt wurde. Die separate
references-Rekonstruktion nimmt keinen neuen Auftrag entgegen; sie liest nur
den dauerhaften nativen Beleg und erhält dessen bestätigten immutable Pin.
Ein später legitimer Task-Edit wird damit weder überschrieben noch als neuer
Create-Auftrag ausgegeben. Äquivalente UTC-Schreibweisen einer nativen
Routine werden für Operations-ID, Titel und Beschreibung gleich normalisiert.

Private Producer-Aufrufe können keine Federation-, Mirror- oder Offline-
Entwurfszweige betreten. Ein Verlust der lokalen Lead-/Isolated-Rolle wird
an den nativen Transaktionsgrenzen erneut geprüft und lässt keine Task oder
halben Producer-Beleg zurück. Nach einer externen Sourcebestätigung prüft
der Producer Live-HEAD, Origin, sauberen Worktree und native Fences erneut,
bevor er eine neue Task anlegt. Die Wiederaufnahme eines bereits bestätigten
Belegs verlangt weiterhin kein Repinning auf einen späteren Mainstand.

### Kontrollierter Backfill des belegten Altbestands

Der erstmalig bestätigte Bestand umfasst **nur** die Task-IDs
4137, 4138, 4139, 4140, 4141, 4142, 4239. Weitere seitdem erzeugte Tasks
gehören nicht automatisch zu diesem Auftrag. Vor jedem Schreibschritt sind
Task, native Inhaltsversion, Status und Lease frisch zurückzulesen.
Eine aktive fremde Lease sperrt den Schritt. Ein privater Producer-Beleg
wird für Altbestand nicht nachträglich erfunden.

| Task | Historischer fachlicher Gegenstand |
| --- | --- |
| 4137 | Delta governance, Revision 4317cb432da26b734ec9d600791013402bf89278 |
| 4138 | Delta gui, gleiche Revision |
| 4139 | Delta memory, gleiche Revision |
| 4140 | Delta root, gleiche Revision |
| 4141 | Delta scheduler, gleiche Revision |
| 4142 | Delta workers, gleiche Revision |
| 4239 | Routine roadmap_review, Revision 1bfe7f328df074ffac74f029b772afb70cf54b78 |

Für jede dieser Aufgaben muss der Operator den historischen Analysegegenstand
von der nun ausdrücklich autorisierten Ausführungsbasis unterscheiden.
Der allgemeine enroll_task_repository-Operatorpfad verlangt einen aktuell
öffentlich bestätigten Source-Pin; er akzeptiert keinen bloß behaupteten
historischen SHA und provisioniert selbst keinen Clone.

Der konkrete Ablauf ist:

1. Den genauen Bestand zurücklesen und einen expliziten Plan mit Task-ID,
   Vorversion, unverändertem historischem Analysecommit, gewähltem neuen
   Ausführungscommit und erwarteten Zielinhalten festhalten. Eine Titelsuche
   dient nur zur Inventarisierung. project oder source sind kein Beweis.
2. Den vorhandenen expliziten Sourceowner
   worker_git.provision_public_source_clone("ellmos-ai/bach") aufrufen und
   dessen tatsächlich zurückgelieferte Revision samt physischem Clone
   verifizieren. Ein Verzeichnisname allein ist kein Source-Proof.
3. Falls Ausführungsbasis und bisheriger fachlicher Quellverweis abweichen,
   **nur description** über den nativen versionsgeprüften Task-Mutationspfad
   präzisieren. Der bisherige Quellen-/Manifestinhalt bleibt nachvollziehbar.
   Eine eindeutige Ergänzung benennt den historischen Analysecommit und
   separat ellmos-ai/bach@<bestätigter Ausführungscommit>. Falls der alte
   Text diese historische Revision als „tatsächlichen Quellcommit“ bezeichnet,
   diese Formulierung ausdrücklich zu „historischer Analysecommit“ präzisieren.
   Der Auftrag bleibt reine Analyse; ein fehlender oder nicht bestätigbarer
   historischer Gegenstand ist ein sichtbarer Blocker.
4. Die neue native Inhaltsversion und den Auditbeleg zurücklesen.
   title, status, assigned_to, Modell-/Slotfelder, project, source,
   Fences, Leases und Resultate erhalten durch den Backfill keine neue
   Bedeutung. task_version wird vom nativen Owner ermittelt, nie manuell
   gesetzt. Für unveränderte Beschreibungen bleibt die frische Vorversion
   maßgeblich.
5. Pro Task den aktuellen Registry-Digest lesen und ausschließlich den
   vorhandenen Operatorpfad aufrufen:

       enroll_task_repository(
           client, task_id,
           repository="ellmos-ai/bach",
           task_version=verified_native_version,
           source_sha=verified_execution_sha,
           expected_registry_sha256=verified_registry_sha256,
           operator="operator:maintenance-backfill",
       )

6. Task/Lease erneut lesen, resolve_task_repository(task_id) und das
   bestehende Worker-Repository-Gate prüfen. Dabei wird keine Aufgabe
   übernommen und kein Modell gestartet. Eine passende Bindung ist ein
   eigenes Abnahmeergebnis, kein automatischer Arbeits- oder Reviewabschluss.

**Unklarer Operator-ACK:** Kein neues Task-Add und keine blind wiederholte
Mutation. Zuerst den nativen Audit-/Taskstand und den geschützten
Registry-Eintrag gegen denselben konkreten Plan prüfen. Bereits vorhandene
passende Zuordnung bedeutet Abschluss. Eine bestätigte Beschreibungskorrektur
ohne Bindung wird mit ihrer zurückgelesenen nativen Version fortgesetzt.
Abweichende Version, Source-Pin, Bindung oder Lease erfordert einen neu
bestätigten Plan. Ist Main während eines unvollständigen Backfills
weitergelaufen, wird kein neuer Source-Pin stillschweigend eingesetzt.
Ein fertiger älterer immutable Pin bleibt gültig; ein noch nicht genehmigter
aktueller Operator-Write muss dessen aktuellen Public-Source-Vertrag erfüllen.

**Weitere Inventarisierung:** Über den vorhandenen nativen Task-Lesepfad
alle Zustände mit Doku-Delta oder Doku-Routine, dem bestätigten Root-Kürzel,
Kategorie WORKER und Zuweisung BACH sichten; created_at ab dem Beginn
der Liveabnahme zusätzlich erfassen. Der Library-Reader
task.list(status=None, filter_text="Doku-", assigned_to="BACH", limit=None)
liefert dafür die vollständige Menge ohne stillen ersten-Seiten-Abbruch.
Titel, Datum und Cache sind nur Selector-/Diagnosefelder. Neue IDs werden
einzeln mit nativem Inhalt, Audit, Lease und Registry zurückgelesen und
ausdrücklich in einen weiteren Plan aufgenommen.

Eine nach hartem Prozessverlust zurückgebliebene gemeinsame .operator-lock-Datei
bleibt registry_busy. Der Producer übernimmt oder löscht keinen fremden Writer-Fence.
Nach dessen ausdrücklich bestätigter Reparatur durch den Operator wird derselbe
native Task-/Producer-Beleg fortgesetzt; eine unbekannte Fenceinhaberschaft
ist kein Anlass, einen zweiten Task anzulegen.
