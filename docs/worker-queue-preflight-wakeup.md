# Worker queue preflight and change hints

## Behavior

A fresh unbound Buddha Always-On generation reads the canonical task queue before requesting optional model warmup. It scans ordinary candidate pages with the same effective per-task selection policy and repository selector used by native acquisition. It honors version deferrals, current lease state, task status, dependencies, unresolved tool traces and the local creator priority window. A review-only queue can match through a grant-free read of the same private review eligibility logic used by actual review grants.

An empty, excluded, incomplete or unverifiable queue does not request model warmup. The worker exposes a queue-preflight waiting activity and checks again. A positive preflight is prospective eligibility: atomic Acquire, source/worktree preparation, current slot/profile, model resource admission and every dispatch guard still run. No grant, lease, result acceptance or tool request is produced by preflight.

Fixed task pins and resumed task runs keep the existing native Acquire/recovery route. They do not wait behind optional queue warmup. Only the established native recovery and denial handlers may release a fixed pin; a read hint cannot do so. Completion polling and review backfill run before preflight, so a cold empty queue cannot itself suppress creation of review jobs. Host-precondition waits remain ahead of acquisition. Expired preparation-only deferrals are released only after a complete exhausted scan; ordinary returned-version deferrals remain binding.

## Cross-process hints and fallback

The observer resolves its database through the existing native TaskLeaseClient authority. A remote authority is never replaced with a local projection. On a local file authority it keeps one `mode=ro`, query-only SQLite connection and compares `PRAGMA data_version` only on that same connection. The observer holds no transaction across reads, scans or waiting. Short per-task readiness reads use a separate read-only transaction to satisfy the native tool-trace consistency check and release it immediately.

SQLite changes from every canonical writer are covered without installing partial publishers into task creation paths: task creation, update, lease return, dependency completion and persisted policy changes all commit through other connections. The indication is deliberately a **change hint**, not a semantic TaskCreated event. Unrelated database commits can also cause a fresh cheap check. Registry file identity/size/modification changes are included.

The observer captures its revision **before** independent preflight/acquisition. A commit during that scan is therefore still visible when the worker starts waiting. Changes to database path/authority or file identity invalidate the old connection and get a new epoch. Read failures close the connection; successful later reads reconnect. Worker cleanup closes the observer.

Idle probes run every **0.5 seconds**. Changes are coalesced to at most one early recheck every **2 seconds**. The independent **10-second periodic fallback** remains active when no hint arrives, on remote authorities and after observation failures. Stop interrupts waiting. Existing resource/model/host cooldowns and work-window checks remain controlling; hints only shorten a queue-idle wait and never bypass those gates.

## Evidence and limits

Primary contract: [SQLite PRAGMA data_version](https://www.sqlite.org/pragma.html#pragma_data_version). SQLite specifies that data_version changes when another connection commits, including connections in other processes, and that values must be compared on the same connection.

On the Mac Studio on 17 November 2026, an isolated benchmark using the native TaskLeaseClient resolver and a private HOME/database completed 10,000 steady observer probes in **0.259830 seconds wall time**, **0.259818 seconds CPU**, or **25.98 microseconds wall time per probe**. At two probes per second this projects to about **187 ms CPU per hour per idle worker** for the measured observer loop. This measures data-version/file-stat/resolver overhead in an isolated configuration; it excludes full queue scans, service contention and model work. The observer remained outside a transaction.

`system/tests/test_worker_queue_preflight.py` covers a real separate-process writer, commits racing preflight, coalescing, periodic fallback, connection loss, database replacement, authority changes, registry changes, closure/query-only behavior, all candidate pages, persisted task-policy restrictions, deferrals, native lease/dependency checks, remote read routing and real private review eligibility without grant construction.

`system/tests/test_worker_start_admission.py` exercises the running worker: no model warmup/claim for empty or unavailable preflight, preflight → warmup → native Acquire for work, and a real terminal fixed-pin recovery without warmup. Existing scope-deferral, review and task-client regression suites protect the shared paths.

Preflight is not a new authorization API. Source clone validation remains in its existing preparation path. Remote read APIs do not expose private local review authority or all private trace/creator details; their final canonical Acquire retains those checks. File-only policy/profile changes that are not in the task database remain covered by the periodic fresh slot/profile checks.
