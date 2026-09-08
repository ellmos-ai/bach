#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Korrigiert haeufige Fachbegriffe in BACH-Uebersetzungen."""

from __future__ import annotations

import sys

from db_access import build_parser, connect


sys.stdout.reconfigure(encoding="utf-8")

FIXES = {
    "achtung": {
        "es": "ATENCIÓN",
        "ru": "ВНИМАНИЕ",
        "ja": "警告",
        "zh": "注意",
    },
    "hinweis": {
        "es": "NOTA",
        "ru": "ПРИМЕЧАНИЕ",
        "ja": "注記",
        "zh": "提示",
    },
    "beispiel": {
        "es": "EJEMPLO",
        "ru": "ПРИМЕР",
        "ja": "例",
        "zh": "示例",
    },
    "fehler": {
        "es": "ERROR",
        "ru": "ОШИБКА",
        "ja": "エラー",
        "zh": "错误",
    },
}

parser = build_parser(__doc__ or "Korrigiert haeufige Fachbegriffe.")
parser.add_argument("--apply", action="store_true", help="Aenderungen wirklich in die DB schreiben.")
args = parser.parse_args()

db_path, conn = connect(args.db)
cur = conn.cursor()

updated = 0
for key, lang_map in FIXES.items():
    for lang, target_value in lang_map.items():
        if args.apply:
            cur.execute(
                """
                UPDATE languages_translations
                SET value = ?, is_verified = 1, updated_at = datetime('now')
                WHERE key = ? AND language = ? AND value IN ('WARNING', 'NOTE', 'EXAMPLE', 'ERROR')
                """,
                (target_value, key, lang),
            )
            updated += cur.rowcount
        else:
            row = cur.execute(
                """
                SELECT COUNT(*) FROM languages_translations
                WHERE key = ? AND language = ? AND value IN ('WARNING', 'NOTE', 'EXAMPLE', 'ERROR')
                """,
                (key, lang),
            ).fetchone()
            updated += row[0]

try:
    if args.apply:
        conn.commit()
    else:
        conn.rollback()
finally:
    conn.close()

mode = "Updated" if args.apply else "Would update"
print(f"Database {db_path}: {mode} {updated} term entries.")
