# -*- coding: utf-8 -*-
"""Trigger-Generatoren respektieren die Sichtung 045 (T-20260926-363436040).

Vorher schrieben sie in system/data/bach.db (Geister-DB) und der
Themen-Generator per INSERT OR REPLACE -- ein echter Lauf gegen BACH_DB haette
deaktivierte Themen reaktiviert und fremde Zeilen gleicher Phrase ersetzt.
"""
import importlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_DIR = Path(__file__).resolve().parent.parent
TOOLS = SYSTEM_DIR / "tools"
SCHEMA_DIR = SYSTEM_DIR / "data" / "schema"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"gen_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def union_db(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "bach_memory_union_gen", SCHEMA_DIR / "memory_union" / "memory_union.py")
    mu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mu)
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    mu.create_union_schema(conn)
    conn.executemany(
        "INSERT INTO context_triggers (trigger_phrase, hint_text, source, is_active, usage_count)"
        " VALUES (?,?,?,?,?)", [
            ("oder", "[THEMA-PAKET] alt", "theme", 0, 3),      # in 045 deaktiviert
            ("code", "manual-Hinweis", "manual", 1, 7),        # fremde Quelle, gleiche Phrase
        ])
    conn.execute("INSERT INTO memory_lessons (category, title, solution, is_active) VALUES ('test', 'Muss pruefen', 'x', 1)")
    conn.commit()
    conn.close()
    return db


def _rows(db):
    conn = sqlite3.connect(db)
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT trigger_phrase, source, is_active, hint_text, usage_count FROM context_triggers")}
    conn.close()
    return rows


@pytest.mark.parametrize("name", [
    "theme_packet_generator", "lesson_trigger_generator", "tool_auto_discovery",
    "workflow_trigger_generator", "trigger_maintainer", "bach_auto_discovery"])
def test_generators_use_bach_db(name):
    # Andere Suiten laden die zentrale Pfad-Registry neu; der Vergleich muss
    # denselben aktuell geladenen Kanon wie der Generator verwenden.
    bach_paths = importlib.import_module("hub.bach_paths")
    assert Path(_load(name).DB_PATH) == Path(bach_paths.BACH_DB)


def test_theme_upsert_respects_sichtung_and_foreign_source(union_db, monkeypatch):
    gen = _load("theme_packet_generator")
    monkeypatch.setattr(gen, "DB_PATH", union_db)
    gen.sync_to_db([{"triggers": ["oder", "code", "wartung"], "hint": "[THEMA-PAKET] neu"}])
    rows = _rows(union_db)
    assert rows["oder"] == ("theme", 0, "[THEMA-PAKET] neu", 3)   # bleibt aus, Zaehler bleibt
    assert rows["code"] == ("manual", 1, "manual-Hinweis", 7)     # fremde Zeile unberuehrt
    assert rows["wartung"][:3] == ("theme", 1, "[THEMA-PAKET] neu")


def test_lesson_generator_adds_inactive_candidates(union_db, monkeypatch):
    gen = _load("lesson_trigger_generator")
    monkeypatch.setattr(gen, "DB_PATH", union_db)
    gen.process_lessons()
    new = {k: v for k, v in _rows(union_db).items() if v[0] == "lesson"}
    assert new and all(v[1] == 0 for v in new.values())
