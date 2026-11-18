# Native resource host connection — #4218

BACH's local model-call boundary can use the canonical extracted
`ellmos-ai/ocean-resources` module. `ocean_resources_pin.json` pins the module
version, exact reviewed commit and every Python/JSON package file. Both the
existing read-only pipeline projection and the new native connection use this
same provider verifier. The obsolete `open-ocean` distribution pin is removed
only after replacing it with this stricter provenance/content verification.

The checked-in implementation requires `ocean-resources==0.2.0` from the exact
commit recorded in that pin. Editable installs need the canonical origin, the
pinned revision in HEAD history, a clean package and identical content. A
preloaded unverified provider, changed content or a different in-process pin is
held. Provider failure never falls back to another package or unbrokered local
inference once the broker has been explicitly configured.

## Activation contract

**Current Mac activation is blocked for the default Qwen workload.** The native
preflight on 18 November 2026 found a 32 GiB host with about 17.0 GB available;
the earlier monitored 16,384-context Qwen load reported 20,470,675,124 resident
bytes. The broker's strict full-allocation-plus-reserve admission cannot admit
that workload from the observed available memory. Keep
`BACH_RESOURCE_BROKER_CONFIG` unset in the production model processes until this
gap is resolved. Do not shrink the reviewed profile or count speculative swap as
released RAM. A CPU-only broker running beside uncoordinated Qwen is not a
complete safe migration either.

The required next integration step is an independently reviewed model-only
`LOAD_PENDING` admission phase: checkpoint the registered compute consumer and
hold the exclusive host authority, then use the existing supervised BACH cold
start contract (6 GiB starting headroom, 2 GiB floor, pressure at most 2 and
at most 8 GiB swap growth), followed by confirmed actual residency. That would need
its own explicit profile/transition proof and tests. Ordinary CPU allocations
must retain full physical-capacity admission. This change does not implement or
silently enable that exception; code readiness here is not a production
completion claim for BACH #4218.

Before enabling that transition, its acceptance evidence must establish:

- One writer keeps exclusive ownership through checkpoint, native compute-tree
  exit, supervised loading and confirmed model residency. No competing grant is
  issued during a partial or uncertain load.
- The exact reviewed model digest and context retain all existing cold-start
  monitoring and abort limits. CPU grants and unregistered external memory never
  receive speculative capacity credits.
- Cancellation, client expiry, process death and authority restart at every
  transition boundary retain durable identity and unresolved effects. Neither
  elapsed time nor a transport failure proves model absence.
- Compute resumes its original validated checkpoint only after the exact owned
  model has returned, native absence is confirmed and fresh capacity admits it.
  All participating model callers use the same authority and inference lock;
  missing authority fails closed without enabling an unbrokered parallel path.

The complete, authoritative configuration/evidence/API contract is in the
module's `docs/product-host.md`. Do not copy fixture allocations into production.
Observe and independently review the exact native model and CPU workloads first.
The model must be the actual installed name and digest, Ollama must be exactly
0.33.3, and the profile must cover the intended context and representative
inference. Account for server/runner CPU and residency; unknown external daemon
residency blocks this profile scope.

Start one explicit host service using the reviewed BACH interpreter:

```text
python system/tools/maintenance/resource_host.py --config /absolute/private/host.json --sha256 <approved-config-SHA256>
```

The configuration, tokens, evidence, endpoint files and writer state are private
host-local files outside the source repository and OneDrive. The service emits
only host/authority/port status; token values remain in their private files.
Its endpoint files are authority-fenced and updated atomically on startup.
HTTP binds only to 127.0.0.1. Cross-host resources are not pooled.

For the Mac service use the same `BACH_RUNTIME_DIR=/Users/lukas/.bach/runtime`
as existing chat/worker processes. All participating BACH chat, connector and
worker processes must receive `BACH_RESOURCE_BROKER_CONFIG` pointing at the
service-generated BACH client endpoint file. The inference root remains
`/Users/lukas/.bach/runtime/local-inference`; do not make a second lock root.
The optional read-only projection still uses its existing
`BACH_PIPELINE_COORDINATION_ENABLED=1` flag independently.

No broker environment variable means the existing BACH path remains available.
An explicitly configured authority that is missing, stale or invalid produces
HOLD before any local inference. External model endpoints do not request local
host resources. Only registered local model endpoints, digests and context caps
can proceed. Existing budget, worker lease, model binding, reserve and cold-start
checks all remain in the actual dispatch path.

The resource grant is acquired before reserve polling, so a registered compute
consumer can checkpoint and return its allocation. It is also acquired before
HostInferenceGate. The host client reports end_turn only after inference.lock
has been released. Foreground/background priority inside that native gate is
unchanged. A shared BACH client reuses an active matching model reservation
across channels; chat/session memory remains owned by the existing runtime.

## Return, idle and recovery

The native `GuardedModelPort` performs explicit cooperative return. It verifies
the exact durable grant/execution through the arbiter, acquires the existing
HostInferenceGate, verifies version and model identity, writes the existing
durable unload-pending intent, checks the terminal unload ACK and observes the
target actually disappear. No foreign resident alias or other model is unloaded.
Only then can the resource arbiter use a fresh host capacity observation to give
the next request its grant. The independent pressure watchdog's pressure rule is
unchanged.

Timeout/unknown response retains the intent and allocation; no ambiguous POST
is retried automatically. Existing turns finish before return; client TTL never
asserts they have ended. Service restart retains journal evidence and refuses to
adopt an unresolved old execution. A launch supervisor should not clear files or
spin on this HOLD. Stop/cancel owned work and read an idle controller before a
normal service stop. Restart reconciliation must establish actual native state.

Choose broker `idle_seconds` together with BACH/Ollama `keep_alive` (the backend
constructor default is five minutes). The broker does not silently prolong the
server's retention timer. A longer idle retention is appropriate only with both
settings aligned. Competing work still requests return after the configured
interactive slice, after current inference finishes.

External CPU callers use `python -m ocean_resources.client_cli` or `HostClient`
with a scoped endpoint file. Only reviewed, server-owned cooperative processes
can be started/checkpointed/stopped/resumed. An arbitrary already-running PID is
not a resource grant and cannot be safely adopted by this API.

## Verification

Tests use temporary HOME/DB/runtime state, injected model APIs and owned fixture
children. They cover real HTTP CPU→model→CPU checkpoint/resume, request TTL
separate from controller heartbeat, cancellation, exact durable identity,
unconfirmed unloads and the native runtime lock order. A separate temporary
editable installation verifies the real metadata/origin/revision/content checks;
it does not modify the production interpreter installation.
