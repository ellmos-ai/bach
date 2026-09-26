# -*- coding: utf-8 -*-
"""Paritaet alt gegen neu fuer Injektoren, die an memoryhooker wandern.

S3 von T-20260920-823767362 (Gemeinsames Gedaechtnis BACH = OCEAN): ein
BACH-Injektor wird erst abgeschaltet, wenn der memoryhooker-Pfad auf
identischen Eingaben dasselbe liefert. Einheit 1: StrategyInjector.

alt = tools/injectors.py (StrategyInjector / InjectorSystem mit Cooldown)
neu = memoryhooker.triggers.evaluate_triggers ueber BachMemoryBackend auf einer
      Temp-DB mit Vertrags-DDL (memory_union) und Seed-Migration 044.
"""
import importlib.util
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("memoryhooker.triggers")

import hub.memory_hook_provider as mhp
from memoryhooker.config import Config, TriggersConfig
from memoryhooker.state import SessionState
from memoryhooker.triggers import evaluate_triggers

SYSTEM_DIR = Path(__file__).resolve().parent.parent
SCHEMA_DIR = SYSTEM_DIR / "data" / "schema"
sys.path.insert(0, str(SYSTEM_DIR / "tools"))
import injectors  # noqa: E402

PROMPTS = [
    "Ich habe einen Fehler im Code",
    "ERROR beim Build",
    "der Bug ist kaputt",
    "das ist komplex und kompliziert",
    "eine grossartige Idee",
    "ich bin blockiert",
    "I am stuck here",
    "ich komme nicht weiter",
    "wir haben wenig Zeit, es eilt",
    "mach schnell",
    "ich bin unsicher, weiss nicht",
    "vielleicht ist es unklar",
    "fertig! geschafft",
    "task done 42",
    "erledigt",
    "komplexer Fehler, ich bin blockiert",
    "ein ganz normaler Satz ohne Stichwort",
    "",
    "Überspringen? Nein, schwierig.",
]
PROMPTS += [phrase for group in injectors.StrategyInjector.STRATEGIES for phrase in group]


def _union_module():
    spec = importlib.util.spec_from_file_location(
        "bach_memory_union_parity", SCHEMA_DIR / "memory_union" / "memory_union.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seeded_db(tmp_path):
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    _union_module().create_union_schema(conn)
    # gleichlautende manual-Trigger duerfen den Seed nicht verdraengen
    conn.execute("INSERT INTO context_triggers (trigger_phrase, hint_text) VALUES ('fehler', 'x')")
    conn.execute("INSERT INTO context_triggers (trigger_phrase, hint_text) VALUES ('bug', 'y')")
    seed = (SCHEMA_DIR / "migrations" / "044_strategy_triggers.sql").read_text(encoding="utf-8")
    conn.executescript(seed)
    conn.executescript(seed)  # idempotent
    conn.commit()
    conn.close()
    return db


def _neu(db, cooldown=0):
    config = Config(triggers=TriggersConfig(sources=["strategy"], cooldowns={"strategy": cooldown}))
    return config, mhp.BachMemoryBackend(db_path=db)


def test_seed_matches_legacy_strategies(seeded_db):
    conn = sqlite3.connect(seeded_db)
    rows = conn.execute(
        "SELECT trigger_phrase, hint_text FROM context_triggers WHERE source='strategy' ORDER BY id"
    ).fetchall()
    conn.close()
    expected = [("|".join(group), f"[STRATEGIE] {msgs[-1]}")
                for group, msgs in injectors.StrategyInjector.STRATEGIES.items()]
    assert rows == expected


@pytest.mark.parametrize("prompt", PROMPTS)
def test_strategy_parity_per_prompt(seeded_db, prompt):
    alt = injectors.StrategyInjector.check(prompt)
    config, backend = _neu(seeded_db)
    neu = evaluate_triggers(prompt, config, backend, SessionState(), now=0)
    assert neu == ([alt] if alt else [])


def test_strategy_parity_cooldown_sequence(seeded_db, tmp_path, monkeypatch):
    """Gleiche Prompt-Folge, feste Uhr: alt (CooldownManager) == neu (je Quelle)."""
    assert injectors.CooldownManager.DEFAULT_COOLDOWNS["strategy"] == mhp.HOOKER_INJECTORS["strategy"]
    base = tmp_path / "bachbase"
    (base / "data").mkdir(parents=True)
    (base / "config.json").write_text(
        '{"injectors": {"context_injector": false, "time_injector": false,'
        ' "between_injector": false, "strategy_injector": true}}', encoding="utf-8")

    clock = {"now": datetime(2026, 9, 26, 12, 0, 0)}

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(injectors, "datetime", _Clock)
    system = injectors.InjectorSystem(base)
    config, backend = _neu(seeded_db, cooldown=mhp.HOOKER_INJECTORS["strategy"])
    state = SessionState()
    start = clock["now"]
    for offset, prompt in [(0, "fehler"), (30, "blockiert"), (119, "komplex"), (120, "komplex"),
                           (121, "nichts"), (130, "unsicher"), (400, "done")]:
        clock["now"] = start + timedelta(seconds=offset)
        alt = system.process(prompt)
        neu = evaluate_triggers(prompt, config, backend, state,
                                now=clock["now"].timestamp())
        assert neu == alt, (offset, prompt)


def test_legacy_skip_removes_only_strategy(tmp_path):
    base = tmp_path / "bachbase"
    (base / "data").mkdir(parents=True)
    (base / "config.json").write_text(
        '{"injectors": {"context_injector": false, "time_injector": false}}', encoding="utf-8")
    system = injectors.InjectorSystem(base)
    assert system.process("fehler", skip={"strategy"}) == []
    assert system.process("fehler") == ["[STRATEGIE] Erst verstehen, dann fixen."]


class TestSeamTakeover:

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
        monkeypatch.delenv(mhp.LEGACY_INJECTORS_ENV, raising=False)

    def test_handled_and_injected_once(self, seeded_db):
        hook = mhp.ExternalMemoryHook(db_path=seeded_db, config_path=seeded_db.parent / "none.toml")
        assert hook.handled_injectors() == frozenset({"strategy"})
        first = hook.hook_context("ich bin blockiert", "chat-1")
        assert "[STRATEGIE] Frage an User in chat.json notieren." in first
        assert "[STRATEGIE]" not in (hook.hook_context("ich bin blockiert", "chat-1") or "")

    @pytest.mark.parametrize("env,value", [("LEGACY", "strategy"), ("ROLLBACK", "0")])
    def test_rueckweg(self, seeded_db, monkeypatch, env, value):
        name = mhp.LEGACY_INJECTORS_ENV if env == "LEGACY" else mhp.ROLLBACK_ENV
        monkeypatch.setenv(name, value)
        hook = mhp.ExternalMemoryHook(db_path=seeded_db, config_path=seeded_db.parent / "none.toml")
        assert hook.handled_injectors() == frozenset()
        assert "[STRATEGIE]" not in (hook.hook_context("ich bin blockiert", "chat-2") or "")

    def test_without_seed_bach_keeps_legacy(self, tmp_path):
        db = tmp_path / "bach.db"
        conn = sqlite3.connect(db)
        _union_module().create_union_schema(conn)
        conn.close()
        hook = mhp.ExternalMemoryHook(db_path=db, config_path=tmp_path / "none.toml")
        assert hook.handled_injectors() == frozenset()
