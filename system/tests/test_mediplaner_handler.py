#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer MediPlanerHandler."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.mediplaner import MediPlanerHandler, SCHEMA_VERSION


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS health_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    institution TEXT,
    specialty TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_name TEXT NOT NULL,
    doctor_id INTEGER REFERENCES health_contacts(id)
);

CREATE TABLE IF NOT EXISTS health_medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active_ingredient TEXT,
    dosage TEXT,
    schedule TEXT,
    diagnosis_id INTEGER REFERENCES health_diagnoses(id),
    status TEXT DEFAULT 'aktiv',
    notes TEXT,
    side_effects TEXT
);
"""


@pytest.fixture
def mediplaner_env(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    handler = MediPlanerHandler(system_dir)
    handler.user_db_path = db_path
    return handler, db_path


def test_export_payload_contains_contacts_and_meds(mediplaner_env):
    handler, db = mediplaner_env
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO health_contacts (name, specialty, institution, phone) VALUES (?, ?, ?, ?)",
        ("Dr. Meier", "Hausarzt", "Praxis", "030-123"),
    )
    conn.execute("INSERT INTO health_diagnoses (diagnosis_name, doctor_id) VALUES (?, ?)", ("Test", 1))
    conn.execute(
        "INSERT INTO health_medications (name, active_ingredient, dosage, schedule, diagnosis_id, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("Ibuprofen", "Ibuprofen", "400 mg", "morgens, bei Bedarf", 1, "aktiv"),
    )
    conn.commit()
    conn.close()

    ok, text = handler.handle("export", [])
    payload = json.loads(text)

    assert ok is True
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["doctor_contacts"][0]["name"] == "Dr. Meier"
    assert payload["medications"][0]["doctor_id"] == 1
    assert payload["medications"][0]["morgens"] == 1
    assert payload["medications"][0]["bedarf"] == 1


def test_import_payload_merges_contacts_and_meds(mediplaner_env, tmp_path):
    handler, db = mediplaner_env
    payload = {
        "schema_version": SCHEMA_VERSION,
        "clients": [{"id": 1, "first_name": "BACH", "last_name": "Import", "birthdate": "01.01.1900"}],
        "doctor_contacts": [{"id": 7, "name": "Dr. Haus", "specialty": "Hausarzt", "institution": "Praxis"}],
        "medications": [{"id": 8, "client_id": 1, "doctor_id": 7, "name": "L-Thyroxin", "dose_value": "75 mcg", "morgens": 1, "aktiv": 1}],
        "inventory": [],
        "settings": [],
    }
    path = tmp_path / "mediplaner-export-v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    first_ok, first_msg = handler.handle("import", ["--file", str(path)])
    second_ok, second_msg = handler.handle("import", ["--file", str(path)])

    assert first_ok is True
    assert "contacts_inserted=1" in first_msg
    assert "meds_inserted=1" in first_msg
    assert second_ok is True
    assert "contacts_inserted=0" in second_msg
    assert "meds_inserted=0" in second_msg

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM health_contacts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM health_medications").fetchone()[0] == 1
    conn.close()


def test_help_lists_export_and_import(mediplaner_env):
    handler, _ = mediplaner_env
    ok, text = handler.handle("help", [])

    assert ok is True
    assert "bach mediplaner export" in text
    assert "bach mediplaner import" in text
