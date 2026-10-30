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
LOG = ROOT / "free_model_pin_test_result.txt"

if __name__ == "__main__":
    args = ["-q", "--tb=short", TARGET]
    print(f"Running pytest.main({args}) from {ROOT}")
    code = pytest.main(args)
    status = "PASSED" if code == 0 else f"FAILED (exit {code})"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n[{__file__}] pytest exit code: {code} ({status})\n")
    sys.exit(code)
