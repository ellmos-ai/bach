# SPDX-License-Identifier: MIT
"""
Contract and Unit Tests for Cognitive Architecture, Memory Integration & Denkarium
==================================================================================
Scope: GUX-032 bis GUX-043 (Register GUX-94-2026-10-04-v1.1, Task #1700)

Validiert:
1. GUX-032: Architekturansicht rendert kanonische Mermaid-Quelle direkt.
2. GUX-033: Diagrammfarben codieren belegte funktionale Beziehungen mit Legende.
3. GUX-034 bis GUX-041: Die 8 kognitiven Prozessblöcke als echte Datenquellen mit Telemetrie.
4. GUX-041/042: Schema-agnostischer USMC Lessons-Reader ohne Absturz bei fehlender 'source_kind'.
5. GUX-042: /agenten/sessions bindet echte Sessions, Lessons und Working Memory quellengetreu ein.
6. GUX-043 & NAV-ASS-04: Denkarium-Trennung (Mensch vs. Agent-Dumps), reversible Archivierung
   und Öffnen im neuen Tab (target="_blank").
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SYS_DIR = Path(__file__).resolve().parent.parent
if str(SYS_DIR) not in sys.path:
    sys.path.insert(0, str(SYS_DIR))
if str(SYS_DIR / "gui") not in sys.path:
    sys.path.insert(0, str(SYS_DIR / "gui"))

from gui import device_auth
from gui.device_auth import _hash_token, init_devices_db
from gui.server import app
from hub._services.cognitive_service import (
    CANONICAL_MERMAID_DIAGRAM,
    DIAGRAM_LEGEND,
    archive_denkarium_entry,
    ensure_denkarium_schema,
    get_cognitive_topology,
    get_process_block,
    list_denkarium_entries,
    read_usmc_lessons_safe,
    unarchive_denkarium_entry,
)

TOKEN = "test-token-kognitiver-schaltplan-20261005"
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def setup_test_auth(tmp_path, monkeypatch):
    """Isoliertes Device-Auth-Setup fuer HTTP-Aufrufe ueber TestClient."""
    auth_db_path = tmp_path / "test_devices.db"

    def get_auth_connection():
        c = sqlite3.connect(str(auth_db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    conn = get_auth_connection()
    init_devices_db(conn)
    token_hash = _hash_token(TOKEN)
    conn.execute(
        "INSERT OR REPLACE INTO devices (name, token_hash, status) VALUES ('asus-gei', ?, 'active')",
        (token_hash,)
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(device_auth, "GET_CONNECTION", get_auth_connection)


@pytest.fixture
def isolated_memory_db(tmp_path):
    """Erzeugt eine isolierte Test-Datenbank mit dem kanonischen Memory-Schema."""
    db_file = tmp_path / "test_memory.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE memory_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            key TEXT,
            value TEXT,
            value_type TEXT DEFAULT 'text',
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT 'gui',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE memory_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            title TEXT,
            solution TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE memory_working (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT DEFAULT 'scratchpad',
            content TEXT,
            priority INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE memory_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            started_at TEXT,
            ended_at TEXT,
            summary TEXT,
            tasks_completed INTEGER DEFAULT 0,
            tokens_used INTEGER DEFAULT 0
        )
    """)
    ensure_denkarium_schema(conn)

    # Beispieldaten einfuegen
    conn.execute("INSERT INTO memory_facts (category, key, value) VALUES ('sys', 'os', 'windows')")
    conn.execute("INSERT INTO memory_lessons (category, title, solution, is_active) VALUES ('dev', 'Lock-Master', 'Fail-closed pruefen', 1)")
    conn.execute("INSERT INTO memory_working (type, content, priority, is_active) VALUES ('cot', 'Aktiver Schritt 4', 2, 1)")
    conn.execute("INSERT INTO memory_sessions (session_id, started_at, summary) VALUES ('sess-001', '2026-10-05T10:00:00Z', 'Test Session')")
    conn.execute("INSERT INTO denkarium_entries (content, entry_type, category, created_at) VALUES ('Menschlicher Gedanke', 'denkarium', 'notiz', '2026-10-05 10:00')")
    conn.commit()
    conn.close()
    return db_file


