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
Wartungspfad, eine bereits existierende Runtime und symlinkfreie Pfade. Ohne Guard
oder wenn dessen Prüfung scheitert, wird kein persistenter Fehlerbeleg geschrieben;
stderr nennt nur Phase, Fehlerklasse und receipt=unavailable. So bleiben Fehler
vor dem Laden der Konfiguration ohne persistentes failure.json. Auf dem geprüften
Mac schreibt der Writer atomar mit os.fchmod auf Dateimodus 0600. Auf Hosts ohne
os.fchmod bleibt der Belegwriter unavailable; eine plattformübergreifende
Rechtegarantie wird nicht behauptet. Ein Schreibfehler verschleiert nie den
ursprünglichen Fehler. Die reine Statusabfrage bleibt fail-closed und kann einen
frischen, validierten Fehler als last_failure anzeigen; daraus folgt kein
Heartbeat, last_success oder next_due.

Ein LaunchAgent-Plan schreibt scheduler.stdout.log und scheduler.stderr.log
in die lokale Runtime neben der TaskDB; Logs gehören nicht in OneDrive. Diese
Pfade im Plan belegen keine installierte oder laufende Instanz.

## Readbacks für Betriebsnachweis

Ein Dienst gilt erst dann als laufend, wenn ein unabhängiger Status-Readback
Prozessidentität, aktuellen Heartbeat, Checkout-/Konfigurationsidentität und
gültige Ownership bestätigt. Ein Fehlerbeleg diagnostiziert einen fehlgeschlagenen
Versuch, ersetzt aber weder Heartbeat noch last_success oder next_due.
Review und sichere fachliche Korrektur bleiben getrennte Schritte.
