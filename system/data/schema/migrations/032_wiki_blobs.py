"""
Migration 032: Wiki-Artikel als BLOBs in bach.db laden (SQ044)
Liest alle Wiki-Artikel aus system/wiki/ und fuegt sie in bach_blobs ein.
"""
import hashlib
from pathlib import Path


def run_migration(conn):
    """Wird vom Migrations-Runner in db.py aufgerufen."""
    # SQL-Migration zuerst ausfuehren (Tabellen anlegen)
    sql_file = Path(__file__).with_suffix('.sql')
    if sql_file.exists():
        conn.executescript(sql_file.read_text(encoding='utf-8'))

    # Wiki-Pfad relativ zum BACH system/ Verzeichnis
    system_dir = Path(__file__).resolve().parent.parent.parent  # system/
    wiki_dir = system_dir / 'wiki'

    if not wiki_dir.exists():
        print(f"Wiki-Verzeichnis nicht gefunden: {wiki_dir}")
        return

    count = 0
    cursor = conn.cursor()

    # Alle .txt Dateien rekursiv einlesen
    for txt_file in sorted(wiki_dir.rglob('*.txt')):
        if txt_file.name.startswith('_'):
            continue

        try:
            content = txt_file.read_text(encoding='utf-8', errors='replace')
            rel_path = txt_file.relative_to(system_dir).as_posix()  # z.B. wiki/psychotherapie/dbt.txt
            checksum = hashlib.sha256(content.encode('utf-8')).hexdigest()
            size_bytes = len(content.encode('utf-8'))

            # Kategorie aus Unterordner oder 'wiki' als Default
            parts = rel_path.split('/')
            category = parts[1] if len(parts) > 2 else 'wiki'

            cursor.execute("""
                INSERT OR REPLACE INTO bach_blobs
                (path, category, content, mime_type, size_bytes, checksum, lang, created_at, updated_at)
                VALUES (?, ?, ?, 'text/plain', ?, ?, 'de', datetime('now'), datetime('now'))
            """, (rel_path, category, content, size_bytes, checksum))

            count += 1
        except Exception as e:
            print(f"Fehler bei {txt_file}: {e}")

    conn.commit()
    print(f"Migration 032: {count} Wiki-Artikel in bach_blobs geladen.")
