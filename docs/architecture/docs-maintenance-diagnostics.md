# Dokumentationswartung: Dispatch, Review-Handoffs und Fehlerbelege

## Zuständigkeit und Betriebsgrenze

Die Dokumentationspflege wird durch den vorhandenen ellmos-scheduler-Owner
koordiniert. launch-plan beschreibt eine mögliche LaunchAgent-Konfiguration und
aktiviert keinen Dienst. Seine Felder installed=false und started=false gelten
ausschließlich für diesen Plan. Sie sind keine Aussage darüber, ob eine native
Instanz bereits installiert ist oder läuft.

Ein Installationsnachweis benötigt einen gesonderten Readback der tatsächlich
bereitgestellten Artefakte, Konfiguration und Dienstregistrierung. Ein validierter
Prozess-/Heartbeatnachweis belegt dagegen den Lauf zum angegebenen
Beobachtungszeitpunkt; er bestätigt keinen Installations- oder Startvollzug durch
den beschriebenen Plan. Installation und Laufzeitneustart brauchen weiterhin
eine eigene Integrationsfreigabe. Ein gemessener Lauf erzeugt diese Freigabe nicht.

Der Delta-Dispatcher vergleicht einen Quellstand mit dem gespeicherten Cursor,
ordnet geänderte Pfade begrenzten Dokumentationspaketen zu und dispatcht höchstens
ein Paket pro Tick. Die Task- und Ergebnisautorität bleibt bei der nativen
Task-API. Ein Cursor- oder Dispatch-Readback ist kein Beleg für eine fachliche
Korrektur.

## Exakter Review-Handoff und BACH-Aufgabenwiedererkennung

Der Dispatcher verlangt für jede Wiedererkennung die vollständige erzeugte
Aufgabenidentität: Titel, Beschreibung einschließlich Quellrevision und
Dateiliste, Kategorie WORKER, Slotbindung und erforderliches Modell.

Bei normalisiertem assigned_to=bach kann eine passende vorhandene Aufgabe
unabhängig von ihrem Status wiedererkannt werden. Für andere Assignees ist
hingegen der Status review und eine nicht leere Zuordnung erforderlich.
Die Assignee-Identität wird dadurch nicht als menschlich verifiziert.
Die exakte Wiedererkennung verhindert eine konkurrierende Ersatzaufgabe.

Diese Wiedererkennung ist lesend. Sie ändert weder Taskstatus noch Assignee,
akzeptiert kein Ergebnis und setzt weder last_review_success noch
last_repair_success. Sie belegt keine abgeschlossene fachliche Prüfung.
Beim Review-Handoff bleibt review erhalten; im BACH-Fall bleibt der tatsächlich
gelesene Status unverändert. Abweichende Beschreibung, Kategorie, Slot- oder
Modellbindung sowie eine leere Zuordnung bleiben ein Binding-Konflikt.
Bei einer nicht zu BACH gehörenden Zuordnung ist auch ein anderer Status als
review ein Binding-Konflikt; es wird keine Ersatzaufgabe angelegt.

## Fehlerbeleg und lokale Logs

Ein Fehlerbeleg liegt unter failure.json im kanonischen lokalen
Wartungs-Runtime-Verzeichnis neben den übrigen Runtime-Belegen. Das Schema
bach.maintenance-failure.v1 enthält Zeitstempel, eine erlaubte Phase, die
Exception-Klasse, die Hostkennung und die Git-Revision, sofern sie aus dem
tatsächlichen Checkout validiert werden kann. owner_generation wird nur nach
erfolgreich erworbener Prozess-Ownership gesetzt; vor diesem Schritt bleibt der
Wert null. Es gibt keine Tracebacks, Exception-Texte, Quellpfade,
Quellzeilen, Task-Inhalte oder Zugangsdaten.

Der Writer verlangt einen verfügbaren offiziellen Lock-Guard aus einer
validierten Wartungskonfiguration, den aus der nativen TaskDB abgeleiteten lokalen
Wartungspfad, eine bereits existierende Runtime und symlinkfreie Pfade. Beim frühen
Launcherfehler lädt der Entry-Point die Konfiguration aus genau diesem Runtime-Pfad,
prüft, dass maintenance_runtime exakt aus SYSTEM_ROOT/hub/_services/docs/maintenance_runtime.py
stammt, und baut denselben CanonicalLockGuard wie der normale CLI-Serve-Pfad. Erst wenn
Konfiguration, Guard und dessen Lockprüfungen verfügbar sind, darf der redigierte
Fehlerbeleg geschrieben werden. Fehlt etwa der Scanner oder stimmt sein Pin nicht,
bleibt failure.json aus und stderr nennt nur Phase, Fehlerklasse und
receipt=unavailable. Ein Fehler beim Belegschreiben verschleiert nie den
ursprünglichen Fehler; Pfade, Exceptiontexte und Tracebacks werden nicht ausgegeben.
Die historische Exit-1-Ursache ist damit weiterhin nicht diagnostiziert.

