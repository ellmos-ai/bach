# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: inbox
============================
Self-contained inbox monitoring, folder scanning, file intake, and filter gates.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


IGNORED_PATTERNS = frozenset({
    ".git", ".svn", ".tmp", ".dirlock", "thumbs.db", "desktop.ini"
})
IGNORED_PREFIXES = (".", "~$", "LOCK.", "LOCK-", ".tmp")
IGNORED_SUFFIXES = (".tmp", ".lock", ".swp", ".bak", ".part", ".crdownload")


def is_safe_intake_file(path: Path) -> bool:
    """Return True if path is a regular, non-hidden, non-locked intake file."""
    name = path.name
    lower = name.lower()
    if lower in IGNORED_PATTERNS:
        return False
    if any(lower.startswith(p.lower()) for p in IGNORED_PREFIXES):
        return False
    if any(lower.endswith(s.lower()) for s in IGNORED_SUFFIXES):
        return False
    return True


class InboxScanner:
    """Monitors and scans an intake directory with safety filters and categorized reporting."""

    def __init__(self, inbox_dir: Path | str, allowed_extensions: Optional[Set[str]] = None):
        self.inbox_dir = Path(inbox_dir)
        self.allowed_extensions = {ext.lower() if ext.startswith(".") else f".{ext.lower()}"
                                   for ext in allowed_extensions} if allowed_extensions else None

    def scan(self, *, dry_run: bool = True) -> Dict[str, Any]:
        """Scans the inbox directory and reports candidate files."""
        if not self.inbox_dir.exists():
            return {
                "ok": False,
                "error": f"Inbox directory does not exist: {self.inbox_dir}",
                "candidates": [],
                "ignored_count": 0,
            }

        candidates: List[Dict[str, Any]] = []
        ignored_count = 0

        for item in sorted(self.inbox_dir.iterdir()):
            if item.is_dir():
                continue
            if not is_safe_intake_file(item):
                ignored_count += 1
                continue
            suffix = item.suffix.lower()
            if self.allowed_extensions and suffix not in self.allowed_extensions:
                ignored_count += 1
                continue

            stat = item.stat()
            candidates.append({
                "name": item.name,
                "path": str(item),
                "extension": suffix,
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            })

        return {
            "ok": True,
            "inbox_path": str(self.inbox_dir),
            "dry_run": dry_run,
            "candidates_count": len(candidates),
            "ignored_count": ignored_count,
            "candidates": candidates,
        }

    def intake_file(self, file_name: str, target_dir: Path | str) -> Dict[str, Any]:
        """Moves a candidate file from inbox into the target processing directory."""
        source = self.inbox_dir / file_name
        if not source.is_file():
            raise FileNotFoundError(f"Source file not found: {source}")
        if not is_safe_intake_file(source):
            raise ValueError(f"File {file_name} is rejected by intake safety rules")

        dest_dir = Path(target_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / file_name
        if dest_path.exists():
            stem = source.stem
            ext = source.suffix
            dest_path = dest_dir / f"{stem}_{int(time.time())}{ext}"

        shutil.move(str(source), str(dest_path))
        return {
            "ok": True,
            "source": str(source),
            "destination": str(dest_path),
            "size": dest_path.stat().st_size,
        }


def scan_inbox(inbox_path: Path | str, *, dry_run: bool = True) -> Dict[str, Any]:
    return InboxScanner(inbox_path).scan(dry_run=dry_run)
