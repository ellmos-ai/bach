# -*- coding: utf-8 -*-
"""Task 3726: /api/tasks-Pagination ueber 200 Eintraege und vollstaendiges Lesen durch die Clients.

Befund (heutige Source): In api_get_tasks gibt es keine 200er-Kappung. Der Server liefert
ohne Parameter 100 Eintraege (limit=100) und zeigt per limit+1 / has_more / offset / total, ob
Folgeseiten existieren. Gekappt wurden Legacy-Clients, die nur die erste Seite lasen
(tasks_board.html, API.tasks.list in api.js, tasks.html mit limit=500). Diese Tests sichern
(1) den unveraenderten Serververtrag mit 250 Datensaetzen und (2) den echten Client
(api.js getAllPages, unter Node) gegen die echten Serverantworten.

Nur erfundene Daten in einer temporaeren SQLite-Datei; kein ~/.bach, keine Dienste.
"""

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
API_JS = SYSTEM_ROOT / "gui" / "static" / "js" / "api.js"
TEMPLATES = SYSTEM_ROOT / "gui" / "templates"
TOTAL = 250
PENDING, PROGRESS, DONE = 120, 30, 100      # + 0 Rest = 250


@pytest.fixture
def client(tmp_path, monkeypatch):
    from gui import server

    db = tmp_path / "tasks.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT, description TEXT, status TEXT, priority TEXT,
                category TEXT, assigned_to TEXT, delegated_to TEXT,
                created_at TEXT, depends_on TEXT, image_data TEXT
            );
        """)
        rows = []
        for n in range(TOTAL):
            status = "pending" if n < PENDING else "in_progress" if n < PENDING + PROGRESS else "done"
            rows.append((f"Task {n:03d}", f"Beschreibung {n}", status, f"P{1 + n % 4}",
                         "gui" if n % 2 else "core", "CODEX",
                         f"2026-10-{1 + n % 28:02d}T10:{n % 60:02d}:00"))
        conn.executemany(
            "INSERT INTO tasks (title,description,status,priority,category,assigned_to,created_at) "
            "VALUES (?,?,?,?,?,?,?)", rows,
        )

    def connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "t3726" else None)
    test_client = TestClient(server.app, headers={"Authorization": "Bearer t3726"})
    try:
        yield test_client
    finally:
        test_client.close()


def _get(client, query=""):
    res = client.get("/api/tasks" + query)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    return data


# --- Serververtrag (unveraendert) ----------------------------------------------


def test_default_is_still_100_with_total_and_has_more_over_200_rows(client):
    data = _get(client)
    assert data["count"] == len(data["tasks"]) == 100
    assert data["total"] == TOTAL and data["has_more"] is True and data["offset"] == 0


def test_no_server_side_cap_at_200(client):
    """Kein 200er-Limit im Endpunkt: eine grosse Seite liefert alle 250 Zeilen."""
    for limit in (250, 500, 10000):      # 10000 wie rheingold.py
        data = _get(client, f"?limit={limit}")
        assert data["count"] == TOTAL and data["total"] == TOTAL and data["has_more"] is False


@pytest.mark.parametrize("page_size", [1, 7, 100, 249, 250, 251])
def test_follow_pages_are_complete_without_duplicates_or_loss(client, page_size):
    seen, offset, pages = [], 0, 0
    while True:
        data = _get(client, f"?limit={page_size}&offset={offset}")
        pages += 1
        assert data["offset"] == offset and data["total"] == TOTAL
        assert data["count"] == len(data["tasks"]) <= page_size
        seen.extend(row["id"] for row in data["tasks"])
        if not data["has_more"]:
            break
        assert data["count"] == page_size          # volle Seite, wenn es weitergeht
        offset += data["count"]
        assert pages <= TOTAL                      # Schutz gegen Endlosschleife im Test
    assert len(seen) == len(set(seen)) == TOTAL
    # dieselbe Reihenfolge wie eine einzige grosse Seite
    assert seen == [row["id"] for row in _get(client, "?limit=1000")["tasks"]]


@pytest.mark.parametrize("category, expected", [("gui", 125), ("core", 125)])
def test_exact_page_boundary_has_more(client, category, expected):
    base = f"?category={category}"
    assert _get(client, base + f"&limit={expected}")["has_more"] is False          # genau eine volle Seite
    assert _get(client, base + f"&limit={expected - 1}")["has_more"] is True       # ein Datensatz mehr
    assert _get(client, base + f"&limit={expected + 1}")["has_more"] is False


def test_offset_and_edge_cases(client):
    beyond = _get(client, f"?limit=10&offset={TOTAL}")
    assert beyond["tasks"] == [] and beyond["count"] == 0 and beyond["has_more"] is False
    assert beyond["total"] == TOTAL and beyond["offset"] == TOTAL
    last = _get(client, f"?limit=10&offset={TOTAL - 1}")
    assert last["count"] == 1 and last["has_more"] is False
    negative = _get(client, "?limit=10&offset=-5")
    assert negative["offset"] == 0 and negative["count"] == 10


def test_filters_total_and_applied_filters_survive_paging(client):
    first = _get(client, "?status=pending&limit=50&offset=0")
    last = _get(client, "?status=pending&limit=50&offset=100")
    assert first["total"] == last["total"] == PENDING
    assert first["has_more"] is True and last["has_more"] is False and last["count"] == PENDING - 100
    assert first["applied_filters"]["status"] == "pending"
    assert {row["status"] for row in first["tasks"] + last["tasks"]} == {"pending"}


def test_explicit_limit_zero_is_count_only(client):
    """limit=0 ist heute (und bleibt) eine reine Zaehlabfrage: keine Zeilen, total korrekt, kein has_more."""
    data = _get(client, "?limit=0")
    assert data["tasks"] == [] and data["count"] == 0 and data["total"] == TOTAL
    assert data["has_more"] is False and data["offset"] == 0
    assert _get(client, "?status=done&limit=0")["total"] == DONE


# --- Echter Client (api.js unter Node) gegen echte Serverantworten ---------------

NODE = shutil.which("node")

RUNNER = r"""
const fs = require('fs');
globalThis.window = {};
globalThis.localStorage = { getItem() { return null; } };
const spec = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const requests = [];
globalThis.fetch = async (url) => {
  requests.push(url);
  if (!(url in spec.pages)) throw new Error('unerwartete Anfrage: ' + url);
  return { ok: true, status: 200, json: async () => spec.pages[url] };
};
const API = require(process.argv[2]);
(async () => {
  let out;
  try {
    if (spec.call === 'list') out = await API.tasks.list(spec.arg);
    else out = await API.getAllPages(spec.endpoint, 'tasks', spec.pageSize, spec.maxPages);
    console.log(JSON.stringify({ requests, result: out }));
  } catch (e) {
    console.log(JSON.stringify({ requests, error: String(e) }));
  }
})();
"""


def _run_client(tmp_path, spec):
    if not NODE:
        pytest.skip("node nicht verfuegbar")
    runner = tmp_path / "runner.js"
    runner.write_text(RUNNER, encoding="utf-8")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    proc = subprocess.run([NODE, str(runner), str(API_JS), str(spec_file)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _record(client, endpoint, page_size):
    """Zeichnet die echten Serverantworten fuer alle Seiten auf (Schluessel = exakte Client-URL)."""
    pages, offset = {}, 0
    while True:
        sep = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{sep}limit={page_size}&offset={offset}"
        data = client.get(url).json()
        pages[url] = data
        if not data["has_more"]:
            return pages
        offset += data["count"]


def test_client_list_reads_every_page_of_250_rows(client, tmp_path):
    pages = _record(client, "/api/tasks", 100)
    out = _run_client(tmp_path, {"call": "list", "arg": "", "pages": pages})
    result = out["result"]
    ids = [row["id"] for row in result["tasks"]]
    assert out["requests"] == list(pages)              # genau diese 3 Seiten, in Reihenfolge
    assert len(out["requests"]) == 3
    assert len(ids) == len(set(ids)) == TOTAL == result["count"] == result["total"]
    assert result["has_more"] is False and result["success"] is True
    assert ids == [row["id"] for row in client.get("/api/tasks?limit=1000").json()["tasks"]]


def test_client_list_with_status_filter_and_board_page_size(client, tmp_path):
    pages = _record(client, "/api/tasks?status=pending,open,blocked", 100)
    out = _run_client(tmp_path, {"call": "list", "arg": "pending,open,blocked", "pages": pages})
    assert len(out["result"]["tasks"]) == PENDING and out["result"]["total"] == PENDING
    assert len(out["requests"]) == 2

    pages = _record(client, "/api/tasks?status=all", 500)       # tasks.html: Seitengroesse 500
    out = _run_client(tmp_path, {"call": "all", "endpoint": "/api/tasks?status=all", "pageSize": 500,
                                 "maxPages": 1000, "pages": pages})
    assert len(out["result"]["tasks"]) == TOTAL and len(out["requests"]) == 1


def test_client_does_not_hide_a_failing_page(client, tmp_path):
    pages = _record(client, "/api/tasks", 100)
    urls = list(pages)
    pages[urls[1]] = {"success": False, "error": "kaputt"}
    out = _run_client(tmp_path, {"call": "list", "arg": "", "pages": pages})
    assert "result" not in out
    assert out["error"] == "Error: Task-Liste konnte nicht vollständig geladen werden: kaputt"
    assert out["requests"] == urls[:2]


def test_client_drops_duplicate_ids_between_pages(tmp_path):
    row = lambda i: {"id": i, "title": f"t{i}"}      # noqa: E731
    pages = {
        "/api/tasks?limit=3&offset=0": {"success": True, "tasks": [row(1), row(2), row(3)], "count": 3,
                                        "total": 5, "has_more": True, "offset": 0},
        "/api/tasks?limit=3&offset=3": {"success": True, "tasks": [row(3), row(4), row(5)], "count": 3,
                                        "total": 5, "has_more": False, "offset": 3},
    }
    out = _run_client(tmp_path, {"call": "all", "endpoint": "/api/tasks", "pageSize": 3, "maxPages": 10,
                                 "pages": pages})
    assert [r["id"] for r in out["result"]["tasks"]] == [1, 2, 3, 4, 5]


def test_client_rejects_max_pages_exhaustion_as_incomplete(tmp_path):
    page = lambda off: {"success": True, "tasks": [{"id": off + 1}, {"id": off + 2}], "count": 2,  # noqa: E731
                        "total": 99, "has_more": True, "offset": off}
    pages = {f"/api/tasks?limit=2&offset={off}": page(off) for off in range(0, 40, 2)}
    out = _run_client(tmp_path, {"call": "all", "endpoint": "/api/tasks", "pageSize": 2, "maxPages": 3,
                                 "pages": pages})
    assert "result" not in out
    assert out["error"] == "Error: Task-Liste unvollständig: Nach 3 Seiten meldet der Server weitere Ergebnisse."
    assert len(out["requests"]) == 3


def test_client_rejects_empty_page_that_claims_more(tmp_path):
    pages = {"/api/tasks?limit=5&offset=0": {"success": True, "tasks": [], "count": 0, "total": 3,
                                             "has_more": True, "offset": 0}}
    out = _run_client(tmp_path, {"call": "all", "endpoint": "/api/tasks", "pageSize": 5, "maxPages": 50,
                                 "pages": pages})
    assert "result" not in out
    assert out["error"] == "Error: Task-Liste unvollständig: Der Server meldet ab Offset 0 weitere Seiten, liefert aber keine Einträge."
    assert len(out["requests"]) == 1


# --- Consumer-Naht: Templates nutzen den Seitenleser ------------------------------


def test_legacy_templates_read_all_pages_instead_of_one_page():
    board = (TEMPLATES / "tasks_board.html").read_text(encoding="utf-8")
    tasks = (TEMPLATES / "tasks.html").read_text(encoding="utf-8")
    assert "api.getAllPages(url)" in board and "const res = await api.get(url);" not in board
    assert "api.getAllPages('/api/tasks?status=all'" in tasks and "limit=500')" not in tasks
    js = API_JS.read_text(encoding="utf-8")
    assert "list: (status) => API.getAllPages('/api/tasks'" in js
