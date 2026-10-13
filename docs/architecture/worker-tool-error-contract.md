# Worker-tool error contract v1

The task CLI relay needs to carry safe error metadata without changing the
legacy display value. A message prefix is never proof that a tool was blocked
or that it had no effect. Only a locally constructed ToolErrorText from a
known producer may create a structured envelope.

## Wire value

A returned typed error is an exact bach.worker-tool-error.v1 object:

    {
      "schema": "bach.worker-tool-error.v1",
      "code": "write_path_denied",
      "source": "bach_tools.write_file",
      "reason": "write_path_denied",
      "effect_state": "not_applied",
      "correlation": {
        "request_id": "32 lowercase hex characters",
        "generation": "bound worker generation",
        "task_id": 42001,
        "receipt_id": "32 lowercase hex characters"
      }
    }

The correlation values are validated dynamically against the current call;
they are not drawn from a fixed sample-ID list. task_id is a positive strict
integer. A normal returned trace must be confirmed before the bridge creates
and sends a receipt.

A quarantined /call response keeps the existing HTTP 503 behavior and
contains the exact response keys plus quarantined: true. Its receipt_id and
the envelope correlation's receipt_id are both null. Here quarantined means
that the local transport/binding is isolated; it does not assert a canonical
lease status. For an unknown effect, the bridge asks the bound lease authority
to release with outcome=blocked before local invalidation. Only a valid native
release ACK confirms blocked/unleased. If the ACK is missing or invalid, the
result remains unknown, the local binding stays disabled, and no pending or
retry status is claimed. Trace-start failure can prove the target tool was
not started and only locally invalidates the binding. Provider, execution,
returned-trace, transport, and acknowledgement uncertainty remains unknown;
it is never retried. No receipt is invented to make an unknown outcome look
confirmed.

## Bounded producer catalogue

worker_tool_errors.py maps each allowed code to one producer, one public
reason, and a finite set of effect states. Codes cover explicit provider or
dispatch denials, bound-task preflight/validation, write authorization, and
transport failures. Unknown vendor details map to reason_unavailable;
exception text, credentials, source paths, and provider-specific policy text
are not sent in the structured envelope.

not_applied is reserved for an explicit pre-effect guard or validation
failure. For a bound task_manage call, it describes the bound task operation,
not whether the surrounding tool relay was dispatched. The action must be a
string from the native action set (list, detail, done, submit_result, update,
decompose, add); an invalid type or unsupported string is rejected before
invoking the bound task operation with not_applied. A not_started state means
the tool was not dispatched. unknown means the action or its acknowledgement
may have happened. This version does not claim applied for any error.

Timeouts, exceptions, non-success HTTP replies, and nonzero subprocess exits
after dispatch return the bounded unknown-effect error. Each shell/process
helper checks the returned exit code before exposing output; a nonzero exit
suppresses both stdout and stderr. Raw exception text, HTTP bodies, and process
output from a failed invocation are not returned as a confirmed denial or
success. Callers that compose status or maintenance output preserve that typed
failure instead of reporting a completed operation.

Plain legacy strings remain plain strings, including text beginning with
BLOCKIERT:. The bridge does not infer error status from text. The public
WorkerToolClient.call() method keeps its tuple result for confirmed
responses; callers that need the envelope use call_detailed(). Unknown or
quarantined outcomes raise through the legacy method without retrying.

The stdio MCP shim places a validated envelope in structuredContent and
keeps the display text in text content.

## Integration boundary

This eight-file package covers the producer, local relay, client, MCP
transport, focused contract tests, and architecture note. The normal chat
dispatcher and HTTP/GUI callers are outside this source scope. Until B's
chat_runtime.py/Telegram and C's unified_api.py
integrations preserve typed metadata before string coercion, result digesting,
and tool-finish handling, this package is not a complete end-to-end
application rollout. Existing trace, policy, quarantine, authentication, and
lease gates remain authoritative.
