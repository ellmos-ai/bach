"""Small provider-error contract; no provider bodies, URLs or headers escape."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re


# Error types are allowlisted HTTPX class families, never exception text.
_REQUEST_ERROR_KINDS = {
    "connect_timeout": ("ConnectTimeout", "Zeitüberschreitung beim Verbindungsaufbau"),
    "read_timeout": ("ReadTimeout", "Zeitüberschreitung beim Lesen der Antwort"),
    "write_timeout": ("WriteTimeout", "Zeitüberschreitung beim Senden der Anfrage"),
    "pool_timeout": ("PoolTimeout", "Zeitüberschreitung beim Warten auf eine Verbindung"),
    "transport_timeout": ("TimeoutException", "Zeitüberschreitung beim Transport"),
    "connection_error": ("ConnectError", "Verbindungsaufbau fehlgeschlagen"),
    "transport_error": ("RequestError", "Anfragetransport fehlgeschlagen"),
    "http_error": ("HTTPStatusError", "Anfrage vom Anbieter abgelehnt"),
}


def _normalize_request_error(raw):
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _REQUEST_ERROR_KINDS:
        return None
    error_type, description = _REQUEST_ERROR_KINDS[kind]
    if raw.get("error_type") != error_type or raw.get("quota_exceeded") is not False:
        return None
    status = raw.get("status_code")
    if status is not None and (
        kind != "http_error" or type(status) is not int or not 100 <= status <= 599
    ):
        return None
    provider = raw["provider"]
    result = {"provider": provider, "kind": kind, "error_type": error_type,
              "quota_exceeded": False}
    label = "OpenRouter" if provider == "openrouter" else "Hermes"
    message = f"{label}: {description} ({error_type})."
    if status is not None:
        result["status_code"] = status
        message += f" HTTP {status}."
    retry = raw.get("retry_after_seconds")
    if status in {429, 504} and type(retry) is int and 0 <= retry <= 2_147_483_647:
        result["retry_after_seconds"] = retry
        message += f" Retry-After: {retry} Sekunden bis zu einem neuen Versuch."
    result["message"] = message
    return result


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
    if not isinstance(raw, dict):
        return None
    if raw.get("provider") in ("openrouter", "hermes"):
        return _normalize_request_error(raw)
    if raw.get("provider") != "ollama":
        return None
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in {"http_error", "rate_limited", "quota_exceeded", "provider_error", "tool_parse_error"}:
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
    elif kind == "tool_parse_error":
        message = "Ollama konnte einen Werkzeugaufruf nicht lesen."
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
    # Ollama Cloud words it "you (...) have reached your monthly usage limit".
    monthly = status_code in (None, 429) and "monthly usage limit" in text and "reached" in text
    tool_parse = (not monthly and status_code != 429
                  and "xml syntax error" in text and "<function>" in text
                  and "</parameter>" in text)
    raw = {"provider": "ollama", "kind": "tool_parse_error" if tool_parse else (
        "quota_exceeded" if monthly else (
        "rate_limited" if status_code == 429 else
        "http_error" if status_code is not None else "provider_error")),
        "quota_exceeded": monthly}
    if monthly:
        raw["quota_period"] = "month"
    if status_code is not None:
        raw["status_code"] = status_code
    retry = parse_retry_after(retry_after)
    if retry is not None:
        raw["retry_after_seconds"] = retry
    return normalize_backend_error(raw)


def cloud_call_retry_eligible(detail):
    """Allow typed cloud failures only; the caller must reject partial output."""
    error = normalize_backend_error(detail)
    if not error or error.get("quota_exceeded") is not False:
        return False
    if (error.get("status_code") == 429
            and (error["provider"], error["kind"]) in {
                ("ollama", "rate_limited"), ("openrouter", "http_error")}):
        return True
    if (error["provider"] == "openrouter"
            and error["kind"] == "http_error"
            and error.get("status_code") == 504):
        return True
    return (error["provider"] == "openrouter"
            and error["kind"] in {
                "connect_timeout", "read_timeout", "write_timeout", "pool_timeout",
                "transport_timeout", "connection_error", "transport_error"})


def cloud_call_retry_delay(detail, *, retries, waited_seconds):
    """Bound one call to three retries/900s; transport backs off at 5/10/20s."""
    if (type(retries) is not int or not 0 <= retries < 3
            or type(waited_seconds) not in (int, float)
            or not math.isfinite(waited_seconds) or waited_seconds < 0):
        return None
    error = normalize_backend_error(detail)
    if not cloud_call_retry_eligible(error):
        return None
    base = 60 if error.get("status_code") == 429 else 5
    delay = max(base * (2 ** retries), error.get("retry_after_seconds", 0))
    return delay if waited_seconds + delay <= 900 else None


class BackendRequestFailure(RuntimeError):
    """Safe request failure; RuntimeError preserves the existing fallback policy."""

    def __init__(self, detail):
        safe = normalize_backend_error(detail)
        if safe is None or safe["provider"] not in ("openrouter", "hermes"):
            raise ValueError("Ungültiger Transportfehlervertrag")
        self.backend_error = safe
        if safe["kind"] == "http_error":
            status = safe.get("status_code")
            prefix = f"Hermes/OpenRouter Fehler ({status})" if status is not None else "Hermes/OpenRouter API-Fehler"
        else:
            prefix = f"Hermes/OpenRouter Verbindungsfehler ({safe['error_type']})"
        super().__init__(f"{prefix}: {safe['message']}")

    @classmethod
    def from_httpx(cls, exc, *, provider):
        """Classify only observed typed exceptions; never inspect body/text/URL."""
        import httpx
        if provider not in ("openrouter", "hermes"):
            raise ValueError("Ungültiger Transportfehleranbieter")
        status = None
        if isinstance(exc, httpx.HTTPStatusError):
            kind = "http_error"
            status = exc.response.status_code
        elif isinstance(exc, httpx.ConnectTimeout):
            kind = "connect_timeout"
        elif isinstance(exc, httpx.ReadTimeout):
            kind = "read_timeout"
        elif isinstance(exc, httpx.WriteTimeout):
            kind = "write_timeout"
        elif isinstance(exc, httpx.PoolTimeout):
            kind = "pool_timeout"
        elif isinstance(exc, httpx.TimeoutException):
            kind = "transport_timeout"
        elif isinstance(exc, httpx.ConnectError):
            kind = "connection_error"
        elif isinstance(exc, httpx.RequestError):
            kind = "transport_error"
        else:
            raise TypeError("Nicht unterstützte Transportfehlerklasse")
        detail = {"provider": provider, "kind": kind,
                  "error_type": _REQUEST_ERROR_KINDS[kind][0], "quota_exceeded": False}
        if status is not None:
            detail["status_code"] = status
        if status in {429, 504}:
            retry = parse_retry_after(exc.response.headers.get("retry-after"))
            if retry is not None:
                detail["retry_after_seconds"] = retry
        return cls(detail)


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
