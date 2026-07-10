# SPDX-License-Identifier: MIT
"""Tests fuer hub/clutch.py — ClutchHandler (Standalone, kein clutch-bridge noetig)."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.clutch import ClutchHandler


@pytest.fixture
def clutch_env(tmp_path):
    """Erstellt ClutchHandler mit tmp_path als base_path."""
    h = ClutchHandler(tmp_path)
    return h


# ── Properties ──────────────────────────────────────────────

class TestProperties:
    def test_profile_name(self, clutch_env):
        assert clutch_env.profile_name == "clutch"

    def test_target_file(self, clutch_env):
        h = clutch_env
        assert h.target_file == h.base_path / "hub" / "_services" / "delegation"

    def test_get_operations_keys(self, clutch_env):
        ops = clutch_env.get_operations()
        expected = {"status", "analyse", "metriken", "fitness", "health", "migration"}
        assert set(ops.keys()) == expected


# ── HAS_CLUTCH = False (Module nicht vorhanden) ─────────────

class TestNoClutch:
    """Wenn clutch-bridge nicht importiert werden kann, scheitern alle Ops sauber."""

    def test_handle_returns_false_without_clutch(self, clutch_env):
        with patch("hub.clutch.HAS_CLUTCH", False):
            ok, text = clutch_env.handle("status", [])
        assert ok is False
        assert "nicht verfügbar" in text

    def test_all_operations_fail_without_clutch(self, clutch_env):
        with patch("hub.clutch.HAS_CLUTCH", False):
            for op in ["status", "analyse", "metriken", "fitness", "health"]:
                ok, text = clutch_env.handle(op, [])
                assert ok is False, f"Operation '{op}' haette fehlschlagen sollen"

    def test_unknown_op_also_fails_without_clutch(self, clutch_env):
        with patch("hub.clutch.HAS_CLUTCH", False):
            ok, text = clutch_env.handle("nonexistent", [])
        assert ok is False
        assert "nicht verfügbar" in text


# ── Unknown / Fallback ──────────────────────────────────────

class TestHandleUnknown:
    def test_unknown_operation_returns_error(self, clutch_env):
        with patch("hub.clutch.HAS_CLUTCH", True):
            ok, text = clutch_env.handle("gibts_nicht", [])
        assert ok is False
        assert "Unbekannte Operation" in text
        assert "status" in text

    def test_empty_operation_falls_to_status(self, clutch_env):
        mock_bc = MagicMock()
        mock_bc.status.return_value = {"circuits": {}, "overkill_alerts": 0, "token_alerts": 0}
        mock_fs = MagicMock()
        mock_fs.status.return_value = {"total_kombinationen": 0}
        mock_fb = MagicMock()
        mock_fb.metriken.return_value = {"total_delegations": 0}

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_bordcomputer", return_value=mock_bc), \
             patch("hub.clutch.get_fahrschule", return_value=mock_fs), \
             patch("hub.clutch.get_fahrtenbuch", return_value=mock_fb):
            ok, text = clutch_env.handle("", [])
        assert ok is True
        assert "CLUTCH-BRIDGE" in text


# ── Handle: status ───────────────────────────────────────────

class TestHandleStatus:
    def test_status_success(self, clutch_env):
        mock_bc = MagicMock()
        mock_bc.status.return_value = {
            "circuits": {"openai": "closed", "ollama": "closed"},
            "overkill_alerts": 1,
            "token_alerts": 2,
        }
        mock_fs = MagicMock()
        mock_fs.status.return_value = {"total_kombinationen": 15}
        mock_fb = MagicMock()
        mock_fb.metriken.return_value = {"total_delegations": 42}

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_bordcomputer", return_value=mock_bc), \
             patch("hub.clutch.get_fahrschule", return_value=mock_fs), \
             patch("hub.clutch.get_fahrtenbuch", return_value=mock_fb):
            ok, text = clutch_env.handle("status", [])

        assert ok is True
        assert "CLUTCH-BRIDGE" in text
        assert "2 Provider" in text
        assert "1 Overkill-Alerts" in text
        assert "2 Token-Explosions" in text
        assert "15" in text
        assert "42" in text


# ── Handle: analyse ──────────────────────────────────────────

class TestHandleAnalyse:
    def test_analyse_without_args(self, clutch_env):
        with patch("hub.clutch.HAS_CLUTCH", True):
            ok, text = clutch_env.handle("analyse", [])
        assert ok is False
        assert "Nutzung" in text

    def test_analyse_with_task(self, clutch_env):
        mock_profil = SimpleNamespace(
            typ="Standardstrecke",
            typ_code=1,
            tempo=3,
            schwierigkeit=2,
            etappen=1,
            empfohlener_gang="D",
            token_budget_faktor=1.0,
        )
        mock_gas = SimpleNamespace(
            level=50,
            strategie=SimpleNamespace(value="ausgewogen"),
            token_multiplikator=1.0,
            prompt_prefix="",
            prompt_suffix="",
        )
        mock_analyser = MagicMock()
        mock_analyser.analysiere.return_value = mock_profil
        mock_gb = MagicMock()
        mock_gb.berechne.return_value = mock_gas

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_analyser", return_value=mock_analyser), \
             patch("hub.clutch.get_gas_bremse", return_value=mock_gb):
            ok, text = clutch_env.handle("analyse", ["README schreiben"])

        assert ok is True
        assert "Standardstrecke" in text
        assert "ausgewogen" in text
        assert "README schreiben" in text


# ── Handle: metriken ─────────────────────────────────────────

class TestHandleMetriken:
    def test_metriken_default(self, clutch_env):
        mock_fb = MagicMock()
        mock_fb.format_metriken.return_value = "Metriken: 7 Tage"

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_fahrtenbuch", return_value=mock_fb):
            ok, text = clutch_env.handle("metriken", [])

        assert ok is True
        assert "7 Tage" in text
        mock_fb.format_metriken.assert_called_once_with(7)

    def test_metriken_custom_days(self, clutch_env):
        mock_fb = MagicMock()
        mock_fb.format_metriken.return_value = "Metriken: 30 Tage"

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_fahrtenbuch", return_value=mock_fb):
            ok, text = clutch_env.handle("metriken", ["30"])

        mock_fb.format_metriken.assert_called_once_with(30)

    def test_metriken_invalid_days_uses_default(self, clutch_env):
        mock_fb = MagicMock()
        mock_fb.format_metriken.return_value = "Metriken"

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_fahrtenbuch", return_value=mock_fb):
            ok, text = clutch_env.handle("metriken", ["abc"])

        mock_fb.format_metriken.assert_called_once_with(7)


# ── Handle: fitness ──────────────────────────────────────────

class TestHandleFitness:
    def test_fitness(self, clutch_env):
        mock_fs = MagicMock()
        mock_fs.format_status.return_value = "Fahrschule: 15 Kombinationen"

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_fahrschule", return_value=mock_fs):
            ok, text = clutch_env.handle("fitness", [])

        assert ok is True
        assert "15 Kombinationen" in text


# ── Handle: health ───────────────────────────────────────────

class TestHandleHealth:
    def test_health(self, clutch_env):
        mock_bc = MagicMock()
        mock_bc.format_status.return_value = "Bordcomputer: OK"

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_bordcomputer", return_value=mock_bc):
            ok, text = clutch_env.handle("health", [])

        assert ok is True
        assert "Bordcomputer: OK" in text


# -- Handle: migration -------------------------------------------------

class TestHandleMigration:
    def test_migration_reports_component_sources_and_gates(self, clutch_env):
        sources = {
            "external_clutch": "available",
            "scorer": "clutch",
            "partner_registry": "clutch",
            "streckenanalyse": "legacy",
            "gas_bremse": "legacy",
            "bordcomputer": "legacy",
            "fahrschule": "legacy",
            "fahrtenbuch": "legacy",
        }

        with patch("hub.clutch.HAS_CLUTCH", True), \
             patch("hub.clutch.get_component_sources", return_value=sources):
            ok, text = clutch_env.handle("migration", [])

        assert ok is True
        assert "[CLUTCH-MIGRATION]" in text
        assert "scorer: clutch" in text
        assert "partner_registry: clutch" in text
        assert "fahrtenbuch: legacy" in text
        assert "Compat-Adapter: OK" in text
        assert "DB-Brücke: PENDING" in text
        assert "Fork-Archivierung: BLOCKED" in text
