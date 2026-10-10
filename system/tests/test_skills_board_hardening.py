# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Hardening of the legacy skills board API (P-1963-P1).

- PUT /api/skills-board/item-file is gone (410): no file write through this path any more
- GET /api/skills-board/item-file never returns an absolute path
- PUT /api/skills-board/hierarchy validates strictly and writes ONLY hierarchy_assignments (one store, no JSON file)
- tools/migration/skills_hierarchy_dryrun.py reports JSON-versus-table differences without changing anything
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

SYSTEM_ROOT = Path(__file__).parent.parent
for entry in (SYSTEM_ROOT, SYSTEM_ROOT / "tools" / "migration", Path(__file__).parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from gui import server  # noqa: E402
from test_gui_skills_board import _seed_skills_board_db  # noqa: E402
import skills_hierarchy_dryrun as dryrun  # noqa: E402

AUTH = {"Authorization": "Bearer board-test"}


@pytest.fixture()
def board(tmp_path, monkeypatch):
    db_path = tmp_path / "board.sqlite"
    _seed_skills_board_db(db_path)
    conn = sqlite3.connect(db_path)
    # second agent, an expert-parent row and a row whose child is unknown to the hierarchy: none of these may be touched
    conn.execute("INSERT INTO hierarchy_items (id, type, name, description, status) VALUES ('skill-two', 'skill', 'Skill Zwei', 'zweiter Skill', 'active')")
    conn.execute("INSERT INTO bach_agents (id, name, display_name, description, skill_path, is_active, priority) VALUES (2, 'zweiter', 'Zwei', 'x', 'a', 1, 10)")
    conn.execute("INSERT INTO hierarchy_assignments (parent_id, parent_type, child_id, child_type, assignment_order) VALUES ('zweiter', 'agent', 'skill-bugfix', 'skill', 0)")
    conn.execute("INSERT INTO hierarchy_assignments (parent_id, parent_type, child_id, child_type, assignment_order) VALUES ('bueroassistent', 'agent', 'ghost-child', 'skill', 0)")
    conn.execute("INSERT INTO hierarchy_assignments (parent_id, parent_type, child_id, child_type, assignment_order) VALUES ('steuer-agent', 'expert', 'skill-bugfix', 'skill', 0)")
    conn.commit()
    conn.close()

    def get_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    json_path = tmp_path / "skills_hierarchy.json"
    system_root = tmp_path / "system"
    (system_root / "agents" / "bueroassistent").mkdir(parents=True)
    (system_root / "agents" / "bueroassistent" / "SKILL.md").write_text("# Bueroassistent\n", encoding="utf-8")
    monkeypatch.setattr(server, "get_bach_db", get_db)
    monkeypatch.setattr(server, "SKILLS_HIERARCHY_FILE", json_path)
    monkeypatch.setattr(server, "BACH_DIR", system_root)
    monkeypatch.setattr(server, "AGENTS_DIR", system_root / "agents")
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "board-test" else None)
    client = TestClient(server.app)

    class Board:
        pass

    b = Board()
    b.client, b.db_path, b.json_path, b.root, b.get_db = client, db_path, json_path, system_root, get_db
    b.put = lambda payload, **kw: client.put("/api/skills-board/hierarchy", headers=AUTH, json=payload, **kw)
    b.rows = lambda: [tuple(r) for r in get_db().execute(
        "SELECT parent_id, parent_type, child_id, child_type, assignment_order FROM hierarchy_assignments ORDER BY parent_id, parent_type, child_id")]
    return b


def assignments(parent="bueroassistent", **lists):
    base = {"experts": [], "skills": [], "services": [], "workflows": []}
    base.update(lists)
    return {"items": {}, "assignments": {parent: base}}


# ---------------------------------------------------------------- item-file

@pytest.mark.parametrize("name", ["evil.py", "notes.md", "plain.txt"])
def test_item_file_put_is_gone_and_writes_nothing(board, name):
    target = board.root / name
    response = board.client.put("/api/skills-board/item-file", headers=AUTH, json={"path": name, "content": "print('x')"})
    assert response.status_code == 410
    assert "/api/capabilities/skills/{id}/source" in response.json()["detail"]
    assert not target.exists()


def test_item_file_put_is_gone_for_any_body_and_still_needs_a_device_token(board):
    assert board.client.put("/api/skills-board/item-file", headers=AUTH, json={"path": "../../etc/passwd", "content": "x"}).status_code == 410
    assert board.client.put("/api/skills-board/item-file", headers=AUTH, data="not json").status_code == 410
    assert board.client.put("/api/skills-board/item-file", json={"path": "x.py", "content": "x"}).status_code == 401


