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
Wartungs-Runtime-Verzeichnis neben den übrigen Runtime-Belegen. Das begrenzte
Schema enthält observed_at, phase, die Exception-Klasse und höchstens zwölf
Traceback-Orte mit Dateipfad, Zeile und Funktionsname. Für Dateien außerhalb des
BACH-Roots wird nur ein bereinigter Basisname protokolliert. Exception-Text,
Quellzeilen, lokale Variablen, Task-Inhalte und Zugangsdaten gehören nicht in
diesen Beleg.

Die Datei wird über denselben geschützten atomaren Schreibpfad wie der
Wartungsstatus geschrieben. Bei fehlender oder verweigerter Lock-Prüfung wird
kein Fehlerbeleg erzwungen. stderr nennt nur Phase und Fehlerklasse. Ein
LaunchAgent-Plan schreibt scheduler.stdout.log und scheduler.stderr.log
in die lokale Runtime neben der TaskDB; Logs gehören nicht in OneDrive. Diese
Pfade im Plan belegen keine installierte oder laufende Instanz.

## Readbacks für Betriebsnachweis

Ein Dienst gilt erst dann als laufend, wenn ein unabhängiger Status-Readback
Prozessidentität, aktuellen Heartbeat, Checkout-/Konfigurationsidentität und
gültige Ownership bestätigt. Ein Fehlerbeleg diagnostiziert einen fehlgeschlagenen
Versuch, ersetzt aber weder Heartbeat noch last_success oder next_due.
Review und sichere fachliche Korrektur bleiben getrennte Schritte.
