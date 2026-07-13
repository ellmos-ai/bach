# SPDX-License-Identifier: MIT
"""
Messages Handler - Nachrichtensystem CLI
========================================

bach msg list              Nachrichten anzeigen
bach msg send "to" "text"  Nachricht senden (als user)
bach msg send "to" "text" --from gemini   Nachricht von Partner senden
bach msg read <id>         Nachricht lesen/als gelesen markieren
bach msg unread            Ungelesene anzeigen
bach msg inbox             Inbox anzeigen
bach msg outbox            Gesendete anzeigen

MULTI-PARTNER-SUPPORT:
  --from user    Nachricht von User (outbox)
  --from claude  Nachricht von Claude (inbox fuer User)
  --from gemini  Nachricht von Gemini (inbox fuer User)
  --from ollama  Nachricht von Ollama (inbox fuer User)
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler
from .lang import t


class MessagesHandler(BaseHandler):
    """Handler fuer Nachrichten-Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.bach_db = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "msg"
    
    @property
    def target_file(self) -> Path:
        return self.bach_db
    
    def _get_active_partner(self) -> str:
        """Holt den zuletzt eingestempelten Partner aus partner_presence (v1.1.71)."""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.bach_db))
            try:
                row = conn.execute("""
                    SELECT partner_name FROM partner_presence
                    WHERE status = 'online'
                    ORDER BY clocked_in DESC LIMIT 1
                """).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return None
    
    def get_operations(self) -> dict:
        return {
            "list": "Alle Nachrichten anzeigen",
            "inbox": "Inbox anzeigen",
            "outbox": "Gesendete anzeigen",
            "unread": "Ungelesene Nachrichten",
            "send": "Nachricht senden (empfaenger, text, --from absender)",
            "read": "Nachricht lesen (id) [--ack]",
            "ping": "Ungelesene Nachrichten AN mich anzeigen [--from <partner>]",
            "watch": "Polling-Modus: Alle 10s auf neue Nachrichten pruefen [--from <partner>]",
            "count": "Nachrichtenzaehler",
            "delete": "Nachricht loeschen (id [id2 id3...])",
            "archive": "Nachricht archivieren (id [id2 id3...])"
        }
    
    def _get_conn(self):
        """DB-Verbindung holen."""
        conn = sqlite3.connect(self.bach_db)
        conn.row_factory = sqlite3.Row
        return conn
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list":
            return self._list_messages(args)
        elif operation == "inbox":
            return self._list_messages(["--inbox"])
        elif operation == "outbox":
            return self._list_messages(["--outbox"])
        elif operation == "unread":
            return self._list_unread()
        elif operation == "send":
            if len(args) < 2:
                return (False, "Usage: bach msg send <empfaenger> <nachricht> [--from <absender>]")
            
            # Absender extrahieren falls angegeben
            sender = "user"
            if "--from" in args:
                idx = args.index("--from")
                if idx + 1 < len(args):
                    sender = args[idx + 1]
                    args = args[:idx] + args[idx+2:]  # --from und Wert entfernen
            else:
                # Auto-detect: Aktiven Partner aus partner_presence holen (v1.1.71)
                sender = self._get_active_partner() or "user"
            
            return self._send_message(args[0], " ".join(args[1:]), dry_run, sender)
        elif operation == "read":
            if not args:
                return (False, "Usage: bach msg read <id> [--ack]")
            # --ack Flag: Nachricht lesen UND Lesebestaetigung senden
            send_ack = "--ack" in args
            args = [a for a in args if a != "--ack"]
            return self._read_message(args[0], dry_run, send_ack)
        elif operation == "ping":
            # v1.1.73: Zeigt ungelesene Nachrichten AN den Partner
            # Optional: --from <name> um Partner explizit anzugeben
            partner = None
            if "--from" in args:
                idx = args.index("--from")
                if idx + 1 < len(args):
                    partner = args[idx + 1]
            return self._ping_messages(partner)
        elif operation == "watch":
            # v1.1.73: Polling-Modus für Chat
            partner = None
            if "--from" in args:
                idx = args.index("--from")
                if idx + 1 < len(args):
                    partner = args[idx + 1]
            return self._watch_messages(partner)
        elif operation == "count":
            return self._count_messages()
        elif operation == "delete":
            if not args:
                return (False, "Usage: bach msg delete <id> [id2 id3...] [--dry-run]")
            # --dry-run aus args extrahieren
            if "--dry-run" in args:
                dry_run = True
                args = [a for a in args if a != "--dry-run"]
            if not args:
                return (False, "Usage: bach msg delete <id> [id2 id3...] [--dry-run]")
            return self._delete_messages(args, dry_run)
        elif operation == "archive":
            if not args:
                return (False, "Usage: bach msg archive <id> [id2 id3...] [--dry-run]")
            # --dry-run aus args extrahieren
            if "--dry-run" in args:
                dry_run = True
                args = [a for a in args if a != "--dry-run"]
            if not args:
                return (False, "Usage: bach msg archive <id> [id2 id3...] [--dry-run]")
            return self._archive_messages(args, dry_run)
        else:
            return self._show_help()
    
    def _list_messages(self, args: list) -> tuple:
        """Listet Nachrichten auf."""
        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        try:
            direction = None
            limit = 10

            if "--inbox" in args:
                direction = "inbox"
            elif "--outbox" in args:
                direction = "outbox"

            if "--limit" in args:
                idx = args.index("--limit")
                if idx + 1 < len(args):
                    try:
                        limit = int(args[idx + 1])
                    except ValueError:
                        pass

            if direction:
                rows = conn.execute("""
                    SELECT id, direction, sender, recipient, subject, body, status, created_at
                    FROM messages WHERE direction = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (direction, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, direction, sender, recipient, subject, body, status, created_at
                    FROM messages ORDER BY created_at DESC LIMIT ?
                """, (limit,)).fetchall()
        finally:
            conn.close()

        if not rows:
            return (True, "Keine Nachrichten vorhanden.")

        output = [f"=== NACHRICHTEN ({len(rows)}) ===", ""]

        for row in rows:
            status_icon = "●" if row["status"] == "unread" else "○"
            direction_icon = "📥" if row["direction"] == "inbox" else "📤"
            subject = row["subject"] or "(Kein Betreff)"
            date = row["created_at"][:16] if row["created_at"] else "?"

            output.append(f"{status_icon} [{row['id']:3}] {direction_icon} {date}")
            output.append(f"       {row['sender']} -> {row['recipient']}")
            output.append(f"       {subject[:50]}")
            output.append("")

        output.append("--")
        output.append("bach msg read <id>   Nachricht lesen")

        return (True, "\n".join(output))
    
    def _list_unread(self) -> tuple:
        """Listet ungelesene Nachrichten."""
        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        try:
            rows = conn.execute("""
                SELECT id, sender, subject, created_at
                FROM messages WHERE status = 'unread'
                ORDER BY created_at DESC
            """).fetchall()
        finally:
            conn.close()

        if not rows:
            return (True, "Keine ungelesenen Nachrichten.")

        output = [f"=== UNGELESEN ({len(rows)}) ===", ""]

        for row in rows:
            subject = row["subject"] or "(Kein Betreff)"
            date = row["created_at"][:16] if row["created_at"] else "?"
            output.append(f"● [{row['id']:3}] {date} - {row['sender']}")
            output.append(f"         {subject[:50]}")
            output.append("")

        return (True, "\n".join(output))
    
    def _ping_messages(self, partner: str = None) -> tuple:
        """Zeigt ungelesene Nachrichten AN den Partner (v1.1.73)."""
        my_name = partner or self._get_active_partner()
        if not my_name:
            return (False, "[ERROR] Kein Partner. Nutze --from <name> oder starte mit --partner=NAME")

        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        try:
            rows = conn.execute("""
                SELECT id, sender, body, created_at FROM messages
                WHERE status = 'unread' AND recipient = ?
                ORDER BY created_at DESC LIMIT 10
            """, (my_name,)).fetchall()
        finally:
            conn.close()
        
        if not rows:
            return (True, f"[OK] Keine neuen Nachrichten fuer {my_name.upper()}")
        
        output = [
            f"*** {len(rows)} NACHRICHT(EN) AN {my_name.upper()} ***",
            ""
        ]
        
        for row in rows:
            date = row['created_at'][11:16] if row['created_at'] else "?"
            output.append(f"[{row['id']}] VON {row['sender'].upper()} ({date}):")
            body_lines = (row['body'] or '').split('\n')[:4]
            for line in body_lines:
                output.append(f"   > {line[:75]}")
            output.append("")
        
        output.append("--> bach msg read <id> --ack zum Bestaetigen")
        return (True, "\n".join(output))
    
    def _watch_messages(self, partner: str = None) -> tuple:
        """Polling-Modus: Prüft alle 10s auf neue Nachrichten (v1.1.73 Chat)."""
        import time
        import sys
        
        my_name = partner or self._get_active_partner()
        if not my_name:
            return (False, "[ERROR] Kein Partner. Nutze --from <name>")
        
        print(f"[WATCH] Warte auf Nachrichten fuer {my_name.upper()}...")
        print("[WATCH] Ctrl+C zum Beenden\n")
        sys.stdout.flush()
        
        seen_ids = set()
        
        try:
            while True:
                conn = self._get_conn()
                if conn:
                    try:
                        rows = conn.execute("""
                            SELECT id, sender, body, created_at FROM messages
                            WHERE status = 'unread' AND recipient = ?
                            ORDER BY created_at DESC LIMIT 10
                        """, (my_name,)).fetchall()
                    finally:
                        conn.close()

                    for row in rows:
                        if row['id'] not in seen_ids:
                            seen_ids.add(row['id'])
                            date = row['created_at'][11:16] if row['created_at'] else "?"
                            print(f"\n[NEUE NACHRICHT #{row['id']}] {date}")
                            print(f"VON: {row['sender'].upper()}")
                            print(f">>> {row['body'][:200]}")
                            print("--> bach msg read {0} --ack".format(row['id']))
                            sys.stdout.flush()
                
                time.sleep(10)
        except KeyboardInterrupt:
            return (True, "\n[WATCH] Beendet.")
    
    def _send_message(self, recipient: str, body: str, dry_run: bool, sender: str = "user") -> tuple:
        """Sendet eine Nachricht."""
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde senden an: {recipient}")

        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        try:
            now = datetime.now().isoformat()
            direction = "outbox" if sender == "user" else "inbox"

            conn.execute("""
                INSERT INTO messages (direction, sender, recipient, body, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (direction, sender, recipient, body, "unread" if direction == "inbox" else "read", now))

            msg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        return (True, f"[OK] Nachricht #{msg_id} von {sender} gesendet an: {recipient}")
    
    def _read_message(self, msg_id: str, dry_run: bool, send_ack: bool = False) -> tuple:
        """Liest eine Nachricht und markiert als gelesen. Optional: Lesebestaetigung."""
        try:
            mid = int(msg_id)
        except ValueError:
            return (False, f"[ERROR] Ungueltige ID: {msg_id}")

        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        try:
            row = conn.execute("""
                SELECT * FROM messages WHERE id = ?
            """, (mid,)).fetchone()

            if not row:
                return (False, f"[ERROR] Nachricht #{mid} nicht gefunden")

            if not dry_run and row["status"] == "unread":
                conn.execute("""
                    UPDATE messages SET status = 'read', read_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), mid))
                conn.commit()
        finally:
            conn.close()
        
        # Nachricht formatieren
        direction_icon = "📥 INBOX" if row["direction"] == "inbox" else "📤 OUTBOX"
        subject = row["subject"] or "(Kein Betreff)"
        date = row["created_at"][:19] if row["created_at"] else "?"
        
        output = [
            "=" * 50,
            f"  {direction_icon} - Nachricht #{mid}",
            "=" * 50,
            "",
            f"Von:     {row['sender']}",
            f"An:      {row['recipient']}",
            f"Betreff: {subject}",
            f"Datum:   {date}",
            f"Status:  {row['status']}",
            "",
            "-" * 50,
            "",
            row["body"] or "(Kein Inhalt)",
            "",
            "-" * 50
        ]
        
        # v1.1.72: Lesebestaetigung senden wenn --ack
        if send_ack and not dry_run:
            sender = row['sender']
            my_name = self._get_active_partner() or "user"
            if sender and sender != my_name:
                ack_msg = f"[ACK] Nachricht #{mid} gelesen von {my_name.upper()}"
                self._send_message(sender, ack_msg, False, my_name)
                output.append(f"\n[OK] Lesebestaetigung an {sender} gesendet")
        
        return (True, "\n".join(output))
    
    def _count_messages(self) -> tuple:
        """Zeigt Nachrichtenzaehler."""
        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        try:
            total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            inbox = conn.execute("SELECT COUNT(*) FROM messages WHERE direction='inbox'").fetchone()[0]
            outbox = conn.execute("SELECT COUNT(*) FROM messages WHERE direction='outbox'").fetchone()[0]
            unread = conn.execute("SELECT COUNT(*) FROM messages WHERE status='unread'").fetchone()[0]
        finally:
            conn.close()
        
        output = [
            "=== NACHRICHTEN-STATUS ===",
            "",
            f"  Gesamt:    {total}",
            f"  Inbox:     {inbox}",
            f"  Outbox:    {outbox}",
            f"  Ungelesen: {unread}",
        ]
        
        return (True, "\n".join(output))
    
    def _delete_messages(self, msg_ids: list, dry_run: bool) -> tuple:
        """Loescht Nachrichten."""
        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        deleted = []
        errors = []

        try:
            for msg_id in msg_ids:
                try:
                    mid = int(msg_id)
                except ValueError:
                    errors.append(f"Ungueltige ID: {msg_id}")
                    continue

                row = conn.execute("SELECT id FROM messages WHERE id = ?", (mid,)).fetchone()
                if not row:
                    errors.append(f"Nachricht #{mid} nicht gefunden")
                    continue

                if not dry_run:
                    conn.execute("DELETE FROM messages WHERE id = ?", (mid,))
                    deleted.append(mid)
                else:
                    deleted.append(mid)

            if not dry_run:
                conn.commit()
        finally:
            conn.close()
        
        output = []
        if deleted:
            prefix = "[DRY-RUN] Wuerde loeschen:" if dry_run else "[OK] Geloescht:"
            output.append(f"{prefix} {', '.join(map(str, deleted))}")
        if errors:
            output.append(f"[FEHLER] {'; '.join(errors)}")
        
        return (bool(deleted), "\n".join(output) if output else "Keine Aenderungen")
    
    def _archive_messages(self, msg_ids: list, dry_run: bool) -> tuple:
        """Archiviert Nachrichten (setzt status=archived)."""
        conn = self._get_conn()
        if not conn:
            return (False, "[ERROR] Datenbank (bach.db) nicht gefunden")

        archived = []
        errors = []

        try:
            for msg_id in msg_ids:
                try:
                    mid = int(msg_id)
                except ValueError:
                    errors.append(f"Ungueltige ID: {msg_id}")
                    continue

                row = conn.execute("SELECT id, status FROM messages WHERE id = ?", (mid,)).fetchone()
                if not row:
                    errors.append(f"Nachricht #{mid} nicht gefunden")
                    continue

                if row["status"] == "archived":
                    errors.append(f"#{mid} bereits archiviert")
                    continue

                if not dry_run:
                    conn.execute("""
                        UPDATE messages SET status = 'archived', archived_at = ?
                        WHERE id = ?
                    """, (datetime.now().isoformat(), mid))
                    archived.append(mid)
                else:
                    archived.append(mid)

            if not dry_run:
                conn.commit()
        finally:
            conn.close()
        
        output = []
        if archived:
            prefix = "[DRY-RUN] Wuerde archivieren:" if dry_run else "[OK] Archiviert:"
            output.append(f"{prefix} {', '.join(map(str, archived))}")
        if errors:
            output.append(f"[HINWEIS] {'; '.join(errors)}")
        
        return (bool(archived), "\n".join(output) if output else "Keine Aenderungen")
    
    def _show_help(self) -> tuple:
        """Zeigt Hilfe."""
        output = [
            "=== MESSAGES HILFE ===",
            "",
            "bach msg list              Alle Nachrichten",
            "bach msg list --inbox      Nur Inbox",
            "bach msg list --outbox     Nur Gesendete",
            "bach msg list --limit 20   Mit Limit",
            "",
            "bach msg unread            Ungelesene anzeigen",
            "bach msg count             Zaehler anzeigen",
            "",
            "bach msg send <to> <text>  Nachricht senden (als user)",
            "bach msg send <to> <text> --from gemini  Von Partner senden",
            "bach msg read <id>         Nachricht lesen",
            "",
            "bach msg delete <id> [id2...]   Nachricht(en) loeschen",
            "bach msg archive <id> [id2...]  Nachricht(en) archivieren",
            "",
            "PARTNER-IDENTITAETEN:",
            "  --from user    -> Outbox (User sendet)",
            "  --from claude  -> Inbox (Claude sendet an User)",
            "  --from gemini  -> Inbox (Gemini sendet an User)",
            "  --from ollama  -> Inbox (Ollama sendet an User)",
        ]
        
        return (True, "\n".join(output))
