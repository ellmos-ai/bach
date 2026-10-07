"""Private relay client used by the stdio MCP shim; never retries a call."""
import json
import re
import threading
from urllib.parse import urlsplit
import urllib.request
import uuid


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
        with self._opener.open(request, timeout=130) as response:
            raw = response.read(1_000_001)
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

    def call(self, name, arguments):
        with self._lock:
            if self._broken:
                raise RuntimeError("Werkzeugtransport ist nicht mehr bestätigt")
            request_id = uuid.uuid4().hex
            try:
                result = self._http("/call", {"request_id": request_id,
                    "previous_receipt": self._previous, "name": name, "arguments": arguments})
                if (result.get("request_id") != request_id or result.get("generation") != self._generation
                        or type(result.get("task_id")) is not int or result["task_id"] != self._task_id
                        or not isinstance(result.get("receipt_id"), str) or not _ID.fullmatch(result["receipt_id"])
                        or not isinstance(result.get("result"), str) or type(result.get("is_error")) is not bool):
                    raise ValueError()
                receipt_id = result["receipt_id"]
                acknowledgement = self._http("/ack", {"request_id": request_id, "receipt_id": receipt_id})
                if acknowledgement.get("acknowledged") is not True or acknowledgement.get("receipt_id") != receipt_id:
                    raise ValueError()
                self._previous = receipt_id
                return result["result"], result["is_error"]
            except Exception:
                self._broken = True
                raise RuntimeError("Werkzeugaufruf nicht bestätigt; keine Wiederholung") from None
