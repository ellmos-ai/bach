# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone session module."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from session import SessionManager, SessionRecord


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "session"
    assert data["selfcontained"] is True


def test_session_lifecycle(tmp_path: Path):
    store_file = tmp_path / "sessions.json"
    mgr = SessionManager(storage_path=store_file)

    assert mgr.get_active_session() is None

    s = mgr.start_session(user_id="lukas", agent_id="gemini", purpose="Testing Session")
    assert s.is_active is True
    assert mgr.get_active_session().session_id == s.session_id

    time.sleep(0.05)
    ended = mgr.end_session(s.session_id, notes=["Done with work"])
    assert ended.is_active is False
    assert ended.duration_seconds > 0.0
    assert mgr.get_active_session() is None

    # Verify persistence
    mgr2 = SessionManager(storage_path=store_file)
    restored = mgr2.get_session(s.session_id)
    assert restored is not None
    assert restored.user_id == "lukas"
    assert "Done with work" in restored.notes


def test_between_task_check():
    mgr = SessionManager()
    s = mgr.start_session()
    check = mgr.between_task_check(s.session_id, last_action="bach task done 123")
    assert check["session_id"] == s.session_id
    assert check["last_action"] == "bach task done 123"
    assert "nudge" in check
