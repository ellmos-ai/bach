# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for bach_paths.py (hub/bach_paths.py)."""

import os
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import bach as bach_cli
from hub import bach_paths
from hub.bach_paths import (
    BACH_ROOT,
    SYSTEM_ROOT as BP_SYSTEM_ROOT,
    HUB_DIR,
    DATA_DIR,
    GUI_DIR,
    SKILLS_DIR,
    TOOLS_DIR,
    AGENTS_DIR,
    EXPERTS_DIR,
    PARTNERS_DIR,
    CONNECTORS_DIR,
    HELP_DIR,
    LOGS_DIR,
    BACKUPS_DIR,
    LOCAL_BACH_DIR,
    BACH_DB,
    get_path,
    list_paths,
    get_db,
    get_tool_path,
    get_partner_dir,
    get_belege_path,
    resolve,
)


# ═══════════════════════════════════════════════════════════════
# HIERARCHY / STRUCTURE
# ═══════════════════════════════════════════════════════════════


class TestHierarchy:
    def test_hub_dir_is_parent_of_this_module(self):
        assert HUB_DIR == Path(bach_paths.__file__).parent.resolve()

    def test_system_root_is_parent_of_hub(self):
        assert BP_SYSTEM_ROOT == HUB_DIR.parent.resolve()

    def test_bach_root_is_parent_of_system(self):
        assert BACH_ROOT == BP_SYSTEM_ROOT.parent.resolve()

    def test_data_dir_under_system(self):
        assert DATA_DIR == BP_SYSTEM_ROOT / "data"

    def test_gui_dir_under_system(self):
        assert GUI_DIR == BP_SYSTEM_ROOT / "gui"

    def test_skills_dir_under_system(self):
        assert SKILLS_DIR == BP_SYSTEM_ROOT / "skills"

    def test_tools_dir_under_system(self):
        assert TOOLS_DIR == BP_SYSTEM_ROOT / "tools"

    def test_agents_dir_under_system(self):
        assert AGENTS_DIR == BP_SYSTEM_ROOT / "agents"

    def test_experts_dir_under_agents(self):
        assert EXPERTS_DIR == AGENTS_DIR / "_experts"

    def test_partners_dir_under_system(self):
        assert PARTNERS_DIR == BP_SYSTEM_ROOT / "partners"

    def test_connectors_dir_under_system(self):
        assert CONNECTORS_DIR == BP_SYSTEM_ROOT / "connectors"

    def test_help_dir_path(self):
        assert HELP_DIR == BP_SYSTEM_ROOT / "docs" / "help"


# ═══════════════════════════════════════════════════════════════
# BACKUPS DIR CROSS-OS
# ═══════════════════════════════════════════════════════════════


class TestBackupsDir:
    def test_backups_dir_is_path(self):
        assert isinstance(BACKUPS_DIR, Path)

    def test_backups_dir_platform_dependent(self):
        if "BACH_BACKUPS_DIR" in os.environ:
            assert BACKUPS_DIR == Path(os.environ["BACH_BACKUPS_DIR"]).expanduser()
        else:
            assert ".bach" in str(BACKUPS_DIR)
            assert "backups" in str(BACKUPS_DIR).lower()


# ═══════════════════════════════════════════════════════════════
# LOCAL / DB PATHS
# ═══════════════════════════════════════════════════════════════


