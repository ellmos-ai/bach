#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer md_to_pdf converter (find_edge cross-OS detection)"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from tools.converters.md_to_pdf import find_edge, EDGE_PATHS_WIN, EDGE_PATHS_MAC, EDGE_PATHS_LINUX


class TestFindEdge:
    def test_windows_candidate_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(Path, "exists", lambda self: self == EDGE_PATHS_WIN[0])
        result = find_edge()
        assert result == str(EDGE_PATHS_WIN[0])

    def test_mac_candidate_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(Path, "exists", lambda self: self == EDGE_PATHS_MAC[0])
        result = find_edge()
        assert result == str(EDGE_PATHS_MAC[0])

    def test_linux_candidate_found(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(Path, "exists", lambda self: self == EDGE_PATHS_LINUX[0])
        result = find_edge()
        assert result == str(EDGE_PATHS_LINUX[0])

    def test_linux_second_candidate(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(Path, "exists", lambda self: self == EDGE_PATHS_LINUX[1])
        result = find_edge()
        assert result == str(EDGE_PATHS_LINUX[1])

    def test_fallback_to_shutil_which(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(Path, "exists", lambda self: False)
        with patch("shutil.which", side_effect=lambda name: "/usr/local/bin/msedge" if name == "msedge" else None):
            result = find_edge()
        assert result == "/usr/local/bin/msedge"

    def test_fallback_microsoft_edge(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(Path, "exists", lambda self: False)
        with patch("shutil.which", side_effect=lambda name: "/snap/bin/microsoft-edge" if name == "microsoft-edge" else None):
            result = find_edge()
        assert result == "/snap/bin/microsoft-edge"

    def test_no_edge_returns_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(Path, "exists", lambda self: False)
        with patch("shutil.which", return_value=None):
            result = find_edge()
        assert result is None


class TestMarkdownToHTML:
    def test_import(self):
        from tools.converters.md_to_pdf import MarkdownToHTML
        converter = MarkdownToHTML()
        assert converter.show_header is True
        assert converter.show_footer is True

    def test_custom_options(self):
        from tools.converters.md_to_pdf import MarkdownToHTML
        converter = MarkdownToHTML(show_header=False, show_footer=False, show_page_numbers=False)
        assert converter.show_header is False
        assert converter.show_footer is False
        assert converter.show_page_numbers is False
