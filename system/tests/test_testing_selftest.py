# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionen für den fachlich aussagekräftigen QUICK-Selbsttest."""

import importlib.util
import json
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
TESTING_ROOT = SYSTEM_ROOT / "tools" / "testing"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


inventory = _load_module("bach_b001_inventory", TESTING_ROOT / "b_tests" / "B001_file_inventory.py")
roundtrip = _load_module("bach_o001_roundtrip", TESTING_ROOT / "o_tests" / "O001_task_roundtrip.py")
runner = _load_module("bach_test_runner", TESTING_ROOT / "test_runner.py")


def test_b001_success_has_explicit_score_and_meaning(tmp_path):
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")

    result = inventory.analyze_system(tmp_path)

    assert result["status"] == "PASS"
    assert result["score"] == 5.0
    assert "keine Qualitätsbewertung" in result["score_explanation"]
    assert result["total_files"] == 1


def test_o001_uses_bach_task_api_with_an_isolated_canonical_database():
    result = roundtrip.test_task_roundtrip(SYSTEM_ROOT)

    assert result["mode"] == "bach_task_api_isolated_db"
    assert result["status"] == "PASS"
    assert result["score"] == 5.0
    assert all(check["passed"] for check in result["checks"])
    assert any(check["name"] == "canonical_database_isolated" for check in result["checks"])


def test_quick_artifact_explains_its_scores(tmp_path):
    result = runner.run_tests(str(SYSTEM_ROOT), "QUICK", tmp_path)
    artifact = next(tmp_path.glob("TEST_system_QUICK_*.json"))
    stored = json.loads(artifact.read_text(encoding="utf-8"))

    assert result["summary"]["overall"] == 5.0
    assert "keine pauschale Qualitätsaussage" in stored["score_explanation"]
    assert stored["b_tests"]["B001"]["score_explanation"]
    assert stored["o_tests"]["O001"]["score_explanation"]
