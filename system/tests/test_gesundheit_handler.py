#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer GesundheitHandler"""

import sys
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.gesundheit import GesundheitHandler


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
    icd_code TEXT,
    diagnosis_date DATE,
    status TEXT DEFAULT 'aktiv' CHECK(status IN ('aktiv', 'in_abklaerung', 'hypothese', 'widerlegt', 'geheilt')),
    severity TEXT CHECK(severity IN ('leicht', 'mittel', 'schwer')),
    doctor_id INTEGER REFERENCES health_contacts(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active_ingredient TEXT,
    dosage TEXT,
    schedule TEXT,
    diagnosis_id INTEGER REFERENCES health_diagnoses(id),
    start_date DATE,
    end_date DATE,
    status TEXT DEFAULT 'aktiv' CHECK(status IN ('aktiv', 'pausiert', 'beendet')),
    notes TEXT,
    side_effects TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_lab_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    reference_min REAL,
    reference_max REAL,
    test_date DATE NOT NULL,
    is_abnormal INTEGER DEFAULT 0,
    doctor_id INTEGER REFERENCES health_contacts(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doctor_id INTEGER REFERENCES health_contacts(id),
    appointment_date DATETIME NOT NULL,
    duration_minutes INTEGER DEFAULT 30,
    appointment_type TEXT,
    status TEXT DEFAULT 'geplant' CHECK(status IN ('geplant', 'bestaetigt', 'abgesagt', 'verschoben', 'erledigt')),
    notes TEXT,
    reminder_sent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_type TEXT CHECK(doc_type IN ('befund', 'arztbrief', 'labor', 'rezept', 'studie', 'sonstiges')),
    file_path TEXT,
    content_summary TEXT,
    document_date DATE,
    doctor_id INTEGER REFERENCES health_contacts(id),
    diagnosis_id INTEGER REFERENCES health_diagnoses(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vorsorge_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    untersuchung TEXT NOT NULL,
    turnus_monate INTEGER NOT NULL,
    zuletzt DATE,
    naechster_termin DATE,
    doctor_id INTEGER REFERENCES health_contacts(id),
    ab_alter INTEGER,
    bis_alter INTEGER,
    geschlecht TEXT CHECK(geschlecht IN ('m', 'w', 'alle')),
    kategorie TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
);
"""


@pytest.fixture
def health_env(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()

    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.close()

    handler = GesundheitHandler(system_dir)
    handler.user_db_path = db_path
    return handler, db_path


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, health_env):
        h, _ = health_env
        assert h.profile_name == "gesundheit"

    def test_target_file(self, health_env):
        h, db = health_env
        assert h.target_file == db

    def test_operations(self, health_env):
        h, _ = health_env
        ops = h.get_operations()
        assert "status" in ops
        assert "contacts" in ops
        assert "meds" in ops
        assert "reminders" in ops
        assert "appointments" in ops
        assert "vorsorge" in ops


# ================================================================
# ROUTING
# ================================================================

class TestRouting:
    def test_unknown_operation(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg or "nonexistent" in msg

    def test_empty_defaults_to_help(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("", [])
        assert ok is True
        assert "gesundheit" in msg.lower() or "operation" in msg.lower() or "help" in msg.lower()

    def test_help(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("help", [])
        assert ok is True


# ================================================================
# REMINDERS (regression test for column-name fix)
# ================================================================

class TestReminders:
    def test_reminders_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("reminders", [])
        assert ok is True
        assert "Erinnerungen" in msg or "reminders" in msg.lower() or "Keine" in msg

    def test_reminders_with_active_meds(self, health_env):
        h, db = health_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_medications (name, dosage, schedule, status) VALUES (?, ?, ?, ?)",
            ("Ibuprofen", "400mg", "bei Bedarf", "aktiv")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("reminders", [])
        assert ok is True
        assert "Ibuprofen" in msg

    def test_reminders_with_due_vorsorge(self, health_env):
        h, db = health_env
        past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO vorsorge_checks (untersuchung, turnus_monate, naechster_termin, kategorie) VALUES (?, ?, ?, ?)",
            ("Zahnreinigung", 6, past, "Zahn")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("reminders", [])
        assert ok is True
        assert "Zahnreinigung" in msg

    def test_reminders_with_upcoming_appointment(self, health_env):
        """Regression: Verifies correct column names (appointment_date, title, status='abgesagt')."""
        h, db = health_env
        future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d 10:00:00")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_contacts (name, specialty) VALUES (?, ?)",
            ("Dr. Meier", "Allgemein")
        )
        conn.execute(
            "INSERT INTO health_appointments (title, doctor_id, appointment_date, status) VALUES (?, ?, ?, ?)",
            ("Kontrolluntersuchung", 1, future, "geplant")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("reminders", [])
        assert ok is True
        assert "Kontrolluntersuchung" in msg
        assert "Dr. Meier" in msg

    def test_reminders_cancelled_excluded(self, health_env):
        """Abgesagte Termine duerfen nicht in Reminders erscheinen."""
        h, db = health_env
        future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d 10:00:00")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_appointments (title, doctor_id, appointment_date, status) VALUES (?, ?, ?, ?)",
            ("Abgesagter Termin", None, future, "abgesagt")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("reminders", [])
        assert ok is True
        assert "Abgesagter Termin" not in msg


# ================================================================
# STATUS
# ================================================================

class TestStatus:
    def test_status_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("status", [])
        assert ok is True

    def test_status_with_data(self, health_env):
        h, db = health_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_contacts (name, specialty) VALUES (?, ?)",
            ("Dr. Schmidt", "Orthopädie")
        )
        conn.execute(
            "INSERT INTO health_diagnoses (diagnosis_name, icd_code, status) VALUES (?, ?, ?)",
            ("Rückenschmerzen", "M54.5", "aktiv")
        )
        conn.execute(
            "INSERT INTO health_medications (name, status) VALUES (?, ?)",
            ("Paracetamol", "aktiv")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("status", [])
        assert ok is True


# ================================================================
# CONTACTS
# ================================================================

class TestContacts:
    def test_contacts_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("contacts", [])
        assert ok is True

    def test_contacts_with_data(self, health_env):
        h, db = health_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_contacts (name, specialty, phone) VALUES (?, ?, ?)",
            ("Dr. Test", "HNO", "0800-12345")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("contacts", [])
        assert ok is True
        assert "Dr. Test" in msg


# ================================================================
# APPOINTMENTS
# ================================================================

class TestAppointments:
    def test_appointments_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("appointments", [])
        assert ok is True

    def test_add_appointment_no_args(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("add-appointment", [])
        assert ok is False or "titel" in msg.lower() or "syntax" in msg.lower() or "parameter" in msg.lower()


# ================================================================
# VORSORGE
# ================================================================

class TestVorsorge:
    def test_vorsorge_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("vorsorge", [])
        assert ok is True

    def test_vorsorge_faellig_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("vorsorge-faellig", [])
        assert ok is True

    def test_vorsorge_with_data(self, health_env):
        h, db = health_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO vorsorge_checks (untersuchung, turnus_monate, naechster_termin, kategorie) VALUES (?, ?, ?, ?)",
            ("Hautkrebsscreening", 24, "2027-01-01", "Krebs")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("vorsorge", [])
        assert ok is True
        assert "Hautkrebsscreening" in msg


# ================================================================
# MEDS
# ================================================================

class TestMeds:
    def test_meds_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("meds", [])
        assert ok is True

    def test_meds_with_data(self, health_env):
        h, db = health_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_medications (name, dosage, schedule, status) VALUES (?, ?, ?, ?)",
            ("Aspirin", "100mg", "taeglich", "aktiv")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("meds", [])
        assert ok is True
        assert "Aspirin" in msg


# ================================================================
# LABS
# ================================================================

class TestLabs:
    def test_labs_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("labs", [])
        assert ok is True


# ================================================================
# DIAGNOSES
# ================================================================

class TestDiagnoses:
    def test_diagnoses_empty(self, health_env):
        h, _ = health_env
        ok, msg = h.handle("diagnoses", [])
        assert ok is True

    def test_diagnoses_with_data(self, health_env):
        h, db = health_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO health_diagnoses (diagnosis_name, icd_code, status, severity) VALUES (?, ?, ?, ?)",
            ("Migräne", "G43.0", "aktiv", "mittel")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("diagnoses", [])
        assert ok is True
        assert "Migr" in msg
