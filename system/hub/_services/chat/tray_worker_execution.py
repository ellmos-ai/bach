"""Observe one native core worker; persist uncertain starts before HTTP mutation.

The tray holds public correlation metadata only. Task selection, leases,
inference, cooldown counters and completion stay in the native controller.
"""
import json
import os
import threading
import uuid
from pathlib import Path
from urllib.parse import urlencode


WORKER_ID = "buddha_always_on"
_STATES = {"idle", "starting", "running", "stopping", "finishing", "terminal", "unconfirmed"}


def _identifier(value):
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def _execution(value):
    if not isinstance(value, dict):
        return None
    state = value.get("state")
    request_id = value.get("start_request_id")
    generation = value.get("generation")
    started = value.get("worker_thread_started")
    if (value.get("schema") != "bach.worker-execution.v1"
            or value.get("worker_id") != WORKER_ID
            or not _identifier(value.get("service_instance"))
            or not isinstance(state, str) or state not in _STATES
            or type(value.get("terminal")) is not bool
            or value["terminal"] != (state == "terminal")
            or (started is not None and type(started) is not bool)):
        return None
    if request_id is None:
        if generation is not None or state not in {"idle", "unconfirmed"} or started is not None:
            return None
    elif not _identifier(request_id) or not _identifier(generation) or state == "idle":
        return None
    if state in {"running", "finishing"} and started is not True:
        return None
    for key in ("completed_task_ids", "reviewed_task_ids"):
        ids = value.get(key)
        if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids):
            return None
    # Do not retain arbitrary response fields or prompt/task content.
    return {key: value.get(key) for key in ("schema", "service_instance", "worker_id",
        "start_request_id", "generation", "state", "terminal", "worker_thread_started",
        "completed_task_ids", "reviewed_task_ids")}


