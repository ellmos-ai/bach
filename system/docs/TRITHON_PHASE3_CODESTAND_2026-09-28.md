# Trithon Phase 3 — Code-Stand (Task #1470)

Datum: 2026-09-28
Geprüfte Dateien:

| Datei | Zeilen | Befund |
|---|---|---|
| `hub/_services/trithon_dispatch.py` | 315 | `begin_assignment`/`finish_assignment` werden **mit** `path=str(ticket.ledger_path)` aufgerufen; `dispatch_to_ticket_master` ruft **nur** `record_receipt(path, ticket_id, receipt)` auf |
| `hub/_services/agents_heart.py` | 206 | Signaturen keyword-only inkl. `path`-Parameter: `begin_assignment(*, role_id, mode, agent_instance_id, backend_id, model_id, slot_id, task_id, session_id, initiated_by, path=...)`; `Assignment`-Dataclass; `authorize_role` fail-closed (Rollen: hintergrund_worker, task_worker, boss_routing, expert_role; Rechte `task.claim`+`task.execute`); `AssignmentDenied` |
| `hub/_services/trithon/routing_contract.py` | 314 | `ExecutionReceipt` (Z.81), `record_receipt` (Z.234), `create_pending_contract` (Z.291), `claim_contract` (Z.158), `read_ledger`, `_validate_receipt` (Z.224); Exceptions: `RoutingError`, `ContractAlreadyClaimed`, `ContractNotFound`, `InvalidReceipt` |
| `hub/task_audit.py` | 358 | `claim_task_atomic(conn, task_id, claimed_by, lease_seconds)` (Z.260), `release_claim` (Z.321), `apply_task_field_changes` (Z.147), `GateReopenBlocked` |

## Ergebnis

Die aus der Vorlaufarbeit geplanten Phase-3-Änderungen sind **bereits vollständig im Code** vorhanden:

- `path=...` wird in `begin_assignment` und `finish_assignment` durchgereicht.
- `dispatch_to_ticket_master` ruft ausschließlich `record_receipt(...)` auf (keine weiteren Seiteneffekte).

**Keine Code-Änderung erforderlich.** Nächster Schritt: Testabdeckung (#1471 Fixture → #1472 E2E-Tests → #1473 pytest → #1474 Commit).
