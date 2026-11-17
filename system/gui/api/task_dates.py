"""Calendar projections for task lists; never reinterpret legacy timestamps.

Task sources historically wrote both naive UTC and naive host-local values.
These read-only views use each timestamp's recorded calendar fields, including
an explicit offset's recorded day. They neither migrate rows nor infer a zone.
"""
from __future__ import annotations

from datetime import date, datetime
import re

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_STAMP = re.compile(
    r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:(?:T| )(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})"
    r"(?::(?P<second>[0-9]{2})(?:\.(?P<fraction>[0-9]{1,9}))?)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})?)?\Z"
)
SORTS = frozenset({"priority", "created_desc", "created_asc"})


def validate_task_date_filters(created_from, created_to, sort):
    """Validate query fields before any database connection is opened."""
    normalized = []
    for value in (created_from, created_to):
        value = "" if value is None else value.strip()
        if value:
            try:
                if not _DATE.fullmatch(value):
                    raise ValueError
                date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Ungültiges Datum. Erwartet: YYYY-MM-DD.") from exc
        normalized.append(value)
    lower, upper = normalized
    if lower and upper and lower > upper:
        raise ValueError("Ungültiger Zeitraum: Das Von-Datum liegt nach dem Bis-Datum.")
    if sort not in SORTS:
        raise ValueError("Ungültige Task-Sortierung.")
    return lower, upper, sort


def _recorded_timestamp(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = _STAMP.fullmatch(value)
    if not match:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return match


def task_created_day(value):
    """Return the recorded YYYY-MM-DD, or NULL for unknown/invalid values."""
    match = _recorded_timestamp(value)
    return match.group("day") if match else None


def task_created_sort_key(value):
    """Normalize separators/fractions without converting any recorded timezone."""
    match = _recorded_timestamp(value)
    if not match:
        return None
    return (
        match.group("day") + "T"
        + (match.group("hour") or "00") + ":"
        + (match.group("minute") or "00") + ":"
        + (match.group("second") or "00") + "."
        + (match.group("fraction") or "").ljust(9, "0")
    )
