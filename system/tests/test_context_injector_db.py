# -*- coding: utf-8 -*-
"""Kontext-Trigger ueber den memoryhooker-Seam und InjectorSystem-Adapter (S3-Nachlauf T-20260926-537523074).

DB (context_triggers) ist die einzige Quelle; ContextInjector und die Hardcode-Liste
CONTEXT_TRIGGERS sind entfernt. Prueft Leseregel, Nutzungszaehler, Sichtungs-Migration 045,
Fail-soft-Warnung bei defekter DB sowie Wortgrenzen-Matching gegen falsche Substring-Treffer.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("memoryhooker.triggers")

SYSTEM_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SYSTEM_DIR / "data" / "schema"
sys.path.insert(0, str(SYSTEM_DIR))
sys.path.insert(0, str(SYSTEM_DIR / "tools"))
import hub.memory_hook_provider as mhp  # noqa: E402
import injectors  # noqa: E402


def _union_db(path):
    spec = importlib.util.spec_from_file_location(
        "bach_memory_union_ctx", SCHEMA_DIR / "memory_union" / "memory_union.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conn = sqlite3.connect(path)
    module.create_union_schema(conn)
    return conn


@pytest.fixture
def adapter_env(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "config.json").write_text(
        '{"injectors": {"strategy_injector": false, "time_injector": false, "context_injector": true}}',
        encoding="utf-8",
    )
    db = tmp_path / "data" / "bach.db"
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
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    return tmp_path, db


def test_default_on_reads_contract_rule_and_counts_usage(adapter_env):
    base, db = adapter_env
    system = injectors.InjectorSystem(base)
    assert system.process("ein fehler") == ["[KONTEXT] DB: Fehler-Hinweis"]
    for text in ("gesperrt", "aus", "alt", "ich bin blockiert"):
        assert system.process(text) == [], text
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT usage_count FROM context_triggers WHERE trigger_phrase='fehler'").fetchone()[0] == 1
    conn.close()


def test_flag_explicit_off_disables_context(adapter_env, monkeypatch):
    base, db = adapter_env
    monkeypatch.setenv(mhp.CONTEXT_TRIGGERS_DB_ENV, "0")
    system = injectors.InjectorSystem(base)
    assert system.process("ein fehler") == []
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT SUM(usage_count) FROM context_triggers").fetchone()[0] == 0
    conn.close()


def test_sichtung_045_idempotent(tmp_path):
    conn = _union_db(tmp_path / "s.db")
    conn.executemany(
        "INSERT INTO context_triggers (trigger_phrase, hint_text, source) VALUES (?,?,?)", [
            ("the", "[TOOL] junk", "tool"),
            ("gibt", "[LEKTION] junk", "lesson"),
            ("oder", "[THEMA-PAKET] x", "theme"),
            ("shutdown", "[THEMA-PAKET] Shutdown", "theme"),
            ("quiz", "Wiki-Quizzer: skills/_experts/wikiquizzer", "manual"),
            ("bug", "Bugfix-Workflow: skills/_workflows/bugfix-protokoll.md", "manual"),
            ("utf-8", "Encoding-Fix: bach c_encoding_fixer <datei>", "manual"),
        ])
    sql = (SCHEMA_DIR / "migrations" / "045_context_triggers_sichtung.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.executescript(sql)
    got = dict(conn.execute(
        "SELECT trigger_phrase, CASE WHEN is_active THEN hint_text END FROM context_triggers"))
    conn.close()
    assert got == {
        "the": None, "gibt": None, "oder": None, "quiz": None,
        "shutdown": "[THEMA-PAKET] Shutdown",
        "bug": "Bugfix-Workflow: skills/workflows/bugfix-protokoll.md",
        "utf-8": "Encoding-Fix: python tools/file_ops/encoding_fixer.py <datei>",
    }


def test_broken_db_fails_soft(adapter_env, caplog):
    base, db = adapter_env
    db.write_bytes(b"kein sqlite")
    system = injectors.InjectorSystem(base)
    with caplog.at_level("WARNING"):
        assert system.process("ein fehler") == []


def test_substring_matching_and_word_boundaries(tmp_path, monkeypatch):
    """T-20260926-363436040 (5): Falsche Substring-Treffer werden auch im Seam verhindert.

    'abo' darf 'labor' und 'about' nicht treffen.
    'import' darf 'important' nicht treffen.
    'bug' darf 'debug' nicht treffen.
    Echte Treffer ('mein abo', 'import csv', 'ein bug') und deutsche Komposita
    ('Steuererklaerung', 'Arzttermin', 'Medikamenten') muessen weiterhin treffen.
    """
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "config.json").write_text(
        '{"injectors": {"strategy_injector": false, "time_injector": false, "context_injector": true}}',
        encoding="utf-8",
    )
    db = tmp_path / "data" / "bach.db"
    conn = _union_db(db)
    rules = {
        "abo": "Abo-Verwaltung: bach abo list/check/export",
        "import": "Data-Import: tools/data_importer.py",
        "bug": "Bugfix-Workflow: skills/workflows/bugfix-protokoll.md",
        "steuer": "Steuer-Tools: bach steuer status/beleg/posten/export",
        "arzt": "Gesundheit: bach gesundheit termine --upcoming | diagnosen",
        "medikament": "Medikamente: bach gesundheit medikamente",
    }
    conn.executemany(
        "INSERT INTO context_triggers (trigger_phrase, hint_text, source, is_active, status)"
        " VALUES (?,?, 'manual', 1, 'approved')",
        list(rules.items()),
    )
    conn.commit()
    conn.close()

    def check(prompt: str):
        sys_inst = injectors.InjectorSystem(tmp_path)
        res = sys_inst.process(prompt)
        return res[0] if res else None

    assert check("Ich mache ein Experiment im Labor") is None
    assert check("What about the weather?") is None
    assert check("This is an important decision") is None
    assert check("Wir muessen das jetzt debuggen") is None

    assert check("Mein Abo laeuft bald aus") == "[KONTEXT] " + rules["abo"]
    assert check("Hier ist der Import der Datei") == "[KONTEXT] " + rules["import"]
    assert check("Wir haben einen Bug gefunden") == "[KONTEXT] " + rules["bug"]
    assert check("Hilf mir bei der Steuererklärung") == "[KONTEXT] " + rules["steuer"]
    assert check("Ich habe einen Arzttermin") == "[KONTEXT] " + rules["arzt"]
    assert check("Was steht an Medikamenten an?") == "[KONTEXT] " + rules["medikament"]
