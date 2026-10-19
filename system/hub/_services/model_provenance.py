"""Validate a model identifier reported by the current provider response.

This value is provenance metadata, not an assertion about model quality or identity.
Keep this helper independent of LLM backend imports for read-only receipt readers.
"""


def reported_model(value) -> str | None:
    """Return a bounded, literal provider model name or ``None``."""
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    if "://" in value or "www." in value.lower():
        return None
    return value
