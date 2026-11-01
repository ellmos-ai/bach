"""Private generation-bound authority for one native worker's actual task.

This object never belongs in a transcript, public slot, or provider request.
Only canonical content snapshots and confirmed receipt strings leave it.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import logging
import re
import threading
from datetime import datetime, timezone

from hub._services.task_lease_client import (
    LeaseError, LeaseDeniedError, LeaseMaxTotalReachedError, LeaseProtocolError,
    LeaseRequestRejectedError, LeaseSelfCheckRequiredError,
    LeaseReleaseAck, WorkerResultAck,
)

log = logging.getLogger("bach.chat")

_EXTERNAL_PROFILE_BACKENDS = frozenset({"openrouter", "ollama-cloud"})
_REPOSITORY_REJECTIONS = frozenset({"repository_capability_missing", "repository_unverified",
                                    "repository_not_allowed", "repository_changed"})


def _external_profile_backend(slot):
    """Return the canonical cloud profile backend, including Ollama's :cloud alias."""
    if not isinstance(slot, dict):
        return None
    backend = str(slot.get("backend") or "").strip().casefold()
    model = str(slot.get("model") or "").strip().casefold()
    if backend in _EXTERNAL_PROFILE_BACKENDS:
        return backend
    if backend == "ollama" and model.endswith(":cloud"):
        return "ollama-cloud"
    return None


class _TaskDoesNotMatch(LeaseProtocolError):
    """A candidate's fresh content no longer fits this worker."""

    def __init__(self, message, *, reason="changed_selection"):
        self.reason = reason
        super().__init__(message)


class WorkerResultLimitLockedError(LeaseProtocolError):
    """A worker may keep or tighten, but never loosen, its result limit."""

    user_message = "Das Task-Ausgabelimit darf von einem Worker nicht gelockert werden."


class WorkerSubmissionScopeError(LeaseProtocolError):
    """A known pre-submit scope denial; keep the current lease and work."""

    _REASONS = {
        "git_dirty": "Der registrierte Taskarbeitsbaum enthält ungesicherte Änderungen.",
        "source_pin_invalid": "Der registrierte Sourcepin ist nicht bestätigt.",
        "source_pin_missing": "Der öffentliche Sourcepin fehlt.",
        "repository_binding_missing": "Die erforderliche Repo-Bindung fehlt.",
        "task_contract_invalid": "Der kanonische Taskvertrag ist ungültig.",
        "registry_unavailable": "Die Repo-Registry ist nicht bestätigt.",
        "task_version_changed": "Die Taskversion änderte sich während der Scopeprüfung.",
        "scope_unavailable": "Der registrierte Taskscope ist nicht bestätigt.",
    }

    def __init__(self, reason):
        self.reason = reason if reason in self._REASONS else "scope_unavailable"
        self.user_message = (self._REASONS[self.reason] +
            " Keine Ergebnisabgabe; Lease und Arbeitsstand bleiben erhalten. "
            "Nur laut Task erlaubte Sicherungsschritte nutzen, keinen verbotenen Push. "
            "Offenen Teilstand mit complete=false zurückgeben.")
        super().__init__(self.user_message)

class WorkerTaskManageArgumentError(LeaseProtocolError):
    """Only a locally checked tool shape, never an SDK or ownership denial."""

    _GUIDANCE = {
        "list_fields": 'Für task_manage(action="list") nur action angeben; task_id weglassen.',
        "update_fields": 'Für update nur unterstützte Taskfelder wie description oder status angeben; Ergebnis mit submit_result und complete=true abgeben.',
        "update_result": 'Ergebnis getrennt mit task_manage(action="submit_result", task_id=<ID>, result=<Text>, complete=true) abgeben.',
        "update_status": 'Status allein ändern: task_manage(action="update", task_id=<ID>, status=<pending|open|blocked>); Inhaltsfelder separat aktualisieren.',
        "update_completion": 'Fertiges Ergebnis mit submit_result und complete=true abgeben; Inhaltsfelder vorher separat aktualisieren.',
        "decompose_fields": 'Zerlegung: task_manage(action="decompose", task_id=<ID>, subtasks=[{"title":"Kind","description":"Arbeit"}], close_parent=false); keine fremden Felder.',
        "decompose_parent": 'Bei decompose close_parent=false verwenden; danach offenen Rest mit update(status="pending") zurückgeben.',
        "detail_scope": 'Im gebundenen Lauf ist nur task_manage(action="detail", task_id=<eigene ID>) lesbar; andere Tasks sind hier nicht einsehbar.',
        "decompose_assignee": 'Teilaufgaben ohne assigned_to anlegen oder einen bekannten Bearbeiter wie OLLAMA nennen; Themen gehören in category.',
        "mutation_scope": 'Änderungen nur an der gebundenen Task: task_id ist die eigene ID als Zahl, nicht als Text.',
    }

    def __init__(self, reason):
        self.reason = reason
        self.user_message = self._GUIDANCE[reason]
        super().__init__(self.user_message)


# Owners a worker may name for a subtask; anything else (e.g. a topic) leaves the child unpickable.
# Cloud profile owners stay valid: the selector accepts them on their exact profile route.
_SUBTASK_ASSIGNEES = frozenset({"bach", "buddha", "ollama", "claude", "gemini", "copilot", "chatgpt",
                                "perplexity", "human", "user"}) | _EXTERNAL_PROFILE_BACKENDS


