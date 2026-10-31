# Cloud-Queue: offene Rückgabe und Rundenreserve

Task #2431 · Nutzerauftrag vom 22.10.2026

## Verhalten

- Ein ohne Task-ID gestartetes Profil bleibt ohne feste Task-ID. Die aktive Aufgabe stammt aus der aktuellen Ausführungsbindung.
- Ein Backendfehler gibt unerledigte Arbeit regulär als offene Aufgabe zurück. Frühere Toolaufrufe erzeugen keine zusätzliche Prüfaufgabe.
- Vor Rückgabe endet der Lease-Supervisor; die native Rückgabe muss bestätigt sein. Fremde aktive Leases werden nicht verändert.
- Ergebnisannahme läuft getrennt von der Auswahl der nächsten Aufgabe.
- Ollama Cloud und OpenRouter warten bei HTTP 429 ohne Task-Lease und versuchen danach eine neue reguläre Übernahme. Nach drei Versuchen wird der Queueworker nicht mehr dauerhaft beendet. Retry-After, Nutzerstopp und Profilablauf gelten weiterhin.
- Cloudworker erhalten bis zum Vierfachen ihres eingestellten Rundenwertes, höchstens 1000, ohne einen höheren ausdrücklich eingestellten Wert zu senken. Der Agent sieht den wirksamen Wert. Ein separates Modellanfragenbudget wird nicht erhöht.
- Lokale Modelle behalten den eingestellten Rundenwert und die bestehenden RAM-/Reservegrenzen.

## Grenzen und Auslieferung

Vorhandene Arbeit bleibt erhalten und ist beim regulären Wiederaufnehmen zu berücksichtigen. Eine offene Rückgabe ist kein erledigtes Ergebnis. Anbieterquoten werden nicht umgangen; es gibt keinen zusätzlichen kostenpflichtigen Modellfallback.

Implementierung, unabhängiger Quellreview, Commit/Push, Mac-Deployment und Runtime-Abnahme sind getrennte Schritte. Dieser Text allein belegt keinen dieser Schritte. Es wurden keine Tests hinzugefügt oder manuell ausgeführt.
