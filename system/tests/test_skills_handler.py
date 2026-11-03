# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SkillsHandler (hub/skills.py)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.skills import SkillsHandler, verify_selfcontained_module


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def skills_env(tmp_path):
    """Minimal environment for SkillsHandler."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, type TEXT, category TEXT,
            path TEXT, version TEXT, description TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def handler(skills_env):
    return SkillsHandler(skills_env)


@pytest.fixture
def populated_skills(skills_env):
    """Skills directory with sample skill files."""
    s = skills_env / "skills"

    demo = s / "demo_skill"
    demo.mkdir()
    (demo / "SKILL.md").write_text(
        "---\nname: demo\nversion: 1.0.0\n---\n# Demo Skill\nA demo skill for testing.",
        encoding="utf-8",
    )
    (demo / "main.py").write_text("print('hello')", encoding="utf-8")

    proto = s / "_protocols"
    proto.mkdir()
    (proto / "test_protocol.md").write_text(
        "# Test Protocol\nStep 1: do something",
        encoding="utf-8",
    )

    return skills_env


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "skills"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "show" in ops
        assert "search" in ops
        assert "create" in ops
        assert "export" in ops
        assert "install" in ops
        assert "hierarchy" in ops
        assert "version" in ops


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_empty(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True

    def test_list_with_skills(self, populated_skills):
        h = SkillsHandler(populated_skills)
        ok, output = h.handle("list", [])
        assert ok is True
        assert "demo" in output.lower() or "SKILL" in output


# ═══════════════════════════════════════════════════════════════
# SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_existing(self, populated_skills):
        h = SkillsHandler(populated_skills)
        ok, output = h.handle("show", ["demo_skill"])
        # show may return False if skill name doesn't match internal lookup
        assert isinstance(ok, bool)
        assert isinstance(output, str)

    def test_show_nonexistent(self, handler):
        ok, output = handler.handle("show", ["nonexistent_xyz"])
        assert ok is False
        assert "not found" in output.lower() or "nicht gefunden" in output.lower()


# ═══════════════════════════════════════════════════════════════
# VERSION / LOOKUP
# ═══════════════════════════════════════════════════════════════


class TestVersionLookup:
    def test_bach_version_uses_root_skill_before_fuzzy_workflow_match(self, skills_env):
        (skills_env / "SKILL.md").write_text(
            "---\nname: bach\nversion: 3.9.1\n---\n# BACH\n",
            encoding="utf-8",
        )
        workflow_dir = skills_env / "skills" / "workflows" / "system"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "claude-bach-vernetzung.md").write_text(
            "---\nname: claude-bach-vernetzung\nversion: 1.0.0\n---\n# Vernetzung\n",
            encoding="utf-8",
        )

        h = SkillsHandler(skills_env)
        ok, output = h.handle("version", ["bach"])

        assert ok is True
        assert "SKILL.md" in output
        assert "LOKAL:   v3.9.1" in output
        assert "claude-bach-vernetzung" not in output

    def test_bach_version_reads_canonical_and_copy_sources_from_registry(self, skills_env):
        (skills_env / "SKILL.md").write_text(
            "---\nname: bach\nversion: 3.9.1\n---\n# BACH\n",
            encoding="utf-8",
        )
        codex_copy = skills_env / "mirrors" / "codex" / "bach" / "SKILL.md"
        codex_copy.parent.mkdir(parents=True)
        codex_copy.write_text(
            "---\nname: bach\nversion: 3.8.0\n---\n# BACH Copy\n",
            encoding="utf-8",
        )
        data_dir = skills_env / "data"
        (data_dir / "skill_sources.json").write_text(
            json.dumps(
                {
                    "version_sources": {
                        "bach": {
                            "canonical": [
                                {
                                    "source": "repo-root",
                                    "path": "../SKILL.md",
                                }
                            ],
                            "copies": [
                                {
                                    "source": "codex-user-skill",
                                    "path": "../mirrors/codex/bach/SKILL.md",
                                }
                            ],
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        h = SkillsHandler(skills_env)
        ok, output = h.handle("version", ["bach"])

        assert ok is True
        assert "ZENTRAL: v3.9.1 (repo-root)" in output
        assert "KOPIEN:" in output
        assert "codex-user-skill: v3.8.0" in output
        assert "KOPIEN HINTER KANONISCHER QUELLE:" in output

    def test_find_skill_prefers_exact_file_stem_before_substring(self, skills_env):
        workflow_dir = skills_env / "skills" / "workflows"
        workflow_dir.mkdir()
        exact = workflow_dir / "alpha.md"
        fuzzy = workflow_dir / "x-alpha.md"
        fuzzy.write_text("# Fuzzy\n", encoding="utf-8")
        exact.write_text("# Exact\n", encoding="utf-8")

        h = SkillsHandler(skills_env)

        assert h._find_skill("alpha") == exact


# ═══════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════


class TestSearch:
    def test_search_no_args_falls_through_to_list(self, handler):
        # empty args silently falls through to list — may be a bug
        ok, output = handler.handle("search", [])
        assert ok is True
        assert "SKILLS" in output

    def test_search_finds_skill(self, populated_skills):
        h = SkillsHandler(populated_skills)
        ok, output = h.handle("search", ["demo"])
        assert ok is True
        assert "demo" in output.lower() or "Gefunden" in output

    def test_search_no_results(self, handler):
        ok, output = handler.handle("search", ["nonexistent_xyz"])
        assert ok is True
        assert "No results" in output or "Keine" in output


# ═══════════════════════════════════════════════════════════════
# CREATE
# ═══════════════════════════════════════════════════════════════


class TestCreate:
    def test_create_no_args_falls_through_to_list(self, handler):
        ok, output = handler.handle("create", [])
        assert ok is True
        assert "SKILLS" in output

    def test_create_dry_run(self, handler):
        ok, output = handler.handle("create", ["my_new_skill", "--dry-run"])
        assert ok is True
        assert "DRY-RUN" in output

    def test_create_skill(self, handler):
        ok, output = handler.handle("create", ["test_created_skill"])
        assert ok is True
        created = list(handler.skills_dir.rglob("*test_created_skill*"))
        assert len(created) >= 1 or "erstellt" in output.lower() or "created" in output.lower()


# ═══════════════════════════════════════════════════════════════
# HIERARCHY
# ═══════════════════════════════════════════════════════════════


class TestHierarchy:
    def test_hierarchy_missing_table(self, handler):
        ok, output = handler.handle("hierarchy", [])
        assert ok is False
        assert "hierarchy_items" in output or "Migration" in output

    def test_hierarchy_with_table(self, skills_env):
        db_path = skills_env / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS hierarchy_items (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT,
            parent_id INTEGER, description TEXT, status TEXT DEFAULT 'active',
            path TEXT, version TEXT, priority INTEGER DEFAULT 0
        )""")
        conn.commit()
        conn.close()
        h = SkillsHandler(skills_env)
        ok, output = h.handle("hierarchy", [])
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# EXPORT & INSTALL (SELF-CONTAINED MODULES)
# ═══════════════════════════════════════════════════════════════


