"""Private relay client used by the stdio MCP shim; never retries a call."""
import json
import re
import threading
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import uuid

if __package__:
    from .worker_tool_errors import (
        ToolErrorContractError,
        WorkerToolCallResult,
        transport_error,
        validate_envelope,
    )
else:
    from worker_tool_errors import (
        ToolErrorContractError,
        WorkerToolCallResult,
        transport_error,
        validate_envelope,
    )


_ID = re.compile(r"[0-9a-f]{32}\Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class WorkerToolClient:
    def __init__(self, url, token, generation, task_id):
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}
                or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token)
                or not isinstance(generation, str) or not _ID.fullmatch(generation)
                or type(task_id) is not int or task_id <= 0):
            raise ValueError("Privater Werkzeugtransport ist ungültig")
        self._url = url.rstrip("/")
        self._token = token
        self._generation = generation
        self._task_id = task_id
        self._previous = None
        self._broken = False
        self._lock = threading.RLock()
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    @classmethod
    def from_environment(cls, environment):
        try:
            return cls(environment["BACH_WORKER_TOOL_URL"], environment["BACH_WORKER_TOOL_TOKEN"],
                       environment["BACH_WORKER_TOOL_GENERATION"], int(environment["BACH_WORKER_TOOL_TASK_ID"]))
        except Exception:
            raise ValueError("Privater Werkzeugtransport ist nicht konfiguriert") from None

    def _http(self, path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self._url + path, data=data,
            headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=130) as response:
                raw = response.read(1_000_001)
        except urllib.error.HTTPError as exc:
            if path != "/call" or exc.code != 503:
                raise
            try:
                raw = exc.read(1_000_001)
            finally:
                exc.close()
        if len(raw) > 1_000_000:
            raise ValueError("Werkzeugantwort ist zu groß")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Werkzeugantwort ist ungültig")
        return result

    def tools(self):
        with self._lock:
            if self._broken:
                raise RuntimeError("Werkzeugtransport ist nicht mehr bestätigt")
            try:
                result = self._http("/tools")
                tools = result["tools"]
                if not isinstance(tools, list) or len(tools) > 200:
                    raise ValueError()
                for tool in tools:
                    function = tool["function"]
                    if (not isinstance(function["name"], str) or not isinstance(function["parameters"], dict)
                            or not isinstance(function.get("description", ""), str)):
                        raise ValueError()
                return tools
            except Exception:
                self._broken = True
                raise RuntimeError("Werkzeugtransport konnte nicht bestätigt werden") from None

    def call_detailed(self, name, arguments):
        """Return the v1 error envelope when available; never retries a call or ACK."""
        with self._lock:
            request_id = uuid.uuid4().hex
            base_correlation = {"request_id": request_id, "generation": self._generation,
                                "task_id": self._task_id, "receipt_id": None}
            if self._broken:
                error = transport_error("transport_response_unconfirmed", base_correlation)
                return WorkerToolCallResult(
                    "Werkzeugtransport nicht bestätigt; keine Wiederholung", True, error, True)
            try:
                result = self._http("/call", {"request_id": request_id,
                    "previous_receipt": self._previous, "name": name, "arguments": arguments})
            except Exception:  # noqa: BLE001 -- Transport failure is an unknown result; never retry or expose details.
                self._broken = True
                error = transport_error("transport_response_unconfirmed", base_correlation)
                return WorkerToolCallResult(
                    "Werkzeugaufruf nicht bestätigt; keine Wiederholung", True, error, True)
            receipt_id = result.get("receipt_id") if isinstance(result, dict) else None
            quarantined = isinstance(result, dict) and result.get("quarantined") is True
            correlation = {**base_correlation, "receipt_id": None}
            try:
                if not isinstance(result, dict):
                    raise ToolErrorContractError("Werkzeugantwort ist ungültig")
                has_error = "error" in result
                expected_keys = {"request_id", "receipt_id", "generation", "task_id", "result", "is_error"}
                if has_error:
                    expected_keys.add("error")
                if quarantined:
                    expected_keys.add("quarantined")
                if set(result) != expected_keys:
                    raise ToolErrorContractError("Werkzeugantwort hat unbekannte Felder")
                if (result.get("request_id") != request_id or result.get("generation") != self._generation
                        or type(result.get("task_id")) is not int or result["task_id"] != self._task_id
                        or not isinstance(result.get("result"), str) or type(result.get("is_error")) is not bool):
                    raise ToolErrorContractError("Werkzeugantwort passt nicht zum aktuellen Aufruf")
                if quarantined:
                    if receipt_id is not None or result.get("error") is None:
                        raise ToolErrorContractError("Quarantäne hat keine bestätigte Fehlerkorrelation")
                else:
                    if not isinstance(receipt_id, str) or not _ID.fullmatch(receipt_id):
                        raise ToolErrorContractError("Receipt wurde nicht bestätigt")
                    correlation = {**base_correlation, "receipt_id": receipt_id}
                error = validate_envelope(result["error"], expected_correlation=correlation) if has_error else None
                if result["is_error"] is not has_error:
                    raise ToolErrorContractError("Fehlerstatus passt nicht zum Fehlervertrag")
                if quarantined:
                    if error is None or error["effect_state"] not in {"unknown", "not_started"}:
                        raise ToolErrorContractError("Quarantäne ist nicht durch den Fehlervertrag belegt")
                elif error is not None and error["effect_state"] == "unknown":
                    raise ToolErrorContractError("Unbekannte Wirkung wurde nicht quarantänisiert")
            except Exception:  # noqa: BLE001 -- Invalid transport payload is quarantined without parsing exceptions.
                self._broken = True
                correlation = {**base_correlation, "receipt_id": None}
                error = transport_error("transport_response_invalid", correlation)
                return WorkerToolCallResult(
                    "Werkzeugantwort nicht bestätigt; keine Wiederholung", True, error, True)
            if quarantined:
                self._broken = True
                return WorkerToolCallResult(result["result"], True, error, True)
            try:
                acknowledgement = self._http("/ack", {"request_id": request_id, "receipt_id": receipt_id})
                if (not isinstance(acknowledgement, dict)
                        or set(acknowledgement) != {"acknowledged", "receipt_id"}
                        or acknowledgement.get("acknowledged") is not True
                        or acknowledgement.get("receipt_id") != receipt_id):
                    raise ToolErrorContractError("Werkzeug-ACK passt nicht zum Aufruf")
            except Exception:
                self._broken = True
                error = transport_error("transport_ack_unconfirmed", correlation)
                return WorkerToolCallResult(
                    "Werkzeug-ACK nicht bestätigt; keine Wiederholung", True, error, True)
            self._previous = receipt_id
            return WorkerToolCallResult(result["result"], has_error, error, False)

    def call(self, name, arguments):
        """Legacy tuple API; unknown or quarantined outcomes still raise once."""
        outcome = self.call_detailed(name, arguments)
        if outcome.quarantined:
            raise RuntimeError("Werkzeugaufruf nicht bestätigt; keine Wiederholung") from None
        return outcome.result, outcome.is_error
