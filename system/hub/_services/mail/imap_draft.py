"""
Copyright (c) 2026 BACH Contributors
SPDX-License-Identifier: MIT

BACH IMAP-Drafts-Only Mail-Sicherheitsseam
==========================================
Ruecktransfer des bewaehrten Draft-Only Kommunikationsmusters aus FolderHome (Cluster 6).

Sicherheitsprinzip:
1. Keine SMTP-Berechtigung: Das System sendet niemals eigenstaendig E-Mails ins Internet.
2. Drafts-Only Seam: Generierte E-Mails werden via IMAP 'APPEND' (RFC 3501) als RFC-822 Payload
   direkt im Entwurfsordner (Drafts, Entwuerfe, INBOX.Drafts) des Nutzers abgelegt.
3. Human-in-the-Loop: Der tatsaechliche Versand verbleibt ausnahmslos im Mailprogramm
   (Thunderbird, Apple Mail, Webmailer) des Nutzers.
"""

from __future__ import annotations

import base64
import email.utils
import imaplib
import logging
from contextlib import suppress
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_IMAP_PORT = 993
DEFAULT_TIMEOUT_SECONDS = 30

# Standard-Kandidaten fuer lokalisierte Entwurfsordner
CANDIDATE_DRAFTS_FOLDERS = (
    "Drafts",
    "Entwürfe",
    "INBOX.Drafts",
    "INBOX/Drafts",
    "Draft",
    "Entwurf",
    "Brouillons",
)


class ImapDraftError(RuntimeError):
    """Fehler bei der IMAP-Entwurfsablage oder Ordneraufloesung."""


def encode_modified_utf7(value: str) -> str:
    """Kodiert Ordnernamen fuer IMAP (RFC 3501, modified UTF-7).

    Deutsche Ordner wie 'Entwürfe' muessen ueber das Wire-Protokoll als
    'Entw&APw-rfe' transportiert werden.
    """
    output: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        raw = "".join(pending).encode("utf-16-be")
        encoded = base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        output.append(f"&{encoded}-")
        pending.clear()

    for char in value:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            output.append("&-" if char == "&" else char)
        else:
            pending.append(char)
    flush()
    return "".join(output)


def decode_modified_utf7(value: str) -> str:
    """Dekodiert modifiziertes UTF-7 zurueck in lesbaren Text."""
    output: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "&":
            output.append(value[index])
            index += 1
            continue
        end = value.find("-", index)
        if end == -1:
            output.append(value[index:])
            break
        encoded = value[index + 1 : end]
        if not encoded:
            output.append("&")
        else:
            standard = encoded.replace(",", "/")
            standard += "=" * (-len(standard) % 4)
            try:
                output.append(base64.b64decode(standard).decode("utf-16-be"))
            except (ValueError, UnicodeDecodeError):
                output.append(value[index : end + 1])
        index = end + 1
    return "".join(output)


