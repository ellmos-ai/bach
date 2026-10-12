# Providerneutrale Doku-Wartungsaufgaben

Der Owner erzeugt künftige automatisierte Analyseaufgaben weiterhin als WORKER
mit dem nativen Auftraggeber bach. Der aktive Owner kann über den vorhandenen
SchedulerHandler und denselben maintenance_cli.handle-Pfad mit der Aktion
provider-neutral gebeten werden, die zukünftige Slot- und Modellbindung zu
entfernen. Die Aktion ist ein Konfigurationsupdate, kein Task-Update: offene,
Review- oder fremde Aufgaben werden weder verschoben noch umgeschrieben. Der
Dispatcher verwendet die neue Bindung erst für danach neu angelegte Aufgaben.
Die vorhandene GET-Status-API bleibt read-only.

## Owner-CAS

Der CLI-Handler schreibt eine private Request-Datei in die kanonische lokale
Runtime unter ~/.bach/maintenance/. Die Datei bindet exakt die laufende
Owner-Generation, den SHA-256 der aktuellen Konfiguration, den vorherigen
worker_binding-Wert, die ausschließlich leere Zielbindung und eine Nonce.
Der aktive MaintenanceRuntime.serve()-Owner verarbeitet sie nur innerhalb
seiner bestehenden OS-Owner-Sperre und nach erfolgreicher CanonicalLockGuard-
Prüfung. Er prüft Konfigurationshash und alten Bindungswert per CAS, ersetzt nur
worker_binding durch {}, liest die physischen Zielbytes zurück, aktualisiert
self.config und den vorhandenen Dispatcher gemeinsam und schreibt erst danach
einen privaten ACK. Request und ACK werden atomar mit Modus 0600 gespeichert.

Die CLI meldet Erfolg nur, wenn Nonce, Generation und Request-Hash im ACK passen
und die zurückgelesene Konfiguration exakt dessen Zielhash und leere Bindung
enthält. Bei Timeout bleibt dieselbe Request-Datei erhalten; ein erneuter Aufruf
liest denselben Request und erzeugt keine neue Nonce. Ein Timeout bedeutet
unknown, nicht Erfolg oder Fehlschlag. Ein veralteter Owner, Konfigurations-
konflikt, unlesbarer ACK oder fehlende Lock-/Pfadprüfung bleibt geschlossen.
Plattformen ohne nachweisbare POSIX-Dateirechte erhalten unavailable; daraus
wird keine ACL- oder Datenschutzgarantie abgeleitet.

## Grenzen

Die Änderung betrifft ausschließlich zukünftige Doku-Aufgaben und nur die beiden
optionalen Bindungsfelder. Kategorie, Auftraggeber, Rechte, Werkzeuge, Prompt,
Legacyaufgaben und Status bleiben außerhalb dieses CAS. Providerneutralität
hebt keine weiteren Pickup-Filter auf: Kategorie-, Ownership- oder andere
Queueausschlüsse können weiterhin verhindern, dass ein Worker passende Arbeit
findet. Eine Vorschau oder Konfigurationsquittung ist kein Beleg für eine
Taskübernahme oder fachliche Dokuprüfung. Es werden weder Workers gestartet noch
Konfigurationen automatisch angewendet.
