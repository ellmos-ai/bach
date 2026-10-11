"""Bounded observations of the real selector; never authority to acquire a task."""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone

SCHEMA = "bach.worker-queue.v1"
REJECTIONS = frozenset({
    "slot_binding", "model_binding", "explicit_slot_required", "pickup_filter",
    "pickup_category", "pickup_priority", "pickup_tags", "excluded_tag",
    "ownership", "deferred_version", "changed_selection", "held", "not_claimable",
    "creator_priority", "stale_task_version", "already_held_by_caller",
    "conflict",
})
ACQUIRE_DENIALS = frozenset({"held", "not_claimable", "creator_priority",
                           "stale_task_version", "already_held_by_caller", "conflict"})
REASONS = frozenset({
    "task_acquired", "empty_queue", "selection_excluded", "acquire_denied",
    "selection_error",
})
_STATE_REASONS = {"acquired": {"task_acquired"},
                  "waiting": {"empty_queue", "selection_excluded", "acquire_denied"},
                  "error": {"selection_error"}}
_COUNTERS = ("candidate_count", "matched_count", "attempted_count", "scanned_pages")
log = logging.getLogger(__name__)


def project_selection_policy(raw):
    """Bounded read-only configuration, separate from editable fields and grants."""
    if (not isinstance(raw, dict) or raw.get("schema") != "bach.worker-selection.v1"
            or type(raw.get("require_assigned_slot")) is not bool):
        return None
    pickup = raw.get("pickup_filter")
    if not isinstance(pickup, dict) or type(pickup.get("enabled")) is not bool:
        return None
    projected = {"enabled": pickup["enabled"]}
    for key in ("categories", "priorities", "tags", "exclude_tags"):
        values = pickup.get(key)
        if (not isinstance(values, list) or len(values) > 64 or any(
                not isinstance(value, str) or len(value) > 100 or "\x00" in value for value in values)):
            return None
        projected[key] = list(values)
    return {"schema": raw["schema"], "require_assigned_slot": raw["require_assigned_slot"],
            "pickup_filter": projected,
            "unrouted_ownership": ("explicit_pickup_filter" if pickup["enabled"]
                                  else "bach_or_own_worker_role")}


def worker_selection_policy(worker):
    pickup = worker.get("pickup_filter")
    if not isinstance(pickup, dict):
        pickup = {}
    raw = {"schema": "bach.worker-selection.v1",
           "require_assigned_slot": worker.get("require_assigned_slot") is True,
           "pickup_filter": {"enabled": pickup.get("enabled", False),
                            **{key: pickup.get(key) or [] for key in
                               ("categories", "priorities", "tags", "exclude_tags")}}}
    result = project_selection_policy(raw)
    if result is None:
        raise ValueError("Worker-Auswahlfilter ist ungültig")
    return result


def queue_waiting_activity(raw):
    """Readable fallback for existing clients that display current_activity."""
    report = project_queue_status(raw)
    if report is None or report["state"] != "waiting":
        return "Warte auf eine passende übernehmbare Aufgabe"
    labels = {
        "pickup_category": "Kategorie", "pickup_priority": "Priorität",
        "pickup_tags": "erforderliche Tags", "excluded_tag": "ausgeschlossene Tags",
        "pickup_filter": "Auswahlfilter", "slot_binding": "Slot", "model_binding": "Modell",
        "explicit_slot_required": "Slotzuweisung fehlt", "ownership": "Zuständigkeit",
        "deferred_version": "unveränderte Rückgabe", "changed_selection": "Task geändert",
        "held": "fremde Lease", "not_claimable": "Status/Abhängigkeiten",
        "creator_priority": "Creator-Schonfrist", "stale_task_version": "Taskversion",
        "already_held_by_caller": "bereits gehalten", "conflict": "Übernahmekonflikt",
    }
    reasons = ", ".join(f"{labels[key]}: {count}" for key, count in report["rejected_counts"].items())
    prefix = "Keine offenen Kandidaten" if report["reason"] == "empty_queue" else "Keine übernehmbare Aufgabe"
    counts = f'{report["candidate_count"]} Kandidaten, {report["matched_count"]} Auswahlmatches'
    stamp = datetime.fromisoformat(report["observed_at"].replace("Z", "+00:00"))
    checked = stamp.astimezone(timezone.utc).strftime("%H:%M:%S UTC")
    return f"{prefix}: {counts}" + (f"; {reasons}" if reasons else "") + f" · Task-API · {checked}"


