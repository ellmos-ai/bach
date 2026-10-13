# Letzter erfolgreicher Lauf der Dokumentationswartung

BACH liest den Schedulerstatus über BachSchedulerAdapter.jobs(). Die Fassade
liefert last_run und last_result für den jüngsten Versuch getrennt von
last_success, dem Abschlusszeitpunkt des zuletzt erfolgreich beendeten Runs.
Ein späterer Fehlerlauf löscht einen früheren Erfolg nicht; ohne erfolgreichen
Run bleibt last_success null.

MaintenanceRuntime.job_receipts() projiziert für bach.docs.* die bestehenden
Statusfelder id, enabled, next_due_at und last_success aus dieser Fassade.
Die BACH-Schicht leitet den Erfolg nicht aus dem jüngsten Lauf und nicht aus
einer zweiten Scheduler-Store-Abfrage ab. Fehlt die Fassade oder ihr
last_success-Feld, wird der Status fail-closed als nicht verfügbar behandelt.

Die BACH-Abhängigkeit ist auf den unveränderlichen Scheduler-Merge-Commit
f2740ba7e9d9ebe6d425b68b203b5ae263ce3edc gepinnt. Dieser Commit enthält die
separate Success-Projektion; BACH übernimmt sie über die vorhandene Adapter-API.
Der Source-Pin ändert weder die produktive Installation noch den Dienststart.
Eine spätere Installation und ein nativer Readback bleiben eigene Integrations-
und Betriebsschritte.
