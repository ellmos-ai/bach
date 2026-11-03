# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for db_sync_adapter module."""
import json
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from db_sync_adapter import OPERATIONS, SharedAdapterRefusal, SharedDBSyncConfig


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "db_sync_adapter"
    assert data["selfcontained"] is True


def test_db_sync_adapter_constants():
    assert "backup" in OPERATIONS
    assert "status" in OPERATIONS
    assert issubclass(SharedAdapterRefusal, ValueError)
