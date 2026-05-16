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
    db_path = bach_root / "data" / "bach.db"

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
    else:
        print("Usage: python memory_working_cleanup.py <command> [--dry-run]")
        print("")
        print("Commands:")
        print("  analyze          Analysiere memory_working Eintraege")
        print("  set-expires      Setze Expires rueckwirkend")
        print("  cleanup          Soft delete expired Eintraege")
        sys.exit(1)


if __name__ == "__main__":
    main()
