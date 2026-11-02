#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deployment Preflight & Rollback Boundary Enforcement Tool (#3717).

Implements the "Abnahme und Rollback" contract from `OCEAN-TRANSFER-PLAN.md`:
  1. Verifies clean source commit (`git status --porcelain`), captures file and archive
     SHA-256 hashes, verifies identical pin configuration (`kit_manifest.json` vs.
     `docs/contracts/gui-consumer.v1.json`), and snapshots current release identity and
     service configuration.
  2. Technically enforces the rollback boundary via a strict positive allowlist of
     restorable code/config paths (`RESTORABLE_PATHS_ALLOWLIST`) so rollback can NEVER
     touch `bach.db` (TaskDB) or user data.
  3. Emits an artifactable JSON receipt (`bach.deploy-rollback-preflight.v1`) and
     explicitly records the scope boundary: a passing test or preflight run does NOT
     replace worker, browser, or tray acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PREFLIGHT_SCHEMA = "bach.deploy-rollback-preflight.v1"

# Strict positive allowlist of code/config prefixes eligible for code rollback.
RESTORABLE_PATHS_ALLOWLIST: tuple[str, ...] = (
    "system/gui/dist/",
    "system/gui/kit_manifest.json",
    "system/gui/gui-consumer.v1.json",
    "docs/contracts/gui-consumer.v1.json",
    "system/hub/_services/",
    "system/policy/",
    "system/core/",
    "system/tools/",
    "DEPRICATED.md",
    "OCEAN-TRANSFER-PLAN.md",
)

# Hard-protected TaskDB and user-data tokens that must NEVER be touched by rollback.
FORBIDDEN_ROLLBACK_TOKENS: tuple[str, ...] = (
    "bach.db",
    "bach.db-wal",
    "bach.db-shm",
    ".bach/",
    "data/",
    "user/",
    "secrets/",
    "credentials/",
    ".env",
    "task_history",
)

CRITICAL_HASH_FILES: tuple[str, ...] = (
    "system/gui/kit_manifest.json",
    "system/gui/gui-consumer.v1.json",
    "system/hub/_services/ocean_stack_bridge.py",
    "system/hub/_services/policy_registry_adapter.py",
    "DEPRICATED.md",
    "OCEAN-TRANSFER-PLAN.md",
)


