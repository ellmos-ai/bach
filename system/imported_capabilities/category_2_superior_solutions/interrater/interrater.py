"""K8: two independent codings of the same material, and how far they agree.

The use this exists for is a thousand questionnaires nobody wants to code twice
by hand. Two raters code the same items, and what matters is not the average but
the disagreements: those are where the coding scheme is ambiguous, and finding
them is the whole point of running it twice.

Two numbers are reported, never one. Percent agreement is what people expect and
is misleading whenever one code dominates - two raters who assign "other" to
ninety per cent of items agree ninety per cent of the time while telling you
nothing. Cohen's kappa corrects for the agreement chance alone would produce, so
it is reported next to it. Where kappa is undefined - one category used, or one
rater constant - it is reported as undefined with the reason, rather than
printed as a number that would be read as a result.

A rater here can be a model, a run with different settings, or one of the two
deterministic reading strategies below. The diff does not care which: it
compares two codings of the same item set, and says so about itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .primitives import Anchor, anchored_sentences

STRATEGY_FIRST = "first_match"
STRATEGY_LAST = "last_match"
STRATEGIES = (STRATEGY_FIRST, STRATEGY_LAST)
UNCODED = "(uncoded)"
MAX_ITEMS = 5000
MAX_CODES = 40

# Which part of a form to read. A questionnaire says "Wie zufrieden sind Sie?"
# in every stem, so a scheme keyed on that word codes the question rather than
# the answer - on every single form, identically, which looks like agreement.
# The fields to read are therefore declared, like every other vocabulary here.
_LABELLED = re.compile(r"^\s*(?P<label>[^:#]{2,60}?)\s*:\s*(?P<value>\S.*?)\s*$")


@dataclass(frozen=True, slots=True)
class Coding:
    """One rater's answer for every item they saw."""

    rater: str
    codes: dict[str, str]
    anchors: dict[str, Anchor]

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.codes))


@dataclass(frozen=True, slots=True)
class CellDiff:
    item_id: str
    code_a: str
    code_b: str

    @property
    def agree(self) -> bool:
        return self.code_a == self.code_b


@dataclass(frozen=True, slots=True)
class Agreement:
    """Both numbers, and an honest word about the second one."""

    items: int
    agreed: int
    percent: float
    kappa: float | None
    kappa_note: str

    @property
    def disagreed(self) -> int:
        return self.items - self.agreed


@dataclass(frozen=True, slots=True)
class InterraterReport:
    rater_a: str
    rater_b: str
    cells: tuple[CellDiff, ...]
    agreement: Agreement
    only_in_a: tuple[str, ...]
    only_in_b: tuple[str, ...]

    @property
    def disagreements(self) -> tuple[CellDiff, ...]:
        return tuple(cell for cell in self.cells if not cell.agree)


def cohens_kappa(cells: tuple[CellDiff, ...]) -> tuple[float | None, str]:
    """Agreement beyond chance, or a plain statement that it cannot be computed.

    Kappa is undefined when chance agreement is total - one category used, or a
    rater who never varies. Returning 0.0 or 1.0 there would be read as a
    finding about the raters rather than about the arithmetic.
    """
    total = len(cells)
    if total == 0:
        return None, "no item was coded by both raters, so kappa is undefined"
    observed = sum(1 for cell in cells if cell.agree) / total
    codes = {cell.code_a for cell in cells} | {cell.code_b for cell in cells}
    if len(codes) < 2:
        return None, (
            "both raters used a single category, so chance agreement is total and "
            "kappa is undefined"
        )
    expected = 0.0
    for code in codes:
        share_a = sum(1 for cell in cells if cell.code_a == code) / total
        share_b = sum(1 for cell in cells if cell.code_b == code) / total
        expected += share_a * share_b
    if expected >= 1.0:
        return None, (
            "chance agreement is already total for this distribution, so kappa is "
            "undefined"
        )
    return (observed - expected) / (1.0 - expected), ""


def interrater_diff(first: Coding, second: Coding) -> InterraterReport:
    """Compare two codings item by item and report both agreement numbers."""
    shared = sorted(set(first.codes) & set(second.codes))
    cells = tuple(
        CellDiff(item_id=item, code_a=first.codes[item], code_b=second.codes[item])
        for item in shared
    )
    agreed = sum(1 for cell in cells if cell.agree)
    kappa, note = cohens_kappa(cells)
    return InterraterReport(
        rater_a=first.rater,
        rater_b=second.rater,
        cells=cells,
        agreement=Agreement(
            items=len(cells),
            agreed=agreed,
            percent=round(100.0 * agreed / len(cells), 2) if cells else 0.0,
            kappa=round(kappa, 4) if kappa is not None else None,
            kappa_note=note,
        ),
        only_in_a=tuple(sorted(set(first.codes) - set(second.codes))),
        only_in_b=tuple(sorted(set(second.codes) - set(first.codes))),
    )


def validate_codes(value: Any) -> dict[str, tuple[str, ...]]:
    """Read the declared coding scheme: a code and the terms that indicate it."""
    if not isinstance(value, dict) or not value:
        raise ValueError("a coding scheme needs at least one code")
    if len(value) > MAX_CODES:
        raise ValueError(f"a coding scheme may not exceed {MAX_CODES} codes")
    scheme: dict[str, tuple[str, ...]] = {}
    for code, terms in value.items():
        if not isinstance(code, str) or not code.strip():
            raise ValueError("every code needs a name")
        if not isinstance(terms, list) or any(not isinstance(item, str) for item in terms):
            raise ValueError(f"the terms for {code} must be a list of strings")
        cleaned = tuple(item.strip() for item in terms if item.strip())
        if not cleaned:
            raise ValueError(f"the code {code} has no term to look for")
        scheme[code.strip()] = cleaned
    return scheme


