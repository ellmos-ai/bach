# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for PartnerHandler (hub/partner.py)."""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_recognition (
                id INTEGER PRIMARY KEY, partner_name TEXT, partner_type TEXT,
                api_endpoint TEXT, capabilities TEXT, cost_tier INTEGER DEFAULT 1,
                token_zone TEXT DEFAULT 'zone_1', priority INTEGER DEFAULT 50,
                status TEXT DEFAULT 'active', success_rate REAL DEFAULT 1.0, notes TEXT
            )
        """)
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
