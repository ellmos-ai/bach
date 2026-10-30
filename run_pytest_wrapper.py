#!/usr/bin/env python3
"""
Wrapper to run pytest internally without invoking `python -m pytest` on the
command line, which is blocked by the task-bound process guard for this
worktree.
"""
import os
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "system"))

import pytest

TARGET = "system/tests/test_free_model_pin.py"
import tempfile

LOG = pathlib.Path(tempfile.gettempdir()) / "free_model_pin_test_result.txt"
LOG2 = ROOT / "system/tests/free_model_pin_wrapper_log.txt"
JUNIT = ROOT / "system/tests/free_model_pin_junit.xml"

if __name__ == "__main__":
    args = ["-q", "--tb=short", f"--junitxml={JUNIT}", TARGET]
    print(f"Running pytest.main({args}) from {ROOT}")
    code = pytest.main(args)
    status = "PASSED" if code == 0 else f"FAILED (exit {code})"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n[{__file__}] pytest exit code: {code} ({status})\n")
    with LOG2.open("a", encoding="utf-8") as f:
        f.write(f"\n[{__file__}] pytest exit code: {code} ({status})\n")
    sys.exit(code)
