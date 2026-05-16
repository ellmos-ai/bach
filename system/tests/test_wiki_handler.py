# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for WikiHandler (hub/wiki.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.wiki import WikiHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def wiki_env(tmp_path):
    """Minimal wiki environment with articles and folders."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    (wiki_dir / "python.txt").write_text(
        "Python Grundlagen\n\nPython ist eine Programmiersprache.\nSie wird viel genutzt.",
        encoding="utf-8",
    )
    (wiki_dir / "git.txt").write_text(
        "Git Versionskontrolle\n\nGit ist ein verteiltes VCS.\nbranch, merge, rebase.",
        encoding="utf-8",
    )
    (wiki_dir / "_index.txt").write_text(
        "Wiki Index\n\n- python: Python Grundlagen\n- git: Git Versionskontrolle",
        encoding="utf-8",
    )

    sub = wiki_dir / "foerderung"
    sub.mkdir()
    (sub / "icf.txt").write_text(
        "ICF Klassifikation\n\nDie ICF ist ein WHO-Standard.",
        encoding="utf-8",
    )
    (sub / "_index.txt").write_text(
        "Foerderung Themen\n\nArtikel zur Foerderplanung.",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def empty_wiki_env(tmp_path):
    """Wiki environment with empty wiki folder."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return tmp_path


@pytest.fixture
def handler(wiki_env):
    return WikiHandler(wiki_env)


@pytest.fixture
def empty_handler(empty_wiki_env):
    return WikiHandler(empty_wiki_env)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "wiki"

    def test_target_file(self, handler, wiki_env):
        assert handler.target_file == wiki_env / "wiki"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "folders" in ops
        assert "read" in ops
        assert "search" in ops
        assert "provenance" in ops
        assert "sync" in ops


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_with_index(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "WIKI-ARTIKEL" in output
        assert "python" in output.lower()
        assert "git" in output.lower()

    def test_list_shows_folders(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "foerderung" in output.lower()

    def test_list_none_op(self, handler):
        ok, output = handler.handle(None, [])
        assert ok is True
        assert "WIKI-ARTIKEL" in output

    def test_list_empty_wiki(self, empty_handler):
        ok, output = empty_handler.handle("list", [])
        assert ok is True
        assert "0 Artikel" in output


# ═══════════════════════════════════════════════════════════════
# SHOW / READ
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_article(self, handler):
        ok, output = handler.handle("python", [])
        assert ok is True
        assert "WIKI: PYTHON" in output
        assert "Programmiersprache" in output

    def test_show_via_read(self, handler):
        ok, output = handler.handle("read", ["git"])
        assert ok is True
        assert "WIKI: GIT" in output
        assert "VCS" in output

    def test_show_subfolder_article(self, handler):
        ok, output = handler.handle("foerderung/icf", [])
        assert ok is True
        assert "ICF" in output
        assert "WHO" in output

    def test_show_not_found(self, handler):
        ok, output = handler.handle("nonexistent", [])
        assert ok is False
        assert "nicht gefunden" in output

    def test_show_folder_as_topic(self, handler):
        ok, output = handler.handle("foerderung", [])
        assert ok is True
        assert "foerderung" in output.lower()

    def test_show_subfolder_not_found_with_suggestion(self, handler):
        ok, output = handler.handle("foerderung/xyz", [])
        assert "nicht gefunden" in output

    def test_read_no_args(self, handler):
        ok, output = handler.handle("read", [])
        assert ok is False
        assert "Usage" in output

    def test_show_normalizes_backslash(self, handler):
        ok, output = handler.handle("foerderung\\icf", [])
        assert ok is True
        assert "ICF" in output


# ═══════════════════════════════════════════════════════════════
# FOLDERS
# ═══════════════════════════════════════════════════════════════


class TestFolders:
    def test_list_folders(self, handler):
        ok, output = handler.handle("folders", [])
        assert ok is True
        assert "FOERDERUNG" in output
        assert "1" in output

    def test_list_folders_empty(self, empty_handler):
        ok, output = empty_handler.handle("folders", [])
        assert ok is True
        assert "Keine Themenordner" in output


# ═══════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════


class TestSearch:
    def test_search_found(self, handler):
        ok, output = handler.handle("search", ["Programmiersprache"])
        assert ok is True
        assert "python" in output.lower()

    def test_search_no_results(self, handler):
        ok, output = handler.handle("search", ["xyznonexistent"])
        assert ok is True
        assert "xyznonexistent" in output
        assert "Keine Treffer" in output or "No results" in output

    def test_search_in_subfolder(self, handler):
        ok, output = handler.handle("search", ["WHO"])
        assert ok is True
        assert "icf" in output.lower()

    def test_search_no_args(self, handler):
        ok, output = handler.handle("search", [])
        assert ok is False
        assert "Usage" in output

    def test_search_by_filename(self, handler):
        ok, output = handler.handle("search", ["git"])
        assert ok is True
        assert "git" in output.lower()


# ═══════════════════════════════════════════════════════════════
# WIKI MISSING
# ═══════════════════════════════════════════════════════════════


class TestWikiMissing:
    def test_missing_wiki_dir(self, tmp_path):
        h = WikiHandler(tmp_path)
        ok, output = h.handle("list", [])
        assert ok is False
        assert "nicht gefunden" in output


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import inspect
        source = inspect.getsource(WikiHandler)
        for i, line in enumerate(source.split("\n")):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except: pass":
                pytest.fail(f"Bare except at line {i+1}: {stripped}")
