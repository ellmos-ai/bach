#!/usr/bin/env python3
"""Runner fuer Task #2617: tatsaechliche Testausfuehrung mit Receipt-Beleg.

Fuehrt im Worktree aus:
  1. python -m pytest system/tests/test_task_lease_commands.py -v
  2. python -m compileall -q system/hub/task.py
  3. git status --porcelain
  4. git diff --stat
Danach Gegenprobe der Receipt-Dateien (system/tests/conftest.py schreibt
Receipt-JSON plus .loaded-Marker) und Report-Ausgabe nach zwei Pfaden,
sodass die Ergebnisse ohne stdout-Zugriff nachpruefbar sind.
"""
import json
import os
import subprocess
import sys

WORKTREE = "/Users/lukas/services/bach-worktrees/task-2617"
PYTEST_RECEIPT = os.path.join(WORKTREE, "test2617_receipt.json")
REPORT_PATHS = [
    "/tmp/test2617_receipt.json",
    os.path.join(WORKTREE, "test2617_run_report.json"),
]


def run_step(label, cmd, cwd, timeout, env=None):
    entry = {"label": label, "command": cmd, "cwd": cwd, "timeout": timeout}
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True, env=env
        )
        entry["returncode"] = proc.returncode
        entry["stdout_tail"] = proc.stdout[-20000:]
        entry["stderr_tail"] = proc.stderr[-20000:]
    except Exception as exc:  # noqa: BLE001
        entry["error"] = repr(exc)
    return entry


def main():
    report = {"worktree": WORKTREE, "steps": []}

    env = os.environ.copy()
    env["TEST2617_RECEIPT"] = PYTEST_RECEIPT

    steps = [
        (
            "pytest_lease_commands",
            [sys.executable, "-m", "pytest",
             "system/tests/test_task_lease_commands.py", "-v"],
            WORKTREE,
            60,
            env,
        ),
        (
            "compileall_task_py",
            [sys.executable, "-m", "compileall", "-q", "system/hub/task.py"],
            WORKTREE,
            20,
            None,
        ),
        ("git_status_porcelain", ["git", "status", "--porcelain"], WORKTREE, 15, None),
        ("git_diff_stat", ["git", "diff", "--stat"], WORKTREE, 15, None),
    ]

    for label, cmd, cwd, timeout, step_env in steps:
        report["steps"].append(run_step(label, cmd, cwd, timeout, step_env))

    receipt_checks = {}
    for path in (PYTEST_RECEIPT, PYTEST_RECEIPT + ".loaded"):
        info = {}
        try:
            info["exists"] = os.path.exists(path)
            info["size"] = os.path.getsize(path) if info["exists"] else None
        except OSError as exc:
            info["exists"] = False
            info["error"] = repr(exc)
        receipt_checks[path] = info
    report["receipt_checks"] = receipt_checks

    receipt_data = None
    receipt_read_errors = []
    for path in (PYTEST_RECEIPT, "/tmp/test2617_receipt.json"):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                receipt_data = json.load(fh)
            break
        except Exception as exc:  # noqa: BLE001
            receipt_read_errors.append({"path": path, "error": repr(exc)})

    if receipt_data is not None:
        report["receipt_summary"] = {
            "exitstatus": receipt_data.get("exitstatus"),
            "passed": receipt_data.get("passed"),
            "failed": receipt_data.get("failed"),
            "total": receipt_data.get("total"),
        }
        report["receipt_results"] = receipt_data.get("results")
    else:
        report["receipt_summary"] = None
        report["receipt_read_errors"] = receipt_read_errors

    report["report_write_errors"] = []
    for path in REPORT_PATHS:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=1)
        except Exception as exc:  # noqa: BLE001
            report["report_write_errors"].append({"path": path, "error": repr(exc)})

    print("RUN2617-DONE")
    print(json.dumps(report.get("receipt_summary"), ensure_ascii=False))


if __name__ == "__main__":
    main()