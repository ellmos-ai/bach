# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for NewspaperHandler (hub/newspaper.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.newspaper import NewspaperHandler


@pytest.fixture
def handler(tmp_path):
    (tmp_path / "hub" / "_services" / "newspaper").mkdir(parents=True)
    db = tmp_path / "data" / "bach.db"
    db.parent.mkdir(parents=True)
    db.touch()
    return NewspaperHandler(tmp_path)


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "newspaper"

    def test_target_file(self, handler):
        assert "newspaper" in str(handler.target_file)

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "generate" in ops
        assert "deliver" in ops
        assert "config" in ops
        assert "history" in ops
        assert "help" in ops


class TestHandle:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_help(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok is True

    def test_generate_dry_run(self, handler):
        ok, msg = handler.handle("generate", [], dry_run=True)
        assert ok is True
        assert "DRY" in msg
        assert "heute" in msg

    def test_generate_dry_run_with_date(self, handler):
        ok, msg = handler.handle("generate", ["--date", "2026-01-15"], dry_run=True)
        assert ok is True
        assert "2026-01-15" in msg

    def test_deliver_dry_run(self, handler):
        ok, msg = handler.handle("deliver", [], dry_run=True)
        assert ok is True
        assert "DRY" in msg

    def test_deliver_with_channel_dry_run(self, handler):
        ok, msg = handler.handle("deliver", ["--channel", "telegram"], dry_run=True)
        assert ok is True
        assert "telegram" in msg

    @patch.object(NewspaperHandler, '_load_generator')
    def test_generate_success(self, mock_gen, handler):
        mock_generate = MagicMock(return_value={
            "date": "2026-05-16",
            "article_count": 5,
            "categories": ["tech", "science"],
            "html_path": "/tmp/news.html",
            "pdf_path": "/tmp/news.pdf",
        })
        mock_gen.return_value = (mock_generate, MagicMock(), MagicMock(return_value={}))
        ok, msg = handler.handle("generate", [])
        assert ok is True
        assert "Zeitung generiert" in msg

    @patch.object(NewspaperHandler, '_load_generator')
    def test_generate_error(self, mock_gen, handler):
        mock_generate = MagicMock(return_value={"error": "No articles"})
        mock_gen.return_value = (mock_generate, MagicMock(), MagicMock(return_value={}))
        ok, msg = handler.handle("generate", [])
        assert ok is False
        assert "No articles" in msg


def test_desktop_dir_falls_back_to_home_desktop_outside_windows(monkeypatch):
    from hub._services.newspaper import newspaper_generator as gen

    monkeypatch.setattr(gen.sys, "platform", "linux")
    assert gen._desktop_dir() == Path.home() / "Desktop"


def test_desktop_placeholder_and_empty_value_resolve_to_the_visible_desktop(monkeypatch, tmp_path):
    from hub._services.newspaper import newspaper_generator as gen

    monkeypatch.setattr(gen, "_desktop_dir", lambda: tmp_path)
    # config.json ships "{USER_HOME}/Desktop/", which was used literally as a relative path.
    assert gen._resolve_desktop_path("{USER_HOME}/Desktop/") == str(tmp_path)
    assert gen._resolve_desktop_path(None) == str(tmp_path)
    assert gen._resolve_desktop_path("") == str(tmp_path)
    assert gen._resolve_desktop_path("/srv/news") == "/srv/news"


@pytest.mark.skipif(sys.platform != "win32", reason="SHGetKnownFolderPath is Windows-only")
def test_desktop_dir_uses_an_existing_known_folder_on_windows():
    from hub._services.newspaper import newspaper_generator as gen

    assert gen._desktop_dir().is_dir()