def test_gux_032_canonical_mermaid_rendered_directly():
    """GUX-032: Architekturansicht rendert die kanonische Mermaid-Quelle direkt."""
    assert "flowchart TD" in CANONICAL_MERMAID_DIAGRAM
    assert "1. Zentrale Exekutive & Messtechnik" in CANONICAL_MERMAID_DIAGRAM
    assert "6. Zentrum: Aktives Kontextfenster" in CANONICAL_MERMAID_DIAGRAM
    assert "7. Langzeitgedächtnis" in CANONICAL_MERMAID_DIAGRAM

    client = TestClient(app, base_url="http://127.0.0.1:8000")
    res = client.get("/api/cognitive/topology", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "mermaid_code" in data
    assert "flowchart TD" in data["mermaid_code"]

    res_cog = client.get("/api/memory/cognitive-state", headers=AUTH_HEADER)
    assert res_cog.status_code == 200
    assert "mermaid_code" in res_cog.json()


def test_gux_033_diagram_colors_and_clean_legend():
    """GUX-033: Diagrammfarben codieren nur belegte funktionale Beziehungen mit Legende."""
    assert len(DIAGRAM_LEGEND) == 5
    legend_ids = {item["id"] for item in DIAGRAM_LEGEND}
    expected_ids = {"boot_bus", "injection_path", "supervision_sensors", "active_tool_pull", "reactive_guard"}
    assert legend_ids == expected_ids

    for item in DIAGRAM_LEGEND:
        assert "name" in item
        assert "color" in item
        assert "description" in item
        assert "style" in item

    client = TestClient(app, base_url="http://127.0.0.1:8000")
    res = client.get("/api/cognitive/topology", headers=AUTH_HEADER)
    data = res.json()
    assert "legend" in data
    assert len(data["legend"]) == 5


def test_gux_034_to_041_eight_process_blocks_telemetry(isolated_memory_db):
    """GUX-034 bis GUX-041: Alle 8 kognitiven Prozessblöcke sind echte Datenquellen mit Telemetrie."""
    conn = sqlite3.connect(str(isolated_memory_db))
    conn.row_factory = sqlite3.Row
    topology = get_cognitive_topology(conn)
    assert topology["success"] is True
    blocks = topology["blocks"]
    assert len(blocks) == 8

    # 1. kontextfenster (GUX-034)
    b_ctx = get_process_block("kontextfenster", conn=conn)
    assert b_ctx["success"] is True
    assert b_ctx["block"]["data_source"] == "memory_working"
    assert b_ctx["block"]["active_items_count"] >= 1
    assert "working_items" in b_ctx["block"]

    # 2. zentrale_exekutive (GUX-035)
    b_ze = get_process_block("zentrale_exekutive", conn=conn)
    assert b_ze["success"] is True
    assert "SAS" in b_ze["block"]["sub"]

    # 3. sensoren_messtechnik (GUX-036)
    b_sens = get_process_block("sensoren_messtechnik", conn=conn)
    assert b_sens["success"] is True
    assert "sensor_receipt" in b_sens["block"]
    assert b_sens["block"]["sensor_receipt"]["status"] == "nominal"

    # 4. guards (GUX-037)
    b_guards = get_process_block("guards", conn=conn)
    assert b_guards["success"] is True
    assert "guard_receipt" in b_guards["block"]
    assert b_guards["block"]["guard_receipt"]["decision"] == "allow"

    # 5. berechtigung_hooker (GUX-038)
    b_hk = get_process_block("berechtigung_hooker", conn=conn)
    assert b_hk["success"] is True
    assert b_hk["block"]["injection_gate"]["has_control_logic"] is False

    # 6. startprompt (GUX-039)
    b_sp = get_process_block("startprompt", conn=conn)
    assert b_sp["success"] is True
    assert "Boot:Agent" in b_sp["block"]["sub"]

    # 7. lernen_rueckfluss (GUX-040)
    b_learn = get_process_block("lernen_rueckfluss", conn=conn)
    assert b_learn["success"] is True
    assert b_learn["block"]["active_lessons_count"] >= 1

    # 8. langzeit_gedaechtnis (GUX-041)
    b_ltm = get_process_block("langzeit_gedaechtnis", conn=conn)
    assert b_ltm["success"] is True
    assert b_ltm["block"]["facts_count"] >= 1
    assert "ssot_architecture" in b_ltm["block"]

    conn.close()


def test_gux_041_usmc_lessons_safe_schema_agnostic(tmp_path):
    """GUX-041 Follow-up: Robuster USMC Lessons-Reader fängt fehlende Spalten ohne Absturz oder ALTER TABLE ab."""
    # Erzeuge eine Legacy-DB, die 'source_kind' und 'editorial_status' bewusst NICHT hat
    legacy_db = tmp_path / "legacy_usmc_memory.db"
    with sqlite3.connect(legacy_db) as conn:
        conn.execute("""
            CREATE TABLE memory_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                title TEXT,
                solution TEXT,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            INSERT INTO memory_lessons (category, title, solution, is_active)
            VALUES ('legacy_cat', 'Alte Lektion', 'Lösung ohne source_kind Spalte', 1)
        """)
        conn.commit()

    # Schema-agnostischer Aufruf muss 100% gelingen
    res = read_usmc_lessons_safe(legacy_db)
    assert res["success"] is True
    assert res["availability"] == "available"
    assert res["has_source_kind"] is False
    assert res["count"] == 1
    lesson = res["lessons"][0]
    assert lesson["title"] == "Alte Lektion"
    assert lesson["source_kind"] == "legacy"
    assert lesson["provenance_status"] == "legacy_mapped"

    # Verifizieren, dass keine ungefragte Spalte hinzugefügt wurde (kein unbefugtes ALTER TABLE)
    with sqlite3.connect(legacy_db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_lessons)").fetchall()}
        assert "source_kind" not in cols, "read_usmc_lessons_safe darf die Produktionstabelle nicht mutieren!"


def test_gux_042_sessions_page_and_endpoint_without_503():
    """GUX-042: /agenten/sessions bindet echte Chats, Lessons & Working Memory ohne 503 ein."""
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    res_page = client.get("/agenten/sessions")
    assert res_page.status_code == 200
    assert "text/html" in res_page.headers.get("content-type", "")
    assert "Sessions" in res_page.text
    assert "Lessons" in res_page.text

    # API-Endpunkt memory/sessions
    res_api = client.get("/api/memory/sessions", headers=AUTH_HEADER)
    assert res_api.status_code == 200
    assert "sessions" in res_api.json()


def test_gux_043_denkarium_human_notebook_reversible_archive(isolated_memory_db):
    """GUX-043: Denkarium als menschliches Notizbuch mit reversibler Archivierung technischer Agent-Dumps."""
    conn = sqlite3.connect(str(isolated_memory_db))
    conn.row_factory = sqlite3.Row

    # 1. Technischen Dump anlegen
    conn.execute("""
        INSERT INTO denkarium_entries (content, entry_type, category, created_at)
        VALUES ('[Auto-Dump] Ungefilterte Debug-Ausgabe von Agent X', 'denkarium', 'agent_dump', '2026-10-05 11:00')
    """)
    conn.commit()
    dump_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Standard-Listing vor Archivierung
    before = list_denkarium_entries(conn=conn, exclude_archived=True)
    assert any(e["id"] == dump_id for e in before["entries"])

    # 2. Reversibel archivieren
    arch_res = archive_denkarium_entry(dump_id, reason="wrong_agent_dump", conn=conn)
    assert arch_res["success"] is True
    assert arch_res["action"] == "archived"
    assert "undo_token" in arch_res

    # 3. Standard-Listing nach Archivierung: Dump ist ausgeschlossen!
    after_exclude = list_denkarium_entries(conn=conn, exclude_archived=True)
    assert not any(e["id"] == dump_id for e in after_exclude["entries"])
    assert after_exclude["stats"]["archived"] >= 1
    # Menschlicher Eintrag bleibt erhalten
    assert any(e["content"] == "Menschlicher Gedanke" for e in after_exclude["entries"])

    # 4. Listing inkl. Archiv: Dump ist auffindbar
    after_all = list_denkarium_entries(conn=conn, exclude_archived=False)
    dump_entry = next(e for e in after_all["entries"] if e["id"] == dump_id)
    assert dump_entry["is_archived"] == 1
    assert dump_entry["archived_reason"] == "wrong_agent_dump"

    # 5. Reversibel wiederherstellen (Unarchive)
    unarch_res = unarchive_denkarium_entry(dump_id, conn=conn)
    assert unarch_res["success"] is True
    assert unarch_res["action"] == "unarchived"

    restored = list_denkarium_entries(conn=conn, exclude_archived=True)
    assert any(e["id"] == dump_id for e in restored["entries"])

    conn.close()


def test_nav_ass_04_denkarium_opens_in_new_tab():
    """NAV-ASS-04: Denkarium-Link in der Navigation soll mit target='_blank' in einem neuen Tab öffnen."""
    nav_config_path = SYS_DIR / "gui" / "web" / "src" / "config" / "nav_config.json"
    assert nav_config_path.exists()

    with open(nav_config_path, "r", encoding="utf-8") as f:
        nav_data = json.load(f)

    denkarium_found = False

    def check_items(items):
        nonlocal denkarium_found
        for item in items:
            if item.get("href") == "/denkarium":
                denkarium_found = True
                assert item.get("target") == "_blank", "Denkarium-Link muss target='_blank' haben (NAV-ASS-04)!"
            if "children" in item:
                check_items(item["children"])

    check_items(nav_data)
    assert denkarium_found, "Denkarium-Link nicht in nav_config.json gefunden!"

    # Template persoenlich.html pruefen
    persoenlich_tpl = SYS_DIR / "gui" / "templates" / "persoenlich.html"
    if persoenlich_tpl.exists():
        with open(persoenlich_tpl, "r", encoding="utf-8") as f:
            content = f.read()
            assert 'href="/denkarium"' in content
            assert 'target="_blank"' in content
