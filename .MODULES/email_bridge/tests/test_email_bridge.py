# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit test for standalone email_bridge module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import email_bridge


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "email_bridge"
    assert data["selfcontained"] is True


def test_email_draft_store_and_confirm(tmp_path):
    db_file = tmp_path / "email.db"
    store = email_bridge.EmailDraftStore(db_file)

    draft = store.create_draft("worker@ellmos.org", "Test Betreff", "Inhalt des Entwurfs")
    assert draft["ok"] is True
    assert draft["status"] == "draft"
    draft_id = draft["draft_id"]

    # Verify listing
    drafts = store.list_drafts("draft")
    assert len(drafts) == 1
    assert drafts[0]["id"] == draft_id

    # Confirm send
    sent_mock = []
    res = store.confirm_send(draft_id, sender_callable=lambda d: sent_mock.append(d) or True)
    assert res["ok"] is True
    assert res["status"] == "sent"
    assert len(sent_mock) == 1

    # Cannot confirm again
    try:
        store.confirm_send(draft_id)
        assert False, "Should raise RuntimeError"
    except RuntimeError:
        pass


def test_cancel_draft_and_address_validation(tmp_path):
    assert email_bridge.validate_email_address("valid@domain.com") is True
    assert email_bridge.validate_email_address("invalid-address") is False

    store = email_bridge.EmailDraftStore(tmp_path / "email_cancel.db")
    draft = store.create_draft("test@example.com", "Subject", "Body")
    d_id = draft["draft_id"]

    cancel_res = store.cancel_draft(d_id)
    assert cancel_res["status"] == "cancelled"

    # Verify status changed
    cancelled_list = store.list_drafts("cancelled")
    assert len(cancelled_list) == 1
    assert cancelled_list[0]["id"] == d_id
