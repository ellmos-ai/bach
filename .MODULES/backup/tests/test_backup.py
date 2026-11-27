# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone backup module."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from backup import create_backup_zip, inspect_archive, prune_old_backups


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "backup"
    assert data["selfcontained"] is True


def test_create_inspect_and_prune_backups(tmp_path: Path):
    src = tmp_path / "src"
    (src / "__pycache__").mkdir(parents=True)
    (src / "a.txt").write_text("alpha", encoding="utf-8")
    (src / "__pycache__" / "skip.pyc").write_bytes(b"123")

    dest = tmp_path / "backups"
    b1 = create_backup_zip(src, dest, prefix="snap")
    assert b1["file_count"] == 1
    info = inspect_archive(b1["path"])
    assert info["valid"] is True
    assert info["contents"] == ["a.txt"]
    assert info["sha256"] == b1["sha256"]

    time.sleep(0.02)
    b2 = create_backup_zip(src, dest, prefix="snap")
    removed = prune_old_backups(dest, keep_latest=1)
    assert removed == [b1["name"]]
    assert Path(b2["path"]).is_file()
