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


def test_manifest_paths_resolve_system_and_repository_roots(tmp_path):
    """Legacy manifest rows can be relative to either supported root."""
    from tools.fs_protection import FSProtection

    project_root = tmp_path / "project"
    system_root = project_root / "system"
    (system_root / "hub").mkdir(parents=True)
    (system_root / "hub" / "base.py").write_text("# core", encoding="utf-8")
    (project_root / "README.md").write_text("# root", encoding="utf-8")

    protection = FSProtection(system_root)

    assert protection._resolve_manifest_path("hub/base.py") == system_root / "hub" / "base.py"
    assert protection._resolve_manifest_path("README.md") == project_root / "README.md"
    assert protection._resolve_manifest_path("system/missing.py") == system_root / "missing.py"


def test_heal_all_fails_closed_without_snapshots(tmp_path, monkeypatch):
    """A repair must never claim success when no recovery material exists."""
    from tools import fs_protection

    snapshots = tmp_path / "snapshots"
    monkeypatch.setattr(fs_protection, "SNAPSHOTS_DIR", snapshots)
    protection = fs_protection.FSProtection(tmp_path)

    ok, message = protection.heal()

    assert ok is False
    assert "Keine gueltigen Snapshots" in message


class TestSanitizeHostPath:
    def test_valid_relative_within_base(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        base = tmp_path / "system"
        base.mkdir()
        target = base / "hub" / "setup.py"
        target.parent.mkdir()
        target.write_text("# ok", encoding="utf-8")

        res = sanitize_host_path("hub/setup.py", base_path=base)
        assert res == target.resolve()

    def test_valid_absolute_within_base(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        base = tmp_path / "system"
        base.mkdir()
        target = base / "file.txt"
        target.write_text("data", encoding="utf-8")

        res = sanitize_host_path(target, base_path=base)
        assert res == target.resolve()

    def test_repo_root_allowed_when_base_is_system(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        project_root = tmp_path / "project"
        system_root = project_root / "system"
        system_root.mkdir(parents=True)
        readme = project_root / "README.md"
        readme.write_text("# hello", encoding="utf-8")

        res = sanitize_host_path(readme, base_path=system_root)
        assert res == readme.resolve()

    def test_explicit_allowed_roots(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        root1 = tmp_path / "r1"
        root2 = tmp_path / "r2"
        root1.mkdir()
        root2.mkdir()
        f2 = root2 / "sample.txt"
        f2.write_text("text", encoding="utf-8")

        res = sanitize_host_path(f2, base_path=root1, allowed_roots=[root1, root2])
        assert res == f2.resolve()

    def test_empty_or_none_raises_value_error(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        with pytest.raises(ValueError, match="Ungueltiger Pfad"):
            sanitize_host_path(None, base_path=tmp_path)

        with pytest.raises(ValueError, match="Ungueltiger Pfad"):
            sanitize_host_path("", base_path=tmp_path)

        with pytest.raises(ValueError, match="Ungueltiger Pfad"):
            sanitize_host_path("   ", base_path=tmp_path)

    def test_traversal_blocked(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        base = tmp_path / "system"
        base.mkdir()

        with pytest.raises(ValueError, match="Pfad-Traversal oder unerlaubter Pfad erkannt"):
            sanitize_host_path("../../outside.txt", base_path=base)

        with pytest.raises(ValueError, match="Pfad-Traversal oder unerlaubter Pfad erkannt"):
            sanitize_host_path("hub/../../../../escape.py", base_path=base)

    def test_absolute_outside_blocked(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        bach_root = tmp_path / "bach_root"
        base = bach_root / "system"
        base.mkdir(parents=True)
        outside = tmp_path / "foreign" / "secret.txt"
        outside.parent.mkdir()
        outside.write_text("secret", encoding="utf-8")

        with pytest.raises(ValueError, match="Pfad-Traversal oder unerlaubter Pfad erkannt"):
            sanitize_host_path(outside, base_path=base)

    def test_symlink_escape_blocked(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        bach_root = tmp_path / "bach_root"
        base = bach_root / "system"
        base.mkdir(parents=True)
        secret_dir = tmp_path / "outside_secret"
        secret_dir.mkdir()
        secret_file = secret_dir / "secret.txt"
        secret_file.write_text("confidential", encoding="utf-8")

        link = base / "symlink_secret"
        try:
            link.symlink_to(secret_file)
        except OSError:
            pytest.skip("Symlink creation not supported in this environment")

        with pytest.raises(ValueError, match="Symlink-Escape erkannt"):
            sanitize_host_path(link, base_path=base)

    def test_symlink_within_root_allowed(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        bach_root = tmp_path / "bach_root"
        base = bach_root / "system"
        base.mkdir(parents=True)
        target_file = base / "real_file.txt"
        target_file.write_text("allowed", encoding="utf-8")

        link = base / "link_internal.txt"
        try:
            link.symlink_to(target_file)
        except OSError:
            pytest.skip("Symlink creation not supported in this environment")

        res = sanitize_host_path(link, base_path=base)
        assert res == target_file.resolve()

    def test_must_exist_flag(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        base = tmp_path / "system"
        base.mkdir()

        non_existent = base / "does_not_exist.txt"
        res = sanitize_host_path(non_existent, base_path=base, must_exist=False)
        assert res == non_existent.resolve()

        with pytest.raises(ValueError, match="Pfad existiert nicht"):
            sanitize_host_path(non_existent, base_path=base, must_exist=True)

        non_existent.write_text("now exists", encoding="utf-8")
        res2 = sanitize_host_path(non_existent, base_path=base, must_exist=True)
        assert res2 == non_existent.resolve()

    def test_allow_relative_returns_relative_path(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        base = tmp_path / "system"
        base.mkdir()

        rel = sanitize_host_path("hub/sub/file.py", base_path=base, allow_relative=True)
        assert not rel.is_absolute()
        assert rel == Path("hub/sub/file.py")

    def test_bach_home_environment_allowed(self, tmp_path, monkeypatch):
        from tools.fs_protection import sanitize_host_path

        bach_root = tmp_path / "bach_root"
        base = bach_root / "system"
        base.mkdir(parents=True)
        home_dir = tmp_path / "bach_home"
        home_dir.mkdir()
        home_file = home_dir / "tasks.db"
        home_file.write_text("db", encoding="utf-8")

        monkeypatch.setenv("BACH_HOME", str(home_dir))

        res = sanitize_host_path(home_file, base_path=base)
        assert res == home_file.resolve()

    def test_system_prefixed_relative_path(self, tmp_path):
        from tools.fs_protection import sanitize_host_path

        project_root = tmp_path / "project"
        system_root = project_root / "system"
        system_root.mkdir(parents=True)
        target = system_root / "hub" / "setup.py"
        target.parent.mkdir()
        target.write_text("# ok", encoding="utf-8")

        res = sanitize_host_path("system/hub/setup.py", base_path=system_root)
        assert res == target.resolve()

    def test_cli_sanitize_invocation(self, tmp_path, monkeypatch, capsys):
        import sys

        import tools.fs_protection as fsp
        from tools.fs_protection import main

        base = tmp_path / "system"
        base.mkdir()
        monkeypatch.setattr(fsp, "BASE_DIR", base)
        f = base / "valid.txt"
        f.write_text("test", encoding="utf-8")

        # Success case
        monkeypatch.setattr(sys, "argv", ["fs_protection.py", "sanitize", str(f)])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "Sanitized:" in out

        # Failure case
        monkeypatch.setattr(sys, "argv", ["fs_protection.py", "sanitize", "../../invalid.txt"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        out, _ = capsys.readouterr()
        assert "[FEHLER]" in out


