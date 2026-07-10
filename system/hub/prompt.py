# SPDX-License-Identifier: MIT
"""
Prompt Handler - Verwaltung von Prompt-Templates und Boards
============================================================

CLI-Syntax:
  bach prompt list [--category CAT]       Alle Templates listen
  bach prompt add <name> <text> [--category CAT] [--tags t1,t2] [--purpose TEXT]
  bach prompt get <id_oder_name>          Template + Versionshistorie anzeigen
  bach prompt update <id_oder_name> <text> Neue Version erstellen
  bach prompt delete <id_oder_name>       Template loeschen
  bach prompt search <query>              LIKE-Suche in name, text, tags
  bach prompt boards                      Alle Boards listen
  bach prompt board <title> [--add-prompt ID] [--remove-prompt ID] [--description TEXT]

Ref: B42
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class PromptHandler(BaseHandler):
    """Handler fuer Prompt-Templates und Boards."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "prompt"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Prompt-Templates listen (optional --category Filter)",
            "add": "Neues Template: bach prompt add <name> <text> [--category CAT] [--tags t1,t2] [--purpose TEXT]",
            "get": "Template + Versionshistorie: bach prompt get <id_oder_name>",
            "update": "Neue Version erstellen: bach prompt update <id_oder_name> <neuer_text>",
            "delete": "Template loeschen: bach prompt delete <id_oder_name>",
            "search": "LIKE-Suche: bach prompt search <query>",
            "boards": "Alle Boards listen: bach prompt boards",
            "board": "Board verwalten: bach prompt board <title> [--add-prompt ID] [--remove-prompt ID] [--description TEXT]",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list":
            return self._list(args)
        elif operation == "add":
            return self._add(args)
        elif operation == "get":
            if not args:
                return False, "Argument benoetigt: bach prompt get <id_oder_name>"
            return self._get(args[0])
        elif operation == "update":
            if len(args) < 2:
                return False, "Argumente benoetigt: bach prompt update <id_oder_name> <neuer_text>"
            return self._update(args[0], " ".join(args[1:]))
        elif operation == "delete":
            if not args:
                return False, "Argument benoetigt: bach prompt delete <id_oder_name>"
            return self._delete(args[0])
        elif operation == "search":
            if not args:
                return False, "Argument benoetigt: bach prompt search <query>"
            return self._search(" ".join(args))
        elif operation == "boards":
            return self._boards()
        elif operation == "board":
            if not args:
                return False, "Argument benoetigt: bach prompt board <title> [--add-prompt ID] [--remove-prompt ID] [--description TEXT]"
            return self._board(args)
        else:
            return False, f"Unbekannte Operation: {operation}"

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _resolve_prompt(self, conn, id_or_name: str):
        """Findet ein Template per ID oder Name. Returns Row oder None."""
        id_or_name = id_or_name.strip()
        # Zuerst per ID versuchen
        try:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE id = ?", (int(id_or_name),)
            ).fetchone()
            if row:
                return row
        except (ValueError, TypeError):
            pass
        # Dann per Name
        row = conn.execute(
            "SELECT * FROM prompt_templates WHERE name = ?", (id_or_name,)
        ).fetchone()
        return row

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------
    def _list(self, args: list) -> tuple:
        category = None
        for i, arg in enumerate(args):
            if arg == "--category" and i + 1 < len(args):
                category = args[i + 1].strip()

        conn = self._get_conn()
        try:
            if category:
                rows = conn.execute(
                    "SELECT id, name, category, purpose, tags, updated_at "
                    "FROM prompt_templates WHERE category = ? ORDER BY name",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, category, purpose, tags, updated_at "
                    "FROM prompt_templates ORDER BY name"
                ).fetchall()

            if not rows:
                return True, "Keine Prompt-Templates gefunden."

            lines = [
                f"{'ID':<5} {'Name':<30} {'Kategorie':<15} {'Purpose':<30} {'Updated'}",
                "-" * 95,
            ]
            for r in rows:
                purpose = (r["purpose"] or "")[:28]
                cat = r["category"] or "-"
                updated = r["updated_at"] or "-"
                lines.append(
                    f"{r['id']:<5} {r['name']:<30} {cat:<15} {purpose:<30} {updated}"
                )
            lines.append(f"\n{len(rows)} Template(s) gefunden.")
            return True, "\n".join(lines)
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # add
    # ------------------------------------------------------------------
    def _add(self, args: list) -> tuple:
        if len(args) < 2:
            return False, 'Usage: bach prompt add <name> <text> [--category CAT] [--tags t1,t2] [--purpose TEXT]'

        name = args[0].strip()
        # Text ist das zweite Argument (kann in Anfuehrungszeichen stehen)
        text = args[1].strip()
        category = None
        tags = None
        purpose = None

        i = 2
        while i < len(args):
            if args[i] == "--category" and i + 1 < len(args):
                category = args[i + 1].strip()
                i += 2
            elif args[i] == "--tags" and i + 1 < len(args):
                tags = json.dumps([t.strip() for t in args[i + 1].split(",")])
                i += 2
            elif args[i] == "--purpose" and i + 1 < len(args):
                purpose = args[i + 1].strip()
                i += 2
            else:
                i += 1

        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, purpose, text, tags, category, now, now),
            )
            conn.commit()
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return True, f"Template '{name}' erstellt (ID: {pid})."
        except sqlite3.IntegrityError:
            return False, f"Template mit Name '{name}' existiert bereits."
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------
    def _get(self, id_or_name: str) -> tuple:
        conn = self._get_conn()
        try:
            row = self._resolve_prompt(conn, id_or_name)
            if not row:
                return False, f"Template '{id_or_name}' nicht gefunden."

            lines = [
                f"PROMPT TEMPLATE: {row['name']} (ID: {row['id']})",
                f"Kategorie: {row['category'] or '-'}",
                f"Purpose: {row['purpose'] or '-'}",
                f"Tags: {row['tags'] or '-'}",
                f"Erstellt: {row['created_at']}",
                f"Aktualisiert: {row['updated_at']}",
                f"dist_type: {row['dist_type'] or '-'}",
                "",
                "TEXT:",
                row["text"] or "(leer)",
            ]

            # Versionshistorie
            versions = conn.execute(
                "SELECT version_number, text, tags, created_at "
                "FROM prompt_versions WHERE prompt_id = ? ORDER BY version_number DESC",
                (row["id"],),
            ).fetchall()
            if versions:
                lines.append("")
                lines.append(f"VERSIONEN ({len(versions)}):")
                lines.append(f"  {'Nr':<5} {'Erstellt':<25} {'Text (Vorschau)'}")
                lines.append("  " + "-" * 70)
                for v in versions:
                    preview = (v["text"] or "")[:50].replace("\n", " ")
                    lines.append(f"  {v['version_number']:<5} {v['created_at']:<25} {preview}")

            return True, "\n".join(lines)
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # update (Versioning)
    # ------------------------------------------------------------------
    def _update(self, id_or_name: str, new_text: str) -> tuple:
        new_text = new_text.strip()
        if not new_text:
            return False, "Neuer Text darf nicht leer sein."

        conn = self._get_conn()
        try:
            row = self._resolve_prompt(conn, id_or_name)
            if not row:
                return False, f"Template '{id_or_name}' nicht gefunden."

            prompt_id = row["id"]
            old_text = row["text"]
            old_tags = row["tags"]

            # Naechste Versionsnummer bestimmen
            max_ver = conn.execute(
                "SELECT MAX(version_number) FROM prompt_versions WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()[0]
            next_ver = (max_ver or 0) + 1

            now = datetime.now().isoformat()

            # Alten Text in prompt_versions sichern
            conn.execute(
                "INSERT INTO prompt_versions (prompt_id, version_number, text, tags, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (prompt_id, next_ver, old_text, old_tags, now),
            )

            # Template mit neuem Text aktualisieren
            conn.execute(
                "UPDATE prompt_templates SET text = ?, updated_at = ? WHERE id = ?",
                (new_text, now, prompt_id),
            )
            conn.commit()
            return True, f"Template '{row['name']}' aktualisiert (alte Version: v{next_ver})."
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------
    def _delete(self, id_or_name: str) -> tuple:
        conn = self._get_conn()
        try:
            row = self._resolve_prompt(conn, id_or_name)
            if not row:
                return False, f"Template '{id_or_name}' nicht gefunden."

            prompt_id = row["id"]
            name = row["name"]

            # Versionen loeschen
            conn.execute("DELETE FROM prompt_versions WHERE prompt_id = ?", (prompt_id,))
            # Board-Items loeschen
            conn.execute("DELETE FROM prompt_board_items WHERE prompt_id = ?", (prompt_id,))
            # Template loeschen
            conn.execute("DELETE FROM prompt_templates WHERE id = ?", (prompt_id,))
            conn.commit()
            return True, f"Template '{name}' (ID: {prompt_id}) und zugehoerige Versionen/Board-Items geloescht."
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def _search(self, query: str) -> tuple:
        query = query.strip()
        pattern = f"%{query}%"

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, name, category, purpose, tags, text "
                "FROM prompt_templates "
                "WHERE name LIKE ? OR text LIKE ? OR tags LIKE ? "
                "ORDER BY name",
                (pattern, pattern, pattern),
            ).fetchall()

            if not rows:
                return True, f"Keine Treffer fuer '{query}'."

            lines = [
                f"Suche: '{query}' -- {len(rows)} Treffer",
                f"{'ID':<5} {'Name':<30} {'Kategorie':<15} {'Vorschau'}",
                "-" * 80,
            ]
            for r in rows:
                preview = (r["text"] or "")[:40].replace("\n", " ")
                cat = r["category"] or "-"
                lines.append(f"{r['id']:<5} {r['name']:<30} {cat:<15} {preview}")

            return True, "\n".join(lines)
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # boards
    # ------------------------------------------------------------------
    def _boards(self) -> tuple:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT b.id, b.title, b.description, b.created_at, "
                "COUNT(bi.id) AS item_count "
                "FROM prompt_boards b "
                "LEFT JOIN prompt_board_items bi ON bi.board_id = b.id "
                "GROUP BY b.id ORDER BY b.title"
            ).fetchall()

            if not rows:
                return True, "Keine Boards vorhanden."

            lines = [
                f"{'ID':<5} {'Titel':<30} {'Items':<7} {'Beschreibung'}",
                "-" * 75,
            ]
            for r in rows:
                desc = (r["description"] or "")[:35]
                lines.append(f"{r['id']:<5} {r['title']:<30} {r['item_count']:<7} {desc}")
            lines.append(f"\n{len(rows)} Board(s).")
            return True, "\n".join(lines)
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # board (erstellen / verwalten)
    # ------------------------------------------------------------------
    def _board(self, args: list) -> tuple:
        title = args[0].strip()
        add_prompt_id = None
        remove_prompt_id = None
        description = None

        i = 1
        while i < len(args):
            if args[i] == "--add-prompt" and i + 1 < len(args):
                add_prompt_id = args[i + 1].strip()
                i += 2
            elif args[i] == "--remove-prompt" and i + 1 < len(args):
                remove_prompt_id = args[i + 1].strip()
                i += 2
            elif args[i] == "--description" and i + 1 < len(args):
                description = args[i + 1].strip()
                i += 2
            else:
                i += 1

        conn = self._get_conn()
        try:
            # Board finden oder erstellen
            board = conn.execute(
                "SELECT * FROM prompt_boards WHERE title = ?", (title,)
            ).fetchone()

            if not board:
                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT INTO prompt_boards (title, description, created_at) VALUES (?, ?, ?)",
                    (title, description, now),
                )
                conn.commit()
                board = conn.execute(
                    "SELECT * FROM prompt_boards WHERE title = ?", (title,)
                ).fetchone()
                msg = f"Board '{title}' erstellt (ID: {board['id']})."
            else:
                msg = f"Board '{title}' (ID: {board['id']})."

            board_id = board["id"]

            # Description aktualisieren (wenn Board schon existiert)
            if description and board:
                conn.execute(
                    "UPDATE prompt_boards SET description = ? WHERE id = ?",
                    (description, board_id),
                )
                conn.commit()
                msg += f" Beschreibung aktualisiert."

            # Prompt hinzufuegen
            if add_prompt_id:
                prompt = self._resolve_prompt(conn, add_prompt_id)
                if not prompt:
                    return False, f"Prompt '{add_prompt_id}' nicht gefunden."
                try:
                    now = datetime.now().isoformat()
                    conn.execute(
                        "INSERT INTO prompt_board_items (board_id, prompt_id, added_at) "
                        "VALUES (?, ?, ?)",
                        (board_id, prompt["id"], now),
                    )
                    conn.commit()
                    msg += f" Prompt '{prompt['name']}' hinzugefuegt."
                except sqlite3.IntegrityError:
                    msg += f" Prompt '{prompt['name']}' ist bereits im Board."

            # Prompt entfernen
            if remove_prompt_id:
                prompt = self._resolve_prompt(conn, remove_prompt_id)
                if not prompt:
                    return False, f"Prompt '{remove_prompt_id}' nicht gefunden."
                conn.execute(
                    "DELETE FROM prompt_board_items WHERE board_id = ? AND prompt_id = ?",
                    (board_id, prompt["id"]),
                )
                conn.commit()
                msg += f" Prompt '{prompt['name']}' entfernt."

            # Board-Inhalt anzeigen
            items = conn.execute(
                "SELECT pt.id, pt.name, pt.category, bi.added_at "
                "FROM prompt_board_items bi "
                "JOIN prompt_templates pt ON pt.id = bi.prompt_id "
                "WHERE bi.board_id = ? ORDER BY bi.added_at",
                (board_id,),
            ).fetchall()

            if items:
                msg += f"\n\nInhalt ({len(items)} Prompts):"
                msg += f"\n  {'ID':<5} {'Name':<30} {'Kategorie':<15} {'Hinzugefuegt'}"
                msg += "\n  " + "-" * 65
                for it in items:
                    cat = it["category"] or "-"
                    msg += f"\n  {it['id']:<5} {it['name']:<30} {cat:<15} {it['added_at']}"

            return True, msg
        except sqlite3.Error as e:
            return False, f"DB-Fehler: {e}"
        finally:
            conn.close()
