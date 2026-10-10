# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Dry-run report: skills_hierarchy.json versus the table hierarchy_assignments.

Since the skills board stores assignments ONLY in the database table (one store), the old JSON file is no longer read or
written by the GUI. This report shows what the JSON still holds and where it differs from the table. It changes nothing:
the JSON is read, the database is opened read-only, and nothing is migrated automatically. Whether differences are adopted
is a decision of the user.

Usage: python skills_hierarchy_dryrun.py --json <skills_hierarchy.json> --db <database file> [--format text|json]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

KEY_TYPE = {"experts": "expert", "skills": "skill", "services": "service", "workflows": "workflow"}


def json_pairs(path: Path) -> dict:
    """{(parent, child): child_type} from the legacy JSON file; empty when the file is absent."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = {}
    for parent, lists in (data.get("assignments") or {}).items():
        for key, ids in (lists or {}).items():
            for child in ids or []:
                pairs[(parent, child)] = KEY_TYPE.get(key, key)
    return pairs


def table_pairs(db_file: Path) -> dict:
    """{(parent, child): child_type} for agent parents; the database is opened read-only."""
    connection = sqlite3.connect(db_file.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hierarchy_assignments'").fetchone()
        if not exists:
            return {}
        rows = connection.execute("SELECT parent_id, child_id, child_type FROM hierarchy_assignments WHERE parent_type = 'agent'").fetchall()
        return {(parent, child): child_type for parent, child, child_type in rows}
    finally:
        connection.close()


def compare(json_path: Path, db_file: Path) -> dict:
    left, right = json_pairs(json_path), table_pairs(db_file)
    only_json = sorted(set(left) - set(right))
    only_table = sorted(set(right) - set(left))
    type_diff = sorted(pair for pair in set(left) & set(right) if left[pair] != right[pair])
    return {
        "json_file_present": json_path.is_file(), "json_assignments": len(left), "table_assignments": len(right),
        "common": len(set(left) & set(right)) - len(type_diff),
        "only_in_json": [{"parent": p, "child": c, "type": left[(p, c)]} for p, c in only_json],
        "only_in_table": [{"parent": p, "child": c, "type": right[(p, c)]} for p, c in only_table],
        "type_differs": [{"parent": p, "child": c, "json": left[(p, c)], "table": right[(p, c)]} for p, c in type_diff],
        "identical": not only_json and not only_table and not type_diff,
        "changes_made": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    report = compare(args.json, args.db)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print("DRY-RUN, es wird nichts verändert oder übernommen.")
    print("JSON-Datei vorhanden:", report["json_file_present"], "| Zuordnungen JSON:", report["json_assignments"], "| Tabelle:", report["table_assignments"], "| gemeinsam:", report["common"])
    for title, key in (("Nur in der JSON-Datei", "only_in_json"), ("Nur in der Tabelle", "only_in_table"), ("Typ unterschiedlich", "type_differs")):
        print(title + " (" + str(len(report[key])) + "):")
        for entry in report[key]:
            print("  ", entry)
    print("Identisch:", report["identical"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
