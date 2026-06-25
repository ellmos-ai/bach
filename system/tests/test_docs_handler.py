#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for DocsHandler (hub/docs.py)."""

import sqlite3
import pytest
from pathlib import Path


def _create_docs_tables(conn):
    """Minimal DB tables needed by docs generate methods."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT,
            category TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT,
            category TEXT,
            description TEXT,
            path TEXT,
            is_available INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bach_agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT,
            type TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT,
            value TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dist_file_versions (
            version TEXT,
            file_path TEXT,
            file_hash TEXT,
            created_at TEXT,
            dist_type INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS languages_config (
            id INTEGER PRIMARY KEY,
            default_language TEXT DEFAULT 'en',
            fallback_language TEXT DEFAULT 'en',
            enabled_languages TEXT DEFAULT '["de", "en"]',
            auto_translate INTEGER DEFAULT 0,
            preserve_formatting INTEGER DEFAULT 1,
            updated_at TEXT
        )
    """)
    conn.commit()


def _seed_docs_db(conn):
    """Insert sample data for generate methods."""
    conn.execute("INSERT INTO system_config (key, value) VALUES ('bach_version', '4.3.20')")
    conn.execute("INSERT INTO skills (name, type, category, description) VALUES ('greeting', 'protocol', 'social', 'Greeting protocol')")
    conn.execute("INSERT INTO skills (name, type, category, description) VALUES ('backup', 'service', 'system', 'Auto backup')")
    conn.execute("INSERT INTO tools (name, category, description, path) VALUES ('md_to_pdf', 'converter', 'Converts MD to PDF.', 'tools/converters/md_to_pdf.py')")
    conn.execute("INSERT INTO tools (name, category, description, path) VALUES ('csv_export', 'converter', 'Exports CSV files.', 'tools/converters/csv_export.py')")
    conn.execute("INSERT INTO tools (name, category, description, path) VALUES ('deep_scan', 'analysis', 'Deep code scan.', 'tools/deep_scan.py')")
    conn.execute("INSERT INTO bach_agents (name, display_name, type, description) VALUES ('buero', 'Buero-Agent', 'boss', 'Buero-Verwaltung')")
    conn.execute("INSERT INTO memory_lessons (content) VALUES ('Always backup first')")
    conn.execute("INSERT INTO memory_facts (key, value) VALUES ('version', '4.3.20')")
    conn.execute("INSERT INTO dist_file_versions VALUES ('4.3.20', 'hub/docs.py', 'abcdef1234567890', '2026-05-15T10:00:00', 2)")
    conn.execute("INSERT INTO dist_file_versions VALUES ('4.3.20', 'hub/base.py', '1234567890abcdef', '2026-05-15T10:00:00', 2)")
    conn.execute("INSERT INTO languages_config (id, default_language, fallback_language) VALUES (1, 'en', 'en')")
    conn.commit()


def _create_docs_tree(base_path):
    """Create a realistic docs/ directory tree."""
    docs = base_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    (docs / "README.md").write_text("# BACH Docs\n\nWelcome to BACH.", encoding="utf-8")
    (docs / "getting-started.md").write_text("# Getting Started\n\nInstall BACH.", encoding="utf-8")
    (docs / "konzept-architektur.md").write_text("# Architektur-Konzept\n\nModular.", encoding="utf-8")
    (docs / "soll_ist_analyse.md").write_text("# Soll-Ist Analyse\n\nVergleich.", encoding="utf-8")

    guides = docs / "guides"
    guides.mkdir()
    (guides / "db-sync.md").write_text("# DB-Sync Guide\n\nSynchronize databases.\n\nKeyword: replication", encoding="utf-8")
    (guides / "first-steps.md").write_text("# First Steps\n\nBegin here.", encoding="utf-8")

    ref = docs / "reference"
    ref.mkdir()
    (ref / "cli-commands.md").write_text("# CLI Commands\n\n## bach task\nManage tasks.", encoding="utf-8")

    helpd = docs / "help"
    helpd.mkdir()
    (helpd / "task.txt").write_text("BACH Task Help\n\nUsage: bach task [add|list|done]", encoding="utf-8")
    (helpd / "_index.txt").write_text("Help index (hidden)", encoding="utf-8")

    return docs


