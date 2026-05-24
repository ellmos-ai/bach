# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for BerichtHandler (hub/bericht.py)."""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.bericht import BerichtHandler


@pytest.fixture
def handler(tmp_path):
    (tmp_path / "user" / "documents" / "foerderplaner" / "klienten").mkdir(parents=True)
    (tmp_path / "skills" / "_templates").mkdir(parents=True)
    (tmp_path / "agents" / "_experts" / "report_generator").mkdir(parents=True)
    return BerichtHandler(tmp_path)


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "bericht"

    def test_target_file(self, handler):
        assert handler.target_file.name == "foerderplaner"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "generate" in ops
        assert "list" in ops
        assert "export" in ops
        assert "pipeline" in ops
        assert "help" in ops


class TestHandle:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_help_operation(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok is True

    def test_empty_operation(self, handler):
        ok, msg = handler.handle("", [])
        assert ok is True

    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok is True

    def test_generate_no_args(self, handler):
        ok, msg = handler.handle("generate", [])
        assert ok is False

    def test_export_no_args(self, handler):
        ok, msg = handler.handle("export", [])
        assert ok is False

    def test_status(self, handler):
        ok, msg = handler.handle("status", [])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_extract_no_args(self, handler):
        ok, msg = handler.handle("extract", [])
        assert ok is False

    def test_prompt_no_args(self, handler):
        ok, msg = handler.handle("prompt", [])
        assert ok is False

    def test_pipeline_success_redacts_output_path(self, handler):
        class DummyPipeline:
            def run_full_pipeline(self, **kwargs):
                return types.SimpleNamespace(
                    success=True,
                    output_path=Path(r"C:\secret\Real Name\Foerderbericht_Real Name_20260523.docx"),
                    tarnname="Tarn Person",
                    duration_s=1.2,
                    steps_completed=["bericht: erstellt"],
                )

        dummy_module = types.SimpleNamespace(FoerderberichtPipeline=DummyPipeline)
        with patch.dict(sys.modules, {
            "hub._services.document.foerderbericht_pipeline": dummy_module,
        }):
            ok, msg = handler.handle("pipeline", [])

        assert ok is True
        assert "Bericht: erstellt" in msg
        assert "Real Name" not in msg
        assert "Foerderbericht_Real Name" not in msg
