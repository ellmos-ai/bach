# BACH Adapter: llm-note (Notiz-Engine, ersetzt das Denkarium; PB-11, #3994)
"""Dünner BACH-Adapter auf `llm_note.store.NoteStore`.

Die Notizen liegen in `~/.bach/llm-note.db` (`BACH_LOCAL_DIR`), nie im Klon und nicht in `bach.db`.
`/api/notes*` spricht das llm-note-Vokabular (`note`/`logbook`); `/api/denkarium*` bleibt als Alias
mit unverändertem Antwortformat (`denkarium`/`logbuch`), bis alle Verbraucher umgestellt sind.
Solange die Altdaten (`denkarium_entries`) nicht migriert sind (`use_llm_note`: die Migration hat noch keine Zeile
mit `legacy_id` geschrieben), bleiben Alias UND `/api/notes` auf der Alt-Tabelle; `GET /api/notes` meldet dann
`pending_migration`. Lesende Aufrufe legen `llm-note.db` nie an, erst das erste Schreiben nach der Migration.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from hub._services.ocean_stack_bridge import load_llm_note_module

_TO_DENKARIUM = {"note": "denkarium", "logbook": "logbuch"}
_MAX_LIMIT = 1000  # llm-note MAX_QUERY_LIMIT


class NotesUnavailable(RuntimeError):
    """llm-note is not installed or too old for PB-11 (no archive/import support)."""


def notes_db_path() -> Path:
    return Path(os.environ.get("BACH_LOCAL_DIR") or Path.home() / ".bach") / "llm-note.db"


def _store(create: bool = True) -> Any:
    """Open the store. Readers pass create=False: a missing DB yields None instead of a new empty file."""
    try:
        cls = load_llm_note_module().NoteStore
    except ImportError as exc:
        raise NotesUnavailable(f"llm-note nicht verfügbar: {exc}") from exc
    if not hasattr(cls, "import_entry"):
        raise NotesUnavailable("llm-note ohne Archivfunktion (>= PB-11 nötig)")
    if not create and not notes_db_path().exists():
        return None
    return cls(notes_db_path())


def _entry(e: Any) -> dict[str, Any]:
    return asdict(e)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _engine_ready() -> bool:
    try:
        return hasattr(load_llm_note_module().NoteStore, "import_entry")
    except ImportError:
        return False


def _ids(db: Path, sql: str) -> set[int]:
    """First column of a read-only query; missing file, table or column -> empty set. Never creates a file."""
    if not Path(db).exists():
        return set()
    try:
        conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
        try:
            return {int(r[0]) for r in conn.execute(sql) if r[0] is not None}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


def _legacy_ids(legacy_db: str | Path) -> set[int]:
    return _ids(Path(legacy_db), "SELECT id FROM denkarium_entries")


def _migrated_ids() -> set[int]:
    return _ids(notes_db_path(), "SELECT legacy_id FROM note_entries WHERE legacy_id IS NOT NULL")


def pending_count(legacy_db: str | Path) -> int:
    """Legacy rows that have no counterpart (`legacy_id`) in llm-note yet."""
    return len(_legacy_ids(legacy_db) - _migrated_ids())


def use_llm_note(legacy_db: str | Path) -> bool:
    """True when notes (and the `/api/denkarium` alias) are served from llm-note.

    Only after the migration has run: llm-note holds rows with a `legacy_id`, or it exists next to an empty
    legacy table (migration of an empty Denkarium). Before that the legacy table stays the single store, so a
    rollout never hides notes and a read never flips the backend. Legacy rows added after the migration do not
    flip it back: `pending_count` reports them and re-running the idempotent migration picks them up.
    """
    if not _engine_ready():
        return False
    return bool(_migrated_ids()) or (notes_db_path().exists() and not _legacy_ids(legacy_db))


# --- llm-note vocabulary (`/api/notes`) -------------------------------------------------------

def list_notes(
    *,
    entry_type: str | None = None,
    category: str | None = None,
    limit: int = 50,
    search: str | None = None,
    include_archived: bool = False,
    legacy_db: str | Path | None = None,
) -> dict[str, Any]:
    store = _store(create=False)
    pending = pending_count(legacy_db) if legacy_db else 0
    if store is None:  # nothing written yet: answer empty, create no file
        return _list_result("llm-note", [], [], pending)
    limit = max(0, min(int(limit), _MAX_LIMIT))
    if search:
        found = store.search(search, entry_type=entry_type, category=category, limit=limit,
                             include_archived=include_archived)
    else:
        found = store.list_entries(entry_type=entry_type, category=category, limit=limit,
                                   include_archived=include_archived)
    # ponytail: stats/categories from one capped scan (<= 1000 entries); use SQL aggregates if it ever grows
    everything = store.list_entries(include_archived=True, limit=_MAX_LIMIT)
    return _list_result("llm-note", found, everything, pending)


def _list_result(backend: str, found: list[Any], everything: list[Any], pending: int) -> dict[str, Any]:
    live = [e for e in everything if not e.is_archived]
    cats: dict[str, int] = {}
    for e in live:
        cats[e.category] = cats.get(e.category, 0) + 1
    return {
        "backend": backend,
        "pending_migration": pending > 0,
        "pending_count": pending,
        "entries": [_entry(e) for e in found],
        "count": len(found),
        "stats": {
            "total": len(everything),
            "archived": len(everything) - len(live),
            "logbook": sum(e.entry_type == "logbook" for e in live),
            "note": sum(e.entry_type == "note" for e in live),
        },
        "categories": [{"name": n, "count": c} for n, c in sorted(cats.items(), key=lambda kv: -kv[1])],
    }


def create_note(data: dict[str, Any]) -> dict[str, Any]:
    content = str(data.get("content") or "").strip()
    if not content:
        raise ValueError("Inhalt darf nicht leer sein")
    mood = data.get("mood")
    if mood in (0, "", None):
        mood = None
    elif not isinstance(mood, int) or isinstance(mood, bool) or not 1 <= mood <= 5:
        raise ValueError("mood muss 1-5 sein")
    return _entry(_store().write(
        content,
        entry_type=data.get("entry_type") or "note",
        category=data.get("category") or "note",
        title=data.get("title") or None,
        mood=mood,
        source=data.get("source") or "web",
    ))


def archive_note(entry_id: int, reason: str | None = None) -> dict[str, Any]:
    return _entry(_store().archive(entry_id, reason))


def unarchive_note(entry_id: int) -> dict[str, Any]:
    return _entry(_store().unarchive(entry_id))


def delete_note(entry_id: int) -> None:
    _store().delete(entry_id)


def get_note(entry_id: int) -> dict[str, Any]:
    return _entry(_store().get(entry_id))


def mark_promoted(entry_id: int, target: str, promoted_id: int) -> dict[str, Any]:
    return _entry(_store().promote(entry_id, target, promoted_id=promoted_id))


# --- CLI ids (bach denkarium ...): migrated entries keep their old number, new ones are "n<id>" ------------

def display_id(entry: dict[str, Any]) -> str:
    """The id a user types and reads: the legacy number for migrated entries, `n<llm-note id>` for new ones."""
    return str(entry["legacy_id"]) if entry.get("legacy_id") is not None else f"n{entry['id']}"


def resolve_display_id(token: str) -> int:
    """CLI id -> llm-note id. A plain number is a legacy id (no fallback to llm-note ids: they may collide)."""
    token = str(token).strip()
    entries = _store().list_entries(include_archived=True, limit=_MAX_LIMIT)
    if token[:1] in ("n", "N") and token[1:].isdigit():
        wanted = int(token[1:])
        found = [e.id for e in entries if e.id == wanted and e.legacy_id is None]
    elif token.isdigit():
        found = [e.id for e in entries if e.legacy_id == int(token)]
    else:
        raise ValueError("Ungueltige Entry-ID.")
    if not found:
        raise KeyError(f"Eintrag #{token} nicht gefunden.")
    return found[0]


# --- llm-note vocabulary on top of the legacy table (before the migration) ---------------------

_FROM_DENKARIUM = {"denkarium": "note", "logbuch": "logbook"}
_TO_LEGACY = {v: k for k, v in _FROM_DENKARIUM.items()}


def legacy_type(entry_type: str | None) -> str | None:
    """llm-note type -> legacy type (unknown values pass through)."""
    return _TO_LEGACY.get(entry_type, entry_type) if entry_type else entry_type


def from_denkarium_list(legacy: dict[str, Any], legacy_db: str | Path) -> dict[str, Any]:
    """Re-label a legacy list response in the llm-note vocabulary; flags the pending migration."""
    entries = []
    for e in legacy["entries"]:
        e = dict(e)
        e["entry_type"] = _FROM_DENKARIUM.get(e.get("entry_type") or "denkarium", e.get("entry_type"))
        e["is_archived"] = bool(e.get("is_archived"))
        entries.append(e)
    s = legacy["stats"]
    return {
        "backend": "denkarium-legacy",
        "pending_migration": True,
        "pending_count": pending_count(legacy_db),
        "entries": entries,
        "count": legacy["count"],
        "stats": {"total": s["total"], "archived": s["archived"], "logbook": s["logbuch"], "note": s["denkarium"]},
        "categories": legacy["categories"],
    }


# --- legacy `/api/denkarium` alias (response format unchanged) --------------------------------

_LEGACY_FIELDS = ("id", "entry_type", "title", "content", "category", "source", "mood", "promoted_to",
                  "promoted_id", "is_archived", "archived_reason", "archived_at", "created_at", "updated_at")


def _legacy_entry(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: e.get(k) for k in _LEGACY_FIELDS}
    out["entry_type"] = _TO_DENKARIUM.get(e["entry_type"], e["entry_type"])
    out["is_archived"] = int(bool(e.get("is_archived")))
    return out


def denkarium_list(entry_type: str | None = None, category: str | None = None, limit: int = 50,
                   search: str | None = None, exclude_archived: bool = True) -> dict[str, Any]:
    r = list_notes(entry_type=entry_type, category=category, limit=limit, search=search,
                   include_archived=not exclude_archived)
    s = r["stats"]
    return {
        "entries": [_legacy_entry(e) for e in r["entries"]],
        "count": r["count"],
        "stats": {"total": s["total"], "archived": s["archived"], "logbuch": s["logbook"],
                  "denkarium": s["note"]},
        "categories": r["categories"],
    }


def denkarium_create(data: dict[str, Any]) -> dict[str, Any]:
    entry_type = data.get("entry_type") or "denkarium"
    title = data.get("title")
    if entry_type in ("logbuch", "logbook") and not title:
        title = f"Sternzeit {_now()}"
    entry = create_note({
        "content": data.get("content", ""),
        "entry_type": entry_type,
        "category": data.get("category") or "notiz",
        "title": title,
        "mood": data.get("mood"),
        "source": data.get("source") or "web",
    })
    return {"ok": True, "id": entry["id"], "message": f"Eintrag #{entry['id']} gespeichert"}


def denkarium_archive(entry_id: int, reason: str) -> dict[str, Any]:
    e = archive_note(entry_id, reason)
    return {"success": True, "entry_id": e["id"], "action": "archived", "reason": reason,
            "archived_at": e["archived_at"],
            "message": f"Eintrag #{e['id']} reversibel archiviert ({reason}). Kann jederzeit wiederhergestellt werden."}


def denkarium_unarchive(entry_id: int) -> dict[str, Any]:
    e = unarchive_note(entry_id)
    return {"success": True, "entry_id": e["id"], "action": "unarchived",
            "message": f"Eintrag #{e['id']} erfolgreich im aktiven Notizbuch wiederhergestellt."}
