# email_bridge Module

Standalone module for draft-first safe email dispatching, address validation, and outbox auditing.

## Guarantees
- **Draft-First Invariant:** Every outbound email is stored in state `draft`. Outbound network dispatching NEVER occurs automatically; it requires an explicit `confirm_send(draft_id)` call.
- **Audit & Cancel:** Unsent drafts can be reviewed, listed, or cancelled at any time without side-effects.
