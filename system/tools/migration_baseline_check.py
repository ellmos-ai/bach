#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Welche ungebuchten Migrationen einer Bestands-DB sind schon wirksam?

Nur lesend gegenueber der Quell-DB. Jede in ``_migrations`` fehlende Migration
laeuft in Dateireihenfolge auf einer KOPIE (SQLite-Backup-API) in einem eigenen
Prozess; ``BACH_DB`` zeigt dabei auf die Kopie, der Migrationsordner liegt
ebenfalls kopiert im Temp-Verzeichnis (manche Migrationen bauen Pfade relativ
zu ``__file__``). Vorher/nachher werden Schema und Zeilenzahlen verglichen:

    wirksam  -- keine Aenderung: Effekt ist schon da, darf gestempelt werden
    fehlt    -- Aenderung: Effekt fehlt, Migration muss angewandt werden
    fehler   -- Migration bricht ab: Handarbeit
    unklar   -- Kopie unveraendert, aber die Migration schrieb eine andere Datei

Anlass: T-20260926-598278998 (Laptop-bach.db mit 42 ungebuchten Migrationen;
ein blindes ``bach update migrations baseline`` haette fehlende Effekte als
angewandt gebucht). Aufruf:

    python tools/migration_baseline_check.py --db ~/.bach/bach.db [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = SYSTEM_ROOT / "data" / "schema" / "migrations"

_RUNNER = r"""
import importlib.util, sqlite3, sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from core.db import dispatch_py_migration
mig, db = Path(sys.argv[1]), sys.argv[2]
conn = sqlite3.connect(db)
try:
    if mig.suffix == ".sql":
        conn.executescript(mig.read_text(encoding="utf-8"))
    else:
        spec = importlib.util.spec_from_file_location("migration_" + mig.stem, mig)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dispatch_py_migration(module, conn, Path(db))
    conn.commit()
finally:
    conn.close()
"""


def available(migrations_dir: Path) -> list[str]:
    """Wie hub/update.py _get_available_migrations."""
    return sorted(f.name for f in migrations_dir.iterdir()
                  if f.suffix in (".py", ".sql") and not f.name.startswith("_"))


def booked(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in conn.execute("SELECT filename FROM _migrations")}
    except sqlite3.OperationalError:
        return set()


def snapshot(db: Path) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        objects = {(t, n): " ".join((s or "").split())
                   for t, n, s in conn.execute(
                       "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        rows, columns = {}, {}
        for (kind, name) in objects:
            if kind == "table":
                try:
                    rows[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                except sqlite3.Error:
                    rows[name] = None
                columns[name] = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
        return {"objects": objects, "rows": rows, "columns": columns}
    finally:
        conn.close()


def diff(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """(alle Aenderungen, destruktive Aenderungen). Destruktiv = entferntes
    Objekt, entfernte Spalte einer weiter bestehenden Tabelle oder gesunkene
    Zeilenzahl -- alles kann Daten kosten."""
    changes, destructive = [], []
    for key in sorted(set(before["objects"]) | set(after["objects"])):
        kind, name = key
        if key not in before["objects"]:
            changes.append(f"+{kind} {name}")
        elif key not in after["objects"]:
            changes.append(f"-{kind} {name}")
            destructive.append(f"-{kind} {name}")
        elif before["objects"][key] != after["objects"][key]:
            changes.append(f"~{kind} {name}")
    for name in sorted(set(before["columns"]) & set(after["columns"])):
        for column in before["columns"][name]:
            if column not in after["columns"][name]:
                changes.append(f"-column {name}.{column}")
                destructive.append(f"-column {name}.{column}")
    for name in sorted(set(before["rows"]) & set(after["rows"])):
        old, new = before["rows"][name], after["rows"][name]
        if old != new:
            changes.append(f"rows {name}: {old} -> {new}")
            if isinstance(old, int) and isinstance(new, int) and new < old:
                destructive.append(f"rows {name}: {old} -> {new}")
    return changes, destructive


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _other_dbs(root: Path, copy: Path) -> set[Path]:
    return {p for p in root.rglob("*.db") if p != copy}


def check(source: Path, migrations_dir: Path = MIGRATIONS, system_root: Path = SYSTEM_ROOT,
          timeout: float = 300) -> dict:
    source_hash = _sha256(source)
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        pending = [m for m in available(migrations_dir) if m not in booked(src)]
        with tempfile.TemporaryDirectory(prefix="bach-baseline-") as tmp:
            root = Path(tmp)
            work_schema = root / "system" / "data" / "schema"
            shutil.copytree(migrations_dir.parent, work_schema)
            work_migrations = work_schema / migrations_dir.name
            copy = root / "copy.db"
            dst = sqlite3.connect(copy)
            src.backup(dst)
            dst.close()
            env = {**os.environ, "BACH_DB": str(copy), "PYTHONIOENCODING": "utf-8"}
            results = []
            for name in pending:
                before, other_before = snapshot(copy), _other_dbs(root, copy)
                try:
                    proc = subprocess.run(
                        [sys.executable, "-c", _RUNNER, str(work_migrations / name), str(copy),
                         str(system_root)],
                        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=timeout, check=False,
                    )
                except subprocess.TimeoutExpired:
                    results.append({"migration": name, "status": "fehler",
                                    "detail": f"Timeout nach {timeout:g} s", "destructive": []})
                    continue
                after = snapshot(copy)
                changes, destructive = diff(before, after)
                if proc.returncode != 0:
                    status = "fehler"
                    detail = (proc.stderr.strip().splitlines() or ["?"])[-1]
                    if "duplicate column name" in detail:
                        detail += (" -- Spalte existiert schon; nicht idempotent, der Rest der "
                                   "Datei lief nicht: einzeln pruefen")
                elif changes:
                    status, detail = "fehlt", changes
                elif _other_dbs(root, copy) - other_before:
                    status = "unklar"
                    detail = "schrieb eine andere Datei statt BACH_DB"
                else:
                    status, detail = "wirksam", []
                results.append({"migration": name, "status": status, "detail": detail,
                                "destructive": destructive})
    finally:
        src.close()
    return {
        "db": str(source),
        "pending": len(pending),
        "results": results,
        "source_unchanged": _sha256(source) == source_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").partition("\n")[0] or None)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--migrations-dir", type=Path, default=MIGRATIONS)
    args = parser.parse_args(argv)
    report = check(args.db.expanduser(), migrations_dir=args.migrations_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    print(f"DB: {report['db']}  ungebucht: {report['pending']}  "
          f"Quelle unveraendert: {report['source_unchanged']}")
    for status in ("wirksam", "fehlt", "unklar", "fehler"):
        group = [r for r in report["results"] if r["status"] == status]
        print(f"\n== {status} ({len(group)})")
        for r in group:
            detail = r["detail"]
            if isinstance(detail, list):
                # Loeschungen immer vollstaendig zeigen, nur den Rest kuerzen.
                # Destruktives (Drops, Zeilen-Abnahmen) immer vollstaendig.
                rest = [d for d in detail if d not in r["destructive"]]
                shown = r["destructive"] + rest[:6]
                detail = "; ".join(shown) + (" ..." if len(rest) > 6 else "")
            print(f"  {r['migration']}" + (f"  -- {detail}" if detail else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