@pytest.fixture
def docs_env(tmp_path, monkeypatch):
    """Full docs environment: file tree + DB."""
    base = tmp_path / "system"
    base.mkdir()

    data_dir = base / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_docs_tables(conn)
    _seed_docs_db(conn)
    conn.close()

    _create_docs_tree(base)

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    import hub.lang as _lang_mod
    monkeypatch.setattr(_lang_mod, "_t_db_path", None)
    monkeypatch.setattr(_lang_mod, "_t_lang_cache", None)
    return base, db_path


@pytest.fixture
def docs_only(tmp_path):
    """File tree only, no DB."""
    base = tmp_path / "system"
    base.mkdir()
    _create_docs_tree(base)
    return base


@pytest.fixture
def handler(docs_env):
    """Instantiated DocsHandler."""
    base, _ = docs_env
    from hub.docs import DocsHandler
    return DocsHandler(base)


# ─── Init & Basics ────────────────────────────────────────

class TestDocsInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "docs"

    def test_target_file_is_docs_dir(self, handler, docs_env):
        base, _ = docs_env
        assert handler.target_file == base / "docs"

    def test_operations_dict(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "search" in ops
        assert "sync" in ops
        assert "generate" in ops
        assert "migrate" in ops

    def test_missing_docs_dir(self, tmp_path, monkeypatch):
        base = tmp_path / "system"
        base.mkdir()
        (base / "data").mkdir()
        db_path = base / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)

        from hub.docs import DocsHandler
        h = DocsHandler(base)
        ok, msg = h.handle("list", [])
        assert not ok
        assert "nicht gefunden" in msg


# ─── List ─────────────────────────────────────────────────

