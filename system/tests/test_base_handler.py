# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for BaseHandler — dual-init, _canonical_db resolution, abstract interface."""

import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.base import BaseHandler


class ConcreteHandler(BaseHandler):
    """Minimal concrete implementation for testing the abstract base."""

    @property
    def profile_name(self) -> str:
        return "test"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data"

    def get_operations(self) -> dict:
        return {"ping": "Test operation"}

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "ping":
            return True, "pong"
        return False, f"Unknown: {operation}"


class FakeApp:
    """Fake App container for new-style init."""

    def __init__(self, base_path, db=None):
        self.base_path = base_path
        self.db = db or (base_path / "data" / "bach.db")


# ═══════════════════════════════════════════════════════════════
# DUAL-INIT
# ═══════════════════════════════════════════════════════════════


class TestDualInit:
    def test_legacy_path_init(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        assert h.app is None
        assert h.base_path == system_dir

    def test_legacy_string_init(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(str(system_dir))
        assert h.app is None
        assert h.base_path == system_dir

    def test_app_init(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        app = FakeApp(system_dir)
        h = ConcreteHandler(app)
        assert h.app is app
        assert h.base_path == system_dir


# ═══════════════════════════════════════════════════════════════
# _canonical_db RESOLUTION
# ═══════════════════════════════════════════════════════════════


class TestCanonicalDb:
    def test_local_db_preferred_when_exists(self, tmp_path):
        """When a local bach.db exists under base_path/data/, use it."""
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        data_dir = system_dir / "data"
        data_dir.mkdir()
        local_db = data_dir / "bach.db"
        conn = sqlite3.connect(str(local_db))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        h = ConcreteHandler(system_dir)
        assert h._canonical_db == local_db

    def test_falls_through_when_no_local_db(self, tmp_path):
        """When no local bach.db exists, falls through to BACH_DB from bach_paths."""
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()

        h = ConcreteHandler(system_dir)
        # _canonical_db should NOT point to the non-existent local path
        assert h._canonical_db != system_dir / "data" / "bach.db"

    def test_system_root_never_uses_local(self):
        """When base_path IS the real system root, always use BACH_DB."""
        real_system_root = Path(__file__).resolve().parent.parent
        h = ConcreteHandler(real_system_root)
        from hub.bach_paths import BACH_DB
        assert h._canonical_db == BACH_DB

    def test_canonical_db_is_path(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        assert isinstance(h._canonical_db, Path)

    def test_local_db_via_app_init(self, tmp_path):
        """App-style init also resolves _canonical_db correctly."""
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        data_dir = system_dir / "data"
        data_dir.mkdir()
        local_db = data_dir / "bach.db"
        local_db.write_bytes(b"")  # touch

        conn = sqlite3.connect(str(local_db))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        app = FakeApp(system_dir)
        h = ConcreteHandler(app)
        assert h._canonical_db == local_db


# ═══════════════════════════════════════════════════════════════
# ABSTRACT INTERFACE
# ═══════════════════════════════════════════════════════════════


class TestAbstractInterface:
    def test_profile_name(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        assert h.profile_name == "test"

    def test_target_file(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        assert h.target_file == system_dir / "data"

    def test_get_operations(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        ops = h.get_operations()
        assert "ping" in ops

    def test_handle_known_operation(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        ok, msg = h.handle("ping", [])
        assert ok
        assert msg == "pong"

    def test_handle_unknown_operation(self, tmp_path):
        system_dir = tmp_path / "system"
        system_dir.mkdir()
        (system_dir / "data").mkdir()
        h = ConcreteHandler(system_dir)
        ok, msg = h.handle("unknown", [])
        assert not ok

    def test_cannot_instantiate_abstract(self, tmp_path):
        with pytest.raises(TypeError):
            BaseHandler(tmp_path)
