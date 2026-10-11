# Dokumentationswartung: Dispatch, Review-Handoffs und Fehlerbelege

## Zuständigkeit und Betriebsgrenze

Die Dokumentationspflege wird durch den vorhandenen ellmos-scheduler-Owner
koordiniert. Dieser Patch ergänzt keinen zweiten Zeitplaner und aktiviert keinen
Dienst. launch-plan beschreibt nur eine mögliche LaunchAgent-Konfiguration;
installed=false und started=false bleiben die maßgeblichen Readbacks. Eine
Installation oder ein Laufzeitneustart braucht eine eigene Integrationsfreigabe.

Der Delta-Dispatcher vergleicht einen Quellstand mit dem gespeicherten Cursor,
ordnet geänderte Pfade begrenzten Dokumentationspaketen zu und dispatcht höchstens
ein Paket pro Tick. Die Task- und Ergebnisautorität bleibt bei der nativen
Task-API. Ein Cursor- oder Dispatch-Readback ist kein Beleg für eine fachliche
Korrektur.

## Exakter Review-Handoff

Eine vorhandene Aufgabe im Status review kann als bereits dispatcht/recovered
wiedererkannt werden, wenn ihre vollständige Identität zur erzeugten Doku-Aufgabe
passt: Titel, Beschreibung einschließlich Quellrevision und Dateiliste,
Kategorie WORKER, gebundener Slot und erforderliches Modell. Ein nicht leerer Wert im Feld assigned_to ist bei dieser exakten
Übereinstimmung zulässig. Die Identität des Assignee wird dabei nicht als
menschlich verifiziert. So wird ein bestehender Review-Handoff nicht als
konkurrierende Aufgabe dupliziert.

Diese Wiedererkennung ist lesend. Sie ändert weder Task noch Assignee, akzeptiert
kein Ergebnis und setzt weder last_review_success noch last_repair_success.
Der Status bleibt review, und semantic_review_completed bleibt false.
Abweichende Beschreibung, Kategorie, Slot, Modell oder Status sowie ein leerer
Assignee bleiben ein Binding-Konflikt; es wird keine Ersatzaufgabe angelegt.

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
gültige Ownership bestätigt. Ein Fehlerbeleg diagnostiziert einen fehlgeschlagenen
Versuch, ersetzt aber weder Heartbeat noch last_success oder next_due.
Review und sichere fachliche Korrektur bleiben getrennte Schritte.
