#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: MIT
"""
TaskHandler - Task-Verwaltung fuer BACH

Operationen:
  add <titel>           Task hinzufuegen
  list [filter]         Tasks auflisten
  done <id> [id2...]    Task(s) als erledigt markieren
  block <id> [id2...]   Task(s) blockieren
  unblock <id> [id2...] Task(s) entblocken
  show <id>             Task-Details anzeigen
  delete <id> [id2...]  Task(s) loeschen
  priority <id> <prio>  Prioritaet aendern

Multi-ID Support:
  bach task done 319 320 321
  bach task block 100 101 --reason "Wartet auf API"

Autor: Claude
Stand: 2026-01-23
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional
from .base import BaseHandler
from .lang import t


class TaskHandler(BaseHandler):
    """Handler fuer Task-Verwaltung"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = base_path / "data" / "bach.db"
    
    @property
    def profile_name(self) -> str:
        return "task"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "add": t("task_add_desc", default="Task hinzufuegen"),
            "list": t("task_list_desc", default="Tasks auflisten"),
            "edit": t("task_edit_desc", default="Task bearbeiten (Titel, Beschreibung, Kategorie)"),
            "done": t("task_done_desc", default="Task(s) erledigen (Multi-ID)"),
            "block": t("task_block_desc", default="Task(s) blockieren (Multi-ID)"),
            "unblock": t("task_unblock_desc", default="Task(s) entblocken (Multi-ID)"),
            "reopen": t("task_reopen_desc", default="Task(s) wieder oeffnen (Multi-ID)"),
            "show": t("task_show_desc", default="Task-Details anzeigen"),
            "delete": t("task_delete_desc", default="Task(s) loeschen (Multi-ID)"),
            "priority": t("task_priority_desc", default="Prioritaet aendern"),
            "assign": t("task_assign_desc", default="Task(s) zuweisen (Multi-ID)"),
            "depends": t("task_depends_desc", default="Abhaengigkeit setzen/anzeigen"),
            "help": t("hilfe", default="Hilfe anzeigen")
        }
    
    def _get_db(self):
        """Datenbankverbindung holen"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _parse_ids(self, args: List[str]) -> Tuple[List[int], List[str]]:
        """Extrahiert IDs und restliche Argumente"""
        ids = []
        rest = []
        for arg in args:
            try:
                ids.append(int(arg))
            except ValueError:
                rest.append(arg)
        return ids, rest
    
    def _get_note(self, args: List[str]) -> Optional[str]:
        """Extrahiert --note aus Argumenten"""
        for i, arg in enumerate(args):
            if arg == "--note" and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith("--note="):
                return arg[7:]
        return None
    
    def _get_reason(self, args: List[str]) -> Optional[str]:
        """Extrahiert --reason aus Argumenten"""
        for i, arg in enumerate(args):
            if arg == "--reason" and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith("--reason="):
                return arg[9:]
        return None
    
    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """Haupteinstiegspunkt"""
        
        if operation == "add":
            return self._add(args)
        elif operation == "list":
            return self._list(args)
        elif operation == "edit":
            return self._edit(args)
        elif operation == "done":
            return self._done(args)
        elif operation == "block":
            return self._block(args)
        elif operation == "unblock":
            return self._unblock(args)
        elif operation == "reopen":
            return self._reopen(args)
        elif operation == "show":
            return self._show(args)
        elif operation == "delete":
            return self._delete(args)
        elif operation == "priority":
            return self._priority(args)
        elif operation == "assign":
            return self._assign(args)
        elif operation == "depends":
            return self._depends(args)
        elif operation in ["", "help"]:
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach task help"
    
    def _sanitize_title(self, title: str) -> str:
        """Titel bereinigen - unbalancierte Anfuehrungszeichen entfernen"""
        # Zaehle Anfuehrungszeichen
        double_quotes = title.count('"')
        single_quotes = title.count("'")
        
        # Unbalancierte entfernen
        if double_quotes % 2 != 0:
            title = title.replace('"', '')
        if single_quotes % 2 != 0:
            title = title.replace("'", '')
        
        # Whitespace normalisieren
        title = ' '.join(title.split())
        
        return title.strip()
    
    def _add(self, args: List[str]) -> Tuple[bool, str]:
        """Task hinzufuegen"""
        if not args:
            return False, "Usage: bach task add <titel> [--priority P1-P4] [--description TEXT]"
        
        title = self._sanitize_title(args[0])
        priority = "P3"
        description = ""
        category = "general"
        
        # Optionen parsen
        i = 1
        while i < len(args):
            if args[i] in ["--priority", "-p"] and i + 1 < len(args):
                priority = args[i + 1].upper()
                i += 2
            elif args[i] in ["--description", "-d"] and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif args[i] in ["--category", "-c"] and i + 1 < len(args):
                category = args[i + 1]
                i += 2
            else:
                i += 1
        
        with self._get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO tasks (title, priority, category, description, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', datetime('now'))
            """, (title, priority, category, description))
            task_id = cursor.lastrowid
            conn.commit()

        # Hook: after_task_create
        try:
            from core.hooks import hooks
            hooks.emit('after_task_create', {
                'task_id': task_id, 'title': title,
                'priority': priority, 'category': category
            })
        except Exception:
            pass

        return True, f"[OK] Task {task_id} erstellt: {title}"
    
    def _edit(self, args: List[str]) -> Tuple[bool, str]:
        """Task bearbeiten - Titel, Beschreibung, Kategorie, Zuweisung aendern"""
        if not args:
            return False, "Usage: bach task edit <id> [--title TEXT] [--description TEXT] [--category TEXT] [--assigned NAME]"
        
        # ID extrahieren
        try:
            task_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige Task-ID: {args[0]}"
        
        # Optionen parsen
        title = None
        description = None
        category = None
        assigned_to = None
        
        i = 1
        while i < len(args):
            if args[i] in ["--title", "-t"] and i + 1 < len(args):
                title = self._sanitize_title(args[i + 1])
                i += 2
            elif args[i] in ["--description", "-d"] and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif args[i] in ["--category", "-c"] and i + 1 < len(args):
                category = args[i + 1]
                i += 2
            elif args[i] in ["--assigned", "-a"] and i + 1 < len(args):
                assigned_to = args[i + 1].lower()
                i += 2
            else:
                i += 1
        
        # Pruefen ob mindestens eine Option angegeben wurde
        if title is None and description is None and category is None and assigned_to is None:
            return False, "Mindestens eine Option angeben: --title, --description, --category, --assigned"
        
        with self._get_db() as conn:
            # Pruefen ob Task existiert
            row = conn.execute("SELECT id, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return False, f"Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}"
            
            # Updates sammeln
            updates = []
            params = []
            changes = []
            
            if title is not None:
                updates.append("title = ?")
                params.append(title)
                changes.append(f"Titel -> {title[:40]}...")
            
            if description is not None:
                updates.append("description = ?")
                params.append(description)
                changes.append(f"Beschreibung aktualisiert ({len(description)} Zeichen)")
            
            if category is not None:
                updates.append("category = ?")
                params.append(category)
                changes.append(f"Kategorie -> {category}")
            
            if assigned_to is not None:
                updates.append("assigned_to = ?")
                params.append(assigned_to)
                changes.append(f"Zugewiesen -> {assigned_to}")
            
            # Update ausfuehren
            params.append(task_id)
            conn.execute(f"""
                UPDATE tasks SET {', '.join(updates)} WHERE id = ?
            """, params)
            conn.commit()
        
        return True, f"[OK] Task {task_id} bearbeitet: {', '.join(changes)}"
    
    def _list(self, args: List[str]) -> Tuple[bool, str]:
        """Tasks auflisten"""
        status_filter = "pending"
        filter_text = None
        assigned_filter = None
        unassigned_only = False
        
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ["all", "done", "pending", "open", "blocked"]:
                status_filter = arg if arg != "all" else None
            elif arg.startswith("--filter="):
                filter_text = arg[9:]
            elif arg == "--filter" and i + 1 < len(args):
                filter_text = args[i + 1]
                i += 1
            elif arg.startswith("--assigned="):
                assigned_filter = arg[11:].upper()
            elif arg == "--assigned" and i + 1 < len(args):
                assigned_filter = args[i + 1].upper()
                i += 1
            elif arg == "--unassigned":
                unassigned_only = True
            i += 1
        
        # Query aufbauen
        conditions = []
        params = []
        
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        
        if filter_text:
            conditions.append("title LIKE ?")
            params.append(f"%{filter_text}%")
        
        if assigned_filter:
            conditions.append("(assigned_to = ? OR delegated_to = ?)")
            params.extend([assigned_filter, assigned_filter])
        
        if unassigned_only:
            conditions.append("(assigned_to IS NULL OR assigned_to = '') AND (delegated_to IS NULL OR delegated_to = '')")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self._get_db() as conn:
            rows = conn.execute(f"""
                SELECT id, priority, title, status, category, assigned_to, delegated_to, depends_on 
                FROM tasks 
                WHERE {where_clause}
                ORDER BY priority, id
            """, params).fetchall()
            
            # Tasks in Liste umwandeln und Abhängigkeiten prüfen
            task_list = []
            for r in rows:
                item = dict(r)
                is_blocked = False
                if item['depends_on']:
                    dep_ids = [int(x.strip()) for x in item['depends_on'].split(',') if x.strip()]
                    total_unfinished = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join(['?']*len(dep_ids))}) AND status != 'done'", dep_ids).fetchone()[0]
                    if total_unfinished > 0:
                        is_blocked = True
                item['is_blocked_by_dep'] = is_blocked
                task_list.append(item)
        
        if not task_list:
            filter_desc = []
            if status_filter:
                filter_desc.append(f"Status: {status_filter}")
            if assigned_filter:
                filter_desc.append(f"Assigned: {assigned_filter}")
            if unassigned_only:
                filter_desc.append("Unassigned")
            return True, f"Keine Tasks gefunden ({', '.join(filter_desc) or 'alle'})"
        
        # Header
        header_parts = [status_filter or 'alle']
        if assigned_filter:
            header_parts.append(f"→{assigned_filter}")
        if unassigned_only:
            header_parts.append("unassigned")
        
        lines = [f"\n[TASKS] Tasks ({', '.join(header_parts)}):\n"]
        for t in task_list:
            # Partner-Anzeige
            partner = t['assigned_to'] or t['delegated_to'] or ""
            partner_suffix = f" →{partner}" if partner else ""
            blocked_mark = " (BLOCKED)" if t['is_blocked_by_dep'] else ""
            lines.append(f"  [{t['id']}] {t['priority']} {t['title'][:50]}{partner_suffix}{blocked_mark}")
        
        return True, "\n".join(lines)
    
    def _done(self, args: List[str]) -> Tuple[bool, str]:
        """Task(s) als erledigt markieren - Multi-ID Support"""
        ids, rest = self._parse_ids(args)
        
        if not ids:
            return False, "Usage: bach task done <id> [id2 id3...] [--note TEXT]"
        
        note = self._get_note(rest)
        results = []
        
        with self._get_db() as conn:
            for task_id in ids:
                # Pruefen ob Task existiert
                row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    results.append(f"[WARN] Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}")
                    continue
                
                # Task als done markieren
                conn.execute("""
                    UPDATE tasks 
                    SET status = 'done', completed_at = datetime('now')
                    WHERE id = ?
                """, (task_id,))
                
                # Note speichern falls vorhanden
                if note:
                    conn.execute("""
                        UPDATE tasks SET description = 
                            CASE WHEN description IS NULL OR description = '' 
                            THEN ? ELSE description || char(10) || char(10) || ? END
                        WHERE id = ?
                    """, (f"[DONE] {note}", f"[DONE] {note}", task_id))
                
                results.append(f"[OK] Task {task_id} erledigt!")

                # Hook: after_task_done
                try:
                    from core.hooks import hooks
                    hooks.emit('after_task_done', {
                        'task_id': task_id, 'title': row['title']
                    })
                except Exception:
                    pass

            conn.commit()

        return True, "\n".join(results)

    def _block(self, args: List[str]) -> Tuple[bool, str]:
        """Task(s) blockieren - Multi-ID Support"""
        ids, rest = self._parse_ids(args)
        
        if not ids:
            return False, "Usage: bach task block <id> [id2 id3...] [--reason TEXT]"
        
        reason = self._get_reason(rest)
        results = []
        
        with self._get_db() as conn:
            for task_id in ids:
                row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    results.append(f"[WARN] Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}")
                    continue
                
                conn.execute("""
                    UPDATE tasks SET status = 'blocked'
                    WHERE id = ?
                """, (task_id,))
                
                if reason:
                    conn.execute("""
                        UPDATE tasks SET description = 
                            CASE WHEN description IS NULL OR description = '' 
                            THEN ? ELSE description || char(10) || char(10) || ? END
                        WHERE id = ?
                    """, (f"[BLOCKED] {reason}", f"[BLOCKED] {reason}", task_id))
                
                results.append(f"[OK] Task {task_id} blockiert" + (f" ({reason})" if reason else ""))
            
            conn.commit()
        
        return True, "\n".join(results)
    
    def _unblock(self, args: List[str]) -> Tuple[bool, str]:
        """Task(s) entblocken - Multi-ID Support"""
        ids, rest = self._parse_ids(args)
        
        if not ids:
            return False, "Usage: bach task unblock <id> [id2 id3...]"
        
        results = []
        
        with self._get_db() as conn:
            for task_id in ids:
                row = conn.execute("SELECT title, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    results.append(f"[WARN] Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}")
                    continue
                
                if row['status'] != 'blocked':
                    results.append(f"[INFO] Task {task_id} war nicht blockiert")
                    continue
                
                conn.execute("""
                    UPDATE tasks SET status = 'pending'
                    WHERE id = ?
                """, (task_id,))
                
                results.append(f"[OK] Task {task_id} entblockt")
            
            conn.commit()
        
        return True, "\n".join(results)
    
    def _reopen(self, args: List[str]) -> Tuple[bool, str]:
        """Task(s) wieder oeffnen (done -> pending) - Multi-ID Support"""
        ids, rest = self._parse_ids(args)
        
        if not ids:
            return False, "Usage: bach task reopen <id> [id2 id3...]"
        
        results = []
        
        with self._get_db() as conn:
            for task_id in ids:
                row = conn.execute("SELECT title, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    results.append(f"[WARN] Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}")
                    continue
                
                conn.execute("""
                    UPDATE tasks SET status = 'pending', completed_at = NULL
                    WHERE id = ?
                """, (task_id,))
                
                results.append(f"[OK] Task {task_id} wieder geoeffnet")
            
            conn.commit()
        
        return True, "\n".join(results)
    
    def _delete(self, args: List[str]) -> Tuple[bool, str]:
        """Task(s) loeschen - Multi-ID Support"""
        ids, rest = self._parse_ids(args)
        
        if not ids:
            return False, "Usage: bach task delete <id> [id2 id3...]"
        
        results = []
        
        with self._get_db() as conn:
            for task_id in ids:
                row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    results.append(f"[WARN] Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}")
                    continue
                
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                results.append(f"[OK] Task {task_id} geloescht: {row['title'][:40]}")
            
            conn.commit()
        
        return True, "\n".join(results)
    
    def _show(self, args: List[str]) -> Tuple[bool, str]:
        """Task-Details anzeigen"""
        if not args:
            return False, "Usage: bach task show <id>"
        
        try:
            task_id = int(args[0])
        except ValueError:
            return False, "Ungueltige Task-ID"
        
        with self._get_db() as conn:
            row = conn.execute("""
                SELECT * FROM tasks WHERE id = ?
            """, (task_id,)).fetchone()
        
        if not row:
            return False, f"Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}"
        
        lines = [
            f"\n=== TASK {task_id} ===",
            f"Titel:       {row['title']}",
            f"Status:      {row['status']}",
            f"Prioritaet:  {row['priority']}",
            f"Kategorie:   {row['category'] or '-'}",
            f"Erstellt:    {row['created_at']}",
        ]
        
        if row['completed_at']:
            lines.append(f"Erledigt:    {row['completed_at']}")
        
        if row['description']:
            lines.append(f"\nBeschreibung:\n{row['description']}")
        
        return True, "\n".join(lines)
    
    def _priority(self, args: List[str]) -> Tuple[bool, str]:
        """Prioritaet aendern"""
        if len(args) < 2:
            return False, "Usage: bach task priority <id> <P1-P4>"
        
        try:
            task_id = int(args[0])
        except ValueError:
            return False, "Ungueltige Task-ID"
        
        priority = args[1].upper()
        if priority not in ["P1", "P2", "P3", "P4"]:
            return False, "Prioritaet muss P1, P2, P3 oder P4 sein"
        
        with self._get_db() as conn:
            row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return False, f"Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}"
            
            conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
            conn.commit()
        
        return True, f"[OK] Task {task_id} Prioritaet: {priority}"
    
    def _assign(self, args: List[str]) -> Tuple[bool, str]:
        """Task(s) einem Partner zuweisen - Multi-ID Support"""
        ids, rest = self._parse_ids(args)
        
        if not ids:
            return False, "Usage: bach task assign <id> [id2...] --to PARTNER"
        
        # Partner extrahieren
        partner = None
        for i, arg in enumerate(rest):
            if arg == "--to" and i + 1 < len(rest):
                partner = rest[i + 1].upper()
            elif arg.startswith("--to="):
                partner = arg[5:].upper()
        
        if not partner:
            return False, "Fehler: --to PARTNER erforderlich\nBeispiel: bach task assign 100 --to GEMINI"
        
        # Bekannte Partner validieren (optional, aber hilfreich)
        known_partners = ["CLAUDE", "GEMINI", "COPILOT", "OLLAMA", "CHATGPT", "PERPLEXITY", "HUMAN"]
        if partner not in known_partners:
            warning = f"[INFO] Partner '{partner}' nicht in bekannter Liste ({', '.join(known_partners[:3])}...)"
        else:
            warning = ""
        
        results = []
        
        with self._get_db() as conn:
            for task_id in ids:
                row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if not row:
                    results.append(f"[WARN] Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}")
                    continue
                
                conn.execute("""
                    UPDATE tasks SET assigned_to = ?, delegated_to = ?, updated_at = datetime('now')
                    WHERE id = ?
                """, (partner, partner, task_id))
                
                results.append(f"[OK] Task {task_id} -> {partner}")
            
            conn.commit()
        
        if warning:
            results.insert(0, warning)
        
        return True, "\n".join(results)
    
    def _depends(self, args: List[str]) -> Tuple[bool, str]:
        """Task-Abhaengigkeit setzen/anzeigen
        
        Usage:
          bach task depends <id>              Abhaengigkeiten anzeigen
          bach task depends <id> --on <id2>   Abhaengigkeit hinzufuegen
          bach task depends <id> --remove <id2>  Abhaengigkeit entfernen
          bach task depends <id> --clear      Alle Abhaengigkeiten loeschen
        """
        if not args:
            return False, "Usage: bach task depends <id> [--on <id2>] [--remove <id2>] [--clear]"
        
        try:
            task_id = int(args[0])
        except ValueError:
            return False, "Ungueltige Task-ID"
        
        # Optionen extrahieren
        on_id = None
        remove_id = None
        clear_all = False
        
        i = 1
        while i < len(args):
            if args[i] == "--on" and i + 1 < len(args):
                try:
                    on_id = int(args[i + 1])
                except ValueError:
                    return False, f"Ungueltige Abhaengigkeits-ID: {args[i + 1]}"
                i += 2
            elif args[i].startswith("--on="):
                try:
                    on_id = int(args[i][5:])
                except ValueError:
                    return False, f"Ungueltige Abhaengigkeits-ID: {args[i][5:]}"
                i += 1
            elif args[i] == "--remove" and i + 1 < len(args):
                try:
                    remove_id = int(args[i + 1])
                except ValueError:
                    return False, f"Ungueltige Abhaengigkeits-ID: {args[i + 1]}"
                i += 2
            elif args[i].startswith("--remove="):
                try:
                    remove_id = int(args[i][9:])
                except ValueError:
                    return False, f"Ungueltige Abhaengigkeits-ID: {args[i][9:]}"
                i += 1
            elif args[i] == "--clear":
                clear_all = True
                i += 1
            else:
                i += 1
        
        with self._get_db() as conn:
            # Pruefen ob Task existiert
            row = conn.execute("SELECT title, depends_on FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return False, f"Task {task_id} {t('nicht_gefunden', default='nicht gefunden')}"
            
            current_deps = set()
            if row['depends_on']:
                current_deps = set(int(x) for x in row['depends_on'].split(',') if x.strip())
            
            # Clear all
            if clear_all:
                conn.execute("UPDATE tasks SET depends_on = NULL, updated_at = datetime('now') WHERE id = ?", (task_id,))
                conn.commit()
                return True, f"[OK] Task {task_id}: Alle Abhaengigkeiten entfernt"
            
            # Add dependency
            if on_id:
                # Pruefen ob Ziel-Task existiert
                target = conn.execute("SELECT title FROM tasks WHERE id = ?", (on_id,)).fetchone()
                if not target:
                    return False, f"Ziel-Task {on_id} {t('nicht_gefunden', default='nicht gefunden')}"
                
                # Zirkulaere Abhaengigkeit pruefen
                if on_id == task_id:
                    return False, "Zirkulaere Abhaengigkeit: Task kann nicht von sich selbst abhaengen"
                
                # Bereits vorhanden?
                if on_id in current_deps:
                    return True, f"[INFO] Task {task_id} haengt bereits von Task {on_id} ab"
                
                current_deps.add(on_id)
                new_deps = ','.join(str(x) for x in sorted(current_deps))
                conn.execute("UPDATE tasks SET depends_on = ?, updated_at = datetime('now') WHERE id = ?", (new_deps, task_id))
                conn.commit()
                return True, f"[OK] Task {task_id} haengt jetzt von Task {on_id} ab ({target['title'][:30]})"
            
            # Remove dependency
            if remove_id:
                if remove_id not in current_deps:
                    return True, f"[INFO] Task {task_id} hatte keine Abhaengigkeit zu Task {remove_id}"
                
                current_deps.discard(remove_id)
                new_deps = ','.join(str(x) for x in sorted(current_deps)) if current_deps else None
                conn.execute("UPDATE tasks SET depends_on = ?, updated_at = datetime('now') WHERE id = ?", (new_deps, task_id))
                conn.commit()
                return True, f"[OK] Abhaengigkeit von Task {task_id} zu Task {remove_id} entfernt"
            
            # Show dependencies (default)
            if not current_deps:
                return True, f"\n=== TASK {task_id} ABHAENGIGKEITEN ===\n{row['title']}\n\nKeine Abhaengigkeiten definiert."
            
            lines = [f"\n=== TASK {task_id} ABHAENGIGKEITEN ===", f"{row['title']}", "", "Haengt ab von:"]
            for dep_id in sorted(current_deps):
                dep_row = conn.execute("SELECT title, status FROM tasks WHERE id = ?", (dep_id,)).fetchone()
                if dep_row:
                    status_icon = "✓" if dep_row['status'] == 'done' else "○" if dep_row['status'] == 'pending' else "⊘"
                    lines.append(f"  [{dep_id}] {status_icon} {dep_row['title'][:50]}")
                else:
                    lines.append(f"  [{dep_id}] [GELOESCHT]")
            
            # Blockierungsstatus
            pending_deps = []
            for dep_id in current_deps:
                dep_row = conn.execute("SELECT status FROM tasks WHERE id = ?", (dep_id,)).fetchone()
                if dep_row and dep_row['status'] != 'done':
                    pending_deps.append(dep_id)
            
            if pending_deps:
                lines.append(f"\n[BLOCKIERT] {len(pending_deps)} offene Abhaengigkeit(en)")
            else:
                lines.append("\n[BEREIT] Alle Abhaengigkeiten erfuellt")
            
            return True, "\n".join(lines)
    
    def _help(self) -> Tuple[bool, str]:
        """Hilfe anzeigen"""
        return True, """
TASK-VERWALTUNG
===============

Befehle:
  bach task add <titel>              Task hinzufuegen
  bach task list [status]            Tasks auflisten (pending/done/blocked/all)
  bach task list --filter TERM       Tasks nach Begriff filtern
  bach task list --assigned PARTNER  Tasks nach Partner filtern
  bach task list --unassigned        Nur unzugewiesene Tasks
  bach task done <id> [id2...]       Task(s) erledigen
  bach task block <id> [id2...]      Task(s) blockieren
  bach task unblock <id> [id2...]    Task(s) entblocken
  bach task reopen <id> [id2...]     Task(s) wieder oeffnen
  bach task assign <id> --to PARTNER Task(s) zuweisen (GEMINI, COPILOT, etc.)
  bach task depends <id>             Abhaengigkeiten anzeigen
  bach task depends <id> --on <id2>  Abhaengigkeit hinzufuegen
  bach task depends <id> --remove <id2>  Abhaengigkeit entfernen
  bach task depends <id> --clear     Alle Abhaengigkeiten loeschen
  bach task show <id>                Task-Details
  bach task delete <id> [id2...]     Task(s) loeschen
  bach task priority <id> <P1-P4>    Prioritaet aendern

Filter-Optionen (kombinierbar):
  --filter TERM           Nach Begriff im Titel
  --assigned PARTNER      Nach zugewiesenem Partner
  --unassigned            Nur Tasks ohne Zuweisung

Weitere Optionen:
  --priority, -p P1-P4    Prioritaet beim Erstellen
  --description, -d TEXT  Beschreibung beim Erstellen
  --note TEXT             Notiz beim Erledigen
  --reason TEXT           Grund beim Blockieren
  --to PARTNER            Partner beim Zuweisen

Beispiele:
  bach task done 319 320 321 --note "Alle Help-Dateien erstellt"
  bach task assign 100 101 --to GEMINI
  bach task depends 306 --on 305   # Task 306 wartet auf 305
  bach task list pending --assigned COPILOT
  bach task list all --unassigned
"""
