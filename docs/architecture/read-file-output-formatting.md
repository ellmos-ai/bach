# Read-file excerpt format

`read_file` keeps its existing path and authorization flow. This change formats only the text returned after the existing checks and guarded open have succeeded.

## Call compatibility

The optional `line_numbers` boolean is additive. When omitted, task-bound reads use annotated output; the legacy unbound reader keeps its raw-text output. Passing `line_numbers: false` explicitly requests raw text. `lines` remains capped at 200, and `offset` is a one-based physical line number. Both parameters reject booleans and non-integer values; booleans are not integers for this interface.

## Annotated output

Annotated output identifies the physical line range, total number of decoded physical lines, requested offset, page size, and whether more file lines remain. Each returned row uses its actual one-based physical line number. Empty files and offsets after EOF have explicit summaries. UTF-8 decoding continues to replace invalid byte sequences, and universal newline handling counts CRLF as one physical line.

The output limit is 4,000 characters including the header and any truncation marker. If a row cannot fit in full, the formatter may show a prefix under that row's number and labels it incomplete. The marker gives an offset that can be requested again without skipping the unfinished row. A page boundary is separately reported from character truncation.

This formatting is navigation help, not evidence that a quoted claim is correct. Reviews must verify the cited content and source context; an unnumbered or truncated excerpt is not a verified citation.

## Security boundary

The formatter is host-neutral and receives only the already selected text rows and physical line numbers. It receives no path and has no file or runtime dependencies. `BachToolProvider` still performs the task lease/fence and reader-scope checks before opening task files. Secret, symlink, forbidden-path, or stale-lease denials stay fail-closed and do not expose paths or tokens.

No CLI, HTTP API, GUI route, or task-action contract is changed; this formatter is used only by the existing chat tool provider.
