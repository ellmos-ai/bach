# Task binding scope for external workers

`task_manage` is generation-bound to one canonical Task Lease. Its `list` action
returns only the already-bound task summary. `detail` accepts only that task's
integer ID and returns the same bound snapshot; it does not fetch an arbitrary ID.
Foreign IDs and extra list/detail fields receive a generic protocol error without
including the requested ID or task content. `submit_result`, lease renewal, and
separate operator review continue to use the existing binding and receipt path.

External profile assignment is accepted for the explicit provider aliases
`OPENROUTER` and `OLLAMA-CLOUD` only when the running profile has that exact
backend and the task carries the exact same `assigned_slot` and
`required_model`. The owner alias is compared after the same whitespace-trimmed,
case-insensitive canonicalization used by the CLI and picker. A provider name
does not become a general owner or role. GUI assignment still requires a current, authenticated, runtime-verified
profile; the picker retains model, slot, pickup-tag, dependency, creator-priority,
and lease checks.

For these cloud profiles, `assigned_slot` identifies the configured worker
profile route. It is not a physical local model slot, and this binding change does
not start a model, alter provider availability, or grant broader task access.