class TestDbPaths:
    def test_local_bach_dir(self):
        assert LOCAL_BACH_DIR == Path.home() / ".bach"

    def test_bach_db_is_path(self):
        assert isinstance(BACH_DB, Path)
        assert BACH_DB.name == "bach.db"

    def test_cli_runtime_uses_canonical_bach_db(self):
        assert bach_cli.DB_PATH == BACH_DB

    def test_get_db_default(self):
        assert get_db() == BACH_DB

    def test_get_db_user_alias(self):
        assert get_db("user") == BACH_DB

    def test_get_db_bach(self):
        assert get_db("bach") == BACH_DB

    def test_resolve_db_blocks_implicit_onedrive_fallback(self, tmp_path, monkeypatch):
        local_db = tmp_path / "home" / ".bach" / "bach.db"
        onedrive_db = tmp_path / "OneDrive" / ".TOPICS" / ".AI" / ".OS" / "BACH" / "system" / "data" / "bach.db"
        onedrive_db.parent.mkdir(parents=True)
        onedrive_db.write_bytes(b"not empty")

        monkeypatch.delenv("BACH_DB", raising=False)
        monkeypatch.delenv("BACH_ALLOW_ONEDRIVE_DB_FALLBACK", raising=False)
        monkeypatch.setattr(bach_paths, "_LOCAL_DB", local_db)
        monkeypatch.setattr(bach_paths, "ONEDRIVE_DB", onedrive_db)

        assert bach_paths._resolve_bach_db() == local_db

    def test_resolve_db_allows_explicit_onedrive_fallback(self, tmp_path, monkeypatch):
        local_db = tmp_path / "home" / ".bach" / "bach.db"
        onedrive_db = tmp_path / "OneDrive" / ".TOPICS" / ".AI" / ".OS" / "BACH" / "system" / "data" / "bach.db"
        onedrive_db.parent.mkdir(parents=True)
        onedrive_db.write_bytes(b"not empty")

        monkeypatch.delenv("BACH_DB", raising=False)
        monkeypatch.setenv("BACH_ALLOW_ONEDRIVE_DB_FALLBACK", "1")
        monkeypatch.setattr(bach_paths, "_LOCAL_DB", local_db)
        monkeypatch.setattr(bach_paths, "ONEDRIVE_DB", onedrive_db)

        assert bach_paths._resolve_bach_db() == onedrive_db


# ═══════════════════════════════════════════════════════════════
# get_path()
# ═══════════════════════════════════════════════════════════════


class TestGetPath:
    def test_root(self):
        assert get_path("root") == BACH_ROOT

    def test_system(self):
        assert get_path("system") == BP_SYSTEM_ROOT

    def test_hub(self):
        assert get_path("hub") == HUB_DIR

    def test_data(self):
        assert get_path("data") == DATA_DIR

    def test_tools(self):
        assert get_path("tools") == TOOLS_DIR

    def test_agents(self):
        assert get_path("agents") == AGENTS_DIR

    def test_case_insensitive(self):
        assert get_path("ROOT") == get_path("root")
        assert get_path("Data") == get_path("data")

    def test_dash_underscore_interchangeable(self):
        assert get_path("bach-db") == get_path("bach_db")

    def test_unknown_path_raises(self):
        with pytest.raises(KeyError, match="Unbekannter Pfad"):
            get_path("nonexistent_path_xyz")

    def test_unknown_path_lists_available(self):
        with pytest.raises(KeyError, match="Verfügbar"):
            get_path("nonexistent")

    def test_db_path(self):
        assert get_path("db") == BACH_DB

    def test_partners(self):
        assert get_path("partners") == PARTNERS_DIR

    def test_connectors(self):
        assert get_path("connectors") == CONNECTORS_DIR


class TestCliHelpers:
    def test_folders_helper_uses_canonical_bach_db(self, monkeypatch):
        from hub import folders as folders_module

        captured = {}

        def fake_handle_folders(db_path, args):
            captured["db_path"] = db_path
            captured["args"] = args
            return 0

        monkeypatch.setattr(folders_module, "_handle_folders", fake_handle_folders)

        result = bach_cli._handle_folders("list", ["--json"])

        assert result == 0
        assert captured["db_path"] == BACH_DB
        assert captured["args"] == ["list", "--json"]


# ═══════════════════════════════════════════════════════════════
# list_paths()
# ═══════════════════════════════════════════════════════════════


class TestListPaths:
    def test_returns_dict(self):
        paths = list_paths()
        assert isinstance(paths, dict)

    def test_all_values_are_strings(self):
        paths = list_paths()
        for v in paths.values():
            assert isinstance(v, str)

    def test_contains_core_paths(self):
        paths = list_paths()
        assert "root" in paths
        assert "system" in paths
        assert "data" in paths
        assert "db" in paths

    def test_at_least_30_entries(self):
        paths = list_paths()
        assert len(paths) >= 30


