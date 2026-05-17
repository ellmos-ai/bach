# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for EmailHandler (hub/email.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.email import EmailHandler


@pytest.fixture
def email_env(tmp_path, monkeypatch):
    """EmailHandler with mocked sender."""
    base = tmp_path / "bach" / "system"
    data = base / "data"
    data.mkdir(parents=True)
    db_path = data / "bach.db"
    db_path.write_bytes(b"")

    handler = EmailHandler(base)
    monkeypatch.setattr(handler, "db_path", db_path)
    return handler, base


class TestEmailBasic:
    def test_profile_name(self, email_env):
        handler, _ = email_env
        assert handler.profile_name == "email"

    def test_operations(self, email_env):
        handler, _ = email_env
        ops = handler.get_operations()
        assert "send" in ops
        assert "draft" in ops
        assert "confirm" in ops
        assert "cancel" in ops
        assert "drafts" in ops
        assert "sent" in ops
        assert "help" in ops

    def test_unknown_operation(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("nope", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_help(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("help", [])
        assert ok is True


class TestEmailDraft:
    def test_send_no_args(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("send", [])
        assert ok is False
        assert "Usage" in msg

    def test_send_no_at_sign(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("send", ["noatsign"])
        assert ok is False
        assert "@" in msg

    def test_send_no_subject(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("send", ["test@x.com"])
        assert ok is False
        assert "Betreff" in msg

    def test_send_no_body(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("send", ["test@x.com", "Subject"])
        assert ok is False
        assert "Text" in msg

    def test_send_dry_run(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle(
            "send", ["test@x.com", "Hello", "Body text"], dry_run=True
        )
        assert ok is True
        assert "DRY" in msg
        assert "test@x.com" in msg

    def test_send_dry_run_named_args(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle(
            "send",
            ["user@example.com", "--subject", "Test Subject", "--body", "Test Body"],
            dry_run=True,
        )
        assert ok is True
        assert "DRY" in msg
        assert "user@example.com" in msg

    @patch.object(EmailHandler, "_get_sender")
    def test_send_success(self, mock_get_sender, email_env):
        handler, _ = email_env
        mock_sender = MagicMock()
        mock_sender.create_draft.return_value = (True, 42, "OK")
        mock_get_sender.return_value = mock_sender

        ok, msg = handler.handle("send", ["a@b.com", "Betreff", "Inhalt"])
        assert ok is True
        assert "42" in msg
        assert "a@b.com" in msg
        mock_sender.create_draft.assert_called_once()

    @patch.object(EmailHandler, "_get_sender")
    def test_send_failure(self, mock_get_sender, email_env):
        handler, _ = email_env
        mock_sender = MagicMock()
        mock_sender.create_draft.return_value = (False, None, "API Error")
        mock_get_sender.return_value = mock_sender

        ok, msg = handler.handle("send", ["a@b.com", "Betreff", "Inhalt"])
        assert ok is False
        assert "API Error" in msg


class TestEmailConfirm:
    def test_confirm_no_args(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("confirm", [])
        assert ok is False
        assert "Usage" in msg

    def test_confirm_invalid_id(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("confirm", ["abc"])
        assert ok is False
        assert "Ungueltige ID" in msg


class TestEmailCancel:
    def test_cancel_no_args(self, email_env):
        handler, _ = email_env
        ok, msg = handler.handle("cancel", [])
        assert ok is False
