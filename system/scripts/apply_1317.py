#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply fix for Task #1317: translate leftover DE marker "Förderziele" in
cli.word_template_service_allge into the affected target languages.

Default mode is DRY-RUN. Pass --apply to mutate the database.
The script writes a restore.sql next to the database for rollback.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from tools.translations.db_access import connect

# Target row identified by manual QA #1317 review.
# Key is stored without namespace prefix; namespace='cli'.
KEY = "word_template_service_allge"
NAMESPACE = "cli"

# Bijektive Zielmenge: id <-> (language, replacement)
TARGETS = {
    7163: ("en", "funding objectives"),
    12793: ("es", "objetivos de financiación"),
    14817: ("ja", "資金調達目的"),
    13810: ("ru", "цели финансирования"),
    15824: ("zh", "资助目标"),
}

DE_ROW_ID = 4470
DE_LANGUAGE = "de"
DE_MARKER = "Förderziele"
SOURCE = "manual_qa_1317"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply #1317 translation fix for leftover German marker."
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="Optionaler DB-Pfad."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Änderungen tatsächlich in die DB schreiben (default: dry-run).",
    )
    parser.add_argument(
        "--verdict",
        type=Path,
        default=Path("/tmp/review1317_verdict.json"),
        help="Pfad zur Verdict-JSON von make_verdict_1317.py.",
    )
    return parser


def ensure_schema(conn) -> list[str]:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(languages_translations)")
    rows = cur.fetchall()
    columns = [row["name"] for row in rows]
    required = {"id", "key", "namespace", "language", "value", "source", "is_verified"}
    missing = required - set(columns)
    if missing:
        raise AssertionError(f"Struktur-Assert fehlgeschlagen: fehlende Spalten {missing}")
    return columns


def load_verdict(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Verdict-Datei nicht gefunden: {path}")
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def assert_bijektion(conn) -> dict[int, sqlite3.Row]:
    cur = conn.cursor()
    ids = list(TARGETS.keys())
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"SELECT id, key, namespace, language, value, source, is_verified "
        f"FROM languages_translations WHERE id IN ({placeholders})",
        ids,
    )
    rows = {row["id"]: row for row in cur.fetchall()}

    # 1. Jede Ziel-ID existiert.
    missing = set(ids) - set(rows.keys())
    if missing:
        raise AssertionError(f"Bijektion-Assert: IDs fehlen in DB: {sorted(missing)}")

    # 2. Jede zurückgegebene ID gehört zur Zielmenge.
    extra = set(rows.keys()) - set(ids)
    if extra:
        raise AssertionError(f"Bijektion-Assert: unerwartete IDs: {sorted(extra)}")

    # 3. key/namespace stimmen; Sprache entspricht TARGETS.
    for rid, (expected_lang, _repl) in TARGETS.items():
        row = rows[rid]
        if row["key"] != KEY or row["namespace"] != NAMESPACE:
            raise AssertionError(
                f"Bijektion-Assert: id={rid} erwartet key={KEY}/namespace={NAMESPACE}, "
                f"hat aber key={row['key']}/namespace={row['namespace']}"
            )
        if row["language"] != expected_lang:
            raise AssertionError(
                f"Bijektion-Assert: id={rid} erwartet lang={expected_lang}, "
                f"hat aber lang={row['language']}"
            )
    return rows


def assert_de_marker_preserved(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, language, value FROM languages_translations WHERE id = ?",
        (DE_ROW_ID,),
    )
    row = cur.fetchone()
    if row is None:
        raise AssertionError(f"DE-Marker-Assert: DE-Zeile id={DE_ROW_ID} fehlt")
    if row["language"] != DE_LANGUAGE:
        raise AssertionError(
            f"DE-Marker-Assert: id={DE_ROW_ID} hat language={row['language']}, "
            f"erwartet {DE_LANGUAGE}"
        )
    if DE_MARKER not in row["value"]:
        raise AssertionError(
            f"DE-Marker-Assert: id={DE_ROW_ID} enthält nicht mehr den DE-Marker "
            f"'{DE_MARKER}'"
        )


def compute_new_values(rows: dict[int, sqlite3.Row]) -> dict[int, str]:
    updates: dict[int, str] = {}
    for rid, (lang, replacement) in TARGETS.items():
        old_value = rows[rid]["value"]
        if DE_MARKER not in old_value:
            raise AssertionError(
                f"DE-Marker-Assert: id={rid} (lang={lang}) enthält "
                f"'{DE_MARKER}' nicht; keine Übersetzung nötig oder Daten inkonsistent"
            )
        updates[rid] = old_value.replace(DE_MARKER, replacement)
    return updates


