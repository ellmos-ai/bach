"""Private generation-bound authority for one native worker's actual task.

This object never belongs in a transcript, public slot, or provider request.
Only canonical content snapshots and confirmed receipt strings leave it.
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone

from hub._services.task_lease_client import (
    LeaseError, LeaseDeniedError, LeaseMaxTotalReachedError, LeaseProtocolError,
    LeaseReleaseAck,
)


class _TaskDoesNotMatch(LeaseProtocolError):
    """A candidate's fresh content no longer fits this worker."""


class WorkerLeaseBinding:
    def __init__(self, client, snapshot, ack, *, generation, is_current, stop_event, clock=None, policy_guard=None):
        self._client = client
        self._snapshot = copy.deepcopy(snapshot)
        self._ack = ack
        self._generation = generation
        self._is_current = is_current
        self._stop_event = stop_event
        self._policy_guard = policy_guard
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._injected_clock = clock is not None
        self._lock = threading.RLock()
        self._active = True
        self._closed = False
        self._completed = False
        self._completion_result = None
        self._review_ack = None
        self._renew_exhausted = False
        self._decomposition_receipt = None

    @classmethod
    def acquire(cls, client, task_id, *, worker_id, host, generation, is_current,
                stop_event, clock=None, slot=None, automatic=False, policy_guard=None, _creator_delegation=None,
                deferred_versions=None):
        if not generation or not is_current() or stop_event.is_set():
            raise LeaseProtocolError("Workerlauf ist nicht mehr aktiv")
        if policy_guard is not None:
            policy_guard()
        snapshot = client.task_snapshot(task_id)
        if automatic and (deferred_versions or {}).get(task_id) == snapshot["task_version"]:
            raise _TaskDoesNotMatch("Zurückgegebene Task-Version wartet auf eine Inhaltsänderung")
        matches = cls._automatic_matches_slot if automatic else cls._matches_slot
        if slot is not None and not matches(snapshot, slot):
            raise _TaskDoesNotMatch("Task passt nicht zur aktuellen Workerbesetzung")
        kwargs = {"now": clock()} if clock is not None else {}
        if _creator_delegation is None:
            ack = client.acquire(task_id, worker_id=worker_id, host=host,
                                 task_version=snapshot["task_version"], **kwargs)
        else:
            if (_creator_delegation.task_id != task_id or _creator_delegation.generation != generation
                    or _creator_delegation.worker_id != worker_id or _creator_delegation.host != host):
                raise LeaseProtocolError("Creator-Delegation gehört nicht zu dieser privaten Workergeneration")
            ack = client._acquire_native_creator(task_id, delegation=_creator_delegation,
                worker_id=worker_id, host=host, task_version=snapshot["task_version"], **kwargs)
        return cls(client, snapshot, ack, generation=generation, is_current=is_current,
                   stop_event=stop_event, clock=clock, policy_guard=policy_guard)

    @staticmethod
    def _matches_slot(snapshot, slot):
        from .slots_config import task_matches_slot_binding, match_task_to_pickup_filter
        if not task_matches_slot_binding(snapshot, slot):
            return False
        pickup = slot.get("pickup_filter")
        return (not isinstance(pickup, dict) or not pickup.get("enabled")
                or match_task_to_pickup_filter(snapshot, slot))

    @classmethod
    def _automatic_matches_slot(cls, snapshot, slot):
        if not cls._matches_slot(snapshot, slot):
            return False
        pickup = slot.get("pickup_filter")
        # Explicit routing/filter configuration may select a human-created
        # task. A generic backlog scan has no such ownership instruction.
        if snapshot.get("assigned_slot") or (isinstance(pickup, dict) and pickup.get("enabled")):
            return True
        allowed = {"bach", "buddha", "ollama"}
        allowed.update(str(slot.get(key) or "").strip().casefold()
                       for key in ("id", "role_id", "sub_mode"))
        allowed.discard("")
        return str(snapshot.get("assigned_to") or "").strip().casefold() in allowed

    @classmethod
    def acquire_next(cls, client, slot, **kwargs):
        """Acquire the actual configured/next canonical task before any inference."""
        explicit = slot.get("task_id")
        if explicit not in (None, "", 0, "0"):
            if isinstance(explicit, str) and explicit.isdecimal():
                explicit = int(explicit)
            return cls.acquire(client, explicit, slot=slot, **kwargs)
        if kwargs.get("_creator_delegation") is not None:
            raise LeaseProtocolError("Creator-Delegation braucht die explizit gebundene Sequenz-Task")
        offset = 0
        while True:
            if not kwargs["is_current"]() or kwargs["stop_event"].is_set():
                raise LeaseProtocolError("Workerlauf ist nicht mehr aktiv")
            page = client.task_candidates(limit=100, offset=offset)
            for task in page["tasks"]:
                if not cls._automatic_matches_slot(task, slot):
                    continue
                try:
                    return cls.acquire(client, task["id"], slot=slot, automatic=True, **kwargs)
                except _TaskDoesNotMatch:
                    continue
                except LeaseDeniedError as exc:
                    if exc.reason not in {"held", "not_claimable", "creator_priority",
                                           "stale_task_version", "already_held_by_caller"}:
                        raise
            if not page["has_more"]:
                return None
            if not page["tasks"]:
                raise LeaseProtocolError("Kanonische Task-Seite hat keinen Fortschritt")
            offset += 100

    @property
    def generation(self):
        return self._generation

    @property
    def decomposition_receipt(self):
        with self._lock:
            if not self._is_current() or self._stop_event.is_set():
                return None
            return copy.deepcopy(self._decomposition_receipt)

    @property
    def task_id(self):
        return self._ack.task_id

    @property
    def closed(self):
        with self._lock:
            return self._closed

    @property
    def completed_task_ids(self):
        with self._lock:
            return (self.task_id,) if self._completed else ()

    @property
    def completion_result(self):
        """Actual model output, retained only after a correlated Done ACK."""
        with self._lock:
            return copy.deepcopy(self._completion_result) if self._completed else None

    @property
    def reviewed_task_ids(self):
        """Only a correlated typed canonical Review Release ACK is evidence."""
        with self._lock:
            ack = self._review_ack
            if isinstance(ack, LeaseReleaseAck) and ack.task_id == self.task_id and ack.outcome == "review" and ack.status == "review":
                return (self.task_id,)
            return ()

    def task_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def _assert_authority_active(self):
        with self._lock:
            if not self._active or self._closed or not self._is_current() or self._stop_event.is_set():
                raise LeaseProtocolError("Taskbindung oder Workerlauf ist nicht mehr aktiv")
            self._ack.assert_locally_valid(now=self._clock())

    def assert_active(self):
        with self._lock:
            self._assert_authority_active()
            if self._policy_guard is not None:
                try:
                    self._policy_guard()
                except Exception:
                    # A known local policy change does not make the last
                    # confirmed lease ambiguous: owned Return remains allowed.
                    raise LeaseProtocolError("Worker-Konfiguration ist nicht mehr zugelassen") from None

    def _ref(self):
        args = {"lease_id": self._ack.lease_id, "fence": self._ack.fence,
                "task_version": self._snapshot["task_version"]}
        # Production authority samples its live clock under the write lock.
        if self._injected_clock:
            args["now"] = self._clock()
        return args

    def _operation(self, function, *, keep_max_total=False, check_policy=True, **kwargs):
        if check_policy:
            self.assert_active()
        try:
            return function(self.task_id, **self._ref(), **kwargs)
        except LeaseError as exc:
            if keep_max_total and isinstance(exc, LeaseMaxTotalReachedError):
                # Known denial: the last confirmed lease still owns its
                # remaining lifetime. No ACK, deadline or version is guessed.
                raise
            # A missing/malformed ACK may follow a committed operation.
            # Revoke locally; never guess a new version or retry this mutation.
            self._active = False
            raise
        except Exception:
            self._active = False
            raise LeaseProtocolError("Taskoperation fehlgeschlagen; Bestätigung fehlt") from None

    def renew(self):
        with self._lock:
            self._assert_authority_active()
            if self._renew_exhausted:
                return False
            try:
                self._ack = self._operation(self._client.renew, keep_max_total=True, check_policy=False)
            except LeaseMaxTotalReachedError:
                self._renew_exhausted = True
                return False
            return True

    @property
    def stop_requested(self):
        return self._stop_event.is_set()

    def invalidate(self):
        with self._lock:
            self._active = False

    def heartbeat(self, *, renew_due=False):
        with self._lock:
            self._assert_authority_active()
            remaining = (self._ack.local_deadline - self._clock()).total_seconds()
            if renew_due or remaining <= 120:
                return self.renew()
            return False

    def return_lease(self):
        """Cleanup may return a stopped worker's known lease; ambiguity forbids it."""
        with self._lock:
            if not self._active or self._closed or not self._is_current():
                return False
            try:
                self._operation(self._client.release, outcome="return", check_policy=False)
            except LeaseError:
                return False
            self._closed = True
            self._active = False
            return True

    def execute_task_command(self, operation, arguments):
        from .bound_task_command import bound_task_command
        with self._lock:
            self.assert_active()
            return bound_task_command(operation, arguments, self)

    def record_worktree_result(self, task_id, annotation, *, review=False, result_ref=""):
        """Fence a Git result's content; review releases ownership without Done."""
        with self._lock:
            self.assert_active()
            if type(task_id) is not int or task_id != self.task_id or not isinstance(annotation, str) or not annotation:
                raise LeaseProtocolError("Worktree-Ergebnis gehört nicht zur gebundenen Task")
            if review:
                import re
                if not isinstance(result_ref, str) or not re.fullmatch(
                        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", result_ref):
                    raise LeaseProtocolError("Bestätigte PR-Referenz fehlt")
            previous = self._snapshot.get("description") or ""
            description = str(previous) + ("\n\n" if previous else "") + annotation
            ack = self._operation(self._client.update, changes={"description": description})
            self._snapshot.update(description=description, task_version=ack.task_version)
            if review:
                release = self._operation(self._client.release, outcome="review", result_ref=result_ref)
                if (not isinstance(release, LeaseReleaseAck) or release.released is not True
                        or type(release.task_id) is not int or type(release.fence) is not int
                        or type(release.task_id) is not int or release.task_id != self.task_id
                        or type(release.fence) is not int or release.fence != self._ack.fence
                        or release.outcome != "review" or release.status != "review"):
                    self.invalidate()
                    raise LeaseProtocolError("Review-Freigabe nicht bestätigt")
                self._review_ack = release
                self._closed = True
                self._active = False
            return True

    def execute_task_manage(self, args):
        with self._lock:
            self.assert_active()
            if not isinstance(args, dict):
                raise LeaseProtocolError("Ungültige Task-Werkzeugargumente")
            action = args.get("action", "list")
            if action == "list":
                page = self._client.task_candidates(limit=20)
                return "\n".join(f"[{task['id']}] {task.get('priority', '')} "
                                 f"{task.get('status', '')}: {task.get('title', '')}"
                                 for task in page["tasks"]) or "Keine offenen Tasks."
            if action == "detail":
                snapshot = self._client.task_snapshot(args.get("task_id"))
                return "\n".join(f"{key}: {value}" for key, value in snapshot.items())
            if action != "add" and (type(args.get("task_id")) is not int
                                    or args["task_id"] != self.task_id):
                raise LeaseProtocolError("Mutation gehört nicht zur gebundenen Task")
            if action == "done":
                if set(args) - {"action", "task_id", "result"}:
                    raise LeaseProtocolError("Unbekannte Abschlussfelder")
                result = args.get("result")
                record = None
                note = ""
                if result is not None:
                    if (not isinstance(result, str) or not result.strip()
                            or len(result) > 3000 or "\x00" in result):
                        raise LeaseProtocolError("Ergebnis muss lesbarer Text mit höchstens 3000 Zeichen sein")
                    record = {"schema": "bach.task-result.v1", "task_id": self.task_id,
                              "generation": self._generation, "result": result}
                    note = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    if len(note) > 4000:
                        raise LeaseProtocolError("Kodiertes Ergebnis überschreitet das Task-Historienbudget")
                release = self._operation(self._client.release, outcome="done", note=note)
                if (not isinstance(release, LeaseReleaseAck) or release.released is not True
                        or release.task_id != self.task_id or release.fence != self._ack.fence
                        or release.outcome != "done" or release.status != "done"):
                    self.invalidate()
                    raise LeaseProtocolError("Taskabschluss nicht bestätigt")
                self._completion_result = record
                self._closed = self._completed = True
                self._active = False
                return f"Task #{self.task_id} erledigt."
            if action == "update":
                allowed = {"title", "description", "category", "priority", "depends_on",
                           "assigned_to", "required_model", "assigned_slot", "status"}
                if set(args) - allowed - {"action", "task_id"}:
                    raise LeaseProtocolError("Unbekannte Task-Inhaltsfelder")
                changes = {key: value for key, value in args.items() if key in allowed}
                if "status" in changes:
                    outcomes = {"done": "done", "completed": "done", "pending": "return",
                                "open": "return", "blocked": "blocked"}
                    if len(changes) != 1 or changes["status"] not in outcomes:
                        raise LeaseProtocolError("Statuswechsel braucht einen eigenständigen Lease-Abschluss")
                    outcome = outcomes[changes["status"]]
                    self._operation(self._client.release, outcome=outcome)
                    self._closed = True
                    self._completed = outcome == "done"
                    self._active = False
                else:
                    ack = self._operation(self._client.update, changes=changes)
                    self._snapshot.update(changes)
                    self._snapshot["task_version"] = ack.task_version
                return f"Task #{self.task_id} aktualisiert: {', '.join(changes)}"
            if action in {"decompose", "add"}:
                if action == "add":
                    fields = {"title", "description", "priority", "depends_on", "assigned_to",
                              "category", "required_model", "assigned_slot"}
                    if set(args) - fields - {"action"}:
                        raise LeaseProtocolError("Unbekannte Teilaufgabenfelder")
                    subtasks = [{key: value for key, value in args.items() if key in fields}]
                    close_parent = False
                else:
                    allowed = {"action", "task_id", "subtasks", "close_parent", "sequential",
                               "category", "assigned_to", "assigned_slot", "required_model"}
                    if set(args) - allowed:
                        raise LeaseProtocolError("Unbekannte Zerlegungsfelder")
                    subtasks = args.get("subtasks")
                    close_parent = args.get("close_parent", True)
                    if isinstance(subtasks, list):
                        subtasks = [{**{key: args[key] for key in ("category", "assigned_to", "assigned_slot", "required_model")
                                       if key in args}, **item} if isinstance(item, dict) else item
                                    for item in subtasks]
                previous_version = self._snapshot["task_version"]
                ack = self._operation(self._client.decompose, subtasks=subtasks,
                                      close_parent=close_parent, sequential=args.get("sequential", False))
                if action == "decompose":
                    self._decomposition_receipt = {
                        "task_id": self.task_id, "previous_version": previous_version,
                        "created_ids": tuple(ack.created_ids), "parent_closed": ack.parent_closed,
                    }
                self._snapshot["task_version"] = ack.task_version
                self._snapshot["description"] = (self._snapshot.get("description") or "") + (
                    f"\n[In {ack.created_count} Teilaufgaben zerlegt: {list(ack.created_ids)}]")
                if ack.parent_closed:
                    self._closed = self._completed = True
                    self._active = False
                if action == "add":
                    return f"Task #{ack.created_ids[0]} erstellt: {subtasks[0]['title']}"
                return (f"Task #{self.task_id} in {ack.created_count} Teilaufgaben zerlegt: "
                        f"IDs {list(ack.created_ids)}")
            raise LeaseProtocolError("Unbekannte Task-Aktion")
