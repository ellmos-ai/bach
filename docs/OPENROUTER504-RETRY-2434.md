# OpenRouter HTTP 504 — Task #2434

Ein normalisierter OpenRouter-HTTPStatusError 504 beendete den Worker, weil bisher nur HTTP 429 und Transportfehler für die Modellaufruf-Wiederholung zugelassen waren.

HTTP 504 wird jetzt im vorhandenen sicheren Modellaufruf-Pfad erneut versucht: drei Wiederholungen mit 5, 10 und 20 Sekunden Pause, höchstens 900 Sekunden Gesamtwartezeit pro Aufruf. Ein gültiger Retry-After-Wert wird berücksichtigt. Die bestehenden Grenzen für partielle Ausgabe, Werkzeugausführung, Abbruch und Call-Identität bleiben erhalten.

Nach ausgeschöpften Modellaufruf-Versuchen dürfen continuous/persistent-Cloudworker den vorhandenen Rückgabe-/Wartepfad nutzen. Vor jeder Wartephase müssen der Lease-Supervisor beendet und die native Lease-Rückgabe bestätigt sein. Danach mindestens 60 Sekunden Pause, exponentiell bis 900 Sekunden zwischen Versuchen, oder länger laut Retry-After. Anschließend reguläre neue Aufgabenübernahme. Stop, TTL und Generation bleiben wirksam; Profile ohne feste Aufgabe bleiben ungebunden.

Der zusätzliche HTTP-Status gilt nur für OpenRouter 504. Andere HTTP-Fehler und lokale Ressourcenregeln werden nicht erweitert. Der bestehende 429-Pfad bleibt erhalten. Der Verlauf nennt einen 504-Abbruch temporary_gateway_timeout.

Statische Quellenprüfung: Python-AST und git diff --check. Keine Tests hinzugefügt oder manuell ausgeführt. Exakte unabhängige Review, Veröffentlichung, Mac-Aktivierung und gewöhnliche Laufzeitbeobachtung werden separat belegt. Basis ist der aktive Overlay-Stand 14440a23 einschließlich der bisherigen Worker-/Guardfixes.