def code_corpus(
    source_ids: tuple[str, ...],
    texts: dict[str, str],
    scheme: dict[str, tuple[str, ...]],
    *,
    strategy: str = STRATEGY_FIRST,
    rater: str = "",
    scan_labels: tuple[str, ...] = (),
) -> Coding:
    """Assign one code per source with a declared reading strategy.

    The two strategies are not a trick to manufacture disagreement: reading a
    document for its first indication and reading it for its last are two real
    ways to code a form, and they part company exactly on the documents where a
    coding scheme is ambiguous. That is what a rater race is looking for, and it
    means the machinery can be shown without a model on the machine.

    ``scan_labels`` names which labelled parts to read - "Antwort", "Nachtrag" -
    and is how a scheme avoids coding the question it was asked about. Left
    empty, the whole document is read, which is right for prose and wrong for a
    form whose stem repeats the very word the scheme keys on.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    codes: dict[str, str] = {}
    anchors: dict[str, Anchor] = {}
    for source_id in source_ids[:MAX_ITEMS]:
        text = texts.get(source_id)
        if text is None:
            continue
        hits: list[tuple[str, Anchor]] = []
        for sentence in anchored_sentences(text):
            if scan_labels:
                labelled = _LABELLED.match(sentence.text)
                if labelled is None or not any(
                    label.casefold() == labelled.group("label").strip().casefold()
                    for label in scan_labels
                ):
                    continue
                folded = labelled.group("value").casefold()
            else:
                folded = sentence.text.casefold()
            for code in sorted(scheme):
                if any(term.casefold() in folded for term in scheme[code]):
                    hits.append((code, Anchor(source_id=source_id, line=sentence.line)))
                    break
        if not hits:
            codes[source_id] = UNCODED
            continue
        chosen = hits[0] if strategy == STRATEGY_FIRST else hits[-1]
        codes[source_id] = chosen[0]
        anchors[source_id] = chosen[1]
    return Coding(rater=rater or strategy, codes=codes, anchors=anchors)


def supplied_coding(
    value: Any,
    *,
    rater: str,
    source_ids: tuple[str, ...],
    labels: dict[str, str],
    allowed_codes: set[str],
) -> Coding:
    """Match a separately supplied rating sheet to the exact readable corpus.

    A sheet may use opaque source IDs or unique file names. Missing, foreign, or
    duplicated items are refused so a high agreement cannot hide skipped forms.
    The caller, not this function, is responsible for establishing that two
    sheets really came from independent raters.
    """
    if not isinstance(value, dict) or not value:
        raise ValueError("supplied coding must be a non-empty object")
    if not rater.strip():
        raise ValueError("supplied coding needs a rater name")
    if not source_ids or len(source_ids) > MAX_ITEMS:
        raise ValueError(f"supplied coding needs 1 to {MAX_ITEMS} readable items")
    by_name: dict[str, str] = {}
    for source_id in source_ids:
        name = labels.get(source_id, source_id)
        if name in by_name:
            raise ValueError(f"ambiguous display name in corpus: {name}")
        by_name[name] = source_id
    expected = set(source_ids)
    codes: dict[str, str] = {}
    for item, code in value.items():
        if not isinstance(item, str) or not isinstance(code, str):
            raise ValueError("supplied coding keys and codes must be strings")
        resolved_id = item if item in expected else by_name.get(item)
        if resolved_id is None:
            raise ValueError(f"supplied coding contains an unknown item: {item}")
        if resolved_id in codes:
            raise ValueError(f"supplied coding repeats an item: {item}")
        if code not in allowed_codes and code != UNCODED:
            raise ValueError(f"supplied coding contains an undeclared code: {code}")
        codes[resolved_id] = code
    missing = expected - set(codes)
    if missing:
        raise ValueError(f"supplied coding omits {len(missing)} readable item(s)")
    return Coding(rater=rater.strip(), codes=codes, anchors={})


def interrater_payload(
    report: InterraterReport, labels: dict[str, str] | None = None
) -> dict[str, object]:
    """Render the diff. Labels turn opaque source ids back into file names.

    A cell diff whose first column reads src_4f2845b… is a table nobody can act
    on, so the display name travels with the id rather than replacing it.
    """
    return {
        "schema": "nemofold.interrater.v1",
        "rater_a": report.rater_a,
        "rater_b": report.rater_b,
        "item_count": report.agreement.items,
        "agreed": report.agreement.agreed,
        "disagreed": report.agreement.disagreed,
        "percent_agreement": report.agreement.percent,
        "cohens_kappa": report.agreement.kappa,
        "kappa_note": report.agreement.kappa_note,
        "only_in_a": list(report.only_in_a),
        "only_in_b": list(report.only_in_b),
        "disagreements": [
            {
                "item_id": cell.item_id,
                "display_name": (labels or {}).get(cell.item_id, cell.item_id),
                "code_a": cell.code_a,
                "code_b": cell.code_b,
            }
            for cell in report.disagreements
        ],
        "reading_note": (
            "Percent agreement is misleading whenever one code dominates, which is "
            "why kappa stands next to it. Where kappa is undefined it says so rather "
            "than printing a number that would be read as a result. The disagreements "
            "are the output worth reading: they mark where the coding scheme is "
            "ambiguous, not where a rater was wrong."
        ),
    }


def interrater_rows(
    report: InterraterReport, labels: dict[str, str] | None = None
) -> tuple[tuple[str, ...], ...]:
    """The cell diff as a table, for the workbook export."""
    return tuple(
        (
            (labels or {}).get(cell.item_id, cell.item_id),
            cell.code_a,
            cell.code_b,
            "ja" if cell.agree else "nein",
        )
        for cell in report.cells
    )