Auf dem geprüften Mac schreibt der Writer atomar mit os.fchmod auf Dateimodus 0600.
Auf Hosts ohne os.fchmod bleibt der Belegwriter unavailable; eine
plattformübergreifende Rechtegarantie wird nicht behauptet. Die reine Statusabfrage
bleibt fail-closed und kann einen frischen, validierten Fehler als last_failure
anzeigen; daraus folgt kein Heartbeat, last_success oder next_due.

Ein LaunchAgent-Plan nennt scheduler.stdout.log und scheduler.stderr.log in der
lokalen Runtime neben der TaskDB; Logs gehören nicht in OneDrive. Umask=077 begrenzt
die Rechte neu erzeugter Ausgabedateien. Das gilt erst für einen künftigen geplanten
Start und ändert weder die installierte Plist noch vorhandene Logdateien. Planfelder
belegen keine installierte oder laufende Instanz; der Plan bleibt installed=false und
started=false.

## Readbacks für Betriebsnachweis

Ein Dienst gilt erst dann als laufend, wenn ein unabhängiger Status-Readback
Prozessidentität, aktuellen Heartbeat, Checkout-/Konfigurationsidentität und
gültige Ownership bestätigt. Der Beleg gilt für seinen Beobachtungszeitpunkt;
ein gespeicherter Snapshot ist kein ungeprüfter Echtzeitstatus.

last_success wird aus dem zuletzt ausgewählten Run eines Jobs projiziert:
Nur wenn dieser succeeded ist, wird dessen finished_at übernommen.
last_success=null bedeutet deshalb nur, dass dieses Readback keinen erfolgreichen
Abschluss als last_success ausweist. Eine frühere erfolgreiche Ausführung kann
weiterhin in der Runhistorie stehen. Daraus folgt weder, dass der Job nie
ausgeführt wurde, noch dass er zuvor nie erfolgreich war.
Ein Fehlerbeleg diagnostiziert einen fehlgeschlagenen Versuch, ersetzt aber
weder Heartbeat noch last_success oder next_due. Ein erfolgreicher Delta-Dispatch
belegt keine abgeschlossene fachliche Dokuprüfung oder Reparatur. Review und
sichere fachliche Korrektur bleiben getrennte Schritte.


## Bestätigtes Sperrwarten und lokale Betriebsbelege (#4220)

Ein bestätigter Lock ist ein eigener Zustand. Der native Scanner muss aus einer
gepinnten Quelle stammen und einen vollständigen Scan, das angefragte Ziel,
gültige Twin-Nachweise und zum Ergebnis passende Exitcodes liefern. Ein Fehler
auf einem späteren erforderlichen Wurzelpfad hat Vorrang vor einem zuvor
gefundenen Lock. Fehlende Vollständigkeit, ungültige Daten, Timeout und unbekannte
Zustände werden nicht in erwartetes Sperrwarten umgedeutet. Die eng begrenzte
Ausnahme für einen bereits belegten OneDrive-Pointer akzeptiert nur den dafür
vorgesehenen Exitcode 1.

Die Prozess-Ownership und die redigierte Statusprojektion sind von der
Arbeitsfreigabe getrennt. Ihr Zielguard darf ausschließlich `owner.lock`,
`status.json` und `status.<32 lowercase hex characters>.tmp` im kanonischen lokalen Wartungsverzeichnis neben
der TaskDB freigeben. Er prüft dieses Ziel mit demselben gepinnten nativen
Scanner vollständig; Symlinks und OneDrive-Runtime-Pfade sind ausgeschlossen.
Er besitzt keine Befugnis für Scheduler-Datenbank, Dokumentationscursor,
Konfiguration, Binding-Anfragen oder Taskdaten. Dafür bleibt der vollständige
Arbeitsguard mit Repository und Projektzwilling verbindlich.

Wenn der Arbeitsguard eine Sperre bestätigt, bleibt der alleinige lokale
Prozess-Owner bestehen und veröffentlicht `state=waiting_for_lock`, sofern
dessen eigener Runtime-Pfad frei ist. Dieser Zustand startet keine Jobs und
liefert keine neuen Erfolgs- oder Reviewbelege. `running=true` bedeutet hier
ausschließlich, dass Prozess und Lebenszeichen verifiziert wurden. Vor dem
nächsten Arbeitsversuch wird die gesamte Arbeitsfreigabe erneut geprüft.

Das Warten beginnt mit zehn Sekunden und wächst bis höchstens zum konfigurierten
Pollintervall; ein kürzeres Pollintervall begrenzt schon den ersten Schritt.
Eine zusammenhängende Wartephase hat ein Budget von 1.800 Sekunden zuzüglich
der laufenden begrenzten Scan-/Statusoperation. Danach endet der Versuch mit
`MaintenanceLockWaitTimeout` in der Phase `lock_wait`. Ein Stop-Signal
unterbricht das Warten unmittelbar. Nur ein erfolgreich freigegebener Tick setzt
das Wartebudget zurück. Ein unbekanntes Prüfergebnis beendet den Versuch sofort.