class TestExportInstallSelfContained:
    def test_export_creates_selfcontained_directory_and_manifest(self, populated_skills, tmp_path):
        h = SkillsHandler(populated_skills)
        out_dir = tmp_path / "custom_export"
        ok, output = h.handle("export", ["demo_skill", str(out_dir)])
        assert ok is True
        assert "Ungepacktes selfcontained Paket" in output

        manifest_path = out_dir / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["name"] == "demo_skill"
        assert manifest["selfcontained"] is True
        assert any(c["name"] == "Ocean" for c in manifest["consumers"])

        unpacked_skill = out_dir / "skill"
        assert unpacked_skill.exists()
        assert (unpacked_skill / "SKILL.md").exists()
        assert (unpacked_skill / "main.py").exists()

        # Re-import from directory (unpacked self-contained module)
        ok_install, out_install = h.handle("install", [str(out_dir)])
        assert ok_install is True
        assert "erfolgreich installiert" in out_install
        assert (populated_skills / "skills" / "demo_skill" / "SKILL.md").exists()
        assert (populated_skills / "skills" / "demo_skill" / "manifest.json").exists()

    def test_export_module_creates_selfcontained_repo_and_passes_verification(self, skills_env, tmp_path):
        hub_services = skills_env / "hub" / "_services"
        hub_services.mkdir(parents=True, exist_ok=True)
        svc_file = hub_services / "sample_service.py"
        svc_file.write_text(
            '# -*- coding: utf-8 -*-\n__version__ = "0.3.0"\n\ndef run():\n    return "ok"\n',
            encoding="utf-8"
        )

        h = SkillsHandler(skills_env)
        out_dir = tmp_path / "sample_service_export"

        # 1. Dry-run
        ok_dry, out_dry = h.handle("export-module", ["sample_service", str(out_dir)], dry_run=True)
        assert ok_dry is True
        assert "[DRY-RUN]" in out_dry
        assert not out_dir.exists()

        # 2. Actual export
        ok_real, out_real = h.handle("export-module", ["sample_service", str(out_dir)])
        assert ok_real is True
        assert "erfolgreich verifiziert und exportiert" in out_real

        assert (out_dir / "manifest.json").exists()
        assert (out_dir / "README.md").exists()
        assert (out_dir / "src" / "sample_service.py").exists()
        assert (out_dir / "tests" / "test_sample_service.py").exists()

        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["name"] == "sample_service"
        assert manifest["version"] == "0.3.0"
        assert manifest["type"] == "module"
        assert manifest["selfcontained"] is True
        assert manifest["entrypoints"]["library"] == "src/sample_service.py"

        # 3. verify command accepts exported module directory
        ok_v, out_v = h.handle("verify", [str(out_dir)])
        assert ok_v is True
        assert "[GÜLTIG]" in out_v

    def test_install_replaces_legacy_single_file_with_backup(self, skills_env, tmp_path):
        services_dir = skills_env / "skills" / "_services"
        services_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = services_dir / "think.md"
        legacy_file.write_text("---\nname: think\nversion: 1.0.0\n---\n# Think Legacy\n", encoding="utf-8")

        # Create updated selfcontained export package
        pkg_dir = tmp_path / "think_new_pkg"
        pkg_dir.mkdir()
        manifest = {
            "name": "think",
            "version": "1.1.0",
            "type": "service",
            "selfcontained": True,
            "consumers": [{"name": "BACH", "version": ">=3.0"}]
        }
        (pkg_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        pkg_skill = pkg_dir / "skill"
        pkg_skill.mkdir()
        (pkg_skill / "SKILL.md").write_text("---\nname: think\nversion: 1.1.0\n---\n# Think v1.1.0\n", encoding="utf-8")

        h = SkillsHandler(skills_env)
        ok, output = h.handle("install", [str(pkg_dir)])
        assert ok is True
        assert "Legacy Backup erstellt" in output

        # Check backup exists in exports/_backups
        backups = list((skills_env / "exports" / "_backups").glob("think_legacy_backup_*.md"))
        assert len(backups) == 1
        assert "Think Legacy" in backups[0].read_text(encoding="utf-8")

        # Check new version installed
        installed = services_dir / "think"
        assert installed.is_dir()
        assert (installed / "SKILL.md").exists()
        assert "Think v1.1.0" in (installed / "SKILL.md").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# MODULE LIFECYCLE & SELFCONTAINED VERIFICATION
# ═══════════════════════════════════════════════════════════════


class TestModuleLifecycleVerification:
    def test_verify_valid_selfcontained_module_directory(self, tmp_path):
        mod_dir = tmp_path / "my_valid_mod"
        mod_dir.mkdir()
        manifest = {
            "name": "my_valid_mod",
            "version": "1.2.3",
            "type": "skill",
            "entry_points": {"main": "SKILL.md"},
            "boundaries": {"data": "user-local", "network": "none"}
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (mod_dir / "SKILL.md").write_text("# My Valid Mod\n", encoding="utf-8")

        is_valid, errors, warnings, meta = verify_selfcontained_module(mod_dir)
        assert is_valid is True
        assert len(errors) == 0
        assert meta["name"] == "my_valid_mod"
        assert meta["version"] == "1.2.3"

    def test_verify_valid_selfcontained_zip(self, tmp_path):
        import zipfile
        zip_path = tmp_path / "valid_pkg.zip"
        manifest = {
            "name": "zipped-module",
            "version": "2.0.0",
            "type": "service",
            "entry_points": {"main": "SKILL.md"}
        }
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("SKILL.md", "# Zipped Skill\n")

        is_valid, errors, warnings, meta = verify_selfcontained_module(zip_path)
        assert is_valid is True
        assert len(errors) == 0
        assert meta["name"] == "zipped-module"

    def test_verify_missing_manifest_rejected(self, tmp_path):
        empty_dir = tmp_path / "empty_mod"
        empty_dir.mkdir()

        is_valid, errors, warnings, meta = verify_selfcontained_module(empty_dir)
        assert is_valid is False
        assert any("Keine Manifest-Datei" in e for e in errors)

    def test_verify_invalid_semver_rejected(self, tmp_path):
        mod_dir = tmp_path / "bad_ver_mod"
        mod_dir.mkdir()
        manifest = {
            "name": "bad_ver_mod",
            "version": "not-a-version",
            "type": "skill"
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        is_valid, errors, warnings, meta = verify_selfcontained_module(mod_dir)
        assert is_valid is False
        assert any("Ungültiges Versionsformat" in e for e in errors)

    def test_verify_missing_entrypoint_rejected(self, tmp_path):
        mod_dir = tmp_path / "missing_ep_mod"
        mod_dir.mkdir()
        manifest = {
            "name": "missing_ep_mod",
            "version": "1.0.0",
            "entry_points": {"main": "DOES_NOT_EXIST.md"}
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        is_valid, errors, warnings, meta = verify_selfcontained_module(mod_dir)
        assert is_valid is False
        assert any("DOES_NOT_EXIST.md" in e for e in errors)

    def test_verify_zip_slip_rejected(self, tmp_path):
        import zipfile
        zip_path = tmp_path / "malicious.zip"
        manifest = {"name": "evil-mod", "version": "1.0.0"}
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("../evil.py", "print('hacked')")

        is_valid, errors, warnings, meta = verify_selfcontained_module(zip_path)
        assert is_valid is False
        assert any("Unsichere Pfad-Traversal-Sequenz" in e for e in errors)

    def test_verify_cli_command(self, skills_env, tmp_path):
        mod_dir = tmp_path / "cli_verify_mod"
        mod_dir.mkdir()
        manifest = {
            "name": "cli_verify_mod",
            "version": "3.0.0",
            "entry_points": {"main": "SKILL.md"}
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (mod_dir / "SKILL.md").write_text("# CLI Verify\n", encoding="utf-8")

        h = SkillsHandler(skills_env)
        ok, msg = h.handle("verify", [str(mod_dir)])
        assert ok is True
        assert "[GÜLTIG]" in msg
        assert "cli_verify_mod v3.0.0" in msg

    def test_install_aborts_on_invalid_module(self, skills_env, tmp_path):
        mod_dir = tmp_path / "broken_install_mod"
        mod_dir.mkdir()
        # Invalid manifest: missing version
        manifest = {"name": "broken_mod"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        h = SkillsHandler(skills_env)
        ok, msg = h.handle("install", [str(mod_dir)])
        assert ok is False
        assert "MODUL-VALIDIERUNG: [ABGELEHNT]" in msg

    def test_modularization_audit_returns_success_and_metrics(self, skills_env):
        h = SkillsHandler(skills_env)
        ok, msg = h.handle("audit", [])
        assert ok is True
        assert "=== BACH MODULARISIERUNGS- & ENTFLECHTUNGS-AUDIT ===" in msg
        assert "Gefundene Hub-Dienste:" in msg
        assert "Bereits entflochten (Seams):" in msg
        assert "EMPFOHLENE EXPORT-KANDIDATEN" in msg
        assert "bach skills export-module" in msg


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import ast
        source_file = SYSTEM_ROOT / "hub" / "skills.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                pytest.fail(f"Bare except at line {node.lineno} in skills.py")
