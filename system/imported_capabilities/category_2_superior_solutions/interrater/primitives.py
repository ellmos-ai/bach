"""Reusable document primitives: structure, dedupe, merge, snapshot delta.

D-032: use cases are open-ended, so the workflows must be compositions of a few
shared, anchored operations rather than four private implementations of the same
ideas. Everything here returns values that carry their own source anchor, which
is what lets a later Voyage library chain these primitives into cases nobody has
written a workflow for yet.

Four primitives, one vocabulary:

* :func:`extract_fields`   - schema-bound extraction of declared fields into rows
* :func:`deduplicate`      - fold repeated statements, keeping every struck one
* :func:`merge_sections`   - merge documents section-wise and surface conflicts
* :func:`snapshot_delta`   - describe what is new against a named baseline

The text helpers they share (sentence splitting, summarising, fingerprinting,
label folding) live here too, because two copies of a sentence splitter is how a
corpus ends up with two different ideas of what a sentence is.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .structured_codec import decode_structured_cell

# --------------------------------------------------------------------------- #
# Shared text handling
# --------------------------------------------------------------------------- #

DEDUPE_SCOPES = frozenset({"exact", "normalized"})
LABEL_SEPARATORS = ":：–—-"
MAX_VALUE_CHARS = 300
MAX_SENTENCE_CHARS = 400
UMLAUT_FOLDING = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# A German ordinal ends a fragment with one or two digits and a period
# ("am 1." + "April 2026."); splitting there cuts a fact in half so the halves
# escape deduplication and stop working as quotes. Two near misses this rule has
# to avoid: a four-digit year ("2026.") really does end a sentence, and so does
# a date fragment ("Rechnung 2026-04."), where the trailing "04" is not an
# ordinal at all. Hence the number must stand on its own after whitespace, not
# merely follow any non-digit. Known limit: "z. B." still splits.
_ORDINAL_TAIL = re.compile(r"(?:^|\s)\d{1,2}\.$")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_LABELLED_LINE = re.compile(r"^\s*(?P<label>[^:#]{2,60}?)\s*:\s*(?P<value>\S.*?)\s*$")
_STRUCTURED_ROW = re.compile(r"^Zeile \d+ · ")


def ascii_variant(label: str) -> str:
    """Transliterate umlauts, because documents write both spellings."""
    return "".join(UMLAUT_FOLDING.get(character, character) for character in label)


def split_sentences(text: str) -> tuple[str, ...]:
    """Split into sentences without cutting German ordinals in half."""
    merged: list[str] = []
    for fragment in _SENTENCE_SPLIT.split(text):
        candidate = fragment.strip()
        if not candidate:
            continue
        if merged and _ORDINAL_TAIL.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {candidate}"
            continue
        merged.append(candidate)
    return tuple(sentence[:MAX_SENTENCE_CHARS] for sentence in merged)


def summarize(text: str, max_sentences: int, *, max_chars: int = 320) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    return " ".join(split_sentences(collapsed)[:max_sentences])[:max_chars]


def fingerprint(statement: str, scope: str) -> str:
    """Key a statement for deduplication under the requested scope."""
    if scope not in DEDUPE_SCOPES:
        raise ValueError("dedupe scope must be exact or normalized")
    collapsed = _WHITESPACE.sub(" ", statement).strip()
    if scope == "exact":
        return collapsed
    folded = unicodedata.normalize("NFKD", collapsed.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", folded)).strip()


@dataclass(frozen=True, slots=True)
class Anchor:
    """Where a value came from. Every primitive result carries one."""

    source_id: str
    line: int


def is_field_line(line: str) -> bool:
    """True for a labelled header field, false for prose that happens to hold a colon.

    The distinction is a short label and no sentence ending: "Deckung ab:
    01.01.2026" is a field, while "Vier Personen wurden befragt: A, B und C." is
    a sentence that must stay joined with the line it wraps onto.
    """
    match = _LABELLED_LINE.match(line)
    if match is None:
        return False
    if line.rstrip().endswith((".", "!", "?")):
        return False
    return len(match.group("label").split()) <= 3


@dataclass(frozen=True, slots=True)
class AnchoredSentence:
    """A sentence plus the line it starts on."""

    text: str
    line: int


def anchored_sentences(text: str, *, max_sentences: int = 2000) -> tuple[AnchoredSentence, ...]:
    """Split a document into sentences that know which line they start on.

    Line-by-line matching looks simpler and is quietly wrong: prose wraps, so a
    name, a date or a place can straddle a line break and then matches nothing at
    all. Missing a person because their surname moved to the next line is a
    silent failure, which is the kind this corpus can least afford. Paragraphs of
    consecutive non-empty lines are therefore joined before splitting, and each
    sentence keeps the line where it begins so an anchor still points somewhere a
    reader can look.
    """
    found: list[AnchoredSentence] = []
    block: list[tuple[int, str]] = []

    def flush() -> None:
        if not block:
            return
        joined = " ".join(line for _, line in block)
        # Walk the sentences against the joined text to find where each starts,
        # then translate that offset back into the original line number.
        offsets: list[int] = []
        position = 0
        for _, line in block:
            offsets.append(position)
            position += len(line) + 1
        cursor = 0
        for sentence in split_sentences(joined):
            index = joined.find(sentence, cursor)
            if index < 0:
                index = cursor
            cursor = index + len(sentence)
            line_number = block[0][0]
            for (number, _), start in zip(block, offsets, strict=True):
                if start <= index:
                    line_number = number
                else:
                    break
            found.append(AnchoredSentence(text=sentence, line=line_number))
        block.clear()

    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            flush()
            continue
        if is_field_line(stripped):
            # A header field is not prose. Joining "Versicherungsnehmer: A" and
            # "Betreuer: B" into one running sentence would put two people in a
            # sentence neither of them appears in, and anything reading
            # co-occurrence would report a link the document never states.
            flush()
            found.append(AnchoredSentence(text=stripped, line=number))
            continue
        block.append((number, stripped))
        if len(found) >= max_sentences:
            break
    flush()
    return tuple(found[:max_sentences])


# --------------------------------------------------------------------------- #
# Primitive 1: schema-bound structure extraction
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()

    def labels(self) -> tuple[str, ...]:
        declared = (self.name, *self.aliases)
        return tuple(dict.fromkeys((*declared, *(ascii_variant(item) for item in declared))))


@dataclass(frozen=True, slots=True)
class FieldValue:
    field: str
    value: str | None = None
    anchor: Anchor | None = None
    quote: str | None = None

    @property
    def filled(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True)
class FieldRow:
    source_id: str
    display_name: str
    values: tuple[FieldValue, ...]
    record_line: int | None = None

    @property
    def filled_count(self) -> int:
        return sum(1 for value in self.values if value.filled)


def label_pattern(spec: FieldSpec) -> re.Pattern[str]:
    labels = sorted(
        {label.strip() for label in spec.labels() if label.strip()}, key=len, reverse=True
    )
    alternatives = "|".join(re.escape(label) for label in labels)
    return re.compile(
        rf"^\s*(?:{alternatives})\s*[{re.escape(LABEL_SEPARATORS)}]\s*(?P<value>\S.*?)\s*$",
        re.IGNORECASE,
    )


def matches_topic(text: str, topic_filter: tuple[str, ...]) -> bool:
    if not topic_filter:
        return True
    haystack = text.casefold()
    return any(term.casefold() in haystack for term in topic_filter)


def extract_fields(
    sources: tuple[tuple[str, str], ...],
    texts: dict[str, str],
    fields: tuple[FieldSpec, ...],
    *,
    topic_filter: tuple[str, ...] = (),
    max_rows: int = 500,
    structured_source_ids: frozenset[str] | None = None,
) -> tuple[tuple[FieldRow, ...], tuple[str, ...]]:
    """Read declared fields out of labelled lines; return rows and skipped ids.

    A field the sources do not answer stays empty. There is no inference step
    that could fill it, which is the property the whole registry rests on.
    """
    patterns = {spec.name: label_pattern(spec) for spec in fields}
    if structured_source_ids is None:
        structured_source_ids = frozenset(
            source_id for source_id, display_name in sources
            if Path(display_name).suffix.casefold() in {".db", ".sqlite", ".sqlite3", ".xlsx"}
        )
    rows: list[FieldRow] = []
    skipped: list[str] = []
    for source_id, display_name in sources:
        text = texts.get(source_id)
        if text is None or not matches_topic(text, topic_filter):
            skipped.append(source_id)
            continue
        lines = text.splitlines()
        structured_lines = (
            tuple(number for number, line in enumerate(lines, start=1)
                  if _STRUCTURED_ROW.match(line))
            if source_id in structured_source_ids else ()
        )
        record_groups = (
            tuple((number,) for number in structured_lines)
            if structured_lines else (tuple(range(1, len(lines) + 1)),)
        )
        for group in record_groups:
            values: list[FieldValue] = []
            for spec in fields:
                pattern = patterns[spec.name]
                found = FieldValue(field=spec.name)
                for number in group:
                    line = lines[number - 1]
                    # Structured readers label one record per line. Match each
                    # declared cell without borrowing values from another row.
                    structured_row = _STRUCTURED_ROW.match(line) is not None
                    candidates = (
                        tuple(cell.strip() for cell in line.split(" · ")[1:])
                        if structured_row
                        else (line,)
                    )
                    for candidate in candidates:
                        match = pattern.match(candidate)
                        if match is None:
                            continue
                        value = match.group("value").strip()
                        quote = candidate
                        if structured_row:
                            value = decode_structured_cell(value)
                            quote = candidate[: match.start("value")] + value
                        value = value[:MAX_VALUE_CHARS]
                        if not value:
                            continue
                        found = FieldValue(
                            field=spec.name,
                            value=value,
                            anchor=Anchor(source_id=source_id, line=number),
                            quote=(quote if structured_row else line.strip())[:MAX_VALUE_CHARS],
                        )
                        break
                    if found.value is not None:
                        break
                values.append(found)
            if len(rows) >= max_rows:
                raise ValueError("field_rows_limit_exceeded")
            rows.append(
                FieldRow(
                    source_id=source_id,
                    display_name=display_name,
                    values=tuple(values),
                    record_line=group[0] if structured_lines else None,
                )
            )
    return tuple(rows), tuple(skipped)


# --------------------------------------------------------------------------- #
# Primitive 2: deduplication that keeps what it strikes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AnchoredStatement:
    text: str
    anchor: Anchor


@dataclass(frozen=True, slots=True)
class StruckStatement:
    statement: AnchoredStatement
    duplicate_of: AnchoredStatement


@dataclass(frozen=True, slots=True)
class DedupeOutcome:
    kept: tuple[AnchoredStatement, ...]
    struck: tuple[StruckStatement, ...]
    scope: str

    @property
    def struck_count(self) -> int:
        return len(self.struck)


def deduplicate(
    statements: tuple[AnchoredStatement, ...],
    *,
    scope: str = "normalized",
) -> DedupeOutcome:
    """Fold repeated statements, recording every struck occurrence with its twin.

    Nothing is dropped silently: a deduplication a reader cannot audit is
    indistinguishable from a deletion.
    """
    first_seen: dict[str, AnchoredStatement] = {}
    kept: list[AnchoredStatement] = []
    struck: list[StruckStatement] = []
    for statement in statements:
        key = fingerprint(statement.text, scope)
        if not key:
            continue
        original = first_seen.get(key)
        if original is None:
            first_seen[key] = statement
            kept.append(statement)
            continue
        struck.append(StruckStatement(statement=statement, duplicate_of=original))
    return DedupeOutcome(kept=tuple(kept), struck=tuple(struck), scope=scope)


def statements_from_texts(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    min_words: int = 4,
    focus_terms: tuple[str, ...] = (),
    max_per_source: int = 200,
) -> tuple[AnchoredStatement, ...]:
    """Lift quotable sentences out of the sources, each with its own anchor."""
    statements: list[AnchoredStatement] = []
    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        taken = 0
        for number, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            for sentence in split_sentences(stripped):
                if taken >= max_per_source:
                    break
                if len(sentence.split()) < min_words:
                    continue
                if focus_terms and not any(
                    term.casefold() in sentence.casefold() for term in focus_terms
                ):
                    continue
                taken += 1
                statements.append(
                    AnchoredStatement(
                        text=sentence, anchor=Anchor(source_id=source_id, line=number)
                    )
                )
    return tuple(statements)


# --------------------------------------------------------------------------- #
# Primitive 3: section-wise merge with visible conflicts
# --------------------------------------------------------------------------- #

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(?P<title>\S.*?)\s*#*\s*$")
DEFAULT_SECTION = "Document body"
MAX_PARAGRAPH_CHARS = 800


@dataclass(frozen=True, slots=True)
class MergedSection:
    title: str
    paragraphs: tuple[AnchoredStatement, ...]


@dataclass(frozen=True, slots=True)
class MergeConflict:
    section: str
    label: str
    values: tuple[tuple[str, Anchor], ...]


@dataclass(frozen=True, slots=True)
class MergedDocument:
    sections: tuple[MergedSection, ...]
    conflicts: tuple[MergeConflict, ...]
    source_ids: tuple[str, ...]

    @property
    def paragraph_count(self) -> int:
        return sum(len(section.paragraphs) for section in self.sections)


def _sections_of(
    text: str, *, structured: bool = False
) -> list[tuple[str, list[tuple[int, str]]]]:
    sections: list[tuple[str, list[tuple[int, str]]]] = []
    current_title = DEFAULT_SECTION
    current: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        heading = HEADING.match(raw)
        if heading is not None:
            if current:
                sections.append((current_title, current))
                current = []
            current_title = heading.group("title")
            continue
        line = raw.strip()
        if line:
            if structured and _STRUCTURED_ROW.match(line):
                _, *cells = line.split(" · ")
                current.extend(
                    (number, cell.strip()[:MAX_PARAGRAPH_CHARS])
                    for cell in cells if cell.strip()
                )
            else:
                current.append((number, line[:MAX_PARAGRAPH_CHARS]))
    if current:
        sections.append((current_title, current))
    return sections


def merge_sections(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    *,
    max_sections: int = 200,
    structured_source_ids: frozenset[str] = frozenset(),
) -> MergedDocument:
    """Merge documents section by section, surfacing disagreements as conflicts.

    Merging is where provenance is usually lost, so every paragraph keeps its
    anchor and a label two sources answer differently becomes a conflict rather
    than a silent winner.
    """
    ordered_titles: list[str] = []
    grouped: dict[str, list[AnchoredStatement]] = {}
    labelled: dict[tuple[str, str], list[tuple[str, Anchor]]] = {}
    used: list[str] = []

    for source_id in source_ids:
        text = texts.get(source_id)
        if text is None:
            continue
        used.append(source_id)
        for title, entries in _sections_of(
            text, structured=source_id in structured_source_ids
        ):
            key = title.casefold()
            if key not in grouped:
                if len(ordered_titles) >= max_sections:
                    continue
                ordered_titles.append(title)
                grouped[key] = []
            for line, paragraph in entries:
                anchor = Anchor(source_id=source_id, line=line)
                grouped[key].append(AnchoredStatement(text=paragraph, anchor=anchor))
                match = _LABELLED_LINE.match(paragraph)
                if match is None:
                    continue
                labelled.setdefault((key, match.group("label").strip().casefold()), []).append(
                    (match.group("value").strip(), anchor)
                )

    conflicts = [
        MergeConflict(
            section=next(
                (title for title in ordered_titles if title.casefold() == section_key),
                section_key,
            ),
            label=label_key,
            values=tuple(values),
        )
        for (section_key, label_key), values in labelled.items()
        if len({value.casefold() for value, _ in values}) > 1
    ]
    return MergedDocument(
        sections=tuple(
            MergedSection(title=title, paragraphs=tuple(grouped[title.casefold()]))
            for title in ordered_titles
        ),
        conflicts=tuple(sorted(conflicts, key=lambda item: (item.section, item.label))),
        source_ids=tuple(dict.fromkeys(used)),
    )


# --------------------------------------------------------------------------- #
# Primitive 4: snapshot delta
# --------------------------------------------------------------------------- #

OWNER_RESOLVED = "resolved"
OWNER_UNSUPPORTED = "unavailable_on_platform"
OWNER_DENIED = "permission_denied"
OWNER_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DeltaEntry:
    source_id: str
    display_name: str
    size_bytes: int
    modified: str
    summary: str
    owner: str | None
    owner_status: str


def resolve_owner(path: Path) -> tuple[str | None, str]:
    """Name the owning account, or say precisely why it cannot be named."""
    try:
        # typeshed marks Path.owner as unavailable on Windows, which is exactly
        # the case this function exists to report at runtime rather than avoid.
        return path.owner(), OWNER_RESOLVED  # type: ignore[misc]
    except NotImplementedError:
        return None, OWNER_UNSUPPORTED
    except PermissionError:
        return None, OWNER_DENIED
    except (OSError, KeyError, ValueError):
        return None, OWNER_UNKNOWN


def snapshot_delta(
    records: tuple[tuple[str, str, str], ...],
    texts: dict[str, str],
    new_source_ids: tuple[str, ...],
    *,
    max_sentences: int = 3,
    max_entries: int = 500,
) -> tuple[tuple[DeltaEntry, ...], str]:
    """Describe each newly seen source; records are (source_id, display_name, path)."""
    wanted = set(new_source_ids)
    entries: list[DeltaEntry] = []
    statuses: set[str] = set()
    for source_id, display_name, path_value in records:
        if source_id not in wanted:
            continue
        path = Path(path_value)
        try:
            stat = path.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(
                timespec="seconds"
            )
        except OSError:
            size = 0
            modified = ""
        owner, status = resolve_owner(path)
        statuses.add(status)
        entries.append(
            DeltaEntry(
                source_id=source_id,
                display_name=display_name,
                size_bytes=size,
                modified=modified,
                summary=summarize(texts.get(source_id, ""), max_sentences),
                owner=owner,
                owner_status=status,
            )
        )
        if len(entries) >= max_entries:
            break
    unresolved = statuses - {OWNER_RESOLVED}
    overall = (
        OWNER_UNKNOWN
        if not entries
        else OWNER_RESOLVED
        if not unresolved
        else sorted(unresolved)[0]
    )
    return tuple(entries), overall


# --------------------------------------------------------------------------- #
# Primitive 5: staged aggregation that keeps its anchors
# --------------------------------------------------------------------------- #

MAX_ANCHORS_PER_RESULT = 50


@dataclass(frozen=True, slots=True)
class AggregationBudget:
    """Ceilings for a staged run. Every one of them is reported when it bites."""

    partition_size: int = 20
    max_partitions: int = 64
    max_per_partition: int = 40
    max_results: int = 200

    def __post_init__(self) -> None:
        for name in ("partition_size", "max_partitions", "max_per_partition", "max_results"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class AggregatedStatement:
    """One folded statement and every place it came from.

    ``anchors`` is a list, not a single anchor: that is the whole difference
    between an aggregate you can follow home and a summary you have to trust.
    """

    text: str
    anchors: tuple[Anchor, ...]
    support: int
    anchor_total: int
    partitions: tuple[int, ...]

    @property
    def anchors_truncated(self) -> bool:
        return self.anchor_total > len(self.anchors)


@dataclass(frozen=True, slots=True)
class AggregationStage:
    name: str
    inputs: int
    outputs: int
    dropped: int = 0


@dataclass(frozen=True, slots=True)
class AggregationOutcome:
    results: tuple[AggregatedStatement, ...]
    stages: tuple[AggregationStage, ...]
    partition_count: int
    notes: tuple[str, ...]

    @property
    def within_budget(self) -> bool:
        return not self.notes


def partition_statements(
    statements: tuple[AnchoredStatement, ...], size: int
) -> tuple[tuple[AnchoredStatement, ...], ...]:
    """Split into fixed-size partitions in input order.

    Deterministic by construction: same input, same partitions, every run. A
    partitioning that depended on hashing or on set iteration would make two
    runs over the same corpus disagree about what was aggregated with what.
    """
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("partition size must be a positive integer")
    return tuple(
        tuple(statements[start:start + size]) for start in range(0, len(statements), size)
    )


def _fold(
    items: tuple[tuple[str, tuple[Anchor, ...], int, tuple[int, ...]], ...],
    scope: str,
    limit: int,
) -> tuple[list[AggregatedStatement], int]:
    """Fold equal statements, unioning their anchors and their partitions."""
    order: list[str] = []
    seen: dict[str, tuple[str, list[Anchor], int, list[int], int]] = {}
    for text, anchors, support, partitions in items:
        key = fingerprint(text, scope)
        if not key:
            continue
        found = seen.get(key)
        if found is None:
            order.append(key)
            seen[key] = (text, list(anchors), support, list(partitions), len(anchors))
            continue
        kept_text, kept_anchors, kept_support, kept_partitions, total = found
        known = {(anchor.source_id, anchor.line) for anchor in kept_anchors}
        for anchor in anchors:
            if (anchor.source_id, anchor.line) in known:
                continue
            known.add((anchor.source_id, anchor.line))
            kept_anchors.append(anchor)
            total += 1
        for partition in partitions:
            if partition not in kept_partitions:
                kept_partitions.append(partition)
        seen[key] = (
            kept_text, kept_anchors, kept_support + support, kept_partitions, total
        )
    folded = [
        AggregatedStatement(
            text=text,
            anchors=tuple(anchors[:MAX_ANCHORS_PER_RESULT]),
            support=support,
            anchor_total=total,
            partitions=tuple(partitions),
        )
        for text, anchors, support, partitions, total in (seen[key] for key in order)
    ]
    return folded[:limit], max(0, len(folded) - limit)


def aggregate_mapreduce(
    statements: tuple[AnchoredStatement, ...],
    *,
    scope: str = "normalized",
    budget: AggregationBudget | None = None,
) -> AggregationOutcome:
    """Aggregate a large statement set in two stages without losing provenance.

    Stage one folds inside each partition, stage two folds the partial results
    against each other. An anchor list only ever grows on the way through, so a
    statement that survived both stages can still name every source it came
    from - which is what makes an aggregate over a big corpus quotable instead
    of merely plausible.

    The local extractive fold is the reducer used here. A model stage is meant
    to replace it at the partition level and goes through the existing provider
    gates; this function stays provider-agnostic, so swapping the reducer cannot
    quietly change what happens to the anchors.

    Results keep input order rather than being ranked. Ranking is a decision for
    the workflow that knows what the question was.
    """
    ceiling = budget or AggregationBudget()
    partitions = partition_statements(statements, ceiling.partition_size)
    notes: list[str] = []
    dropped_partitions = 0
    if len(partitions) > ceiling.max_partitions:
        dropped_partitions = len(partitions) - ceiling.max_partitions
        skipped = sum(len(part) for part in partitions[ceiling.max_partitions:])
        partitions = partitions[:ceiling.max_partitions]
        notes.append(
            f"{dropped_partitions} partition(s) holding {skipped} statement(s) were not "
            f"aggregated: the run reached the ceiling of {ceiling.max_partitions} "
            "partitions."
        )

    partial: list[tuple[str, tuple[Anchor, ...], int, tuple[int, ...]]] = []
    per_partition_dropped = 0
    for index, part in enumerate(partitions):
        folded, dropped = _fold(
            tuple((item.text, (item.anchor,), 1, (index,)) for item in part),
            scope,
            ceiling.max_per_partition,
        )
        per_partition_dropped += dropped
        partial.extend(
            (item.text, item.anchors, item.support, item.partitions) for item in folded
        )
    if per_partition_dropped:
        notes.append(
            f"{per_partition_dropped} partial result(s) were cut by the per-partition "
            f"ceiling of {ceiling.max_per_partition}."
        )

    results, final_dropped = _fold(tuple(partial), scope, ceiling.max_results)
    if final_dropped:
        notes.append(
            f"{final_dropped} aggregated statement(s) were cut by the result ceiling of "
            f"{ceiling.max_results}."
        )
    stages = (
        AggregationStage(
            name="partition",
            inputs=len(statements),
            outputs=sum(len(part) for part in partitions),
            dropped=dropped_partitions,
        ),
        AggregationStage(
            name="fold-partition",
            inputs=sum(len(part) for part in partitions),
            outputs=len(partial),
            dropped=per_partition_dropped,
        ),
        AggregationStage(
            name="fold-final",
            inputs=len(partial),
            outputs=len(results),
            dropped=final_dropped,
        ),
    )
    return AggregationOutcome(
        results=tuple(results),
        stages=stages,
        partition_count=len(partitions),
        notes=tuple(notes),
    )
