# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for DataAnalysisHandler (hub/data_analysis.py)."""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.data_analysis import DataAnalysisHandler


@pytest.fixture
def handler(tmp_path):
    return DataAnalysisHandler(tmp_path)


@pytest.fixture
def csv_file(tmp_path):
    data_dir = tmp_path / "user" / "data-analysis" / "input"
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "test.csv"
    f.write_text("name,age,score\nAlice,30,85\nBob,25,92\nClara,28,78\n", encoding="utf-8")
    return f


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "data"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "load" in ops
        assert "describe" in ops
        assert "head" in ops
        assert "list" in ops

    def test_directories_created(self, handler):
        assert handler.data_dir.exists()
        assert handler.input_dir.exists()
        assert handler.output_dir.exists()
        assert handler.charts_dir.exists()


class TestHandle:
    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok is True

    def test_load_no_args(self, handler):
        ok, msg = handler.handle("load", [])
        assert ok is False
        assert "Pfad" in msg

    def test_describe_no_args(self, handler):
        ok, msg = handler.handle("describe", [])
        assert ok is False

    def test_head_no_args(self, handler):
        ok, msg = handler.handle("head", [])
        assert ok is False

    def test_load_csv(self, handler, csv_file):
        ok, msg = handler.handle("load", [str(csv_file)])
        assert ok is True
        assert "name" in msg or "Spalten" in msg or "Zeilen" in msg or "3" in msg

    def test_head_csv(self, handler, csv_file):
        ok, msg = handler.handle("head", [str(csv_file)])
        assert ok is True
        assert "Alice" in msg

    def test_head_with_rows_param(self, handler, csv_file):
        ok, msg = handler.handle("head", [str(csv_file), "--rows", "1"])
        assert ok is True

    def test_load_nonexistent(self, handler):
        ok, msg = handler.handle("load", ["/nonexistent/file.csv"])
        assert ok is False