def _bach_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_rollback_paths(candidate_paths: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Enforce the positive allowlist for rollback paths; reject TaskDB and user data fail-closed."""
    allowed: list[str] = []
    rejected: list[dict[str, str]] = []

    for raw in candidate_paths:
        norm = raw.replace("\\", "/").strip()
        while norm.startswith("./"):
            norm = norm[2:]
        if not norm or ".." in norm.split("/"):
            rejected.append({"path": raw, "reason": "path_traversal_or_empty"})
            continue

        lower_norm = norm.lower()
        if any(tok in lower_norm for tok in FORBIDDEN_ROLLBACK_TOKENS):
            rejected.append({"path": raw, "reason": "protected_taskdb_or_user_data"})
            continue

        if any(norm == prefix.rstrip("/") or norm.startswith(prefix) for prefix in RESTORABLE_PATHS_ALLOWLIST):
            allowed.append(norm)
        else:
            rejected.append({"path": raw, "reason": "not_in_positive_restorable_allowlist"})

    return {
        "ok": len(rejected) == 0,
        "allowlist": list(RESTORABLE_PATHS_ALLOWLIST),
        "allowed_paths": allowed,
        "rejected_paths": rejected,
    }


def check_git_state(repo_root: Path) -> dict[str, Any]:
    """Inspect git HEAD commit and working tree cleanliness."""
    try:
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        head_commit = head_proc.stdout.strip() if head_proc.returncode == 0 else None
        dirty_lines = [ln for ln in status_proc.stdout.splitlines() if ln.strip()]
        return {
            "git_available": head_proc.returncode == 0,
            "head_commit": head_commit,
            "clean_worktree": len(dirty_lines) == 0,
            "dirty_count": len(dirty_lines),
            "dirty_files": dirty_lines[:25],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "git_available": False,
            "head_commit": None,
            "clean_worktree": False,
            "dirty_count": None,
            "error": str(exc),
        }


def verify_pin_parity(repo_root: Path) -> dict[str, Any]:
    """Compare GUI consumer contract pins between `kit_manifest.json` and `gui-consumer.v1.json`."""
    kit_path = repo_root / "system" / "gui" / "kit_manifest.json"
    contract_path = repo_root / "system" / "gui" / "gui-consumer.v1.json"
    if not contract_path.is_file():
        contract_path = repo_root / "docs" / "contracts" / "gui-consumer.v1.json"
    if not kit_path.is_file() or not contract_path.is_file():
        return {
            "pins_identical": False,
            "reason": "missing_manifest_or_contract",
        }
    try:
        kit = json.loads(kit_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        src = contract.get("source") or contract.get("pin") or {}
        kit_ver = kit.get("version")
        con_ver = contract.get("version") or src.get("release_version")
        kit_commit = kit.get("pinned_source_commit") or kit.get("source_commit")
        con_commit = src.get("commit") or src.get("source_commit")
        kit_sha = kit.get("release_archive_sha256") or kit.get("archive_sha256")
        con_sha = src.get("archive_sha256")
        version_match = bool(kit_ver and kit_ver == con_ver)
        commit_match = bool(kit_commit and kit_commit == con_commit)
        archive_match = bool(kit_sha and kit_sha == con_sha)
        return {
            "pins_identical": bool(version_match and commit_match and archive_match),
            "release_version": kit_ver,
            "source_commit": kit_commit,
            "archive_sha256": kit_sha,
            "version_match": version_match,
            "commit_match": commit_match,
            "archive_match": archive_match,
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "pins_identical": False,
            "reason": f"parse_error: {exc}",
        }


def run_deploy_preflight(
    repo_root: Path | None = None,
    *,
    require_clean_git: bool = False,
    artifact_output: Path | None = None,
) -> dict[str, Any]:
    """Execute deployment preflight and rollback boundary verification (#3717)."""
    root = repo_root or _bach_root()
    git_state = check_git_state(root)
    pin_parity = verify_pin_parity(root)

    file_hashes: dict[str, str | None] = {}
    for rel in CRITICAL_HASH_FILES:
        file_hashes[rel] = _sha256_file(root / rel)

    rollback_boundary_self_test = validate_rollback_paths(
        [
            "system/gui/kit_manifest.json",
            "docs/contracts/gui-consumer.v1.json",
            "DEPRICATED.md",
        ]
    )
    forbidden_probe = validate_rollback_paths(["~/.bach/bach.db", "data/user_secrets.json"])

    service_snapshot = {
        "BACH_POLICY_REGISTRY_ENABLED": os.environ.get("BACH_POLICY_REGISTRY_ENABLED", "0"),
        "ELLMOS_SYSTEM_GUI_DIST": os.environ.get("ELLMOS_SYSTEM_GUI_DIST"),
        "ELLMOS_MODULES_CATALOG": os.environ.get("ELLMOS_MODULES_CATALOG"),
        "python_executable": sys.executable,
        "platform": sys.platform,
    }

    git_ok = git_state["clean_worktree"] if require_clean_git else bool(git_state["git_available"])
    preflight_ok = (
        git_ok
        and pin_parity.get("pins_identical") is True
        and all(v is not None for v in file_hashes.values())
        and rollback_boundary_self_test["ok"] is True
        and forbidden_probe["ok"] is False
    )

    receipt: dict[str, Any] = {
        "schema": PREFLIGHT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "preflight_ok": preflight_ok,
        "git_state": git_state,
        "pin_parity": pin_parity,
        "file_hashes": file_hashes,
        "service_snapshot": service_snapshot,
        "rollback_boundary": {
            "mode": "positive_allowlist_only",
            "restorable_allowlist": list(RESTORABLE_PATHS_ALLOWLIST),
            "forbidden_tokens": list(FORBIDDEN_ROLLBACK_TOKENS),
            "taskdb_and_userdata_excluded": True,
            "self_test_allowlist_ok": rollback_boundary_self_test["ok"],
            "self_test_forbidden_blocked": not forbidden_probe["ok"],
        },
        "scope_boundary": {
            "preflight_replaces_worker_acceptance": False,
            "preflight_replaces_browser_acceptance": False,
            "preflight_replaces_tray_acceptance": False,
            "note": (
                "Ein erfolgreicher Test- oder Preflight-Lauf ersetzt keinen produktiven "
                "Worker-Lauf und keine Browser- oder Tray-Abnahme (OCEAN-TRANSFER-PLAN.md)."
            ),
        },
    }

    if artifact_output is not None:
        artifact_output.parent.mkdir(parents=True, exist_ok=True)
        artifact_output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BACH Deployment Preflight & Rollback Boundary Tool (#3717).")
    parser.add_argument("--require-clean-git", action="store_true", help="Fail if git worktree has uncommitted files")
    parser.add_argument("--output", type=Path, help="Write JSON preflight receipt to file")
    parser.add_argument("--check-rollback-path", action="append", default=[], help="Validate candidate rollback path")
    parser.add_argument("--json", action="store_true", help="Print full JSON receipt")
    args = parser.parse_args(argv)

    if args.check_rollback_path:
        check = validate_rollback_paths(args.check_rollback_path)
        print(json.dumps(check, indent=2))
        return 0 if check["ok"] else 1

    receipt = run_deploy_preflight(
        require_clean_git=args.require_clean_git,
        artifact_output=args.output,
    )
    if args.json:
        print(json.dumps(receipt, indent=2))
    else:
        print(
            f"Deploy Preflight: ok={receipt['preflight_ok']} | "
            f"head={receipt['git_state'].get('head_commit')} | "
            f"pins_identical={receipt['pin_parity'].get('pins_identical')} | "
            f"taskdb_excluded={receipt['rollback_boundary']['taskdb_and_userdata_excluded']}"
        )
    return 0 if receipt["preflight_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
