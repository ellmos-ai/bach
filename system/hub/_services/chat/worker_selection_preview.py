"""Read-only observations of the native selector, never an acquisition decision."""
from __future__ import annotations

import copy
import re
from collections import Counter
from datetime import datetime, timezone
from time import monotonic

from hub._services.task_schema import parse_task_dependency_ids
from .worker_lease_binding import WorkerLeaseBinding
from .worker_queue_status import REJECTIONS

SCHEMA = "bach.worker-selection-preview.v1"
MAX_ITEMS = 100
MAX_REMOTE_READS = 128
PREVIEW_SECONDS = 5.0
_VERSION = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
OBSERVATIONS = frozenset({
    "lease_held", "status_not_pending", "dependencies_unfinished",
    "dependencies_invalid", "dependencies_unavailable", "task_changed",
    "lease_unavailable", "review_route_unchecked",
})
UNCHECKED = (
    "atomic_acquire", "creator_priority", "review_authority", "provider",
    "source_register", "tool_rights", "resources", "running_profile", "startup_recovery",
)


class PreviewUnavailable(RuntimeError):
    """A bounded observation could not be tied to its native source."""


class _ObservationBudget:
    """One request budget, including failed reads and the initial page/pin.

    Check time on both sides of each synchronous read. An in-flight transport
    retains its own timeout; no further read starts after the deadline.
    """

    def __init__(self, client):
        self.remote = client.mode == "remote"
        self.deadline = monotonic() + PREVIEW_SECONDS
        self.reads = 0

    def check(self):
        if monotonic() >= self.deadline:
            raise PreviewUnavailable("Zeitbudget der Auswahlvorschau ist erschöpft")

    def read(self, method, *args, **kwargs):
        self.check()
        if self.remote and self.reads >= MAX_REMOTE_READS:
            raise PreviewUnavailable("Lesebudget der Auswahlvorschau ist erschöpft")
        self.reads += 1
        try:
            return method(*args, **kwargs)
        finally:
            self.check()


def _task(task):
    if (not isinstance(task, dict) or type(task.get("id")) is not int or task["id"] <= 0
            or not isinstance(task.get("task_version"), str)
            or not _VERSION.fullmatch(task["task_version"])
            or not isinstance(task.get("status"), str)):
        raise PreviewUnavailable("Kanonischer Taskbeleg ist ungültig")
    return task