Ist der Runtime-Pfad selbst gesperrt, werden weder ein neuer Owner noch neue
Statusdateien geschrieben. Auch dann wird nur bei bestätigtem Lock begrenzt
gewartet. Ohne gültigen aktuellen Beleg bleibt die Statusanzeige unverifiziert.
Nach Neustart gelten dieselben Prüfungen und eine neue Ownergeneration;
gespeicherte PID-Zahlen ersetzen die Betriebssystem-Ownership nicht.

Archivierte native Aufgaben bleiben in der Dokumentationsprojektion sichtbar.
`task_status=archived` ist ein bekannter Status, aber kein angenommener
Ergebnisnachweis. Unbekannte Statuswerte bleiben ausgeschlossen. Dies behebt
insbesondere den beobachteten Fall, in dem ein archivierter Routine-Task den
gesamten aktuellen Dienstnachweis ungültig erscheinen ließ.

Die bestehende Delta- und Routinefälligkeit wird durch diese Änderung nicht
umgeschrieben. Catch-up- und Reihenfolgesemantik des Scheduler-Moduls sind eine
gesonderte Frage.


The status publisher opens its private temporary file exclusively (mode 0600),
checks the regular single-link descriptor against the directory entry, fsyncs,
and atomically replaces status.json. Existing temporary files are never truncated.
Only the exact newly allocated temporary entry may be removed on cleanup, and only
after the native runtime guard still approves. Interrupted older entries remain
untouched and do not block the next status write. Existing owner files must be
regular, single-link, owned by the current user and match the opened descriptor;
a hardlinked or replaced owner is rejected before use.

The 30-minute continuous lock-wait budget starts when the lock is confirmed,
before publishing its status. It is checked again after every interruptible wait,
before a new work round and after the work guard before dispatch; releasing a lock
at the deadline cannot start one extra job.

## Verpasste Delta-Intervalle (BACH #4225 / Ocean #49)

Die Delta-Prüfung prüft idempotent den aktuellen Repository-Zustand und verwendet
ab Scheduler 0.3.7 ausdrücklich die native Policy coalesce_latest. Nach längeren
Unterbrechungen fasst ein Claim frühere unbeanspruchte Delta-Termine zusammen.
Der Zeitanker bleibt erhalten; das nächste limit=1-Fenster kann anschließend
eine andere fällige Routine aufnehmen.

Die vier Routinen behalten replay und ihre bestehenden Intervalle von
14/14/60/30 Tagen. Ein bereits beanspruchter, später abgelaufener Delta-Lauf wird
mit seinem ursprünglichen Termin wiederholt. Zusammengefasste Termine erscheinen
nicht als einzelne ausgeführte oder erfolgreiche Läufe. Die Modulhistorie führt
coalesced_from und coalesced_count am tatsächlich beanspruchten Lauf.

create_documentation_scheduler prüft den exakten Capability-Vertrag
ellmos.scheduler.misfire-policy.v1 vor der Adapterkonstruktion. Ein altes Modul
wird mit scheduler_misfire_policy_unavailable abgewiesen. Die Wartung prüft die
bestehende Delta-Definition und ändert ausschließlich die Policy über den nativen
CAS mit beobachteter Generation und bisheriger Policy. Ein aktiver Claim oder
eine inzwischen geänderte Version verhindert die Umstellung. Es gibt keine
direkte SQL-Korrektur und keinen manuellen Sprung von Fristdaten.

### Aktivierungsreihenfolge

Zuerst den separat geprüften Scheduler-Commit installieren, dann den BACH-Commit
mit exakt darauf zeigendem Dependency-Pin. Vor Aktivierung Installationsprovenienz,
Importpfad, Capability und den einzigen Runtime-Owner prüfen. Die native Migration
muss ohne konkurrierenden aktiven Claim erfolgen; bei Konflikt frisch beobachten.
Modul und Adapter wurden auf einer isolierten Kopie des historischen
f2740ba7-Zustands geprüft. Die Kopie hatte neun Jobs und 5500 Laufbelege;
Schema- und Policy-Migration erhielten alle bisherigen Termine und Laufbelege.
Nur die Delta-Policy änderte sich. Zwei synthetische lokale Probeläufe belegten
danach Delta und eine fällige Routine. Dabei wurde keine native Task-API benutzt.

Ein altes Modul berücksichtigt die neue Policy nicht. Daher zuerst den Owner
koordiniert anhalten und den Policy-/Build-Rollback explizit planen; keine
parallelen alten und neuen Writer. Der getestete Quellcodezustand ersetzt
keinen Nachweis einer aktivierten Installation.

Geprüfter Scheduler-Quellcommit für diesen Anschluss: 698b22ceccde4f83c2680d2d957e394317667869 (0.3.7). Der Dependency-Pin in requirements.txt bezeichnet genau diesen Stand.

Die unabhängige Prüfung ergänzte einen Fall mit getrennten abgelaufenen
Claims und erfolgreichem Zwischenlauf. Der gepinnte Folgestand wählt alle
ausstehenden Wiederholungen unabhängig vom regulären Fälligkeitszeiger aus
und erhält den Fortschritt bereits zugelassener Termine. Erfolgreiche
Zwischenläufe werden weder wiederholt noch als ausgelassen mitgezählt.
