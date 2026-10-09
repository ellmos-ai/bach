"""Small provider-error contract; no provider bodies, URLs or headers escape."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re


def parse_retry_after(value, *, now=None):
    """Accept actual delta-seconds or a timezone-aware HTTP-date header."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]{1,10}", value):
        seconds = int(value)
    else:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            reference = now or datetime.now(timezone.utc)
            seconds = max(0, math.ceil((date - reference).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return None
    return seconds if 0 <= seconds <= 2_147_483_647 else None


def normalize_backend_error(raw):
    """Validate enums/types and regenerate the public message from constants."""
    if not isinstance(raw, dict) or raw.get("provider") != "ollama":
        return None
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in {"http_error", "rate_limited", "quota_exceeded", "provider_error"}:
        return None
    quota = kind == "quota_exceeded"
    if type(raw.get("quota_exceeded")) is not bool or raw["quota_exceeded"] != quota:
        return None
    result = {"provider": "ollama", "kind": kind, "quota_exceeded": quota}
    status = raw.get("status_code")
    if status is not None:
        if type(status) is not int or not 400 <= status <= 599:
            return None
        result["status_code"] = status
    if kind in {"http_error", "rate_limited"} and status is None:
        return None
    if kind == "rate_limited" and status != 429:
        return None
    if quota and raw.get("quota_period") == "month":
        result["quota_period"] = "month"
        message = "Ollama: Monatskontingent erreicht. Kontingent beim Anbieter prüfen."
    elif quota:
        message = "Ollama: Kontingent erreicht. Kontingent beim Anbieter prüfen."
    elif kind == "rate_limited":
        message = "Ollama: Anfragelimit erreicht."
    elif kind == "http_error":
        message = "Ollama: Anfrage vom Anbieter abgelehnt."
    else:
        message = "Ollama meldet einen Fehler."
    if status is not None:
        message += f" HTTP {status}."
    retry = raw.get("retry_after_seconds")
    if type(retry) is int and 0 <= retry <= 2_147_483_647:
        result["retry_after_seconds"] = retry
        message += f" Retry-After: {retry} Sekunden bis zu einem neuen Versuch."
    result["message"] = message
    return result


def classify_ollama_error(payload, *, status_code=None, retry_after=None):
    """Recognize explicit quota evidence without copying arbitrary error text."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        error = error.get("message")
    text = " ".join(error.lower().split()) if isinstance(error, str) else ""
    monthly = status_code in (None, 429) and "monthly usage limit reached" in text
    raw = {"provider": "ollama", "kind": "quota_exceeded" if monthly else (
        "rate_limited" if status_code == 429 else
        "http_error" if status_code is not None else "provider_error"),
        "quota_exceeded": monthly}
    if monthly:
        raw["quota_period"] = "month"
    if status_code is not None:
        raw["status_code"] = status_code
    retry = parse_retry_after(retry_after)
    if retry is not None:
        raw["retry_after_seconds"] = retry
    return normalize_backend_error(raw)


async def read_error_payload(response, *, timeout_seconds):
    """Bound error bodies to 16 KiB and the caller's remaining total budget."""
    import asyncio
    import httpx
    async def read_bounded():
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            if len(data) + len(chunk) > 16_384:
                return None
            data.extend(chunk)
        result = json.loads(data)
        return result if isinstance(result, dict) else None
    try:
        return await asyncio.wait_for(read_bounded(), timeout=timeout_seconds)
    except (ValueError, UnicodeDecodeError, httpx.HTTPError, asyncio.TimeoutError):
        return None