class NativeWorkerObserver:
    def __init__(self, base_url: str, state_path: Path, request):
        self.base_url = base_url
        self.state_path = Path(state_path)
        self.request = request
        self.intent = None
        self.execution = None
        self.status = "unconfirmed"
        self._loaded = False
        self._blocked = False
        self._lock = threading.Lock()

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                text = handle.read(8193)
            if len(text) > 8192:
                raise ValueError("Oversized intent")
            saved = json.loads(text)
            if (not isinstance(saved, dict) or saved.get("schema") != "bach.tray-intent.v1"
                    or saved.get("base_url") != self.base_url or "intent" not in saved):
                raise ValueError("Invalid intent envelope")
            intent = saved["intent"]
            if intent is not None:
                required = {"worker_id", "service_instance", "start_request_id", "generation"}
                if (not isinstance(intent, dict) or set(intent) not in (required, required | {"stop_requested"})
                        or intent["worker_id"] != WORKER_ID
                        or not _identifier(intent["service_instance"])
                        or not _identifier(intent["start_request_id"])
                        or (intent["generation"] is not None and not _identifier(intent["generation"]))
                        or type(intent.get("stop_requested", False)) is not bool
                        or (intent.get("stop_requested") is True and intent["generation"] is None)):
                    raise ValueError("Invalid intent")
                self.intent = {**intent, "stop_requested": intent.get("stop_requested", False)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self._blocked = True

    def _save(self, intent):
        if intent is not None:
            intent = {**intent, "stop_requested": intent.get("stop_requested", False)}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump({"schema": "bach.tray-intent.v1", "base_url": self.base_url,
                           "intent": intent}, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        self.intent = intent

    def _accept(self, execution):
        intent = self.intent
        if (intent is None or execution is None
                or any(execution[key] != intent[key] for key in
                       ("worker_id", "service_instance", "start_request_id"))
                or (intent["generation"] is not None and execution["generation"] != intent["generation"])):
            self.status = "unconfirmed"
            self.execution = None
            return
        if execution["terminal"]:
            self._save(None)
        elif intent["generation"] is None:
            self._save({**intent, "generation": execution["generation"]})
        self.execution = execution
        self.status = execution["state"]

    def _request_owned_stop(self, requested):
        execution = self.execution
        if (not requested or self.intent is None or execution is None
                or self.intent.get("stop_requested") is True
                or self.intent["generation"] is None
                or execution["state"] not in {"running", "starting", "unconfirmed"}):
            return
        self._save({**self.intent, "stop_requested": True})
        code, result = self.request("POST", "/api/workers/stop", {"id": WORKER_ID,
            "expected_service_instance": self.intent["service_instance"],
            "expected_start_request_id": self.intent["start_request_id"],
            "expected_generation": self.intent["generation"]})
        execution = _execution(result.get("execution")) if isinstance(result, dict) else None
        self._accept(execution if code in {200, 409, 503} else None)

    def step(self, *, allow_start: bool, request_stop: bool = False):
        """One readback or one preflight/start; never resend an uncertain POST."""
        if type(allow_start) is not bool or type(request_stop) is not bool:
            raise ValueError("Worker gates must be booleans")
        with self._lock:
            self._load()
            if self._blocked:
                self.status = "unconfirmed"
                self.execution = None
                return
            try:
                if self.intent is not None:
                    path = "/api/workers/execution?" + urlencode({"id": WORKER_ID,
                        "start_request_id": self.intent["start_request_id"]})
                    code, result = self.request("GET", path)
                    execution = _execution(result.get("execution")) if isinstance(result, dict) else None
                    self._accept(execution if code == 200 and isinstance(result, dict)
                                 and result.get("ok") is True else None)
                    self._request_owned_stop(request_stop)
                    return

                code, result = self.request("GET", "/api/workers/execution?" + urlencode({"id": WORKER_ID}))
                execution = _execution(result.get("execution")) if isinstance(result, dict) else None
                if code != 200 or execution is None or result.get("ok") is not True:
                    self.status = "unconfirmed"
                    self.execution = None
                    return
                self.execution = execution
                self.status = execution["state"]
                if execution["start_request_id"] is not None and not execution["terminal"]:
                    self._save({key: execution[key] for key in
                                ("worker_id", "service_instance", "start_request_id", "generation")})
                    self._request_owned_stop(request_stop)
                    return
                if not allow_start or request_stop or execution["state"] not in {"idle", "terminal"}:
                    return
                self._save({"worker_id": WORKER_ID, "service_instance": execution["service_instance"],
                            "start_request_id": uuid.uuid4().hex, "generation": None})
                self.status = "unconfirmed"
                self.execution = None
                code, result = self.request("POST", "/api/workers/run", {
                    "id": WORKER_ID, "start_request_id": self.intent["start_request_id"],
                    "expected_service_instance": self.intent["service_instance"]})
                execution = _execution(result.get("execution")) if isinstance(result, dict) else None
                admission = result.get("admission") if isinstance(result, dict) else None
                not_admitted = (isinstance(admission, dict) and admission.get("admitted") is False
                    and all(admission.get(key) == self.intent[key] for key in
                            ("worker_id", "service_instance", "start_request_id")))
                # A competing caller can win the controller's reservation. Its
                # definitive 409 denies our start and names the existing run.
                if (code == 409 and not_admitted and execution is not None and not execution["terminal"]
                        and execution["service_instance"] == self.intent["service_instance"]
                        and execution["start_request_id"] != self.intent["start_request_id"]):
                    self._save({key: execution[key] for key in
                                ("worker_id", "service_instance", "start_request_id", "generation")})
                elif code in {403, 404, 409, 503} and not_admitted and execution is None:
                    self._save(None)
                    self.status = "denied"
                    return
                self._accept(execution if code in {200, 202, 400, 409, 503} else None)
            except (OSError, ValueError, TypeError, KeyError):
                # Disk failure or unknown network/protocol outcome cannot clear
                # an intent or authorize another mutation, even after timeout.
                self._blocked = True
                self.status = "unconfirmed"
                self.execution = None
