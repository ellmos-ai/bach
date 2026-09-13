# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""TRANSFER-02 Regressionstests: ellmos-tests Adapter in hub/test.py.

Sichert Stufe 2 des MODULRUECKTRANSFER-PLANs
(docs/architecture/MODULRUECKTRANSFER-PLAN.md):

- Importierbarkeit des TestHandlers (Syntax-Guard: der Adapter war
  urspruenglich mit ungueltiger String-Konkatenation nicht importierbar)
- Adapter-Aufloesung via ELLMOS_TESTS_PATH inkl. Validierung des Checkouts
- Rollback auf den legacy test_runner.py via --native/--legacy
- --dry-run fuehrt nichts aus (Plan-Anforderung Stufe 2)
- ELLMOS_PROFILES decken sich mit den Faehigkeiten von run_external.py
  (QUICK/STANDARD/FULL); OBSERVATION/OUTPUT/MEMORY_FOCUS/TASK_FOCUS sind
  legacy-only und muessen mit --native anforderbar sein.
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.test import TestHandler as BachTestHandler, ELLMOS_PROFILES, PROFILES


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def fake_ellmos(tmp_path, monkeypatch):
    """Legt einen gueltigen ellmos-tests-Checkout unter tmp_path an."""
    root = tmp_path / "ellmos-tests"
    runner = root / "system_diff_tests" / "testing" / "run_external.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# fake run_external.py\n", encoding="utf-8")
    monkeypatch.setenv("ELLMOS_TESTS_PATH", str(root))
    return root


@pytest.fixture
def handler(fake_ellmos, tmp_path):
    """TestHandler mit aufgeloestem Fake-ellmos-Adapter und legacy-Runner."""
    legacy_runner = tmp_path / "tools" / "testing" / "test_runner.py"
    legacy_runner.parent.mkdir(parents=True)
    legacy_runner.write_text("# fake legacy test_runner.py\n", encoding="utf-8")

    h = BachTestHandler(tmp_path)
    ok, _ = h.handle("profiles", [])  # initialisiert _ellmos_path
    assert ok
    return h


@pytest.fixture
def native_handler(tmp_path, monkeypatch):
    """TestHandler ohne ellmos-Adapter (invalidier ELLMOS_TESTS_PATH)."""
    monkeypatch.setenv("ELLMOS_TESTS_PATH", str(tmp_path / "gibts_nicht"))
    h = BachTestHandler(tmp_path)
    h.handle("profiles", [])  # initialisiert _ellmos_path
    return h


# ═══════════════════════════════════════════════════════════════
# SYNTAX-GUARD & CONTRACT
# ═══════════════════════════════════════════════════════════════


def test_handler_module_is_importable():
    """Der Adapter-Code muss importierbar sein (Syntax-Guard, TRANSFER-02)."""
    import hub.test as module

    assert module.TestHandler is BachTestHandler
    assert callable(BachTestHandler.handle)


def test_ellmos_profiles_match_run_external_contract():
    """ELLMOS_PROFILES muss den Profilem von run_external.py entsprechen."""
    assert ELLMOS_PROFILES == {"QUICK", "STANDARD", "FULL"}
    # Legacy kennt alle Adapter-Profile
    assert ELLMOS_PROFILES <= set(PROFILES)


def test_legacy_only_profiles_exist():
    """Die legacy-only Profile duerfen nicht als ellmos-faehig deklariert sein."""
    assert {"OBSERVATION", "OUTPUT", "MEMORY_FOCUS", "TASK_FOCUS"} & ELLMOS_PROFILES == set()


# ═══════════════════════════════════════════════════════════════
# ADAPTER-AUFLOESUNG & ROLLBACK
# ═══════════════════════════════════════════════════════════════


def test_adapter_resolves_ellmos_tests_checkout(handler, fake_ellmos):
    ok, msg = handler.handle("profiles", [])
    assert ok
    assert str(fake_ellmos) in msg
    assert "ellmos-tests" in msg


def test_invalid_ellmos_path_falls_back_to_legacy(native_handler):
    assert native_handler._ellmos_path is None
    assert native_handler._use_ellmos_tests() is False


def test_native_flag_rolls_back_to_legacy(handler):
    """Rollback-Nachweis: --native schaltet auf den legacy-Pfad zurueck."""
    ok, msg = handler.handle("profiles", ["--native"])
    assert ok
    assert "legacy" in msg
    assert handler._use_ellmos_tests() is False


def test_legacy_flag_is_alias_for_native(handler):
    ok, msg = handler.handle("profiles", ["--legacy"])
    assert ok
    assert "legacy" in msg


# ═══════════════════════════════════════════════════════════════
# DRY-RUN (Plan-Anforderung Stufe 2)
# ═══════════════════════════════════════════════════════════════


def test_dry_run_executes_nothing_via_ellmos(handler):
    with mock.patch("hub.test.subprocess.run") as run:
        ok, msg = handler.handle("self", ["QUICK"], dry_run=True)
    assert ok
    run.assert_not_called()
    assert "DRY-RUN" in msg
    assert "run_external.py" in msg
    assert "--profile QUICK" in msg


def test_dry_run_executes_nothing_via_legacy(handler):
    with mock.patch("hub.test.subprocess.run") as run:
        ok, msg = handler.handle("self", ["QUICK", "--native"], dry_run=True)
    assert ok
    run.assert_not_called()
    assert "test_runner.py" in msg
    assert "-p QUICK" in msg


def test_dry_run_system_test_executes_nothing(handler, tmp_path):
    with mock.patch("hub.test.subprocess.run") as run:
        ok, msg = handler.handle("run", [str(tmp_path), "FULL"], dry_run=True)
    assert ok
    run.assert_not_called()
    assert "FULL" in msg


def test_dry_run_compare_shows_both_commands(handler, tmp_path):
    other = tmp_path / "other-system"
    other.mkdir()
    with mock.patch("hub.test.subprocess.run") as run:
        ok, msg = handler.handle("compare", [str(other)], dry_run=True)
    assert ok
    run.assert_not_called()
    assert msg.count("DRY-RUN") == 2


def test_real_execution_still_possible_with_mock(handler, tmp_path):
    """Ohne dry-run wird subprocess tatsaechlich aufgerufen (Adapter aktiv)."""
    with mock.patch(
        "hub.test.subprocess.run", return_value=mock.Mock(returncode=0, stdout="ok", stderr="")
    ) as run:
        handler.handle("self", ["QUICK"])
    run.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# PROFIL-ABSICHERUNG
# ═══════════════════════════════════════════════════════════════


def test_legacy_only_profile_rejected_by_ellmos_adapter(handler):
    """Legacy-only Profile muessen am Adapter abgewiesen werden."""
    ok, msg = handler.handle("self", ["OBSERVATION"], dry_run=True)
    assert not ok
    assert "unterstuetzt" in msg
    assert "--native" in msg


def test_legacy_only_profile_runs_via_native(handler):
    ok, msg = handler.handle("self", ["MEMORY_FOCUS", "--native"], dry_run=True)
    assert ok
    assert "MEMORY_FOCUS" in msg


def test_unknown_profile_rejected(handler):
    ok, _ = handler.handle("self", ["GIBTSNICHT"], dry_run=True)
    assert not ok