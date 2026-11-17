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
