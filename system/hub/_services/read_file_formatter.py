"""Host-neutral formatting for bounded physical-line file excerpts."""
from __future__ import annotations

from collections.abc import Sequence

MAX_READ_FILE_LINES = 200
MAX_READ_FILE_OFFSET = 2_147_483_647
MAX_READ_FILE_OUTPUT_CHARS = 4000


def _line_text(value: str) -> str:
    return value.rstrip("\r\n")


def _truncation_marker(line_number: int, *, partial: bool) -> str:
    if partial:
        detail = f"Zeile {line_number} ist unvollständig angezeigt"
    else:
        detail = f"Zeile {line_number} ist nicht vollständig angezeigt"
    return (
        f"[Ausgabe bei {MAX_READ_FILE_OUTPUT_CHARS} Zeichen gekürzt; {detail}. "
        f"Weiterlesen mit offset={line_number}.]"
    )


def format_read_file_output(
    rows: Sequence[tuple[int, str]],
    *,
    offset: int,
    requested_lines: int,
    effective_lines: int,
    total_lines: int,
) -> str:
    """Format numbered physical lines with honest range and truncation metadata.

    The output contains no filesystem path. ``rows`` must be the consecutive
    physical lines starting at ``offset`` that the guarded caller actually read.
    """
    if type(offset) is not int or not 1 <= offset <= MAX_READ_FILE_OFFSET:
        raise ValueError("offset must be a bounded positive integer")
    if type(requested_lines) is not int or requested_lines < 1:
        raise ValueError("requested_lines must be a positive integer")
    if type(effective_lines) is not int or not 1 <= effective_lines <= MAX_READ_FILE_LINES:
        raise ValueError("effective_lines is outside the read limit")
    if effective_lines != min(requested_lines, MAX_READ_FILE_LINES):
        raise ValueError("effective_lines does not match the request cap")
    if type(total_lines) is not int or total_lines < 0:
        raise ValueError("total_lines must be a non-negative integer")

    normalized: list[tuple[int, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError("rows must contain line-number/text pairs")
        line_number, text = row
        expected = offset + index
        if type(line_number) is not int or line_number != expected:
            raise ValueError("rows must contain consecutive physical line numbers")
        if type(text) is not str or line_number > total_lines or index >= effective_lines:
            raise ValueError("row is outside the validated file excerpt")
        normalized.append((line_number, text))

    if total_lines == 0:
        page_note = f"Datei leer (0 physische Zeilen); Offset={offset}; angezeigt=0/{effective_lines}."
    elif not normalized:
        page_note = (
            f"Dateiende bei Zeile {total_lines}; Offset={offset} liegt dahinter; "
            f"angezeigt=0/{effective_lines}."
        )
    else:
        first, last = normalized[0][0], normalized[-1][0]
        count = len(normalized)
        if last < total_lines:
            end_note = f"weitere Zeilen vorhanden; fortsetzen mit offset={last + 1}"
        else:
            end_note = "Dateiende erreicht"
        page_note = (
            f"Physische Zeilen {first}–{last} von {total_lines}; Offset={offset}; "
            f"angezeigt={count}/{effective_lines}; {end_note}."
        )
    if requested_lines > effective_lines:
        page_note += f" Anfrage auf höchstens {effective_lines} Zeilen begrenzt."
    header = page_note + "\n"

    body = "".join(
        f"{line_number:>6} | {_line_text(text)}\n"
        for line_number, text in normalized
    )
    complete = header + body
    if len(complete) <= MAX_READ_FILE_OUTPUT_CHARS:
        return complete.rstrip("\n")

    # A compact header leaves room for useful source text while still stating
    # the requested physical offset, page limit, and file extent.
    compact = (
        f"Auszug ab physischer Zeile {offset}; Limit={effective_lines}; "
        f"Datei={total_lines} physische Zeilen."
    )
    if requested_lines > effective_lines:
        compact += f" Anfrage auf höchstens {effective_lines} Zeilen begrenzt."
    output = compact + "\n"
    used = len(output)
    for index, (line_number, text) in enumerate(normalized):
        content = _line_text(text)
        prefix = f"{line_number:>6} | "
        full_row = prefix + content + "\n"
        if index + 1 < len(normalized):
            next_number = normalized[index + 1][0]
            reserve = "\n" + _truncation_marker(next_number, partial=False)
            if used + len(full_row) + len(reserve) <= MAX_READ_FILE_OUTPUT_CHARS:
                output += full_row
                used += len(full_row)
                continue
        elif used + len(full_row) <= MAX_READ_FILE_OUTPUT_CHARS:
            output += full_row
            used += len(full_row)
            continue

        marker = "\n" + _truncation_marker(line_number, partial=True)
        room = MAX_READ_FILE_OUTPUT_CHARS - used - len(marker)
        if room > len(prefix):
            partial = prefix + content[:room - len(prefix)]
            output += partial + marker
        else:
            marker = "\n" + _truncation_marker(line_number, partial=False)
            output += marker
        return output
    return output.rstrip("\n")
