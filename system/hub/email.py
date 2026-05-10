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
BACH Email Handler v1.0
========================
E-Mail-Versand mit Draft-Sicherheit via Gmail API.

Jede Mail wird IMMER zuerst als Entwurf gespeichert.
Nur 'confirm' sendet tatsaechlich.

Operationen:
  send <to> <subject> <body>    Entwurf erstellen
  draft <to> <subject> <body>   Alias fuer send
  confirm <id>                  Bestaetigt und sendet
  cancel <id>                   Verwirft Entwurf
  drafts                        Offene Entwuerfe
  sent                          Gesendete Mails
  show <id>                     Entwurf-Details anzeigen
  setup                         Gmail Scope-Erweiterung
  test                          Test-Mail an eigene Adresse
  help                          Hilfe

Account: your-email@example.com (Gmail API, OAuth2)
"""

import sys
from pathlib import Path
from typing import List, Tuple

from hub.base import BaseHandler

# Service-Pfad fuer Imports
SERVICE_DIR = Path(__file__).parent / "_services" / "mail"


class EmailHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self._sender = None

    @property
    def profile_name(self) -> str:
        return "email"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "send": "E-Mail-Entwurf erstellen: send <to> <subject> <body>",
            "draft": "Alias fuer send",
            "confirm": "Entwurf bestaetigen und senden: confirm <id>",
            "cancel": "Entwurf verwerfen: cancel <id>",
            "drafts": "Offene Entwuerfe auflisten",
            "sent": "Gesendete Mails auflisten",
            "show": "Entwurf-Details anzeigen: show <id>",
            "setup": "Gmail API Scope-Erweiterung (einmalig)",
            "test": "Test-Mail an eigene Adresse senden",
            "help": "Hilfe anzeigen",
        }

    def _get_sender(self):
        """Lazy-Init des EmailSender."""
        if self._sender is None:
            if str(SERVICE_DIR) not in sys.path:
                sys.path.insert(0, str(SERVICE_DIR))
            from email_sender import EmailSender
            self._sender = EmailSender()
        return self._sender

    def handle(self, operation: str, args: List[str],
               dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "send": self._create_draft,
            "draft": self._create_draft,
            "confirm": self._confirm,
            "cancel": self._cancel,
            "drafts": self._list_drafts,
            "list": self._list_drafts,
            "": self._list_drafts,
            "sent": self._list_sent,
            "show": self._show,
            "setup": self._setup,
            "test": self._test,
            "help": self._help,
        }
        fn = ops.get(operation)
        if not fn:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach email help"
        return fn(args, dry_run)

    # ---------- OPERATIONEN ----------

    def _create_draft(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """
        Erstellt E-Mail-Entwurf.

        Formate:
          bach email send <to> <subject> <body>
          bach email send <to> --subject "Betreff" --body "Text"
          bach email send <to> --subject "Betreff" --body "Text" --cc "cc@x.com"
        """
        if not args:
            return False, (
                "Usage: bach email send <to> <subject> <body>\n"
                "  oder: bach email send <to> --subject \"Betreff\" --body \"Text\"\n"
                "  Optionen: --cc, --bcc"
            )

        # Erstes Argument muss Email-Adresse sein
        to = args[0] if args and '@' in args[0] else None
        if not to:
            return False, "Erstes Argument muss eine E-Mail-Adresse sein (mit @)"

        # Named args parsen
        subject = self._get_named_arg(args, "--subject") or self._get_named_arg(args, "-s")
        body = self._get_named_arg(args, "--body") or self._get_named_arg(args, "-b")
        cc = self._get_named_arg(args, "--cc")
        bcc = self._get_named_arg(args, "--bcc")
        attach = self._get_named_arg(args, "--attach") or self._get_named_arg(args, "-a")

        # Positional Fallback: send <to> <subject> <body>
        positional = [a for a in args[1:]
                      if not a.startswith("-") and a not in (subject, body, cc, bcc, attach)]
        if not subject and len(positional) >= 1:
            subject = positional[0]
        if not body and len(positional) >= 2:
            body = " ".join(positional[1:])

        if not subject:
            return False, "Kein Betreff angegeben (--subject oder zweites Argument)"
        if not body:
            return False, "Kein Text angegeben (--body oder drittes Argument)"

        if dry_run:
            return True, f"[DRY] Wuerde Entwurf erstellen: An={to}, Betreff={subject}"

        sender = self._get_sender()
        success, draft_id, msg = sender.create_draft(
            to=to, subject=subject, body=body, cc=cc, bcc=bcc, attachment_path=attach
        )

        if success:
            preview = (
                f"Entwurf #{draft_id} erstellt\n"
                f"  An:      {to}\n"
            )
            if cc:
                preview += f"  CC:      {cc}\n"
            if bcc:
                preview += f"  BCC:     {bcc}\n"
            preview += f"  Betreff: {subject}\n"
            if attach:
                from pathlib import Path
                filename = Path(attach).name
                preview += f"  Anhang:  {filename}\n"
            preview += (
                f"  Text:    {body[:300]}{'...' if len(body) > 300 else ''}\n\n"
                f"Senden:    bach email confirm {draft_id}\n"
                f"Verwerfen: bach email cancel {draft_id}"
            )
            return True, preview
        return False, msg

    def _confirm(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Bestaetigt und sendet einen Entwurf."""
        if not args:
            return False, "Usage: bach email confirm <id>"
        try:
            draft_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige ID: {args[0]}"

        if dry_run:
            return True, f"[DRY] Wuerde Entwurf #{draft_id} senden"

        confirmed_by = self._get_named_arg(args, "--by") or "user"
        sender = self._get_sender()
        return sender.confirm_and_send(draft_id, confirmed_by=confirmed_by)

    def _cancel(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Verwirft einen Entwurf."""
        if not args:
            return False, "Usage: bach email cancel <id>"
        try:
            draft_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige ID: {args[0]}"

        if dry_run:
            return True, f"[DRY] Wuerde Entwurf #{draft_id} verwerfen"

        sender = self._get_sender()
        return sender.cancel_draft(draft_id)

    def _list_drafts(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Listet offene Entwuerfe."""
        sender = self._get_sender()
        drafts = sender.list_drafts(status='draft')
        if not drafts:
            return True, "Keine offenen Entwuerfe"

        lines = [f"{len(drafts)} offene(r) Entwurf/Entwuerfe:\n"]
        for d in drafts:
            lines.append(
                f"  #{d['id']:<3} An: {d['recipient']:<30} "
                f"Betreff: {(d['subject'] or '')[:40]}  "
                f"({(d['created_at'] or '')[:16]})"
            )
        lines.append(f"\nSenden: bach email confirm <id>")
        lines.append(f"Verwerfen: bach email cancel <id>")
        return True, "\n".join(lines)

    def _list_sent(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Listet gesendete Mails."""
        sender = self._get_sender()
        sent = sender.list_drafts(status='sent')
        if not sent:
            return True, "Keine gesendeten Mails"

        lines = [f"{len(sent)} gesendete Mail(s):\n"]
        for d in sent:
            lines.append(
                f"  #{d['id']:<3} An: {d['recipient']:<30} "
                f"Betreff: {(d['subject'] or '')[:40]}  "
                f"({(d['sent_at'] or '')[:16]})"
            )
        return True, "\n".join(lines)

    def _show(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Zeigt Entwurf-Details."""
        if not args:
            return False, "Usage: bach email show <id>"
        try:
            draft_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige ID: {args[0]}"

        sender = self._get_sender()
        d = sender.get_draft(draft_id)
        if not d:
            return False, f"Entwurf #{draft_id} nicht gefunden"

        lines = [
            f"Entwurf #{d['id']} ({d['status']})",
            f"  Von:     {d['sender_email']}",
            f"  An:      {d['recipient']}",
        ]
        if d.get('cc'):
            lines.append(f"  CC:      {d['cc']}")
        if d.get('bcc'):
            lines.append(f"  BCC:     {d['bcc']}")
        lines.extend([
            f"  Betreff: {d['subject']}",
            f"  Erstellt: {d['created_at']}",
        ])
        if d.get('sent_at'):
            lines.append(f"  Gesendet: {d['sent_at']} (von: {d.get('confirmed_by', '?')})")
        if d.get('error_message'):
            lines.append(f"  Fehler: {d['error_message']}")
        lines.append(f"\n--- Text ---\n{d['body']}")
        return True, "\n".join(lines)

    def _setup(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Gmail Scope-Erweiterung (einmalig)."""
        if dry_run:
            return True, "[DRY] Wuerde Gmail Scopes erweitern"

        if str(SERVICE_DIR) not in sys.path:
            sys.path.insert(0, str(SERVICE_DIR))
        from account_manager import AccountManager
        mgr = AccountManager()
        success, result = mgr.upgrade_gmail_scopes()
        if success:
            return True, f"Gmail API bereit: {result}\nScopes: readonly + send"
        return False, f"Setup fehlgeschlagen: {result}"

    def _test(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Sendet Test-Mail an eigene Adresse."""
        if dry_run:
            return True, "[DRY] Wuerde Test-Mail senden"

        sender = self._get_sender()
        return sender.send_test()

    def _help(self, *_) -> Tuple[bool, str]:
        return True, """EMAIL - E-Mail Versand via Gmail API
=====================================

BEFEHLE:
  bach email send <to> <betreff> <text>     Entwurf erstellen
  bach email send <to> --subject "..." --body "..."
  bach email confirm <id>                   Entwurf senden
  bach email cancel <id>                    Entwurf verwerfen
  bach email drafts                         Offene Entwuerfe
  bach email sent                           Gesendete Mails
  bach email show <id>                      Entwurf-Details
  bach email setup                          Gmail Scope-Erweiterung (einmalig)
  bach email test                           Test-Mail an eigene Adresse

SICHERHEIT:
  Jede Mail wird IMMER zuerst als Entwurf gespeichert.
  Nur 'bach email confirm <id>' sendet tatsaechlich.

ACCOUNT: your-email@example.com (Gmail API, OAuth2)

TELEGRAM:
  senden <id>    - Entwurf senden
  verwerfen <id> - Entwurf verwerfen
  entwuerfe      - Offene Entwuerfe anzeigen"""

    # ---------- HILFSFUNKTIONEN ----------

    @staticmethod
    def _get_named_arg(args: list, flag: str):
        """Holt Wert eines benannten Arguments (--flag value oder --flag=value)."""
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None
