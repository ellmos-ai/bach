# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: backup
============================
Self-contained ZIP backup creator, manifest inspector, integrity verifier and retention pruner.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_EXCLUDES = (".git", "__pycache__", ".pytest_cache", "node_modules", ".venv")


@dataclass
class BackupArchiveInfo:
    name: str
    path: str
    size_bytes: int
    file_count: int
    sha256: str
    created_at: str


def compute_sha256(file_path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(file_path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup_zip(
    source_dir: Path | str,
    dest_dir: Path | str,
    *,
    prefix: str = "backup",
    exclude_parts: Iterable[str] = DEFAULT_EXCLUDES,
) -> Dict[str, Any]:
    """Create a timestamped ZIP backup and return metadata + SHA-256 checksum."""
    src = Path(source_dir).resolve()
    out_dir = Path(dest_dir).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archive_path = out_dir / f"{prefix}_{stamp}.zip"
    excludes = set(exclude_parts)
    file_count = 0

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(src.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(src)
            if any(part in excludes for part in rel.parts):
                continue
            zf.write(item, arcname=rel.as_posix())
            file_count += 1

    return {
        "name": archive_path.name,
        "path": str(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "file_count": file_count,
        "sha256": compute_sha256(archive_path),
        "created_at": datetime.now().isoformat(),
    }


def inspect_archive(archive_path: Path | str) -> Dict[str, Any]:
    """Inspect contents and metadata of an existing ZIP backup archive."""
    target = Path(archive_path)
    if not target.is_file():
        raise FileNotFoundError(f"Archive not found: {target}")
    with zipfile.ZipFile(target, "r") as zf:
        bad_member = zf.testzip()
        names = zf.namelist()
    return {
        "name": target.name,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "file_count": len(names),
        "contents": names,
        "corrupt_member": bad_member,
        "valid": bad_member is None,
        "sha256": compute_sha256(target),
    }


def prune_old_backups(dest_dir: Path | str, *, keep_latest: int = 10, pattern: str = "*.zip") -> List[str]:
    """Remove oldest backup archives beyond keep_latest."""
    target_dir = Path(dest_dir)
    if not target_dir.is_dir():
        return []
    archives = sorted(target_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    removed: List[str] = []
    for old in archives[max(0, keep_latest):]:
        old.unlink()
        removed.append(old.name)
    return removed
