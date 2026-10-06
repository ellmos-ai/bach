"""Read-only, source-separated memory search for the Ocean GUI.

Schemas follow the existing MemoryHooker GardenerBackend and UsmcBackend.
Connections use SQLite mode=ro; neither this module nor its callers migrate DBs.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _source(name: str, path: Path, tables: tuple[str, ...], query: str, limit: int) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "source": name, "availability": "unavailable", "checked_at": checked_at,
        "count": None, "results": [], "error": "database_missing",
    }
    if not path.is_file():
        return result
    try:
        with closing(_db(path)) as conn:
            present = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not set(tables).issubset(present):
                result["error"] = "schema_unavailable"
                return result
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = []
            if name == "bach":
                rows = conn.execute(
                    "SELECT id, category, key, value FROM memory_facts "
                    "WHERE key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\' "
                    "ORDER BY id DESC LIMIT ?", (pattern, pattern, limit),
                ).fetchall()
                for row in rows:
                    result["results"].append({
                        "id": f"bach:fact:{row['id']}", "source": "bach", "type": "fact",
                        "title": row["key"], "snippet": str(row["value"] or "")[:240],
                        "category": row["category"],
                    })
            elif name.startswith("gardener:"):
                rows = conn.execute(
                    "SELECT id, type, name, content FROM everything "
                    "WHERE name LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' "
                    "ORDER BY updated DESC LIMIT ?", (pattern, pattern, limit),
                ).fetchall()
                for row in rows:
                    result["results"].append({
                        "id": f"{name}:{row['id']}", "source": name, "type": row["type"],
                        "title": row["name"], "snippet": str(row["content"] or "")[:240],
                    })
            else:
                specs = (
                    ("usmc_facts", "fact", "key", "value", "category"),
                    ("usmc_lessons", "lesson", "title", "solution", "category"),
                    ("usmc_working", "working", "type", "content", "priority"),
                )
                for table, kind, title_col, text_col, extra_col in specs:
                    remaining = limit - len(result["results"])
                    if remaining <= 0:
                        break
                    active = " AND is_active = 1" if kind != "fact" else ""
                    rows = conn.execute(
                        f"SELECT id, {title_col}, {text_col}, {extra_col} FROM {table} "
                        f"WHERE ({title_col} LIKE ? ESCAPE '\\' OR {text_col} LIKE ? ESCAPE '\\'){active} "
                        f"ORDER BY id DESC LIMIT ?", (pattern, pattern, remaining),
                    ).fetchall()
                    for row in rows:
                        result["results"].append({
                            "id": f"usmc:{kind}:{row['id']}", "source": "usmc", "type": kind,
                            "title": str(row[title_col]), "snippet": str(row[text_col] or "")[:240],
                            "category": row[extra_col] if kind != "working" else None,
                        })
        result.update(availability="available", count=len(result["results"]), error=None)
    except (OSError, sqlite3.Error):
        result.update(availability="unavailable", count=None, results=[], error="database_read_failed")
    return result


def search_memory(query: str, limit: int, bach_db: Path) -> dict[str, Any]:
    gardener_dir = Path(os.path.expandvars(os.path.expanduser(
        os.environ.get("GARDENER_DATA", "~/.gardener")
    )))
    usmc_db = Path(os.path.expandvars(os.path.expanduser(
        os.environ.get("USMC_DB_PATH", "~/.usmc/usmc_memory.db")
    )))
    sources = [
        _source("bach", bach_db, ("memory_facts",), query, limit),
        _source("gardener:user", gardener_dir / "user.db", ("everything",), query, limit),
        _source("gardener:system", gardener_dir / "gardener.db", ("everything",), query, limit),
        _source("usmc", usmc_db, ("usmc_facts", "usmc_lessons", "usmc_working"), query, limit),
    ]
    return {
        "query": query, "limit": limit,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "availability": "available" if all(s["availability"] == "available" for s in sources)
                        else "partial" if any(s["availability"] == "available" for s in sources)
                        else "unavailable",
        "sources": sources,
        "results": [hit for source in sources for hit in source["results"]],
    }
