#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
memory_working_cleanup.py - Working Memory Cleanup Tool
=======================================================

Bereinigt memory_working nach Expires-Regeln.

CLI:
    python memory_working_cleanup.py analyze     Analysiere Eintraege
    python memory_working_cleanup.py cleanup     Soft delete expired
    python memory_working_cleanup.py --dry-run   Zeige was geloescht wuerde

Teil von SQ043: Memory-DB & Partner-Vernetzung
Referenz: BACH_Dev/docs/MEMORY_WORKING_CLEANUP_KONZEPT.md
"""

import json
import os
from pathlib import Path
import sqlite3


class WorkingMemoryCleanup:
    """Working Memory Cleanup und Analyse."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def analyze_stats(self) -> dict:
        """Sammelt Statistikdaten fuer memory_working Eintraege."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                type,
                content,
                priority,
                created_at,
                julianday('now') - julianday(created_at) as age_days,
                expires_at,
                is_active
            FROM memory_working
            WHERE is_active = 1
            ORDER BY created_at DESC
            """
        )
        entries = cursor.fetchall()
        conn.close()

        stats = {
            "total": len(entries),
            "keep": 0,
            "review": 0,
            "archive": 0,
            "by_age": {"< 7d": 0, "7-14d": 0, "> 14d": 0},
            "entries": [],
        }

        for entry_id, entry_type, content, priority, _created_at, age_days, expires_at, is_active in entries:
            if age_days < 7:
                action = "KEEP"
                stats["keep"] += 1
                stats["by_age"]["< 7d"] += 1
            elif age_days < 14:
                action = "REVIEW"
                stats["review"] += 1
                stats["by_age"]["7-14d"] += 1
            else:
                action = "ARCHIVE"
                stats["archive"] += 1
                stats["by_age"]["> 14d"] += 1

            stats["entries"].append(
                {
                    "id": entry_id,
                    "type": entry_type,
                    "content": content[:80] if content else "",
                    "priority": priority,
                    "age_days": round(age_days, 1),
                    "action": action,
                    "expires_at": expires_at,
                    "is_active": is_active,
                }
            )

        return stats

    def analyze(self, dry_run: bool = True) -> tuple[bool, str]:
        """Analysiert memory_working Eintraege.

        Args:
            dry_run: Wird ignoriert (analyze aendert keine Daten)

        Returns:
            (success, message): Erfolgs-Status und formatierte Statistik
        """
        stats = self.analyze_stats()

        msg = f"""
Working Memory Analyse
===========================================================

GESAMT: {stats['total']} Eintraege

EMPFEHLUNGEN:
  KEEP    (< 7 Tage):   {stats['keep']:3d}
  REVIEW  (7-14 Tage):  {stats['review']:3d}
  ARCHIVE (> 14 Tage):  {stats['archive']:3d}

ALTER-VERTEILUNG:
  < 7 Tage:   {stats['by_age']['< 7d']:3d}
  7-14 Tage:  {stats['by_age']['7-14d']:3d}
  > 14 Tage:  {stats['by_age']['> 14d']:3d}

[TIPP] bach mem working cleanup --dry-run
"""
        return True, msg.strip()

    def set_expires_retroactive(self, dry_run: bool = True) -> tuple[bool, str]:
        """Setzt expires_at rueckwirkend fuer alle Eintraege ohne Expires."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memory_working WHERE expires_at IS NULL")
        count_null = cursor.fetchone()[0]

        if count_null == 0:
            conn.close()
            return True, "Alle Eintraege haben bereits expires_at gesetzt"

        if dry_run:
            conn.close()
            return True, f"[DRY-RUN] Wuerde {count_null} Eintraegen expires_at setzen"

        cursor.execute(
            """
            UPDATE memory_working
            SET expires_at = datetime('now', '+7 days')
            WHERE julianday('now') - julianday(created_at) < 7
            AND expires_at IS NULL
            """
        )
        recent_updated = cursor.rowcount

        cursor.execute(
            """
            UPDATE memory_working
            SET expires_at = datetime('now')
            WHERE julianday('now') - julianday(created_at) >= 7
            AND expires_at IS NULL
            """
        )
        old_updated = cursor.rowcount

        conn.commit()
        conn.close()

        return True, f"Expires gesetzt: {recent_updated} recent (+7d), {old_updated} old (now)"

    def cleanup_soft(self, dry_run: bool = True) -> tuple[bool, str]:
        """Soft delete (is_active=0) fuer expired Eintraege."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM memory_working
            WHERE expires_at < datetime('now')
            AND is_active = 1
            """
        )
        count_expired = cursor.fetchone()[0]

        if count_expired == 0:
            conn.close()
            return True, "Keine expired Eintraege zum Bereinigen"

        if dry_run:
            conn.close()
            return True, f"[DRY-RUN] Wuerde {count_expired} expired Eintraege soft-deleten"

        cursor.execute(
            """
            UPDATE memory_working
            SET is_active = 0
            WHERE expires_at < datetime('now')
            AND is_active = 1
            """
        )

        conn.commit()
        conn.close()

        return True, f"{count_expired} expired Eintraege soft-deleted (is_active=0)"

    def cleanup(self, dry_run: bool = True) -> tuple[bool, str]:
        """Rueckwaertskompatibler Alias fuer bestehende Startup-/Handler-Aufrufe."""
        return self.cleanup_soft(dry_run=dry_run)

    def archive(self, days: int = 30, dry_run: bool = True) -> tuple[bool, str]:
        """Move old entries atomically while preserving the complete source row."""
        if days <= 0:
            return False, "days muss größer als 0 sein"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_memory'"
        )
        if cursor.fetchone() is None:
            conn.close()
            return False, "archived_memory-Tabelle fehlt (schema_archive.sql nicht angewendet)"

        archive_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(archived_memory)")
        }
        if "source_record" not in archive_columns:
            conn.close()
            return False, (
                "archived_memory.source_record fehlt "
                "(Migration 042_archived_memory_source_record.py nicht angewendet)"
            )

        working_columns = [
            row[1] for row in cursor.execute("PRAGMA table_info(memory_working)")
        ]
        if "id" not in working_columns:
            conn.close()
            return False, "memory_working.id fehlt"
        select_columns = ", ".join(f'"{name}"' for name in working_columns)
        cutoff = "julianday('now') - julianday(created_at) > ?"
        cursor.execute(
            f"""
            SELECT {select_columns}
            FROM memory_working
            WHERE {cutoff}
              AND NOT EXISTS (
                  SELECT 1 FROM archived_memory
                  WHERE memory_type='working'
                    AND original_id = memory_working.id
              )
            ORDER BY created_at
            """,
            (days,),
        )
        rows = cursor.fetchall()

        if not rows:
            conn.close()
            return True, (
                f"Keine Eintraege > {days} Tage zum Archivieren "
                f"(alle aktuell oder bereits archiviert)"
            )

        if dry_run:
            id_index = working_columns.index("id")
            ids = [row[id_index] for row in rows]
            conn.close()
            return True, (
                f"[DRY-RUN] Wuerde {len(rows)} Eintraege > {days} Tage "
                f"(id {min(ids)}..{max(ids)}) nach archived_memory verschieben"
            )

        reason = f"auto-archived after {days} days"
        records = [dict(zip(working_columns, row)) for row in rows]
        data = [
            (
                record["id"],
                record.get("type"),
                record.get("content"),
                record.get("created_at"),
                reason,
                json.dumps(record, ensure_ascii=False, separators=(",", ":")),
            )
            for record in records
        ]
        try:
            cursor.executemany(
                """
                INSERT INTO archived_memory
                    (original_id, memory_type, category, key, content,
                     created_at, archived_at, archive_reason, source_record)
                VALUES (?, 'working', ?, NULL, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                """,
                data,
            )
            archived_count = cursor.rowcount
            cursor.execute(
                "DELETE FROM memory_working WHERE id IN ("
                + ",".join("?" * len(rows))
                + ")",
                [record["id"] for record in records],
            )
            deleted_count = cursor.rowcount
            if archived_count != len(rows) or deleted_count != len(rows):
                conn.rollback()
                conn.close()
                return False, (
                    f"Rowcount-Mismatch: archiviert {archived_count}, "
                    f"geloescht {deleted_count} von {len(rows)} -> rollback"
                )
            conn.commit()
        except (sqlite3.Error, TypeError, ValueError) as exc:
            conn.rollback()
            conn.close()
            return False, f"Archiv-Fehler: {exc}"
        conn.close()
        return True, (
            f"{archived_count} Eintraege > {days} Tage nach archived_memory "
            f"verschoben (reversibel, reason='{reason}')"
        )

    def restore(self, archive_id: int, dry_run: bool = True) -> tuple[bool, str]:
        """Restore one Working Memory entry atomically from its complete source row."""
        if archive_id <= 0:
            return False, "archive_id muss größer als 0 sein"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            archive_columns = {
                row[1] for row in cursor.execute("PRAGMA table_info(archived_memory)")
            }
            if "source_record" not in archive_columns:
                return False, (
                    "archived_memory.source_record fehlt "
                    "(Migration 042_archived_memory_source_record.py nicht angewendet)"
                )

            row = cursor.execute(
                """
                SELECT original_id, source_record
                FROM archived_memory
                WHERE archive_id = ? AND memory_type = 'working'
                """,
                (archive_id,),
            ).fetchone()
            if row is None:
                return False, f"Working-Memory-Archiv {archive_id} nicht gefunden"
            original_id, source_record = row
            if not source_record:
                return False, (
                    f"Working-Memory-Archiv {archive_id} ist ein Legacy-Eintrag "
                    "ohne verlustfreien source_record"
                )

            try:
                record = json.loads(source_record)
            except (TypeError, json.JSONDecodeError) as exc:
                return False, f"Ungültiger source_record in Archiv {archive_id}: {exc}"
            if not isinstance(record, dict) or record.get("id") != original_id:
                return False, f"source_record in Archiv {archive_id} passt nicht zu original_id"

            working_columns = {
                item[1] for item in cursor.execute("PRAGMA table_info(memory_working)")
            }
            unknown_columns = set(record) - working_columns
            if unknown_columns:
                return False, (
                    "memory_working-Schema kann Archiv nicht verlustfrei aufnehmen: "
                    + ", ".join(sorted(unknown_columns))
                )
            if "id" not in record:
                return False, f"source_record in Archiv {archive_id} hat keine id"
            if cursor.execute(
                "SELECT 1 FROM memory_working WHERE id = ?", (original_id,)
            ).fetchone():
                return False, f"memory_working.id {original_id} ist bereits belegt"

            if dry_run:
                return True, (
                    f"[DRY-RUN] Wuerde Working-Memory-Archiv {archive_id} "
                    f"als id {original_id} wiederherstellen"
                )

            columns = list(record)
            quoted_columns = ", ".join(f'"{name}"' for name in columns)
            placeholders = ", ".join("?" for _ in columns)
            cursor.execute(
                f"INSERT INTO memory_working ({quoted_columns}) VALUES ({placeholders})",
                [record[name] for name in columns],
            )
            if cursor.rowcount != 1:
                raise sqlite3.IntegrityError("Restore-Insert hat keine Zeile erzeugt")

            # INSERT-Provenienz-Trigger duerfen historische NULL-/Session-Werte
            # nicht auf die aktuelle Session umschreiben. Ein explizites UPDATE
            # setzt deshalb unmittelbar danach den archivierten Datensatz exakt.
            value_columns = [name for name in columns if name != "id"]
            assignments = ", ".join(f'"{name}" = ?' for name in value_columns)
            if assignments:
                cursor.execute(
                    f"UPDATE memory_working SET {assignments} WHERE id = ?",
                    [record[name] for name in value_columns] + [original_id],
                )
                if cursor.rowcount != 1:
                    raise sqlite3.IntegrityError(
                        "Restore-Normalisierung hat keine Zeile aktualisiert"
                    )

            if cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='restore_log'"
            ).fetchone():
                cursor.execute(
                    """
                    INSERT INTO restore_log
                        (archive_table, archive_id, target_db, target_id, success, notes)
                    VALUES ('archived_memory', ?, ?, ?, 1, 'working-memory restore')
                    """,
                    (archive_id, str(self.db_path), original_id),
                )

            cursor.execute(
                "DELETE FROM archived_memory WHERE archive_id = ? AND memory_type = 'working'",
                (archive_id,),
            )
            if cursor.rowcount != 1:
                raise sqlite3.IntegrityError("Restore-Archivloeschung hat keine Zeile entfernt")
            conn.commit()
        except (sqlite3.Error, TypeError, ValueError) as exc:
            conn.rollback()
            return False, f"Restore-Fehler: {exc}"
        finally:
            conn.close()

        return True, (
            f"Working-Memory-Archiv {archive_id} verlustfrei als id {original_id} "
            "wiederhergestellt"
        )


def print_analysis(stats: dict) -> None:
    """Druckt Analyse-Ergebnisse mit aeltesten Eintraegen."""
    print("=" * 70)
    print("WORKING MEMORY ANALYSE")
    print("=" * 70)
    print("")
    print(f"Total Eintraege:  {stats['total']}")
    print("")
    print("AKTIONEN:")
    print(f"  KEEP (< 7 Tage):      {stats['keep']:<3} ({stats['by_age']['< 7d']})")
    print(f"  REVIEW (7-14 Tage):   {stats['review']:<3} ({stats['by_age']['7-14d']})")
    print(f"  ARCHIVE (> 14 Tage):  {stats['archive']:<3} ({stats['by_age']['> 14d']})")
    print("")

    print("TOP 10 AELTESTE EINTRAEGE:")
    print("-" * 70)
    oldest = sorted(stats["entries"], key=lambda item: item["age_days"], reverse=True)[:10]
    for entry in oldest:
        print(f"  [{entry['action']:7}] {entry['age_days']:5.1f}d | {entry['content'][:60]}")
    print("")


def main() -> None:
    """CLI entry point."""
    import sys

    bach_root = Path(__file__).parent.parent
    db_path = Path(
        os.environ.get("BACH_DB", str(bach_root / "data" / "bach.db"))
    ).expanduser()

    if not db_path.exists():
        print(f"[ERROR] DB nicht gefunden: {db_path}")
        sys.exit(1)

    cleanup = WorkingMemoryCleanup(db_path)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if cmd == "analyze":
        print_analysis(cleanup.analyze_stats())
    elif cmd == "set-expires":
        success, msg = cleanup.set_expires_retroactive(dry_run=dry_run)
        print(msg)
        if not success:
            sys.exit(1)
    elif cmd == "cleanup":
        success, msg = cleanup.cleanup_soft(dry_run=dry_run)
        print(msg)
        if not success:
            sys.exit(1)
    elif cmd == "archive":
        # Task #1313 (Option B): reversibler Move nach archived_memory.
        # Sicherheit: Standard ist DRY-RUN; nur mit --apply wird ausgefuehrt.
        days = 30
        for i, a in enumerate(sys.argv):
            if a == "--days" and i + 1 < len(sys.argv):
                try:
                    days = int(sys.argv[i + 1])
                except ValueError:
                    print("[ERROR] --days erwartet eine positive Ganzzahl")
                    sys.exit(1)
        if days <= 0:
            print("[ERROR] --days muss größer als 0 sein")
            sys.exit(1)
        apply_now = "--apply" in sys.argv
        success, msg = cleanup.archive(days=days, dry_run=not apply_now)
        print(msg)
        if not success:
            sys.exit(1)
    elif cmd == "restore":
        positional = [a for a in sys.argv[2:] if not a.startswith("--")]
        if not positional:
            print("[ERROR] restore erwartet eine archive_id")
            sys.exit(1)
        try:
            archive_id = int(positional[0])
        except ValueError:
            print("[ERROR] archive_id muss eine positive Ganzzahl sein")
            sys.exit(1)
        apply_now = "--apply" in sys.argv
        success, msg = cleanup.restore(archive_id, dry_run=not apply_now)
        print(msg)
        if not success:
            sys.exit(1)
    else:
        print("Usage: python memory_working_cleanup.py <command> [--dry-run]")
        print("")
        print("Commands:")
        print("  analyze          Analysiere memory_working Eintraege")
        print("  set-expires      Setze Expires rueckwirkend")
        print("  cleanup          Soft delete expired Eintraege")
        print("  archive [--apply]  Reversibel alte Eintraege > 30d nach archived_memory (Standard: dry-run)")
        print("  restore ID [--apply]  Archivierten Working-Memory-Eintrag wiederherstellen")
        sys.exit(1)


if __name__ == "__main__":
    main()
