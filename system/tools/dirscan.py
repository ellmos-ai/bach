#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entrypoint for the directory scanner.

The implementation lives in ``tools/file_ops/dirscan.py``. Older handlers and
help pages still import or execute ``tools/dirscan.py`` directly.
"""
from pathlib import Path
import runpy

try:
    from .file_ops.dirscan import DirectoryScanner
except ImportError:  # Also works when tools/ is inserted directly into sys.path.
    from file_ops.dirscan import DirectoryScanner

__all__ = ["DirectoryScanner"]


def main() -> None:
    runpy.run_path(str(Path(__file__).parent / "file_ops" / "dirscan.py"), run_name="__main__")


if __name__ == "__main__":
    main()
