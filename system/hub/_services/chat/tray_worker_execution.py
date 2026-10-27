"""Observe one native core worker; persist uncertain starts before HTTP mutation.

The tray holds public correlation metadata only. Task selection, leases,
inference, cooldown counters and completion stay in the native controller.
"""
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from urllib.parse import urlencode

from hub._services.user_config_store import _exclusive_lock

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
        self._raw_digest = None
        self._lock = threading.Lock()

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self.state_path.read_bytes()
            if len(raw) > 8192:
                raise ValueError("Oversized intent")
            saved = json.loads(raw.decode("utf-8"))
            self._raw_digest = hashlib.sha256(raw).hexdigest()
            schema = saved.get("schema") if isinstance(saved, dict) else None
            fields = ({"schema", "base_url", "intent"} if schema == "bach.tray-intent.v1"
                      else {"schema", "base_url", "intent", "retired_unconfirmed"})
            if (type(schema) is not str
                    or schema not in {"bach.tray-intent.v1", "bach.tray-intent.v2"}
                    or set(saved) != fields or saved.get("base_url") != self.base_url):
                raise ValueError("Invalid intent envelope")
            if schema == "bach.tray-intent.v2" and saved["retired_unconfirmed"] is not None:
                proof = saved["retired_unconfirmed"]
                if (type(proof) is not dict
                        or proof.get("schema") != "bach.tray-intent-reconcile-proof.v1"
                        or proof.get("effect") != "tray_intent_only"
                        or type(proof.get("target_binding")) is not str
                        or proof["target_binding"] not in {"fixed", "guarded_reference"}
                        or proof.get("old_execution_terminal") is not False
                        or not _identifier(proof.get("service_instance"))
                        or not _identifier(proof.get("start_request_id"))
                        or not _identifier(proof.get("current_service_instance"))):
                    raise ValueError("Invalid retirement proof")
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

    def _saved_envelope(self):
        try:
            raw = self.state_path.read_bytes()
        except FileNotFoundError:
            return None, None
        if len(raw) > 8192:
            raise ValueError("Oversized intent")
        saved = json.loads(raw.decode("utf-8"))
        if type(saved) is not dict or saved.get("base_url") != self.base_url:
            raise ValueError("Invalid intent envelope")
        schema = saved.get("schema")
        fields = ({"schema", "base_url", "intent"} if schema == "bach.tray-intent.v1"
                  else {"schema", "base_url", "intent", "retired_unconfirmed"})
        if (type(schema) is not str
                or schema not in {"bach.tray-intent.v1", "bach.tray-intent.v2"}
                or set(saved) != fields):
            raise ValueError("Invalid intent envelope")
        return raw, saved

    def _write_locked(self, intent, retired):
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump({"schema": "bach.tray-intent.v2", "base_url": self.base_url,
                           "intent": intent, "retired_unconfirmed": retired}, handle, ensure_ascii=False)
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
        self._raw_digest = hashlib.sha256(self.state_path.read_bytes()).hexdigest()

    def _save(self, intent):
        if intent is not None:
            intent = {**intent, "stop_requested": intent.get("stop_requested", False)}
        with _exclusive_lock(self.state_path):
            _, saved = self._saved_envelope()
            previous = saved.get("intent") if saved is not None else None
            if isinstance(previous, dict):
                previous = {**previous, "stop_requested": previous.get("stop_requested", False)}
            if previous != self.intent:
                raise ValueError("Tray intent changed by another owner")
            retired = saved.get("retired_unconfirmed") if saved is not None else None
            self._write_locked(intent, retired)

    def retire_unconfirmed(self, *, actor, intent_sha256, target_task_id,
                           target_task_version, mode="retire_unconfirmed"):
        """Explicit operator action; never invoked by the periodic tray step."""
        if (type(actor) is not str or not actor or type(intent_sha256) is not str
                or len(intent_sha256) != 64 or any(c not in "0123456789abcdef" for c in intent_sha256)
                or type(target_task_id) is not int or target_task_id <= 0
                or type(target_task_version) is not str or len(target_task_version) != 64
                or any(c not in "0123456789abcdef" for c in target_task_version)
                or type(mode) is not str
                or mode not in {"retire_unconfirmed", "confirmed_inactive"}):
            raise ValueError("Explicit reconcile inputs required")
        with self._lock, _exclusive_lock(self.state_path):
            self._load()
            raw, saved = self._saved_envelope()
            if (self._blocked or self.intent is None or raw is None
                    or hashlib.sha256(raw).hexdigest() != intent_sha256
                    or saved.get("intent") is None):
                raise ValueError("Tray intent digest or owner changed")
            old = {**saved["intent"], "stop_requested": saved["intent"].get("stop_requested", False)}
            if old != self.intent:
                raise ValueError("Tray intent changed by another owner")
            code, result = self.request("GET", "/api/workers/execution?" + urlencode({"id": WORKER_ID}))
            current = _execution(result.get("execution")) if isinstance(result, dict) else None
            if (code != 200 or not isinstance(result, dict) or result.get("ok") is not True
                    or current is None or current["start_request_id"] is not None
                    or current["state"] != "idle"
                    or current["service_instance"] == old["service_instance"]):
                raise ValueError("Current controller is not idle in a different service epoch")
            request = {"schema": "bach.tray-intent-reconcile-request.v1", "mode": mode,
                       "actor": actor, "worker_id": WORKER_ID,
                       "service_instance": old["service_instance"],
                       "start_request_id": old["start_request_id"],
                       "generation": old["generation"], "intent_sha256": intent_sha256,
                       "expected_current_service_instance": current["service_instance"],
                       "target_task_id": target_task_id, "target_task_version": target_task_version}
            status, reply = self.request("POST", "/api/workers/tray-intent/reconcile", request)
            expected = {"schema": "bach.tray-intent-reconcile-proof.v1",
                        "mode": mode, "actor": actor, "worker_id": WORKER_ID,
                        "service_instance": old["service_instance"],
                        "start_request_id": old["start_request_id"],
                        "generation": old["generation"], "intent_sha256": intent_sha256,
                        "current_service_instance": current["service_instance"],
                        "target_task_id": target_task_id, "target_task_version": target_task_version,
                        "effect": "tray_intent_only", "old_execution_terminal": False}
            proof = reply.get("proof") if type(reply) is dict else None
            if (status != 200 or type(reply) is not dict or reply.get("ok") is not True
                    or type(proof) is not dict
                    or proof.get("target_binding") not in {"fixed", "guarded_reference"}
                    or {key: value for key, value in proof.items() if key != "target_binding"} != expected):
                raise ValueError("Exact controller reconciliation proof missing")
            expected = dict(proof)
            # The server proved no Task result; this CAS retires only these
            # unchanged tray bytes, never an execution, lease or receipt.
            reread, _ = self._saved_envelope()
            if reread != raw:
                raise ValueError("Tray intent changed before retirement")
            code, result = self.request("GET", "/api/workers/execution?" + urlencode({"id": WORKER_ID}))
            final = _execution(result.get("execution")) if isinstance(result, dict) else None
            if (code != 200 or not isinstance(result, dict) or result.get("ok") is not True
                    or final is None or final["service_instance"] != current["service_instance"]
                    or final["state"] != "idle" or final["start_request_id"] is not None):
                raise ValueError("Controller changed before tray intent CAS")
            self._write_locked(None, expected)
            self.execution = None
            self.status = "retired_unconfirmed"
            return expected

    def _refresh_external_retirement(self):
        """Observe a CAS by the explicit operator CLI, never infer a terminal run."""
        if self.intent is None or self._raw_digest is None:
            return False
        try:
            with _exclusive_lock(self.state_path):
                raw, saved = self._saved_envelope()
                if raw is None or hashlib.sha256(raw).hexdigest() == self._raw_digest:
                    return False
                proof = saved.get("retired_unconfirmed")
                old = self.intent
                if (saved.get("schema") != "bach.tray-intent.v2"
                        or saved.get("intent") is not None
                        or type(proof) is not dict
                        or proof.get("schema") != "bach.tray-intent-reconcile-proof.v1"
                        or proof.get("mode") not in {"retire_unconfirmed", "confirmed_inactive"}
                        or proof.get("effect") != "tray_intent_only"
                        or type(proof.get("target_binding")) is not str
                        or proof["target_binding"] not in {"fixed", "guarded_reference"}
                        or proof.get("old_execution_terminal") is not False
                        or proof.get("worker_id") != WORKER_ID
                        or proof.get("service_instance") != old["service_instance"]
                        or proof.get("start_request_id") != old["start_request_id"]
                        or proof.get("generation") != old["generation"]
                        or proof.get("intent_sha256") != self._raw_digest
                        or not _identifier(proof.get("current_service_instance"))
                        or type(proof.get("actor")) is not str or not proof["actor"]):
                    raise ValueError("External tray state is not an exact retirement")
                self.intent = None
                self.execution = None
                self.status = "retired_unconfirmed"
                self._raw_digest = hashlib.sha256(raw).hexdigest()
                self._blocked = False
                return True
        except (OSError, ValueError, TypeError, KeyError):
            self._blocked = True
            self.execution = None
            self.status = "unconfirmed"
            return False

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
            if self._refresh_external_retirement():
                return
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


