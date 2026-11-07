# BACH Adapter: llm-note (Notiz-Engine, ersetzt das Denkarium; PB-11, #3994)
"""Dünner BACH-Adapter auf `llm_note.store.NoteStore`.

Die Notizen liegen in `~/.bach/llm-note.db` (`BACH_LOCAL_DIR`), nie im Klon und nicht in `bach.db`.
`/api/notes*` spricht das llm-note-Vokabular (`note`/`logbook`); `/api/denkarium*` bleibt als Alias
mit unverändertem Antwortformat (`denkarium`/`logbuch`), bis alle Verbraucher umgestellt sind.
Solange die Altdaten (`denkarium_entries`) nicht migriert sind, bedient der Alias weiter den Altbestand
(`use_llm_note`), damit nach dem Rollout nichts "verschwindet".
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


def _store() -> Any:
    try:
        cls = load_llm_note_module().NoteStore
    except ImportError as exc:
        raise NotesUnavailable(f"llm-note nicht verfügbar: {exc}") from exc
    if not hasattr(cls, "import_entry"):
        raise NotesUnavailable("llm-note ohne Archivfunktion (>= PB-11 nötig)")
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


def use_llm_note(legacy_db: str | Path) -> bool:
    """True when `/api/denkarium` should be served from llm-note.

    llm-note DB exists -> yes (migrated or already in use). Otherwise only if the legacy table has no
    rows (fresh install). Unmigrated legacy rows keep the legacy path, so a rollout never hides notes.
    """
    if not _engine_ready():
        return False
    if notes_db_path().exists():
        return True
    try:
        conn = sqlite3.connect(f"file:{Path(legacy_db).as_posix()}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM denkarium_entries").fetchone()[0] == 0
        finally:
            conn.close()
    except sqlite3.Error:
        return True  # no legacy table / DB: nothing to protect


# --- llm-note vocabulary (`/api/notes`) -------------------------------------------------------

def list_notes(
    *,
    entry_type: str | None = None,
    category: str | None = None,
    limit: int = 50,
    search: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    store = _store()
    limit = max(0, min(int(limit), _MAX_LIMIT))
    if search:
        found = store.search(search, entry_type=entry_type, category=category, limit=limit,
                             include_archived=include_archived)
    else:
        found = store.list_entries(entry_type=entry_type, category=category, limit=limit,
                                   include_archived=include_archived)
    # ponytail: stats/categories from one capped scan (<= 1000 entries); use SQL aggregates if it ever grows
    everything = store.list_entries(include_archived=True, limit=_MAX_LIMIT)
    live = [e for e in everything if not e.is_archived]
    cats: dict[str, int] = {}
    for e in live:
        cats[e.category] = cats.get(e.category, 0) + 1
    return {
        "backend": "llm-note",
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