class TestDocsList:
    def test_list_shows_sections(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "BACH DOKUMENTATION" in msg

    def test_list_shows_readme(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "README" in msg

    def test_list_shows_konzepte(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "KONZEPTE" in msg

    def test_list_shows_analysen(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "ANALYSEN" in msg

    def test_list_shows_guides(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "GUIDES" in msg

    def test_list_shows_reference(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "REFERENCE" in msg

    def test_list_shows_legacy_help_count(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "LEGACY HELP" in msg
        assert "2 Legacy" in msg

    def test_list_empty_operation_routes_to_list(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "BACH DOKUMENTATION" in msg

    def test_list_none_operation_routes_to_list(self, handler):
        ok, msg = handler.handle(None, [])
        assert ok
        assert "BACH DOKUMENTATION" in msg


# ─── Show ─────────────────────────────────────────────────

class TestDocsShow:
    def test_show_readme(self, handler):
        ok, msg = handler.handle("readme", [])
        assert ok
        assert "DOCS: README" in msg
        assert "Welcome to BACH" in msg

    def test_show_index_alias(self, handler):
        ok, msg = handler.handle("index", [])
        assert ok
        assert "README" in msg

    def test_show_root_doc(self, handler):
        ok, msg = handler.handle("getting-started", [])
        assert ok
        assert "Install BACH" in msg

    def test_show_guide_by_path(self, handler):
        ok, msg = handler.handle("guides/db-sync", [])
        assert ok
        assert "DB-Sync Guide" in msg

    def test_show_reference_by_path(self, handler):
        ok, msg = handler.handle("reference/cli-commands", [])
        assert ok
        assert "CLI Commands" in msg

    def test_show_guide_fallback(self, handler):
        ok, msg = handler.handle("db-sync", [])
        assert ok
        assert "DB-Sync" in msg

    def test_show_reference_fallback(self, handler):
        ok, msg = handler.handle("cli-commands", [])
        assert ok
        assert "CLI Commands" in msg

    def test_show_fuzzy_match(self, handler):
        ok, msg = handler.handle("konzept", [])
        assert ok
        assert "Modular" in msg

    def test_show_not_found(self, handler):
        ok, msg = handler.handle("nonexistent-doc", [])
        assert not ok
        assert "nicht gefunden" in msg

    def test_show_via_api(self, handler):
        ok, msg = handler.handle("show", ["getting-started"])
        assert ok
        assert "Install BACH" in msg

    def test_show_backslash_normalization(self, handler):
        ok, msg = handler.handle("guides\\db-sync", [])
        assert ok
        assert "DB-Sync" in msg


# ─── Render ───────────────────────────────────────────────

class TestDocsRender:
    def test_markdown_truncation(self, handler, docs_env):
        base, _ = docs_env
        long_content = "\n".join([f"Line {i}" for i in range(150)])
        (base / "docs" / "long-doc.md").write_text(long_content, encoding="utf-8")

        ok, msg = handler.handle("long-doc", [])
        assert ok
        assert "50 weitere Zeilen" in msg
        assert "Line 0" in msg
        assert "Line 99" in msg

    def test_text_render(self, handler):
        ok, msg = handler.handle("help/task", [])
        # help/task.txt exists via _show() path routing
        # Actually _show routes help/task -> docs/help/task.md (not found) -> task.txt
        # Let's check: _show("help/task") -> folder="help", doc_name="task" -> tries .md then .txt
        # The fixture has help/task.txt
        assert ok
        assert "bach task" in msg.lower() or "BACH Task" in msg

    def test_render_broken_file(self, handler, docs_env):
        base, _ = docs_env
        bad = base / "docs" / "broken.md"
        bad.write_bytes(b'\x80\x81\x82\xff')  # invalid UTF-8
        ok, msg = handler.handle("broken", [])
        assert not ok
        assert "fehler" in msg.lower() or "error" in msg.lower()


# ─── Search ───────────────────────────────────────────────

class TestDocsSearch:
    def test_search_finds_keyword(self, handler):
        ok, msg = handler.handle("search", ["replication"])
        assert ok
        assert "db-sync" in msg.lower() or "replication" in msg.lower()

    def test_search_in_filename(self, handler):
        ok, msg = handler.handle("search", ["konzept"])
        assert ok
        assert "konzept" in msg.lower()

    def test_search_no_results(self, handler):
        ok, msg = handler.handle("search", ["zzz_nonexistent_term_zzz"])
        assert ok
        assert "Keine Treffer" in msg

    def test_search_no_args(self, handler):
        ok, msg = handler.handle("search", [])
        assert not ok
        assert "Usage" in msg or "keyword" in msg.lower()

    def test_search_multi_word(self, handler):
        ok, msg = handler.handle("search", ["Getting", "Started"])
        assert ok
        # Joins to "Getting Started"
        assert "getting" in msg.lower()

    def test_search_legacy_txt(self, handler):
        ok, msg = handler.handle("search", ["bach task"])
        assert ok
        assert "Legacy" in msg or "task" in msg.lower()

    def test_search_skips_hidden_files(self, handler):
        ok, msg = handler.handle("search", ["Help index"])
        assert ok
        assert "_index" not in msg

    def test_search_max_20_results(self, handler, docs_env):
        base, _ = docs_env
        for i in range(25):
            (base / "docs" / f"testdoc{i}.md").write_text(f"common_keyword_{i}", encoding="utf-8")

        ok, msg = handler.handle("search", ["common_keyword"])
        assert ok
        assert "weitere Treffer" in msg or "25" in msg


# ─── Sync MD -> TXT ──────────────────────────────────────

class TestDocsSync:
    def test_sync_creates_txt(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("sync", [])
        assert ok
        assert "synchronisiert" in msg

        # Check that txt was created in help/guides/
        txt = base / "docs" / "help" / "guides" / "db-sync.txt"
        assert txt.exists()
        content = txt.read_text(encoding="utf-8")
        assert "DB-Sync Guide" in content

    def test_sync_strips_markdown(self, handler, docs_env):
        base, _ = docs_env
        handler.handle("sync", [])

        txt = base / "docs" / "help" / "guides" / "db-sync.txt"
        content = txt.read_text(encoding="utf-8")
        # Headers should be stripped of #
        assert not content.startswith("#")

    def test_sync_reference_dir(self, handler, docs_env):
        base, _ = docs_env
        handler.handle("sync", [])

        txt = base / "docs" / "help" / "reference" / "cli-commands.txt"
        assert txt.exists()

    def test_sync_empty_dirs(self, docs_env):
        base, _ = docs_env
        # Remove guides and reference
        import shutil
        shutil.rmtree(base / "docs" / "guides")
        shutil.rmtree(base / "docs" / "reference")

        from hub.docs import DocsHandler
        h = DocsHandler(base)
        ok, msg = h.handle("sync", [])
        assert ok
        assert "0 Dateien" in msg


# ─── Migrate TXT -> MD ───────────────────────────────────

class TestDocsMigrate:
    def test_migrate_creates_md(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("migrate", ["docs/help/task.txt", "docs/guides/task.md"])
        assert ok
        assert "Migration erfolgreich" in msg

        target = base / "docs" / "guides" / "task.md"
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert content.startswith("# ")
        assert "bach task" in content.lower()

    def test_migrate_missing_args(self, handler):
        ok, msg = handler.handle("migrate", [])
        assert not ok
        assert "Usage" in msg

    def test_migrate_one_arg(self, handler):
        ok, msg = handler.handle("migrate", ["source.txt"])
        assert not ok

    def test_migrate_source_not_found(self, handler):
        ok, msg = handler.handle("migrate", ["nonexistent.txt", "output.md"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_migrate_extracts_title(self, handler, docs_env):
        base, _ = docs_env
        src = base / "titled.txt"
        src.write_text("My Custom Title\n\nSome content here.", encoding="utf-8")

        ok, msg = handler.handle("migrate", ["titled.txt", "docs/titled.md"])
        assert ok

        target = base / "docs" / "titled.md"
        content = target.read_text(encoding="utf-8")
        assert "# My Custom Title" in content


# ─── Markdown to Plaintext ────────────────────────────────

class TestMarkdownToPlaintext:
    def test_strip_headers(self, handler):
        result = handler._markdown_to_plaintext("# Title\n## Subtitle")
        assert "Title" in result
        assert "#" not in result

    def test_strip_bold(self, handler):
        result = handler._markdown_to_plaintext("**bold text**")
        assert "bold text" in result
        assert "**" not in result

    def test_strip_italic(self, handler):
        result = handler._markdown_to_plaintext("*italic*")
        assert "italic" in result
        assert result.count("*") == 0

    def test_strip_links(self, handler):
        result = handler._markdown_to_plaintext("[click here](https://example.com)")
        assert result == "click here (https://example.com)"
        assert "[" not in result

    def test_strip_inline_code(self, handler):
        result = handler._markdown_to_plaintext("Use `bach task add`")
        assert "bach task add" in result
        assert "`" not in result

    def test_strip_code_blocks(self, handler):
        md = "```python\nprint('hello')\n```"
        result = handler._markdown_to_plaintext(md)
        assert "print" in result
        assert "```" not in result

    def test_list_bullets(self, handler):
        result = handler._markdown_to_plaintext("- item one\n- item two")
        assert "item one" in result


# ─── Generate README ──────────────────────────────────────

class TestGenerateReadme:
    def test_generate_readme_en(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("generate", ["readme"])
        assert ok
        assert "README" in msg

        readme = base.parent / "README.md"
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        assert "BACH" in content
        assert "4.3.20" in content
        assert "552" in content or "Tools" in content

    def test_generate_readme_de(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("generate", ["readme", "--lang", "de"])
        assert ok

        readme_de = base.parent / "README.de.md"
        assert readme_de.exists()
        content = readme_de.read_text(encoding="utf-8")
        assert "Betriebssystem" in content

    def test_generate_readme_stats(self, handler, docs_env):
        base, _ = docs_env
        handler.handle("generate", ["readme"])
        content = (base.parent / "README.md").read_text(encoding="utf-8")
        assert "2 Skills" in content or "Skills" in content
        assert "1 " in content or "Agents" in content


# ─── Generate API ─────────────────────────────────────────

class TestGenerateAPI:
    def test_generate_api(self, handler, docs_env):
        base, _ = docs_env
        # Create hub/ dir with a handler file for _get_handlers_from_registry
        hub_dir = base / "hub"
        hub_dir.mkdir(exist_ok=True)
        (hub_dir / "task.py").write_text(
            'from .base import BaseHandler\nclass TaskHandler(BaseHandler):\n    """Task Management"""\n    pass\n',
            encoding="utf-8"
        )

        ok, msg = handler.handle("generate", ["api"])
        assert ok
        assert "API-Referenz" in msg

        api_file = base / "docs" / "reference" / "api.md"
        assert api_file.exists()
        content = api_file.read_text(encoding="utf-8")
        assert "Handler" in content
        assert "Tools" in content

    def test_generate_api_tools_by_category(self, handler, docs_env):
        base, _ = docs_env
        (base / "hub").mkdir(exist_ok=True)

        ok, msg = handler.handle("generate", ["api"])
        assert ok

        content = (base / "docs" / "reference" / "api.md").read_text(encoding="utf-8")
        assert "converter" in content
        assert "analysis" in content


# ─── Generate Skills ──────────────────────────────────────

class TestGenerateSkills:
    def test_generate_skills_en(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("generate", ["skills"])
        assert ok
        assert "SKILLS" in msg

        skills_file = base.parent / "SKILLS.md"
        assert skills_file.exists()
        content = skills_file.read_text(encoding="utf-8")
        assert "greeting" in content
        assert "backup" in content

    def test_generate_skills_de(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("generate", ["skills", "--lang", "de"])
        assert ok

        skills_de = base.parent / "SKILLS.de.md"
        assert skills_de.exists()
        content = skills_de.read_text(encoding="utf-8")
        assert "Katalog" in content


# ─── Generate Changelog ──────────────────────────────────

class TestGenerateChangelog:
    def test_generate_changelog(self, handler, docs_env):
        base, _ = docs_env
        ok, msg = handler.handle("generate", ["changelog"])
        assert ok
        assert "CHANGELOG" in msg

        changelog = base.parent / "CHANGELOG.md"
        assert changelog.exists()
        content = changelog.read_text(encoding="utf-8")
        assert "4.3.20" in content
        assert "hub/docs.py" in content or "docs.py" in content

    def test_changelog_dist_type_icons(self, handler, docs_env):
        base, _ = docs_env
        handler.handle("generate", ["changelog"])
        content = (base.parent / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "CORE" in content or "\U0001f534" in content  # 🔴


# ─── Generate Quickstart ─────────────────────────────────

class TestGenerateQuickstart:
    def test_generate_quickstart_en(self, handler, docs_env):
        base, _ = docs_env
        # Need hub/ for _get_handlers_from_registry
        hub_dir = base / "hub"
        hub_dir.mkdir(exist_ok=True)

        ok, msg = handler.handle("generate", ["quickstart"])
        assert ok
        assert "QUICKSTART" in msg

        qs = base.parent / "QUICKSTART.md"
        assert qs.exists()

    def test_generate_quickstart_de(self, handler, docs_env):
        base, _ = docs_env
        (base / "hub").mkdir(exist_ok=True)

        ok, msg = handler.handle("generate", ["quickstart", "--lang", "de"])
        assert ok

        qs_de = base.parent / "QUICKSTART.de.md"
        assert qs_de.exists()
        content = qs_de.read_text(encoding="utf-8")
        assert "Minuten" in content or "Installation" in content


# ─── Generate Unknown Target ─────────────────────────────

class TestGenerateEdgeCases:
    def test_generate_unknown_target(self, handler):
        ok, msg = handler.handle("generate", ["nonexistent"])
        assert not ok
        assert "Unbekanntes Ziel" in msg

    def test_generate_no_args_means_all(self, handler, docs_env):
        base, _ = docs_env
        (base / "hub").mkdir(exist_ok=True)
        ok, msg = handler.handle("generate", [])
        assert ok


# ─── Handler Registry Scan ────────────────────────────────

class TestHandlerRegistry:
    def test_scan_finds_handlers(self, handler, docs_env):
        base, _ = docs_env
        hub_dir = base / "hub"
        hub_dir.mkdir(exist_ok=True)
        (hub_dir / "task.py").write_text(
            'from .base import BaseHandler\nclass TaskHandler(BaseHandler):\n    """Task-Verwaltung"""\n    pass\n',
            encoding="utf-8"
        )
        (hub_dir / "wiki.py").write_text(
            'from .base import BaseHandler\nclass WikiHandler(BaseHandler):\n    """Wiki-System"""\n    pass\n',
            encoding="utf-8"
        )

        handlers = handler._get_handlers_from_registry()
        names = [h[0] for h in handlers]
        assert "task" in names
        assert "wiki" in names

    def test_scan_skips_underscore_files(self, handler, docs_env):
        base, _ = docs_env
        hub_dir = base / "hub"
        hub_dir.mkdir(exist_ok=True)
        (hub_dir / "_internal.py").write_text("class InternalHandler(BaseHandler): pass", encoding="utf-8")
        (hub_dir / "visible.py").write_text("from .base import BaseHandler\nclass VisibleHandler(BaseHandler):\n    pass\n", encoding="utf-8")

        handlers = handler._get_handlers_from_registry()
        names = [h[0] for h in handlers]
        assert "_internal" not in names
        assert "visible" in names

    def test_scan_extracts_docstring(self, handler, docs_env):
        base, _ = docs_env
        hub_dir = base / "hub"
        hub_dir.mkdir(exist_ok=True)
        (hub_dir / "custom.py").write_text(
            'from .base import BaseHandler\nclass CustomHandler(BaseHandler):\n    """Custom doc description"""\n    pass\n',
            encoding="utf-8"
        )

        handlers = handler._get_handlers_from_registry()
        custom = [h for h in handlers if h[0] == "custom"]
        assert len(custom) == 1
        assert "Custom doc description" in custom[0][1]

    def test_scan_empty_hub(self, handler, docs_env):
        base, _ = docs_env
        hub_dir = base / "hub"
        hub_dir.mkdir(exist_ok=True)
        # No .py files
        handlers = handler._get_handlers_from_registry()
        assert handlers == []

    def test_scan_missing_hub_dir(self, tmp_path, monkeypatch):
        base = tmp_path / "system"
        base.mkdir()
        (base / "data").mkdir()
        db_path = base / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)

        from hub.docs import DocsHandler
        h = DocsHandler(base)
        assert h._get_handlers_from_registry() == []


# ─── Build Content Templates ─────────────────────────────

class TestBuildContent:
    def test_build_readme_en(self, handler):
        stats = {"skills": 10, "agents": 5, "tools": 100, "lessons": 20, "facts": 50, "workflows": 8}
        content = handler._build_readme_content(stats, "4.3.20", lang="en")
        assert "BACH" in content
        assert "4.3.20" in content
        assert "100 Tools" in content
        assert "10 Skills" in content

    def test_build_readme_de(self, handler):
        stats = {"skills": 10, "agents": 5, "tools": 100, "lessons": 20, "facts": 50, "workflows": 8}
        content = handler._build_readme_content(stats, "4.3.20", lang="de")
        assert "Betriebssystem" in content
        assert "KI-Agenten" in content

    def test_build_readme_unknown_lang_falls_back_en(self, handler):
        stats = {"skills": 1, "agents": 1, "tools": 1, "lessons": 1, "facts": 1, "workflows": 1}
        content = handler._build_readme_content(stats, "1.0", lang="fr")
        assert "Overview" in content  # Falls back to EN

    def test_build_api_content(self, handler):
        handlers = [("task", "hub.task", "Task management")]
        tools = {"converter": [("md_to_pdf", "Converts MD", "tools/md_to_pdf.py")]}
        content = handler._build_api_content(handlers, tools)
        assert "bach task" in content
        assert "converter" in content
        assert "md_to_pdf" in content

    def test_build_skills_content_en(self, handler):
        skills = {"protocol": [("greeting", "social", "Greeting skill")]}
        content = handler._build_skills_content(skills, lang="en")
        assert "Skills Catalog" in content
        assert "greeting" in content

    def test_build_skills_content_de(self, handler):
        skills = {"protocol": [("greeting", "social", "Greeting skill")]}
        content = handler._build_skills_content(skills, lang="de")
        assert "Katalog" in content

    def test_build_changelog_content(self, handler):
        versions = [("4.3.20", "hub/docs.py", "abcdef1234567890", "2026-05-15T10:00:00", 2)]
        content = handler._build_changelog_content(versions, "4.3.20")
        assert "4.3.20" in content
        assert "docs.py" in content

    def test_build_quickstart_en(self, handler):
        handlers = [("task", "Task management")]
        content = handler._build_quickstart_content("4.3.20", handlers, lang="en")
        assert "Quickstart" in content
        assert "4.3.20" in content

    def test_build_quickstart_de(self, handler):
        handlers = [("task", "Task management")]
        content = handler._build_quickstart_content("4.3.20", handlers, lang="de")
        assert "Minuten" in content or "Installation" in content