def main(argv=None):
    """Local operator CLI; inspect is read-only, retire requires Control auth."""
    import argparse
    import sys
    import urllib.error
    import urllib.request
    from urllib.parse import urlsplit

    from hub._services.chat.control_auth import get_control_api_auth_header

    parser = argparse.ArgumentParser(description="Gebundenen BACH-Tray-Intent prüfen oder administrativ zurückziehen")
    parser.add_argument("action", choices=("inspect", "retire"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--actor")
    parser.add_argument("--intent-sha256")
    parser.add_argument("--expected-old-service")
    parser.add_argument("--expected-request")
    parser.add_argument("--target-task-id", type=int)
    parser.add_argument("--target-task-version")
    parser.add_argument("--mode", choices=("retire_unconfirmed", "confirmed_inactive"),
                        default="retire_unconfirmed")
    args = parser.parse_args(argv)
    parsed = urlsplit(args.base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.port != 8081 or parsed.path or parsed.query or parsed.fragment
            or parsed.username is not None or parsed.password is not None):
        parser.error("Nur die lokale Control-API auf Port 8081 ist zulässig")
    path = Path.home() / ".bach" / f"bach_worker_{hashlib.sha256(args.base_url.encode('utf-8')).hexdigest()[:24]}.json"
    try:
        raw = path.read_bytes()
        if len(raw) > 8192:
            raise ValueError("Intent-Datei ist zu groß")
        saved = json.loads(raw.decode("utf-8"))
        if (type(saved) is not dict or saved.get("base_url") != args.base_url
                or saved.get("schema") not in {"bach.tray-intent.v1", "bach.tray-intent.v2"}
                or type(saved.get("intent")) is not dict):
            raise ValueError("Kein gültiger offener Tray-Intent")
        intent = saved["intent"]
        digest = hashlib.sha256(raw).hexdigest()
        if args.action == "inspect":
            print(json.dumps({"schema": saved["schema"], "intent_sha256": digest,
                "service_instance": intent.get("service_instance"),
                "start_request_id": intent.get("start_request_id"),
                "generation": intent.get("generation")}, sort_keys=True))
            return 0
        if (not args.actor or args.intent_sha256 != digest
                or args.expected_old_service != intent.get("service_instance")
                or args.expected_request != intent.get("start_request_id")
                or args.target_task_id is None or not args.target_task_version):
            raise ValueError("Explizite Actor-/Intent-/Taskbindung fehlt oder hat sich geändert")
        authorization = get_control_api_auth_header()
        if not authorization:
            raise ValueError("Control-API-Authentisierung ist nicht verfügbar")

        def request(method, route, body=None):
            payload = None if body is None else json.dumps(body).encode("utf-8")
            headers = {"Authorization": authorization, "Accept": "application/json"}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            call = urllib.request.Request(args.base_url + route, data=payload,
                                          method=method, headers=headers)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(call, timeout=5) as response:
                    return response.status, json.loads(response.read(65537).decode("utf-8"))
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read(65537).decode("utf-8"))

        observer = NativeWorkerObserver(args.base_url, path, request)
        proof = observer.retire_unconfirmed(actor=args.actor, intent_sha256=digest,
            target_task_id=args.target_task_id, target_task_version=args.target_task_version,
            mode=args.mode)
        print(json.dumps({"schema": proof["schema"], "mode": proof["mode"],
            "effect": proof["effect"], "old_execution_terminal": False,
            "intent_sha256": proof["intent_sha256"],
            "target_task_id": proof["target_task_id"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"Tray-Intent nicht abgewickelt: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
