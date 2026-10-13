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
