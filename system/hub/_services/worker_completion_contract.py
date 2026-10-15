"""Predeclared, bounded task criteria; model assertions are never evidence."""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = "bach.worker-task-contract.v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./-]{1,240}\Z")


def parse_contract(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 8192:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or set(data) != {"schema", "criteria"} or data["schema"] != SCHEMA:
        return None
    criteria = data["criteria"]
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 16:
        return None
    for item in criteria:
        if not isinstance(item, dict):
            return None
        kind = item.get("kind")
        if kind == "result_min_chars":
            if set(item) != {"kind", "min_chars"} or type(item["min_chars"]) is not int or not 1 <= item["min_chars"] <= 3000:
                return None
        elif kind == "git_blob_sha256":
            if (set(item) != {"kind", "path", "sha256"}
                    or type(item["path"]) is not str or not _PATH.fullmatch(item["path"])
                    or item["path"].startswith("./") or "//" in item["path"]
                    or type(item["sha256"]) is not str or not _HEX.fullmatch(item["sha256"])):
                return None
        else:
            return None
    return data


def canonical_contract(value):
    if not isinstance(value, dict):
        raise ValueError("Strukturierter Taskvertrag erforderlich")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    if parse_contract(encoded) is None:
        raise ValueError("Taskvertrag hat unbekannte oder ungültige Kriterien")
    return encoded


def evaluate_contract(raw, *, result, snapshot, repo_root=None, worktrees_dir=None):
    """Check actual result and clean, registered Git tree, with no writes."""
    if raw is None:
        return {"availability": "unavailable", "reason": "contract_not_predeclared", "met": False}
    contract = parse_contract(raw)
    if contract is None:
        return {"availability": "unavailable", "reason": "contract_invalid", "met": False}
    if not isinstance(result, str) or not isinstance(snapshot, dict) or snapshot.get("availability") != "available":
        return {"availability": "unavailable", "reason": "contract_scope_unavailable", "met": False}
    for index, item in enumerate(contract["criteria"]):
        if item["kind"] == "result_min_chars":
            if len(result.strip()) < item["min_chars"]:
                return {"availability": "available", "reason": "criterion_failed", "criterion_index": index, "met": False}
            continue
        # The registered task tree, not a worker-supplied path, selects Git.
        try:
            from .chat.worker_write_guard import _paths, _registered_tree, _scope_git
            repo, root = _paths(repo_root, worktrees_dir)
            task_id = snapshot.get("task_id")
            if type(task_id) is not int or task_id <= 0:
                raise ValueError("scope task missing")
            tree = _registered_tree(repo, root, task_id)
            path = item["path"]
            code, raw = _scope_git(["show", f"HEAD:{path}"], tree, allowed=(0, 128), timeout=8)
            if code != 0 or len(raw) > 1024 * 1024:
                return {"availability": "available", "reason": "criterion_failed", "criterion_index": index, "met": False}
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                return {"availability": "available", "reason": "criterion_failed", "criterion_index": index, "met": False}
        except Exception:
            return {"availability": "unavailable", "reason": "contract_git_unavailable", "met": False}
    return {"availability": "available", "reason": "predeclared_criteria_met", "met": True}