def generate_restore_sql(
    db_path: Path, rows: dict[int, sqlite3.Row], updates: dict[int, str]
) -> str:
    lines = [
        "-- Auto-generated restore script for Task #1317",
        f"-- Database: {db_path}",
        f"-- Generated: {datetime.now(timezone.utc).isoformat()}",
        "BEGIN;",
    ]
    for rid in sorted(TARGETS.keys()):
        old = rows[rid]["value"]
        lines.append(
            f"UPDATE languages_translations SET value = {json.dumps(old, ensure_ascii=False)}, "
            f"source = {json.dumps(rows[rid]['source'], ensure_ascii=False)}, "
            f"is_verified = {rows[rid]['is_verified']} "
            f"WHERE id = {rid};"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def apply_updates(
    conn, updates: dict[int, str], rows: dict[int, sqlite3.Row], apply: bool
) -> None:
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    for rid in sorted(TARGETS.keys()):
        lang, replacement = TARGETS[rid]
        old_value = rows[rid]["value"]
        new_value = updates[rid]
        count = old_value.count(DE_MARKER)
        print(f"[{rid} lang={lang}] {count}x '{DE_MARKER}' -> '{replacement}'")
        print("  OLD:", repr(old_value[:120]))
        print("  NEW:", repr(new_value[:120]))
        if apply:
            cur.execute(
                "UPDATE languages_translations SET value = ?, source = ?, "
                "is_verified = 1, updated_at = ? WHERE id = ?",
                (new_value, SOURCE, now, rid),
            )
            print(f"  -> updated {cur.rowcount} row(s)")


def assert_post_apply(conn) -> None:
    cur = conn.cursor()
    ids = list(TARGETS.keys())
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"SELECT id, language, value FROM languages_translations WHERE id IN ({placeholders})",
        ids,
    )
    for row in cur.fetchall():
        if DE_MARKER in row["value"]:
            raise AssertionError(
                f"Post-Apply DE-Marker-Assert: id={row['id']} lang={row['language']} "
                f"enthält immer noch '{DE_MARKER}'"
            )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path, conn = connect(args.db)
    print(f"Datenbank: {db_path}")

    # 1. Struktur-Assert
    ensure_schema(conn)
    print("Struktur-Assert OK")

    # 2. Verdict-Datei vorhanden (wird für source/prüfung mitgeführt)
    verdict = load_verdict(args.verdict)
    defect = next((v for v in verdict.values() if v.get("verdict") == "DEFECT"), None)
    if defect is None:
        raise AssertionError("Kein DEFECT-Eintrag im Verdict gefunden")
    print(f"Verdict DEFECT: id={defect.get('index')} -> row id={list(verdict.keys())[list(verdict.values()).index(defect)]}")

    # 3. Bijektion-Assert
    rows = assert_bijektion(conn)
    print("Bijektion-Assert OK")

    # 4. DE-Marker-Assert
    assert_de_marker_preserved(conn)
    print("DE-Marker-Assert OK")

    # 5. Neue Werte berechnen
    updates = compute_new_values(rows)

    # 6. Restore-SQL schreiben
    restore_path = db_path.with_suffix(".restore_1317.sql")
    restore_sql = generate_restore_sql(db_path, rows, updates)
    restore_path.write_text(restore_sql, encoding="utf-8")
    print(f"restore.sql geschrieben: {restore_path}")

    if not args.apply:
        print("\nDRY-RUN Modus – folgende Änderungen würden vorgenommen:")
        apply_updates(conn, updates, rows, apply=False)
        print("\nKeine Änderungen gespeichert. Führe mit --apply aus, um anzuwenden.")
        conn.close()
        return 0

    print("\nApply-Modus – schreibe Änderungen...")
    try:
        conn.execute("BEGIN")
        apply_updates(conn, updates, rows, apply=True)
        conn.commit()
        print("Commit OK")
    except Exception as exc:
        conn.rollback()
        print(f"Rollback wegen Fehler: {exc}", file=sys.stderr)
        raise

    assert_post_apply(conn)
    print("Post-Apply DE-Marker-Assert OK")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