def test_item_file_get_returns_only_a_relative_path(board):
    response = board.client.get("/api/skills-board/item-file", headers=AUTH, params={"type": "agent", "id": "bueroassistent", "path_hint": "agents/bueroassistent/"})
    body = response.json()
    assert response.status_code == 200 and body["success"] is True
    assert body["path"] == "agents/bueroassistent/SKILL.md"
    assert "absolute_path" not in body
    assert str(board.root) not in json.dumps(body)


# ---------------------------------------------------------------- hierarchy: one store

def test_get_reads_the_table_and_never_creates_the_json_file(board):
    data = board.client.get("/api/skills-board/hierarchy", headers=AUTH).json()
    assert data["_meta"]["source"] == "bach.db"
    assert data["assignments"]["bueroassistent"]["experts"] == ["steuer-agent"]
    assert not board.json_path.exists()


def test_put_writes_only_hierarchy_assignments_and_not_the_json_file(board):
    response = board.put(assignments(experts=["steuer-agent"], skills=["skill-bugfix"], workflows=["workflow-bugfix-protokoll"]))
    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] == "hierarchy_assignments" and body["items_persisted"] is False
    assert (body["inserted"], body["updated"], body["deleted"]) == (2, 0, 0)
    assert not board.json_path.exists()
    rows = board.rows()
    assert ("bueroassistent", "agent", "skill-bugfix", "skill", 0) in rows
    assert ("bueroassistent", "agent", "workflow-bugfix-protokoll", "workflow", 0) in rows
    again = board.client.get("/api/skills-board/hierarchy", headers=AUTH).json()
    assert again["assignments"]["bueroassistent"]["skills"] == ["skill-bugfix"]


def test_put_removes_and_reorders_and_is_idempotent(board):
    board.put(assignments(experts=["steuer-agent"], skills=["skill-bugfix"]))
    removed = board.put(assignments(skills=["skill-bugfix"])).json()
    assert (removed["inserted"], removed["deleted"]) == (0, 1)
    assert not any(r[2] == "steuer-agent" and r[0] == "bueroassistent" for r in board.rows())
    repeat = board.put(assignments(skills=["skill-bugfix"])).json()
    assert (repeat["inserted"], repeat["updated"], repeat["deleted"]) == (0, 0, 0)
    board.put(assignments(skills=["skill-bugfix", "skill-two"]))
    swapped = board.put(assignments(skills=["skill-two", "skill-bugfix"])).json()
    assert (swapped["inserted"], swapped["updated"], swapped["deleted"]) == (0, 2, 0)
    order = {r[2]: r[4] for r in board.rows() if r[0] == "bueroassistent"}
    assert (order["skill-two"], order["skill-bugfix"]) == (0, 1)


def test_put_leaves_other_parents_unknown_children_and_non_agent_rows_untouched(board):
    before = set(board.rows())
    board.put(assignments(skills=["skill-bugfix"]))  # replaces everything of bueroassistent that the hierarchy knows
    after = set(board.rows())
    assert ("zweiter", "agent", "skill-bugfix", "skill", 0) in after              # parent absent from the payload: untouched
    assert ("bueroassistent", "agent", "ghost-child", "skill", 0) in after        # child unknown to the hierarchy: untouched
    assert ("steuer-agent", "expert", "skill-bugfix", "skill", 0) in after        # not an agent parent: untouched
    assert ("bueroassistent", "agent", "steuer-agent", "expert", 0) not in after  # known child no longer assigned: deleted
    assert before - after == {("bueroassistent", "agent", "steuer-agent", "expert", 0)}


def test_put_clears_all_known_assignments_of_a_parent_with_empty_lists(board):
    board.put(assignments())
    assert [r for r in board.rows() if r[0] == "bueroassistent" and r[2] != "ghost-child"] == []


def test_items_are_validated_but_never_stored(board):
    payload = assignments(skills=["skill-bugfix"])
    payload["items"] = {"skills": [{"id": "skill-bugfix", "name": "Umbenannt"}], "workflows": [{"id": "workflow_999", "name": "Neu"}]}
    assert board.put(payload).status_code == 200
    data = board.client.get("/api/skills-board/hierarchy", headers=AUTH).json()
    assert [i["name"] for i in data["items"]["skills"]] == ["Bugfix Skill", "Skill Zwei"]
    assert all(i["id"] != "workflow_999" for i in data["items"]["workflows"])


# ---------------------------------------------------------------- hierarchy: validation (negative tests)

