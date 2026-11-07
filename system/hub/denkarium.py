# SPDX-License-Identifier: MIT
"""
Denkarium Handler - Logbuch + Gedanken-Sammler
===============================================
Dies ist das persönliche Notizbuch des Users — NICHT als Board/Scratchpad für
Agenten nutzen. Agenten nutzen stattdessen `bach memory` (Fakten/Lektionen) und
Session-Berichte.

bach denkarium write "Text"         Gedanken notieren
bach denkarium write "Text" --type logbuch  Logbuch-Eintrag (Sternzeit)
bach denkarium read                 Letzte Eintraege lesen
bach denkarium read --type logbuch  Nur Logbuch-Eintraege
bach denkarium search "Begriff"     Suchen
bach denkarium brainstorm "Thema"   Ideen zu einem Thema sammeln
bach denkarium promote <id> task    Eintrag zu Task befoerdern

Referenz: SQ045, Runde 34
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("build-your-users-mind")
class DenkariumHandler(BaseHandler):
    """Handler fuer bach denkarium Operationen."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        from .bach_paths import BACH_DB
        self.db_path = BACH_DB

    @property
    def profile_name(self) -> str:
        return "denkarium"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "write": "Gedanken notieren: write \"Text\" [--type=logbuch] [--cat=idee]",
            "read": "Eintraege lesen [--type=logbuch|denkarium] [--cat=CAT] [--limit=N]",
            "search": "Suchen: search \"Begriff\"",
            "brainstorm": "Ideen sammeln: brainstorm \"Thema\"",
            "promote": "Befoerdern: promote <id> task|wiki",
            "categories": "Kategorien auflisten",
            "stats": "Statistik anzeigen",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "write" and args:
            return self._write(args, dry_run)
        elif operation == "read":
            return self._read(args)
        elif operation == "search" and args:
            return self._search(args[0])
        elif operation == "brainstorm" and args:
            return self._brainstorm(args[0], dry_run)
        elif operation == "promote" and len(args) >= 2:
            return self._promote(args[0], args[1], dry_run)
        elif operation == "categories":
            return self._categories()
        elif operation == "stats":
            return self._stats()
        else:
            ops = self.get_operations()
            lines = ["DENKARIUM - Logbuch + Gedanken-Sammler", "=" * 50, ""]
            lines.append("Zwei Modi:")
            lines.append("  denkarium  Freie Gedanken, Ideen, Reflexionen")
            lines.append("  logbuch    Chronologisches Tagebuch (Sternzeit)")
            lines.append("")
            for op, desc in ops.items():
                lines.append(f"  bach denkarium {op:12s} {desc}")
            return True, "\n".join(lines)

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _format_entries(entries: list, header: str, with_mood: bool, short: int = 80) -> str:
        """Listing in the legacy layout; ids as `notes_adapter.display_id` (old numbers stay valid)."""
        from hub._services import notes_adapter

        lines = [header, "=" * 60, ""]
        for e in entries:
            icon = "B" if e["entry_type"] == "logbook" else "D"
            mood = f" [{e['mood']}/5]" if with_mood and e["mood"] else ""
            title = f" {e['title']}" if e["title"] else ""
            did = notes_adapter.display_id(e)
            if with_mood:
                lines.append(f"  [{icon}] #{did} [{e['created_at']}] ({e['category']}){mood}{title}")
            else:
                lines.append(f"  [{icon}] #{did} [{e['created_at']}]{title}")
            content = e["content"]
            if len(content) > short:
                content = content[:short - 3] + "..."
            lines.append(f"      {content}")
            lines.append("")
        return "\n".join(lines)

    def _promote_llm(self, entry_id: str, target: str, dry_run: bool) -> tuple:
        from hub._services import notes_adapter

        try:
            llm_id = notes_adapter.resolve_display_id(entry_id)
        except ValueError as exc:
            return False, str(exc)
        except KeyError as exc:
            return False, exc.args[0]
        note = notes_adapter.get_note(llm_id)
        shown = notes_adapter.display_id(note)
        if dry_run:
            return True, f"[DRY-RUN] Wuerde #{shown} zu {target} befoerdern"
        promoted_id = 0  # wiki promotion only marks, as before
        if target == 'task':
            conn = self._get_conn()
            cur = conn.execute(
                "INSERT INTO tasks (title, description, status, priority, assigned_to, dist_type) "
                "VALUES (?, ?, 'pending', 3, 'user', 0)",
                (note["title"] or note["content"][:50], note["content"]))
            promoted_id = cur.lastrowid
            conn.commit()
            conn.close()
        notes_adapter.mark_promoted(llm_id, target, promoted_id)
        if target == 'task':
            return True, f"[OK] Eintrag #{shown} zu Task #{promoted_id} befoerdert"
        return True, f"[OK] Eintrag #{shown} fuer Wiki-Erstellung markiert"

    def _write(self, args: list, dry_run: bool) -> tuple:
        """Neuen Eintrag schreiben."""
        text = args[0]
        entry_type = "denkarium"
        category = "notiz"
        title = None
        mood = None

        for arg in args[1:]:
            if arg.startswith("--type="):
                entry_type = arg.split("=", 1)[1]
            elif arg.startswith("--cat="):
                category = arg.split("=", 1)[1]
            elif arg.startswith("--title="):
                title = arg.split("=", 1)[1]
            elif arg.startswith("--mood="):
                try:
                    mood = int(arg.split("=", 1)[1])
                except ValueError:
                    pass

        if dry_run:
            return True, f"[DRY-RUN] Wuerde {entry_type}-Eintrag erstellen"

        from hub._services import notes_adapter

        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            entry_id = notes_adapter.denkarium_create({
                "content": text, "entry_type": entry_type, "category": category, "title": title,
                "mood": mood, "source": "user"})["id"]
            type_label = "Logbuch" if entry_type == "logbuch" else "Denkarium"
            return True, f"[OK] {type_label}-Eintrag #n{entry_id} gespeichert ({category})"

        conn = self._get_conn()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Sternzeit fuer Logbuch
        if entry_type == "logbuch" and not title:
            title = f"Sternzeit {now}"

        conn.execute("""
            INSERT INTO denkarium_entries
                (entry_type, title, content, category, source, mood, created_at)
            VALUES (?, ?, ?, ?, 'user', ?, ?)
        """, (entry_type, title, text, category, mood, now))

        entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        type_label = "Logbuch" if entry_type == "logbuch" else "Denkarium"
        return True, f"[OK] {type_label}-Eintrag #{entry_id} gespeichert ({category})"

    def _read(self, args: list) -> tuple:
        """Eintraege lesen."""
        entry_type = None
        category = None
        limit = 10

        for arg in args:
            if arg.startswith("--type="):
                entry_type = arg.split("=", 1)[1]
            elif arg.startswith("--cat="):
                category = arg.split("=", 1)[1]
            elif arg.startswith("--limit="):
                try:
                    limit = int(arg.split("=", 1)[1])
                except ValueError:
                    pass

        from hub._services import notes_adapter

        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            found = notes_adapter.list_notes(entry_type=entry_type, category=category, limit=limit)["entries"]
            return True, self._format_entries(found, f"DENKARIUM ({entry_type or 'alle'}, letzte {limit})", with_mood=True)

        conn = self._get_conn()

        query = "SELECT id, entry_type, title, content, category, mood, created_at FROM denkarium_entries"
        conditions = []
        params = []

        if entry_type:
            conditions.append("entry_type = ?")
            params.append(entry_type)
        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        conn.close()

        if not rows:
            return True, "Keine Eintraege gefunden."

        type_label = entry_type or "alle"
        lines = [f"DENKARIUM ({type_label}, letzte {limit})", "=" * 60, ""]

        for row in rows:
            mood_str = f" [{row['mood']}/5]" if row['mood'] else ""
            title_str = f" {row['title']}" if row['title'] else ""
            type_icon = "B" if row['entry_type'] == 'logbuch' else "D"

            lines.append(f"  [{type_icon}] #{row['id']} [{row['created_at']}] ({row['category']}){mood_str}{title_str}")

            content = row['content']
            if len(content) > 80:
                content = content[:77] + "..."
            lines.append(f"      {content}")
            lines.append("")

        return True, "\n".join(lines)

    def _search(self, term: str) -> tuple:
        """In Eintraegen suchen."""
        from hub._services import notes_adapter

        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            found = notes_adapter.list_notes(search=term, limit=20)["entries"]
            if not found:
                return True, f"Keine Treffer fuer '{term}'."
            return True, self._format_entries(found, f"DENKARIUM-SUCHE: {term}", with_mood=False, short=60) + f"\n{len(found)} Treffer"

        conn = self._get_conn()
        rows = conn.execute("""
            SELECT id, entry_type, title, content, category, created_at
            FROM denkarium_entries
            WHERE content LIKE ? OR title LIKE ? OR category LIKE ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (f"%{term}%", f"%{term}%", f"%{term}%")).fetchall()
        conn.close()

        if not rows:
            return True, f"Keine Treffer fuer '{term}'."

        lines = [f"DENKARIUM-SUCHE: {term}", "=" * 50, ""]
        for row in rows:
            type_icon = "B" if row['entry_type'] == 'logbuch' else "D"
            title_str = f" {row['title']}" if row['title'] else ""
            content = row['content'][:60] + "..." if len(row['content']) > 60 else row['content']
            lines.append(f"  [{type_icon}] #{row['id']} [{row['created_at']}]{title_str}")
            lines.append(f"      {content}")
            lines.append("")

        lines.append(f"{len(rows)} Treffer")
        return True, "\n".join(lines)

    def _brainstorm(self, topic: str, dry_run: bool) -> tuple:
        """Brainstorm-Eintrag erstellen."""
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Brainstorm zu '{topic}' erstellen"

        from hub._services import notes_adapter

        title = f"Brainstorm: {topic}"
        content = f"Thema: {topic}\n\nIdeen:\n- \n\n(Ergaenze Ideen mit: bach denkarium write \"Idee\" --cat=idee)"
        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            entry_id = notes_adapter.denkarium_create({
                "content": content, "entry_type": "denkarium", "category": "brainstorm", "title": title,
                "source": "user"})["id"]
            return True, f"[OK] Brainstorm #n{entry_id} gestartet: {topic}\n     Ideen ergaenzen mit: bach denkarium write \"Idee\" --cat=idee"

        conn = self._get_conn()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        conn.execute("""
            INSERT INTO denkarium_entries
                (entry_type, title, content, category, source, created_at)
            VALUES ('denkarium', ?, ?, 'brainstorm', 'user', ?)
        """, (title, content, now))

        entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        return True, f"[OK] Brainstorm #{entry_id} gestartet: {topic}\n     Ideen ergaenzen mit: bach denkarium write \"Idee\" --cat=idee"

    def _promote(self, entry_id: str, target: str, dry_run: bool) -> tuple:
        """Eintrag zu Task oder Wiki befoerdern."""
        if target not in ('task', 'wiki'):
            return False, "Ziel muss 'task' oder 'wiki' sein."

        from hub._services import notes_adapter

        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            return self._promote_llm(entry_id, target, dry_run)

        try:
            eid = int(entry_id)
        except ValueError:
            return False, "Ungueltige Entry-ID."

        conn = self._get_conn()
        entry = conn.execute(
            "SELECT id, title, content FROM denkarium_entries WHERE id = ?",
            (eid,)
        ).fetchone()

        if not entry:
            conn.close()
            return False, f"Eintrag #{eid} nicht gefunden."

        if dry_run:
            conn.close()
            return True, f"[DRY-RUN] Wuerde #{eid} zu {target} befoerdern"

        title = entry['title'] or entry['content'][:50]

        if target == 'task':
            conn.execute(
                "INSERT INTO tasks (title, description, status, priority, assigned_to, dist_type) "
                "VALUES (?, ?, 'pending', 3, 'user', 0)",
                (title, entry['content'])
            )
            promoted_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            # Wiki-Promotion ist komplexer, hier nur markieren
            promoted_id = 0

        conn.execute(
            "UPDATE denkarium_entries SET promoted_to = ?, promoted_id = ?, updated_at = ? WHERE id = ?",
            (target, promoted_id, datetime.now().isoformat(), eid)
        )
        conn.commit()
        conn.close()

        if target == 'task':
            return True, f"[OK] Eintrag #{eid} zu Task #{promoted_id} befoerdert"
        else:
            return True, f"[OK] Eintrag #{eid} fuer Wiki-Erstellung markiert"

    def _categories(self) -> tuple:
        """Kategorien auflisten."""
        from hub._services import notes_adapter

        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            counts: dict = {}
            for e in notes_adapter.list_notes(limit=1000)["entries"]:
                key = (e["category"], "logbuch" if e["entry_type"] == "logbook" else "denkarium")
                counts[key] = counts.get(key, 0) + 1
            if not counts:
                return True, "Keine Eintraege vorhanden."
            lines = ["DENKARIUM-KATEGORIEN", "=" * 40, ""]
            for (category, kind), cnt in sorted(counts.items()):
                lines.append(f"  {category:20s} [{'Logbuch' if kind == 'logbuch' else 'Denkarium':10s}] ({cnt} Eintraege)")
            return True, "\n".join(lines)

        conn = self._get_conn()
        rows = conn.execute("""
            SELECT category, entry_type, COUNT(*) as cnt
            FROM denkarium_entries
            GROUP BY category, entry_type
            ORDER BY category, entry_type
        """).fetchall()
        conn.close()

        if not rows:
            return True, "Keine Eintraege vorhanden."

        lines = ["DENKARIUM-KATEGORIEN", "=" * 40, ""]
        for row in rows:
            type_label = "Logbuch" if row['entry_type'] == 'logbuch' else 'Denkarium'
            lines.append(f"  {row['category']:20s} [{type_label:10s}] ({row['cnt']} Eintraege)")

        return True, "\n".join(lines)

    def _stats(self) -> tuple:
        """Statistik anzeigen."""
        from hub._services import notes_adapter

        if notes_adapter.use_llm_note(self.db_path):  # migrated: llm-note is the single store (PB-11)
            entries = notes_adapter.list_notes(include_archived=True, limit=1000)["entries"]
            dates = sorted(e["created_at"] for e in entries if e["created_at"])
            lines = [
                "DENKARIUM-STATISTIK", "=" * 40, "",
                f"  Gesamt:    {len(entries)}",
                f"  Logbuch:   {sum(e['entry_type'] == 'logbook' for e in entries)}",
                f"  Denkarium: {sum(e['entry_type'] == 'note' for e in entries)}",
                f"  Befoerdert: {sum(e['promoted_to'] is not None for e in entries)}",
                "",
                f"  Erster Eintrag: {dates[0] if dates else '-'}",
                f"  Letzter Eintrag: {dates[-1] if dates else '-'}",
            ]
            return True, "\n".join(lines)

        conn = self._get_conn()

        total = conn.execute("SELECT COUNT(*) FROM denkarium_entries").fetchone()[0]
        logbuch = conn.execute("SELECT COUNT(*) FROM denkarium_entries WHERE entry_type='logbuch'").fetchone()[0]
        denkarium = conn.execute("SELECT COUNT(*) FROM denkarium_entries WHERE entry_type='denkarium'").fetchone()[0]
        promoted = conn.execute("SELECT COUNT(*) FROM denkarium_entries WHERE promoted_to IS NOT NULL").fetchone()[0]

        first = conn.execute("SELECT MIN(created_at) FROM denkarium_entries").fetchone()[0]
        last = conn.execute("SELECT MAX(created_at) FROM denkarium_entries").fetchone()[0]

        conn.close()

        lines = [
            "DENKARIUM-STATISTIK",
            "=" * 40,
            "",
            f"  Gesamt:    {total}",
            f"  Logbuch:   {logbuch}",
            f"  Denkarium: {denkarium}",
            f"  Befoerdert: {promoted}",
            "",
            f"  Erster Eintrag: {first or '-'}",
            f"  Letzter Eintrag: {last or '-'}",
        ]

        return True, "\n".join(lines)
