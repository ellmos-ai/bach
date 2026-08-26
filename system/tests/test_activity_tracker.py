#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
test_activity_tracker.py - Unit Tests für ActivityTracker (SQ022)
==================================================================

Tests für Inaktivitäts-Erkennung und Auto-Finalize.

Referenz: SQ027 Release-Testpipeline
Datum: 2026-02-20
"""

import pytest
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace

# Füge parent-dir zum Path hinzu
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.activity_tracker import ActivityTracker


def test_memory_decay_module_decays_fact_confidence(tmp_path):
    """Regression for the EOD hook import: tools.memory_decay must exist."""
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE memory_facts (
            id INTEGER PRIMARY KEY,
            category TEXT,
            key TEXT,
            value TEXT,
            confidence REAL,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO memory_facts (category, key, value, confidence) VALUES (?, ?, ?, ?)",
        ("system", "sample", "value", 1.0),
    )
    conn.commit()
    conn.close()

    from tools.memory_decay import MemoryDecay

    result = MemoryDecay(db_path).apply_decay_to_facts(dry_run=False)

    assert result["decayed_facts"] == 1
    conn = sqlite3.connect(str(db_path))
    confidence = conn.execute(
        "SELECT confidence FROM memory_facts WHERE key = 'sample'"
    ).fetchone()[0]
    conn.close()
    assert confidence == pytest.approx(0.98)


def test_memory_decay_dry_run_does_not_change_fact_confidence(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE memory_facts (id INTEGER PRIMARY KEY, key TEXT, confidence REAL)"
    )
    conn.execute("INSERT INTO memory_facts (key, confidence) VALUES (?, ?)", ("sample", 0.9))
    conn.commit()
    conn.close()

    from tools.memory_decay import MemoryDecay

    result = MemoryDecay(db_path).apply_decay_to_facts(dry_run=True)

    assert result["decayed_facts"] == 1
    conn = sqlite3.connect(str(db_path))
    confidence = conn.execute(
        "SELECT confidence FROM memory_facts WHERE key = 'sample'"
    ).fetchone()[0]
    conn.close()
    assert confidence == pytest.approx(0.9)


@pytest.fixture
def temp_db():
    """Erstellt temporäre Test-DB mit system_activity Tabelle."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    # Setup: Erstelle system_activity Tabelle
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE system_activity (
            id INTEGER PRIMARY KEY,
            last_activity TEXT,
            session_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        INSERT INTO system_activity (id, last_activity, session_id)
        VALUES (1, ?, NULL)
    """, (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

    yield db_path

    # Teardown: Lösche temp DB
    db_path.unlink(missing_ok=True)


def test_tick_updates_last_activity(temp_db):
    """Test: tick() aktualisiert last_activity Timestamp."""
    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)

    # Hole ursprünglichen Timestamp
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.execute("SELECT last_activity FROM system_activity WHERE id=1")
    before = cursor.fetchone()[0]
    conn.close()

    # Warte kurz und führe tick aus
    import time
    time.sleep(0.1)

    tracker.tick(session_id="test-session-123")

    # Prüfe ob aktualisiert
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.execute("SELECT last_activity, session_id FROM system_activity WHERE id=1")
    row = cursor.fetchone()
    after = row[0]
    session_id = row[1]
    conn.close()

    assert after > before, "last_activity sollte aktualisiert worden sein"
    assert session_id == "test-session-123", "session_id sollte gesetzt sein"


def test_check_idle_below_threshold(temp_db):
    """Test: check_idle_and_finalize() gibt False wenn nicht idle."""
    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)

    # Aktualisiere last_activity auf jetzt
    tracker.tick()

    # Prüfe Idle (sollte False sein, da gerade erst geticked)
    # Nutze temp_db Parent-Dir als bach_root (vermeidet PermissionError beim Cleanup)
    bach_root = temp_db.parent
    finalized = tracker.check_idle_and_finalize(bach_root)

    assert finalized is False, "Sollte nicht finalisieren wenn unter Schwelle"


def test_check_idle_above_threshold(temp_db, monkeypatch):
    """Test: check_idle_and_finalize() erkennt Idle korrekt."""
    # Kurze Schwelle (1 Sekunde) für schnellen Test
    tracker = ActivityTracker(temp_db, idle_threshold_minutes=0)  # 0 Min = sofort idle

    # Setze last_activity auf vor 2 Sekunden
    past = (datetime.now() - timedelta(seconds=2)).isoformat()
    conn = sqlite3.connect(str(temp_db))
    conn.execute("UPDATE system_activity SET last_activity = ? WHERE id = 1", (past,))
    conn.commit()
    conn.close()

    # Externe Finalisierungsfolgen bleiben isoliert; geprüft wird der echte
    # Idle-Zweig samt erfolgreichem Rückgabevertrag.
    bach_root = temp_db.parent
    shutdown_module = SimpleNamespace(
        ShutdownHandler=lambda _root: SimpleNamespace(
            _complete=lambda _note, dry_run=False: (True, "ok")
        )
    )
    monkeypatch.setitem(sys.modules, "hub.shutdown", shutdown_module)
    monkeypatch.setattr(tracker, "update_directory_truth", lambda _root: None)
    monkeypatch.setattr(tracker, "_export_mirrors", lambda _root: None)
    monkeypatch.setattr(tracker, "_write_daily_log", lambda _root: None)

    finalized = tracker.check_idle_and_finalize(bach_root)

    assert finalized is True


def test_tick_graceful_degradation_no_table(temp_db):
    """Test: tick() crasht nicht wenn Tabelle fehlt."""
    # Lösche Tabelle
    conn = sqlite3.connect(str(temp_db))
    conn.execute("DROP TABLE system_activity")
    conn.commit()
    conn.close()

    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)

    # tick() sollte nicht crashen (silent fail ist OK)
    try:
        tracker.tick()
    except Exception as e:
        pytest.fail(f"tick() sollte nicht crashen: {e}")


def test_multiple_ticks_same_session(temp_db):
    """Test: Mehrere ticks in gleicher Session funktionieren."""
    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)
    session_id = "test-session-multi"

    # 3 ticks
    for i in range(3):
        tracker.tick(session_id=f"{session_id}-{i}")

    # Prüfe ob letzter session_id gespeichert
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.execute("SELECT session_id FROM system_activity WHERE id=1")
    result = cursor.fetchone()[0]
    conn.close()

    assert result == f"{session_id}-2", "Letzter session_id sollte gespeichert sein"


def test_check_idle_no_row(temp_db):
    """Test: check_idle_and_finalize() crasht nicht wenn keine Row."""
    # Lösche Row
    conn = sqlite3.connect(str(temp_db))
    conn.execute("DELETE FROM system_activity WHERE id=1")
    conn.commit()
    conn.close()

    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)

    # Nutze temp_db Parent-Dir als bach_root (vermeidet PermissionError beim Cleanup)
    bach_root = temp_db.parent
    finalized = tracker.check_idle_and_finalize(bach_root)

    assert finalized is False, "Sollte False zurückgeben wenn keine Row"


def test_init_if_needed_creates_row(temp_db):
    """Test: init_if_needed() erstellt Row wenn keine existiert."""
    # Lösche Row
    conn = sqlite3.connect(str(temp_db))
    conn.execute("DELETE FROM system_activity WHERE id=1")
    conn.commit()
    conn.close()

    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)

    # init_if_needed() sollte Row erstellen (braucht bach_root Parameter, auch wenn nicht genutzt)
    bach_root = Path(temp_db).parent.parent  # dummy bach_root
    tracker.init_if_needed(bach_root)

    # Prüfe ob Row existiert
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.execute("SELECT COUNT(*) FROM system_activity WHERE id=1")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1, "init_if_needed() sollte Row erstellen"


def test_check_eod_time_detection():
    """Test: _is_end_of_day() erkennt 23:00 Uhr korrekt."""
    # Importiere private Methode für Test
    from tools.activity_tracker import ActivityTracker

    # Mock-Zeit: 23:05 Uhr sollte True ergeben
    # Mock-Zeit: 14:00 Uhr sollte False ergeben
    # Hinweis: Ohne Mocking schwer testbar, Test dokumentiert nur Intent
    # Tatsächlicher Test würde Time-Mocking brauchen (z.B. freezegun)
    pass  # Placeholder - braucht Time-Mocking-Library


def test_session_id_persistence(temp_db):
    """Test: session_id wird korrekt persistiert und abrufbar."""
    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)
    test_session = "session-abc-123"

    # Setze session_id via tick
    tracker.tick(session_id=test_session)

    # Hole session_id direkt aus DB
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.execute("SELECT session_id FROM system_activity WHERE id=1")
    stored_session = cursor.fetchone()[0]
    conn.close()

    assert stored_session == test_session, "session_id sollte persistiert sein"

    # Zweiter tick mit anderem session_id sollte überschreiben
    new_session = "session-xyz-456"
    tracker.tick(session_id=new_session)

    conn = sqlite3.connect(str(temp_db))
    cursor = conn.execute("SELECT session_id FROM system_activity WHERE id=1")
    updated_session = cursor.fetchone()[0]
    conn.close()

    assert updated_session == new_session, "session_id sollte überschrieben sein"


def test_idle_threshold_calculation(temp_db, monkeypatch):
    """Test: Idle-Threshold wird korrekt auf Basis der last_activity berechnet.

    Hinweis: Prueft nur ob Idle korrekt erkannt wird (unter/ueber Schwelle),
    nicht die Finalize-Logik (die haengt wenn kein echtes BACH-System vorhanden).
    """
    from datetime import datetime, timedelta

    # Pruefe: Unter Schwelle = nicht idle
    tracker_30 = ActivityTracker(temp_db, idle_threshold_minutes=30)

    # Setze last_activity auf 5 Minuten zurueck (weit unter 30 Min Schwelle)
    recent = (datetime.now() - timedelta(minutes=5)).isoformat()
    conn = sqlite3.connect(str(temp_db))
    conn.execute("UPDATE system_activity SET last_activity = ? WHERE id = 1", (recent,))
    conn.commit()
    conn.close()

    result = tracker_30.check_idle_and_finalize(temp_db.parent)
    assert result is False, "Sollte nicht idle sein bei 5 Min / 30 Min Schwelle"

    # Prüfe: Über Schwelle = idle; externe Finalisierungsfolgen werden isoliert.
    tracker_1 = ActivityTracker(temp_db, idle_threshold_minutes=120)

    # Setze last_activity auf 130 Minuten zurueck (ueber 120 Min Schwelle)
    old_activity = (datetime.now() - timedelta(minutes=130)).isoformat()
    conn = sqlite3.connect(str(temp_db))
    conn.execute("UPDATE system_activity SET last_activity = ? WHERE id = 1", (old_activity,))
    conn.commit()
    conn.close()

    shutdown_module = SimpleNamespace(
        ShutdownHandler=lambda _root: SimpleNamespace(
            _complete=lambda _note, dry_run=False: (True, "ok")
        )
    )
    monkeypatch.setitem(sys.modules, "hub.shutdown", shutdown_module)
    monkeypatch.setattr(tracker_1, "update_directory_truth", lambda _root: None)
    monkeypatch.setattr(tracker_1, "_export_mirrors", lambda _root: None)
    monkeypatch.setattr(tracker_1, "_write_daily_log", lambda _root: None)

    result = tracker_1.check_idle_and_finalize(temp_db.parent)

    assert result is True


def test_export_mirrors_uses_exporters_without_cli_subprocess(temp_db, tmp_path, monkeypatch):
    """Regression: Auto-Finalize darf keine rekursive bach.py-export-Kette starten."""
    tracker = ActivityTracker(temp_db, idle_threshold_minutes=30)
    bach_root = tmp_path / "bach"
    (bach_root / "system" / "tools").mkdir(parents=True)

    calls = []

    class FakeExporter:
        def __init__(self, root_path):
            self.root_path = Path(root_path)

        def generate(self):
            calls.append(self.root_path)
            return True, "ok"

    module_specs = {
        "agents_export": "AgentsExporter",
        "partners_export": "PartnersExporter",
        "usecases_export": "UsecasesExporter",
        "chains_export": "ChainsExporter",
        "workflows_export": "WorkflowsExporter",
    }
    for module_name, class_name in module_specs.items():
        monkeypatch.setitem(
            sys.modules,
            module_name,
            SimpleNamespace(**{class_name: FakeExporter}),
        )

    import subprocess

    def fail_subprocess(*_args, **_kwargs):
        raise AssertionError("Mirror export must not shell out to bach.py")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    assert tracker._export_mirrors(bach_root) is True
    assert len(calls) == 5
    assert all(root == bach_root for root in calls)


if __name__ == "__main__":
    # Einzeln ausführbar für schnelles Testing
    pytest.main([__file__, "-v"])
