"""One direct decomposition request for a specific run and task version."""
import copy
from datetime import datetime, timezone
import threading
import uuid


class WorkerTaskActions:
    def __init__(self, worker_id, generation):
        self.worker_id = worker_id
        self.generation = generation
        self._lock = threading.RLock()
        self._receipt = None
        self._closed = False
        self._binding = None

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._receipt)

    def _check_binding(self, binding):
        if self._closed or binding is None or binding is not self._binding or binding.generation != self.generation:
            raise ValueError("Workerlauf ist nicht mehr aktuell")
        try:
            binding.assert_active()
        except Exception as exc:
            raise ValueError("Aktuelle Taskbindung fehlt") from exc
        if self._receipt and (binding.task_id != self._receipt["task_id"] or
                              binding.task_snapshot()["task_version"] != self._receipt["task_version"]):
            raise ValueError("Auftrag wurde seit der Anfrage geändert")

    def request(self, generation, task_id, task_version, binding):
        with self._lock:
            if generation != self.generation or self._closed:
                raise ValueError("Workerlauf ist nicht mehr aktuell")
            if self._receipt and self._receipt["state"] in {"pending", "running"}:
                raise ValueError("Zerlegung ist bereits angefordert")
            if binding is None or binding.generation != generation:
                raise ValueError("Aktuelle Taskbindung fehlt")
            try:
                binding.assert_active()
            except Exception as exc:
                raise ValueError("Aktuelle Taskbindung fehlt") from exc
            if (type(task_id) is not int or task_id != binding.task_id
                    or task_version != binding.task_snapshot()["task_version"]):
                raise ValueError("Task-ID oder Inhaltsversion ist nicht mehr aktuell")
            self._receipt = {
                "kind": "worker-decompose", "worker_id": self.worker_id,
                "generation": generation, "task_id": task_id, "task_version": task_version,
                "request_id": uuid.uuid4().hex, "state": "pending",
                "requested_at": datetime.now(timezone.utc).isoformat(), "confirmed_at": None,
            }
            self._binding = binding
            return self.snapshot()

    def validate(self, binding):
        with self._lock:
            if self._closed:
                raise ValueError("Workerlauf beendet")
            if self._receipt and self._receipt["state"] in {"pending", "running"}:
                try:
                    self._check_binding(binding)
                except ValueError:
                    self._receipt["state"] = "error"
                    raise

    def consume(self, binding, *, backend, model):
        with self._lock:
            if self._closed:
                raise ValueError("Workerlauf beendet")
            if not self._receipt or self._receipt["state"] not in {"pending", "running"}:
                return None
            self.validate(binding)
            if self._receipt["state"] == "running":
                return None
            self._receipt.update(state="running", backend=backend, model=model)
            return self.instruction()

    def instruction(self):
        with self._lock:
            if self._closed or not self._receipt or self._receipt["state"] != "running":
                return None
            return (f"[ZERLEGUNG ANGEFORDERT · Task #{self._receipt['task_id']} · Anfrage {self._receipt['request_id']}]\n"
                    "Zerlege ausschließlich diesen Auftrag mit task_manage(action='decompose', close_parent=false) "
                    "in konkrete, ausführbare Teilaufgaben. Nutze den vorhandenen Kontext und die aktuelle Rolle. "
                    "Die Teilaufgabenanlage bestätigt nur die Zerlegung. Gib danach den Plan mit "
                    "task_manage(action='submit_result', task_id=<ID>, result='<Plan, Kind-IDs, offene Arbeit>') "
                    "zur getrennten Review-Abnahme ab.")

    def confirm(self, binding):
        with self._lock:
            if self._closed or not self._receipt or self._receipt["state"] != "running":
                return False
            proof = binding.decomposition_receipt if binding is not None else None
            if (not proof or binding is not self._binding or binding.generation != self.generation
                    or proof["task_id"] != self._receipt["task_id"]
                    or proof["previous_version"] != self._receipt["task_version"]):
                return False
            self._receipt.update(state="confirmed", created_ids=list(proof["created_ids"]),
                                 parent_closed=proof["parent_closed"],
                                 confirmed_at=datetime.now(timezone.utc).isoformat())
            return True

    def end_block(self):
        with self._lock:
            if self._receipt and self._receipt["state"] == "running":
                self._receipt["state"] = "error"

    def cancel(self):
        with self._lock:
            self._closed = True
            if self._receipt and self._receipt["state"] in {"pending", "running"}:
                self._receipt["state"] = "cancelled"
