# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for PartnerHandler (hub/partner.py)."""

import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _create_partner_recognition_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS partner_recognition (
            id INTEGER PRIMARY KEY,
            partner_name TEXT,
            partner_type TEXT,
            api_endpoint TEXT,
            capabilities TEXT,
            cost_tier INTEGER DEFAULT 1,
            token_zone TEXT DEFAULT 'zone_1',
            priority INTEGER DEFAULT 50,
            status TEXT DEFAULT 'active',
            success_rate REAL DEFAULT 1.0,
            notes TEXT
        )
    """)


@pytest.fixture
def base_path(tmp_path):
    """Create a minimal BACH directory structure."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return tmp_path


@pytest.fixture
def partner_db(base_path):
    """Create a test DB with partner_recognition table."""
    db_path = base_path / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_partner_recognition_table(conn)
    conn.execute("""
        INSERT INTO partner_recognition (partner_name, partner_type, api_endpoint,
                                          capabilities, cost_tier, token_zone, priority, status, notes)
        VALUES ('Claude', 'api', 'https://api.anthropic.com', '["coding", "analysis"]',
                3, 'zone_1', 90, 'active', 'Primary AI Partner')
    """)
    conn.execute("""
        INSERT INTO partner_recognition (partner_name, partner_type, api_endpoint,
                                          capabilities, cost_tier, token_zone, priority, status, notes)
        VALUES ('Ollama', 'local', NULL, '["chat"]',
                0, 'zone_3', 50, 'active', 'Local AI')
    """)
    conn.commit()
    conn.close()
    return db_path


class TestPartnerHandlerInit:
    def test_init_no_double_super(self, base_path):
        """Regression: super().__init__ was called twice (fixed)."""
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            assert handler.base_path == base_path

    def test_profile_name(self, base_path):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            assert handler.profile_name == "partner"


class TestLoadPartnersFromDb:
    def test_empty_db(self, base_path):
        db_path = base_path / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        _create_partner_recognition_table(conn)
        conn.commit()
        conn.close()

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path
            result = handler._load_partners_from_db()
            assert result["partners"] == []
            assert "delegation_zones" in result

    def test_loads_partners(self, base_path, partner_db):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = partner_db
            result = handler._load_partners_from_db()
            assert len(result["partners"]) == 2
            claude = next(p for p in result["partners"] if p["name"] == "Claude")
            assert claude["type"] == "external_ai"
            assert claude["token_cost"] == "high"
            assert claude["capabilities"] == ["coding", "analysis"]
            assert claude["priority"] == 90

    def test_zone_mapping(self, base_path, partner_db):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = partner_db
            result = handler._load_partners_from_db()
            ollama = next(p for p in result["partners"] if p["name"] == "Ollama")
            assert ollama["delegation_zones"] == [3, 4]

    def test_missing_db(self, base_path):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = base_path / "nonexistent.db"
            result = handler._load_partners_from_db()
            assert result["partners"] == []

    def test_invalid_capabilities_json(self, base_path):
        db_path = base_path / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        _create_partner_recognition_table(conn)
        conn.execute("""
            INSERT INTO partner_recognition (partner_name, partner_type, capabilities)
            VALUES ('Broken', 'api', 'not-valid-json')
        """)
        conn.commit()
        conn.close()

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path
            result = handler._load_partners_from_db()
            broken = result["partners"][0]
            assert broken["capabilities"] == []


