"""PB-11 (#3994): notes adapter on top of llm-note, `/api/notes` and the `/api/denkarium` alias."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from hub._services import notes_adapter
from hub._services.ocean_stack_bridge import load_llm_note_module


@pytest.fixture(autouse=True)
def notes_env(tmp_path, monkeypatch):
    """Isolated DB location; skip when the installed llm-note predates PB-11."""
    monkeypatch.setenv("BACH_LOCAL_DIR", str(tmp_path / "local"))
    try:
        mod = load_llm_note_module()
    except ImportError:
        pytest.skip("llm-note checkout not present")
    if not hasattr(mod.NoteStore, "import_entry"):
        pytest.skip("llm-note without archive/import support (PB-11 not merged in the sibling checkout)")
    return tmp_path


def test_db_lives_outside_the_repo(notes_env):
    path = notes_adapter.notes_db_path()
    assert path == notes_env / "local" / "llm-note.db"


def test_create_list_archive_unarchive_delete_roundtrip():
    created = notes_adapter.create_note({"content": "hello", "category": "idee"})
    assert created["id"] >= 1 and created["entry_type"] == "note"

    listing = notes_adapter.list_notes()
    assert [e["content"] for e in listing["entries"]] == ["hello"]
    assert listing["stats"] == {"total": 1, "archived": 0, "logbook": 0, "note": 1}
    assert listing["categories"] == [{"name": "idee", "count": 1}]

    notes_adapter.archive_note(created["id"], "weg")
    assert notes_adapter.list_notes()["entries"] == []
    both = notes_adapter.list_notes(include_archived=True)
    assert both["entries"][0]["is_archived"] is True and both["stats"]["archived"] == 1

    notes_adapter.unarchive_note(created["id"])
    assert len(notes_adapter.list_notes()["entries"]) == 1

    notes_adapter.delete_note(created["id"])
    assert notes_adapter.list_notes()["count"] == 0


def test_empty_content_is_rejected_and_unknown_id_raises_keyerror():
    with pytest.raises(ValueError):
        notes_adapter.create_note({"content": "   "})
    with pytest.raises(KeyError):
        notes_adapter.archive_note(999)


def test_search_and_type_filter():
    notes_adapter.create_note({"content": "alpha thought"})
    notes_adapter.create_note({"content": "alpha log", "entry_type": "logbook"})
    assert notes_adapter.list_notes(search="alpha")["count"] == 2
    only_logs = notes_adapter.list_notes(entry_type="logbook")
    assert [e["content"] for e in only_logs["entries"]] == ["alpha log"]


def test_denkarium_view_keeps_legacy_response_format():
    notes_adapter.create_note({"content": "gedanke"})
    notes_adapter.create_note({"content": "logeintrag", "entry_type": "logbuch"})
    view = notes_adapter.denkarium_list(entry_type="logbuch")
    assert set(view) == {"entries", "count", "stats", "categories"}
    assert set(view["stats"]) == {"total", "archived", "logbuch", "denkarium"}
    assert view["stats"] == {"total": 2, "archived": 0, "logbuch": 1, "denkarium": 1}
    entry = view["entries"][0]
    assert entry["entry_type"] == "logbuch"
    assert {"id", "title", "content", "category", "source", "mood", "promoted_to", "promoted_id",
            "is_archived", "archived_reason", "archived_at", "created_at", "updated_at"} <= set(entry)


def test_denkarium_create_defaults_match_legacy_route():
    result = notes_adapter.denkarium_create({"content": "x", "entry_type": "logbuch"})
    assert result["ok"] is True and result["message"].startswith("Eintrag #")
    entry = notes_adapter.list_notes()["entries"][0]
    assert entry["entry_type"] == "logbook" and entry["title"].startswith("Sternzeit ")
    assert entry["category"] == "notiz" and entry["source"] == "web"


def _legacy_db(path: Path, rows: int) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE denkarium_entries (id INTEGER PRIMARY KEY, content TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO denkarium_entries (content) VALUES (?)", (f"c{i}",))
    conn.commit()
    conn.close()
    return path


def test_use_llm_note_falls_back_to_legacy_until_migrated(notes_env):
    legacy = _legacy_db(notes_env / "legacy.db", rows=2)
    assert notes_adapter.use_llm_note(legacy) is False  # legacy rows, nothing migrated yet
    notes_adapter.create_note({"content": "a bare llm-note row is no migration"})
    assert notes_adapter.use_llm_note(legacy) is False
    load_llm_note_module().NoteStore(notes_adapter.notes_db_path()).import_entry("alt", legacy_id=1)
    assert notes_adapter.use_llm_note(legacy) is True  # the migration marker: a row with legacy_id


def test_use_llm_note_needs_the_migration_even_on_an_empty_denkarium(notes_env):
    empty = _legacy_db(notes_env / "empty.db", rows=0)
    assert notes_adapter.use_llm_note(notes_env / "missing.db") is False
    assert notes_adapter.use_llm_note(empty) is False  # nothing migrated, no llm-note db yet
    notes_adapter.create_note({"content": "migration of an empty Denkarium creates the db"})
    assert notes_adapter.use_llm_note(empty) is True


def test_mark_promoted_records_target(notes_env):
    entry = notes_adapter.create_note({"content": "p"})
    promoted = notes_adapter.mark_promoted(entry["id"], "task", 77)
    assert promoted["promoted_to"] == "task" and promoted["promoted_id"] == 77


def test_gui_notes_routes_end_to_end(monkeypatch, notes_env):
    server = _server_with_legacy(monkeypatch, notes_env, ["alt"])
    _migrate(server)
    created = asyncio.run(server.notes_create(_FakeRequest({"content": "via route", "entry_type": "logbook"})))
    assert created["entry"]["entry_type"] == "logbook"
    listing = asyncio.run(server.notes_list())
    assert listing["count"] == 2 and listing["backend"] == "llm-note"
    asyncio.run(server.notes_archive(created["entry"]["id"], _FakeRequest({"reason": "r"})))
    assert asyncio.run(server.notes_list())["count"] == 1
    assert asyncio.run(server.notes_list(include_archived=True))["count"] == 2
    asyncio.run(server.notes_unarchive(created["entry"]["id"]))
    asyncio.run(server.notes_delete(created["entry"]["id"]))
    assert asyncio.run(server.notes_list(include_archived=True))["count"] == 1


class _FakeRequest:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


def _server_with_legacy(monkeypatch, tmp_path, rows):
    from gui import server

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE denkarium_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, entry_type TEXT, title TEXT,"
        " content TEXT, category TEXT, source TEXT, mood INTEGER, promoted_to TEXT, promoted_id INTEGER,"
        " created_at TEXT, updated_at TEXT)"
    )
    for text in rows:
        conn.execute("INSERT INTO denkarium_entries (entry_type, content, category, created_at)"
                     " VALUES ('denkarium', ?, 'notiz', '2026-02-19 08:00')", (text,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "USER_DB", db)
    return server


def test_denkarium_alias_serves_legacy_rows_until_migration(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1", "alt-2"])
    result = asyncio.run(server.denkarium_list())
    assert sorted(e["content"] for e in result["entries"]) == ["alt-1", "alt-2"]
    assert not notes_adapter.notes_db_path().exists()  # reading must not create the llm-note DB


def test_denkarium_alias_switches_to_llm_note_after_migration(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, [])
    _migrate(server)  # empty Denkarium: creates the llm-note db, which is the marker
    created = asyncio.run(server.denkarium_create(_FakeRequest({"content": "neu", "category": "test"})))
    assert created["ok"] is True
    result = asyncio.run(server.denkarium_list())
    assert set(result) == {"entries", "count", "stats", "categories"}
    assert [e["content"] for e in result["entries"]] == ["neu"]
    assert result["stats"] == {"total": 1, "archived": 0, "logbuch": 0, "denkarium": 1}
    archived = asyncio.run(server.denkarium_archive_direct(created["id"], _FakeRequest({"reason": "x"})))
    assert archived["action"] == "archived"
    assert asyncio.run(server.denkarium_list())["count"] == 0
    assert asyncio.run(server.denkarium_list(exclude_archived=False))["count"] == 1
    assert asyncio.run(server.denkarium_unarchive_direct(created["id"]))["action"] == "unarchived"
    assert asyncio.run(server.denkarium_delete(created["id"])) == {"ok": True}


def test_notes_routes_map_errors_to_http_status(monkeypatch, tmp_path):
    from fastapi import HTTPException

    server = _server_with_legacy(monkeypatch, tmp_path, [])
    _migrate(server)
    with pytest.raises(HTTPException) as bad:
        asyncio.run(server.notes_create(_FakeRequest({"content": ""})))
    assert bad.value.status_code == 400
    with pytest.raises(HTTPException) as missing:
        asyncio.run(server.notes_unarchive(4242))
    assert missing.value.status_code == 404


# --- R2 review (bach#668): reads never create the DB, the alias stays on the legacy table until migrated ------

def _migrate(server):
    from llm_note.migrate_denkarium import migrate

    return migrate(server.USER_DB, notes_adapter.notes_db_path(), apply=True,
                   snapshot_dir=notes_adapter.notes_db_path().parent / "snap")


def test_reading_notes_never_creates_the_llm_note_db(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, [])
    assert notes_adapter.list_notes()["entries"] == []
    asyncio.run(server.notes_list())
    asyncio.run(server.denkarium_list())
    assert not notes_adapter.notes_db_path().exists()


def test_get_notes_before_migration_keeps_legacy_rows_visible(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1", "alt-2"])
    notes = asyncio.run(server.notes_list())
    assert notes["pending_migration"] is True and notes["backend"] == "denkarium-legacy"
    assert sorted(e["content"] for e in notes["entries"]) == ["alt-1", "alt-2"]
    assert {e["entry_type"] for e in notes["entries"]} == {"note"}  # llm-note vocabulary
    assert notes["stats"]["note"] == 2
    assert asyncio.run(server.denkarium_list())["count"] == 2  # alias did not flip
    assert not notes_adapter.notes_db_path().exists()


def test_writes_before_migration_go_to_the_legacy_table_only(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1"])
    created = asyncio.run(server.notes_create(_FakeRequest({"content": "neu", "entry_type": "logbook", "title": "T"})))
    assert created["ok"] is True and created["pending_migration"] is True
    legacy = asyncio.run(server.denkarium_list())
    assert legacy["count"] == 2 and legacy["stats"]["logbuch"] == 1
    new_id = created["entry"]["id"]
    asyncio.run(server.notes_archive(new_id, _FakeRequest({"reason": "r"})))
    assert asyncio.run(server.notes_list())["count"] == 1
    assert asyncio.run(server.notes_list(include_archived=True))["count"] == 2
    asyncio.run(server.notes_unarchive(new_id))
    asyncio.run(server.notes_delete(new_id))
    assert asyncio.run(server.notes_list())["count"] == 1
    assert not notes_adapter.notes_db_path().exists()  # no second store


def test_after_migration_both_routes_show_the_same_notes_with_original_dates(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1", "alt-2"])
    assert _migrate(server)["target_count"] == 2
    notes = asyncio.run(server.notes_list())
    assert notes["backend"] == "llm-note" and notes["pending_migration"] is False
    assert sorted(e["content"] for e in notes["entries"]) == ["alt-1", "alt-2"]
    assert {e["created_at"] for e in notes["entries"]} == {"2026-02-19 08:00"}
    alias = asyncio.run(server.denkarium_list())
    assert alias["count"] == 2 and alias["entries"][0]["entry_type"] == "denkarium"


def test_legacy_straggler_after_migration_is_reported_not_hidden(monkeypatch, tmp_path):
    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1"])
    _migrate(server)
    conn = sqlite3.connect(server.USER_DB)
    conn.execute("INSERT INTO denkarium_entries (entry_type, content, category, created_at)"
                 " VALUES ('denkarium', 'spaet', 'notiz', '2026-03-01 10:00')")
    conn.commit()
    conn.close()
    notes = asyncio.run(server.notes_list())
    assert notes["backend"] == "llm-note"  # stays on llm-note, no flip back
    assert notes["pending_migration"] is True and notes["pending_count"] == 1
    _migrate(server)  # idempotent re-run picks it up
    assert asyncio.run(server.notes_list())["pending_migration"] is False


def test_denkarium_handler_writes_follow_the_active_store(monkeypatch, tmp_path):
    from hub.denkarium import DenkariumHandler

    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1"])
    handler = DenkariumHandler(tmp_path)
    handler.db_path = server.USER_DB
    ok, _ = handler.handle("write", ["vor der Migration"])
    assert ok and asyncio.run(server.denkarium_list())["count"] == 2
    assert not notes_adapter.notes_db_path().exists()
    _migrate(server)
    ok, text = handler.handle("write", ["nach der Migration", "--type=logbuch"])
    ok2, _ = handler.handle("brainstorm", ["Thema"])
    assert ok and ok2 and "gespeichert" in text
    contents = [e["content"] for e in notes_adapter.list_notes(include_archived=True)["entries"]]
    assert any("nach der Migration" in c for c in contents) and any("Thema" in c for c in contents)
    conn = sqlite3.connect(server.USER_DB)
    assert conn.execute("SELECT COUNT(*) FROM denkarium_entries").fetchone()[0] == 2  # no new legacy rows
    conn.close()


# --- R2 follow-up: every CLI/chat operation follows the same migration marker ------------------------------

def _cli_env(monkeypatch, tmp_path):
    """Legacy ids 2 and 3 (id 1 deleted) so that llm-note ids (1, 2) differ from the legacy ids."""
    from hub.denkarium import DenkariumHandler

    server = _server_with_legacy(monkeypatch, tmp_path, ["alt-1", "alt-2", "alt-3"])
    conn = sqlite3.connect(server.USER_DB)
    conn.execute("DELETE FROM denkarium_entries WHERE id = 1")
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT,"
                 " status TEXT, priority INTEGER, assigned_to TEXT, dist_type INTEGER)")
    conn.commit()
    conn.close()
    handler = DenkariumHandler(tmp_path)
    handler.db_path = server.USER_DB
    return server, handler


def test_cli_read_search_stats_categories_find_new_entries_after_migration(monkeypatch, tmp_path):
    server, handler = _cli_env(monkeypatch, tmp_path)
    _migrate(server)
    ok, text = handler.handle("write", ["frisch geschrieben", "--cat=idee"])
    assert ok and "#n" in text  # new entries carry the llm-note id with an n prefix
    assert "frisch geschrieben" in handler.handle("read", [])[1]
    assert "frisch geschrieben" in handler.handle("search", ["frisch"])[1]
    assert "idee" in handler.handle("categories", [])[1]
    stats = handler.handle("stats", [])[1]
    assert "Gesamt:    3" in stats  # alt-2, alt-3 and the new entry, not the legacy table
    # migrated entries keep their old numbers in the listing
    listing = handler.handle("read", ["--limit=10"])[1]
    assert "#2 " in listing and "#3 " in listing


def test_cli_promote_with_an_old_id_hits_the_same_note_as_before(monkeypatch, tmp_path):
    server, handler = _cli_env(monkeypatch, tmp_path)
    _migrate(server)
    ok, text = handler.handle("promote", ["2", "task"])  # old id 2 = "alt-2" (llm-note id 1)
    assert ok and "#2" in text
    by_legacy = {e["legacy_id"]: e for e in notes_adapter.list_notes(include_archived=True)["entries"]}
    assert by_legacy[2]["promoted_to"] == "task" and by_legacy[3]["promoted_to"] is None
    conn = sqlite3.connect(server.USER_DB)
    assert conn.execute("SELECT description FROM tasks").fetchall() == [("alt-2",)]
    conn.close()
    assert not handler.handle("promote", ["999", "task"])[0]  # unknown old id -> error, no fallback to llm id 999


def test_cli_promote_of_a_new_entry_uses_the_n_prefixed_id(monkeypatch, tmp_path):
    server, handler = _cli_env(monkeypatch, tmp_path)
    _migrate(server)
    _, text = handler.handle("write", ["neu und befoerdert"])
    new_id = text.split("#")[1].split()[0]  # e.g. "n3"
    assert new_id.startswith("n")
    ok, message = handler.handle("promote", [new_id, "task"])
    assert ok, message
    conn = sqlite3.connect(server.USER_DB)
    assert conn.execute("SELECT description FROM tasks").fetchall() == [("neu und befoerdert",)]
    conn.close()
    assert handler.handle("promote", ["2", "wiki", ], dry_run=True)[1].startswith("[DRY-RUN]")


def test_cli_operations_stay_on_the_legacy_table_before_the_migration(monkeypatch, tmp_path):
    server, handler = _cli_env(monkeypatch, tmp_path)
    assert "alt-2" in handler.handle("read", [])[1]
    assert "Gesamt:    2" in handler.handle("stats", [])[1]
    assert handler.handle("promote", ["2", "task"])[0] is True
    assert not notes_adapter.notes_db_path().exists()
