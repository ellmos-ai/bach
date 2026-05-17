#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Help-Docs Generator: Verwaltet vollständige Help-Dateien in der DB.

Zwei Modi:
  ingest  - Liest bestehende .txt-Dateien ein und speichert sie in languages_translations (namespace=help_doc)
  generate - Erzeugt .txt-Dateien aus der DB für eine bestimmte Sprache

Konvention:
  - Key = relativer Pfad ohne Endung, z.B. "install", "tools/python_cli_editor"
  - Deutsche Dateien: topic.txt (key="topic", language="de")
  - Englische Dateien: topic_en.txt (key="topic", language="en")
  - Unterordner: folder/topic.txt (key="folder/topic", language="de")

Usage:
  python help_docs_generator.py ingest [--lang de|en] [--dry-run]
  python help_docs_generator.py generate --lang en [--dry-run]
  python help_docs_generator.py stats
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

HELP_DIR = SYSTEM_ROOT / "docs" / "help"
DB_PATH = SYSTEM_ROOT / "data" / "bach.db"
NAMESPACE = "help_doc"


def _get_db(db_path: Path = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Stellt sicher, dass languages_translations existiert."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS languages_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            namespace TEXT DEFAULT 'general',
            language TEXT NOT NULL DEFAULT 'de',
            value TEXT NOT NULL,
            is_verified INTEGER DEFAULT 0,
            source TEXT DEFAULT 'file_import',
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(key, namespace, language)
        )
    """)
    conn.commit()


def ingest(lang: str = None, dry_run: bool = False, db_path: Path = None) -> dict:
    """Importiert bestehende .txt Help-Dateien in die DB.

    Erkennt Sprache aus Dateiname:
      topic.txt -> DE (default)
      topic_en.txt -> EN
    Wenn --lang angegeben, werden nur Dateien dieser Sprache importiert.
    """
    conn = _get_db(db_path)
    _ensure_table(conn)

    stats = {"imported": 0, "skipped": 0, "updated": 0, "errors": []}
    now = datetime.now().isoformat()

    for txt_file in sorted(HELP_DIR.rglob("*.txt")):
        if txt_file.name.startswith("_"):
            continue

        rel = txt_file.relative_to(HELP_DIR)
        stem = rel.stem
        parent = str(rel.parent).replace("\\", "/")

        # Sprache aus Dateiname erkennen
        file_lang = "de"
        if stem.endswith("_en"):
            file_lang = "en"
            stem = stem[:-3]
        elif stem.endswith("_es"):
            file_lang = "es"
            stem = stem[:-3]
        elif stem.endswith("_fr"):
            file_lang = "fr"
            stem = stem[:-3]
        elif stem.endswith("_ja"):
            file_lang = "ja"
            stem = stem[:-3]
        elif stem.endswith("_zh"):
            file_lang = "zh"
            stem = stem[:-3]
        elif stem.endswith("_ru"):
            file_lang = "ru"
            stem = stem[:-3]

        # Filter nach Sprache wenn angegeben
        if lang and file_lang != lang:
            continue

        # Key zusammenbauen
        if parent == ".":
            key = stem
        else:
            key = f"{parent}/{stem}"

        try:
            content = txt_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            stats["errors"].append(f"{txt_file.name}: {e}")
            continue

        if not content.strip():
            stats["skipped"] += 1
            continue

        if dry_run:
            print(f"  [DRY] {key} ({file_lang}) <- {rel}")
            stats["imported"] += 1
            continue

        # Upsert
        existing = conn.execute(
            "SELECT id FROM languages_translations WHERE key=? AND namespace=? AND language=?",
            (key, NAMESPACE, file_lang)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE languages_translations SET value=?, updated_at=?, source='file_import' WHERE id=?",
                (content, now, existing["id"])
            )
            stats["updated"] += 1
        else:
            conn.execute(
                """INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, 'file_import', ?, ?)""",
                (key, NAMESPACE, file_lang, content, now, now)
            )
            stats["imported"] += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return stats


def generate(lang: str, dry_run: bool = False, db_path: Path = None, fallback: str = "en") -> dict:
    """Generiert .txt Help-Dateien aus der DB für eine bestimmte Sprache.

    Fallback-Logik: Wenn ein Topic in der Zielsprache nicht existiert,
    wird die Fallback-Sprache (default: EN) verwendet.

    Schreibt:
      DE-Dateien als topic.txt
      EN-Dateien als topic_en.txt (usw. für andere Sprachen)
    """
    conn = _get_db(db_path)
    _ensure_table(conn)

    # Alle Keys der Zielsprache laden
    rows = conn.execute(
        "SELECT key, value FROM languages_translations WHERE namespace=? AND language=?",
        (NAMESPACE, lang)
    ).fetchall()

    # Fallback: Alle Keys der Fallback-Sprache die in Zielsprache fehlen
    target_keys = {row["key"] for row in rows}
    fallback_rows = []
    if fallback and fallback != lang:
        fallback_rows = conn.execute(
            "SELECT key, value FROM languages_translations WHERE namespace=? AND language=?",
            (NAMESPACE, fallback)
        ).fetchall()
        fallback_rows = [r for r in fallback_rows if r["key"] not in target_keys]

    conn.close()

    stats = {"generated": 0, "skipped": 0, "fallback_used": 0, "errors": []}

    def _write_file(key: str, content: str, file_lang: str, is_fallback: bool = False) -> None:
        if not content or not content.strip():
            stats["skipped"] += 1
            return

        if "/" in key:
            parts = key.rsplit("/", 1)
            folder = parts[0]
            stem = parts[1]
            target_dir = HELP_DIR / folder
        else:
            stem = key
            target_dir = HELP_DIR

        # Suffix je nach Sprache (DE=kein Suffix, andere=_xx)
        if file_lang == "de":
            filename = f"{stem}.txt"
        else:
            filename = f"{stem}_{file_lang}.txt"

        target_file = target_dir / filename

        if dry_run:
            tag = "[DRY-FB]" if is_fallback else "[DRY]"
            print(f"  {tag} {target_file.relative_to(HELP_DIR)}")
            stats["generated"] += 1
            if is_fallback:
                stats["fallback_used"] += 1
            return

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
            stats["generated"] += 1
            if is_fallback:
                stats["fallback_used"] += 1
        except OSError as e:
            stats["errors"].append(f"{filename}: {e}")

    # Zielsprache generieren
    for row in rows:
        _write_file(row["key"], row["value"], lang)

    # Fallback-Dateien generieren (in Fallback-Sprache, für fehlende Topics)
    for row in fallback_rows:
        _write_file(row["key"], row["value"], fallback, is_fallback=True)

    return stats


def stats(db_path: Path = None) -> dict:
    """Zeigt Statistiken über Help-Docs in der DB."""
    conn = _get_db(db_path)
    _ensure_table(conn)

    result = {}
    rows = conn.execute(
        "SELECT language, COUNT(*) as cnt, SUM(LENGTH(value)) as total_size, AVG(LENGTH(value)) as avg_size "
        "FROM languages_translations WHERE namespace=? GROUP BY language",
        (NAMESPACE,)
    ).fetchall()
    conn.close()

    for row in rows:
        result[row["language"]] = {
            "count": row["cnt"],
            "total_size": row["total_size"],
            "avg_size": int(row["avg_size"]) if row["avg_size"] else 0,
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Help-Docs Generator: DB <-> .txt Dateien")
    sub = parser.add_subparsers(dest="command")

    p_ingest = sub.add_parser("ingest", help="Importiert .txt-Dateien in die DB")
    p_ingest.add_argument("--lang", choices=["de", "en", "es", "fr", "ja", "zh", "ru"], help="Nur diese Sprache importieren")
    p_ingest.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht schreiben")
    p_ingest.add_argument("--db-path", type=Path, default=None)

    p_gen = sub.add_parser("generate", help="Generiert .txt-Dateien aus der DB")
    p_gen.add_argument("--lang", required=True, choices=["de", "en", "es", "fr", "ja", "zh", "ru"])
    p_gen.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht schreiben")
    p_gen.add_argument("--db-path", type=Path, default=None)

    p_stats = sub.add_parser("stats", help="Zeigt DB-Statistiken")
    p_stats.add_argument("--db-path", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "ingest":
        result = ingest(lang=args.lang, dry_run=args.dry_run, db_path=args.db_path)
        print(f"Ingest: {result['imported']} importiert, {result['updated']} aktualisiert, "
              f"{result['skipped']} übersprungen")
        if result["errors"]:
            for e in result["errors"]:
                print(f"  FEHLER: {e}")
        return 0

    elif args.command == "generate":
        result = generate(lang=args.lang, dry_run=args.dry_run, db_path=args.db_path)
        print(f"Generate ({args.lang}): {result['generated']} Dateien erstellt, "
              f"{result['skipped']} übersprungen")
        if result["errors"]:
            for e in result["errors"]:
                print(f"  FEHLER: {e}")
        return 0

    elif args.command == "stats":
        result = stats(db_path=args.db_path)
        if not result:
            print("Keine Help-Docs in der DB.")
        else:
            print("Help-Docs Statistik:")
            for lang_code, info in sorted(result.items()):
                print(f"  {lang_code}: {info['count']} Dateien, "
                      f"Ø {info['avg_size']} Zeichen, "
                      f"Gesamt: {info['total_size']//1024} KB")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