class TestCanonicalDbUsage:
    def test_get_current_zone_uses_handler_db_path(self, base_path, tmp_path):
        db_path = tmp_path / "canonical" / "bach.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitor_tokens (
                timestamp TEXT,
                budget_percent REAL
            )
        """)
        conn.execute("""
            INSERT INTO monitor_tokens (timestamp, budget_percent)
            VALUES (?, 85.0)
        """, (datetime.now().isoformat(),))
        conn.commit()
        conn.close()

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path

            assert handler._get_current_zone() == 4

    def test_get_current_zone_returns_unknown_without_telemetry(self, base_path, partner_db):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = partner_db

            assert handler._get_current_zone() is None

    def test_delegate_stops_when_telemetry_is_unknown(self, base_path, partner_db):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = partner_db
            data = handler._load_partners_from_db()

            ok, text = handler._delegate(
                data,
                ["Coding Aufgabe delegieren"],
                dry_run=True,
            )

        assert ok is False
        assert "Token-Telemetrie unbekannt" in text
        assert "keine automatische Delegation" in text

    @pytest.mark.parametrize("invalid_zone", ["0", "-1", "5"])
    def test_delegate_rejects_invalid_zone_override(
        self,
        base_path,
        partner_db,
        invalid_zone,
    ):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = partner_db
            data = handler._load_partners_from_db()

            ok, text = handler._delegate(
                data,
                ["Coding Aufgabe delegieren", f"--zone={invalid_zone}"],
                dry_run=True,
            )

        assert ok is False
        assert "Ungültige Zone" in text

    def test_get_allowed_partners_uses_handler_db_path(self, base_path, tmp_path):
        db_path = tmp_path / "canonical" / "bach.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS delegation_rules (
                zone TEXT,
                allowed_partners TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            INSERT INTO delegation_rules (zone, allowed_partners, status)
            VALUES ('zone_2', '[\"gemini\", \"ollama\"]', 'active')
        """)
        conn.commit()
        conn.close()

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path

            assert handler._get_allowed_partners_from_db(2) == ["gemini", "ollama"]

    def test_delegate_uses_handler_db_for_fahrtenbuch(self, base_path, tmp_path):
        db_path = tmp_path / "canonical" / "bach.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        _create_partner_recognition_table(conn)
        conn.execute("""
            INSERT INTO partner_recognition (partner_name, partner_type, api_endpoint,
                                              capabilities, cost_tier, token_zone, priority, status, notes)
            VALUES ('Claude', 'api', 'https://api.anthropic.com', '["coding"]',
                    3, 'zone_1', 90, 'active', 'Primary AI Partner')
        """)
        conn.commit()
        conn.close()

        strecken_profil = SimpleNamespace(
            typ="Feldweg",
            typ_code=1,
            schwierigkeit=1,
            etappen=1,
            empfohlener_gang="D",
        )
        gas_stellung = SimpleNamespace(
            level=10,
            strategie=SimpleNamespace(value="direkt"),
            token_multiplikator=0.6,
            prompt_prefix="",
            prompt_suffix="",
        )
        analyser = MagicMock()
        analyser.analysiere.return_value = strecken_profil
        bordcomputer = MagicMock()
        bordcomputer.is_available.return_value = True
        bordcomputer.check_overkill.return_value = None
        fahrtenbuch = MagicMock()

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", True), \
             patch("hub.partner.get_strecken_analyser", return_value=analyser), \
             patch("hub.partner.berechne_gas", return_value=gas_stellung), \
             patch("hub.partner.get_bordcomputer", return_value=bordcomputer), \
             patch("hub.partner.get_fahrtenbuch", return_value=fahrtenbuch) as mock_get_fahrtenbuch:
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path
            data = handler._load_partners_from_db()

            with patch.object(handler, "_get_current_zone", return_value=1):
                ok, text = handler._delegate(data, ["Delegation Smoke"], dry_run=False)

        assert ok is True
        assert "Delegation in MessageBox gespeichert" in text
        mock_get_fahrtenbuch.assert_called_once_with(db_path=db_path)
        fahrtenbuch.eintrag.assert_called_once()

    def test_delegate_score_flag_reports_scorer_details(self, base_path, tmp_path):
        db_path = tmp_path / "canonical" / "bach.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        _create_partner_recognition_table(conn)
        conn.execute("""
            INSERT INTO partner_recognition (partner_name, partner_type, api_endpoint,
                                              capabilities, cost_tier, token_zone, priority, status, notes)
            VALUES ('Claude', 'api', 'https://api.anthropic.com', '["coding"]',
                    3, 'zone_1', 90, 'active', 'Primary AI Partner')
        """)
        conn.commit()
        conn.close()

        scorer = MagicMock()
        scorer.score.return_value = (
            72,
            {"length": 15, "keywords": 25, "code": 16, "multi_step": 10, "technical": 6},
        )
        scorer.get_recommended_model.return_value = "opus"

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", True), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False), \
             patch("hub.partner.get_scorer", return_value=scorer), \
             patch("hub.partner.get_scorer_source", return_value="clutch"):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path
            data = handler._load_partners_from_db()

            with patch.object(handler, "_get_current_zone", return_value=1):
                ok, text = handler._delegate(
                    data,
                    ["Migration pruefen", "--score"],
                    dry_run=True,
                )

        assert ok is True
        assert "Score:    72/100 (Quelle: clutch, Modell: opus)" in text
        assert "Breakdown: Laenge=15, Keywords=25, Code=16, Multi-Step=10, Technik=6" in text

    def test_delegate_target_partner_respects_partner_registry_zone_rules(self, base_path, partner_db):
        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = partner_db
            data = handler._load_partners_from_db()

            with patch.object(handler, "_get_current_zone", return_value=3):
                ok, text = handler._delegate(
                    data,
                    ["Routing pruefen", "--to=Claude"],
                    dry_run=True,
                )

        assert ok is False
        assert "Partner 'Claude' nicht in Zone 3 verfuegbar" in text

    def test_delegate_auto_selection_respects_allowed_partners(self, base_path, tmp_path):
        db_path = tmp_path / "canonical" / "bach.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        _create_partner_recognition_table(conn)
        conn.execute("""
            INSERT INTO partner_recognition (partner_name, partner_type, api_endpoint,
                                              capabilities, cost_tier, token_zone, priority, status, notes)
            VALUES ('Claude', 'api', 'https://api.anthropic.com', '["coding"]',
                    3, 'zone_1', 90, 'active', 'Primary AI Partner')
        """)
        conn.execute("""
            INSERT INTO partner_recognition (partner_name, partner_type, api_endpoint,
                                              capabilities, cost_tier, token_zone, priority, status, notes)
            VALUES ('Ollama', 'local', NULL, '["bulk"]',
                    0, 'zone_1', 40, 'active', 'Local AI')
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS delegation_rules (
                zone TEXT,
                allowed_partners TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            INSERT INTO delegation_rules (zone, allowed_partners, status)
            VALUES ('zone_1', '[\"Claude\"]', 'active')
        """)
        conn.commit()
        conn.close()

        with patch("hub.partner.HAS_COMPLEXITY_SCORER", False), \
             patch("hub.partner.HAS_CLUTCH_BRIDGE", False):
            from hub.partner import PartnerHandler
            handler = PartnerHandler(base_path)
            handler.db_path = db_path
            data = handler._load_partners_from_db()

            with patch.object(handler, "_get_current_zone", return_value=1):
                ok, text = handler._delegate(
                    data,
                    ["Coding Aufgabe delegieren"],
                    dry_run=True,
                )

        assert ok is True
        assert "Partner:  Claude" in text
        assert "Routing:  " in text
