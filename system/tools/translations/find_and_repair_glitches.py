#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Findet und repariert Platzhalter-/URL-Glitches in BACH-Uebersetzungen."""

from __future__ import annotations

import re
import sys

from db_access import build_parser, connect


sys.stdout.reconfigure(encoding="utf-8")


def fix_glitches(text):
    if not text or not isinstance(text, str):
        return text

    new_text = re.sub(r"\{\s+([a-zA-Z0-9_]+)\s+\}", r"{\1}", text)
    new_text = re.sub(r"\{\s+([a-zA-Z0-9_]+)\}", r"{\1}", new_text)
    new_text = re.sub(r"\{([a-zA-Z0-9_]+)\s+\}", r"{\1}", new_text)
    new_text = re.sub(r"%\s+([sd])", r"%\1", new_text)
    new_text = re.sub(
        r"https?\s*:\s*/\s*/",
        r"http://" if "http:" in text else "https://",
        new_text,
    )
    new_text = re.sub(
        r"https?\s+://",
        r"https://" if "https" in text else "http://",
        new_text,
    )
    return new_text


parser = build_parser(__doc__ or "Findet Uebersetzungs-Glitches.")
parser.add_argument("--apply", action="store_true", help="Aenderungen wirklich in die DB schreiben.")
args = parser.parse_args()

db_path, conn = connect(args.db)
rows = conn.execute("SELECT id, key, namespace, language, value FROM languages_translations").fetchall()

repaired_in_db = 0
cur = conn.cursor()

for row in rows:
    value = row["value"]
    fixed_value = fix_glitches(value)
    if fixed_value != value:
        if args.apply:
            cur.execute(
                "UPDATE languages_translations SET value = ?, updated_at = datetime('now') WHERE id = ?",
                (fixed_value, row["id"]),
            )
        repaired_in_db += 1
        if repaired_in_db <= 5:
            verb = "FIXED" if args.apply else "WOULD FIX"
            print(
                f"[{row['namespace']}] {row['key']} ({row['language']}) {verb}:\n"
                f"  BEFORE: {repr(value[:60])}\n"
                f"  AFTER:  {repr(fixed_value[:60])}"
            )

try:
    if args.apply:
        conn.commit()
    else:
        conn.rollback()
finally:
    conn.close()

mode = "Repaired" if args.apply else "Would repair"
print(f"Database {db_path}: {mode} {repaired_in_db} glitch entries.")