# ═══════════════════════════════════════════════════════════════
# get_tool_path()
# ═══════════════════════════════════════════════════════════════


class TestGetToolPath:
    def test_nonexistent_tool_returns_none(self):
        result = get_tool_path("nonexistent_tool_xyz_12345")
        assert result is None

    def test_adds_py_extension(self):
        result = get_tool_path("nonexistent_tool_xyz_12345")
        assert result is None

    def test_existing_tool_in_tools_dir(self):
        if (TOOLS_DIR / "file_cleaner.py").exists():
            result = get_tool_path("file_cleaner")
            assert result is not None
            assert result.name == "file_cleaner.py"

    def test_existing_tool_with_extension(self):
        if (TOOLS_DIR / "file_cleaner.py").exists():
            result = get_tool_path("file_cleaner.py")
            assert result is not None


# ═══════════════════════════════════════════════════════════════
# get_partner_dir()
# ═══════════════════════════════════════════════════════════════


class TestGetPartnerDir:
    def test_claude(self):
        assert get_partner_dir("claude") == PARTNERS_DIR / "claude"

    def test_gemini(self):
        assert get_partner_dir("gemini") == PARTNERS_DIR / "gemini"

    def test_arbitrary(self):
        assert get_partner_dir("test") == PARTNERS_DIR / "test"


# ═══════════════════════════════════════════════════════════════
# get_belege_path()
# ═══════════════════════════════════════════════════════════════


class TestGetBelegePath:
    def test_default(self):
        result = get_belege_path()
        assert "belege" in str(result).lower()

    def test_with_anbieter(self):
        result = get_belege_path("amazon")
        assert str(result).endswith("amazon")


# ═══════════════════════════════════════════════════════════════
# resolve()
# ═══════════════════════════════════════════════════════════════


class TestResolve:
    def test_resolve_from_system(self):
        result = resolve("tools/file_cleaner.py")
        assert result == BP_SYSTEM_ROOT / "tools" / "file_cleaner.py"

    def test_resolve_from_root(self):
        result = resolve("system/hub/bach_paths.py", from_root=True)
        assert result == BACH_ROOT / "system" / "hub" / "bach_paths.py"

    def test_resolve_default_is_system(self):
        result = resolve("hub")
        assert result == BP_SYSTEM_ROOT / "hub"


# ═══════════════════════════════════════════════════════════════
# DEPLOYMENT MODE
# ═══════════════════════════════════════════════════════════════

from hub.bach_paths import (
    get_deployment_mode,
    is_server_mode,
    is_onedrive_mode,
    DEPLOYMENT_MODE,
)


class TestDeploymentMode:
    def test_mode_is_string(self):
        assert isinstance(get_deployment_mode(), str)

    def test_mode_in_valid_set(self):
        assert get_deployment_mode() in {"server", "onedrive", "local"}

    def test_constant_matches_function(self):
        assert DEPLOYMENT_MODE == get_deployment_mode()

    def test_is_server_mode_returns_bool(self):
        assert isinstance(is_server_mode(), bool)

    def test_is_onedrive_mode_returns_bool(self):
        assert isinstance(is_onedrive_mode(), bool)

    def test_server_mode_with_env(self, monkeypatch):
        monkeypatch.setenv("BACH_SERVER_MODE", "1")
        assert get_deployment_mode() == "server"
        assert is_server_mode() is True

    def test_server_mode_with_host_env(self, monkeypatch):
        monkeypatch.setenv("BACH_HOST", "somehost")
        assert get_deployment_mode() == "server"

    def test_onedrive_or_local_without_env(self, monkeypatch):
        monkeypatch.delenv("BACH_SERVER_MODE", raising=False)
        monkeypatch.delenv("BACH_HOST", raising=False)
        mode = get_deployment_mode()
        assert mode in {"onedrive", "local"}
