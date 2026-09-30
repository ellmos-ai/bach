# SPDX-License-Identifier: MIT
"""Read-only native DB prerequisite; no creation, migration or credential claim.

Profile bach-schema-sql-v1 supports exactly the source-bound schema.sql shape,
optionally with the canonical core/db.py _migrations provenance table.
Other legitimate migration epochs require their own declared profile.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROFILE = "bach-schema-sql-v1"
SCHEMA_SHA256 = "94a8a61981a2331e7272fc462d4574b9e4eb32d77bdc783fc0be263c8a8fea29"
CORE_DB_SHA256 = "579e07d8dabdbb373aa36c0e9f605f832f742328781f800f8de0601b1f7e993c"
# core/db.py baseline_migrations: provenance only, never freshness authority.
MIGRATIONS_DDL = """CREATE TABLE IF NOT EXISTS _migrations (
    id INTEGER PRIMARY KEY,
    filename TEXT UNIQUE NOT NULL,
    applied_at TEXT NOT NULL
)"""


@dataclass(frozen=True)
class NativeReadiness:
    ready: bool
    reason: str
    profile: str = PROFILE


class DBSyncReadinessError(FileNotFoundError):
    """A native operation was refused before preparing IO or a provider."""


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _structure(conn):
    objects = tuple(conn.execute(
        "SELECT type,name,tbl_name,sql FROM main.sqlite_schema "
        "WHERE substr(name, 1, 7) <> 'sqlite_' ORDER BY type,name"
    ))
    # Preserve quoted tokens; discard only whitespace and SQL comments.
    def tokens(sql):
        if sql is None:
            return None
        parts = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`[^`]*`|\[[^]]*\]|--[^\n]*|/\*[\s\S]*?\*/|\s+|[^\s]", sql)
        return tuple(p for p in parts if not p.isspace() and not p.startswith(("--", "/*")))
    objects = tuple((kind, name, table, tokens(sql))
                    for kind, name, table, sql in objects)
    listed = list(conn.execute("PRAGMA main.table_list"))
    if not any(row[0] == "main" and row[1] == "sqlite_schema" for row in listed):
        raise sqlite3.DatabaseError("table-list-unavailable")
    kinds = tuple(sorted(tuple(row[1:]) for row in listed
                         if row[0] == "main" and not row[1].startswith("sqlite_")))
    columns = tuple((name, tuple(conn.execute(f"PRAGMA main.table_xinfo({_quote(name)})")))
                    for name, *_ in kinds)
    return objects, kinds, columns


@lru_cache(maxsize=1)
def _profiles(schema_text):
    conn = sqlite3.connect(":memory:")
    try:
        # Only the pinned shipped source is executed, only in private memory.
        conn.executescript(schema_text)
        plain = _structure(conn)
        conn.execute(MIGRATIONS_DDL)
        return plain, _structure(conn)
    finally:
        conn.close()


def _file_state(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("linked-path")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size == 0:
        raise ValueError("invalid-file")
    # Literal names: metacharacters in database names are not glob syntax.
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError("sidecar-present")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def validate_native_db(db_path: Path, *, schema_path: Path | None = None) -> NativeReadiness:
    """Validate a stable, sidecar-free file without opening application/runtime.

    This measured prerequisite is not a writer-exclusion lease. It does not
    establish FTS credential coverage or authorize a native/shared cutover.
    """
    try:
        path = Path(db_path)
        if not path.is_absolute():
            return NativeReadiness(False, "absolute-db-path-required")
        before = _file_state(path)
        source = schema_path or Path(__file__).parent.parent / "data/schema/schema.sql"
        text = source.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != SCHEMA_SHA256:
            return NativeReadiness(False, "schema-source-pin-mismatch")
        core_text = (Path(__file__).parent.parent / "core/db.py").read_text(encoding="utf-8")
        if hashlib.sha256(core_text.encode("utf-8")).hexdigest() != CORE_DB_SHA256:
            return NativeReadiness(False, "core-source-pin-mismatch")
        expected = _profiles(text)
        # Refused sidecars are checked before using immutable. No recovery,
        # journal/SHM creation, migration, application imports or stamp writes.
        conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA user_version").fetchone() != (0,):
                return NativeReadiness(False, "unsupported-user-version")
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                return NativeReadiness(False, "integrity-check-failed")
            if _structure(conn) not in expected:
                return NativeReadiness(False, "unsupported-schema-shape")
            # Force view resolution as well; broken dependency names are errors.
            for (name,) in conn.execute("SELECT name FROM sqlite_schema WHERE type='view'"):
                conn.execute(f"SELECT * FROM {_quote(name)} LIMIT 0")
        finally:
            conn.close()
        if _file_state(path) != before:
            return NativeReadiness(False, "database-changed")
        return NativeReadiness(True, "ready")
    except ValueError as exc:
        return NativeReadiness(False, str(exc) if str(exc) in {
            "linked-path", "invalid-file", "sidecar-present"} else "invalid-db-path")
    except FileNotFoundError:
        return NativeReadiness(False, "missing-file")
    except (OSError, sqlite3.Error):
        # Do not expose data or arbitrary SQLite error messages.
        return NativeReadiness(False, "unreadable-or-unsafe-database")
