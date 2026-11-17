# Bestätigte Freigabe von pausierten Compute-Jobs

Stand: 2026-11-17. Umsetzung: BACH #4216.

## Automatische Freigabe

Der bestehende Resume-Monitor und die Startup-Recovery unterscheiden drei
Ergebnisse einer nativen Ollama-Beobachtung:

| Ergebnis | Beleg | Verhalten |
|---|---|---|
| Geladen | Gültige, nicht leere `models`-Liste | Nicht fortsetzen |
| Abwesend | Gültige, leere `models`-Liste | Weitere Freigabeprüfungen zulässig |
| Unbekannt | Transport-, JSON- oder Schemafehler | Nicht fortsetzen |

Auch ein anderes als das ursprünglich angeforderte Modell belegt denselben
Hostspeicher. Deshalb genügt das Verschwinden nur eines Modellnamens nicht.
Die Probe verwendet die übergebene Ollama-URL; der bestehende Standard bleibt
`http://localhost:11434`. Sie startet oder entlädt keine Modelle.

Der Monitor prüft standardmäßig alle 30 Sekunden. Er verlangt 90 Sekunden
durchgehend bestätigte Abwesenheit und danach eine weitere Prüfung nach fünf
Sekunden. Ein unbekanntes oder geladenes Ergebnis setzt das Abwesenheitsfenster
zurück. Die Frist wird monoton gemessen. Nach Ablauf des standardmäßigen
Vierstundenbudgets bleiben Pausebelege erhalten; es gibt keine automatische
Freigabe durch Zeitablauf.

Startup-Recovery führt eine eigene frische Probe aus. Bei geladenem Modell oder
unbekanntem Zustand bleibt sie mit `compute_recovery_deferred` und einem
konkreten Grund stehen. Ein weiterer automatischer Dauerprozess wird dadurch
nicht gestartet. Der verbleibende Zustand muss später erneut überprüft werden.

## Pausezulassung vor Modellanfragen

Eine unvollständige oder ungeprüfte Compute-Pause ist keine erfolgreiche
Zulassung. Ungültige aktive Job-/PID-Angaben, nicht unterstützte Plattformen,
fehlende Prozessidentität und Fehler beim Speichern, Signalisieren oder
Bestätigen werden als `ComputePauseError` weitergegeben. Der Fehler trägt nur
die zuvor tatsächlich bestätigten eigenen Teilpausen.

Beide Telegram-Einstiege und der bisherige CLI-Worker stoppen in diesem Fall
vor dem Modellaufruf. Sie versuchen die eigenen bestätigten Teilpausen nur nach
einer frischen leeren Ollama-Probe zurückzugeben. Ein anderer oder ungeprüfter
Pausenbeleg wird dabei nicht übernommen. Der CLI-Worker gibt seine Task zurück;
sein Einmallauf endet bei dieser Zulassungsverweigerung mit Exitcode 1.
Kontinuierliche Wiederholungen warten mindestens den bestehenden Prüftakt.

Die Startupmeldung unterscheidet leere Recovery von zurückgestellten oder
teilweise verbleibenden Pausen. Unbestätigte Freigaben werden weder im Chat
noch im CLI-Status als erfolgreich fortgesetzt bezeichnet.

## Besitznachweis für Prozesssignale

Die bestehende Datei `~/.memwatchdog/bot_paused_pids.json` enthält für neue Pausen
einen versionierten Beleg mit PID, Prozesserstellungszeit, Pause-ID und Zustand.
Ein OS-Dateilock serialisiert Änderungen dieser Datei. Atomare Ersetzung und
Synchronisierung auf den Datenträger sichern den Beleg vor dem jeweiligen
Signal sowie die anschließende Bestätigung.

Der Zustandsablauf ist:

1. Pauseabsicht mit Prozessidentität speichern.
2. Dieselbe Prozessidentität erneut prüfen und SIGSTOP senden.
3. Den gestoppten Zustand bestätigen und die eigene Pause speichern.
4. Vor SIGCONT Besitz und aktuelle Prozessidentität erneut prüfen.
5. Resumeabsicht speichern, SIGCONT senden und den nicht mehr gestoppten Zustand
   bestätigen. Erst dann darf der zugehörige Restbeleg entfernt werden.

Die nach außen verwendete PID-Liste bleibt listenkompatibel. Intern trägt sie
den ursprünglichen Pausebeleg. Ein später ausgeführter Monitor darf dadurch
keine neuere Pause derselben PID oder desselben Prozesses übernehmen.
`resume_compute_jobs()` liefert nur die tatsächlich bestätigten Resume-PIDs
zurück; Monitor-Callbacks erhalten diese bestätigte Teilmenge.

Unklare Signalabschlüsse werden nicht automatisch wiederholt. Bereits
gestoppte Prozesse werden beim Pausieren nicht nachträglich als eigene Pause
übernommen. PID-Wiederverwendung, unbekannte Prozesszustände und fehlende
Prozessrechte erzeugen einen erhaltenen Prüfbedarf.

## Legacy- und Fehlerreste

Alte Dateien mit ausschließlich PID-Nummern enthalten keinen ausreichenden
Identitätsnachweis. Sie werden weder nachträglich mit der aktuellen
Prozesserstellungszeit aufgewertet noch durch Recovery automatisch signalisiert
oder gelöscht. Logs nennen `legacy_unverified` beziehungsweise einen anderen
konkreten Haltegrund. Neue versionierte Belege markieren unklare Reste mit
`manual_review_required`.

Eine teilweise erfolgreiche Freigabe entfernt nur die bestätigten Einträge.
Andere Einträge und der Sessionbeleg bleiben erhalten. Solange die Pause-Datei
besteht, liefert die vorhandene adaptive Modellretention weiterhin fünf Minuten.
Ein Fehler beim Lesen oder Schreiben der Datei führt ebenfalls nicht zu
ungeprüftem Cleanup oder einem Signal ohne Beleg.

## Bestehende Grenzen

Die expliziten Resume-Aufrufe nach einem Fehler einer bereits gestarteten
Telegram-Anfrage und im Finally-Pfad eines bereits gestarteten CLI-Laufs
bleiben bestehen. Sie unterliegen jetzt dem Besitz- und
Identitätsnachweis, verwenden aber weiterhin ihren bisherigen expliziten
Aufrufvertrag; sie werden nicht in den automatischen Idle-Monitor umgebaut.

SIGSTOP hält die Prozessausführung an und gibt für sich genommen keinen RAM
frei. Eine leere Ollama-Liste ist außerdem keine Reservierung des gesamten
Host-RAMs gegenüber anderen Anwendungen. Diese Änderung aktiviert keinen
universellen RAM-Broker und verändert weder Compute-Queues noch deren
Checkpointverfahren.

## Verifikation

`system/tests/test_compute_resume_safety.py` verwendet künstliche Prozessobjekte,
synthetische Erstellungsidentitäten, eine simulierte Uhr und HTTP-Antworten.
Abgedeckt werden unter anderem Transport-/Schemafehler, zurückgesetzte
Idlefenster, Timeout, Startup-Recovery, Legacy-Reste, PID-Wiederverwendung,
Schreibfehler, Teilfreigaben und verspätete Monitore.

Die bestehenden Caller-Verträge werden zusätzlich durch
`system/tests/test_model_socket_callers.py` geprüft. Die Tests benötigen keine
realen Signale, Modellstarts, Modell-Unloads oder produktiven Pausebelege.
