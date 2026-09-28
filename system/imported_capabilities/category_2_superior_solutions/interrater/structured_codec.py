"""Lossless cell escaping for the anchored structured-row wire format."""

from __future__ import annotations

import re

_ESCAPED_TOKEN = re.compile(r"%(?:25|E2%88%99)|∙", re.IGNORECASE)


def encode_structured_cell(value: str) -> str:
    """Protect percent signs and the row delimiter without changing the value."""
    return value.replace("%", "%25").replace("∙", "%E2%88%99").replace("·", "∙")


def decode_structured_cell(value: str) -> str:
    """Restore one encoded cell without recursively decoding source text."""

    def restore(match: re.Match[str]) -> str:
        token = match.group(0).casefold()
        if token == "%25":
            return "%"
        if token == "%e2%88%99":
            return "∙"
        return "·"

    return _ESCAPED_TOKEN.sub(restore, value)
