#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
BACH Email Sender v1.0
=======================
Sendet E-Mails via Gmail API (OAuth2).

Sicherheitskonzept:
- Alle Mails werden IMMER zuerst als Draft in der DB gespeichert
- Versand nur nach expliziter User-Bestaetigung (confirm <id>)
- Kein direkter Versand ohne Zwischenschritt

Abhaengigkeiten:
- account_manager.py (Gmail API Service)
- bach.db (email_drafts Tabelle)

Autor: BACH System
Datum: 2026-02-13
"""

import base64
import sqlite3
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict
import logging

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# ============ PFADE ============

SERVICE_DIR = Path(__file__).parent.resolve()
BACH_DIR = SERVICE_DIR.parent.parent.parent
DATA_DIR = BACH_DIR / "data"
USER_DB = BACH_DB

LOG_FILE = BACH_DIR / "data" / "logs" / "email_sender.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# Default-Account
DEFAULT_SENDER = "user@example.com"
DEFAULT_ACCOUNT_ID = 3


class EmailSender:
    """Sendet E-Mails via Gmail API mit Draft-Sicherheitskonzept."""

    def __init__(self):
        self._init_database()
        self._service = None

    def _init_database(self):
        """Erstellt email_drafts Tabelle falls nicht vorhanden."""
        conn = sqlite3.connect(str(USER_DB))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient TEXT NOT NULL,
                cc TEXT,
                bcc TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                body_html TEXT,
                attachment_path TEXT,
                account_id INTEGER DEFAULT 3,
                sender_email TEXT DEFAULT 'your-email@example.com',
                status TEXT DEFAULT 'draft'
                    CHECK(status IN ('draft', 'sent', 'cancelled', 'failed')),
                error_message TEXT,
                gmail_message_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                confirmed_by TEXT,
                cancelled_at TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_drafts_status
            ON email_drafts(status)
        """)
        conn.commit()
        conn.close()

    def _get_service(self):
        """Holt Gmail API Service (lazy, cached)."""
        if self._service is None:
            # AccountManager importieren
            if str(SERVICE_DIR) not in sys.path:
                sys.path.insert(0, str(SERVICE_DIR))
            from account_manager import AccountManager
            mgr = AccountManager()
            self._service = mgr.get_gmail_service()
        return self._service

    def create_draft(self, to: str, subject: str, body: str,
                     cc: str = None, bcc: str = None,
                     body_html: str = None,
                     attachment_path: str = None,
                     account_id: int = DEFAULT_ACCOUNT_ID,
                     sender_email: str = DEFAULT_SENDER
                     ) -> Tuple[bool, int, str]:
        """
        Erstellt einen E-Mail-Entwurf in der DB.

        Returns:
            (success, draft_id, message)
        """
        if not to or '@' not in to:
            return False, 0, f"Ungueltige Empfaenger-Adresse: {to}"
        if not subject:
            return False, 0, "Kein Betreff angegeben"
        if not body:
            return False, 0, "Kein Text angegeben"

        # Attachment validieren falls angegeben
        if attachment_path and not Path(attachment_path).exists():
            return False, 0, f"Attachment nicht gefunden: {attachment_path}"

        conn = sqlite3.connect(str(USER_DB))
        try:
            cursor = conn.execute("""
                INSERT INTO email_drafts
                (recipient, cc, bcc, subject, body, body_html,
                 account_id, sender_email, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """, (to, cc, bcc, subject, body, body_html,
                  account_id, sender_email))
            draft_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Draft #{draft_id} erstellt: an {to}, Betreff: {subject[:50]}")
            return True, draft_id, f"Entwurf #{draft_id} erstellt"
        except Exception as e:
            logger.error(f"Draft-Erstellung fehlgeschlagen: {e}")
            return False, 0, f"Fehler: {e}"
        finally:
            conn.close()

    def confirm_and_send(self, draft_id: int,
                         confirmed_by: str = "user"
                         ) -> Tuple[bool, str]:
        """
        Bestaetigt und sendet einen Entwurf via Gmail API.

        Returns:
            (success, message)
        """
        conn = sqlite3.connect(str(USER_DB))
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            "SELECT * FROM email_drafts WHERE id = ?", (draft_id,)
        ).fetchone()

        if not row:
            conn.close()
            return False, f"Entwurf #{draft_id} nicht gefunden"

        if row['status'] != 'draft':
            conn.close()
            return False, (f"Entwurf #{draft_id} hat Status '{row['status']}' "
                          f"(nur 'draft' kann gesendet werden)")

        # Gmail API Service holen
        service = self._get_service()
        if not service:
            conn.close()
            return False, ("Gmail API nicht verfuegbar. "
                          "Bitte 'bach email setup' ausfuehren fuer OAuth-Autorisierung.")

        try:
            # Gmail Message bauen
            message = self._build_gmail_message(
                to=row['recipient'],
                subject=row['subject'],
                body=row['body'],
                body_html=row['body_html'],
                cc=row['cc'],
                bcc=row['bcc'],
                sender=row['sender_email'],
                attachment_path=row['attachment_path'] if 'attachment_path' in row.keys() else None
            )

            # Senden via Gmail API
            result = service.users().messages().send(
                userId='me', body=message
            ).execute()

            gmail_id = result.get('id', '')

            conn.execute("""
                UPDATE email_drafts
                SET status = 'sent',
                    sent_at = ?,
                    confirmed_by = ?,
                    gmail_message_id = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), confirmed_by, gmail_id, draft_id))
            conn.commit()
            conn.close()

            logger.info(f"E-Mail gesendet: #{draft_id} an {row['recipient']} (gmail_id={gmail_id})")
            return True, f"E-Mail #{draft_id} gesendet an {row['recipient']}"

        except Exception as e:
            conn.execute("""
                UPDATE email_drafts
                SET status = 'failed', error_message = ?
                WHERE id = ?
            """, (str(e)[:500], draft_id))
            conn.commit()
            conn.close()
            logger.error(f"Versand fehlgeschlagen #{draft_id}: {e}")
            return False, f"Versand fehlgeschlagen: {e}"

    def cancel_draft(self, draft_id: int) -> Tuple[bool, str]:
        """Verwirft einen Entwurf."""
        conn = sqlite3.connect(str(USER_DB))
        row = conn.execute(
            "SELECT status FROM email_drafts WHERE id = ?", (draft_id,)
        ).fetchone()

        if not row:
            conn.close()
            return False, f"Entwurf #{draft_id} nicht gefunden"

        if row[0] != 'draft':
            conn.close()
            return False, (f"Entwurf #{draft_id} kann nicht verworfen werden "
                          f"(Status: {row[0]})")

        conn.execute("""
            UPDATE email_drafts
            SET status = 'cancelled', cancelled_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), draft_id))
        conn.commit()
        conn.close()
        logger.info(f"Draft #{draft_id} verworfen")
        return True, f"Entwurf #{draft_id} verworfen"

    def list_drafts(self, status: str = 'draft') -> List[Dict]:
        """Listet Entwuerfe nach Status."""
        conn = sqlite3.connect(str(USER_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM email_drafts WHERE status = ? ORDER BY created_at DESC LIMIT 50",
            (status,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_draft(self, draft_id: int) -> Optional[Dict]:
        """Holt einzelnen Entwurf."""
        conn = sqlite3.connect(str(USER_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM email_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def _build_gmail_message(self, to: str, subject: str, body: str,
                              body_html: str = None, cc: str = None,
                              bcc: str = None, sender: str = None,
                              attachment_path: str = None) -> dict:
        """Baut Gmail API Message-Objekt (base64-encoded MIME)."""

        # Mit Attachment immer MIMEMultipart
        if attachment_path or body_html:
            msg = MIMEMultipart('mixed')

            # Body-Teil
            if body_html:
                body_part = MIMEMultipart('alternative')
                body_part.attach(MIMEText(body, 'plain', 'utf-8'))
                body_part.attach(MIMEText(body_html, 'html', 'utf-8'))
                msg.attach(body_part)
            else:
                msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # Attachment anhängen
            if attachment_path:
                file_path = Path(attachment_path)
                if file_path.exists():
                    with open(file_path, 'rb') as f:
                        attachment = MIMEBase('application', 'octet-stream')
                        attachment.set_payload(f.read())
                    encoders.encode_base64(attachment)
                    attachment.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{file_path.name}"'
                    )
                    msg.attach(attachment)
        else:
            msg = MIMEText(body, 'plain', 'utf-8')

        msg['To'] = to
        msg['Subject'] = subject
        if sender:
            msg['From'] = sender
        if cc:
            msg['Cc'] = cc
        if bcc:
            msg['Bcc'] = bcc

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')
        return {'raw': raw}

    def send_test(self, sender_email: str = DEFAULT_SENDER
                  ) -> Tuple[bool, str]:
        """Sendet Test-Mail an eigene Adresse (Draft + sofort confirm)."""
        success, draft_id, msg = self.create_draft(
            to=sender_email,
            subject="BACH E-Mail Test",
            body=(f"Dies ist eine Test-E-Mail von BACH.\n"
                  f"Gesendet: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                  f"Wenn du diese Mail siehst, funktioniert der Versand."),
            sender_email=sender_email
        )
        if not success:
            return False, msg
        return self.confirm_and_send(draft_id, confirmed_by="test")
