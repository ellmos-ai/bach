# Früher Vordergrundbedarf an der lokalen Inferenzgrenze

Task 1949, Quellstand auf BACH main 015550b351c953f8944a1b54deeb71218784889f.

Eine direkte lokale Nutzeranfrage wird nach Bestätigung des lokalen Modellziels und vor ihrer RAM-Prüfung in der bestehenden HostInferenceGate-Queue angekündigt. Das ist Bedarf, kein Compute-Besitz: owner.json und inference.lock werden erst nach erfolgreicher Zulassung verwendet. Der bestehende Status foreground_waiters zählt auch solche RAM-wartenden Nutzer.

Die Queue behält ihre bisherigen Tickets, PID-/Erstellzeitprüfung, Zielhashes, FIFO-Auswahl und begrenzte Vordergrundserie. Ein zugehöriger lokaler Zulassungsbeleg unterscheidet noch wartende von bereiten Tickets. Ein RAM-wartender Nutzer blockiert keinen anderen bereiten Nutzer. Hintergrundanfragen werden weiterhin erst nach der RAM-Prüfung eingereiht; die vorhandene Fairness bleibt wirksam. Ungültige Belege sperren die Koordination.

request(...) kündigt Bedarf an und liefert einen einmal verwendbaren Owner-Kontext. Erst dessen Aufruf bindet das dann bestätigte Modellziel und markiert dasselbe Ticket unter dem Queue-Lock als bereit. turn(...) bleibt der kompatible kombinierte Zugang. Ältere Tickets ohne Zulassungsbeleg gelten weiterhin als bereits bereit; neue und alte Ticketfelder bleiben gleich. Für eine vollständige Abnahme der neuen Auswahlsemantik müssen die beteiligten Runtimeprozesse den aktualisierten Code verwenden.

Der vorhandene Ressourcenprüfer bestätigt zuerst das lokale Ziel einschließlich Digest, Budget und Kontext. Ein auf diesen Prüfaufruf begrenzter asynchroner Beobachter kündigt dann den Vordergrundbedarf an, noch bevor RAM und Disk gemessen werden. Nach Ende des Aufrufs ist der Beobachter auch für geerbte Kindkontexte inaktiv. Seine Fehler, etwa bei Leaseverlust, werden nicht in wiederholbare RAM-Fehler umgedeutet. Bestätigte Cloudziele und externe Aliase erzeugen dabei weder Ticket noch lokales Gate-Verzeichnis.

Die Runtime prüft RAM/Disk, Ressourcenpolicy, eigene Tasklease und Modellbindung weiter vor und unter dem Owner. Ein vor der Metadatenprüfung noch unbekanntes Ziel wird nicht vorzeitig als lokale Modellbindung erzwungen. Wird ein wartendes Ziel später extern, verlässt es die Bedarfsklammer vor dem Cloudaufruf. Bei später entfallender Zulassung wird Bedarf neu angekündigt und dieselbe bisherige Wartefrist fortgeführt. Kein Werkzeugschritt und kein Modellaufruf wird dadurch wiederholt.

Abbruch, Fehler und Fristablauf entfernen nur den eigenen Bedarf. Warten erzeugt keine Besitzerdatei und verbraucht keine neue Modellanfrage. Es gibt keine zweite Executorqueue und keine Änderung von RAM-Budgets, Modellgröße, Kontext, Taskabschluss oder Workerfreigaben.

Diese Änderung ersetzt weder Task 2419 (Watchdog-Maintenance an derselben Inferenzsperre) noch die vollständige Compute-Checkpoint-/RAM-Freigabe aus 2334. Die produktive Übergabe und Geräteabnahme bleiben getrennte offene Anforderungen. Kein Modell- oder Workerstart, Unload, Dienstneustart oder Deployment wird durch diese Quelländerung ausgeführt.
