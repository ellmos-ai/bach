# SPDX-License-Identifier: MIT
"""
Memory Handler - DB-basiertes Memory-Management
===============================================

Alles in bach.db, kein Dateisystem mehr.

Tabellen:
- memory_working:  Schnelle Notizen (scratchpad, context, note)
- memory_facts:    Persistente Fakten (user, project, system)
- memory_lessons:  Lessons Learned (eigener Handler)
- memory_sessions: Session-Tracking (automatisch)
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from .base import BaseHandler
from .lang import t
from core.provenance import (
    classify_people_scope,
    classify_privacy,
    format_timestamp,
    truncate_text,
)


class MemoryHandler(BaseHandler):
    """Handler fuer --memory Operationen - DB-basiert"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "memory"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "status": "Memory-Uebersicht (Counts)",
            "write": "Notiz schreiben (in memory_working)",
            "read": "Letzte Notizen lesen",
            "fact": "Fakt speichern (key:value [--conf=0.8] [--source=X])",
            "facts": "Alle Fakten anzeigen [category] [--min-conf=0.5]",
            "certain": "Nur hochkonfidente Fakten (>=0.8)",
            "uncertain": "Unsichere Fakten (<0.5) zur Pruefung",
            "confidence": "Konfidenz aktualisieren (key neue_konfidenz)",
            "search": "Memory durchsuchen",
            "context": "Kontext fuer Claude generieren",
            "provenance": "Herkunft, Evidenzart, Personenbezug und Privacy-Hinweise zeigen",
            "clear": "Working Memory leeren",
            "session": "Session-Bericht speichern (Shutdown)",
            "sessions": "Letzte Sessions anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.db_path.exists():
            return False, f"Datenbank nicht gefunden: {self.db_path}"
        
        if operation == "status" or not operation:
            return self._status()
        elif operation == "write":
            if not args:
                return False, "Usage: --memory write \"Notiz\""
            return self._write(" ".join(args), dry_run)
        elif operation == "read":
            n = int(args[0]) if args else 10
            return self._read(n)
        elif operation == "fact":
            if not args:
                return False, "Usage: --memory fact \"key:value\""
            return self._add_fact(" ".join(args), dry_run)
        elif operation == "facts":
            # Parse args: [category] [--min-conf=X]
            category = None
            min_conf = 0.0
            for arg in args:
                if arg.startswith("--min-conf="):
                    try:
                        min_conf = float(arg.split("=")[1])
                    except ValueError:
                        pass
                elif not arg.startswith("--"):
                    category = arg
            return self._list_facts(category, min_conf)
        elif operation == "certain":
            return self._list_facts(None, min_confidence=0.8)
        elif operation == "uncertain":
            return self._list_uncertain_facts()
        elif operation == "confidence":
            if len(args) < 2:
                return False, "Usage: --memory confidence \"category.key\" 0.9"
            key_part = args[0]
            try:
                new_conf = float(args[1])
            except ValueError:
                return False, "Konfidenz muss eine Zahl sein (0.0-1.0)"
            return self._update_confidence(key_part, new_conf, dry_run)
        elif operation == "search":
            if not args:
                return False, "Usage: --memory search \"keyword1 keyword2 ...\""
            return self._search(" ".join(args))
        elif operation == "context":
            return self._generate_context()
        elif operation == "provenance":
            return self._provenance(args)
        elif operation == "clear":
            return self._clear_working(dry_run)
        elif operation == "session":
            if not args:
                return False, "Usage: --memory session \"Zusammenfassung der Session\""
            return self._save_session(" ".join(args), dry_run)
        elif operation == "sessions":
            n = int(args[0]) if args else 5
            return self._list_sessions(n)
        else:
            return self._status()
    
    def _get_conn(self):
        return sqlite3.connect(self.db_path)
    
    def _status(self) -> tuple:
        conn = self._get_conn()
        try:
            working = conn.execute("SELECT COUNT(*) FROM memory_working WHERE is_active=1").fetchone()[0]
            facts = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
            lessons = conn.execute("SELECT COUNT(*) FROM memory_lessons WHERE is_active=1").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM memory_sessions").fetchone()[0]

            # Konfidenz-Statistik
            conf_high = conn.execute("SELECT COUNT(*) FROM memory_facts WHERE confidence >= 0.8").fetchone()[0]
            conf_mid = conn.execute("SELECT COUNT(*) FROM memory_facts WHERE confidence >= 0.5 AND confidence < 0.8").fetchone()[0]
            conf_low = conn.execute("SELECT COUNT(*) FROM memory_facts WHERE confidence < 0.5 AND confidence IS NOT NULL").fetchone()[0]

            results = [
                "MEMORY STATUS (DB-basiert)",
                "=" * 60,
                "",
                f"  Working Memory:  {working} aktive Eintraege",
                f"  Facts:           {facts} Fakten",
                f"  Lessons:         {lessons} Lessons",
                f"  Sessions:        {sessions} Sessions",
                "",
                "Fakten nach Konfidenz:",
                f"  [*****] Sicher (>=0.8):    {conf_high}",
                f"  [***--] Mittel (0.5-0.8):  {conf_mid}",
                f"  [*----] Unsicher (<0.5):   {conf_low}",
                "",
                "Befehle:",
                "  --memory write \"...\"              Notiz speichern",
                "  --memory read [n]                 Letzte n lesen",
                "  --memory fact k:v [--conf=X]      Fakt mit Konfidenz",
                "  --memory facts [cat] [--min-conf] Fakten anzeigen",
                "  --memory certain                  Nur sichere Fakten",
                "  --memory uncertain                Unsichere zur Pruefung",
                "  --memory confidence key 0.9      Konfidenz aktualisieren",
                "  --memory search \"...\"            Durchsuchen",
                "  --memory context                  Kontext generieren"
            ]
            return True, "\n".join(results)
        finally:
            conn.close()
    
    def _write(self, text: str, dry_run: bool) -> tuple:
        """Notiz in memory_working speichern."""
        if dry_run:
            return True, f"[DRY-RUN] Wuerde speichern: {text[:50]}..."
        
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO memory_working (type, content, created_at, updated_at)
                VALUES ('note', ?, ?, ?)
            """, (text, now, now))
            conn.commit()

            # Hook: after_memory_write
            try:
                from core.hooks import hooks
                hooks.emit('after_memory_write', {
                    'type': 'note', 'content': text[:100]
                })
            except Exception:
                pass

            return True, f"[OK] Notiz gespeichert."
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()
    
    def _read(self, n: int = 10) -> tuple:
        """Letzte n Notizen aus memory_working lesen."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT id, type, content, created_at 
                FROM memory_working 
                WHERE is_active = 1
                ORDER BY created_at DESC
                LIMIT ?
            """, (n,)).fetchall()
            
            if not rows:
                return True, "Keine Notizen im Working Memory."
            
            results = [f"WORKING MEMORY (letzte {len(rows)})", "=" * 50]
            for id, type, content, created in rows:
                time = created[11:16] if created else "?"
                results.append(f"[{time}] ({type}) {content[:60]}{'...' if len(content) > 60 else ''}")
            
            return True, "\n".join(results)
        finally:
            conn.close()
    
    def _add_fact(self, text: str, dry_run: bool) -> tuple:
        """
        Fakt in memory_facts speichern.

        Format: category.key:value [--conf=0.8] [--source=explicit]

        Beispiele:
            user.name:Max
            user.name:Max --conf=1.0 --source=explicit
            project.deadline:2026-03-01 --conf=0.7 --source=mentioned
        """
        # Parse optionale Flags
        confidence = 1.0  # Default: sicher
        source = "cli"    # Default: CLI-Eingabe

        # Flags extrahieren
        parts_raw = text.split()
        text_parts = []
        for part in parts_raw:
            if part.startswith("--conf="):
                try:
                    confidence = float(part.split("=")[1])
                    confidence = max(0.0, min(1.0, confidence))  # Clamp 0-1
                except ValueError:
                    pass
            elif part.startswith("--source="):
                source = part.split("=")[1]
            else:
                text_parts.append(part)

        text = " ".join(text_parts)

        if ":" not in text:
            return False, "Format: key:value [--conf=0.8] [--source=explicit]"

        parts = text.split(":", 1)
        key_part = parts[0].strip()
        value = parts[1].strip()

        # Category.key oder nur key
        if "." in key_part:
            cat_key = key_part.split(".", 1)
            category = cat_key[0]
            key = cat_key[1]
        else:
            category = "project"
            key = key_part

        valid_cats = ['user', 'project', 'system', 'domain']
        if category not in valid_cats:
            category = "project"

        # Konfidenz-Visualisierung
        conf_bar = self._confidence_bar(confidence)

        if dry_run:
            return True, f"[DRY-RUN] Fakt: [{category}] {key} = {value} {conf_bar} (source: {source})"

        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            # UPSERT mit confidence und source
            conn.execute("""
                INSERT INTO memory_facts (category, key, value, confidence, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """, (category, key, value, confidence, source, now, now))
            conn.commit()
            return True, f"[OK] Fakt gespeichert: [{category}] {key} = {value} {conf_bar} (source: {source})"
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()

    def _confidence_bar(self, confidence: float) -> str:
        """Erzeugt visuelle Konfidenz-Anzeige."""
        filled = int(confidence * 5)
        empty = 5 - filled
        return f"[{'*' * filled}{'-' * empty}] {confidence:.1f}"
    
    def _list_facts(self, category: str = None, min_confidence: float = 0.0) -> tuple:
        """Alle Fakten anzeigen mit Konfidenz und Quelle."""
        conn = self._get_conn()
        try:
            if category:
                rows = conn.execute("""
                    SELECT category, key, value, confidence, source, updated_at
                    FROM memory_facts
                    WHERE category = ? AND (confidence >= ? OR confidence IS NULL)
                    ORDER BY confidence DESC, key
                """, (category, min_confidence)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT category, key, value, confidence, source, updated_at
                    FROM memory_facts
                    WHERE confidence >= ? OR confidence IS NULL
                    ORDER BY category, confidence DESC, key
                """, (min_confidence,)).fetchall()

            if not rows:
                if min_confidence > 0:
                    return True, f"Keine Fakten mit Konfidenz >= {min_confidence}"
                return True, "Keine Fakten gespeichert."

            title = "MEMORY FACTS"
            if min_confidence > 0:
                title += f" (Konfidenz >= {min_confidence})"
            results = [title, "=" * 60]

            current_cat = None
            for cat, key, value, conf, source, updated in rows:
                if cat != current_cat:
                    results.append(f"\n[{cat.upper()}]")
                    current_cat = cat

                # Konfidenz-Anzeige
                conf_val = conf if conf is not None else 1.0
                conf_bar = self._confidence_bar(conf_val)

                # Source-Anzeige (gekuerzt)
                src_display = f"({source})" if source else ""

                # Wert kuerzen
                val_display = value[:40] + "..." if len(value) > 40 else value

                results.append(f"  {key}: {val_display}")
                results.append(f"       {conf_bar} {src_display}")

            results.append(f"\nGesamt: {len(rows)} Fakten")
            return True, "\n".join(results)
        finally:
            conn.close()

    def _list_uncertain_facts(self) -> tuple:
        """Zeigt unsichere Fakten (<0.5) zur Ueberpruefung."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT category, key, value, confidence, source, updated_at
                FROM memory_facts
                WHERE confidence < 0.5 AND confidence IS NOT NULL
                ORDER BY confidence ASC, updated_at DESC
            """).fetchall()

            if not rows:
                return True, "Keine unsicheren Fakten (alle Konfidenz >= 0.5)"

            results = ["UNSICHERE FAKTEN (Konfidenz < 0.5)", "=" * 60,
                       "Diese Fakten sollten verifiziert werden:", ""]

            for cat, key, value, conf, source, updated in rows:
                conf_bar = self._confidence_bar(conf)
                results.append(f"  [{cat}] {key}: {value[:40]}")
                results.append(f"       {conf_bar} (source: {source or 'unknown'})")
                results.append("")

            results.append(f"Gesamt: {len(rows)} unsichere Fakten")
            results.append("\nTipp: --memory confidence \"cat.key\" 0.9 zum Aktualisieren")
            return True, "\n".join(results)
        finally:
            conn.close()

    def _update_confidence(self, key_part: str, new_confidence: float, dry_run: bool) -> tuple:
        """Aktualisiert die Konfidenz eines Fakts."""
        # Clamp confidence
        new_confidence = max(0.0, min(1.0, new_confidence))

        # Category.key parsen
        if "." in key_part:
            cat_key = key_part.split(".", 1)
            category = cat_key[0]
            key = cat_key[1]
        else:
            category = "project"
            key = key_part

        if dry_run:
            return True, f"[DRY-RUN] Wuerde Konfidenz setzen: [{category}] {key} -> {new_confidence}"

        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute("""
                UPDATE memory_facts
                SET confidence = ?, updated_at = ?
                WHERE category = ? AND key = ?
            """, (new_confidence, now, category, key))
            conn.commit()

            if cursor.rowcount == 0:
                return False, f"Fakt nicht gefunden: [{category}] {key}"

            conf_bar = self._confidence_bar(new_confidence)
            return True, f"[OK] Konfidenz aktualisiert: [{category}] {key} {conf_bar}"
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()
    
    def _search(self, query: str) -> tuple:
        """Durchsucht alle Memory-Tabellen mit Relevanz-Scoring (Assoziativ)."""
        conn = self._get_conn()
        results = [f"ASSOZIATIVE SUCHE: {query}", "=" * 50]
        
        keywords = query.lower().split()
        if not keywords:
            return False, "Leere Suchanfrage."
            
        try:
            # 1. Alles abrufen (roh)
            working = conn.execute("SELECT content FROM memory_working WHERE is_active = 1").fetchall()
            facts = conn.execute("SELECT key || ': ' || value FROM memory_facts").fetchall()
            lessons = conn.execute("SELECT title || ': ' || solution FROM memory_lessons WHERE is_active = 1").fetchall()
            
            # 2. Scoring berechnen
            scored_results = []
            
            for (content,) in working:
                score = self._calculate_relevance(content, keywords)
                if score > 0:
                    scored_results.append((score, "working", content))
                    
            for (content,) in facts:
                score = self._calculate_relevance(content, keywords)
                if score > 0:
                    scored_results.append((score, "fact", content))
            
            for (content,) in lessons:
                score = self._calculate_relevance(content, keywords)
                if score > 0:
                    scored_results.append((score, "lesson", content))
            
            # 3. Sortieren (Hoher Score zuerst)
            scored_results.sort(key=lambda x: x[0], reverse=True)
            
            # 4. Ausgabe formatieren (Top 15)
            if not scored_results:
                return True, f"Keine Treffer fuer: {query}"
                
            for score, src, content in scored_results[:15]:
                # Visualisiere Score
                relevance = "*" * score
                results.append(f"  [{src}] {relevance} {content[:80]}...")
            
            results.append(f"\n{len(scored_results)} Treffer")
            return True, "\n".join(results)
        finally:
            conn.close()

    def _calculate_relevance(self, text: str, keywords: list) -> int:
        """Berechnet Overlap-Score."""
        score = 0
        text_lower = text.lower()
        for kw in keywords:
            if kw in text_lower:
                score += 1
        return score
    
    def _generate_context(self) -> tuple:
        """Generiert kompakten Kontext fuer Claude (priorisiert hochkonfidente Fakten)."""
        conn = self._get_conn()
        try:
            context_parts = []

            # Aktive Working Notes (letzte 5)
            working = conn.execute("""
                SELECT content FROM memory_working
                WHERE is_active = 1 ORDER BY created_at DESC LIMIT 5
            """).fetchall()
            if working:
                context_parts.append("## Aktuelle Notizen")
                for (content,) in working:
                    context_parts.append(f"- {content[:100]}")

            # Hochkonfidente Fakten zuerst (>= 0.7)
            facts_certain = conn.execute("""
                SELECT category, key, value, confidence FROM memory_facts
                WHERE confidence >= 0.7 OR confidence IS NULL
                ORDER BY confidence DESC, updated_at DESC LIMIT 8
            """).fetchall()
            if facts_certain:
                context_parts.append("\n## Sichere Fakten")
                for cat, key, value, conf in facts_certain:
                    conf_indicator = f"[{conf:.1f}]" if conf else "[1.0]"
                    context_parts.append(f"- {key}: {value[:50]} {conf_indicator}")

            # Unsichere Fakten separat markieren (< 0.7)
            facts_uncertain = conn.execute("""
                SELECT category, key, value, confidence FROM memory_facts
                WHERE confidence < 0.7 AND confidence IS NOT NULL
                ORDER BY confidence DESC LIMIT 5
            """).fetchall()
            if facts_uncertain:
                context_parts.append("\n## Unsichere Fakten (zu verifizieren)")
                for cat, key, value, conf in facts_uncertain:
                    context_parts.append(f"- {key}: {value[:50]} [{conf:.1f}]")

            # Letzte Lessons (nur Titel)
            lessons = conn.execute("""
                SELECT title FROM memory_lessons
                WHERE is_active = 1 ORDER BY created_at DESC LIMIT 5
            """).fetchall()
            if lessons:
                context_parts.append("\n## Letzte Lessons")
                for (title,) in lessons:
                    context_parts.append(f"- {title}")

            if not context_parts:
                return True, "Kein Kontext verfuegbar."

            return True, "\n".join(context_parts)
        finally:
            conn.close()

    def _parse_provenance_args(self, args: list) -> tuple[str, int]:
        """Parst scope/limit fuer provenance."""
        scope = "all"
        limit = 5
        valid_scopes = {"all", "working", "facts", "lessons", "sessions"}

        for arg in args:
            lowered = str(arg).lower()
            if lowered in valid_scopes:
                scope = lowered
            else:
                try:
                    limit = max(1, min(int(lowered), 20))
                except ValueError:
                    continue
        return scope, limit

    def _memory_evidence(self, scope: str, row: sqlite3.Row) -> str:
        """Leitet eine kurze Evidenz-Kategorie ab."""
        if scope == "working":
            return "Working Note"
        if scope == "lessons":
            return "Lesson Learned"
        if scope == "sessions":
            return "Session Summary"

        source = (row["source"] or "").lower()
        confidence = row["confidence"] if row["confidence"] is not None else 1.0

        if source.startswith(("user", "explicit")):
            return "Expliziter Fakt"
        if confidence < 0.8 or source.startswith(("inferred", "observed")):
            return "Abgeleiteter Fakt"
        if row["category"] == "system":
            return "System-Fakt"
        return "Persistenter Fakt"

    def _format_memory_provenance_entry(
        self,
        *,
        label: str,
        evidence: str,
        source: str,
        preview: str,
        timestamp: str,
        people_scope: str,
        privacy: str,
        scope_reason: str,
        privacy_hint: str,
    ) -> list[str]:
        return [
            f"  {label}",
            f"    Evidenz: {evidence} | Quelle: {source or '-'}",
            f"    Personenbezug: {people_scope} | Privacy: {privacy}",
            f"    Zeit: {format_timestamp(timestamp)}",
            f"    Inhalt: {truncate_text(preview)}",
            f"    Hinweis: {scope_reason} {privacy_hint}",
            "",
        ]

    def _provenance(self, args: list) -> tuple:
        """Zeigt heuristische Provenance-Infos fuer Memory-Eintraege."""
        scope, limit = self._parse_provenance_args(args)
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row

        results = [
            "MEMORY PROVENANCE (heuristisch)",
            "=" * 60,
            "",
            "Hinweis: Personenbezug und Privacy sind Review-Hilfen, keine harte Policy.",
        ]

        try:
            sections = 0

            if scope in {"all", "working"}:
                rows = conn.execute(
                    """
                    SELECT id, type, content, created_at, updated_at
                    FROM memory_working
                    WHERE is_active = 1
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                if rows:
                    results.extend(["", "[WORKING]"])
                    for row in rows:
                        people_scope, scope_reason = classify_people_scope(
                            text=row["content"],
                            source="working_memory",
                        )
                        privacy, privacy_hint = classify_privacy(
                            text=row["content"],
                            source="working_memory",
                            people_scope=people_scope,
                        )
                        results.extend(
                            self._format_memory_provenance_entry(
                                label=f"#{row['id']} ({row['type']})",
                                evidence=self._memory_evidence("working", row),
                                source="working_memory",
                                preview=row["content"],
                                timestamp=row["updated_at"] or row["created_at"],
                                people_scope=people_scope,
                                privacy=privacy,
                                scope_reason=scope_reason,
                                privacy_hint=privacy_hint,
                            )
                        )
                    sections += 1

            if scope in {"all", "facts"}:
                rows = conn.execute(
                    """
                    SELECT id, category, key, value, confidence, source, created_at, updated_at
                    FROM memory_facts
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                if rows:
                    results.extend(["", "[FACTS]"])
                    for row in rows:
                        people_scope, scope_reason = classify_people_scope(
                            text=row["value"],
                            category=row["category"],
                            source=row["source"] or "",
                        )
                        privacy, privacy_hint = classify_privacy(
                            text=row["value"],
                            category=row["category"],
                            source=row["source"] or "",
                            people_scope=people_scope,
                        )
                        conf = row["confidence"]
                        conf_text = "" if conf is None else f" | Konfidenz: {conf:.1f}"
                        results.extend(
                            self._format_memory_provenance_entry(
                                label=f"#{row['id']} [{row['category']}] {row['key']}{conf_text}",
                                evidence=self._memory_evidence("facts", row),
                                source=row["source"] or "unknown",
                                preview=row["value"],
                                timestamp=row["updated_at"] or row["created_at"],
                                people_scope=people_scope,
                                privacy=privacy,
                                scope_reason=scope_reason,
                                privacy_hint=privacy_hint,
                            )
                        )
                    sections += 1

            if scope in {"all", "lessons"}:
                rows = conn.execute(
                    """
                    SELECT id, category, severity, title, problem, solution, related_tools, related_files, created_at
                    FROM memory_lessons
                    WHERE is_active = 1
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                if rows:
                    results.extend(["", "[LESSONS]"])
                    for row in rows:
                        source = row["related_files"] or row["related_tools"] or "lesson_db"
                        preview = row["solution"] or row["problem"] or row["title"]
                        people_scope, scope_reason = classify_people_scope(
                            text=" ".join(filter(None, [row["title"], row["problem"], row["solution"]])),
                            category=row["category"],
                            source=source,
                        )
                        privacy, privacy_hint = classify_privacy(
                            text=preview,
                            category=row["category"],
                            source=source,
                            people_scope=people_scope,
                        )
                        results.extend(
                            self._format_memory_provenance_entry(
                                label=f"#{row['id']} [{row['severity']}] {row['title']}",
                                evidence=self._memory_evidence("lessons", row),
                                source=source,
                                preview=preview,
                                timestamp=row["created_at"],
                                people_scope=people_scope,
                                privacy=privacy,
                                scope_reason=scope_reason,
                                privacy_hint=privacy_hint,
                            )
                        )
                    sections += 1

            if scope in {"all", "sessions"}:
                rows = conn.execute(
                    """
                    SELECT id, session_id, summary, started_at, ended_at, partner_id, tasks_created, tasks_completed
                    FROM memory_sessions
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                if rows:
                    results.extend(["", "[SESSIONS]"])
                    for row in rows:
                        preview = row["summary"] or row["session_id"]
                        people_scope, scope_reason = classify_people_scope(
                            text=preview,
                            source=row["session_id"],
                            partner_id=row["partner_id"] or "",
                        )
                        privacy, privacy_hint = classify_privacy(
                            text=preview,
                            source=row["session_id"],
                            partner_id=row["partner_id"] or "",
                            people_scope=people_scope,
                        )
                        ended = row["ended_at"] or "aktiv"
                        results.extend(
                            self._format_memory_provenance_entry(
                                label=(
                                    f"#{row['id']} {row['session_id']} "
                                    f"(+{row['tasks_created'] or 0} / -{row['tasks_completed'] or 0}, Ende: {format_timestamp(ended)})"
                                ),
                                evidence=self._memory_evidence("sessions", row),
                                source=row["partner_id"] or "unknown",
                                preview=preview,
                                timestamp=row["started_at"],
                                people_scope=people_scope,
                                privacy=privacy,
                                scope_reason=scope_reason,
                                privacy_hint=privacy_hint,
                            )
                        )
                    sections += 1

            if sections == 0:
                return True, "Keine passenden Memory-Einträge für Provenance."

            return True, "\n".join(results).rstrip()
        finally:
            conn.close()
    
    def _clear_working(self, dry_run: bool) -> tuple:
        """Working Memory leeren (soft delete)."""
        if dry_run:
            return True, "[DRY-RUN] Wuerde Working Memory leeren"
        
        conn = self._get_conn()
        try:
            conn.execute("UPDATE memory_working SET is_active = 0")
            conn.commit()
            return True, "[OK] Working Memory geleert."
        finally:
            conn.close()
    
    def _save_session(self, summary: str, dry_run: bool) -> tuple:
        """Session-Bericht in memory_sessions speichern."""
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Session speichern: {summary[:50]}..."
        
        conn = self._get_conn()
        try:
            now = datetime.now()
            session_id = f"session_{now.strftime('%Y%m%d_%H%M%S')}"
            
            # Pruefen ob es eine offene Session gibt
            open_session = conn.execute("""
                SELECT id, session_id FROM memory_sessions 
                WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1
            """).fetchone()
            
            if open_session:
                # Offene Session abschliessen
                conn.execute("""
                    UPDATE memory_sessions 
                    SET ended_at = ?, summary = ?
                    WHERE id = ?
                """, (now.isoformat(), summary, open_session[0]))
                session_id = open_session[1]
                action = "abgeschlossen"
            else:
                # Neue Session mit gleichem Start/End (nachtraeglicher Bericht)
                conn.execute("""
                    INSERT INTO memory_sessions 
                    (session_id, started_at, ended_at, summary, tasks_created, tasks_completed)
                    VALUES (?, ?, ?, ?, 0, 0)
                """, (session_id, now.isoformat(), now.isoformat(), summary))
                action = "erstellt"
            
            conn.commit()
            return True, f"[OK] Session {session_id} {action}"
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()
    
    def _list_sessions(self, n: int = 5) -> tuple:
        """Letzte n Sessions anzeigen."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT session_id, started_at, ended_at, summary, 
                       tasks_created, tasks_completed, continuation_context
                FROM memory_sessions 
                ORDER BY id DESC LIMIT ?
            """, (n,)).fetchall()
            
            if not rows:
                return True, "Keine Sessions gespeichert."
            
            results = [f"LETZTE {len(rows)} SESSIONS", "=" * 60]
            
            for sid, started, ended, summary, created, completed, continuation in rows:
                # Datum formatieren
                date = started[:10] if started else "?"
                time_start = started[11:16] if started and len(started) > 11 else "?"
                time_end = ended[11:16] if ended and len(ended) > 11 else "aktiv"
                
                results.append("")
                results.append(f"[{sid}]")
                results.append(f"  Zeit: {date} {time_start} - {time_end}")
                results.append(f"  Tasks: +{created or 0} erstellt, {completed or 0} erledigt")
                
                if summary:
                    # Erste Zeile der Summary
                    first_line = summary.split('\n')[0][:60]
                    results.append(f"  Summary: {first_line}...")
                
                if continuation:
                    results.append(f"  Naechste: {continuation[:50]}...")
            
            return True, "\n".join(results)
        finally:
            conn.close()
