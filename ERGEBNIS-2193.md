# Task 2193 – Lesende Quellenanalyse: Ergebnisautor, Worker-ID, Laufgeneration, Lease/Fence

Nur gelesen im eigenen Worktree task-2193; Live-Pfade gesperrt. Keine Implementation, keine erfundenen Anker.

## B1 Ergebnisautor (submitted_by)
Anker: `system/hub/_services/task_result_service.py:575-579` (INSERT) und `:698-715` (`prepare_submission_receipt`).
Die Prüfung vergleicht den task_history-Übergang exakt als `("in_progress","review",record["submitted_by"])`; das Receipt führt result_id, task_id, fence, generation, task_version, result_sha256, submitted_by, submitted_at, submitted_status_event_id. Der Autor geht als `worker`-Parameter ins INSERT (`submitted_by=worker`) und wird nicht aus einer verifizierten Lease abgeleitet – er ist Aufruferangabe.
Negative Prüfsituation (#2192): Ein Receipt mit korrektem Statuswechsel, aber fremdem `worker`-Parameter passiert die Prüfung. Der Vertrag braucht den Fehlerfall „Receipt.submitted_by ≠ Schreiber des INSERT“; er fehlt heute.

## B2 Worker-ID / Producer-Binding
Anker: `task_result_service.py:586-599`. Binding nur bei `claimed_by==worker` UND `claim_id` UND `claim_generation==generation` UND `claim_fence>0` UND `claim_task_version==version`; sonst bleibt sie offen, ohne Ablehnung.
Negative Prüfsituation: Ein Ergebnis ohne Bindung wird widerspruchsfrei akzeptiert – es gibt keinen Fehlerpfad. #2192 muss „fehlende Bindung“ als eigenen prüfbaren Zustand führen.

## B3 Laufgeneration vs. Lease/Fence
Anker: `system/hub/_services/chat/worker_lease_binding.py:160-221`: `acquire(..., worker_id, host, generation, is_current)` prüft Generation/worker_id beim Review-Grant (182-183) und bei Creator-Delegation (216-218); `generation` ist eine von worker_id und fence getrennte Größe. Im INSERT kommt `fence` aus `row["claim_fence"]`, `generation` aus dem Parameter. Receipt-Schema `bach.worker-submission-receipt.v1` (`:24-25`).
Negative Prüfsituation: Für `generation` und `fence` fehlt eine gemeinsame Prüfinstanz; eine veraltete generation bei gültiger fence bleibt unbemerkt. `system/gui/device_auth.py:1-30` belegt nur Geräte-/Sessionidentität (SHA-256-Hashes, Keyring), keine Worker-Autorenidentität.

## Abgabe-Status
`task_manage(submit_result, 2193)` wurde mit „Taskoperation nicht bestätigt; Taskbindung prüfen“ abgelehnt: Task 2193 ist `pending`, `claimed_by=None`, `claim_issued_at=None`, `claim_fence=35`. Es fehlt die vom Controller erworbene Lease; ich erzeuge sie nicht selbst.
