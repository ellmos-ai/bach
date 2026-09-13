# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer das Domaenen-Writer-Gate (T-20260822-624075478, Punkt 3).

MediPlaner ist der Kanon fuer Medikamente; BACH liest sie ueber die Projektion.
Die alten Schreibpfade bleiben fuer eine Altbestandsuebernahme erhalten, aber nur
gegatet. Diese Tests halten beides fest: dass im Normalbetrieb nichts geschrieben
wird, und dass der ausdrueckliche Migrationslauf weiterhin funktioniert.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.domain_writer_gate import (  # noqa: E402
    LEGACY_WRITE_ENV,
    blocked_reason,
    known_domains,
    legacy_domain_writes_enabled,
)


class TestGate:
    def test_blocks_by_default(self):
        reason = blocked_reason("medication", "gesundheit add-med", {})
        assert reason is not None
        # Die Absage muss den Weg nennen, sonst steht der Nutzer im Regen.
        assert LEGACY_WRITE_ENV in reason
        assert "MediPlaner" in reason

    def test_explicit_migration_run_passes(self):
        assert blocked_reason("medication", "x", {LEGACY_WRITE_ENV: "1"}) is None
        assert blocked_reason("routine", "x", {LEGACY_WRITE_ENV: "true"}) is None

    def test_unknown_domain_raises_instead_of_allowing(self):
        """Ein Tippfehler im Domaenennamen darf keinen Schreibpfad oeffnen."""
        with pytest.raises(ValueError):
            blocked_reason("medikation", "x", {})

    def test_known_domains(self):
        assert known_domains() == ("medication", "routine")

    def test_unset_and_empty_are_off(self):
        assert legacy_domain_writes_enabled({}) is False
        assert legacy_domain_writes_enabled({LEGACY_WRITE_ENV: ""}) is False
        assert legacy_domain_writes_enabled({LEGACY_WRITE_ENV: "0"}) is False


def _medication_db(tmp_path: Path) -> Path:
    """Minimale bach.db mit den zwei Tabellen, die der Import anfasst."""
    path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE health_contacts (
            id INTEGER PRIMARY KEY, name TEXT, institution TEXT, specialty TEXT,
            phone TEXT, email TEXT, address TEXT, notes TEXT, is_active INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE health_medications (
            id INTEGER PRIMARY KEY, name TEXT, active_ingredient TEXT, dosage TEXT,
            schedule TEXT, diagnosis_id INTEGER, start_date TEXT, status TEXT,
            notes TEXT, side_effects TEXT, contact_id INTEGER, end_date TEXT,
            created_at TEXT, updated_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    return path


class TestMediplanerImportIsGated:
    @pytest.fixture
    def handler_and_db(self, tmp_path, monkeypatch):
        from hub import mediplaner

        db_path = _medication_db(tmp_path)
        handler = mediplaner.MediPlanerHandler(tmp_path)
        monkeypatch.setattr(
            handler, "_get_db", lambda: sqlite3.connect(str(db_path)), raising=False
        )
        payload = {
            "schema_version": mediplaner.SCHEMA_VERSION,
            "doctor_contacts": [{"id": 1, "name": "Dr. Test"}],
            "medications": [],
        }
        export = tmp_path / "export.json"
        export.write_text(json.dumps(payload), encoding="utf-8")
        return handler, db_path, export

    def _rows(self, db_path: Path, table: str) -> int:
        conn = sqlite3.connect(str(db_path))
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def test_import_is_refused_and_writes_nothing(self, handler_and_db, monkeypatch):
        handler, db_path, export = handler_and_db
        monkeypatch.delenv(LEGACY_WRITE_ENV, raising=False)

        ok, message = handler._import(["--file", str(export)])

        assert ok is False
        assert LEGACY_WRITE_ENV in message
        assert self._rows(db_path, "health_contacts") == 0

    def test_migration_run_still_imports(self, handler_and_db, monkeypatch):
        handler, db_path, export = handler_and_db
        monkeypatch.setenv(LEGACY_WRITE_ENV, "1")

        ok, _message = handler._import(["--file", str(export)])

        assert ok is True
        assert self._rows(db_path, "health_contacts") == 1