class ImapDraftSeam:
    """IMAP-Drafts-Only Seam zur Ablage von Mail-Entwuerfen ohne Versandbefugnis."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_IMAP_PORT,
        username: str = "",
        password: str = "",
        use_ssl: bool = True,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        connection_factory: Optional[object] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds
        self._connection_factory = connection_factory
        self._connection: Optional[object] = None

    def __enter__(self) -> ImapDraftSeam:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        """Stellt eine gesicherte Verbindung zum IMAP-Server her."""
        try:
            if self._connection_factory is not None:
                self._connection = self._connection_factory()
            elif self.use_ssl:
                self._connection = imaplib.IMAP4_SSL(
                    self.host, self.port, timeout=self.timeout_seconds
                )
            else:
                self._connection = imaplib.IMAP4(
                    self.host, self.port, timeout=self.timeout_seconds
                )

            if self.username and self.password:
                self._connection.login(self.username, self.password)
        except (imaplib.IMAP4.error, OSError) as exc:
            self.close()
            raise ImapDraftError(
                f"IMAP-Verbindung fehlgeschlagen ({self.host}:{self.port}): {exc}"
            ) from None

    def close(self) -> None:
        """Schliesst die Verbindung sauber."""
        if self._connection is not None:
            with suppress(imaplib.IMAP4.error, OSError, AttributeError):
                self._connection.logout()
            self._connection = None

    def list_folders(self) -> List[str]:
        """Gibt die Liste der Mailbox-Ordner in dekodierter Klarschrift zurueck."""
        if self._connection is None:
            raise ImapDraftError("IMAP-Verbindung ist nicht geoeffnet.")
        try:
            status, data = self._connection.list()
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapDraftError(f"Ordnerliste konnte nicht gelesen werden: {exc}") from None

        if status != "OK" or not data:
            return []

        folders: list[str] = []
        for item in data:
            if not item:
                continue
            text = (
                item.decode("utf-8", errors="replace")
                if isinstance(item, bytes)
                else str(item)
            )
            stripped = text.strip()
            if stripped.endswith('"'):
                opening = stripped.rfind('"', 0, len(stripped) - 1)
                name = stripped[opening + 1 : -1]
            else:
                name = stripped.rsplit(" ", 1)[-1].strip('"')
            if name:
                folders.append(decode_modified_utf7(name))
        return folders

    def detect_drafts_folder(
        self, custom_candidates: Optional[List[str]] = None
    ) -> str:
        """Findet den passenden Entwurfsordner auf dem Server."""
        available = self.list_folders()
        candidates = custom_candidates or list(CANDIDATE_DRAFTS_FOLDERS)

        # 1. Exakter Match
        for cand in candidates:
            if cand in available:
                return cand

        # 2. Case-Insensitive Match
        available_lower = {f.lower(): f for f in available}
        for cand in candidates:
            if cand.lower() in available_lower:
                return available_lower[cand.lower()]

        # 3. Teilstring-Match (z.B. nach "draft" oder "entw")
        for f in available:
            f_lower = f.lower()
            if "draft" in f_lower or "entw" in f_lower:
                return f

        # Fallback auf ersten Kandidaten
        return candidates[0] if candidates else "Drafts"

    def build_rfc822_message(
        self,
        to: str,
        subject: str,
        body: str,
        sender: str = "",
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        body_html: Optional[str] = None,
        attachment_path: Optional[str] = None,
    ) -> bytes:
        """Erstellt eine RFC-822-konforme E-Mail-Nachricht als Bytes."""
        if attachment_path or body_html:
            msg = MIMEMultipart("mixed")
            if body_html:
                alt = MIMEMultipart("alternative")
                alt.attach(MIMEText(body, "plain", "utf-8"))
                alt.attach(MIMEText(body_html, "html", "utf-8"))
                msg.attach(alt)
            else:
                msg.attach(MIMEText(body, "plain", "utf-8"))

            if attachment_path:
                p = Path(attachment_path)
                if p.is_file():
                    with open(p, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition", f'attachment; filename="{p.name}"'
                    )
                    msg.attach(part)
        else:
            msg = MIMEText(body, "plain", "utf-8")

        msg["To"] = to
        msg["Subject"] = subject
        if sender:
            msg["From"] = sender
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain="bach.local")
        msg["X-Mailer"] = "BACH-IMAP-Drafts-Seam/v1.0"
        return msg.as_bytes()

    def append_draft(
        self,
        to: str,
        subject: str,
        body: str,
        sender: str = "",
        folder: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        body_html: Optional[str] = None,
        attachment_path: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Legt den Entwurf via IMAP APPEND im Entwurfsordner ab.

        Returns:
            (success, message)
        """
        if not to or "@" not in to:
            return False, f"Ungueltige Empfaenger-Adresse: {to}"
        if not subject:
            return False, "Kein Betreff angegeben"
        if not body:
            return False, "Kein Text angegeben"

        with self:
            target_folder = folder or self.detect_drafts_folder()
            wire_folder = encode_modified_utf7(target_folder)
            raw_bytes = self.build_rfc822_message(
                to=to,
                subject=subject,
                body=body,
                sender=sender,
                cc=cc,
                bcc=bcc,
                body_html=body_html,
                attachment_path=attachment_path,
            )

            try:
                status, response = self._connection.append(
                    wire_folder,
                    r"(\Draft)",
                    None,
                    raw_bytes,
                )
            except (imaplib.IMAP4.error, OSError) as exc:
                logger.error(f"IMAP APPEND fehlgeschlagen in '{target_folder}': {exc}")
                return False, f"Ablage in '{target_folder}' fehlgeschlagen: {exc}"

            if status != "OK":
                return False, f"Server lehnte Entwurf ab: {response}"

            logger.info(
                f"Entwurf erfolgreich per IMAP APPEND in '{target_folder}' abgelegt (an {to})"
            )
            return True, f"Entwurf erfolgreich in '{target_folder}' abgelegt (IMAP-APPEND)"