def preview_worker_selection(client, slot, *, configuration_version, execution_profile_version,
                             deferred_versions=None, limit=50, offset=0):
    """Use the *same* selector on current canonical candidates without Acquire.

    Counters describe the requested page, not the complete queue. A selector
    match is explicitly not a grant. No review grants, tools, model calls or
    durable queue/controller updates occur here.
    """
    if (not isinstance(slot, dict) or not isinstance(slot.get("id"), str)
            or not _SAFE_ID.fullmatch(slot["id"])
            or not isinstance(configuration_version, str)
            or not _VERSION.fullmatch(configuration_version)
            or not isinstance(execution_profile_version, str)
            or not _VERSION.fullmatch(execution_profile_version)
            or getattr(client, "mode", None) not in {"local", "remote"}
            or type(limit) is not int or not 1 <= limit <= MAX_ITEMS
            or type(offset) is not int or not 0 <= offset <= 100_000):
        raise ValueError("Ungültige Vorschauanfrage")
    slot = copy.deepcopy(slot)
    budget = _ObservationBudget(client)
    deferred = dict(deferred_versions or {})
    explicit = slot.get("task_id")
    pinned = explicit not in (None, "", 0, "0")
    if pinned:
        if isinstance(explicit, str) and explicit.isdecimal():
            explicit = int(explicit)
        if type(explicit) is not int or explicit <= 0 or offset != 0:
            raise ValueError("Ungültige fest gebundene Task-ID oder Seitenposition")
        tasks = [_task(budget.read(client.task_snapshot, explicit))]
        total, has_more = 1, False
    else:
        page = budget.read(client.task_candidates, limit=limit, offset=offset)
        if (not isinstance(page, dict) or not isinstance(page.get("tasks"), list)
                or len(page["tasks"]) > limit or type(page.get("has_more")) is not bool
                or page.get("offset") != offset or type(page.get("total")) is not int
                or page["total"] < 0):
            raise PreviewUnavailable("Kanonische Kandidatenseite ist ungültig")
        tasks = [_task(t) for t in page["tasks"]]
        total, has_more = page["total"], page["has_more"]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise PreviewUnavailable("Kandidatenseite enthält doppelte Task-IDs")
    dependency_cache = {}
    items = []
    counts = Counter()
    for task in tasks:
        budget.check()
        # Explicit pins use the native explicit path, which deliberately does
        # not apply ordinary automatic ownership/deferred-version rules.
        review_pin = pinned and str(task.get("source") or "").startswith("worker-result-review:v1:")
        if review_pin:
            reason = None  # A private review grant may use a different native route.
        elif pinned:
            reason = (None if WorkerLeaseBinding._matches_slot(task, slot)
                      else "changed_selection")
        else:
            reason = WorkerLeaseBinding._selection_rejection_reason(task, slot)
            if reason is None and deferred.get(task["id"]) == task["task_version"]:
                reason = "deferred_version"
        if reason is not None and reason not in REJECTIONS:
            raise PreviewUnavailable("Selector meldet einen unbekannten Ausschluss")
        observations = []
        if str(task["status"]).strip().lower() not in {"pending", "open"}:
            observations.append("status_not_pending")
        if review_pin:
            observations.append("review_route_unchecked")
        try:
            lease = budget.read(client.read, task["id"])
            if lease.task_version != task["task_version"]:
                observations.append("task_changed")
            if lease.leased:
                observations.append("lease_held")
        except PreviewUnavailable:
            raise
        except Exception:  # Observation failure never becomes permission.
            observations.append("lease_unavailable")
        dependency_ids, invalid = parse_task_dependency_ids(task.get("depends_on"))
        if invalid or len(dependency_ids) > 32:
            observations.append("dependencies_invalid")
        else:
            for dep in dependency_ids:
                if dep not in dependency_cache:
                    if len(dependency_cache) >= 256:
                        observations.append("dependencies_unavailable")
                        break
                    try:
                        dependency_cache[dep] = _task(budget.read(client.task_snapshot, dep))["status"]
                    except PreviewUnavailable:
                        raise
                    except Exception:
                        dependency_cache[dep] = None
                status = dependency_cache[dep]
                if status is None:
                    observations.append("dependencies_unavailable")
                elif status != "done":  # Same exact terminal value as task_schema.
                    observations.append("dependencies_unfinished")
        observations = sorted(set(observations))
        if reason:
            counts[reason] += 1
        for observation in observations:
            counts[observation] += 1
        selection = "unconfirmed" if review_pin else "excluded" if reason else "match"
        items.append({"task_id": task["id"], "selection": selection,
                      "selection_reason": reason, "observations": observations})
    budget.check()
    return {
        "schema": SCHEMA, "worker_id": slot["id"],
        "configuration_version": configuration_version,
        "execution_profile_version": execution_profile_version,
        "source": "canonical_task_api", "authority_mode": client.mode,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "explicit_pin" if pinned else "ordinary_candidates",
        "offset": offset, "limit": limit, "candidate_count": len(items),
        "reported_total": total, "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "matched_count": sum(item["selection"] == "match" for item in items),
        "reason_counts": dict(counts), "items": items,
        "claimability": "not_checked", "unchecked_gates": list(UNCHECKED),
        "snapshot_atomic": False, "configuration_saved": False,
    }


