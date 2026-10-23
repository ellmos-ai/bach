# Watchdog unload and host inference coordination

This protocol is a source delivery. It does not activate the watchdog helper or
prove that a running process has loaded the updated gate.

## Shared ownership

BACH's existing HostInferenceGate holds local-inference/inference.lock with a
POSIX flock for the complete model call. The watchdog helper uses that same
existing file and lock family. It never replaces the file, creates an alternative
lock, starts a model, or creates another admission queue.

All participating consumers and the watchdog must use the same local runtime
root. BACH derives it from BACH_RUNTIME_DIR or the user's default runtime.
A separately configured watchdog root must resolve to that exact location.

The Mac helper is delivered at
system/tools/maintenance/memory_pressure_unload_guard.py. It uses the Python
standard library, including POSIX flock and SIGALRM. It is not a Windows tool.

## Unload transaction

The helper acquires the inference lock without waiting. A missing lock or
ineligible owner/path causes a skip. It refuses an existing unload-pending.json.

Inside the lock it checks the legacy session flag and a fresh native pressure
measurement. Confirmed normal pressure and unavailable pressure measurements
prevent an unload. The configured escalation thresholds still decide eligibility
for a known non-normal measurement. Session and pressure are checked again
before each model request.

The currently reviewed Ollama version is 0.33.3. A different version is rejected
before mutation. Model name and digest come from a validated GET /api/ps snapshot.

Before the POST, the helper exclusively writes unload-pending.json, flushes the
file and its directory, and only then submits keep_alive=0. The intent contains
an opaque request identifier, PID, time, and a hash binding name and digest.
Logs contain fixed reason codes without model names or raw server responses.

In [Ollama 0.33.3 GenerateHandler](https://github.com/ollama/ollama/blob/v0.33.3/server/routes.go),
done_reason=unload acknowledges the expiry request. The
[scheduler](https://github.com/ollama/ollama/blob/v0.33.3/server/sched.go)
can still defer it while a runner has active references. Therefore the helper
keeps the lock and intent while polling GET /api/ps. Both the original name and
digest must be absent before the intent is removed and its directory flushed.

The log code ollama_unload_confirmed means observed runner absence. It does not
measure physical RAM release or prove that this request alone caused the change.
Exit 0 means all listed targets reached that observed state. Partial success is
reported per target; any later failure makes the overall exit nonzero.

The CLI arms a 20-second signal timer. This bounds ordinary user-space waits;
it is not a hard real-time guarantee for an uninterruptible operating-system
operation. A timeout, crash, invalid response, or ambiguous POST retains intent.
Neither a subsequent helper call nor the gate automatically removes it.

## Gate behavior and deployment order

The updated gate checks for unload-pending.json after acquiring inference.lock
and before admitting the next request. Any existing entry, including an invalid
or dangling entry, denies model dispatch. It does not infer completion from a
dead helper PID or the entry's age.

The gate update and helper must be deployed as one coordinated change:

1. Record current source, runtime root, processes, watchdog source, and rollback
   copies. Obtain the actual host deployment authority.
2. Quiesce participating callers and prove the old gate consumers have exited.
   A changed file on disk is insufficient.
3. Install and load the updated gate. Verify the actual runtime root and process
   source for every participating consumer.
4. Install the helper and then wire only the watchdog's existing
   do_ollama_unload_all function to it.
5. Restart the watchdog using the host's actual service manager. Read back the
   new process and source, then perform separately authorized runtime acceptance.

A portable shell integration inside the existing watchdog function is:

```bash
inference_root="${BACH_RUNTIME_DIR:-$HOME/.bach/runtime}/local-inference"
"$python" -I -B "$helper" \
  --inference-root "$inference_root" \
  --session-flag "$SESSION_FLAG" --metric-mode "$METRIC_MODE" \
  --warn-level "$PRESSURE_WARN_LEVEL" \
  --emergency-pages "$FREE_EMERGENCY_PAGES" \
  --free-threshold "${free_threshold:-$FREE_PAGES_MIN}" >> "$LOG" 2>&1
```

Here python and helper are operator-bound absolute paths to the intended
interpreter and delivered helper. No copy command, daemon restart, or model
operation is performed by this document.

Direct provider clients that do not use this gate are outside its admission and
pending protection. The inspected Ollama scheduler protects already referenced
requests; that is not proof of shared session-wide coordination. Inventory direct
web clients, model tools, and idle-maintenance callers before claiming full host
coverage. Do not activate this helper while older gate code remains in use.

## Recovery from an unresolved intent

Do not delete the intent merely because the helper exited, its PID was reused,
the entry is old, or a single GET shows no model. An earlier request may still
be processing server-side.

An operator must preserve the intent and its exact hash, stop new participating
dispatch, and establish that no old unload can still execute. This needs either
a correlated terminal backend receipt or an explicitly authorized controlled
backend shutdown/restart with proof that the old backend and its requests have
terminated. Check direct callers before any such service action; the helper
does not perform it.

After verified backend quiescence, check the current backend generation and
model state. Under the same inference lock, remove only the exact unchanged
intent whose outcome was resolved, flush the directory, and record the evidence
and decision. A replacement intent or changed hash requires a new investigation.
This delivery intentionally provides no automatic clear or retry command.

## Acceptance and rollback boundaries

Before activation, prove the participating caller inventory, gate code actually
loaded by those processes, identical lock roots/inodes, and recovery procedure.
Runtime acceptance must cover active and starting model calls, unknown pressure,
session protection, delayed ACK versus completion, process death, and an
unresolved intent. RAM or pressure relief requires separate observations.

The watchdog's other escalation actions, compute pause/resume, and main-loop
pull/recovery policy are not replaced by this helper. An outer loop that maps
unknown pressure to a numeric level still needs its own policy correction.

For rollback, first stop new watchdog unload attempts and resolve every pending
operation. Keep the updated gate while intent remains unresolved. Restore source
and restart processes only within the authorized host procedure; never roll back
to a gate that ignores an outstanding intent.
