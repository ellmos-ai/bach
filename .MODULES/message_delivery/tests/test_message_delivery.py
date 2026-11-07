# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit test for standalone message_delivery module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import message_delivery


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "message_delivery"
    assert data["selfcontained"] is True


def test_message_delivery_lifecycle(tmp_path):
    db_file = tmp_path / "test_messages.db"
    engine = message_delivery.MessageDeliveryEngine(db_file)

    # Initial count
    assert engine.count("user", unread_only=True) == 0

    # Send message from gemini to user
    msg_id = engine.send("user", "Hallo von Gemini!", sender="gemini")
    assert msg_id > 0

    # Verify unread count
    assert engine.count("user", unread_only=True) == 1

    # List inbox
    inbox = engine.list_messages(box="inbox", partner="user", unread_only=True)
    assert len(inbox) == 1
    assert inbox[0]["sender"] == "gemini"
    assert inbox[0]["message"] == "Hallo von Gemini!"

    # Read message with ack
    read_item = engine.read(msg_id, mark_ack=True)
    assert read_item["read_at"] is not None
    assert read_item["ack_at"] is not None

    # Verify unread count is now 0
    assert engine.count("user", unread_only=True) == 0

    # Archive message
    assert engine.archive(msg_id) is True
    assert engine.count("user", unread_only=False) == 0
