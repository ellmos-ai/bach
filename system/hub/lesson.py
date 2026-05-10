# SPDX-License-Identifier: MIT
"""
Lesson Handler - Lessons Learned Management
============================================

bach lesson add "Titel" --problem "..." --solution "..."
bach lesson list [category]
bach lesson search "keyword"
bach lesson show ID
bach lesson last [n]
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


class LessonHandler(BaseHandler):
    """Handler fuer --lesson Operationen"""
    
    CATEGORIES = ['bug', 'workflow', 'tool', 'integration', 'performance', 'general']
    SEVERITIES = ['low', 'medium', 'high', 'critical']
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "lesson"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "add": "Neue Lesson hinzufuegen",
            "edit": "Lesson bearbeiten (NEU v1.1.70)",
            "deactivate": "Lesson deaktivieren (NEU v1.1.70)",
            "list": "Alle Lessons anzeigen",
            "last": "Letzte n Lessons (Standard: 5)",
            "search": "Lessons durchsuchen",
            "show": "Details einer Lesson",
            "categories": "Verfuegbare Kategorien"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.db_path.exists():
            return False, f"Datenbank nicht gefunden: {self.db_path}"
        
        if operation == "add":
            return self._add(args, dry_run)
        elif operation == "edit":
            return self._edit(args)
        elif operation == "deactivate":
            return self._deactivate(args)
        elif operation == "list":
            category = args[0] if args else None
            return self._list(category)
        elif operation == "last":
            n = int(args[0]) if args else 5
            return self._last(n)
        elif operation == "search":
            if not args:
                return False, "Usage: --lesson search \"keyword\""
            return self._search(" ".join(args))
        elif operation == "show":
            if not args:
                return False, "Usage: --lesson show ID"
            return self._show(args[0])
        elif operation == "categories":
            return True, f"Kategorien: {', '.join(self.CATEGORIES)}"
        else:
            return self._last(5)
    
    def _add(self, args: list, dry_run: bool) -> tuple:
        """Lesson hinzufuegen - Parsing von Args."""
        if not args:
            return False, self._add_usage()
        
        # Einfacher Modus: nur Titel+Solution als ein String
        # Format: "Titel: Solution" oder "Titel -- Solution"
        full_text = " ".join(args)
        
        # Parse --category, --severity, --problem
        category = "general"
        severity = "medium"
        problem = None
        title = full_text
        solution = full_text
        
        # --category extrahieren
        if "--category" in full_text:
            parts = full_text.split("--category")
            full_text = parts[0].strip()
            cat_part = parts[1].strip().split()[0] if parts[1].strip() else "general"
            if cat_part in self.CATEGORIES:
                category = cat_part
        
        # --severity extrahieren
        if "--severity" in full_text:
            parts = full_text.split("--severity")
            full_text = parts[0].strip()
            sev_part = parts[1].strip().split()[0] if parts[1].strip() else "medium"
            if sev_part in self.SEVERITIES:
                severity = sev_part
        
        # --problem extrahieren
        if "--problem" in full_text:
            parts = full_text.split("--problem")
            full_text = parts[0].strip()
            problem = parts[1].strip()
        
        # Titel:Solution oder Titel--Solution parsen
        if ":" in full_text and not full_text.startswith("http"):
            parts = full_text.split(":", 1)
            title = parts[0].strip()
            solution = parts[1].strip() if len(parts) > 1 else title
        elif "--" in full_text:
            parts = full_text.split("--", 1)
            title = parts[0].strip()
            solution = parts[1].strip() if len(parts) > 1 else title
        else:
            title = full_text[:50] + "..." if len(full_text) > 50 else full_text
            solution = full_text
        
        if dry_run:
            return True, f"[DRY-RUN] Lesson: {title}\n  Category: {category}\n  Solution: {solution[:50]}..."
        
        # In DB speichern
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO memory_lessons 
                (category, severity, title, problem, solution, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (category, severity, title, problem, solution, now, now))
            conn.commit()
            lesson_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Hook: after_lesson_add
            try:
                from core.hooks import hooks
                hooks.emit('after_lesson_add', {
                    'lesson_id': lesson_id, 'title': title,
                    'category': category, 'severity': severity
                })
            except Exception:
                pass

            return True, f"[OK] Lesson #{lesson_id} gespeichert: {title}"
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()
    
    def _edit(self, args: list) -> tuple:
        """Lesson bearbeiten - Titel, Solution, Category, Severity aendern"""
        if not args:
            return False, "Usage: bach lesson edit <id> [--title TEXT] [--solution TEXT] [--category CAT] [--severity SEV]"
        
        # ID extrahieren
        try:
            lesson_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige Lesson-ID: {args[0]}"
        
        # Optionen parsen
        title = None
        solution = None
        category = None
        severity = None
        
        i = 1
        while i < len(args):
            if args[i] in ["--title", "-t"] and i + 1 < len(args):
                title = args[i + 1]
                i += 2
            elif args[i] in ["--solution", "-s"] and i + 1 < len(args):
                solution = args[i + 1]
                i += 2
            elif args[i] in ["--category", "-c"] and i + 1 < len(args):
                cat = args[i + 1].lower()
                if cat in self.CATEGORIES:
                    category = cat
                else:
                    return False, f"Ungueltige Kategorie: {cat}. Erlaubt: {', '.join(self.CATEGORIES)}"
                i += 2
            elif args[i] in ["--severity"] and i + 1 < len(args):
                sev = args[i + 1].lower()
                if sev in self.SEVERITIES:
                    severity = sev
                else:
                    return False, f"Ungueltige Severity: {sev}. Erlaubt: {', '.join(self.SEVERITIES)}"
                i += 2
            else:
                i += 1
        
        # Pruefen ob mindestens eine Option angegeben
        if all(v is None for v in [title, solution, category, severity]):
            return False, "Mindestens eine Option angeben: --title, --solution, --category, --severity"
        
        conn = sqlite3.connect(self.db_path)
        try:
            # Pruefen ob Lesson existiert
            row = conn.execute("SELECT id, title FROM memory_lessons WHERE id = ?", (lesson_id,)).fetchone()
            if not row:
                return False, f"Lesson #{lesson_id} nicht gefunden"
            
            # Updates sammeln
            updates = []
            params = []
            changes = []
            
            if title is not None:
                updates.append("title = ?")
                params.append(title)
                changes.append(f"Titel -> {title[:30]}...")
            
            if solution is not None:
                updates.append("solution = ?")
                params.append(solution)
                changes.append(f"Solution aktualisiert ({len(solution)} Zeichen)")
            
            if category is not None:
                updates.append("category = ?")
                params.append(category)
                changes.append(f"Kategorie -> {category}")
            
            if severity is not None:
                updates.append("severity = ?")
                params.append(severity)
                changes.append(f"Severity -> {severity}")
            
            # updated_at setzen
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            
            # Update ausfuehren
            params.append(lesson_id)
            conn.execute(f"UPDATE memory_lessons SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            
            return True, f"[OK] Lesson #{lesson_id} bearbeitet: {', '.join(changes)}"
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()
    
    def _deactivate(self, args: list) -> tuple:
        """Lesson deaktivieren (is_active = 0)"""
        if not args:
            return False, "Usage: bach lesson deactivate ID [--reason 'Grund']"
        
        try:
            lesson_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige ID: {args[0]}"
        
        # Optional: Grund parsen
        reason = None
        if len(args) > 2 and args[1] in ['--reason', '-r']:
            reason = args[2]
        
        conn = sqlite3.connect(self.db_path)
        try:
            # Pruefen ob Lesson existiert und aktiv ist
            row = conn.execute("SELECT id, title, is_active FROM memory_lessons WHERE id = ?", (lesson_id,)).fetchone()
            if not row:
                return False, f"Lesson #{lesson_id} nicht gefunden"
            
            if row[2] == 0:
                return False, f"Lesson #{lesson_id} ist bereits deaktiviert"
            
            # Deaktivieren
            conn.execute("""
                UPDATE memory_lessons 
                SET is_active = 0, updated_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), lesson_id))
            conn.commit()
            
            msg = f"[OK] Lesson #{lesson_id} deaktiviert: {row[1][:40]}"
            if reason:
                msg += f"\n    Grund: {reason}"
            return True, msg
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()
    
    def _add_usage(self) -> str:
        return """Usage: bach lesson add "Titel: Loesung"

Optionen:
  --category bug|workflow|tool|integration|performance|general
  --severity low|medium|high|critical
  --problem "Problembeschreibung"

Beispiele:
  bach lesson add "DB-Pfad: Immer data/bach.db verwenden"
  bach lesson add "Handler-Bug: base_path nicht root" --category bug
  bach lesson add "Titel" --problem "Was ging schief" --category workflow"""
    
    def _list(self, category: str = None) -> tuple:
        conn = sqlite3.connect(self.db_path)
        try:
            if category:
                rows = conn.execute("""
                    SELECT id, category, severity, title, created_at 
                    FROM memory_lessons 
                    WHERE category = ? AND is_active = 1
                    ORDER BY created_at DESC
                """, (category,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, category, severity, title, created_at 
                    FROM memory_lessons 
                    WHERE is_active = 1
                    ORDER BY created_at DESC
                """).fetchall()
            
            if not rows:
                return True, "Keine Lessons gefunden."
            
            results = ["LESSONS LEARNED", "=" * 50, ""]
            for id, cat, sev, title, created in rows:
                date = created[:10] if created else "?"
                results.append(f"  #{id} [{cat}] {title[:40]}")
            
            results.append("")
            results.append(f"Gesamt: {len(rows)} Lessons")
            results.append("Details: --lesson show ID")
            
            return True, "\n".join(results)
        finally:
            conn.close()
    
    def _last(self, n: int) -> tuple:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("""
                SELECT id, category, title, solution, created_at 
                FROM memory_lessons 
                WHERE is_active = 1
                ORDER BY created_at DESC
                LIMIT ?
            """, (n,)).fetchall()
            
            if not rows:
                return True, "Keine Lessons vorhanden."
            
            results = [f"LETZTE {len(rows)} LESSONS", "=" * 50]
            for id, cat, title, solution, created in rows:
                date = created[:10] if created else "?"
                results.append("")
                results.append(f"#{id} [{cat}] {title}")
                results.append(f"   {solution[:60]}...")
            
            return True, "\n".join(results)
        finally:
            conn.close()
    
    def _search(self, keyword: str) -> tuple:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("""
                SELECT id, category, title, solution 
                FROM memory_lessons 
                WHERE is_active = 1 
                  AND (title LIKE ? OR solution LIKE ? OR problem LIKE ?)
                ORDER BY created_at DESC
            """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")).fetchall()
            
            if not rows:
                return True, f"Keine Treffer fuer: {keyword}"
            
            results = [f"SUCHE: {keyword}", "=" * 50]
            for id, cat, title, solution in rows:
                results.append(f"  #{id} [{cat}] {title[:40]}")
            
            results.append(f"\n{len(rows)} Treffer")
            return True, "\n".join(results)
        finally:
            conn.close()
    
    def _show(self, lesson_id: str) -> tuple:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("""
                SELECT id, category, severity, title, problem, solution, 
                       related_tools, created_at, times_shown
                FROM memory_lessons WHERE id = ?
            """, (lesson_id,)).fetchone()
            
            if not row:
                return False, f"Lesson #{lesson_id} nicht gefunden"
            
            id, cat, sev, title, problem, solution, tools, created, shown = row
            
            results = [
                f"LESSON #{id}",
                "=" * 50,
                f"Titel:     {title}",
                f"Kategorie: {cat}",
                f"Severity:  {sev}",
                f"Erstellt:  {created[:16] if created else '?'}",
                f"Angezeigt: {shown}x",
                ""
            ]
            
            if problem:
                results.append(f"Problem:\n  {problem}")
                results.append("")
            
            results.append(f"Loesung:\n  {solution}")
            
            if tools:
                results.append(f"\nTools: {tools}")
            
            # times_shown erhoehen
            conn.execute("UPDATE memory_lessons SET times_shown = times_shown + 1, last_shown = ? WHERE id = ?",
                        (datetime.now().isoformat(), lesson_id))
            conn.commit()
            
            return True, "\n".join(results)
        finally:
            conn.close()