def project_queue_status(raw):
    """Allow only counters and native task IDs, never task text or lease material."""
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    if (not isinstance(raw.get("reason"), str) or raw["reason"] not in REASONS
            or not isinstance(raw.get("state"), str) or raw["state"] not in {"acquired", "waiting", "error"}):
        return None
    if raw["reason"] not in _STATE_REASONS[raw["state"]]:
        return None
    if (raw.get("source") != "canonical_task_api" or not isinstance(raw.get("authority_mode"), str)
            or raw["authority_mode"] not in {"local", "remote"}):
        return None
    if type(raw.get("scan_complete")) is not bool:
        return None
    for key in _COUNTERS:
        if type(raw.get(key)) is not int or not 0 <= raw[key] <= 1_000_000:
            return None
    if not raw["attempted_count"] <= raw["matched_count"] <= raw["candidate_count"]:
        return None
    observed = raw.get("observed_at")
    if not isinstance(observed, str) or len(observed) > 40:
        return None
    try:
        stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
    except ValueError:
        return None
    rejected = raw.get("rejected_counts")
    if not isinstance(rejected, dict) or set(rejected) - REJECTIONS:
        return None
    if any(type(value) is not int or not 0 <= value <= 1_000_000 for value in rejected.values()):
        return None
    if sum(rejected.values()) > raw["candidate_count"]:
        return None
    result = {key: raw[key] for key in (
        "schema", "state", "reason", "source", "authority_mode", "observed_at",
        "scan_complete", *_COUNTERS,
    )}
    result["rejected_counts"] = dict(rejected)
    for key in ("last_candidate_task_id", "selected_task_id"):
        value = raw.get(key)
        if value is not None:
            if type(value) is not int or value <= 0:
                return None
            result[key] = value
    if result["state"] == "acquired" and "selected_task_id" not in result:
        return None
    if result["state"] != "acquired" and "selected_task_id" in result:
        return None
    if result["reason"] == "empty_queue" and (
            result["candidate_count"] or not result["scan_complete"] or result["scanned_pages"] != 1):
        return None
    if result["reason"] == "selection_excluded" and (
            not result["candidate_count"] or result["matched_count"] or not result["scan_complete"]):
        return None
    if result["reason"] in {"task_acquired", "acquire_denied"} and not result["attempted_count"]:
        return None
    if result["state"] in {"acquired", "error"} and result["scan_complete"]:
        return None
    if result["state"] in {"waiting", "acquired"}:
        acquired = int(result["state"] == "acquired")
        attempted_rejections = sum(rejected.get(key, 0) for key in ACQUIRE_DENIALS | {"changed_selection"})
        if (sum(rejected.values()) + acquired != result["candidate_count"]
                or attempted_rejections + acquired != result["attempted_count"]
                or result["attempted_count"] != result["matched_count"]):
            return None
    return result


class QueueObservation:
    def __init__(self, client, callback=None, clock=None):
        self.callback = callback
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.record = {
            "schema": SCHEMA, "source": "canonical_task_api",
            "authority_mode": client.mode, "state": "error", "reason": "selection_error",
            "scan_complete": False, "candidate_count": 0, "matched_count": 0,
            "attempted_count": 0, "scanned_pages": 0, "rejected_counts": {},
        }

    def candidate(self, task_id):
        self.record["candidate_count"] += 1
        self.record["last_candidate_task_id"] = task_id

    def reject(self, reason):
        assert reason in REJECTIONS
        counts = self.record["rejected_counts"]
        counts[reason] = counts.get(reason, 0) + 1

    def acquired(self, binding):
        self.record.update(state="acquired", reason="task_acquired", selected_task_id=binding.task_id)

    def waiting(self):
        reason = ("empty_queue" if not self.record["candidate_count"] else
                  "selection_excluded" if not self.record["matched_count"] else "acquire_denied")
        self.record.update(state="waiting", reason=reason, scan_complete=True)

    def denied(self, reason):
        self.reject(reason)
        self.record.update(state="waiting", reason="acquire_denied")

    def publish(self):
        if self.callback is None:
            return
        try:
            record = {**self.record, "observed_at": self.clock().astimezone(timezone.utc).isoformat()}
            projected = project_queue_status(record)
            if projected is None:
                return
            self.callback(copy.deepcopy(projected))
        except Exception:  # noqa: BLE001 -- telemetry must not lose an acquired lease.
            # Observation failure must not lose an already acquired capability.
            log.warning("Worker queue observation could not be published")
