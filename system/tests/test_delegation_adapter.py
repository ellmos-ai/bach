# SPDX-License-Identifier: MIT
"""Regression tests for the BACH-to-clutch delegation adapter."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _clear_clutch_modules() -> None:
    for name in list(sys.modules):
        if name == "clutch" or name.startswith("clutch."):
            del sys.modules[name]


def _reload_delegation():
    _clear_clutch_modules()
    import hub._services.delegation as delegation

    return importlib.reload(delegation)


def test_external_clutch_path_can_supply_scorer(tmp_path, monkeypatch):
    pkg = tmp_path / "clutch"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "scorer.py").write_text(
        """
class ExternalScorer:
    def score(self, task):
        return 88, {"length": 8, "keywords": 80}

    def gang_level_fuer_score(self, score):
        return 5


def get_scorer():
    return ExternalScorer()
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("BACH_CLUTCH_PATH", str(tmp_path))
    monkeypatch.delenv("BACH_DISABLE_EXTERNAL_CLUTCH", raising=False)

    delegation = _reload_delegation()

    scorer = delegation.get_scorer()
    assert delegation.get_scorer_source() == "clutch"
    assert scorer.score("Migration pruefen")[0] == 88
    assert scorer.get_recommended_model(90) == "opus"


def test_external_clutch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("BACH_DISABLE_EXTERNAL_CLUTCH", "1")
    monkeypatch.delenv("BACH_CLUTCH_PATH", raising=False)

    delegation = _reload_delegation()

    assert delegation.get_scorer_source() == "legacy"
