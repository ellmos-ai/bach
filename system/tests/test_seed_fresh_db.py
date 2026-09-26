# -*- coding: utf-8 -*-
"""Frische DBs bekommen die Daten-Seeds der Migrationen (T-20260926-244294919).

schema.sql traegt nur Struktur; baseline_migrations bucht Migrationen ohne sie
auszufuehren. Die als ``-- BACH-SEED: idempotent`` markierten Migrationen
(context_triggers fuer Strategy 044, Tool-Warn 046, Between 047) muessen auf
einer frischen DB trotzdem ankommen, sonst bleibt BACH still beim
Injektor-Altpfad (S3 von T-20260920-823767362).
"""
import sqlite3
from pathlib import Path

import pytest

import hub.bach_paths as bach_paths
import hub.memory_hook_provider as mhp
from core.db import Database

SYSTEM_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SYSTEM_DIR / "data" / "schema"
SEEDS = ["044_strategy_triggers.sql", "046_tool_warn_triggers.sql", "047_between_triggers.sql"]


def _counts(path):
    conn = sqlite3.connect(path)
    rows = dict(conn.execute(
        "SELECT source, COUNT(*) FROM context_triggers WHERE is_active = 1 GROUP BY source"))
    conn.close()
    return rows


def test_marked_seed_files():
    marked = [p.name for p in sorted((SCHEMA_DIR / "migrations").glob("*.sql"))
              if Database.SEED_MARKER in p.read_text(encoding="utf-8").splitlines()[:5]]
    assert marked == SEEDS


def test_fresh_db_gets_seeds_idempotently(tmp_path):
    db = Database(tmp_path / "bach.db", SCHEMA_DIR)
    db.init_schema()
    db.baseline_migrations()
    assert db.apply_seed_migrations() == SEEDS
    assert db.apply_seed_migrations() == SEEDS  # zweiter Lauf: No-op
    assert _counts(tmp_path / "bach.db") == {"strategy": 6, "tool_warn": 1, "between": 1}


def test_app_fresh_db_path_applies_seeds(tmp_path, monkeypatch):
    from core.app import App
    fresh = tmp_path / "fresh" / "bach.db"
    fresh.parent.mkdir()
    monkeypatch.setattr(bach_paths, "BACH_DB", fresh)
    App(SYSTEM_DIR).db
    assert _counts(fresh) == {"strategy": 6, "tool_warn": 1, "between": 1}


@pytest.mark.skipif(not hasattr(mhp, "CLI_ONLY_INJECTORS"), reason="Seam vor S3 Einheit 4")
def test_fresh_db_is_taken_over_by_seam(tmp_path, monkeypatch):
    pytest.importorskip("memoryhooker.triggers")
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(mhp.LEGACY_INJECTORS_ENV, raising=False)
    monkeypatch.delenv(mhp.CONTEXT_TRIGGERS_DB_ENV, raising=False)
    db = Database(tmp_path / "bach.db", SCHEMA_DIR)
    db.init_schema()
    db.baseline_migrations()
    db.apply_seed_migrations()
    hook = mhp.ExternalMemoryHook(db_path=tmp_path / "bach.db", config_path=tmp_path / "none.toml")
    assert hook.handled_injectors() == frozenset({"strategy", "tool_warn", "between"})
