# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit test for standalone notify module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import notify


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "notify"
    assert data["selfcontained"] is True


def test_tag_notification():
    res = notify.tag_notification("Alert Message", ["BACH", "SYS"])
    assert res == "[BACH] [SYS] Alert Message"
    res_str = notify.tag_notification("Warning", "dev, urgent")
    assert res_str == "[dev] [urgent] Warning"


def test_notification_router_dispatch(tmp_path):
    db_file = tmp_path / "notify.db"
    router = notify.NotificationRouter(db_file)

    delivered_items = []
    router.register_channel_handler("desktop", lambda p: delivered_items.append(p) or True)

    # Send delivered
    res = router.send("Test Title", "My Content", channel="desktop", priority="high", tags=["test"])
    assert res["ok"] is True
    assert res["status"] == "delivered"
    assert res["delivered"] is True
    assert len(delivered_items) == 1
    assert delivered_items[0]["title"] == "Test Title"

    # Send pending to queue
    res_queue = router.send("Queue Title", "Deferred message", channel="queue")
    assert res_queue["ok"] is True
    assert res_queue["status"] == "pending"

    # Check pending
    pending = router.get_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == res_queue["id"]

    # Mark delivered
    ack = router.mark_delivered(res_queue["id"])
    assert ack is True
    assert len(router.get_pending()) == 0
