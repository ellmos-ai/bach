"""Strict, read-only GitHub review observation for one pinned PR head."""
from __future__ import annotations

import json
import os
import re
import subprocess

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_URL = re.compile(r"https://github\.com/ellmos-ai/bach/pull/([1-9][0-9]*)\Z")


def _unavailable(reason):
    return {"availability": "unavailable", "reason": reason, "status": "pending"}


def canonical_contract(value):
    """Validate a predeclared PR requirement without observing GitHub."""
    if (not isinstance(value, dict) or set(value) != {"schema", "pull_url", "required_checks",
            "min_approvals", "require_merged"} or value.get("schema") != "bach.worker-github-review-contract.v1"
            or type(value.get("pull_url")) is not str or not _URL.fullmatch(value["pull_url"])
            or type(value.get("required_checks")) is not list or not 1 <= len(value["required_checks"]) <= 32
            or any(type(name) is not str or not name or name.strip() != name or len(name) > 180
                   for name in value["required_checks"])
            or len(set(value["required_checks"])) != len(value["required_checks"])
            or type(value.get("min_approvals")) is not int or not 1 <= value["min_approvals"] <= 20
            or type(value.get("require_merged")) is not bool):
        raise ValueError("GitHub-Reviewvertrag ist ungültig")
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _public_observer(number):
    """Use the already configured native gh authority, without issuing tokens."""
    env = os.environ.copy()
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_REPO="ellmos-ai/bach")
    def get(args):
        completed = subprocess.run(["gh", *args], capture_output=True, text=True,
                                   timeout=12, check=False, env=env)
        if completed.returncode != 0 or len(completed.stdout) > 1024 * 1024:
            raise ValueError("GitHub observation unavailable")
        return json.loads(completed.stdout)
    base = "repos/ellmos-ai/bach"
    pull = get(["api", f"{base}/pulls/{number}"])
    reviews = get(["api", f"{base}/pulls/{number}/reviews?per_page=100"])
    head = pull.get("head", {}).get("sha") if isinstance(pull, dict) else None
    checks = (get(["api", f"{base}/commits/{head}/check-runs?per_page=100"])
              if type(head) is str and _SHA.fullmatch(head) else None)
    gate = get(["pr", "view", str(number), "--repo", "ellmos-ai/bach",
                "--json", "reviewDecision,mergeStateStatus"])
    if (not isinstance(reviews, list) or len(reviews) >= 100
            or not isinstance(checks, dict) or not isinstance(checks.get("check_runs"), list)
            or checks.get("total_count") != len(checks["check_runs"])
            or not isinstance(gate, dict)
            or set(gate) != {"reviewDecision", "mergeStateStatus"}):
        raise ValueError("GitHub pagination incomplete")
    return {"pull": pull, "reviews": reviews, "checks": checks["check_runs"], "gate": gate}


def observe_github_review(contract, *, head_oid, task_id, result_revision, observer=None):
    """Require exact PR/head, final approval and all declared check contexts."""
    if (not isinstance(contract, dict) or set(contract) != {"schema", "pull_url", "required_checks", "min_approvals", "require_merged"}
            or contract.get("schema") != "bach.worker-github-review-contract.v1"
            or not isinstance(contract.get("pull_url"), str)):
        return _unavailable("github_contract_missing")
    match = _URL.fullmatch(contract["pull_url"])
    checks = contract.get("required_checks")
    if (not match or type(head_oid) is not str or not _SHA.fullmatch(head_oid)
            or not isinstance(checks, list) or not checks or len(checks) > 32
            or any(type(name) is not str or not name or name.strip() != name or len(name) > 180 for name in checks)
            or len(set(checks)) != len(checks)
            or type(contract.get("min_approvals")) is not int or not 1 <= contract["min_approvals"] <= 20
            or type(contract.get("require_merged")) is not bool):
        return _unavailable("github_contract_invalid")
    observer = observer or _public_observer
    try:
        seen = observer(int(match[1]))
        if not isinstance(seen, dict) or set(seen) != {"pull", "reviews", "checks", "gate"}:
            raise ValueError("observation incomplete")
        pull, reviews, runs, gate = (seen["pull"], seen["reviews"],
                                    seen["checks"], seen["gate"])
        if (not isinstance(pull, dict) or pull.get("html_url") != contract["pull_url"]
                or pull.get("head", {}).get("sha") != head_oid
                or pull.get("base", {}).get("repo", {}).get("full_name") != "ellmos-ai/bach"
                or pull.get("state") != ("closed" if contract["require_merged"] else "open")
                or pull.get("draft") is not False):
            return _unavailable("github_pr_not_current")
        if contract["require_merged"] and not pull.get("merged_at"):
            return _unavailable("github_merge_required")
        if (not isinstance(gate, dict) or set(gate) != {"reviewDecision", "mergeStateStatus"}
                or type(gate["mergeStateStatus"]) is not str):
            return _unavailable("github_observation_invalid")
        author = pull.get("user", {}).get("login")
        if (type(author) is not str or not author
                or not isinstance(reviews, list) or not isinstance(runs, list)
                or len(reviews) > 1000 or len(runs) > 1000):
            return _unavailable("github_observation_invalid")
        latest = {}
        for review in reviews:
            if not isinstance(review, dict):
                continue
            login = review.get("user", {}).get("login")
            timestamp, identifier = review.get("submitted_at"), review.get("id")
            if (type(login) is not str or not login or type(timestamp) is not str
                    or not timestamp or type(identifier) is not int or identifier <= 0):
                return _unavailable("github_review_invalid")
            if login not in latest or (timestamp, identifier) > latest[login][0]:
                latest[login] = ((timestamp, identifier), review)
        def authorized(login, review):
            return (login.casefold() != author.casefold()
                and review.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"})
        if any(review.get("state") == "CHANGES_REQUESTED" and authorized(login, review)
               for login, (_, review) in latest.items()):
            return {"availability": "available", "status": "rejected",
                    "task_id": task_id, "result_revision": result_revision,
                    "pull_url": contract["pull_url"], "head_oid": head_oid}
        if (gate["reviewDecision"] not in {None, "", "APPROVED"}
                or (not contract["require_merged"] and gate["mergeStateStatus"] != "CLEAN")):
            return _unavailable("github_merge_requirements_unmet")
        approvals = sum(review.get("state") == "APPROVED"
            and review.get("commit_id") == head_oid
            and authorized(login, review)
            for login, (_, review) in latest.items())
        if approvals < contract["min_approvals"]:
            return _unavailable("github_approval_missing")
        observed = {}
        for run in runs:
            if not isinstance(run, dict) or run.get("head_sha") != head_oid:
                continue
            name = run.get("name")
            if type(name) is str:
                observed[name] = observed.get(name, True) and run.get("conclusion") == "success"
        if any(observed.get(name) is not True for name in checks):
            return _unavailable("github_checks_missing")
        return {"availability": "available", "status": "verified", "task_id": task_id,
                "result_revision": result_revision, "pull_url": contract["pull_url"],
                "head_oid": head_oid, "approved_count": approvals, "required_checks": list(checks)}
    except Exception:
        return _unavailable("github_observer_unavailable")