def project_selection_preview(raw, worker_id):
    """Strict secret-free transport boundary; never forward arbitrary data."""
    if (not isinstance(raw, dict) or raw.get("schema") != SCHEMA
            or raw.get("worker_id") != worker_id
            or not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id)
            or raw.get("source") != "canonical_task_api"
            or not isinstance(raw.get("authority_mode"), str)
            or raw["authority_mode"] not in {"local", "remote"}
            or not isinstance(raw.get("mode"), str)
            or raw["mode"] not in {"explicit_pin", "ordinary_candidates"}
            or raw.get("claimability") != "not_checked"
            or raw.get("unchecked_gates") != list(UNCHECKED)
            or raw.get("snapshot_atomic") is not False
            or raw.get("configuration_saved") is not False
            or not isinstance(raw.get("configuration_version"), str)
            or not _VERSION.fullmatch(raw["configuration_version"])
            or not isinstance(raw.get("execution_profile_version"), str)
            or not _VERSION.fullmatch(raw["execution_profile_version"])):
        return None
    for field in ("offset", "limit", "candidate_count", "reported_total", "matched_count"):
        if type(raw.get(field)) is not int or raw[field] < 0:
            return None
    if (not 1 <= raw["limit"] <= MAX_ITEMS or raw["offset"] > 100_000
            or raw["candidate_count"] > raw["limit"]
            or raw["candidate_count"] > raw["reported_total"]
            or raw["matched_count"] > raw["candidate_count"]
            or type(raw.get("has_more")) is not bool
            or (raw.get("next_offset") != raw["offset"] + raw["limit"] if raw["has_more"]
                else raw.get("next_offset") is not None)):
        return None
    if raw["mode"] == "explicit_pin" and (
            raw["offset"] != 0 or raw["candidate_count"] != 1
            or raw["reported_total"] != 1 or raw["has_more"]):
        return None
    stamp = raw.get("observed_at")
    if not isinstance(stamp, str) or len(stamp) > 40:
        return None
    try:
        if datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is None:
            return None
    except ValueError:
        return None
    if not isinstance(raw.get("items"), list) or len(raw["items"]) != raw["candidate_count"]:
        return None
    items, ids, counts = [], set(), Counter()
    for item in raw["items"]:
        if (not isinstance(item, dict) or type(item.get("task_id")) is not int
                or item["task_id"] <= 0 or item["task_id"] in ids
                or not isinstance(item.get("selection"), str)
                or item["selection"] not in {"match", "excluded", "unconfirmed"}):
            return None
        ids.add(item["task_id"])
        reason = item.get("selection_reason")
        if ((item["selection"] in {"match", "unconfirmed"} and reason is not None)
                or (item["selection"] == "excluded"
                    and (not isinstance(reason, str) or reason not in REJECTIONS))):
            return None
        observations = item.get("observations")
        if (not isinstance(observations, list) or len(observations) > len(OBSERVATIONS)
                or any(not isinstance(x, str) or x not in OBSERVATIONS for x in observations)
                or len(set(observations)) != len(observations)):
            return None
        if (("review_route_unchecked" in observations) != (item["selection"] == "unconfirmed")
                or (item["selection"] == "unconfirmed" and raw["mode"] != "explicit_pin")):
            return None
        if reason:
            counts[reason] += 1
        counts.update(observations)
        items.append({"task_id": item["task_id"], "selection": item["selection"],
                      "selection_reason": reason, "observations": list(observations)})
    if (sum(i["selection"] == "match" for i in items) != raw["matched_count"]
            or not isinstance(raw.get("reason_counts"), dict)
            or any(type(v) is not int for v in raw["reason_counts"].values())
            or dict(counts) != raw["reason_counts"]):
        return None
    keys = ("schema", "worker_id", "configuration_version", "execution_profile_version",
            "source", "authority_mode",
            "observed_at", "mode", "offset", "limit", "candidate_count", "reported_total",
            "has_more", "next_offset", "matched_count", "claimability", "snapshot_atomic",
            "configuration_saved")
    return {**{k: raw[k] for k in keys}, "items": items,
            "reason_counts": dict(counts), "unchecked_gates": list(UNCHECKED)}