class WorkerLeaseBinding:
    def __init__(self, client, snapshot, ack, *, generation, is_current, stop_event,
                 clock=None, policy_guard=None, selection_policy_pin=None, selection_profile=None, _review_grant=None):
        self._client = client
        self._snapshot = copy.deepcopy(snapshot)
        self._ack = ack
        self._generation = generation
        self._is_current = is_current
        self._stop_event = stop_event
        self._policy_guard = policy_guard
        self._selection_policy_pin = copy.deepcopy(selection_policy_pin)
        self._selection_profile = copy.deepcopy(selection_profile)
        self._review_grant = _review_grant
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._injected_clock = clock is not None
        self._lock = threading.RLock()
        self._trace_completion_tokens = {}
        self._quarantine_ack = None
        self._active = True
        self._closed = False
        self._deactivation_reason = None
        self._completion_result = None
        self._submission_expected = None
        self._review_ack = None
        self._model_execution_pending = None
        self._model_execution_candidate = None
        self._scope_captured_result_id = None
        self._renew_exhausted = False
        self._decomposition_receipt = None
        # Only native, versioned update ACKs may move a running budget's task pin.
        self._budget_version_transitions = []
        # Cumulative for this lease, not reset by model block boundaries.
        # Starting a tool can have an effect even when its response is lost.
        self._tool_dispatch_count = 0

    @classmethod
    def acquire(cls, client, task_id, *, worker_id, host, generation, is_current,
                stop_event, clock=None, slot=None, automatic=False, policy_guard=None, _creator_delegation=None,
                deferred_versions=None, _review_grant=None):
        if not generation or not is_current() or stop_event.is_set():
            raise LeaseProtocolError("Workerlauf ist nicht mehr aktiv")
        if policy_guard is not None:
            policy_guard()
        snapshot = client.task_snapshot(task_id)
        selection_profile = cls._selection_profile_snapshot(slot) if slot is not None else {}
        selection_policy_pin = cls._effective_selection_policy_snapshot(client,snapshot,selection_profile)
        if selection_policy_pin is None:
            raise _TaskDoesNotMatch("Gespeicherte Auswahlpolicy nicht verifizierbar", reason="selection_policy_unavailable")
        if slot is None:
            from hub._services.worker_policy_settings import _selection_kernel
            restrictions = _selection_kernel().SelectionPolicy(**{
                key:selection_policy_pin['policy'][key] for key in ('require_assigned_slot','enforce_model_binding')})
            if restrictions.rejection(snapshot,{}) is not None:
                raise _TaskDoesNotMatch('Taskeinschränkung braucht eine verifizierbare Workerbesetzung')
        if automatic and (deferred_versions or {}).get(task_id) == snapshot["task_version"]:
            raise _TaskDoesNotMatch("Zurückgegebene Task-Version wartet auf eine Inhaltsänderung")
        if _review_grant is not None:
            if (getattr(_review_grant, "task_id", None) != task_id
                    or getattr(_review_grant, "generation", None) != generation
                    or getattr(_review_grant, "worker_id", None) != worker_id
                    or getattr(_review_grant, "host", None) != host
                    or slot is None
                    or getattr(_review_grant, "slot_id", None) != slot.get("id")):
                raise _TaskDoesNotMatch("Reviewtask passt nicht zur gebundenen Reviewerroute")
            review_slot = {**slot, "pickup_filter": {"enabled": False}}
            reason = cls._selection_rejection_reason(snapshot, review_slot, selection_policy=selection_policy_pin["policy"])
            if reason:
                raise _TaskDoesNotMatch("Reviewtask passt nicht zur gebundenen Reviewerroute",
                    reason="repository_changed" if reason in _REPOSITORY_REJECTIONS else "changed_selection")
        elif automatic and slot is not None:
            reason = cls._selection_rejection_reason(snapshot, slot, selection_policy=selection_policy_pin["policy"])
            if reason:
                raise _TaskDoesNotMatch("Task passt nicht zur aktuellen Workerbesetzung",
                    reason="repository_changed" if reason in _REPOSITORY_REJECTIONS else "changed_selection")
        elif slot is not None:
            if not cls._matches_slot(snapshot, slot, selection_policy=selection_policy_pin["policy"]):
                raise _TaskDoesNotMatch("Task passt nicht zur aktuellen Workerbesetzung")
            repository_reason = cls._repository_rejection_reason(snapshot, slot)
            if repository_reason:
                raise _TaskDoesNotMatch(repository_reason, reason="repository_changed")
        kwargs = {"now": clock()} if clock is not None else {}
        if _external_profile_backend(slot):
            # Shorten stale-claim recovery for cloud workers while retaining
            # the shared lease contract's two-hour S-profile run ceiling.
            kwargs["ttl_profile"] = "S"
        if _creator_delegation is None:
            acquire_kwargs = dict(worker_id=worker_id, host=host,
                task_version=snapshot["task_version"], result_generation=generation, **kwargs)
            if _review_grant is not None:
                acquire_kwargs["_review_grant"] = _review_grant
            ack = client.acquire(task_id, **acquire_kwargs)
        else:
            if (_creator_delegation.task_id != task_id or _creator_delegation.generation != generation
                    or _creator_delegation.worker_id != worker_id or _creator_delegation.host != host):
                raise LeaseProtocolError("Creator-Delegation gehört nicht zu dieser privaten Workergeneration")
            ack = client._acquire_native_creator(task_id, delegation=_creator_delegation,
                worker_id=worker_id, host=host, task_version=snapshot["task_version"], **kwargs)
        return cls(client, snapshot, ack, generation=generation, is_current=is_current,
                   stop_event=stop_event, clock=clock, policy_guard=policy_guard,
                   selection_policy_pin=selection_policy_pin, selection_profile=selection_profile,
                   _review_grant=_review_grant)


    @staticmethod
    def _selection_profile_snapshot(slot):
        if (not isinstance(slot, dict) or type(slot.get("id")) is not str
                or not slot["id"] or type(slot.get("model")) is not str
                or not slot["model"].strip()):
            return None
        fields = ("id", "model", "backend", "role_id", "sub_mode",
                  "require_assigned_slot", "enforce_model_binding", "pickup_filter", "allowed_repositories")
        return {key: copy.deepcopy(slot[key]) for key in fields if key in slot}

    @staticmethod
    def _effective_selection_policy_snapshot(client, snapshot, slot):
        """Read the stored global/task policy and bind its exact digest to this task version."""
        if (getattr(client, "mode", None) not in {"local", "remote"}
                or not isinstance(snapshot, dict) or not isinstance(slot, dict)
                or type(snapshot.get("id")) is not int or snapshot["id"] <= 0
                or not isinstance(snapshot.get("task_version"), str) or not snapshot["task_version"]):
            return None
        try:
            from hub._services.worker_policy_settings import CONTRACT, TASK_SCHEMA
            # Policy and task reads share the SDK's exact native connection.
            # Never fall back to an unrelated host DB or a caller's policy.
            reader = getattr(client, "_task_policy_snapshot", None)
            if not callable(reader):
                return None
            stored = reader(snapshot["id"])
            if (not isinstance(stored, dict) or stored.get("schema") != TASK_SCHEMA
                    or stored.get("availability") != "available"
                    or type(stored.get("task_id")) is not int
                    or stored["task_id"] != snapshot["id"]
                    or stored.get("task_version") != snapshot["task_version"]):
                return None
            configuration_version = stored.get("configuration_version")
            if (not isinstance(configuration_version, str)
                    or re.fullmatch(r"[0-9a-f]{64}", configuration_version) is None):
                return None
            effective = stored.get("effective")
            if (not isinstance(effective, dict)
                    or effective.get("contract_version") != CONTRACT
                    or type(effective.get("require_assigned_slot")) is not bool
                    or type(effective.get("enforce_model_binding")) is not bool):
                return None
            from .worker_queue_status import project_selection_policy, worker_selection_policy
            profile = worker_selection_policy(slot)
            policy = project_selection_policy({
                "schema": "bach.worker-selection.v1",
                "require_assigned_slot": (
                    profile["require_assigned_slot"] or effective["require_assigned_slot"]),
                "enforce_model_binding": (
                    profile["enforce_model_binding"] or effective["enforce_model_binding"]),
                "pickup_filter": profile["pickup_filter"],
                "allowed_repositories": profile["allowed_repositories"],
            })
            if policy is None:
                return None
            return {
                "policy": policy,
                "task_version": snapshot["task_version"],
                "configuration_version": configuration_version,
            }
        except Exception:
            return None


    @classmethod
    def _matches_review_slot(cls, snapshot, slot, *, selection_policy=None):
        """Keep physical slot/model constraints while review policy owns category routing."""
        if not isinstance(slot, dict):
            return False
        review_slot = dict(slot)
        review_slot["pickup_filter"] = {"enabled": False}
        return cls._selection_rejection_reason(snapshot, review_slot,selection_policy=selection_policy) is None

    @staticmethod
    def _matches_slot(snapshot, slot, *, selection_policy=None):
        if selection_policy is None:
            return False
        from .slots_config import task_matches_slot_binding, pickup_filter_rejection
        if not task_matches_slot_binding(snapshot,slot,selection_policy=selection_policy):
            return False
        pickup_slot = WorkerLeaseBinding._effective_pickup_slot(snapshot,slot)
        pickup = pickup_slot.get('pickup_filter')
        return (not isinstance(pickup,dict) or not pickup.get('enabled') or
                pickup_filter_rejection(snapshot,pickup_slot,selection_policy=selection_policy) is None)

    @staticmethod
    def _effective_pickup_slot(snapshot, slot):
        """Apply only the task-type flexibility granted to cloud workers."""
        if not isinstance(slot, dict):
            return {}
        pickup = slot.get("pickup_filter")
        if not isinstance(pickup, dict) or not pickup.get("enabled"):
            return slot
        if slot.get("require_assigned_slot") is True and str(snapshot.get("assigned_slot") or "").strip():
            # Explicit routing takes precedence over generic category/priority
            # selection. Tag restrictions still apply.
            pickup = {**pickup, "categories": [], "priorities": []}
        elif _external_profile_backend(slot):
            # Cloud workers may pick any task type; preserve priority and tag
            # policy while removing category as a queue-wide exclusion.
            pickup = {**pickup, "categories": []}
        else:
            return slot
        return {**slot, "pickup_filter": pickup}

    @staticmethod
    def _matches_external_profile_route(snapshot, slot):
        """Match the canonical owner alias and exact external profile/model route."""
        profile_backend = _external_profile_backend(slot)
        slot_id = slot.get("id")
        model = slot.get("model")
        if (profile_backend is None
                or type(slot_id) is not str or not slot_id or slot_id.strip() != slot_id
                or type(model) is not str or not model.strip()):
            return False
        return (
            type(snapshot.get("assigned_to")) is str
            and snapshot["assigned_to"].strip().casefold() == profile_backend
            and type(snapshot.get("assigned_slot")) is str
            and snapshot["assigned_slot"] == slot_id
            and type(snapshot.get("required_model")) is str
            and snapshot["required_model"] == model
        )

    @classmethod
    def _automatic_matches_slot(cls, snapshot, slot, *, selection_policy=None):
        return cls._selection_rejection_reason(snapshot, slot,selection_policy=selection_policy) is None

    @classmethod
    def _selection_rejection_reason(cls, snapshot, slot, *, selection_policy=None):
        if not isinstance(slot,dict) or not isinstance(selection_policy,dict):
            return 'selection_policy_unavailable'
        try:
            from hub._services.worker_policy_settings import _selection_kernel
            policy = _selection_kernel().SelectionPolicy(
                require_assigned_slot=selection_policy['require_assigned_slot'],
                enforce_model_binding=selection_policy['enforce_model_binding'])
            reason = policy.rejection(snapshot,slot)
            if reason:
                return reason
        except (KeyError,ValueError,TypeError,RuntimeError):
            return 'selection_policy_unavailable'
        if not cls._matches_slot(snapshot,slot,selection_policy=selection_policy):
            from .slots_config import pickup_filter_rejection
            return pickup_filter_rejection(snapshot,cls._effective_pickup_slot(snapshot,slot),selection_policy=selection_policy) or 'pickup_filter'
        return cls._repository_rejection_reason(snapshot,slot)

    @classmethod
    def _repository_rejection_reason(cls, snapshot, slot):
        """Require trusted task source authority, then apply an optional repo list."""
        if not isinstance(slot, dict):
            return "repository_capability_missing"
        try:
            from .worker_queue_status import worker_selection_policy
            repositories = worker_selection_policy(slot)["allowed_repositories"]
        except Exception:  # noqa: BLE001 -- malformed worker policy fails closed.
            return "repository_capability_missing"
        try:
            from .worker_repo_registry import resolve_task_repository
            binding = resolve_task_repository(snapshot.get("id"))
        except Exception:  # noqa: BLE001 -- unreadable/malformed registry fails closed.
            return "repository_unverified"
        from hub._services.worker_policy_settings import _selection_kernel
        return _selection_kernel().repository_rejection(binding.repository,repositories)

    @classmethod
    def acquire_next(cls, client, slot, *, observe_queue=None, review_route=None,
                     review_requested_model=None, **kwargs):
        """Acquire the actual configured/next canonical task before any inference."""
        from .worker_queue_status import QueueObservation
        observation = QueueObservation(client, observe_queue, kwargs.get("clock"))
        try:
            return cls._acquire_next_observed(client, slot, observation,
                review_route=review_route, review_requested_model=review_requested_model, **kwargs)
        finally:
            observation.publish()

    @classmethod
    def _acquire_next_observed(cls, client, slot, observation, *, review_route=None,
                               review_requested_model=None, **kwargs):
        from .worker_queue_status import ACQUIRE_DENIALS
        on_fixed_task_rejected = kwargs.pop("on_fixed_task_rejected", None)
        review_first = kwargs.pop("review_first", False) is True
        explicit = slot.get("task_id")
        released_fixed_task_id = None
        if explicit not in (None, "", 0, "0"):
            if isinstance(explicit, str) and explicit.isdecimal():
                explicit = int(explicit)
            observation.candidate(explicit)
            fixed_snapshot = client.task_snapshot(explicit)
            repository_reason = cls._repository_rejection_reason(fixed_snapshot, slot)
            if repository_reason:
                observation.reject(repository_reason)
                observation.waiting()
                return None
            observation.record["matched_count"] += 1
            observation.record["attempted_count"] += 1
            fixed_version = fixed_snapshot.get("task_version") if isinstance(fixed_snapshot, dict) else None
            review_grant = None
            if getattr(client, "mode", None) == "local":
                metadata_reader = getattr(client, "_review_task_metadata", None)
                grant_issuer = getattr(client, "_issue_review_grant", None)
                try:
                    metadata = metadata_reader(explicit) if callable(metadata_reader) else None
                except Exception:
                    metadata = None
                if (isinstance(metadata, dict) and metadata.get("review_task_id") == explicit
                        and callable(grant_issuer) and isinstance(review_route, dict)
                        and isinstance(review_requested_model, str)
                        and isinstance(slot, dict) and isinstance(slot.get("id"), str)):
                    clock = kwargs.get("clock") or (lambda: datetime.now(timezone.utc))
                    try:
                        review_grant = grant_issuer(explicit,
                            worker_id=kwargs.get("worker_id"), host=kwargs.get("host"),
                            generation=kwargs.get("generation"), slot_id=slot["id"],
                            route=review_route, requested_model=review_requested_model,
                            is_current=kwargs.get("is_current"),
                            stop_event=kwargs.get("stop_event"), clock=clock)
                    except Exception:
                        review_grant = None
            try:
                acquire_kwargs = dict(kwargs)
                if review_grant is not None:
                    acquire_kwargs["_review_grant"] = review_grant
                binding = cls.acquire(client, explicit, slot=slot, **acquire_kwargs)
            except _TaskDoesNotMatch as exc:
                observation.reject(exc.reason if exc.reason in _REPOSITORY_REJECTIONS else "changed_selection")
                observation.waiting()
                return None
            except LeaseDeniedError as exc:
                if exc.reason not in ACQUIRE_DENIALS:
                    raise
                observation.denied(exc.reason)
                if exc.reason == "conflict":
                    raise  # A native no-grant conflict still stops this run.
                if not callable(on_fixed_task_rejected):
                    raise  # Without an owning-slot release callback, keep the pin intact.
                deferred_versions = kwargs.get("deferred_versions")
                if not isinstance(deferred_versions, dict):
                    deferred_versions = {}
                    kwargs["deferred_versions"] = deferred_versions
                if isinstance(fixed_version, str):
                    deferred_versions[explicit] = fixed_version
                on_fixed_task_rejected(explicit, exc.reason, fixed_version)
                released_fixed_task_id = explicit
                # The persisted pin is cleared by the callback. Continue against
                # the same canonical selector with the rejected ID skipped for
                # this generation, even if its content changes during the scan.
                slot = dict(slot)
                slot["task_id"] = None
            else:
                observation.acquired(binding)
                return binding
        if kwargs.get("_creator_delegation") is not None:
            raise LeaseProtocolError("Creator-Delegation braucht die explizit gebundene Sequenz-Task")
        if review_first:
            # Reviews are ordinary work (user decision 25.10.2026): the caller alternates turns.
            reviewed = cls._acquire_review_next(client, slot, observation,
                review_route=review_route, review_requested_model=review_requested_model,
                **kwargs)
            if reviewed is not None:
                return reviewed
        offset = 0
        while True:
            if not kwargs["is_current"]() or kwargs["stop_event"].is_set():
                raise LeaseProtocolError("Workerlauf ist nicht mehr aktiv")
            page = client.task_candidates(limit=100, offset=offset)
            observation.record["scanned_pages"] += 1
            for task in page["tasks"]:
                observation.candidate(task["id"])
                if task["id"] == released_fixed_task_id:
                    observation.reject("deferred_version")
                    continue
                policy_pin = cls._effective_selection_policy_snapshot(client,task,cls._selection_profile_snapshot(slot))
                reason = ("selection_policy_unavailable" if policy_pin is None else
                          cls._selection_rejection_reason(task,slot,selection_policy=policy_pin["policy"]))
                if reason:
                    observation.reject(reason)
                    continue
                if (kwargs.get("deferred_versions") or {}).get(task["id"]) == task["task_version"]:
                    observation.reject("deferred_version")
                    continue
                observation.record["matched_count"] += 1
                observation.record["attempted_count"] += 1
                try:
                    binding = cls.acquire(client, task["id"], slot=slot, automatic=True, **kwargs)
                    observation.acquired(binding)
                    return binding
                except _TaskDoesNotMatch as exc:
                    observation.reject(exc.reason if exc.reason in _REPOSITORY_REJECTIONS else "changed_selection")
                    continue
                except LeaseDeniedError as exc:
                    if exc.reason == "conflict":
                        observation.denied(exc.reason)
                        raise  # A native no-grant conflict still stops this run.
                    # Task-specific denials (incl. an unresolved prior trace) skip only this task.
                    if exc.reason not in ACQUIRE_DENIALS:
                        raise
                    observation.reject(exc.reason)
            if not page["has_more"]:
                reviewed = cls._acquire_review_next(client, slot, observation,
                    review_route=review_route, review_requested_model=review_requested_model,
                    **kwargs)
                if reviewed is not None:
                    return reviewed
                observation.waiting()
                return None
            if not page["tasks"]:
                # A remote canonical page may contain only excluded reserved
                # review markers. Advancing preserves normal pagination; the
                # local queue filters them in SQL before this point.
                if offset >= 100_000:
                    raise LeaseProtocolError("Kanonische Task-Seite hat keinen Fortschritt")
            offset += 100

    @classmethod
    def _acquire_review_next(cls, client, slot, observation, *, review_route=None,
                             review_requested_model=None, **kwargs):
        """Review pickup runs only after every eligible ordinary task was tried."""
        from .worker_queue_status import ACQUIRE_DENIALS
        if (getattr(client, "mode", None) != "local" or not isinstance(review_route, dict)
                or not isinstance(review_requested_model, str) or not review_requested_model.strip()
                or not callable(getattr(client, "_review_candidates", None))
                or not callable(getattr(client, "_issue_review_grant", None))):
            return None
        worker_id, host = kwargs.get("worker_id"), kwargs.get("host")
        generation, is_current = kwargs.get("generation"), kwargs.get("is_current")
        stop_event = kwargs.get("stop_event")
        if (not isinstance(slot, dict) or not isinstance(slot.get("id"), str)
                or not slot["id"] or not callable(is_current)
                or stop_event is None or not callable(getattr(stop_event, "is_set", None))):
            return None
        clock = kwargs.get("clock") or (lambda: datetime.now(timezone.utc))
        deferred_versions = kwargs.get("deferred_versions") or {}
        offset = 0
        while True:
            if not is_current() or stop_event.is_set():
                raise LeaseProtocolError("Workerlauf ist nicht mehr aktiv")
            try:
                page = client._review_candidates(limit=100, offset=offset)
            except Exception:
                return None
            if (not isinstance(page, dict) or not isinstance(page.get("tasks"), list)
                    or type(page.get("has_more")) is not bool or page.get("offset") != offset):
                return None
            observation.record["scanned_pages"] += 1
            for task in page["tasks"]:
                if not isinstance(task, dict) or type(task.get("id")) is not int:
                    continue
                observation.candidate(task["id"])
                policy_pin = cls._effective_selection_policy_snapshot(client,task,cls._selection_profile_snapshot(slot))
                reason = ("selection_policy_unavailable" if policy_pin is None else cls._selection_rejection_reason(
                    task, {**slot, "pickup_filter": {"enabled": False}},selection_policy=policy_pin["policy"]))
                if reason:
                    observation.reject(reason if reason in {"slot_binding", "model_binding",
                        "explicit_slot_required", "selection_policy_unavailable", "ownership", *_REPOSITORY_REJECTIONS} else "ownership")
                    continue
                if deferred_versions.get(task["id"]) == task.get("task_version"):
                    observation.reject("deferred_version")
                    continue
                try:
                    grant = client._issue_review_grant(task["id"], worker_id=worker_id,
                        host=host, generation=generation, slot_id=slot["id"],
                        route=review_route, requested_model=review_requested_model,
                        is_current=is_current, stop_event=stop_event, clock=clock)
                except Exception:
                    grant = None
                if grant is None:
                    observation.reject("ownership")
                    continue
                observation.record["matched_count"] += 1
                observation.record["attempted_count"] += 1
                try:
                    binding = cls.acquire(client, task["id"], slot=slot, automatic=True,
                        _review_grant=grant, **kwargs)
                    observation.acquired(binding)
                    return binding
                except _TaskDoesNotMatch as exc:
                    observation.reject(exc.reason if exc.reason in _REPOSITORY_REJECTIONS else "changed_selection")
                except LeaseDeniedError as exc:
                    if exc.reason == "conflict":
                        observation.denied(exc.reason)
                        raise
                    if exc.reason not in ACQUIRE_DENIALS:
                        raise
                    observation.reject(exc.reason)
            if not page["has_more"]:
                return None
            if offset >= 100_000:
                raise LeaseProtocolError("Review-Taskseite hat keinen Fortschritt")
            offset += 100

    @property
    def generation(self):
        return self._generation

    @property
    def tool_dispatch_count(self):
        with self._lock:
            return self._tool_dispatch_count

    def mark_tool_dispatch(self):
        """Record a possible effect before entry into a bound dispatcher."""
        with self._lock:
            self.assert_active()
            self._tool_dispatch_count += 1

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
        return self.result_state()["completed_task_ids"]

    @property
    def completion_result(self):
        """Only a currently accepted, correlated canonical result can be handed on."""
        state = self.result_state()
        return state["result"] if state["completed_task_ids"] else None

    @property
    def submitted_result(self):
        """Historical submission ACK, never itself proof of current acceptance."""
        with self._lock:
            return copy.deepcopy(self._completion_result)

    @property
    def has_result_receipt(self):
        with self._lock:
            return (self._completion_result is not None or self._review_ack is not None
                    or self._submission_expected is not None)

    def result_state(self):
        with self._lock:
            record = copy.deepcopy(self._completion_result)
            expected = copy.deepcopy(self._submission_expected)
            review = self._review_ack
            version = self._snapshot["task_version"]
            fence = self._ack.fence
        empty = {"completed_task_ids": (), "reviewed_task_ids": (), "result": None}
        if record is None and review is None and expected is None:
            return empty
        # No DB/HTTP work while holding controller or binding locks.
        observed = self._client.task_result_snapshot(self.task_id)
        current = observed.get("result")
        reconstructed = False
        if record is None and expected is not None:
            if current is None:
                raise LeaseProtocolError("Ergebnisabgabe nach fehlendem ACK noch nicht geklärt")
            if any(current.get(key) != expected[key] for key in expected):
                raise LeaseProtocolError("Kanonisches Ergebnis gehört nicht zur ungeklärten Abgabe")
            if (type(current.get("result_id")) is not int or current["result_id"] <= 0
                    or type(current.get("submission_event_id")) is not int):
                raise LeaseProtocolError("Kanonische Rekonstruktion der Ergebnisabgabe fehlt")
            record = current
            with self._lock:
                if self._submission_expected == expected:
                    self._completion_result = copy.deepcopy(current)
                    self._deactivate("result_reconstructed", close=True)
                    reconstructed = True
        if record is not None:
            if (not isinstance(current, dict) or any(current.get(key) != record.get(key)
                    for key in ("result_id", "task_id", "fence", "generation", "task_version", "result_sha256"))):
                raise LeaseProtocolError("Kanonische Ergebnisbindung nicht mehr bestätigt")
            if current.get("accepted") is True:
                if reconstructed:
                    self._link_confirmed_model_execution()
                self.capture_confirmed_scope()
                return {**empty, "completed_task_ids": (self.task_id,), "result": current}
            if current.get("reason") == "awaiting_review":
                if reconstructed:
                    self._link_confirmed_model_execution()
                self.capture_confirmed_scope()
                return {**empty, "reviewed_task_ids": (self.task_id,), "result": current}
            raise LeaseProtocolError("Aktuelle Ergebnisabnahme nicht bestätigt")
        elif (isinstance(review, LeaseReleaseAck) and review.released is True
              and review.task_id == self.task_id and review.fence == fence
              and review.outcome == review.status == observed.get("status") == "review"
              and observed.get("task_version") == version):
            task = self._client.task_snapshot(self.task_id)
            if task.get("claim_fence") == fence and task.get("status") == "review":
                return {**empty, "reviewed_task_ids": (self.task_id,)}
        return empty

    @property
    def reviewed_task_ids(self):
        return self.result_state()["reviewed_task_ids"]

    def task_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def budget_task_version_evidence(self):
        """Return the live binding version and its confirmed same-lease ACK chain."""
        with self._lock:
            self.assert_active()
            return (self.task_id, self._snapshot["task_version"],
                    tuple(self._budget_version_transitions))

    def correction_context(self):
        with self._lock:
            self._assert_authority_active()
            return self._client.task_correction_context(
                self.task_id, lease_id=self._ack.lease_id, fence=self._ack.fence,
                task_version=self._snapshot["task_version"], generation=self._generation,
            )

    def _assert_authority_active(self):
        with self._lock:
            if not self._active or self._closed or not self._is_current() or self._stop_event.is_set():
                raise LeaseProtocolError("Taskbindung oder Workerlauf ist nicht mehr aktiv")
            self._ack.assert_locally_valid(now=self._clock())

    def _assert_selection_current(self):
        if self._selection_profile is None:
            return
        pin = self._effective_selection_policy_snapshot(self._client,self._snapshot,self._selection_profile)
        if (pin is None or self._selection_policy_pin is None or
                pin['configuration_version'] != self._selection_policy_pin['configuration_version'] or
                pin['policy'] != self._selection_policy_pin['policy'] or
                self._selection_constraints_changed(pin)):
            raise LeaseProtocolError('Gespeicherte Task-Auswahlpolicy ist nicht mehr zugelassen')

    def _selection_constraints_changed(self,pin):
        if self._selection_profile:
            profile = self._selection_profile
            if self._review_grant is not None:
                profile = {**profile, 'pickup_filter': {'enabled': False}}
            return self._selection_rejection_reason(self._snapshot,profile,selection_policy=pin['policy']) is not None
        from hub._services.worker_policy_settings import _selection_kernel
        policy = _selection_kernel().SelectionPolicy(**{
            key:pin['policy'][key] for key in ('require_assigned_slot','enforce_model_binding')})
        return policy.rejection(self._snapshot,{}) is not None

    def matches_execution_slot(self, slot):
        """Actual dispatch uses the same private canonical policy, not preferences."""
        self.assert_active()
        if self._selection_profile is None or slot.get('id') != self._selection_profile.get('id'):
            return False
        actual = {**self._selection_profile, 'id':slot['id'], 'model':slot.get('model')}
        if self._review_grant is not None:
            actual['pickup_filter'] = {'enabled': False}
        return self._selection_rejection_reason(self._snapshot,actual,selection_policy=self._selection_policy_pin['policy']) is None

    def assert_active(self):
        with self._lock:
            self._assert_authority_active()
            self._assert_selection_current()
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
        except LeaseSelfCheckRequiredError:
            # This exact local validation ran before any result/status write.
            raise
        except LeaseRequestRejectedError:
            # The service rejected the request before applying it; the lease stays valid.
            raise
        except LeaseError as exc:
            if keep_max_total and isinstance(exc, LeaseMaxTotalReachedError):
                # Known denial: the last confirmed lease still owns its
                # remaining lifetime. No ACK, deadline or version is guessed.
                raise
            # A missing/malformed ACK may follow a committed operation.
            # Revoke locally; never guess a new version or retry this mutation.
            self._deactivate("operation_lease_error")
            raise
        except Exception:
            self._deactivate("operation_unconfirmed")
            raise LeaseProtocolError("Taskoperation fehlgeschlagen; Bestätigung fehlt") from None

    def _adopt_task_version(self, version, *, previous_version):
        # The caller holds the binding lock and supplies only a native ACK version.
        if (self._snapshot.get("task_version") != previous_version
                or self._ack.task_version != previous_version):
            self._deactivate("task_version_mismatch")
            raise LeaseProtocolError("Taskversion passt nicht zur bestaetigten Workerbindung")
        try:
            current_ack = replace(self._ack, task_version=version)
        except Exception:
            self._deactivate("task_version_unconfirmed")
            raise LeaseProtocolError("Neue Taskversion ist nicht bestaetigt") from None
        self._ack = current_ack
        self._snapshot["task_version"] = current_ack.task_version
        self._budget_version_transitions.append((previous_version, current_ack.task_version))

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

    def _deactivate(self, reason, *, close=False):
        """Revoke local authority; the first fixed reason stays, never payloads."""
        with self._lock:
            if close:
                self._closed = True
            if self._active:
                self._deactivation_reason = reason
                (log.info if close else log.warning)(
                    "binding_deactivated reason=%s closed=%s task_id=%s generation=%s",
                    reason, close, self.task_id, self._generation)
            self._active = False

    @property
    def deactivation_reason(self):
        """Fixed-vocabulary cause for an inactive binding, for logs and slot status."""
        with self._lock:
            if self._deactivation_reason is not None:
                return self._deactivation_reason
            if not self._is_current():
                return "worker_not_current"
            return "stop_requested" if self._stop_event.is_set() else None

    def invalidate(self, reason="invalidated"):
        with self._lock:
            self._deactivate(reason)
            self._model_execution_pending = None
            self._model_execution_candidate = None
            if self._review_grant is not None:
                self._review_grant._last_answer = None
                self._review_grant._last_answer_sha256 = None

    def begin_model_execution(self, *, backend_id, requested_model, slot_id, request_sha256,
                              route_sha256=None):
        """Start optional private evidence for this exact live binding and call."""
        with self._lock:
            # A new attempt, including a fallback, supersedes the prior answer.
            self._model_execution_pending = None
            self._model_execution_candidate = None
            if self._review_grant is not None:
                self._review_grant._last_answer = None
                self._review_grant._last_answer_sha256 = None
            if (not self._active or self._closed or not self._is_current()
                    or self._stop_event.is_set() or self._ack.result_generation != self._generation):
                return None
            if self._review_grant is not None and (
                    backend_id != self._review_grant.route.get("backend_id")
                    or requested_model != self._review_grant.requested_model
                    or slot_id != self._review_grant.slot_id
                    or route_sha256 != self._review_grant.route.get("route_sha256")):
                return None
            start = getattr(self._client, "_start_model_execution", None)
            if not callable(start):
                return None
            try:
                start_kwargs = {"backend_id": backend_id, "requested_model": requested_model,
                                "slot_id": slot_id, "request_sha256": request_sha256}
                if route_sha256 is not None:
                    start_kwargs["route_sha256"] = route_sha256
                handle = start(self, **start_kwargs)
            except Exception:
                # Evidence is optional for the existing personal review path.
                return None
            if handle is not None:
                self._model_execution_pending = handle
            return handle

    def _discard_model_execution_candidate(self):
        """A real new dispatch invalidates an older answer even without evidence."""
        with self._lock:
            self._model_execution_pending = None
            self._model_execution_candidate = None
            if self._review_grant is not None:
                self._review_grant._last_answer = None
                self._review_grant._last_answer_sha256 = None

    def finish_model_execution(self, handle, *, result=None, failed=False, route_sha256=None,
                               failure=None):
        """Confirm a returned backend answer; a CLI may already have submitted.

        ``failure`` is a fixed code from worker_execution_evidence.failure_code.
        """
        should_record_review = False
        should_reconcile = False
        with self._lock:
            if handle is None or self._model_execution_pending is not handle:
                return False
            self._model_execution_pending = None
            finish = getattr(self._client, "_finish_model_execution", None)
            if not callable(finish):
                return False
            if (failed or not self._is_current() or self._stop_event.is_set()
                    or self._ack.result_generation != self._generation):
                if self._review_grant is not None:
                    self._review_grant._last_answer = None
                    self._review_grant._last_answer_sha256 = None
                try:
                    finish_kwargs = {"failed": True}
                    if route_sha256 is not None:
                        finish_kwargs["route_sha256"] = route_sha256
                    reason = failure if failed else "binding_inactive"
                    if reason is not None:
                        finish_kwargs["failure"] = reason
                    finish(self, handle, **finish_kwargs)
                except Exception:
                    pass
                return False
            try:
                finish_kwargs = {"result": result, "failed": False}
                if route_sha256 is not None:
                    finish_kwargs["route_sha256"] = route_sha256
                confirmed = finish(self, handle, **finish_kwargs) is True
            except Exception:
                if self._review_grant is not None:
                    self._review_grant._last_answer = None
                    self._review_grant._last_answer_sha256 = None
                return False
            if not confirmed:
                if self._review_grant is not None:
                    self._review_grant._last_answer = None
                    self._review_grant._last_answer_sha256 = None
                return False
            self._model_execution_candidate = handle
            if self._review_grant is not None:
                try:
                    self._review_grant._last_answer = copy.deepcopy(result)
                    from hub._services.worker_execution_evidence import _digest as answer_digest
                    self._review_grant._last_answer_sha256 = answer_digest(result)
                except Exception:
                    self._review_grant._last_answer = None
                    self._review_grant._last_answer_sha256 = None
            if self._completion_result is not None:
                self._link_confirmed_model_execution()
                should_record_review = self._review_grant is not None
                should_reconcile = not should_record_review
        if should_record_review:
            record = getattr(self._client, "_record_result_review", None)
            if callable(record):
                try:
                    record(self)
                except Exception:
                    pass
        elif should_reconcile:
            self._reconcile_confirmed_completion()
        return True

    def _reconcile_confirmed_completion(self):
        """Run optional local policy outside the binding lock and preserve ACKs."""
        reconcile = getattr(self._client, "_reconcile_task_completion", None)
        if callable(reconcile):
            try:
                return reconcile(self.task_id)
            except Exception:
                return None
        return None

    def _link_confirmed_model_execution(self):
        """Attach a confirmed answer to the canonical submitted result, if any."""
        try:
            handle = self._model_execution_candidate
            if (handle is None or self._completion_result is None or not self._is_current()
                    or self._stop_event.is_set() or self._ack.result_generation != self._generation):
                return False
            link = getattr(self._client, "_link_model_execution", None)
            if not callable(link):
                return False
            return link(self, handle) is True
        except Exception:
            return False

    def capture_confirmed_scope(self):
        """Optional Git evidence after a canonical submission, outside locks."""
        with self._lock:
            if (self._completion_result is None or not self._is_current()
                    or self._stop_event.is_set()
                    or self._ack.result_generation != self._generation):
                return False
            result_id = self._completion_result.get("result_id")
            already_captured = self._scope_captured_result_id == result_id
        if already_captured:
            # Only capture is cached. Every public result read still
            # revalidates the current Git/lock state independently.
            evaluation = self._reconcile_confirmed_completion()
            if not isinstance(evaluation, dict) or evaluation.get("status") == "review":
                self._prepare_eligible_review_task()
            return True
        capture = getattr(self._client, "_capture_task_scope", None)
        if not callable(capture):
            return False
        try:
            confirmed = capture(self) is True
            if confirmed:
                with self._lock:
                    if (self._completion_result is not None
                            and self._completion_result.get("result_id") == result_id):
                        self._scope_captured_result_id = result_id
                evaluation = self._reconcile_confirmed_completion()
                if not isinstance(evaluation, dict) or evaluation.get("status") == "review":
                    self._prepare_eligible_review_task()
            else:
                # A submitted Git task without a tree must reach the same
                # canonical negative evidence guard as a later controller poll.
                # The guard preserves unavailable/transient cases and the ACK.
                self._reconcile_confirmed_completion()
            return confirmed
        except Exception:
            # Capture errors never undo a committed submission. The existing
            # local evaluator alone may reopen proven missing-tree work.
            self._reconcile_confirmed_completion()
            return False

    def _prepare_eligible_review_task(self):
        """Optional idempotent preparation; never nests Git/DB work under the binding lock."""
        if self._review_grant is not None:
            return None
        prepare = getattr(self._client, "_prepare_review_task", None)
        if not callable(prepare):
            return None
        try:
            return prepare(self)
        except Exception:
            return None

    def heartbeat(self, *, renew_due=False):
        with self._lock:
            self._assert_authority_active()
            remaining = (self._ack.local_deadline - self._clock()).total_seconds()
            if renew_due or remaining <= 120:
                return self.renew()
            return False

    def trace_tool_started(self, *, source, request_id, tool_name, arguments_sha256):
        """Authorize and persist a start before dispatch; never return the lease id."""
        from .worker_tool_trace import TraceIdentity
        from hub._services.task_lease_client import ToolTraceStartAck
        with self._lock:
            self.assert_active()
            ack = self._ack
            generation = self._generation
            if (ack.result_generation != generation
                    or ack.task_version != self._snapshot.get("task_version")):
                raise LeaseProtocolError("Taskbindung bestätigt keine aktuelle Trace-Generation")
            identity = TraceIdentity(
                task_id=self.task_id, fence=ack.fence, worker_id=ack.worker_id,
                generation=generation, task_version=ack.task_version,
                request_id=request_id, source=source, tool_name=tool_name)
            start_ack = self._client.tool_trace_start(
                identity, lease_id=ack.lease_id, arguments_sha256=arguments_sha256)
            if not isinstance(start_ack, ToolTraceStartAck):
                raise LeaseProtocolError("Werkzeug-Trace-Start ist nicht bestätigt")
            self._trace_completion_tokens[identity] = start_ack.completion_token
            return identity

    def trace_tool_phase(self, identity, phase, *, receipt_id=None, result_sha256=None,
                         diagnostic=None):
        """Complete a started call even if the lease was returned while it ran."""
        from .worker_tool_trace import TraceIdentity
        if not isinstance(identity, TraceIdentity):
            raise LeaseProtocolError("Werkzeug-Trace-Identität fehlt")
        with self._lock:
            ack = self._ack
            if (identity.task_id != self.task_id or identity.fence != ack.fence
                    or identity.worker_id != ack.worker_id
                    or identity.generation != self._generation):
                raise LeaseProtocolError("Werkzeug-Trace gehört nicht zu dieser Taskbindung")
            completion_token = self._trace_completion_tokens.get(identity)
            if completion_token is None:
                raise LeaseProtocolError("Werkzeug-Trace-Abschluss ist nicht gebunden")
            result = self._client.tool_trace_phase(
                identity, phase, receipt_id=receipt_id, result_sha256=result_sha256,
                completion_token=completion_token,
                **({"diagnostic": diagnostic} if diagnostic is not None else {}))
            if phase in {"failed", "acknowledged"}:
                self._trace_completion_tokens.pop(identity, None)
            return result

    def return_lease(self, note=""):
        """Cleanup may return a stopped worker's known lease; ambiguity forbids it.

        ``note`` is a fixed-vocabulary reason stored with the return event.
        """
        with self._lock:
            if not self._active or self._closed or not self._is_current():
                return False
            try:
                self._operation(self._client.release, outcome="return", note=note,
                                check_policy=False)
            except LeaseError:
                return False
            self._deactivate("lease_returned", close=True)
            return True

    def execute_task_command(self, operation, arguments):
        from .bound_task_command import bound_task_command
        with self._lock:
            self.assert_active()
            return bound_task_command(operation, arguments, self)

    def quarantine_lease(self):
        """Block uncertain tool work canonically; never requeue it as pending."""
        with self._lock:
            if not self._active or self._closed or not self._is_current():
                return False
            try:
                ack = self._operation(
                    self._client.release, outcome="blocked", check_policy=False,
                    note="backend_error_after_tool_dispatch: Toolwirkungen vor Wiederaufnahme prüfen",
                )
                if (not isinstance(ack, LeaseReleaseAck) or ack.released is not True
                        or type(ack.task_id) is not int or type(ack.fence) is not int
                        or ack.task_id != self.task_id or ack.fence != self._ack.fence
                        or ack.outcome != "blocked" or ack.status != "blocked"):
                    raise LeaseProtocolError("Quarantäne-Freigabe nicht bestätigt")
            except LeaseError:
                # A missing ACK may follow a committed quarantine. Neither
                # Return-to-pending nor a guessed retry may undo that decision.
                self._deactivate("quarantine_unconfirmed")
                return False
            self._quarantine_ack = ack
            self._deactivate("lease_quarantined", close=True)
            return True

    def quarantined_effects_clear(self):
        """Read native settlement for this exact locally quarantined generation.

        Remote or connection-only clients have no proven local read-only authority
        here and remain terminal. Never invent a second DB path or HTTP endpoint.
        """
        from pathlib import Path
        import sqlite3
        from hub._services.task_lease import task_content_version
        from .worker_tool_trace import task_trace_recovery_state

        with self._lock:
            receipt = self._quarantine_ack
            ack = self._ack
            if (not isinstance(receipt, LeaseReleaseAck)
                    or receipt.released is not True or receipt.outcome != "blocked"
                    or receipt.status != "blocked" or receipt.task_id != self.task_id
                    or receipt.fence != ack.fence or not self._closed or self._active
                    or not self._is_current() or self._stop_event.is_set()
                    or ack.result_generation != self._generation
                    or self._trace_completion_tokens or self._model_execution_pending is not None
                    or self._client.mode != "local"
                    or getattr(self._client, "_conn", None) is not None):
                return False
            # This is the path supplied to the original native TaskLeaseClient.
            # No home-directory fallback and no caller/prompt path is accepted.
            authority_path = getattr(self._client, "_db_path", None)
            if not isinstance(authority_path, Path):
                return False
            expected = (self.task_id, ack.fence, self._generation,
                        ack.worker_id, ack.task_version)

        conn = None
        try:
            db = authority_path.resolve(strict=True)
            if not db.is_file():
                return False
            conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (expected[0],)).fetchone()
            if (row is None or row["status"] != "blocked" or row["claim_id"]
                    or row["claim_fence"] != expected[1]
                    or task_content_version(dict(row)) != expected[4]
                    or task_trace_recovery_state(conn, expected[0]) != "clear"):
                return False
            identities = conn.execute(
                "SELECT DISTINCT generation,worker_id FROM worker_tool_trace_events "
                "WHERE task_id=? AND fence=?", expected[:2],
            ).fetchall()
            if not identities or any(
                    row["generation"] != expected[2] or row["worker_id"] != expected[3]
                    for row in identities):
                return False
            executions = conn.execute(
                "SELECT generation,phase FROM worker_model_executions WHERE task_id=? AND fence=?",
                expected[:2],
            ).fetchall()
            if not executions or any(
                    row["generation"] != expected[2] or row["phase"] not in {"returned", "failed"}
                    for row in executions):
                return False
        except Exception:  # noqa: BLE001 -- unknown/pending effects stay terminal
            return False
        finally:
            if conn is not None:
                conn.rollback()
                conn.close()
        with self._lock:
            return (self._quarantine_ack is receipt and self._ack is ack
                    and self._closed and not self._active
                    and self._is_current() and not self._stop_event.is_set()
                    and not self._trace_completion_tokens
                    and self._model_execution_pending is None)

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
            self._adopt_task_version(ack.task_version, previous_version=ack.previous_task_version)
            self._snapshot["description"] = description
            if review:
                release = self._operation(self._client.release, outcome="review", result_ref=result_ref)
                if (not isinstance(release, LeaseReleaseAck) or release.released is not True
                        or type(release.task_id) is not int or type(release.fence) is not int
                        or type(release.task_id) is not int or release.task_id != self.task_id
                        or type(release.fence) is not int or release.fence != self._ack.fence
                        or release.outcome != "review" or release.status != "review"):
                    self.invalidate("review_release_unconfirmed")
                    raise LeaseProtocolError("Review-Freigabe nicht bestätigt")
                self._review_ack = release
                self._deactivate("review_released", close=True)
            return True

    def _prepare_submission_scope(self):
        """Read required repository evidence before any result/release write, outside locks."""
        with self._lock:
            self.assert_active()
            version = self._snapshot["task_version"]
            raw_contract = self._snapshot.get("completion_contract_json")
        from hub._services.worker_completion_contract import parse_contract
        contract = parse_contract(raw_contract) if raw_contract is not None else None
        if raw_contract is not None and contract is None:
            raise WorkerSubmissionScopeError("task_contract_invalid")
        from hub._services.chat.worker_repo_registry import load_registry
        try:
            registered = str(self.task_id) in load_registry()["tasks"]
        except Exception:
            raise WorkerSubmissionScopeError("registry_unavailable") from None
        git_required = bool(contract and any(
            criterion["kind"] == "git_blob_sha256" for criterion in contract["criteria"]))
        if not registered:
            if git_required:
                raise WorkerSubmissionScopeError("repository_binding_missing")
            # Explicitly valid registry absence and a non-Git contract preserve
            # the existing non-repository result path. Unknown is never absence.
            return None
        from hub._services.chat.worker_write_guard import snapshot_task_scope
        from hub._services.worker_scope_evidence import _snapshot_valid
        try:
            scope = snapshot_task_scope(self.task_id)
        except Exception:
            raise WorkerSubmissionScopeError("scope_unavailable") from None
        if not isinstance(scope, dict) or scope.get("availability") != "available":
            reason = scope.get("reason") if isinstance(scope, dict) else "scope_unavailable"
            raise WorkerSubmissionScopeError(reason)
        if not isinstance(scope.get("source_pin"), dict):
            raise WorkerSubmissionScopeError("source_pin_missing")
        if not _snapshot_valid(scope, self.task_id):
            raise WorkerSubmissionScopeError("scope_unavailable")
        with self._lock:
            self.assert_active()
            if self._snapshot["task_version"] != version:
                raise WorkerSubmissionScopeError("task_version_changed")
        return scope

    def _confirm_submission_scope(self, prepared_scope):
        """After an ACK, require canonical scope/revision; never replay a submission."""
        if self.capture_confirmed_scope() is not True:
            raise LeaseProtocolError("Ergebnis wurde abgegeben; Scope-Nachbestätigung fehlt. Kein erneutes Submit.")
        try:
            observed = self._client.task_result_snapshot(self.task_id)
        except Exception:
            raise LeaseProtocolError("Ergebnis wurde abgegeben; aktueller Resultreadback fehlt. Kein erneutes Submit.") from None
        record = observed.get("result") if isinstance(observed, dict) else None
        with self._lock:
            confirmed = copy.deepcopy(self._completion_result)
        scope = record.get("scope") if isinstance(record, dict) else None
        revision = record.get("result_revision") if isinstance(record, dict) else None
        if (not isinstance(confirmed, dict) or not isinstance(record, dict)
                or any(record.get(key) != confirmed.get(key) for key in (
                    "task_id", "result_id", "generation", "fence", "task_version", "result_sha256"))
                or not isinstance(scope, dict) or scope.get("availability") != "available"
                or scope.get("snapshot") != prepared_scope
                or type(revision) is not str or re.fullmatch(r"[a-f0-9]{64}", revision) is None):
            raise LeaseProtocolError("Ergebnis wurde abgegeben; Scope/Resultrevision nicht bestätigt. Kein erneutes Submit.")

    def execute_task_manage(self, args, *, _dispatch_marked=False):
        """Dispatch a bound task operation, recording review only after releasing the binding lock."""
        grant = self._review_grant
        if grant is not None and isinstance(args, dict) and args.get("action") == "submit_result":
            guard = getattr(self._client, "_guard_review_dispatch", None)
            if (not callable(guard) or not guard(self, route=grant.route,
                                                requested_model=grant.requested_model)):
                raise LeaseProtocolError("Review-Ziel ist vor der Abgabe nicht mehr aktuell")
        submitting = (grant is None and isinstance(args, dict) and (
            args.get("action") in {"done", "submit_result"}
            or (args.get("action") == "update" and args.get("status") in {"done", "completed"})))
        prepared_scope = self._prepare_submission_scope() if submitting else None
        result = self._execute_task_manage_locked(args, _dispatch_marked=_dispatch_marked)
        if prepared_scope is not None:
            self._confirm_submission_scope(prepared_scope)
        with self._lock:
            submitted_review = (self._review_grant is not None
                and self._completion_result is not None and self._review_ack is not None)
        if submitted_review:
            record = getattr(self._client, "_record_result_review", None)
            if callable(record):
                try:
                    recorded = record(self)
                    if isinstance(recorded, dict) and recorded.get("availability") == "cancelled":
                        return (f"Task #{self.task_id}: Review-Ziel nach Abgabe geändert; "
                                "dieses administrative Reviewkind wurde storniert.")
                except Exception:
                    # A failed optional review receipt cannot undo the child submission.
                    pass
        return result

    def _execute_task_manage_locked(self, args, *, _dispatch_marked=False):
        with self._lock:
            self.assert_active()
            # Native controller actions also need proof without a dispatcher.
            # The private flag prevents counting the same dispatch twice.
            if not _dispatch_marked:
                self.mark_tool_dispatch()
            if not isinstance(args, dict):
                raise LeaseProtocolError("Ungültige Task-Werkzeugargumente")
            action = args.get("action", "list")
            if self._review_grant is not None:
                if action == "detail":
                    if (set(args) != {"action", "task_id"}
                            or type(args.get("task_id")) is not int
                            or args["task_id"] not in {self.task_id, self._review_grant.target_task_id}):
                        raise LeaseProtocolError("Reviewdetail ist auf die eigene und Zieltask begrenzt")
                    snapshot = (self.task_snapshot() if args["task_id"] == self.task_id
                                else self._client.task_snapshot(args["task_id"]))
                    allowed = ("id", "title", "description", "category", "priority", "project", "status")
                    return "\n".join(f"{key}: {snapshot[key]}" for key in allowed if key in snapshot)
                if (action != "submit_result"
                        or set(args) != {"action", "task_id", "result"}
                        or type(args.get("task_id")) is not int
                        or args["task_id"] != self.task_id):
                    raise LeaseProtocolError("Reviewtask erlaubt nur eigenes Detail oder eigenes submit_result")
                # A review child must not be released for arbitrary prose. The
                # actual backend return was confirmed before normal tool dispatch;
                # its one submit call must match the proposed result byte for byte.
                if action == "submit_result":
                    from hub._services.worker_result_review import _grant_valid, _verdict_from_answer
                    from hub._services.worker_execution_evidence import _digest as answer_digest
                    if (not _grant_valid(self._review_grant)
                            or self._model_execution_pending is not None
                            or self._model_execution_candidate is None
                            or self._review_grant._last_answer_sha256 is None
                            or answer_digest(self._review_grant._last_answer) !=
                               self._review_grant._last_answer_sha256
                            or _verdict_from_answer(self._review_grant._last_answer,
                                                    self.task_id, args.get("result")) is None):
                        raise LeaseProtocolError("Reviewurteil ist nicht durch die bestätigte Modellantwort belegt")
            if action == "list":
                if set(args) - {"action"}:
                    raise WorkerTaskManageArgumentError("list_fields")
                task = self.task_snapshot()
                return (f"[{task['id']}] {task.get('priority', '')} "
                        f"{task.get('status', '')}: {task.get('title', '')}")
            if action == "detail":
                if (set(args) != {"action", "task_id"}
                        or type(args.get("task_id")) is not int
                        or args["task_id"] != self.task_id):
                    raise WorkerTaskManageArgumentError("detail_scope")
                snapshot = self.task_snapshot()
                return "\n".join(f"{key}: {value}" for key, value in snapshot.items())
            if action != "add" and (type(args.get("task_id")) is not int
                                    or args["task_id"] != self.task_id):
                raise WorkerTaskManageArgumentError("mutation_scope")
            if action in {"done", "submit_result"}:
                if set(args) - {"action", "task_id", "result"}:
                    raise LeaseProtocolError("Unbekannte Abschlussfelder")
                from hub._services.task_result_service import validate_submission
                try:
                    _, text, digest = validate_submission(
                    {"generation": self._generation, "result": args.get("result")},
                    max_chars=self._snapshot.get("result_max_chars"),
                )
                except ValueError as exc:
                    raise LeaseProtocolError(str(exc)) from None
                self._submission_expected = {"task_id": self.task_id, "fence": self._ack.fence,
                    "generation": self._generation, "task_version": self._snapshot["task_version"],
                    "result_sha256": digest, "result": text}
                try:
                    release = self._operation(self._client.submit_result,
                                              generation=self._generation, result=text,
                                              **({"_review_binding": self} if self._review_grant is not None else {}))
                except LeaseDeniedError:
                    # A correlated explicit denial is not an ambiguous commit.
                    self._submission_expected = None
                    raise
                except LeaseSelfCheckRequiredError:
                    self._submission_expected = None
                    raise
                if (not isinstance(release, WorkerResultAck)
                        or release.release.released is not True
                        or release.release.task_id != self.task_id or release.release.fence != self._ack.fence
                        or release.release.outcome != "review" or release.release.status != "review"):
                    self.invalidate("submission_unconfirmed")
                    raise LeaseProtocolError("Ergebnisabgabe nicht bestätigt")
                self._completion_result = copy.deepcopy(release.record)
                self._review_ack = release.release
                self._deactivate("result_submitted", close=True)
                self._link_confirmed_model_execution()
                return f"Task #{self.task_id}: Ergebnis gespeichert; Abschlussstatus wird nach Policy ermittelt."
            if action == "update":
                allowed = {"title", "description", "category", "priority", "depends_on",
                           "assigned_to", "required_model", "assigned_slot", "status", "result_max_chars"}
                if set(args) - allowed - {"action", "task_id", "result"}:
                    raise WorkerTaskManageArgumentError("update_fields")
                changes = {key: value for key, value in args.items() if key in allowed}
                if "result_max_chars" in changes:
                    value = changes["result_max_chars"]
                    if value is not None and (type(value) is not int or not 1 <= value <= 3000):
                        raise LeaseProtocolError("result_max_chars muss null oder eine Ganzzahl von 1 bis 3000 sein")
                    current_limit = self._snapshot.get("result_max_chars")
                    if current_limit is not None and (
                            type(current_limit) is not int or not 1 <= current_limit <= 3000):
                        raise LeaseProtocolError("Aktuelles Task-Ausgabelimit kann nicht bestätigt werden")
                    if current_limit is not None and (value is None or value > current_limit):
                        raise WorkerResultLimitLockedError(WorkerResultLimitLockedError.user_message)
                if changes.get("status") in {"done", "completed"}:
                    if len(changes) != 1 or "result" not in args:
                        raise WorkerTaskManageArgumentError("update_completion")
                    # The public wrapper already performed Git/lock reads outside this lock.
                    return self._execute_task_manage_locked({"action": "submit_result", "task_id": self.task_id,
                                                            "result": args.get("result")}, _dispatch_marked=True)
                if "result" in args:
                    raise WorkerTaskManageArgumentError("update_result")
                if "status" in changes:
                    outcomes = {"pending": "return",
                                "open": "return", "blocked": "blocked"}
                    if len(changes) != 1 or changes["status"] not in outcomes:
                        raise WorkerTaskManageArgumentError("update_status")
                    outcome = outcomes[changes["status"]]
                    # Fixed reason codes; a saved partial state stays in the description.
                    note = "worker_returned_open" if outcome == "return" else "worker_blocked"
                    self._operation(self._client.release, outcome=outcome, note=note)
                    self._deactivate("status_released", close=True)
                else:
                    ack = self._operation(self._client.update, changes=changes)
                    self._adopt_task_version(ack.task_version, previous_version=ack.previous_task_version)
                    self._snapshot.update(changes)
                return f"Task #{self.task_id} aktualisiert: {', '.join(changes)}"
            if action in {"decompose", "add"}:
                if action == "add":
                    fields = {"title", "description", "priority", "depends_on", "assigned_to",
                              "category", "required_model", "assigned_slot", "result_max_chars"}
                    if set(args) - fields - {"action"}:
                        raise LeaseProtocolError("Unbekannte Teilaufgabenfelder")
                    subtasks = [{key: value for key, value in args.items() if key in fields}]
                    close_parent = False
                else:
                    allowed = {"action", "task_id", "subtasks", "close_parent", "sequential",
                               "category", "assigned_to", "assigned_slot", "required_model", "result_max_chars"}
                    if set(args) - allowed:
                        raise WorkerTaskManageArgumentError("decompose_fields")
                    subtasks = args.get("subtasks")
                    close_parent = args.get("close_parent", False)
                    if close_parent is not False:
                        raise WorkerTaskManageArgumentError("decompose_parent")
                    if isinstance(subtasks, list):
                        subtasks = [{**{key: args[key] for key in (
                                           "category", "assigned_to", "assigned_slot", "required_model", "result_max_chars")
                                       if key in args}, **item} if isinstance(item, dict) else item
                                    for item in subtasks]
                for item in subtasks if isinstance(subtasks, list) else ():
                    owner = item.get("assigned_to") if isinstance(item, dict) else None
                    # Only an exactly empty owner inherits the parent's owner in the native lease service;
                    # a blank one would be stored verbatim and leave the child unpickable.
                    if owner is not None and owner != "" and str(owner).strip().casefold() not in _SUBTASK_ASSIGNEES:
                        raise WorkerTaskManageArgumentError("decompose_assignee")
                previous_version = self._snapshot["task_version"]
                ack = self._operation(self._client.decompose, subtasks=subtasks,
                                      close_parent=close_parent, sequential=args.get("sequential", False))
                if action == "decompose":
                    self._decomposition_receipt = {
                        "task_id": self.task_id, "previous_version": previous_version,
                        "created_ids": tuple(ack.created_ids), "parent_closed": ack.parent_closed,
                    }
                self._adopt_task_version(ack.task_version, previous_version=previous_version)
                self._snapshot["description"] = (self._snapshot.get("description") or "") + (
                    f"\n[In {ack.created_count} Teilaufgaben zerlegt: {list(ack.created_ids)}]")
                if ack.parent_closed:
                    self.invalidate("decompose_closed_parent")
                    raise LeaseProtocolError("Zerlegung hat unerlaubt den Parent abgeschlossen")
                if action == "add":
                    return f"Task #{ack.created_ids[0]} erstellt: {subtasks[0]['title']}"
                return (f"Task #{self.task_id} in {ack.created_count} Teilaufgaben zerlegt: "
                        f"IDs {list(ack.created_ids)}")
            raise LeaseProtocolError("Unbekannte Task-Aktion")
