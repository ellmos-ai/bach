# TaskDB: versionierte Lease-Aktionen für Running

Ergänzung zu `TASKDB-SALT-LEASE-VERTRAG-v1.md`, Task #1727.
Implementierung und isolierte Prüfungen; Integration und Laufzeitabnahme stehen aus.

## Auftragsversion

`task_version` ist ein SHA-256-Fingerprint des momentanen Auftragsinhalts.
Lease-/Heartbeatfelder, Status und Laufzeitstempel beeinflussen ihn nicht.
NULL-Felder werden ausgelassen, damit additive optionale Spalten eine bestehende
Bindung nicht verändern. Titel, Beschreibung, Abhängigkeiten, Priorität,
Zuordnung, Modell-/Slotvorgaben und weitere Inhaltsfelder sind gebunden.

Task-Liste und Taskdetail liefern den Fingerprint. Sie liefern weder `claim_id`
noch `claim_request_id` oder den internen `claim_task_version`.

Acquire kann die gelesene `task_version` als Vorbedingung erhalten. Bei Erfolg
speichert es die Inhaltsbindung in `claim_task_version` und liefert sie im ACK.
Ein Heartbeat ändert diese Bindung nicht. Renew und Release prüfen auch bei
älteren Requests ohne Versionsfeld die gespeicherte Bindung gegen den aktuellen
Inhalt. Eine Abweichung liefert `409 stale_task_version`.

Neue Worker lesen den Auftrag, senden dessen Version bei Acquire und führen
jede Änderung mit Lease-ID, Fence und dieser Version aus. Bei Ablehnung stoppen
sie die Bearbeitung; ein fehlgeschlagener Renew begründet keine neue Bindung.
Bestehende Leases ohne Inhaltsbindung müssen ablaufen. Danach kann ein neues
Acquire den aktuellen Auftragsinhalt binden.

## Zerlegung

`POST /api/tasks/{id}/lease/decompose` verlangt Geräteauth sowie:

```json
{
  "lease_id": "UUID",
  "fence": 1,
  "task_version": "64 hexadezimale Zeichen",
  "subtasks": [{"title": "Erster Schritt", "description": "Konkrete Fortsetzung"}],
  "close_parent": true,
  "sequential": false
}
```

Fence und Flags sind strikt typisiert; unbekannte Requestfelder werden abgelehnt.
Die Liste enthält 1–100 Teilaufgaben. Teilaufgaben unterstützen Titel,
Beschreibung, Priorität, Kategorie, Zuordnung, Abhängigkeiten sowie Modell- und
Slotvorgaben. Vorhandene Modell-/Slotvorgaben werden standardmäßig vererbt.

Unter derselben `BEGIN IMMEDIATE`-Transaktion werden Lease, Fence, Ablauf und
Inhaltsversion geprüft, alle Teilaufgaben angelegt, die Elternbeschreibung
ergänzt und bei `close_parent=true` der Eltern-Task abgeschlossen. Dann werden
seine Capability-Felder geleert; der Fence bleibt erhalten. Bei offenem Eltern-Task
wird die Versionsbindung auf die eigene bestätigte Beschreibung aktualisiert.

Das ACK enthält `decomposed`, `task_id`, `created_ids`, `created_count`,
`parent_closed`, `fence`, `task_version` und `server_now`. Es wird erst nach
erfolgreichem Commit ausgegeben. Fehler beim Anlegen, Abschluss oder Commit
rollen das gesamte Paket zurück. Ein paralleler oder wiederholter Request mit
alter Version kann keine zweite Teilaufgabengruppe anlegen.

Eine Rollenbesetzung oder Taskzuordnung in einer Teilaufgabe ist noch kein
delegierter Providerlauf. Der native Running-Client muss den bestätigten
Auftrag und dessen Version mit seinem tatsächlich gestarteten Worker verbinden.
