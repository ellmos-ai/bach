"""Tests for tools/fs_protection.py — PathClassifier logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from tools.fs_protection import PathClassifier


@pytest.fixture
def classifier():
    return PathClassifier(base_path=Path("/fake/bach/system"))


class TestPathClassifierCore:
    def test_hub_handler_is_core(self, classifier):
        assert classifier.classify_path(Path("hub/setup.py")) == 2

    def test_hub_nested_is_core(self, classifier):
        assert classifier.classify_path(Path("hub/_services/chat/chat_runtime.py")) == 2

    def test_tools_py_is_core(self, classifier):
        assert classifier.classify_path(Path("tools/text_chunker.py")) == 2

    def test_gui_py_is_core(self, classifier):
        assert classifier.classify_path(Path("gui/server.py")) == 2

    def test_gui_html_is_core(self, classifier):
        assert classifier.classify_path(Path("gui/templates/tasks.html")) == 2

    def test_gui_static_is_core(self, classifier):
        assert classifier.classify_path(Path("gui/static/js/nav.js")) == 2

    def test_connectors_py_is_core(self, classifier):
        assert classifier.classify_path(Path("connectors/telegram_connector.py")) == 2

    def test_agents_md_is_core(self, classifier):
        assert classifier.classify_path(Path("agents/bueroassistent.md")) == 2

    def test_agents_experts_is_core(self, classifier):
        assert classifier.classify_path(Path("agents/_experts/steuer/steuer.md")) == 2

    def test_skills_workflows_is_core(self, classifier):
        assert classifier.classify_path(Path("skills/workflows/daily_report.md")) == 2

    def test_skills_services_py_is_core(self, classifier):
        assert classifier.classify_path(Path("skills/_services/chat/chat_runtime.py")) == 2

    def test_partners_is_core(self, classifier):
        assert classifier.classify_path(Path("partners/claude/setup.json")) == 2


class TestPathClassifierUser:
    def test_user_dir_is_user(self, classifier):
        assert classifier.classify_path(Path("user/notes.md")) == 0

    def test_user_nested_is_user(self, classifier):
        assert classifier.classify_path(Path("user/secrets/secrets.json")) == 0

    def test_archive_is_user(self, classifier):
        assert classifier.classify_path(Path("_archive/old_file.py")) == 0

    def test_tools_user_is_user(self, classifier):
        assert classifier.classify_path(Path("tools/_user/my_tool.py")) == 0

    def test_tools_archive_is_user(self, classifier):
        assert classifier.classify_path(Path("tools/_archive/old.py")) == 0

    def test_logs_is_user(self, classifier):
        assert classifier.classify_path(Path("logs/2026-05-17.log")) == 0

    def test_db_files_are_user(self, classifier):
        assert classifier.classify_path(Path("data/bach.db")) in (0, 1)


class TestPathClassifierTemplate:
    def test_schema_sql_is_template(self, classifier):
        assert classifier.classify_path(Path("data/schema.sql")) == 1

    def test_readme_is_template(self, classifier):
        assert classifier.classify_path(Path("README.md")) == 1

    def test_roadmap_is_template(self, classifier):
        assert classifier.classify_path(Path("ROADMAP.md")) == 1

    def test_identity_user_takes_priority(self, classifier):
        # user/* pattern matches first, before TEMPLATE_PATTERNS
        assert classifier.classify_path(Path("user/IDENTITY.md")) == 0

    def test_help_docs_are_template(self, classifier):
        assert classifier.classify_path(Path("docs/help/setup.md")) == 1


class TestPathClassifierDefaults:
    def test_unknown_file_defaults_to_user(self, classifier):
        # Default is USER (0) for safety — unknown files not included in distribution
        result = classifier.classify_path(Path("some_new_file.py"))
        assert result == 0

    def test_backslash_normalization(self, classifier):
        result = classifier.classify_path(Path("hub\\setup.py"))
        assert result == 2


class TestPathClassifierInit:
    def test_default_base_path(self):
        c = PathClassifier()
        assert c.base_path is not None

    def test_custom_base_path(self):
        p = Path("/custom/path")
        c = PathClassifier(base_path=p)
        assert c.base_path == p
