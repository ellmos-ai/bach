# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit-Tests fuer BACH IMAP-Drafts-Only Mail-Sicherheitsseam."""

import email
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

SERVICE_DIR = SYSTEM_ROOT / "hub" / "_services" / "mail"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from imap_draft import (
    ImapDraftSeam,
    ImapDraftError,
    encode_modified_utf7,
    decode_modified_utf7,
)


class TestModifiedUtf7:
    def test_ascii_passthrough(self):
        assert encode_modified_utf7("Drafts") == "Drafts"
        assert decode_modified_utf7("Drafts") == "Drafts"

    def test_german_entwuerfe(self):
        encoded = encode_modified_utf7("Entwürfe")
        assert encoded == "Entw&APw-rfe"
        assert decode_modified_utf7(encoded) == "Entwürfe"

    def test_roundtrip_complex(self):
        folders = ["Entwürfe", "Persönlich/Spam", "Müll & Archiv", "INBOX.Drafts"]
        for f in folders:
            enc = encode_modified_utf7(f)
            dec = decode_modified_utf7(enc)
            assert dec == f


class TestImapDraftSeam:
    @pytest.fixture
    def mock_imap_conn(self):
        conn = MagicMock()
        conn.login.return_value = ("OK", [b"Logged in"])
        conn.list.return_value = (
            "OK",
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren \\Drafts) "/" "Entw&APw-rfe"',
                b'(\\HasNoChildren) "/" "Sent"',
                b'(\\HasNoChildren) "/" "Trash"',
            ],
        )
        conn.append.return_value = ("OK", [b"[APPENDUID 1 42] Append completed."])
        return conn

    def test_folder_detection_localized(self, mock_imap_conn):
        seam = ImapDraftSeam(
            host="mail.example.com",
            connection_factory=lambda: mock_imap_conn,
        )
        with seam:
            detected = seam.detect_drafts_folder()
            assert detected == "Entwürfe"

    def test_append_draft_success(self, mock_imap_conn):
        seam = ImapDraftSeam(
            host="mail.example.com",
            connection_factory=lambda: mock_imap_conn,
        )
        ok, msg = seam.append_draft(
            to="recipient@example.com",
            subject="Status-Update Projekt",
            body="Hallo, hier ist der Entwurf.",
            sender="agent@bach.local",
        )
        assert ok is True
        assert "Entwürfe" in msg

        # Check append call on IMAP mock
        assert mock_imap_conn.append.called
        call_args = mock_imap_conn.append.call_args[0]
        mailbox = call_args[0]
        flags = call_args[1]
        raw_msg = call_args[3]

        assert mailbox == "Entw&APw-rfe"
        assert flags == r"(\Draft)"
        parsed = email.message_from_bytes(raw_msg)
        assert parsed["To"] == "recipient@example.com"
        assert parsed["Subject"] == "Status-Update Projekt"
        assert parsed["X-Mailer"] == "BACH-IMAP-Drafts-Seam/v1.0"

    def test_security_invariants_no_smtp(self):
        """Invariant: Das Seam besitzt keinerlei SMTP- oder Send-Schnittstellen."""
        seam = ImapDraftSeam(host="mail.example.com")
        assert not hasattr(seam, "send")
        assert not hasattr(seam, "send_mail")
        assert not hasattr(seam, "smtp_client")

    def test_connection_error_handling(self):
        def failing_factory():
            raise OSError("Connection refused")

        seam = ImapDraftSeam(
            host="mail.example.com",
            connection_factory=failing_factory,
        )
        with pytest.raises(ImapDraftError) as exc_info:
            seam.connect()
        assert "IMAP-Verbindung fehlgeschlagen" in str(exc_info.value)
