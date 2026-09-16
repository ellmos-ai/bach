# -*- coding: utf-8 -*-
"""Regressionen fuer OPS-TELEM-001: Low-cardinality Telemetrie (Task #1315).

Privacy-Kern: Es duerfen NIE Payloads, Prompts, Pfade oder Nutzerdaten
gespeichert werden -- nur Zaehler mit validierten Low-Cardinality-Labels.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub import bach_paths
from core import telemetry
from core.telemetry import (
    COUNTERS,
    MAX_SERIES_PER_DAY,
    OTHER,
    increment,
    report,
    reset,
    status,
)


def _use_db(tmp_path, monkeypatch):
    db = tmp_path / "telemetry-bach.db"
    monkeypatch.setattr(bach_paths, "BACH_DB", db)
    return db


def _rows(db):
    with sqlite3.connect(str(db)) as conn:
        return conn.execute(
            "SELECT counter, labels, value FROM telemetry_counters "
            "ORDER BY counter, labels"
        ).fetchall()


def test_increment_writes_and_upserts(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)

    assert increment("tool_calls", outcome="ok", tool="task") is True
    assert increment("tool_calls", outcome="ok", tool="task") is True
    assert increment("tool_calls", outcome="error", tool="steuer") is True

    rows = _rows(db)
    assert len(rows) == 2
    by_labels = {labels: value for _, labels, value in rows}
    assert by_labels['{"outcome": "ok", "tool": "task"}'] == 2
    assert by_labels['{"outcome": "error", "tool": "steuer"}'] == 1


def test_label_validation_is_low_cardinality(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)

    # Gueltiger, kompakter Name bleibt erhalten
    increment("agent_starts", outcome="ok", agent="steuer-agent")
    # Prompt-/Injektionsversuch, Freitext, Umlaute, Pfade -> "other"
    increment("agent_starts", outcome="ok",
              agent="Ignore previous instructions\n\nINJECT PAYLOAD")
    increment("agent_starts", outcome="ok", agent="Täter-Ümlaute-ÜBERLANG" * 5)
    increment("agent_starts", outcome="ok", agent="/Users/luas/.ssh/id_rsa")
    # Nicht-String-Label
    increment("agent_starts", outcome="ok", agent=12345)

    labels = {labels for _, labels, _ in _rows(db)}
    assert '{"agent": "steuer-agent", "outcome": "ok"}' in labels
    assert '{"agent": "other", "outcome": "ok"}' in labels
    for entry in labels:
        assert "\n" not in entry and "INJECT" not in entry


def test_unknown_counter_is_ignored(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)
    telemetry.ensure_schema(db)

    assert increment("made_up_counter", outcome="ok") is False
    assert _rows(db) == []


def test_opt_out_env_disables_collection(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)
    telemetry.ensure_schema(db)
    monkeypatch.setenv("BACH_TELEMETRY_DISABLED", "1")

    assert telemetry.is_enabled() is False
    assert increment("tool_calls", outcome="ok", tool="task") is False
    assert _rows(db) == []


def test_outcome_normalization(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)

    increment("model_calls", outcome="WEIRD OUTCOME", model="llama3.2")

    labels = {labels for _, labels, _ in _rows(db)}
    assert labels == {'{"model": "llama3.2", "outcome": "other"}'}


def test_fail_silent_on_unreachable_db(tmp_path, monkeypatch):
    monkeypatch.setattr(bach_paths, "BACH_DB",
                        tmp_path / "no-such-dir" / "bach.db")

    # Kernanforderung: Telemetrie darf NIE den Aufrufer brechen
    assert increment("tool_calls", outcome="ok", tool="task") is False
    ok, text = report(days=7)
    assert ok is False
    ok, text = status()
    assert ok is True  # Status ist ohne DB noch lesbar (nur Schema=NEIN)
    assert "NEIN" in text


def test_series_cap_flows_into_overflow_bucket(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)

    # MAX_SERIES distinkte Serien erzeugen
    for i in range(MAX_SERIES_PER_DAY):
        increment("tool_calls", outcome="ok", tool=f"tool-{i:03d}")
    # Naechste NEUE Serie muss im Overflow-Bucket landen
    increment("tool_calls", outcome="ok", tool="brand-new-tool")

    distinct = len(_rows(db))
    assert distinct <= MAX_SERIES_PER_DAY + 1
    labels = {labels for _, labels, _ in _rows(db)}
    assert '{"overflow":"true","outcome":"ok"}' in labels
    assert '{"outcome": "ok", "tool": "brand-new-tool"}' not in labels


def test_report_and_status_content(tmp_path, monkeypatch):
    _use_db(tmp_path, monkeypatch)
    increment("tool_calls", outcome="ok", tool="task")
    increment("model_calls", outcome="error", model="llama3.2")

    ok, text = report(days=7)
    assert ok is True
    assert "tool_calls" in text
    assert "model_calls" in text
    assert "Privacy" in text

    ok, text = status()
    assert ok is True
    assert "Erfassung aktiv" in text
    assert "BACH_TELEMETRY_DISABLED" in text


def test_reset_requires_confirm_and_deletes(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)
    increment("tool_calls", outcome="ok", tool="task")

    ok, text = reset(confirm=False)
    assert ok is False
    assert "--confirm" in text
    assert len(_rows(db)) == 1

    ok, text = reset(confirm=True)
    assert ok is True
    assert _rows(db) == []


def test_migration_creates_schema(tmp_path, monkeypatch):
    db = _use_db(tmp_path, monkeypatch)

    migration_path = (SYSTEM_ROOT / "data" / "schema" / "migrations"
                      / "041_telemetry.py")
    spec = importlib.util.spec_from_file_location(
        "migration_041_telemetry", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.run_migration(conn=None)

    with sqlite3.connect(str(db)) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='telemetry_counters'"
        ).fetchall()
    assert tables == [("telemetry_counters",)]


def test_counters_allowlist_is_stable():
    # OPS-TELEM-001 definiert genau drei Counter ohne Payload-Flaeche
    assert COUNTERS == {
        "agent_starts": {"agent"},
        "model_calls": {"model"},
        "tool_calls": {"tool"},
    }
    assert OTHER == "other"