# Lokale Inferenz: FIFO und faire Zulassung

## Geltungsbereich

`HostInferenceGate` koordiniert lokale Modellaufrufe auf einem Host. Der bestehende Betriebssystem-Lock `inference` bleibt der einzige Owner-Lock. Der kurze Queue-Lock serialisiert nur Ticket- und Fairnessmetadaten; er startet keine Inferenz und ersetzt weder Ressourcenprüfung noch Modellbindung.

Jeder lokale Aufruf registriert ein prozessgebundenes Ticket, bevor er um den Owner-Lock wartet. Die aktive Ticketfolge wird unter dem Queue-Lock geordnet. Tickets tragen PID und Prozessstartzeit, Priorität, Sequenznummer und einen SHA-256-Fingerabdruck des bereits geprüften Modellziels. Rohes Ziel, Chatinhalt, Prompts, Tokens und Ergebnisse stehen nicht im Ticket. Das Ziel wird während des Wartens weiterhin durch die vorhandenen Binding- und Ressourcenprüfungen revalidiert.

Ältere Prozesse verwenden weiterhin `foreground-*.json` als Vordergrundsignal. Neue Vordergrundtickets schreiben denselben Signalmarker, damit ein noch laufender älterer Hintergrundprozess nicht an ihnen vorbeiläuft. Unbekannte oder beschädigte Queuebelege werden fail-closed behandelt. Beendete Prozesse und wiederverwendete PIDs werden anhand der Prozessstartzeit erkannt; ihre Tickets werden entfernt.

## Reihenfolge

Tickets sind innerhalb jeder Priorität FIFO. Vordergrundtickets dürfen Hintergrundtickets überholen, solange die Grenze nicht erreicht ist. Wenn mindestens ein Hintergrundticket wartet, werden höchstens drei Vordergrundzulassungen hintereinander vergeben. Danach wird das älteste wartende Hintergrundticket zugelassen; der Zähler beginnt bei null. Sind keine Hintergrundtickets vorhanden, wird der Zähler zurückgesetzt. Damit wird kein später eintreffender Hintergrundaufruf für bereits abgeschlossene Vordergrundarbeit benachteiligt.

Gezählt werden Zulassungen, nicht Laufzeit. Ein bereits zugelassener Modellaufruf wird weder präemptiert noch wiederholt. Die faire Zulassung verspricht daher keine maximale Wartezeit in Sekunden.

## Verbindung zur Runtime

Die Runtime prüft die Modellbindung und die konfigurierte lokale Ressourcenreserve vor dem Ticket und erneut an der bestehenden sicheren Modellaufrufgrenze. Ein Ticket ist keine Reserve und reserviert weder RAM noch KV-Cache. Wenn Binding oder Reserve nach dem Warten nicht mehr gültig sind, wird die Runtime-Anfrage vor dem Modellaufruf abgewiesen und das Ticket entfernt.

Cloud- und externe Modellziele nehmen nicht an dieser lokalen Queue teil. Sie behalten ihren bestehenden separaten Ausführungspfad.

## Grenzen

Die Gate-Änderung erhält zunächst den globalen Einzelowner für lokale Inferenz. Sie führt weder Mehrmodell-Parallelität noch gemeinsame KV-/RAM-Buchung oder eine proportionale „Fackel“-Ressourcenverteilung ein. Modell-, Speicher- und Hostbudgets bleiben eigene, noch offene Admissionfragen. Dieser Sourcevertrag belegt keine native Installation, Live-Ausführung oder vollständige Ressourcenabnahme.
