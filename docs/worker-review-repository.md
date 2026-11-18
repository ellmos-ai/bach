# Native review repository inheritance

A native result review needs the same verified repository authority as its parent result. Creating a pending review task alone does not establish that authority. The native review controller now enrolls the child after the review intent has committed, and retries enrollment when an existing pending child is encountered during backfill.

## Authority and publication

`enroll_review_task_repository` accepts a review task ID, its content version and the expected registry SHA-256. It accepts no caller-selected repository, origin or source revision. It re-reads the private native review intent, its current parent result, scope and independent review policy. The parent binding is read from the canonical local registry.

The child's binding inherits the parent's exact immutable public source revision. Native source-owner verification checks the physical clone, canonical public origin and ref proof; this does not replace the parent revision with a newer main branch or download another clone. Missing parent bindings, unverifiable private provenance, held source fences, conflicting existing child bindings or stale versions fail closed.

Final publication holds the existing `.operator-lock` used by explicit repository enrollment and source maintenance. Decomposed child inheritance now uses that same fence and a byte-preimage compare-and-swap. It preserves existing child bindings. An atomic registry replacement cannot silently overwrite a cooperative writer's update.

Git/source checks occur outside the SQLite write transaction. Immediately before registry publication, the operation reserves the canonical SQLite writer, rechecks the child intent, task version, pending/unclaimed state and parent/result/policy pins, then publishes only if the registry preimage and owned fence still match. The database writer is released without task changes. No review grant, lease, result acceptance or source provisioning is performed.

## Failures and retries

A review remains pending when enrollment is unavailable. The native creation/backfill result exposes `repository_binding.state = unavailable` and a closed `reason_code`; the controller also logs that code with the review task ID. It does not log raw exceptions, private paths or source data. Existing pending children are checked again on subsequent backfill, allowing an operator to repair missing source or registry evidence without generating another review task.

Success exposes `enrolled` or `already_bound`. Existing matching bindings are idempotent. Borrowed in-memory connections and noncanonical clients cannot publish to the live registry.

## Verification

`system/tests/test_worker_review_repository.py` uses actual native review intents and result evidence copied into a private test HOME. Coverage includes successful inheritance without task/grant changes, idempotency, missing parent bindings, damaged intent, changed parent result, occupied child, conflicting registry mapping, stale registry SHA, shared fence contention with decomposition, source verification failure, a parent mutation during verification, and visible native-controller failure. Physical source validation is isolated behind the native source-owner seam; existing source-owner tests remain responsible for Git/public-origin verification.

## Decomposition contention and restart recovery

The common writer checks the native lock state of the registry directory before creating its cooperative marker and again after obtaining it. The expected registry digest is mandatory at the review enrollment API; only the shared internal writer permits an omitted expected digest for an already verified native decomposition.

A successful native `lease_decompose` event now records each confirmed child's content version and a SHA-256 of the normalized operation in the existing `task_history` row, in the same transaction as child creation and the parent update. The digest includes the subtask fields, parent-close choice and sequential setting; it does not store request text or lease secrets. The binding does not silently discard a failed registry inheritance. Its tool result reports that children already exist and repository bindings are still unconfirmed, including a closed reason code. Retry follows resolution of the reported blocker.

Every new `add` consults the canonical native decomposition history, independently of description markers. Older BACH writers used the same text marker without a native `lease_decompose` event; a confirmed absence of that event does not create a recovery obligation. An existing malformed event remains unavailable. Removing a text marker does not hide an actual incomplete native operation.

Before interpreting a call as recovery, the worker reads the actual child bindings identified by the native event. If every binding already matches the trusted parent's repository and source revision, that operation is complete. Later description edits on the parent or child do not revoke an existing repository binding. A new `add` therefore proceeds as its own native operation, including after a worker restart. A different `decompose` retains the existing already-decomposed guard; it is not reported as a successful replay of the old request.

For an incomplete operation, only a request whose digest matches the native event can repair those confirmed children. An unrelated `add`, including the same title with different instructions, returns `repository_inheritance_pending` and neither creates tasks nor repairs a different operation. The matching retry never creates the children again. After a process restart, a fresh worker can reconstruct that same event under its new valid parent lease. Before publishing any missing binding, the registry owner verifies the current parent lease/fence and exact parent content version, the unchanged native event and every child's recorded content version. These checks and publication hold the canonical SQLite writer together with the shared registry fence. Changed child versions, an obsolete parent lease, a changed event, active/unavailable locks or conflicting existing child bindings remain blocked. A completed repair reports the verified bindings and explicitly says no new children were created.

Legacy v1 and enrolled v2 repository registries both work. Child versions come directly from canonical task rows and the native event, so a missing child policy projection is not substituted with guessed authority. Existing child bindings are preserved and must match the parent's repository and source pin.

### Historical events without child-version pins or an operation digest

An older native event may lack `child_task_versions` or `request_sha256`. If a child still lacks a verified registry binding, missing child pins block publication with `decomposition_receipt_legacy`; a missing operation digest prevents automatic request matching and returns `repository_inheritance_pending`. Neither case claims success after losing an in-memory ACK. The existing explicit lead-operator path remains available:

1. Read the canonical parent's native `task_history` event with action `lease_decompose` and its confirmed child IDs. Do not obtain these IDs from task description markers.
2. Verify the intended mapping against the parent's trusted registry binding, refresh the child's native content version and verify the public source using the existing source owner.
3. Call the existing `enroll_task_repository(client, child_id, repository=..., task_version=..., source_sha=..., expected_registry_sha256=..., operator="operator:<identity>")` on the canonical local lead. Re-read the registry digest for each operation. That API retains its public/current-source verification and mutates no task or lease.
4. Read back every child's trusted registry binding. When all match the parent, a later native `add` recognizes completion and can proceed even if the historical event lacks both pins and a request digest. A decomposition retry matching the recorded request digest can also confirm completion. Without a request digest, a repeated `decompose` keeps the already-decomposed guard instead of guessing that the supplied request was the historical operation.

The historical-event regression tests execute this existing operator route and confirm the subsequent native readback and new follow-up creation. Further tests cover v1/v2 registries, exact retries without duplicate children/events, different requests with the same title, ordinary parent/child edits after completion, restart with a fresh lease, changed child versions during incomplete recovery, changed parent fences and a rival SQLite writer blocked at registry publication.
