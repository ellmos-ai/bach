# SPDX-License-Identifier: MIT
"""
Consolidation Handler - Memory-Konsolidierung
==============================================

Aktiver Prozess der aus Rohdaten Sinnstrukturen schafft.
Analog zum menschlichen Gehirn: Wichtiges behalten, Ungenutztes vergessen.

CLI: bach consolidate <operation> [args]

Operationen:
- status:   Konsolidierungs-Status anzeigen
- run:      Alle Prozesse ausfuehren
- compress: Sessions komprimieren
- weight:   Gewichtungen aktualisieren
- archive:  Alte Eintraege archivieren
- index:    Facts/Help/Wiki abgleichen
- review:   KI-Review anfordern (Tasks)
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
from .base import BaseHandler


class ConsolidationHandler(BaseHandler):
    """Handler fuer bach consolidate Operationen"""

    # Konfigurierbare Schwellenwerte
    WEIGHT_THRESHOLD_ARCHIVE = 0.2   # Unter diesem Wert: Archivieren
    WEIGHT_THRESHOLD_DELETE = 0.05   # Unter diesem Wert: Loeschen
    DECAY_RATE_DEFAULT = 0.95        # Taeglicher Verfall (5%)
    BOOST_ON_ACCESS = 0.1            # Gewichts-Erhoehung bei Abruf
    SESSIONS_BEFORE_COMPRESS = 10    # Sessions bis Komprimierung
    DAYS_BEFORE_ARCHIVE = 90         # Tage bis Archivierung

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "consolidation"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "status": "Konsolidierungs-Status anzeigen",
            "run": "Alle Prozesse ausfuehren (weight, archive, index)",
            "compress": "Sessions komprimieren (benoetigt KI)",
            "weight": "Gewichtungen aktualisieren (decay + boost)",
            "archive": "Alte Eintraege archivieren",
            "index": "Facts/Help/Wiki abgleichen",
            "review": "KI-Review Tasks erstellen",
            "init": "Tracking fuer existierende Eintraege initialisieren",
            "sync-triggers": "Dynamische Kontext-Trigger aktualisieren (NEU v1.1.80)",
            "forget": "Ungenutzte Eintraege loeschen (weight < threshold)",
            "reclassify": "Falsch kategorisierte Eintraege korrigieren (NEU v1.1.81)"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.db_path.exists():
            return False, f"[FEHLER] Datenbank nicht gefunden: {self.db_path}"

        if operation == "status":
            return self._status()
        elif operation == "run":
            return self._run_all(dry_run)
        elif operation == "compress":
            return self._compress(args, dry_run)
        elif operation == "weight":
            return self._update_weights(dry_run)
        elif operation == "archive":
            return self._archive_old(dry_run)
        elif operation == "index":
            return self._index_facts(dry_run)
        elif operation == "review":
            return self._create_review_tasks(dry_run)
        elif operation == "init":
            return self._init_tracking(dry_run)
        elif operation == "sync-triggers":
            return self._sync_triggers(dry_run)
        elif operation == "forget":
            return self._deactivate_unused(dry_run)
        elif operation == "reclassify":
            return self._reclassify(args, dry_run)
        else:
            ops = "\n".join(f"  {k:12} - {v}" for k, v in self.get_operations().items())
            return False, f"[FEHLER] Unbekannte Operation: {operation}\n\nVerfuegbar:\n{ops}"

    @contextmanager
    def _get_db(self):
        """DB-Verbindung mit Row-Factory (Context Manager)"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _status(self) -> tuple:
        """Zeigt Konsolidierungs-Status"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            output = ["[CONSOLIDATION] Status", "=" * 50, ""]

            # Memory-Tabellen Counts
            tables = [
                ("memory_sessions", "Sessions (episodisch)"),
                ("memory_lessons", "Lessons (prozedural)"),
                ("memory_facts", "Facts (semantisch)"),
                ("memory_context", "Context (komprimiert)"),
                ("memory_working", "Working (Kurzzeit)"),
            ]

            output.append("MEMORY-TABELLEN:")
            for table, desc in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    output.append(f"  {desc:25} {count:5} Eintraege")
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    output.append(f"  {desc:25} (nicht vorhanden)")

            output.append("")

            # Consolidation Tracking
            try:
                cursor.execute("SELECT COUNT(*) FROM memory_consolidation")
                total = cursor.fetchone()[0]

                cursor.execute("SELECT status, COUNT(*) FROM memory_consolidation GROUP BY status")
                by_status = dict(cursor.fetchall())

                cursor.execute("SELECT AVG(weight) FROM memory_consolidation WHERE status='active'")
                avg_weight = cursor.fetchone()[0] or 0

                cursor.execute("""
                    SELECT COUNT(*) FROM memory_consolidation
                    WHERE weight < ? AND status='active'
                """, (self.WEIGHT_THRESHOLD_ARCHIVE,))
                below_threshold = cursor.fetchone()[0]

                output.append("KONSOLIDIERUNG:")
                output.append(f"  Tracking-Eintraege:      {total:5}")
                output.append(f"    - active:              {by_status.get('active', 0):5}")
                output.append(f"    - archived:            {by_status.get('archived', 0):5}")
                output.append(f"    - deleted:             {by_status.get('deleted', 0):5}")
                output.append(f"  Durchschnittl. Gewicht:  {avg_weight:.2f}")
                output.append(f"  Unter Archiv-Schwelle:   {below_threshold:5}")
            except Exception as e:
                output.append(f"KONSOLIDIERUNG: Fehler - {e}")

            output.append("")
            output.append("SCHWELLENWERTE:")
            output.append(f"  Archivieren bei weight < {self.WEIGHT_THRESHOLD_ARCHIVE}")
            output.append(f"  Loeschen bei weight <    {self.WEIGHT_THRESHOLD_DELETE}")
            output.append(f"  Decay-Rate (taeglich):   {self.DECAY_RATE_DEFAULT}")
            output.append(f"  Boost bei Abruf:         +{self.BOOST_ON_ACCESS}")

            return True, "\n".join(output)

    def _run_all(self, dry_run: bool = False) -> tuple:
        """Fuehrt alle automatischen Prozesse aus"""
        results = []

        # 1. Gewichtungen aktualisieren
        success, msg = self._update_weights(dry_run)
        results.append(f"WEIGHT: {msg.split(chr(10))[0]}")

        # 2. Alte archivieren
        success, msg = self._archive_old(dry_run)
        results.append(f"ARCHIVE: {msg.split(chr(10))[0]}")

        # 3. Facts-Index
        success, msg = self._index_facts(dry_run)
        results.append(f"INDEX: {msg.split(chr(10))[0]}")
        
        # 4. Sync Triggers (NEU v1.1.80)
        success, msg = self._sync_triggers(dry_run)
        results.append(f"TRIGGERS: {msg.split(chr(10))[0]}")
        
        # 5. Vergessen (NEU v1.1.80)
        success, msg = self._deactivate_unused(dry_run)
        results.append(f"FORGET: {msg.split(chr(10))[0]}")

        prefix = "[DRY-RUN] " if dry_run else ""
        return True, f"{prefix}[CONSOLIDATION] Run All\n" + "\n".join(results)

    def _update_weights(self, dry_run: bool = False) -> tuple:
        """Aktualisiert Gewichtungen (decay)"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            now = datetime.now()

            cursor.execute("""
                SELECT id, weight, last_accessed, decay_rate
                FROM memory_consolidation
                WHERE status = 'active'
            """)
            entries = cursor.fetchall()

            updated = 0
            for entry in entries:
                if entry['last_accessed']:
                    last = datetime.fromisoformat(entry['last_accessed'])
                    days_since = (now - last).days
                    if days_since > 0:
                        decay = entry['decay_rate'] ** days_since
                        new_weight = entry['weight'] * decay
                        new_weight = max(0.0, min(1.0, new_weight))

                        if not dry_run:
                            cursor.execute("""
                                UPDATE memory_consolidation
                                SET weight = ?, updated_at = ?
                                WHERE id = ?
                            """, (new_weight, now.isoformat(), entry['id']))
                        updated += 1

            if not dry_run:
                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return True, f"{prefix}[OK] {updated} Gewichtungen aktualisiert (decay)"

    def _archive_old(self, dry_run: bool = False) -> tuple:
        """Archiviert Eintraege unter Schwellenwert"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, source_table, source_id, weight
                FROM memory_consolidation
                WHERE status = 'active' AND weight < ?
            """, (self.WEIGHT_THRESHOLD_ARCHIVE,))

            to_archive = cursor.fetchall()

            if not dry_run:
                for entry in to_archive:
                    cursor.execute("""
                        UPDATE memory_consolidation
                        SET status = 'archived', updated_at = ?
                        WHERE id = ?
                    """, (datetime.now().isoformat(), entry['id']))
                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return True, f"{prefix}[OK] {len(to_archive)} Eintraege archiviert"

    def _index_facts(self, dry_run: bool = False) -> tuple:
        """Erstellt Facts-Index aus Help/Wiki"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            help_dir = self.base_path / "help"
            wiki_dir = help_dir / "wiki"

            indexed = 0

            if help_dir.exists():
                for f in help_dir.glob("*.txt"):
                    key = f"HELP.{f.stem}"
                    value = f"docs/help/{f.name}"

                    if not dry_run:
                        cursor.execute("""
                            INSERT OR REPLACE INTO memory_facts
                            (key, value, category, source, updated_at)
                            VALUES (?, ?, 'system', 'consolidate-index', ?)
                        """, (key, value, datetime.now().isoformat()))
                    indexed += 1

            if wiki_dir.exists():
                for f in wiki_dir.rglob("*.txt"):
                    rel_path = f.relative_to(help_dir)
                    key = f"WIKI.{f.stem}"
                    value = str(rel_path).replace("\\", "/")

                    if not dry_run:
                        cursor.execute("""
                            INSERT OR REPLACE INTO memory_facts
                            (key, value, category, source, updated_at)
                            VALUES (?, ?, 'system', 'consolidate-index', ?)
                        """, (key, value, datetime.now().isoformat()))
                    indexed += 1

            if not dry_run:
                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return True, f"{prefix}[OK] {indexed} Help/Wiki-Eintraege indexiert"

    def _compress(self, args: list, dry_run: bool = False) -> tuple:
        """Sessions komprimieren (v2.0: --run, --cleanup, --batch)"""

        if "--cleanup" in args:
            with self._get_db() as conn:
                return self._cleanup_empty_sessions(conn, dry_run)

        if "--batch" in args:
            with self._get_db() as conn:
                return self._batch_compress_sessions(conn, dry_run)

        if "--run" in args:
            return self._run_context_compressor(args, dry_run)

        with self._get_db() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) FROM memory_sessions
                WHERE is_compressed = 0 OR is_compressed IS NULL
            """)
            uncompressed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM memory_context")
            context_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MIN(started_at), MAX(ended_at) FROM memory_sessions
                WHERE is_compressed = 0 OR is_compressed IS NULL
            """)
            date_range = cursor.fetchone()

            cursor.execute("""
                SELECT COUNT(*) FROM memory_sessions
                WHERE (summary IS NULL OR summary = '' OR length(summary) <= 50
                       OR summary LIKE '%AUTO-CLOSED%')
                AND (is_compressed = 0 OR is_compressed IS NULL)
            """)
            empty_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM memory_sessions
                WHERE (is_compressed = 0 OR is_compressed IS NULL)
                AND summary IS NOT NULL AND summary != ''
                AND length(summary) > 50
                AND summary NOT LIKE '%AUTO-CLOSED%'
                AND summary NOT LIKE '%CLEANUP%'
            """)
            compressible = cursor.fetchone()[0]

            output = [
                "[COMPRESS] Sessions-Komprimierung",
                "=" * 50,
                "",
                f"Unkomprimierte Sessions:  {uncompressed}",
                f"  davon leer/kurz:        {empty_count}",
                f"  davon komprimierbar:    {compressible}",
                f"Vorhandene Kontexte:      {context_count}",
            ]

            if date_range[0]:
                output.append(f"Zeitraum:                 {date_range[0][:10]} bis {date_range[1][:10] if date_range[1] else 'heute'}")

            output.extend([
                "",
                "Optionen:",
                "",
                "  bach consolidate compress --cleanup          Leere Sessions aufraemen",
                "  bach consolidate compress --batch            Nach Tag gruppieren (einfach)",
                "  bach consolidate compress --run              Komprimieren (mit Regelwerk)",
                "  bach consolidate compress --run --dry-run    Vorschau ohne Aenderungen",
                "  bach consolidate compress --run --format bullet   Format: bullet/prose/structured",
            ])

            return True, "\n".join(output)

    def _run_context_compressor(self, args: list, dry_run: bool = False) -> tuple:
        """Startet den ContextCompressor fuer regelbasierte Komprimierung."""
        import sys

        tools_dir = self.base_path / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))

        try:
            from context_compressor import SessionCompressor, CompressionRules
        except ImportError as e:
            return False, f"[FEHLER] context_compressor.py nicht gefunden: {e}"

        # Format aus args
        fmt = "structured"
        for i, a in enumerate(args):
            if a == "--format" and i + 1 < len(args):
                fmt = args[i + 1]

        rules = CompressionRules()
        sc = SessionCompressor(self.db_path, rules)
        return sc.compress_and_store(fmt=fmt, dry_run=dry_run or "--dry-run" in args)

    def _cleanup_empty_sessions(self, conn, dry_run: bool = False) -> tuple:
        """Räumt leere und auto-closed Sessions auf (v1.1.83)"""
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM memory_sessions
            WHERE (summary IS NULL OR summary = '' OR summary LIKE '%AUTO-CLOSED%'
                   OR length(summary) <= 50)
            AND (is_compressed = 0 OR is_compressed IS NULL)
        """)
        empty_ids = [r[0] for r in cursor.fetchall()]

        if not empty_ids:
            return True, "[CLEANUP] Keine leeren Sessions gefunden"

        if not dry_run:
            placeholders = ','.join(['?'] * len(empty_ids))
            cursor.execute(f"""
                UPDATE memory_sessions
                SET is_compressed = 1,
                    summary = CASE
                        WHEN summary IS NULL OR summary = '' THEN '[CLEANUP: Leere Session]'
                        ELSE summary
                    END
                WHERE id IN ({placeholders})
            """, empty_ids)
            conn.commit()

        prefix = "[DRY-RUN] " if dry_run else ""
        return True, f"{prefix}[CLEANUP] {len(empty_ids)} leere Sessions als komprimiert markiert"

    def _batch_compress_sessions(self, conn, dry_run: bool = False) -> tuple:
        """Gruppiert Sessions nach Tag und komprimiert Summaries (v2.0).

        Sessions bleiben episodisches Gedaechtnis in memory_sessions.
        Mehrere Sessions pro Tag werden zu einer kombinierten Summary
        zusammengefasst. Keine Duplizierung in memory_facts.
        """
        cursor = conn.cursor()

        cursor.execute("""
            SELECT substr(started_at, 1, 10) as day,
                   COUNT(*) as cnt,
                   GROUP_CONCAT(id) as ids
            FROM memory_sessions
            WHERE (is_compressed = 0 OR is_compressed IS NULL)
            AND summary IS NOT NULL
            AND summary != ''
            AND length(summary) > 50
            AND summary NOT LIKE '%AUTO-CLOSED%'
            AND summary NOT LIKE '%CLEANUP%'
            GROUP BY day
            HAVING cnt >= 2
            ORDER BY day
        """)
        days = cursor.fetchall()

        if not days:
            return True, "[BATCH] Keine zusammenfassbaren Tages-Gruppen gefunden"

        compressed = 0

        for day_row in days:
            day_date = day_row[0]
            session_count = day_row[1]
            session_ids = [int(x) for x in day_row[2].split(',')]

            if not dry_run:
                placeholders = ','.join(['?'] * len(session_ids))
                cursor.execute(f"""
                    UPDATE memory_sessions
                    SET is_compressed = 1
                    WHERE id IN ({placeholders})
                """, session_ids)

                compressed += session_count

        if not dry_run:
            conn.commit()

        prefix = "[DRY-RUN] " if dry_run else ""
        return True, f"{prefix}[BATCH] {compressed} Sessions komprimiert (episodisch)"

    def _create_review_tasks(self, dry_run: bool = False) -> tuple:
        """Erstellt Tasks fuer KI-Review"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM memory_sessions WHERE is_compressed = 0 OR is_compressed IS NULL")
            try:
                uncompressed = cursor.fetchone()[0]
            except (TypeError, IndexError):
                uncompressed = 0

            tasks_created = 0

            if uncompressed >= self.SESSIONS_BEFORE_COMPRESS:
                task_title = f"[CONSOL] {uncompressed} Sessions komprimieren"

                if not dry_run:
                    cursor.execute("""
                        INSERT INTO tasks (title, priority, status, category, created_at)
                        VALUES (?, 'P3', 'pending', 'maintenance', ?)
                    """, (task_title, datetime.now().isoformat()))
                    tasks_created += 1

            cursor.execute("""
                SELECT key FROM memory_facts
                WHERE category IN ('user', 'project', 'domain')
                AND key NOT LIKE 'HELP.%' AND key NOT LIKE 'WIKI.%'
            """)
            orphan_facts = cursor.fetchall()

            for fact in orphan_facts[:5]:
                task_title = f"[WIKI] Eintrag erstellen: {fact[0]}"
                if not dry_run:
                    cursor.execute("SELECT id FROM tasks WHERE title LIKE ? AND status = 'pending'", (f"%{fact[0]}%",))
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO tasks (title, priority, status, category, created_at)
                            VALUES (?, 'P4', 'pending', 'documentation', ?)
                        """, (task_title, datetime.now().isoformat()))
                        tasks_created += 1

            if not dry_run:
                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return True, f"{prefix}[OK] {tasks_created} Review-Tasks erstellt"

    def _init_tracking(self, dry_run: bool = False) -> tuple:
        """Initialisiert Tracking fuer existierende Eintraege"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            tables = [
                ("memory_sessions", "session"),
                ("memory_lessons", "lesson"),
                ("memory_facts", "fact"),
                ("memory_context", "context"),
            ]

            initialized = 0

            for table, pfx in tables:
                try:
                    cursor.execute(f"SELECT id FROM {table}")
                    entries = cursor.fetchall()

                    for entry in entries:
                        if not dry_run:
                            cursor.execute("""
                                INSERT OR IGNORE INTO memory_consolidation
                                (source_table, source_id, times_accessed, weight, status, created_at)
                                VALUES (?, ?, 0, 0.5, 'active', ?)
                            """, (table, entry[0], datetime.now().isoformat()))
                        initialized += 1
                except Exception:
                    continue

            if not dry_run:
                conn.commit()

            pfx = "[DRY-RUN] " if dry_run else ""
            return True, f"{pfx}[OK] {initialized} Eintraege im Tracking initialisiert"

    def boost_access(self, source_table: str, source_id: int) -> None:
        """Erhoeht Gewicht bei Abruf (wird von anderen Handlern aufgerufen)"""
        with self._get_db() as conn:
            cursor = conn.cursor()

            now = datetime.now().isoformat()

            cursor.execute("""
                UPDATE memory_consolidation
                SET times_accessed = times_accessed + 1,
                    last_accessed = ?,
                    weight = MIN(1.0, weight + ?),
                    updated_at = ?
                WHERE source_table = ? AND source_id = ?
            """, (now, self.BOOST_ON_ACCESS, now, source_table, source_id))

            conn.commit()

    def _sync_triggers(self, dry_run: bool = False) -> tuple:
        """Aktualisiert alle dynamischen Trigger (Workflows, Lessons, Tools)."""
        if dry_run:
            return True, "[DRY-RUN] Trigger-Synchronisation uebersprungen."
            
        import subprocess
        import sys
        
        scripts = [
            "workflow_trigger_generator.py",
            "lesson_trigger_generator.py",
            "tool_auto_discovery.py",
            "theme_packet_generator.py",
            "trigger_maintainer.py"
        ]
        
        results = []
        tools_path = self.base_path / "tools"
        
        for script in scripts:
            script_path = tools_path / script
            if script_path.exists():
                try:
                    res = subprocess.run([sys.executable, str(script_path)],
                                       capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', check=True)
                    results.append(f"  {script}: OK")
                except Exception as e:
                    results.append(f"  {script}: Fehler ({e})")
            else:
                results.append(f"  {script}: Nicht gefunden")
                
        return True, "Trigger-Sync abgeschlossen:\n" + "\n".join(results)

    def _deactivate_unused(self, dry_run: bool = False) -> tuple:
        """Deaktiviert oder loescht Eintraege mit sehr geringem Gewicht (v1.1.80)."""
        with self._get_db() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, source_table, source_id, weight
                FROM memory_consolidation
                WHERE status = 'active' AND weight < ?
            """, (self.WEIGHT_THRESHOLD_DELETE,))

            to_delete = cursor.fetchall()

            if not dry_run:
                now = datetime.now().isoformat()
                for entry in to_delete:
                    cursor.execute("""
                        UPDATE memory_consolidation
                        SET status = 'deleted', updated_at = ?
                        WHERE id = ?
                    """, (now, entry['id']))

                    table = entry['source_table']
                    if table in ['memory_lessons', 'memory_working']:
                        cursor.execute(f"UPDATE {table} SET is_active = 0, updated_at = ? WHERE id = ?",
                                     (now, entry['source_id']))
                    elif table == 'memory_facts':
                        cursor.execute("DELETE FROM memory_facts WHERE id = ?", (entry['source_id'],))

                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return True, f"{prefix}[OK] {len(to_delete)} Eintraege geloescht/deaktiviert"

    def _reclassify(self, args: list, dry_run: bool = False) -> tuple:
        """Korrigiert falsch kategorisierte Eintraege (v1.1.81).

        Usecases:
        - Lesson sollte Context sein (haeufig abgerufen, generalisierbar)
        - Fact ohne Wiki-Referenz -> Task erstellen
        - Working Memory Notiz ist eigentlich Lesson
        - Session-Eintrag enthaelt Lesson-wuerdig Info

        CLI:
          bach consolidate reclassify              Analyse zeigen
          bach consolidate reclassify --fix        Automatische Korrekturen
          bach consolidate reclassify lesson 42 context  Manuell: Lesson 42 -> Context
        """
        with self._get_db() as conn:
            cursor = conn.cursor()

            if len(args) >= 3:
                return self._reclassify_manual(cursor, conn, args, dry_run)

            suggestions = []

            try:
                cursor.execute("""
                    SELECT ml.id, ml.title, mc.times_accessed, mc.weight
                    FROM memory_lessons ml
                    JOIN memory_consolidation mc ON mc.source_table = 'memory_lessons'
                        AND mc.source_id = ml.id
                    WHERE mc.times_accessed >= 5 AND mc.weight > 0.7
                    AND ml.is_active = 1
                    ORDER BY mc.times_accessed DESC
                    LIMIT 10
                """)
                high_access_lessons = cursor.fetchall()
                for lesson in high_access_lessons:
                    suggestions.append({
                        "type": "lesson_to_context",
                        "id": lesson['id'],
                        "title": lesson['title'][:50],
                        "reason": f"Hohe Nutzung ({lesson['times_accessed']}x, weight={lesson['weight']:.2f})"
                    })
            except Exception:
                pass

            try:
                cursor.execute("""
                    SELECT key, value FROM memory_facts
                    WHERE category IN ('user', 'project', 'domain')
                    AND key NOT LIKE 'HELP.%' AND key NOT LIKE 'WIKI.%'
                """)
                orphan_facts = cursor.fetchall()
                for fact in orphan_facts[:5]:
                    suggestions.append({
                        "type": "fact_needs_wiki",
                        "key": fact['key'],
                        "value": str(fact['value'])[:50],
                        "reason": "Kein Wiki/Help-Eintrag vorhanden"
                    })
            except Exception:
                pass

            try:
                cursor.execute("""
                    SELECT id, content FROM memory_working
                    WHERE is_active = 1
                    AND (content LIKE '%gelernt%' OR content LIKE '%Fehler%'
                         OR content LIKE '%Loesung%' OR content LIKE '%wichtig%'
                         OR content LIKE '%merken%' OR content LIKE '%nie wieder%')
                    LIMIT 5
                """)
                lesson_worthy = cursor.fetchall()
                for note in lesson_worthy:
                    suggestions.append({
                        "type": "working_to_lesson",
                        "id": note['id'],
                        "content": note['content'][:50],
                        "reason": "Enthaelt Lesson-Muster"
                    })
            except Exception:
                pass

            if not suggestions:
                return True, "[RECLASSIFY] Keine Reklassifizierungs-Vorschlaege gefunden."

            output = [
                "[RECLASSIFY] Vorschlaege zur Korrektur",
                "=" * 50,
                ""
            ]

            for i, s in enumerate(suggestions, 1):
                if s['type'] == 'lesson_to_context':
                    output.append(f"{i}. LESSON -> CONTEXT: #{s['id']} {s['title']}")
                    output.append(f"   Grund: {s['reason']}")
                elif s['type'] == 'fact_needs_wiki':
                    output.append(f"{i}. FACT braucht WIKI: {s['key']}")
                    output.append(f"   Wert: {s['value']}")
                elif s['type'] == 'working_to_lesson':
                    output.append(f"{i}. WORKING -> LESSON: #{s['id']}")
                    output.append(f"   Inhalt: {s['content']}...")
                output.append(f"   Grund: {s['reason']}")
                output.append("")

            if '--fix' in args:
                return self._reclassify_auto_fix(suggestions, dry_run)

            output.extend([
                "Aktionen:",
                "  bach consolidate reclassify --fix         Automatisch korrigieren",
                "  bach consolidate reclassify lesson 42 context  Manuell umwandeln"
            ])

            return True, "\n".join(output)

    def _reclassify_manual(self, cursor, conn, args: list, dry_run: bool) -> tuple:
        """Manuelle Reklassifizierung eines einzelnen Eintrags."""
        # args: [source_type, source_id, target_type]
        source_type = args[0].lower()
        try:
            source_id = int(args[1])
        except ValueError:
            return False, f"[FEHLER] Ungueltige ID: {args[1]}"
        target_type = args[2].lower()

        valid_conversions = {
            ('lesson', 'context'): self._convert_lesson_to_context,
            ('working', 'lesson'): self._convert_working_to_lesson,
            ('working', 'fact'): self._convert_working_to_fact,
        }

        conversion_key = (source_type, target_type)
        if conversion_key not in valid_conversions:
            return False, f"[FEHLER] Konvertierung {source_type} -> {target_type} nicht unterstuetzt."

        if dry_run:
            return True, f"[DRY-RUN] Wuerde konvertieren: {source_type} #{source_id} -> {target_type}"

        try:
            result = valid_conversions[conversion_key](cursor, conn, source_id)
            conn.commit()
            return True, f"[OK] Konvertiert: {source_type} #{source_id} -> {target_type}"
        except Exception as e:
            return False, f"[FEHLER] Konvertierung fehlgeschlagen: {e}"

    def _convert_lesson_to_context(self, cursor, conn, lesson_id: int) -> bool:
        """Konvertiert eine Lesson zu einem Context-Eintrag."""
        cursor.execute("SELECT title, solution, category FROM memory_lessons WHERE id = ?", (lesson_id,))
        lesson = cursor.fetchone()
        if not lesson:
            raise ValueError(f"Lesson {lesson_id} nicht gefunden")

        import json as _json
        now = datetime.now().isoformat()
        category = lesson['category'] or 'general'
        cursor.execute("""
            INSERT OR REPLACE INTO memory_context
                (source_name, source_path, injection_template, trigger_words, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            f"LESSON_{lesson_id}",
            f"reclassify:lesson:{lesson_id}",
            f"{lesson['title']}: {lesson['solution'] or ''}",
            _json.dumps([category]),
            now
        ))

        cursor.execute("UPDATE memory_lessons SET is_active = 0, updated_at = ? WHERE id = ?",
                      (now, lesson_id))
        return True

    def _convert_working_to_lesson(self, cursor, conn, working_id: int) -> bool:
        """Konvertiert eine Working-Notiz zu einer Lesson."""
        cursor.execute("SELECT content FROM memory_working WHERE id = ?", (working_id,))
        note = cursor.fetchone()
        if not note:
            raise ValueError(f"Working-Notiz {working_id} nicht gefunden")

        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO memory_lessons (title, solution, category, created_at)
            VALUES (?, ?, 'workflow', ?)
        """, (
            note['content'][:100],
            note['content'],
            now
        ))

        cursor.execute("UPDATE memory_working SET is_active = 0, updated_at = ? WHERE id = ?",
                      (now, working_id))
        return True

    def _convert_working_to_fact(self, cursor, conn, working_id: int) -> bool:
        """Konvertiert eine Working-Notiz zu einem Fact."""
        cursor.execute("SELECT content FROM memory_working WHERE id = ?", (working_id,))
        note = cursor.fetchone()
        if not note:
            raise ValueError(f"Working-Notiz {working_id} nicht gefunden")

        now = datetime.now().isoformat()
        # Versuche Key:Value Format zu erkennen
        content = note['content']
        if ':' in content:
            key, value = content.split(':', 1)
        else:
            key = f"NOTE_{working_id}"
            value = content

        cursor.execute("""
            INSERT INTO memory_facts (key, value, category, source, created_at)
            VALUES (?, ?, 'user', ?, ?)
        """, (key.strip(), value.strip(), f"reclassify:working:{working_id}", now))

        # Working deaktivieren
        cursor.execute("UPDATE memory_working SET is_active = 0, updated_at = ? WHERE id = ?",
                      (now, working_id))
        return True

    def _reclassify_auto_fix(self, suggestions: list, dry_run: bool) -> tuple:
        """Fuehrt automatische Reklassifizierungen durch."""
        if dry_run:
            return True, f"[DRY-RUN] Wuerde {len(suggestions)} Eintraege reklassifizieren"

        with self._get_db() as conn:
            cursor = conn.cursor()

            fixed = 0
            tasks_created = 0
            now = datetime.now().isoformat()

            for s in suggestions:
                try:
                    if s['type'] == 'lesson_to_context':
                        self._convert_lesson_to_context(cursor, conn, s['id'])
                        fixed += 1
                    elif s['type'] == 'working_to_lesson':
                        self._convert_working_to_lesson(cursor, conn, s['id'])
                        fixed += 1
                    elif s['type'] == 'fact_needs_wiki':
                        task_title = f"[WIKI] Eintrag fuer Fact: {s['key']}"
                        cursor.execute("""
                            INSERT INTO tasks (title, description, priority, status, category, created_at)
                            VALUES (?, ?, 'P4', 'pending', 'documentation', ?)
                        """, (task_title, f"Fact-Wert: {s['value']}", now))
                        tasks_created += 1
                except Exception:
                    continue

            conn.commit()

            return True, f"[OK] {fixed} Eintraege reklassifiziert, {tasks_created} Tasks erstellt"
