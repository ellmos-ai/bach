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
erneute Anlage desselben Pakets. Ein verlorener Anlage-ACK wird anhand Titel,
Beschreibung und Workerbindung rückgelesen, bevor nochmals angelegt wird.

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
