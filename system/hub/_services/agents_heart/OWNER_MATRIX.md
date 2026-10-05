# Eigentümermatrix – agents_heart v1

> **Modul:** `system/hub/_services/agents_heart/agents_heart.py`
> **Ticket:** T-20261003-793817309
> **Status:** pending (kein Runtime-Nachweis)

---

## 1. Verantwortlichkeiten pro Artefakt / Funktion

| Artefakt / Funktion            | Verantwortlich                | Bemerkung |
|--------------------------------|-------------------------------|-----------|
| `RoleContract` (Schema)        | **agents-heart-team**         | v1 frozen; Änderung = MAJOR |
| `ROLE_CONTRACTS` (4 Rollen)    | **agents-heart-team**         | Erweiterung = MINOR; Entfernung = MAJOR |
| `authorize_role()`             | **agents-heart-team**         | Fail-closed-Logik; Security-Critical |
| `Assignment` (Datensatz)       | **agents-heart-team**         | Felder ergänzt = PATCH |
| `begin_assignment()`           | **agents-heart-team**         | Signature Änderung = MAJOR |
| `finish_assignment()`          | **agents-heart-team**         | Signature Änderung = MAJOR |
| `AssignmentEventSink` (Prot.)  | **agents-heart-team**         | Neue Methoden = MAJOR; neue Optionals = MINOR |
| `_BachActivitySink`            | **agents-heart-team**         | BACH-Adapter; nur interne Anpassung |
| `AssignmentDenied`             | **agents-heart-team**         | Keine Änderung ohne Teamfreigabe |
| `Task-ID / Lease`             | **ticket-master**             | ticket-master übergibt task_id an begin_assignment() |
| `Prozess-Spawn`              | **agent-launcher**            | agent-launcher ruft begin/finish auf |
| `LLM-Backend-Auswahl`        | **Backend-Modul**            | backend_id + model_id werden an begin_assignment() übergeben |
| `Compute-Zuordnung`          | **Fackel**                    | Fackel legt agent_instance_id fest |
| `GUI-Rendering`             | **Clients**                  | Clients lesen /api/activity (BACH-Sink) |
| `Event-Recording`            | **AssignmentEventSink-Konsument** | Wer den Sink injiziert, ist Konsument |
| `Trithon-Transport`        | **trithon-team (optional)**   | Phase 3; LedgerEntry-Sink implementieren |
| `MANIFEST.yaml`            | **agents-heart-team**         | Mit jedem Release aktualisieren |
| `OWNER_MATRIX.md`         | **agents-heart-team**         | Bei Team-Änderung aktualisieren |
| `TRITHON_RECONCILIATION.md` | **agents-heart-team**    | Bei Trithon-Schema-Änderung aktualisieren |

---

## 2. Änderungsprotokoll (Changelog)

| Datum        | Version | Änderung | Verantwortlich |
|--------------|---------|----------|----------------|
| 2026-10-03   | v1.0    | Erstes produktneutrales Modul: Protocol + injizierbarer Sink + 4 Rollen | agents-heart-team |

---

## 3. Zuständigkeitsgrenzen

- **agents-heart-team** besitzt `agents_heart.py`, `MANIFEST.yaml`, `OWNER_MATRIX.md`, `TRITHON_RECONCILIATION.md`.
- **Anderen Teams** ist die Änderung von `agents_heart.py` untersagt ohne CR (Change Request) an agents-heart-team.
- BACH-spezifischer Code (slots_config, record_activity) bleibt im **BACH-Core-Team**.
- Trithon-Transport-Konformität wird durch `TRITHON_RECONCILIATION.md` überwacht.

---

## 4. Test-Verantwortung

| Test-Datei                         | Besitzt |
|------------------------------------|---------|
| `system/tests/test_agents_heart.py` | agents-heart-team |
| Trithon-Sink-Test (zukünftig)       | trithon-team (PR nach agents-heart-team) |
