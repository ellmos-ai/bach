#!/usr/bin/env python3
"""
Modul-Gate Prüf-Skript (Forwarding Module).

Verweist auf .github/workflows/module_gate_check.py für CLI- und Import-Kompatibilität.
"""

from pathlib import Path
import importlib.util
import sys

_TARGET = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "module_gate_check.py"
_spec = importlib.util.spec_from_file_location("module_gate_check_impl", str(_TARGET))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Exponiere alle Attribute (get_changed_files, get_git_changed_files, main, etc.)
for _k, _v in _mod.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v

if __name__ == "__main__":
    sys.exit(_mod.main())
