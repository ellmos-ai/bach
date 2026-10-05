#!/usr/bin/env python3
"""Fail-closed gate for BACH-to-OCEAN use-case parity evidence (D-20260906-003).

A matrix row may only leave ``not-evidenced`` through
``architecture/bach-parity-evidence.v1.json``, and every evidenced use case must
name an existing old/new fixture test that refuses to skip under
``REQUIRE_PARITY_EVIDENCE=1``.  ``--run`` executes exactly these tests with that
switch; the parity-evidence CI job calls it, so "evidenced" is only green when
the referenced tests are green.  Historic ``accepted`` values are not evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "architecture" / "bach-parity-evidence.v1.json"
MATRIX = ROOT / "architecture" / "bach-composition-matrix.v1.json"
CI = ROOT / ".github" / "workflows" / "ci.yml"
USE_CASE_STATES = {"evidenced", "divergent"}
ROW_STATES = {"not-evidenced", "partially-evidenced", "evidenced", "not-independent"}
SHA = re.compile(r"^[0-9a-f]{40}$")
RUN_COMMAND = "python tools/check_parity_evidence.py --run"


def row_state(row: dict) -> str:
    evidenced = [case for case in row["use_cases"] if case["state"] == "evidenced"]
    covered = {operation for case in evidenced for operation in case["operations"]}
    if evidenced and covered >= set(row["operations_in_scope"]):
        return "evidenced"
    return "partially-evidenced" if evidenced else "not-evidenced"


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def validate(evidence: dict, matrix: dict, root: Path = ROOT, ci_text: str | None = None) -> list[str]:
    problems: list[str] = []
    if set(evidence.get("use_case_states", {})) != USE_CASE_STATES:
        problems.append(f"use_case_states must be exactly {sorted(USE_CASE_STATES)}")
    matrix_rows = {row["name"]: row for row in matrix["rows"]}
    seen_ids: set[str] = set()
    for name, row in evidence.get("rows", {}).items():
        target = matrix_rows.get(name)
        if target is None or target["class"] != "carrier":
            problems.append(f"{name}: evidence row must name a carrier row of the matrix")
            continue
        if row.get("carrier") != target.get("carrier"):
            problems.append(f"{name}: carrier {row.get('carrier')!r} differs from matrix {target.get('carrier')!r}")
        scope = set(row.get("operations_in_scope") or [])
        if not scope:
            problems.append(f"{name}: operations_in_scope is empty")
        for case in row.get("use_cases", []):
            label = f"{name}/{case.get('id')}"
            if case.get("id") in seen_ids:
                problems.append(f"{label}: duplicate use case id")
            seen_ids.add(case.get("id"))
            if case.get("state") not in USE_CASE_STATES:
                problems.append(f"{label}: state {case.get('state')!r} is not an evidence state")
            if not set(case.get("operations") or []) or not set(case["operations"]) <= scope:
                problems.append(f"{label}: operations must be a non-empty subset of operations_in_scope")
            if "bach-parity-baseline" in json.dumps(case):
                problems.append(f"{label}: the historic parity baseline is not evidence")
            pins = case.get("pins", {})
            if not (SHA.match(pins.get("bach_commit", "")) and SHA.match(pins.get("carrier_commit", ""))):
                problems.append(f"{label}: bach_commit and carrier_commit must be full commit ids")
            if not (root / case.get("fixture", "")).is_dir() or not case.get("fixture"):
                problems.append(f"{label}: fixture directory missing")
            file_part, _, function = case.get("test", "").partition("::")
            test_path = root / file_part
            if not file_part or not function or not test_path.is_file():
                problems.append(f"{label}: referenced test {case.get('test')!r} does not exist")
            elif function not in _test_functions(test_path):
                problems.append(f"{label}: test function {function!r} missing in {file_part}")
            elif "REQUIRE_PARITY_EVIDENCE" not in test_path.read_text(encoding="utf-8"):
                problems.append(f"{label}: {file_part} may skip silently; it must honor REQUIRE_PARITY_EVIDENCE")
        expected = row_state(row) if row.get("use_cases") else "not-evidenced"
        if target.get("use_case_state") != expected:
            problems.append(f"{name}: matrix use_case_state {target.get('use_case_state')!r} != evidence {expected!r}")
    for name, target in matrix_rows.items():
        state = target.get("use_case_state")
        if state not in ROW_STATES:
            problems.append(f"{name}: unknown use_case_state {state!r}")
        elif state in {"evidenced", "partially-evidenced"} and name not in evidence.get("rows", {}):
            problems.append(f"{name}: {state!r} without an entry in the evidence register")
    ci_text = CI.read_text(encoding="utf-8") if ci_text is None else ci_text
    if RUN_COMMAND not in ci_text or "REQUIRE_PARITY_EVIDENCE" not in ci_text:
        problems.append("CI must run the parity-evidence job with REQUIRE_PARITY_EVIDENCE")
    else:
        pinned = {pin for row in evidence.get("rows", {}).values() for case in row.get("use_cases", [])
                  for pin in case.get("pins", {}).values()}
        missing = sorted(pin for pin in pinned if pin not in ci_text)
        if missing:
            problems.append(f"CI parity-evidence job does not check out the pinned commits {missing}")
    return problems


def referenced_tests(evidence: dict) -> list[str]:
    return sorted({case["test"] for row in evidence["rows"].values() for case in row["use_cases"]})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="also run every referenced test; skips fail")
    args = parser.parse_args()
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    problems = validate(evidence, matrix)
    for problem in problems:
        print(f"[PARITY-EVIDENCE] {problem}", file=sys.stderr)
    if problems:
        return 1
    if args.run:
        env = {**os.environ, "REQUIRE_PARITY_EVIDENCE": "1"}
        return subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                *referenced_tests(evidence)], cwd=ROOT, env=env)
    print(f"[PARITY-EVIDENCE] ok: {len(referenced_tests(evidence))} referenced test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
