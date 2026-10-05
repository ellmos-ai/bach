# -*- coding: utf-8 -*-
"""ContextInjector: reparierter DB-Pfad hinter BACH_CONTEXT_TRIGGERS_DB (S3).

Bis S3 las der ContextInjector context_triggers nie (fehlender sqlite3-Import,
falscher DB-Pfad) und nutzte nur die Hardcode-Liste. Default bleibt dieses
Verhalten; mit Flag gilt die Leseregel des gemeinsamen Vertrags. Dazu die
Sichtungs-Migration 045 gegen eine Vertrags-DB.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SYSTEM_DIR / "data" / "schema"
sys.path.insert(0, str(SYSTEM_DIR / "tools"))
import injectors  # noqa: E402

CI = injectors.ContextInjector


def _union_db(path):
    spec = importlib.util.spec_from_file_location(
        "bach_memory_union_ctx", SCHEMA_DIR / "memory_union" / "memory_union.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(path)
    module.create_union_schema(conn)
    return conn


@pytest.fixture
def injector(tmp_path, monkeypatch):
    db = tmp_path / "bach.db"
    conn = _union_db(db)
    rows = [
        ("fehler", "DB: Fehler-Hinweis", "manual", 1, "unknown", None),
        ("gesperrt", "DB: gesperrt", "manual", 1, "blocked", None),
        ("aus", "DB: aus", "manual", 0, "unknown", None),
        ("alt", "DB: abgelaufen", "manual", 1, "unknown", "2000-01-01 00:00:00"),
        ("blockiert|stuck", "[STRATEGIE] x", "strategy", 1, "approved", None),
    ]
    conn.executemany(
        "INSERT INTO context_triggers (trigger_phrase, hint_text, source, is_active, status, expires_at)"
        " VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(CI, "base_path", tmp_path)
    monkeypatch.setattr(CI, "_cache", None)
    monkeypatch.setattr(CI, "_session_triggered", set())
    monkeypatch.setattr(CI, "_db_path", classmethod(lambda cls: db))
    monkeypatch.delenv(injectors.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    return db


def test_default_off_keeps_hardcode_and_never_writes(injector):
    assert CI.check("ein fehler") == "[KONTEXT] " + CI.CONTEXT_TRIGGERS["fehler"]
    conn = sqlite3.connect(injector)
    assert conn.execute("SELECT SUM(usage_count) FROM context_triggers").fetchone()[0] == 0
    conn.close()


def test_flag_on_reads_contract_rule_and_counts_usage(injector, monkeypatch):
    monkeypatch.setenv(injectors.CONTEXT_TRIGGERS_DB_ENV, "1")
    assert CI.check("ein fehler") == "[KONTEXT] DB: Fehler-Hinweis"
    for text in ("gesperrt", "aus", "alt", "ich bin blockiert"):
        assert CI.check(text) is None, text
    conn = sqlite3.connect(injector)
    assert conn.execute(
        "SELECT usage_count FROM context_triggers WHERE trigger_phrase='fehler'").fetchone()[0] == 1
    conn.close()


def test_sichtung_045_idempotent(tmp_path):
    conn = _union_db(tmp_path / "s.db")
    conn.executemany(
        "INSERT INTO context_triggers (trigger_phrase, hint_text, source) VALUES (?,?,?)", [
            ("the", "[TOOL] junk", "tool"),
            ("gibt", "[LEKTION] junk", "lesson"),
            ("oder", "[THEMA-PAKET] x", "theme"),
            ("shutdown", "[THEMA-PAKET] Shutdown", "theme"),
            ("quiz", "Wiki-Quizzer: agents/_experts/wikiquizzer", "manual"),
            ("bug", "Bugfix-Workflow: skills/workflows/bugfix-protokoll.md", "manual"),
            ("utf-8", "Encoding-Fix: bach c_encoding_fixer <datei>", "manual"),
        ])
    sql = (SCHEMA_DIR / "migrations" / "045_context_triggers_sichtung.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.executescript(sql)
    got = dict(conn.execute(
        "SELECT trigger_phrase, CASE WHEN is_active THEN hint_text END FROM context_triggers"))
    assert got == {
        "the": None, "gibt": None, "oder": None, "quiz": None,
        "shutdown": "[THEMA-PAKET] Shutdown",
        "bug": "Bugfix-Workflow: skills/workflows/bugfix-protokoll.md",
        "utf-8": "Encoding-Fix: python tools/file_ops/encoding_fixer.py <datei>",
    }


def test_broken_db_warns_once_and_falls_back(injector, monkeypatch, caplog):
    monkeypatch.setenv(injectors.CONTEXT_TRIGGERS_DB_ENV, "1")
    monkeypatch.setattr(injectors, "_warned", set())
    injector.write_bytes(b"kein sqlite")
    with caplog.at_level("WARNING", logger=injectors.__name__):
        assert CI.check("ein fehler") == "[KONTEXT] " + CI.CONTEXT_TRIGGERS["fehler"]
        CI._cache = None
        CI.check("ein fehler")
    warnings = [r for r in caplog.records if "context_triggers lesen" in r.getMessage()]
    assert len(warnings) == 1 and "DatabaseError" in warnings[0].getMessage()