@pytest.mark.parametrize("payload,fragment", [
    ([], "Wurzel"),
    ({"assignments": {}, "extra": 1}, "unbekannter Schlüssel"),
    ({"assignments": []}, "assignments"),
    ({}, "assignments"),
    ({"assignments": {"bueroassistent": []}}, "unbekannte Gruppe"),
    ({"assignments": {"bueroassistent": {"agents": []}}}, "unbekannte Gruppe"),
    ({"assignments": {"bueroassistent": {"skills": "skill-bugfix"}}}, "Liste"),
    ({"assignments": {"bueroassistent": {"skills": [1]}}}, "Text"),
    ({"assignments": {"bueroassistent": {"skills": ["a\x00b"]}}}, "Steuerzeichen"),
    ({"assignments": {"bueroassistent": {"skills": ["x" * 201]}}}, "200"),
    ({"assignments": {"": {}}}, "Text"),
    ({"assignments": {}, "items": []}, "items"),
    ({"assignments": {}, "items": {"unknown": []}}, "unbekannte Gruppe"),
    ({"assignments": {}, "items": {"skills": ["nope"]}}, "Nicht-Objekt"),
    ({"assignments": {}, "items": {"skills": [{"name": "ohne id"}]}}, "id"),
    ({"assignments": {}, "_meta": "x"}, "_meta"),
    ({"assignments": {"nicht-vorhanden": {}}}, "unbekannter Agent"),
    ({"assignments": {"bueroassistent": {"skills": ["gibt-es-nicht"]}}}, "unbekanntes Element"),
    ({"assignments": {"bueroassistent": {"skills": ["service-registry"]}}}, "unbekanntes Element"),  # service id listed under skills
])
def test_invalid_hierarchy_is_rejected_with_400_and_changes_nothing(board, payload, fragment):
    before = board.rows()
    response = board.put(payload)
    assert response.status_code == 400
    assert fragment in response.json()["detail"]
    assert board.rows() == before
    assert not board.json_path.exists()


def test_non_json_and_oversized_bodies_are_rejected(board):
    before = board.rows()
    assert board.client.put("/api/skills-board/hierarchy", headers=AUTH, data="{not json").status_code == 400
    assert board.client.put("/api/skills-board/hierarchy", headers=AUTH, data=b"\xff\xfe").status_code == 400
    big = json.dumps({"assignments": {}, "_meta": {"pad": "x" * (server.HIERARCHY_BODY_LIMIT + 1)}})
    assert board.client.put("/api/skills-board/hierarchy", headers=AUTH, data=big).status_code == 413
    too_long = {"assignments": {"bueroassistent": {"skills": ["s%d" % i for i in range(server.HIERARCHY_MAX_LIST + 1)]}}}
    assert board.put(too_long).status_code == 400
    assert board.rows() == before


def test_the_arbitrary_json_that_used_to_be_stored_is_now_refused(board):
    assert board.put({"anything": ["goes"]}).status_code == 400


def test_put_requires_a_device_token(board):
    assert board.client.put("/api/skills-board/hierarchy", json=assignments()).status_code == 401


def test_missing_table_is_a_503_not_a_silent_json_fallback(board):
    conn = board.get_db()
    conn.execute("DROP TABLE hierarchy_assignments")
    conn.commit()
    conn.close()
    assert board.put(assignments(skills=["skill-bugfix"])).status_code == 503
    assert not board.json_path.exists()


# ---------------------------------------------------------------- dry-run report

def test_dryrun_reports_differences_and_changes_nothing(board, tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"assignments": {
        "bueroassistent": {"experts": ["steuer-agent"], "skills": ["skill-bugfix"]},
        "zweiter": {"workflows": ["skill-bugfix"]}}}), encoding="utf-8")
    db_before = board.db_path.read_bytes()
    json_before = legacy.read_bytes()
    report = dryrun.compare(legacy, board.db_path)
    assert report["changes_made"] is False and report["identical"] is False
    assert report["json_assignments"] == 3
    assert {(e["parent"], e["child"]) for e in report["only_in_json"]} == {("bueroassistent", "skill-bugfix")}
    assert {(e["parent"], e["child"]) for e in report["only_in_table"]} == {("bueroassistent", "ghost-child")}
    assert report["type_differs"] == [{"parent": "zweiter", "child": "skill-bugfix", "json": "workflow", "table": "skill"}]
    assert report["common"] == 1
    assert board.db_path.read_bytes() == db_before and legacy.read_bytes() == json_before


def test_dryrun_handles_a_missing_json_file_and_cli_output(board, tmp_path, capsys):
    report = dryrun.compare(tmp_path / "absent.json", board.db_path)
    assert report["json_file_present"] is False and report["json_assignments"] == 0
    assert dryrun.main(["--json", str(tmp_path / "absent.json"), "--db", str(board.db_path)]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert dryrun.main(["--json", str(tmp_path / "absent.json"), "--db", str(board.db_path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["changes_made"] is False
