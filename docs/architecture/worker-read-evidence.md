# Worker read evidence

BACH keeps file access, path authorization, task binding, secret-path denial, and tool tracing in `bach_tools.py`. The versioned wire representation is produced by the existing `ellmos_chat.read_evidence.format_read_evidence`; BACH does not copy that formatter or use it to grant access.

## Activation boundary

The versioned `read_file` schema is offered only while an actual `WorkerLeaseBinding` is active and the current runtime session has exactly the read-only tool allowlist `read_file`, `search_text`, and `task_manage`. Before each backend request, including every configured fallback request, `ChatRuntime` runs the existing live worker gate and rebuilds `BachToolProvider` from that same session's refreshed binding, mode, and profile allowlist. The dispatcher receives that same binding and allowlist; a stale schema is not reused across turns or fallback targets. The task lease fences task operations. Task owner, assigned slot, and required model are not used to infer provider identity or enable this format: canonical BACH-owned tasks with an empty task slot and either an empty or explicitly matching model remain eligible. This is provider-neutral and also applies when the configured worker has a local fallback. Other callers and different allowlists retain the existing PR372 `line_numbers` schema and output behavior.

When offered, the schema requires `output_format: "ellmos.read-evidence.v1"`; the path remains subject to the same pre-existing reader checks. A versioned read_file call without that field is unavailable. An unbound caller or a worker with a different allowlist cannot select the v1 branch. If the exact formatter module, schema, limits, or callable signature cannot be validated, BACH returns a bounded `bach.read-evidence-capability.v1` unavailable envelope before opening the file. It does not silently fall back to legacy text for an explicit v1 request.

## Bounds and cursor

Requests use a one-based physical `start_line`, a Unicode code-point `start_char_offset` within that line, and `max_lines`/`max_chars` bounded by the upstream maxima (200 lines and 4000 line-content characters). The reader opens the already-authorized path and supplies only a bounded chunk to the upstream formatter. Its returned JSON must have the exact v1 keys, valid line/cursor relationships, canonical encoding, and fit BACH's 4000-character tool-result budget. If JSON metadata would exceed that budget, BACH asks the formatter for a smaller page from the same bounded chunk. Consumers continue from `next_cursor`; they must not infer omitted line anchors.

The current BACH reader does not attest that it read the complete file, so its v1 calls always pass `source_complete=false` and `source_sha256=null`. A page may therefore carry usable line anchors without claiming a full-file digest. Newline handling follows Python UTF-8 text reading with replacement for invalid byte sequences and universal-newline normalization; offsets count the decoded line content, excluding terminators.

## Release boundary

At this source phase, the upstream PR5 candidate may be loaded only in isolated conformance QA. There is no production dependency pin, installation, service activation, or native-worker acceptance claim until PR5 is regularly merged and an immutable installation source is verified. The BACH regression suite covers the profile gate, no-I/O unavailable paths, bridge/MCP string transport, hash-only trace, and unchanged legacy schema. Exact candidate conformance is recorded separately from those local test doubles.

Correction, measured 2026-10-25 on the Mac Studio (the paragraph above describes the source phase and is outdated):

- ellmos-chat PR #5 was merged regularly on 2026-10-13; its merge commit `1a12f79aa2bb81487758458f9f94a524afc84906` is identical to ellmos-chat `main`.
- BACH `requirements.txt` pins exactly that commit since #384 (2026-10-14).
- The service environment `~/.venvs/bach` has ellmos-chat 0.3.3 installed from exactly that commit (PEP 610 `direct_url.json`), and `_read_evidence_formatter()` validates there.
- Production chat transcripts (`session_snapshots`) contain real v1 pages from 2026-10-18 to 2026-10-24. Between 2026-10-17 and 2026-10-21 some transcripts also contain `formatter_capability_unverified` envelopes.
- No documented acceptance or activation record was found; #384 required verifying the installed service and a real worker read before productive activation. This note records the measured state and is not an acceptance claim.
- Scope stays the exact read-only profile. Since 2026-10-25 the local worker runs with eleven tools, so v1 is not offered to it. Extending v1 to write profiles was measured and rejected for context cost (see `LOKALER-WORKER-HARNESS.md`, section 5).
