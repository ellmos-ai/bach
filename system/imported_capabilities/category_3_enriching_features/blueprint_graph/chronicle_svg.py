"""Deterministic SVG for the Case Chronicle views.

Three properties this module is built for, in order.

**Deterministic bytes.** No timestamps, no randomness, no dictionary iteration
order, and every coordinate rounded to two decimals. The same input renders to
the same bytes, which is what lets a run ledger hash an image and mean it.

**Claim-safe.** Nothing is drawn that the data does not carry. An edge exists
only where a sentence stated it, a gap is drawn as a gap rather than filled in,
and an unknown time is a marked band rather than a plausible-looking point.

**Readable without colour.** Every distinction carries a text label as well as a
stroke style, and each figure has a legend plus a ``<desc>`` that says in words
what the picture shows. A finding nobody can read is not evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

SVG_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'
INK = "#0d2b33"
MUTED = "#5d7078"
ACCENT = "#1c7f86"
SIGNAL = "#c2552f"
PAPER = "#f6f2e6"
LINE = "#c9cfc7"
MAX_LABEL_CHARS = 28


def _round(value: float) -> str:
    """Two decimals, and never "-0.0"."""
    rendered = f"{value:.2f}"
    return "0.00" if rendered == "-0.00" else rendered


def _text(value: str, limit: int = MAX_LABEL_CHARS) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return escape(collapsed)


@dataclass(frozen=True, slots=True)
class Figure:
    """A rendered figure and the sentence that describes it in words."""

    svg: str
    description: str

    def encode(self) -> bytes:
        return self.svg.encode("utf-8")


def _document(width: int, height: int, title: str, description: str, body: str) -> Figure:
    svg = (
        f'{SVG_HEADER}<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(description)}">\n'
        f"  <title>{escape(title)}</title>\n"
        f"  <desc>{escape(description)}</desc>\n"
        f'  <rect width="{width}" height="{height}" fill="{PAPER}"/>\n'
        f"{body}"
        "</svg>\n"
    )
    return Figure(svg=svg, description=description)


def _legend(entries: tuple[tuple[str, str], ...], x: float, y: float) -> str:
    """A legend where every entry is a word, not only a stroke."""
    parts = ['  <g class="legend" font-family="monospace" font-size="10">\n']
    for index, (mark, label) in enumerate(entries):
        offset = y + index * 14
        parts.append(
            f'    <text x="{_round(x)}" y="{_round(offset)}" fill="{MUTED}">'
            f"{escape(mark)} {escape(label)}</text>\n"
        )
    parts.append("  </g>\n")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# K5: the relation graph
# --------------------------------------------------------------------------- #


def relation_graph_svg(
    people: tuple[tuple[str, str], ...],
    edges: tuple[tuple[str, str, str, str], ...],
    *,
    width: int = 720,
    height: int = 520,
) -> Figure:
    """Draw people as nodes and stated relations as edges.

    ``people`` is (id, label) and ``edges`` is (subject, object, kind, quote).
    A node with no edge is still drawn: a person nobody linked to anyone is a
    finding, not an omission.
    """
    if not people:
        return _document(
            width, 160, "Relation graph",
            "No person was declared in the approved sources, so no graph was drawn.",
            f'  <text x="24" y="90" font-family="monospace" font-size="13" fill="{MUTED}">'
            "No declared person in these sources.</text>\n",
        )
    centre_x = width / 2
    centre_y = height / 2 - 10
    radius = min(width, height) / 2 - 110
    positions: dict[str, tuple[float, float]] = {}
    # Fixed angles from a fixed start: the layout is a function of the ordered
    # input, never of a random seed or a hash.
    step = 360.0 / len(people)
    for index, (entity_id, _) in enumerate(people):
        angle = math.radians(-90.0 + index * step)
        positions[entity_id] = (
            centre_x + radius * math.cos(angle),
            centre_y + radius * math.sin(angle),
        )

    body = [
        f'  <text x="24" y="32" font-family="monospace" font-size="12" fill="{INK}">'
        "RELATION GRAPH</text>\n"
    ]
    typed = 0
    for subject, target, kind, quote in edges:
        if subject not in positions or target not in positions:
            continue
        start = positions[subject]
        end = positions[target]
        is_typed = kind != "ko_nennung"
        typed += 1 if is_typed else 0
        dash = "" if is_typed else ' stroke-dasharray="5 4"'
        colour = ACCENT if is_typed else MUTED
        body.append(
            f'  <line x1="{_round(start[0])}" y1="{_round(start[1])}" '
            f'x2="{_round(end[0])}" y2="{_round(end[1])}" stroke="{colour}" '
            f'stroke-width="{"1.8" if is_typed else "1.1"}"{dash}>'
            f"<title>{_text(quote, 160)}</title></line>\n"
        )
        if is_typed:
            middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            body.append(
                f'  <text x="{_round(middle[0])}" y="{_round(middle[1] - 4)}" '
                f'font-family="monospace" font-size="9" fill="{ACCENT}" '
                f'text-anchor="middle">{_text(kind, 18)}</text>\n'
            )
    for entity_id, label in people:
        x, y = positions[entity_id]
        body.append(
            f'  <circle cx="{_round(x)}" cy="{_round(y)}" r="7" fill="{PAPER}" '
            f'stroke="{INK}" stroke-width="1.6"/>\n'
            f'  <text x="{_round(x)}" y="{_round(y - 13)}" font-family="monospace" '
            f'font-size="10" fill="{INK}" text-anchor="middle">{_text(label)}</text>\n'
        )
    body.append(
        _legend(
            (
                ("———", "stated relation (typed, with quote)"),
                ("- - -", "named together in one sentence only"),
            ),
            24,
            height - 34,
        )
    )
    description = (
        f"Relation graph with {len(people)} people and {len(edges)} edges, of which "
        f"{typed} are typed relations stated in a sentence and {len(edges) - typed} "
        "record only that two people are named together. Every edge carries the "
        "sentence it came from."
    )
    return _document(width, height, "Relation graph", description, "".join(body))


# --------------------------------------------------------------------------- #
# Shared scale for the two time figures
# --------------------------------------------------------------------------- #

HATCH = (
    '  <defs><pattern id="nf-gap" width="8" height="8" patternUnits="userSpaceOnUse" '
    'patternTransform="rotate(45)">'
    f'<rect width="8" height="8" fill="{PAPER}"/>'
    f'<line x1="0" y1="0" x2="0" y2="8" stroke="{MUTED}" stroke-width="1.4"/>'
    "</pattern></defs>\n"
)


def _scale(values: tuple[int, ...], left: float, right: float):
    """Map stated minutes onto x. A single moment sits in the middle, not at 0."""
    if not values:
        return lambda _: (left + right) / 2
    low, high = min(values), max(values)
    if high == low:
        return lambda _: (left + right) / 2
    span = high - low
    return lambda value: left + (right - left) * (value - low) / span


def _axis(low_label: str, high_label: str, left: float, right: float, y: float) -> str:
    return (
        f'  <line x1="{_round(left)}" y1="{_round(y)}" x2="{_round(right)}" '
        f'y2="{_round(y)}" stroke="{LINE}" stroke-width="1"/>\n'
        f'  <text x="{_round(left)}" y="{_round(y + 16)}" font-family="monospace" '
        f'font-size="9" fill="{MUTED}">{escape(low_label)}</text>\n'
        f'  <text x="{_round(right)}" y="{_round(y + 16)}" font-family="monospace" '
        f'font-size="9" fill="{MUTED}" text-anchor="end">{escape(high_label)}</text>\n'
    )


# --------------------------------------------------------------------------- #
# K4: the timeline
# --------------------------------------------------------------------------- #


def timeline_svg(
    lanes: tuple[tuple[str, tuple[tuple[str, int, int | None, bool], ...]], ...],
    *,
    title: str = "Timeline",
    width: int = 860,
) -> Figure:
    """Draw one lane per subject.

    Each entry is (label, start_minutes, end_minutes or None, determined). An
    undetermined entry is drawn as a hatched band across the whole lane rather
    than as a point, because the sources did not say where the point would go.
    """
    if not lanes:
        return _document(
            width, 150, title,
            "No event with a stated time was found in the approved sources.",
            f'  <text x="24" y="86" font-family="monospace" font-size="13" fill="{MUTED}">'
            "No event with a stated time.</text>\n",
        )
    left, right = 190.0, width - 40.0
    top = 62.0
    lane_height = 34.0
    height = int(top + len(lanes) * lane_height + 74)
    determined = tuple(
        start for _, entries in lanes for _, start, _, ok in entries if ok
        for start in (start,)
    )
    ends = tuple(
        end for _, entries in lanes for _, _, end, ok in entries if ok and end is not None
    )
    scale = _scale((*determined, *ends), left, right)
    body = [
        HATCH,
        f'  <text x="24" y="32" font-family="monospace" font-size="12" fill="{INK}">'
        f"{escape(title.upper())}</text>\n",
    ]
    undetermined_total = 0
    for index, (lane, entries) in enumerate(lanes):
        y = top + index * lane_height
        body.append(
            f'  <text x="24" y="{_round(y + 4)}" font-family="monospace" font-size="10" '
            f'fill="{INK}">{_text(lane, 22)}</text>\n'
            f'  <line x1="{_round(left)}" y1="{_round(y)}" x2="{_round(right)}" '
            f'y2="{_round(y)}" stroke="{LINE}" stroke-width="0.8"/>\n'
        )
        for label, start, end, ok in entries:
            if not ok:
                undetermined_total += 1
                body.append(
                    f'  <rect x="{_round(left)}" y="{_round(y - 8)}" '
                    f'width="{_round(right - left)}" height="16" fill="url(#nf-gap)" '
                    f'stroke="{MUTED}" stroke-width="0.8" stroke-dasharray="3 3">'
                    f"<title>{_text(label, 160)}</title></rect>\n"
                    # The word has to be readable on top of the hatching.
                    f'  <rect x="{_round((left + right) / 2 - 42)}" y="{_round(y - 7)}" '
                    f'width="84" height="14" fill="{PAPER}"/>\n'
                    f'  <text x="{_round((left + right) / 2)}" y="{_round(y + 4)}" '
                    f'font-family="monospace" font-size="9" fill="{INK}" '
                    f'text-anchor="middle">unbestimmt</text>\n'
                )
                continue
            x1 = scale(start)
            if end is None:
                body.append(
                    f'  <circle cx="{_round(x1)}" cy="{_round(y)}" r="4.5" '
                    f'fill="{ACCENT}"><title>{_text(label, 160)}</title></circle>\n'
                )
            else:
                x2 = max(scale(end), x1 + 3)
                body.append(
                    f'  <rect x="{_round(x1)}" y="{_round(y - 5)}" '
                    f'width="{_round(x2 - x1)}" height="10" fill="{ACCENT}" '
                    f'opacity="0.75"><title>{_text(label, 160)}</title></rect>\n'
                )
    axis_values = (*determined, *ends)
    body.append(
        _axis(
            "earliest stated" if axis_values else "no stated time",
            "latest stated" if axis_values else "",
            left,
            right,
            top + len(lanes) * lane_height + 8,
        )
    )
    body.append(
        _legend(
            (
                ("●", "point in time stated by a source"),
                ("▬", "interval stated by a source"),
                ("▨", "time the sources leave undetermined"),
            ),
            24,
            height - 46,
        )
    )
    description = (
        f"Timeline with {len(lanes)} lane(s). Points and bars are times the sources "
        f"state; {undetermined_total} entr(y/ies) are hatched because the sources "
        "leave the time undetermined and it is not placed at a guessed moment."
    )
    return _document(width, height, title, description, "".join(body))


# --------------------------------------------------------------------------- #
# K6: the alibi weave
# --------------------------------------------------------------------------- #


def alibi_weave_svg(
    rows: tuple[tuple[str, str, int | None, int], ...],
    gaps: tuple[tuple[str, str], ...],
    *,
    title: str = "Alibi weave",
    width: int = 860,
) -> Figure:
    """Draw one line per stated position and a second line for each confirmation.

    Each row is (subject, place, minutes or None, confirmation count). A second
    line is drawn only where another source confirmed the position, so the
    difference between "he says" and "somebody else says" is visible at a
    glance and is never collapsed into one stroke.
    """
    if not rows and not gaps:
        return _document(
            width, 150, title,
            "No stated position and no gap were found in the approved sources.",
            f'  <text x="24" y="86" font-family="monospace" font-size="13" fill="{MUTED}">'
            "Nothing stated, nothing missing.</text>\n",
        )
    left, right = 200.0, width - 40.0
    top = 66.0
    row_height = 38.0
    height = int(top + (len(rows) + len(gaps)) * row_height + 84)
    # A position is a stroke with a word beside it, so the scale has to end early
    # enough for both to fit. Mapping onto the full band put the right-most row
    # and its label off the canvas entirely.
    half, label_width = 46.0, 152.0
    scale = _scale(
        tuple(value for _, _, value, _ in rows if value is not None),
        left + half,
        right - half - label_width,
    )
    body = [
        HATCH,
        f'  <text x="24" y="32" font-family="monospace" font-size="12" fill="{INK}">'
        f"{escape(title.upper())}</text>\n",
    ]
    corroborated = 0
    for index, (subject, place, minutes, confirmations) in enumerate(rows):
        y = top + index * row_height
        body.append(
            f'  <text x="24" y="{_round(y)}" font-family="monospace" font-size="10" '
            f'fill="{INK}">{_text(subject, 20)}</text>\n'
            f'  <text x="24" y="{_round(y + 12)}" font-family="monospace" font-size="9" '
            f'fill="{MUTED}">{_text(place, 20)}</text>\n'
        )
        centre = scale(minutes) if minutes is not None else (left + right) / 2
        body.append(
            f'  <line x1="{_round(centre - 46)}" y1="{_round(y)}" '
            f'x2="{_round(centre + 46)}" y2="{_round(y)}" stroke="{INK}" '
            f'stroke-width="2.4"><title>self-reported position</title></line>\n'
            f'  <text x="{_round(centre + 54)}" y="{_round(y + 3)}" '
            f'font-family="monospace" font-size="9" fill="{MUTED}">selbstauskunft</text>\n'
        )
        if confirmations:
            corroborated += 1
            body.append(
                f'  <line x1="{_round(centre - 46)}" y1="{_round(y + 9)}" '
                f'x2="{_round(centre + 46)}" y2="{_round(y + 9)}" stroke="{ACCENT}" '
                f'stroke-width="2.4"><title>confirmed by another source</title></line>\n'
                f'  <text x="{_round(centre + 54)}" y="{_round(y + 12)}" '
                f'font-family="monospace" font-size="9" fill="{ACCENT}">'
                f"fremdbestaetigt ({confirmations})</text>\n"
            )
    for index, (subject, reason) in enumerate(gaps):
        y = top + (len(rows) + index) * row_height
        body.append(
            f'  <text x="24" y="{_round(y)}" font-family="monospace" font-size="10" '
            f'fill="{INK}">{_text(subject, 20)}</text>\n'
            f'  <rect x="{_round(left)}" y="{_round(y - 9)}" '
            f'width="{_round(right - left)}" height="18" fill="url(#nf-gap)" '
            f'stroke="{SIGNAL}" stroke-width="1" stroke-dasharray="4 3">'
            f"<title>{_text(reason, 160)}</title></rect>\n"
            # The word has to be readable on top of the hatching.
            f'  <rect x="{_round((left + right) / 2 - 98)}" y="{_round(y - 7)}" '
            f'width="196" height="14" fill="{PAPER}"/>\n'
            f'  <text x="{_round((left + right) / 2)}" y="{_round(y + 4)}" '
            f'font-family="monospace" font-size="9" fill="{SIGNAL}" '
            f'text-anchor="middle">Lücke: keine Fremdbestätigung</text>\n'
        )
    body.append(
        _legend(
            (
                ("———", "selbstauskunft: the person says so"),
                ("———", "fremdbestaetigt: another source says so, at place and time"),
                ("▨", "Lücke: nothing places this person in the window"),
            ),
            24,
            height - 58,
        )
    )
    description = (
        f"Alibi weave with {len(rows)} stated position(s), of which {corroborated} carry "
        f"a second line because another source confirms them, and {len(gaps)} hatched "
        "gap(s) where no source places the person at all."
    )
    return _document(width, height, title, description, "".join(body))
